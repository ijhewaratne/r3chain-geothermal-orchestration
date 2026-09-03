"""PyDoubletCouplingResult -- the versioned, typed boundary between raw
PyDoublet output and everything downstream (T1.5B; see ADR-002 and the
approved T1.5 plan, corrected across two T1.5B correction rounds).

Exposes only RAW geothermal quantities (brine flow, brine heat capacity, raw
geothermal thermal power, doublet pump electricity, COP) -- never DH-water
flow, DH-deliverable heat, or DH-pump electricity. Those later quantities are
a separate, not-yet-implemented adapter's responsibility (ADR-001 D3).

Public boundary names:
    PyDoubletCouplingResult -- status="success"
    PyDoubletCouplingFailure -- status="failure"
    PyDoubletBoundaryResult -- Annotated discriminated union of the two,
        dispatched on `status` via Pydantic's real discriminated-union
        machinery (a TypeAdapter), not a manually-inspected plain Union.
`parse_pydoublet_result()` (parsers/pydoublet_parser.py) always returns one
or the other, never raises for any recognized failure mode.

Second correction round: PyDoubletCouplingResult now enforces its own
invariants at the model level (model_validator), so a manually-constructed
or tampered instance deserialized via the discriminated union is rejected
just as strictly as the parser's own output -- the contract is not merely
"whatever the parser happened to produce."
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..errors import FailureCode
from ..hashing import canonical_raw_result_sha256

CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""The coupling-CONTRACT schema version -- independent of this package's own
__version__ (r3chain_geothermal, currently 0.1.0). The contract shape can
version separately from the package that implements it."""

RESULT_IDENTIFIER_PREFIX = "pydoublet-result-"
RESULT_IDENTIFIER_HASH_LENGTH = 16
"""result_identifier = f"{RESULT_IDENTIFIER_PREFIX}{raw_result_sha256[:RESULT_IDENTIFIER_HASH_LENGTH]}".
Defined here (not in parsers/pydoublet_parser.py) because
PyDoubletCouplingResult's own model-level validator enforces this
convention -- the parser imports these same constants rather than
duplicating them, so there is exactly one source of truth."""

_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_UNITS: dict[str, str] = {
    "producer_wellhead_temperature_c": "degC",
    "geothermal_brine_hx_outlet_temperature_c": "degC",
    "geothermal_brine_mass_flow_kg_s": "kg/s",
    "geothermal_brine_specific_heat_capacity_j_kg_k": "J/(kg*K)",
    "raw_geothermal_thermal_power_kw": "kW",
    "doublet_pump_electric_power_kw": "kW",
    "raw_cop_dimensionless": "dimensionless",
}
_REQUIRED_FIELD_PROVENANCE_KEYS = frozenset(_REQUIRED_UNITS) | {"actual_runs_completed"}


class SourceProvenance(BaseModel):
    """Caller-supplied, explicit information about where a raw PyDoublet
    result came from. NEVER inferred by the parser from the raw result's own
    structure alone -- absence of the named temperature field is not, by
    itself, evidence of anything about provenance, and a known commit or
    format hint alone must never imply a calculation mode.

    Args:
        source_pydoublet_commit: The PyDoublet git commit that produced this
            raw result, if known (e.g. "0d649c3e6930d342dac03654d57776e134c2d0b9").
            None if genuinely unknown to the caller.
        source_format_hint: Explicit trust classification supplied by the
            caller/orchestrator:
                "known_pristine" -- caller knows this is the pre-repair
                    (T1.3-era) raw-result shape (e.g. loading the committed
                    fixtures/pydoublet/raw_result.json).
                "known_repaired" -- caller knows this came from a
                    post-T1.4A-repair PyDoublet run.
                "unknown" (default) -- caller has no trusted classification;
                    the parser must not guess one from the JSON's own shape.
        calculation_mode: Explicit, caller-asserted calculation mode.
            T1.5 supports only "deterministic" -- "monte_carlo" and
            "unknown" (the default) both fail with
            PYDOUBLET_UNSUPPORTED_CALCULATION_MODE. This is deliberately
            NEVER derived from source_format_hint or source_pydoublet_commit;
            those identify format/origin, not calculation mode.
        scenario_identifier: Optional caller-supplied scenario identifier,
            used only as a fallback when the raw result itself has no
            /metadata/simulation_name field. Never a source commit hash or
            format-hint string -- see parsers/pydoublet_parser.py::
            _resolve_scenario_identifier.

    Note (docs/issues/mcp-input-provenance-enforcement.md, IP-001):
    exact-hash provenance enforcement ("expected_raw_sha256") is
    deliberately NOT a field on this model. SourceProvenance is embedded
    verbatim into WorkflowAuditRecord and therefore into every
    workflow_result.json/audit.json's `normalize_for_scientific_hash`-based
    bundle_scientific_sha256 -- adding any new field here, even an
    optional one defaulting to `None`, changes that hash for EVERY
    existing caller (an explicit `null` still changes the canonical JSON
    bytes), which would have silently rebaselined
    tests/mcp_client/test_wheel_install.py and
    tests/mcp_server/test_mcp_protocol.py's pinned
    `bundle_scientific_sha256` values with no scientific content actually
    changing (confirmed by directly attempting this design first; see
    docs/decisions/decision-register.md IMPL-001 for the measured before/
    after). `expected_raw_sha256` is instead a keyword-only parameter on
    `parse_pydoublet_result()`/`run_workflow()` themselves (IP-001's own
    "or the validation request" alternative) -- a pure request-time gate,
    never audited state, so it cannot affect any hash of previously-shaped
    output.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_pydoublet_commit: str | None = None
    source_format_hint: Literal["known_pristine", "known_repaired", "unknown"] = "unknown"
    calculation_mode: Literal["deterministic", "monte_carlo", "unknown"] = "unknown"
    scenario_identifier: str | None = None


class NormalizedQuantity(BaseModel):
    """One normalized physical quantity: a value paired with its unit."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    unit: str


class FieldProvenance(BaseModel):
    """Per-field audit trail for one normalized quantity.

    Args:
        source_pointer: RFC 6901 JSON Pointer into raw_result this value was
            extracted from.
        source_unit: The unit of the value at source_pointer, in the raw
            PyDoublet result.
        normalized_unit: The unit of the corresponding NormalizedQuantity.
        conversion_factor: value_in_normalized_unit = raw_value * conversion_factor,
            for a true unit conversion. None when the field underwent a
            metadata *correction* rather than a unit conversion (see
            transformation/raw_reported_value below) -- those two concepts
            are kept distinct rather than overloading conversion_factor.
        extraction_mode: "primary" if source_pointer is the named/primary
            field; "legacy" if the ADR-002 index-based fallback was used;
            "legacy_corrected" if a known legacy metadata defect was
            detected and the normalized value was corrected rather than
            merely re-pointed (see transformation).
        transformation: Machine-readable name of the correction applied,
            when extraction_mode == "legacy_corrected" (e.g.
            "legacy_deterministic_run_count_metadata_correction"). None
            otherwise.
        raw_reported_value: The raw, uncorrected value as originally
            reported at source_pointer, preserved for audit when
            extraction_mode == "legacy_corrected". None otherwise.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_pointer: str
    source_unit: str
    normalized_unit: str
    conversion_factor: float | None = None
    extraction_mode: Literal["primary", "legacy", "legacy_corrected"]
    transformation: str | None = None
    raw_reported_value: Any | None = None


class CouplingWarning(BaseModel):
    """Structured warning, same shape convention as pandapipesAI's
    core/contract.py Warning model and ADR-002's fallback-warning
    requirement."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    affects: list[str] = Field(default_factory=list)


class PyDoubletCouplingResult(BaseModel):
    """A successfully parsed and validated PyDoublet coupling result.

    Exposes only RAW geothermal quantities -- see module docstring. Every
    quantity is a NormalizedQuantity (value + unit); field_provenance
    carries the audit trail (source pointer, source/normalized unit,
    conversion factor, primary/legacy/legacy_corrected extraction mode) for
    each one.

    Identity fields -- kept strictly distinct:
        scenario_identifier identifies the SCENARIO -- stable across
            repeated executions of the same PyDoublet configuration, sourced
            from the verified /metadata/simulation_name field (or, when that
            field is absent, from a caller-supplied trusted
            SourceProvenance.scenario_identifier -- never from a source
            commit hash, a format-hint string, or a raw-result content hash,
            which changes on every execution due to the embedded timestamp).
        result_identifier identifies THIS SPECIFIC raw result instance,
            derived from the canonical raw-result SHA-256
            ("pydoublet-result-<first 16 hash hex chars>"). Two executions
            of the identical scenario differing only in timestamp share the
            same scenario_identifier but have different result_identifier
            values.
        source_timestamp preserves PyDoublet's own /metadata/timestamp
            verbatim, when present, distinct from this contract's own
            created_at.

    Model-level invariants (enforced on every construction/deserialization,
    not only by the parser -- second T1.5B correction round): every
    quantity value is finite and matches the unit required for its named
    field; mass flow, heat capacity, raw thermal power and COP are > 0; pump
    power is >= 0; actual_runs_completed >= 1; scenario_identifier is
    non-empty; raw_result_sha256 is exactly 64 lowercase hex characters;
    result_identifier matches RESULT_IDENTIFIER_PREFIX + the first
    RESULT_IDENTIFIER_HASH_LENGTH characters of raw_result_sha256; the
    canonical hash recomputed from raw_result equals raw_result_sha256;
    field_provenance contains exactly the required normalized-field keys.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_schema_version: Literal["1.0.0"] = CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"
    source_provenance: SourceProvenance
    scenario_identifier: str
    result_identifier: str
    source_timestamp: str | None = None
    calculation_mode: Literal["deterministic"] = "deterministic"

    producer_wellhead_temperature_c: NormalizedQuantity
    geothermal_brine_hx_outlet_temperature_c: NormalizedQuantity
    geothermal_brine_mass_flow_kg_s: NormalizedQuantity
    geothermal_brine_specific_heat_capacity_j_kg_k: NormalizedQuantity
    raw_geothermal_thermal_power_kw: NormalizedQuantity
    doublet_pump_electric_power_kw: NormalizedQuantity
    raw_cop_dimensionless: NormalizedQuantity

    actual_runs_completed: int

    field_provenance: dict[str, FieldProvenance]
    warnings: list[CouplingWarning] = Field(default_factory=list)

    raw_result_sha256: str
    raw_result: dict[str, Any]

    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "PyDoubletCouplingResult":
        errors: list[str] = []

        for field_name, expected_unit in _REQUIRED_UNITS.items():
            quantity: NormalizedQuantity = getattr(self, field_name)
            if not math.isfinite(quantity.value):
                errors.append(f"{field_name}.value must be finite, got {quantity.value!r}")
            if quantity.unit != expected_unit:
                errors.append(f"{field_name}.unit must be {expected_unit!r}, got {quantity.unit!r}")

        if self.geothermal_brine_mass_flow_kg_s.value <= 0:
            errors.append("geothermal_brine_mass_flow_kg_s.value must be > 0")
        if self.geothermal_brine_specific_heat_capacity_j_kg_k.value <= 0:
            errors.append("geothermal_brine_specific_heat_capacity_j_kg_k.value must be > 0")
        if self.raw_geothermal_thermal_power_kw.value <= 0:
            errors.append("raw_geothermal_thermal_power_kw.value must be > 0")
        if self.doublet_pump_electric_power_kw.value < 0:
            errors.append("doublet_pump_electric_power_kw.value must be >= 0")
        if self.raw_cop_dimensionless.value <= 0:
            errors.append("raw_cop_dimensionless.value must be > 0")
        if self.actual_runs_completed < 1:
            errors.append("actual_runs_completed must be >= 1")
        if not self.scenario_identifier.strip():
            errors.append("scenario_identifier must be non-empty")

        if not _HEX64_PATTERN.match(self.raw_result_sha256):
            errors.append("raw_result_sha256 must be exactly 64 lowercase hexadecimal characters")
        else:
            expected_result_identifier = (
                f"{RESULT_IDENTIFIER_PREFIX}{self.raw_result_sha256[:RESULT_IDENTIFIER_HASH_LENGTH]}"
            )
            if self.result_identifier != expected_result_identifier:
                errors.append(
                    f"result_identifier {self.result_identifier!r} does not match the "
                    f"expected {expected_result_identifier!r} derived from raw_result_sha256"
                )
            try:
                recomputed = canonical_raw_result_sha256(self.raw_result)
            except (ValueError, TypeError) as exc:
                errors.append(f"raw_result is not canonically hashable: {exc}")
            else:
                if recomputed != self.raw_result_sha256:
                    errors.append(
                        "raw_result_sha256 does not match the canonical hash recomputed from raw_result"
                    )

        actual_keys = set(self.field_provenance.keys())
        if actual_keys != _REQUIRED_FIELD_PROVENANCE_KEYS:
            missing = sorted(_REQUIRED_FIELD_PROVENANCE_KEYS - actual_keys)
            extra = sorted(actual_keys - _REQUIRED_FIELD_PROVENANCE_KEYS)
            errors.append(
                f"field_provenance must contain exactly {sorted(_REQUIRED_FIELD_PROVENANCE_KEYS)}; "
                f"missing={missing}, extra={extra}"
            )

        if errors:
            raise ValueError("; ".join(errors))
        return self


class PyDoubletCouplingFailure(BaseModel):
    """A rejected PyDoublet coupling parse. Always carries as much
    provenance/context as could be safely determined -- see field docstrings
    for exactly when each optional field is None.

    Model-level invariant: whenever both raw_result and raw_result_sha256
    are present, raw_result_sha256 must be a valid 64-lowercase-hex-char
    canonical hash of raw_result -- the same hash-consistency guarantee the
    success contract enforces, applied symmetrically to failures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_schema_version: Literal["1.0.0"] = CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"
    failure_code: FailureCode
    message: str
    source_pointer: str | None = None
    """RFC 6901 JSON Pointer relevant to this failure, when applicable
    (e.g. which field was missing/invalid). None for failures not tied to a
    single pointer (e.g. PYDOUBLET_NON_CONVERGENCE)."""
    details: dict[str, Any] = Field(default_factory=dict)
    """Structured, failure-specific diagnostic data -- e.g. for a temperature
    mismatch: {"primary_value", "legacy_value", "absolute_difference",
    "relative_difference", "absolute_tolerance_c",
    "relative_tolerance_fraction"}; for an unrecognized schema:
    {"trust_level", "primary_present", "legacy_present",
    "missing_historical_keys", ...}; for an invalid-numeric-value failure
    caused by NaN/Infinity anywhere in raw_result:
    {"invalid_numeric_pointers": [{"pointer", "value"}, ...]}; for a
    non-JSON-native-type failure: {"non_json_native_pointers":
    [{"pointer", "type"}, ...]} -- always including the run-count-equality
    corroborating diagnostic where relevant (see parsers/pydoublet_parser.py)
    -- corroborating evidence only, never the basis for the trust decision
    itself."""
    source_provenance: SourceProvenance
    raw_result_sha256: str | None = None
    """Canonical SHA-256 of raw_result, when it could be safely computed.
    None when raw_result is None (PYDOUBLET_NON_CONVERGENCE) or when hashing
    itself failed (raw_result contained NaN/Infinity, or a non-JSON-native
    value -- the strict canonical-JSON policy refuses to hash either)."""
    raw_result: dict[str, Any] | None = None
    """The original raw result, deep-copied, when available, structurally
    valid enough to retain (a dict, even if invalid), AND safely
    JSON-serializable. None for PYDOUBLET_NON_CONVERGENCE (no raw dict to
    begin with) and for the NaN/Infinity/non-JSON-native-value cases
    (embedding such a value would force model_dump_json() to emit
    non-standard JSON or fail entirely) -- the offending pointer(s) and a
    safe textual representation are preserved in `details` instead, never a
    silently-sanitized copy that could be mistaken for the real data."""

    created_at: datetime

    @model_validator(mode="after")
    def _validate_hash_consistency(self) -> "PyDoubletCouplingFailure":
        if self.raw_result is not None and self.raw_result_sha256 is not None:
            if not _HEX64_PATTERN.match(self.raw_result_sha256):
                raise ValueError("raw_result_sha256 must be exactly 64 lowercase hexadecimal characters")
            try:
                recomputed = canonical_raw_result_sha256(self.raw_result)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"raw_result is not canonically hashable: {exc}") from exc
            if recomputed != self.raw_result_sha256:
                raise ValueError(
                    "raw_result_sha256 does not match the canonical hash recomputed from raw_result"
                )
        return self


PyDoubletBoundaryResult = Annotated[
    Union[PyDoubletCouplingResult, PyDoubletCouplingFailure],
    Field(discriminator="status"),
]
"""Real Pydantic discriminated union on the `status` literal field, resolved
via a TypeAdapter (see _boundary_result_adapter / parse_coupling_result_json)
rather than a manually-inspected plain Union."""

_boundary_result_adapter: TypeAdapter = TypeAdapter(PyDoubletBoundaryResult)


def parse_coupling_result_json(json_str: str) -> PyDoubletBoundaryResult:
    """Deserialize a JSON string produced by either model's
    model_dump_json() back into the correct typed model, using Pydantic's
    discriminated-union validation (dispatch on the "status" field, PLUS
    full model-level invariant re-validation). Full round-trip fidelity:
    parse_coupling_result_json(x.model_dump_json()) == x for any valid
    PyDoubletBoundaryResult x; a tampered payload raises
    pydantic.ValidationError rather than silently deserializing.
    """
    return _boundary_result_adapter.validate_json(json_str)
