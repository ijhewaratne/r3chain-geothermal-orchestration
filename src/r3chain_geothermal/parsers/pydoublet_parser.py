"""Deterministic parser: raw PyDoublet result -> typed PyDoubletBoundaryResult.

Implements ADR-002's temperature primary/fallback policy and the T1.5
mapping table (see docs/decisions/ADR-002-pydoublet-temperature-source.md
and the approved T1.5 plan, corrected across two T1.5B correction rounds).
Never raises for any recognized failure mode -- always returns a typed
PyDoubletBoundaryResult.

Scope boundary (T1.5): exposes only RAW geothermal quantities. Does NOT
compute HX pinch, DH-deliverable heat, DH-water flow, or any pandapipes/
economics/MCP concept -- those are later, separately-approved work.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timezone
from typing import Any

from jsonpointer import JsonPointerException, resolve_pointer
from pydantic import BaseModel, ConfigDict, Field as PydanticField

from ..contracts.coupling_result import (
    RESULT_IDENTIFIER_HASH_LENGTH,
    RESULT_IDENTIFIER_PREFIX,
    CouplingWarning,
    FieldProvenance,
    NormalizedQuantity,
    PyDoubletBoundaryResult,
    PyDoubletCouplingFailure,
    PyDoubletCouplingResult,
    SourceProvenance,
)
from ..errors import (
    LEGACY_PYDOUBLET_RUN_COUNT_METADATA_CORRECTED,
    LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK,
    FailureCode,
)
from ..hashing import (
    CANONICAL_RAW_HASH_ALGORITHM_VERSION,
    canonical_raw_result_json_bytes,
    canonical_raw_result_sha256,
)

_EXPECTED_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
"""Format check for expected_raw_sha256 -- a local copy of the same
64-lowercase-hex rule contracts/coupling_result.py's own (private,
module-internal) _HEX64_PATTERN enforces, since expected_raw_sha256 is a
plain function parameter here, not a Pydantic-validated field."""

# Re-exported for backward compatibility with existing call sites/tests that
# import these two names directly from this module.
__all__ = [
    "POLICY",
    "canonical_raw_result_json_bytes",
    "canonical_raw_result_sha256",
    "parse_pydoublet_result",
]


class _ParserPolicy(BaseModel):
    """Single, validated source of truth for every pointer, warning code and
    tolerance this parser uses. Instantiated once at module import time
    (POLICY, below) -- a malformed value here (e.g. a pointer not starting
    with "/", a negative tolerance) raises pydantic.ValidationError
    immediately at import, rather than corrupting behaviour silently.

    Design note (approved for contract v1.0.0): these values are hard-coded
    Python literals bundled into this typed object, NOT read from
    config/demo_assumptions.json at runtime -- runtime dependence on the
    repository-level config is not required. Consistency with
    config/demo_assumptions.json (schema 0.4) is instead enforced by an
    explicit repo-level test (tests/parsers/test_pydoublet_parser.py::
    test_parser_policy_matches_demo_assumptions_config).

    result_identifier_prefix/result_identifier_hash_length are imported from
    contracts.coupling_result (RESULT_IDENTIFIER_PREFIX/
    RESULT_IDENTIFIER_HASH_LENGTH) rather than duplicated here, since
    PyDoubletCouplingResult's own model-level validator enforces that exact
    convention -- there is exactly one source of truth for it.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    primary_temperature_pointer: str = PydanticField(pattern=r"^/.+")
    legacy_temperature_pointer: str = PydanticField(pattern=r"^/.+")
    hx_outlet_temperature_pointer: str = PydanticField(pattern=r"^/.+")
    mass_flow_pointer: str = PydanticField(pattern=r"^/.+")
    heat_capacity_pointer: str = PydanticField(pattern=r"^/.+")
    raw_thermal_power_mw_pointer: str = PydanticField(pattern=r"^/.+")
    pump_power_kw_pointer: str = PydanticField(pattern=r"^/.+")
    cop_pointer: str = PydanticField(pattern=r"^/.+")
    actual_runs_completed_pointer: str = PydanticField(pattern=r"^/.+")
    monte_carlo_runs_pointer: str = PydanticField(pattern=r"^/.+")
    simulation_name_pointer: str = PydanticField(pattern=r"^/.+")
    timestamp_pointer: str = PydanticField(pattern=r"^/.+")

    mw_to_kw_factor: float = PydanticField(gt=0)

    temperature_agreement_absolute_tolerance_c: float = PydanticField(ge=0)
    temperature_agreement_relative_tolerance_fraction: float = PydanticField(ge=0)

    legacy_temperature_fallback_warning_code: str
    legacy_run_count_correction_warning_code: str
    legacy_run_count_correction_transformation: str

    result_identifier_prefix: str
    result_identifier_hash_length: int = PydanticField(gt=0)


POLICY = _ParserPolicy(
    primary_temperature_pointer="/simulation_results/producer_wellhead_temperature_c",
    legacy_temperature_pointer="/simulation_results/temperature_profile_c/2",
    hx_outlet_temperature_pointer="/surface_installations/heat_exchanger/exit_temperature_c",
    mass_flow_pointer="/simulation_results/mass_flow_rate_kg_per_s",
    heat_capacity_pointer="/simulation_results/heat_capacity_j_per_kg_k",
    raw_thermal_power_mw_pointer="/simulation_results/geothermal_power_mw",
    pump_power_kw_pointer="/simulation_results/required_pump_power_kw",
    cop_pointer="/simulation_results/cop_kw_per_kw",
    actual_runs_completed_pointer="/simulation_parameters/actual_runs_completed",
    monte_carlo_runs_pointer="/simulation_parameters/monte_carlo_runs",
    simulation_name_pointer="/metadata/simulation_name",
    timestamp_pointer="/metadata/timestamp",
    mw_to_kw_factor=1000.0,
    temperature_agreement_absolute_tolerance_c=1e-6,
    temperature_agreement_relative_tolerance_fraction=1e-9,
    legacy_temperature_fallback_warning_code=LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK,
    legacy_run_count_correction_warning_code=LEGACY_PYDOUBLET_RUN_COUNT_METADATA_CORRECTED,
    legacy_run_count_correction_transformation="legacy_deterministic_run_count_metadata_correction",
    result_identifier_prefix=RESULT_IDENTIFIER_PREFIX,
    result_identifier_hash_length=RESULT_IDENTIFIER_HASH_LENGTH,
)

# Convenience aliases (unchanged names from earlier implementations so
# existing call sites/tests keep working) -- all derived from POLICY, not
# independent literals, so there is exactly one place these values are set.
PRIMARY_TEMPERATURE_POINTER = POLICY.primary_temperature_pointer
LEGACY_TEMPERATURE_POINTER = POLICY.legacy_temperature_pointer
HX_OUTLET_TEMPERATURE_POINTER = POLICY.hx_outlet_temperature_pointer
MASS_FLOW_POINTER = POLICY.mass_flow_pointer
HEAT_CAPACITY_POINTER = POLICY.heat_capacity_pointer
RAW_THERMAL_POWER_MW_POINTER = POLICY.raw_thermal_power_mw_pointer
PUMP_POWER_KW_POINTER = POLICY.pump_power_kw_pointer
COP_POINTER = POLICY.cop_pointer
ACTUAL_RUNS_COMPLETED_POINTER = POLICY.actual_runs_completed_pointer
MONTE_CARLO_RUNS_POINTER = POLICY.monte_carlo_runs_pointer
SIMULATION_NAME_POINTER = POLICY.simulation_name_pointer
TIMESTAMP_POINTER = POLICY.timestamp_pointer

# Known-pristine registry (ADR-002; the T1.3 golden-capture baseline).
KNOWN_PRISTINE_COMMITS = frozenset({
    "4fb328d",
    "4fb328dc4d7e035dad13ca60c43856072acedb8b",
})
KNOWN_PRISTINE_RAW_RESULT_SHA256 = frozenset({
    "ed73b0eba885670d46a5e7871d3d3f4c12b8fedf15a9a9fb5b134586aa5bafbe",
})

# Historical (pristine, pre-T1.4C2) key sets -- reused verbatim from
# tests/test_golden_regression.py (repos/PyDoublet), the established source
# of truth for "what a well-formed legacy result looks like structurally".
_HISTORICAL_TOP_LEVEL_KEYS = frozenset({
    "metadata", "reservoir", "simulation_parameters", "simulation_results",
    "surface_installations", "wells",
})
_HISTORICAL_SIMULATION_RESULTS_KEYS = frozenset({
    "converged", "cop_kw_per_kw", "geothermal_power_mw",
    "heat_capacity_j_per_kg_k", "injector_well", "mass_flow_rate_kg_per_s",
    "pressure_profile_pa", "producer_well", "product_density_kg_per_m3",
    "pump_volume_flow_m3_per_h", "required_pump_power_kw",
    "temperature_difference_k", "temperature_profile_c",
})

_JSON_NATIVE_SCALAR_TYPES = (str, int, float, bool, type(None))

_MISSING = object()  # sentinel distinct from any real JSON value including None


class _Rejected(Exception):
    """Internal control-flow exception. Caught by parse_pydoublet_result()
    and converted into a typed PyDoubletCouplingFailure -- never escapes the
    public API."""

    def __init__(
        self, failure_code: FailureCode, message: str, *,
        source_pointer: str | None = None, details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.message = message
        self.source_pointer = source_pointer
        self.details = details or {}


def _json_pointer_escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _find_non_finite_pointers(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Recursively walk a JSON-like structure and return
    [(json_pointer, safe_text_repr), ...] for every NaN/Infinity float
    found. Used only to build a diagnosable failure -- never to silently
    substitute a value."""
    found: list[tuple[str, str]] = []
    if isinstance(obj, float) and not math.isfinite(obj):
        if math.isnan(obj):
            text = "NaN"
        else:
            text = "Infinity" if obj > 0 else "-Infinity"
        found.append((path or "/", text))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(_find_non_finite_pointers(value, f"{path}/{_json_pointer_escape(str(key))}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(_find_non_finite_pointers(value, f"{path}/{index}"))
    return found


def _find_non_json_native_pointers(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Recursively walk a JSON-like structure and return
    [(json_pointer, type_name), ...] for every value that is not a
    JSON-native type (dict/list/str/int/float/bool/None) -- e.g. a
    pathlib.Path, a set, an arbitrary object. Used to build a diagnosable
    PYDOUBLET_RESULT_VALIDATION_FAILED failure when json.dumps() would
    otherwise raise an unhandled TypeError."""
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(_find_non_json_native_pointers(value, f"{path}/{_json_pointer_escape(str(key))}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(_find_non_json_native_pointers(value, f"{path}/{index}"))
    elif not isinstance(obj, _JSON_NATIVE_SCALAR_TYPES):
        found.append((path or "/", type(obj).__name__))
    return found


def _resolve(raw: dict[str, Any], pointer: str) -> Any:
    try:
        return resolve_pointer(raw, pointer, default=_MISSING)
    except JsonPointerException:
        return _MISSING


def _require_finite_number(
    value: Any, *, pointer: str, field_name: str,
    positive: bool = False, non_negative: bool = False,
) -> float:
    if value is _MISSING:
        raise _Rejected(
            FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD,
            f"Required field '{field_name}' is missing at {pointer}.",
            source_pointer=pointer, details={"field_name": field_name},
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Rejected(
            FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE,
            f"Field '{field_name}' at {pointer} is not numeric: {value!r}.",
            source_pointer=pointer, details={"field_name": field_name, "value": repr(value)},
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise _Rejected(
            FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE,
            f"Field '{field_name}' at {pointer} is not finite: {numeric!r}.",
            source_pointer=pointer, details={"field_name": field_name, "value": numeric},
        )
    if positive and numeric <= 0:
        raise _Rejected(
            FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE,
            f"Field '{field_name}' at {pointer} must be > 0, got {numeric!r}.",
            source_pointer=pointer, details={"field_name": field_name, "value": numeric},
        )
    if non_negative and numeric < 0:
        raise _Rejected(
            FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE,
            f"Field '{field_name}' at {pointer} must be >= 0, got {numeric!r}.",
            source_pointer=pointer, details={"field_name": field_name, "value": numeric},
        )
    return numeric


def _resolve_trust_level(
    source_provenance: SourceProvenance, raw_result_sha256: str | None,
) -> str:
    """Returns "trusted_pristine", "trusted_repaired", or "unknown".

    Deliberately does NOT consider anything about the raw result's own
    temperature fields, nor calculation_mode -- trust here is purely about
    FORMAT/structure recognition (explicit caller hint, known commit, or
    known fixture hash), per the corrected legacy-recognition policy:
    absence of the primary field is never, by itself, evidence of legacy
    status. Calculation-mode confirmation is a SEPARATE, additional gate
    (see the top of parse_pydoublet_result) -- format trust never implies
    calculation-mode trust.
    """
    if source_provenance.source_format_hint == "known_pristine":
        return "trusted_pristine"
    if source_provenance.source_format_hint == "known_repaired":
        return "trusted_repaired"
    if source_provenance.source_pydoublet_commit in KNOWN_PRISTINE_COMMITS:
        return "trusted_pristine"
    if raw_result_sha256 is not None and raw_result_sha256 in KNOWN_PRISTINE_RAW_RESULT_SHA256:
        return "trusted_pristine"
    return "unknown"


def _historical_structure_present(raw: dict[str, Any]) -> tuple[bool, list[str]]:
    """Checks the well-formed-pristine-shape structural requirement (part 2
    of the corrected legacy-fallback policy). Returns (ok, missing_keys)."""
    top_level = set(raw.keys()) if isinstance(raw, dict) else set()
    sim_results = raw.get("simulation_results", {}) if isinstance(raw, dict) else {}
    sim_results_keys = set(sim_results.keys()) if isinstance(sim_results, dict) else set()

    missing_top = sorted(_HISTORICAL_TOP_LEVEL_KEYS - top_level)
    missing_sim = sorted(_HISTORICAL_SIMULATION_RESULTS_KEYS - sim_results_keys)
    missing = missing_top + [f"simulation_results/{k}" for k in missing_sim]
    return (len(missing) == 0, missing)


def _resolve_scenario_identifier(
    raw_copy: dict[str, Any], source_provenance: SourceProvenance,
) -> str:
    """Scenario identity must be stable across repeated executions of the
    SAME PyDoublet configuration. Resolution order:
        1. /metadata/simulation_name (the verified scenario-name field).
        2. source_provenance.scenario_identifier (caller-supplied, trusted
           by virtue of being an explicit SourceProvenance field).
        3. PYDOUBLET_MISSING_REQUIRED_FIELD.
    Never a source commit hash, a format-hint string, or a raw-result
    content hash -- those identify PROVENANCE or a specific RESULT
    INSTANCE, not the SCENARIO."""
    scenario_name_raw = _resolve(raw_copy, POLICY.simulation_name_pointer)
    if isinstance(scenario_name_raw, str) and scenario_name_raw.strip():
        return scenario_name_raw
    if source_provenance.scenario_identifier and source_provenance.scenario_identifier.strip():
        return source_provenance.scenario_identifier
    raise _Rejected(
        FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD,
        f"No genuine scenario-name field found at {POLICY.simulation_name_pointer} "
        "and no trusted SourceProvenance.scenario_identifier supplied to derive "
        "a scenario_identifier from.",
        source_pointer=POLICY.simulation_name_pointer,
        details={"field_name": "scenario_identifier"},
    )


def parse_pydoublet_result(
    raw_result: dict[str, Any] | None,
    *,
    source_provenance: SourceProvenance,
    expected_raw_sha256: str | None = None,
) -> PyDoubletBoundaryResult:
    """Parse a raw PyDoublet result dict into a typed PyDoubletBoundaryResult.

    Args:
        raw_result: The raw PyDoublet result (Scenario.calculate()'s return
            value), or None (non-convergence).
        source_provenance: Caller-supplied provenance -- REQUIRED, never
            inferred from raw_result's own shape. See SourceProvenance.
            source_provenance.calculation_mode must be explicitly
            "deterministic" for parsing to proceed at all -- T1.5 supports
            only deterministic coupling results.
        expected_raw_sha256: Optional exact-hash pin
            (docs/issues/mcp-input-provenance-enforcement.md, IP-001) --
            lowercase 64-hex-character SHA-256. When supplied, MUST equal
            `canonical_raw_result_sha256(raw_result)` as independently
            computed by this function -- never trusted from the caller.
            A mismatch fails PYDOUBLET_RAW_HASH_MISMATCH before any
            scientific parsing. `None` (the default) preserves the exact
            pre-existing behavior for every caller that omits it --
            deliberately NOT a field on `source_provenance` (see
            SourceProvenance's own docstring for why: it would silently
            change source_provenance_sha256/bundle_scientific_sha256 for
            every caller, not just ones using this feature).

    Returns:
        PyDoubletCouplingResult on success, PyDoubletCouplingFailure
        otherwise. Never raises for any FailureCode-covered condition.
    """
    created_at = datetime.now(timezone.utc)

    if raw_result is None:
        return PyDoubletCouplingFailure(
            failure_code=FailureCode.PYDOUBLET_NON_CONVERGENCE,
            message="PyDoublet returned None (non-convergence) -- no raw result to parse.",
            source_provenance=source_provenance,
            raw_result_sha256=None,
            raw_result=None,
            created_at=created_at,
        )

    if not isinstance(raw_result, dict):
        return PyDoubletCouplingFailure(
            failure_code=FailureCode.PYDOUBLET_RESULT_VALIDATION_FAILED,
            message=f"raw_result must be a dict or None, got {type(raw_result).__name__}.",
            source_provenance=source_provenance,
            raw_result_sha256=None,
            raw_result=None,
            created_at=created_at,
        )

    # Deep-copy BEFORE any validation/storage -- the caller's original dict
    # must never be mutated or aliased into the returned contract.
    raw_copy = copy.deepcopy(raw_result)

    try:
        raw_hash = canonical_raw_result_sha256(raw_copy)
    except ValueError:
        # NaN/Infinity present somewhere in raw_result. Never embed a
        # non-finite float in a serialized model -- record the offending
        # pointer(s) and a safe textual representation instead, and do not
        # retain raw_result at all.
        invalid_pointers = _find_non_finite_pointers(raw_copy)
        first_pointer = invalid_pointers[0][0] if invalid_pointers else None
        return PyDoubletCouplingFailure(
            failure_code=FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE,
            message=(
                "raw_result contains NaN or Infinity -- cannot compute a "
                "canonical hash or safely serialize raw_result; see "
                "details.invalid_numeric_pointers for the offending location(s)."
            ),
            source_pointer=first_pointer,
            details={
                "invalid_numeric_pointers": [
                    {"pointer": pointer, "value": text} for pointer, text in invalid_pointers
                ],
            },
            source_provenance=source_provenance,
            raw_result_sha256=None,
            raw_result=None,
            created_at=created_at,
        )
    except TypeError:
        # raw_result contains a value that is not a JSON-native type (e.g. a
        # pathlib.Path, a set, an arbitrary object) -- json.dumps() cannot
        # serialize it. Must not leak TypeError from the public API.
        non_native = _find_non_json_native_pointers(raw_copy)
        first_pointer = non_native[0][0] if non_native else None
        return PyDoubletCouplingFailure(
            failure_code=FailureCode.PYDOUBLET_RESULT_VALIDATION_FAILED,
            message=(
                "raw_result contains one or more values that are not JSON-native "
                "types -- cannot compute a canonical hash or safely serialize "
                "raw_result; see details.non_json_native_pointers for the "
                "offending location(s)."
            ),
            source_pointer=first_pointer,
            details={
                "non_json_native_pointers": [
                    {"pointer": pointer, "type": type_name} for pointer, type_name in non_native
                ],
            },
            source_provenance=source_provenance,
            raw_result_sha256=None,
            raw_result=None,
            created_at=created_at,
        )

    # ── Exact input-provenance check (IP-003) -- BEFORE any scientific
    # parsing or network calculation, and before the deterministic-mode
    # gate below, so a mismatched input never even reaches that far. The
    # server independently computed raw_hash above from the complete
    # received object; it never trusts a client-supplied "actual" hash --
    # expected_raw_sha256 is only ever compared against, never assigned
    # from. ──
    if expected_raw_sha256 is not None and not _EXPECTED_HASH_PATTERN.match(expected_raw_sha256):
        return PyDoubletCouplingFailure(
            failure_code=FailureCode.PYDOUBLET_RESULT_VALIDATION_FAILED,
            message=(
                f"expected_raw_sha256 {expected_raw_sha256!r} is not a valid 64-lowercase-hex-"
                "character SHA-256 -- cannot be checked against the calculated raw-result hash."
            ),
            details={"expected_raw_sha256": expected_raw_sha256},
            source_provenance=source_provenance,
            raw_result_sha256=raw_hash,
            raw_result=None,
            created_at=created_at,
        )

    if expected_raw_sha256 is not None and expected_raw_sha256 != raw_hash:
        return PyDoubletCouplingFailure(
            failure_code=FailureCode.PYDOUBLET_RAW_HASH_MISMATCH,
            message=(
                f"expected_raw_sha256 {expected_raw_sha256!r} does not match "
                f"the calculated canonical raw-result hash {raw_hash!r}."
            ),
            details={
                "expected_raw_sha256": expected_raw_sha256,
                "calculated_raw_sha256": raw_hash,
                "canonicalization_algorithm": "canonical_raw_result_sha256",
                "canonicalization_algorithm_version": CANONICAL_RAW_HASH_ALGORITHM_VERSION,
            },
            source_provenance=source_provenance,
            raw_result_sha256=raw_hash,
            # raw_result deliberately withheld here (unlike the successful
            # path, which retains it) -- IP-006: a provenance mismatch must
            # be diagnosable from the two hashes alone, without exposing
            # the entire raw input the caller sent.
            raw_result=None,
            created_at=created_at,
        )

    try:
        field_provenance: dict[str, FieldProvenance] = {}
        warnings: list[CouplingWarning] = []

        # ── Blanket precondition: T1.5 supports only deterministic
        # coupling results. A known commit or known format hint alone must
        # NEVER imply deterministic mode -- this is a separate, explicit
        # field the caller must assert. ──
        if source_provenance.calculation_mode != "deterministic":
            raise _Rejected(
                FailureCode.PYDOUBLET_UNSUPPORTED_CALCULATION_MODE,
                "T1.5 supports only deterministic PyDoublet coupling results; "
                f"source_provenance.calculation_mode={source_provenance.calculation_mode!r} "
                "is not confirmed deterministic.",
                details={"calculation_mode": source_provenance.calculation_mode},
            )

        scenario_identifier = _resolve_scenario_identifier(raw_copy, source_provenance)
        result_identifier = f"{POLICY.result_identifier_prefix}{raw_hash[:POLICY.result_identifier_hash_length]}"
        timestamp_raw = _resolve(raw_copy, POLICY.timestamp_pointer)
        source_timestamp = timestamp_raw if isinstance(timestamp_raw, str) else None

        # ── Temperature: primary/legacy resolution (corrected policy) ──
        primary_temp = _resolve(raw_copy, PRIMARY_TEMPERATURE_POINTER)
        legacy_temp = _resolve(raw_copy, LEGACY_TEMPERATURE_POINTER)

        trust_level = _resolve_trust_level(source_provenance, raw_hash)
        runs_equal_diagnostic = (
            _resolve(raw_copy, ACTUAL_RUNS_COMPLETED_POINTER)
            == _resolve(raw_copy, MONTE_CARLO_RUNS_POINTER)
        )

        used_legacy_temperature_fallback = False

        if primary_temp is not _MISSING:
            temperature_value = _require_finite_number(
                primary_temp, pointer=PRIMARY_TEMPERATURE_POINTER,
                field_name="producer_wellhead_temperature_c",
            )
            temp_pointer = PRIMARY_TEMPERATURE_POINTER
            temp_mode = "primary"
            if legacy_temp is not _MISSING:
                # Legacy present alongside primary: it must be a valid
                # finite number and must agree within tolerance. A present
                # but non-numeric legacy value (string/null/bool/...) is a
                # hard failure, never silently ignored.
                legacy_value = _require_finite_number(
                    legacy_temp, pointer=LEGACY_TEMPERATURE_POINTER,
                    field_name="producer_wellhead_temperature_c_legacy",
                )
                abs_diff = abs(temperature_value - legacy_value)
                agrees = math.isclose(
                    temperature_value, legacy_value,
                    rel_tol=POLICY.temperature_agreement_relative_tolerance_fraction,
                    abs_tol=POLICY.temperature_agreement_absolute_tolerance_c,
                )
                if not agrees:
                    rel_diff = abs_diff / abs(legacy_value) if legacy_value != 0 else abs_diff
                    raise _Rejected(
                        FailureCode.PYDOUBLET_NAMED_LEGACY_TEMPERATURE_MISMATCH,
                        "Primary and legacy producer wellhead temperature fields "
                        "disagree beyond the configured absolute/relative tolerance.",
                        source_pointer=PRIMARY_TEMPERATURE_POINTER,
                        details={
                            "primary_value": temperature_value, "legacy_value": legacy_value,
                            "absolute_difference": abs_diff, "relative_difference": rel_diff,
                            "absolute_tolerance_c": POLICY.temperature_agreement_absolute_tolerance_c,
                            "relative_tolerance_fraction": POLICY.temperature_agreement_relative_tolerance_fraction,
                        },
                    )
        else:
            # Primary absent. Provenance decides what happens next -- never
            # the raw result's own shape alone.
            if trust_level == "trusted_repaired":
                raise _Rejected(
                    FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD,
                    "Source provenance indicates a known-repaired PyDoublet result, "
                    "but the required named field is missing.",
                    source_pointer=PRIMARY_TEMPERATURE_POINTER,
                    details={"trust_level": trust_level, "runs_equal_diagnostic": runs_equal_diagnostic},
                )
            if trust_level != "trusted_pristine":
                raise _Rejected(
                    FailureCode.PYDOUBLET_UNRECOGNIZED_LEGACY_SCHEMA,
                    "Named temperature field is absent and source provenance is not "
                    "a recognized pristine/legacy PyDoublet result -- refusing to "
                    "silently infer legacy status.",
                    details={
                        "trust_level": trust_level,
                        "primary_present": False,
                        "legacy_present": legacy_temp is not _MISSING,
                        "runs_equal_diagnostic_corroborating_only": runs_equal_diagnostic,
                    },
                )
            # trusted_pristine: structural validation (part 2 of the policy).
            structure_ok, missing_keys = _historical_structure_present(raw_copy)
            legacy_is_finite_number = (
                legacy_temp is not _MISSING
                and isinstance(legacy_temp, (int, float))
                and not isinstance(legacy_temp, bool)
                and math.isfinite(float(legacy_temp))
            )
            if not (structure_ok and legacy_is_finite_number):
                raise _Rejected(
                    FailureCode.PYDOUBLET_UNRECOGNIZED_LEGACY_SCHEMA,
                    "Source provenance claims a recognized pristine/legacy result, "
                    "but the expected historical structure was not found.",
                    details={
                        "trust_level": trust_level,
                        "legacy_present_and_finite": legacy_is_finite_number,
                        "missing_historical_keys": missing_keys,
                        "runs_equal_diagnostic_corroborating_only": runs_equal_diagnostic,
                    },
                )
            temperature_value = float(legacy_temp)
            temp_pointer = LEGACY_TEMPERATURE_POINTER
            temp_mode = "legacy"
            used_legacy_temperature_fallback = True
            warnings.append(CouplingWarning(
                code=POLICY.legacy_temperature_fallback_warning_code,
                message=(
                    "Primary field producer_wellhead_temperature_c is absent; "
                    f"falling back to legacy pointer {LEGACY_TEMPERATURE_POINTER} "
                    "on recognized pristine/legacy provenance (ADR-002)."
                ),
                affects=["producer_wellhead_temperature_c"],
            ))

        field_provenance["producer_wellhead_temperature_c"] = FieldProvenance(
            source_pointer=temp_pointer, source_unit="degC", normalized_unit="degC",
            conversion_factor=1.0, extraction_mode=temp_mode,
        )

        # ── Remaining required quantities (all fixed pointers, no legacy path) ──
        hx_outlet_raw = _resolve(raw_copy, HX_OUTLET_TEMPERATURE_POINTER)
        hx_outlet_value = _require_finite_number(
            hx_outlet_raw, pointer=HX_OUTLET_TEMPERATURE_POINTER,
            field_name="geothermal_brine_hx_outlet_temperature_c",
        )
        field_provenance["geothermal_brine_hx_outlet_temperature_c"] = FieldProvenance(
            source_pointer=HX_OUTLET_TEMPERATURE_POINTER, source_unit="degC",
            normalized_unit="degC", conversion_factor=1.0, extraction_mode="primary",
        )

        mass_flow_raw = _resolve(raw_copy, MASS_FLOW_POINTER)
        mass_flow_value = _require_finite_number(
            mass_flow_raw, pointer=MASS_FLOW_POINTER,
            field_name="geothermal_brine_mass_flow_kg_s", positive=True,
        )
        field_provenance["geothermal_brine_mass_flow_kg_s"] = FieldProvenance(
            source_pointer=MASS_FLOW_POINTER, source_unit="kg/s",
            normalized_unit="kg/s", conversion_factor=1.0, extraction_mode="primary",
        )

        heat_capacity_raw = _resolve(raw_copy, HEAT_CAPACITY_POINTER)
        heat_capacity_value = _require_finite_number(
            heat_capacity_raw, pointer=HEAT_CAPACITY_POINTER,
            field_name="geothermal_brine_specific_heat_capacity_j_kg_k", positive=True,
        )
        field_provenance["geothermal_brine_specific_heat_capacity_j_kg_k"] = FieldProvenance(
            source_pointer=HEAT_CAPACITY_POINTER, source_unit="J/(kg*K)",
            normalized_unit="J/(kg*K)", conversion_factor=1.0, extraction_mode="primary",
        )

        raw_power_mw_raw = _resolve(raw_copy, RAW_THERMAL_POWER_MW_POINTER)
        raw_power_mw_value = _require_finite_number(
            raw_power_mw_raw, pointer=RAW_THERMAL_POWER_MW_POINTER,
            field_name="raw_geothermal_thermal_power_kw", positive=True,
        )
        raw_power_kw_value = raw_power_mw_value * POLICY.mw_to_kw_factor
        field_provenance["raw_geothermal_thermal_power_kw"] = FieldProvenance(
            source_pointer=RAW_THERMAL_POWER_MW_POINTER, source_unit="MW",
            normalized_unit="kW", conversion_factor=POLICY.mw_to_kw_factor, extraction_mode="primary",
        )

        pump_power_raw = _resolve(raw_copy, PUMP_POWER_KW_POINTER)
        pump_power_value = _require_finite_number(
            pump_power_raw, pointer=PUMP_POWER_KW_POINTER,
            field_name="doublet_pump_electric_power_kw", non_negative=True,
        )
        field_provenance["doublet_pump_electric_power_kw"] = FieldProvenance(
            source_pointer=PUMP_POWER_KW_POINTER, source_unit="kW",
            normalized_unit="kW", conversion_factor=1.0, extraction_mode="primary",
        )

        cop_raw = _resolve(raw_copy, COP_POINTER)
        cop_value = _require_finite_number(
            cop_raw, pointer=COP_POINTER, field_name="raw_cop_dimensionless", positive=True,
        )
        field_provenance["raw_cop_dimensionless"] = FieldProvenance(
            source_pointer=COP_POINTER, source_unit="dimensionless",
            normalized_unit="dimensionless", conversion_factor=1.0, extraction_mode="primary",
        )

        # ── actual_runs_completed: direct read, EXCEPT under a confirmed
        # legacy-temperature-fallback, where the known run-count metadata
        # defect must be corrected rather than trusted verbatim. Permitted
        # only because calculation_mode == "deterministic" was already
        # confirmed above -- this branch is unreachable otherwise. ──
        actual_runs_raw = _resolve(raw_copy, ACTUAL_RUNS_COMPLETED_POINTER)

        if used_legacy_temperature_fallback:
            monte_carlo_runs_raw = _resolve(raw_copy, MONTE_CARLO_RUNS_POINTER)
            signature_matches = (
                actual_runs_raw is not _MISSING and monte_carlo_runs_raw is not _MISSING
                and isinstance(actual_runs_raw, int) and not isinstance(actual_runs_raw, bool)
                and isinstance(monte_carlo_runs_raw, int) and not isinstance(monte_carlo_runs_raw, bool)
                and actual_runs_raw == monte_carlo_runs_raw
            )
            if not signature_matches:
                raise _Rejected(
                    FailureCode.PYDOUBLET_LEGACY_RUN_COUNT_AMBIGUOUS,
                    "Trusted legacy/pristine provenance confirmed, but "
                    "actual_runs_completed does not match the known "
                    "single-deterministic-run defect signature "
                    "(actual_runs_completed == monte_carlo_runs) -- refusing "
                    "to guess the true completed-run count.",
                    source_pointer=ACTUAL_RUNS_COMPLETED_POINTER,
                    details={
                        "actual_runs_completed_raw": None if actual_runs_raw is _MISSING else actual_runs_raw,
                        "monte_carlo_runs_raw": None if monte_carlo_runs_raw is _MISSING else monte_carlo_runs_raw,
                    },
                )
            actual_runs_completed = 1
            field_provenance["actual_runs_completed"] = FieldProvenance(
                source_pointer=ACTUAL_RUNS_COMPLETED_POINTER, source_unit="count",
                normalized_unit="count", conversion_factor=None,
                extraction_mode="legacy_corrected",
                transformation=POLICY.legacy_run_count_correction_transformation,
                raw_reported_value=actual_runs_raw,
            )
            warnings.append(CouplingWarning(
                code=POLICY.legacy_run_count_correction_warning_code,
                message=(
                    f"actual_runs_completed reported {actual_runs_raw} (matching "
                    "monte_carlo_runs) under recognized legacy/pristine provenance -- "
                    "the known PyDoublet legacy defect where run-count metadata was "
                    "copy-pasted from monte_carlo_runs despite exactly one "
                    "deterministic run executing. Normalized to 1."
                ),
                affects=["actual_runs_completed"],
            ))
        else:
            if actual_runs_raw is _MISSING:
                raise _Rejected(
                    FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD,
                    f"Required field 'actual_runs_completed' is missing at {ACTUAL_RUNS_COMPLETED_POINTER}.",
                    source_pointer=ACTUAL_RUNS_COMPLETED_POINTER,
                )
            if isinstance(actual_runs_raw, bool) or not isinstance(actual_runs_raw, int) or actual_runs_raw < 1:
                raise _Rejected(
                    FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE,
                    f"actual_runs_completed must be an integer >= 1, got {actual_runs_raw!r}.",
                    source_pointer=ACTUAL_RUNS_COMPLETED_POINTER,
                    details={"value": repr(actual_runs_raw)},
                )
            actual_runs_completed = int(actual_runs_raw)
            field_provenance["actual_runs_completed"] = FieldProvenance(
                source_pointer=ACTUAL_RUNS_COMPLETED_POINTER, source_unit="count",
                normalized_unit="count", conversion_factor=1.0, extraction_mode="primary",
            )

        return PyDoubletCouplingResult(
            source_provenance=source_provenance,
            scenario_identifier=scenario_identifier,
            result_identifier=result_identifier,
            source_timestamp=source_timestamp,
            producer_wellhead_temperature_c=NormalizedQuantity(value=temperature_value, unit="degC"),
            geothermal_brine_hx_outlet_temperature_c=NormalizedQuantity(value=hx_outlet_value, unit="degC"),
            geothermal_brine_mass_flow_kg_s=NormalizedQuantity(value=mass_flow_value, unit="kg/s"),
            geothermal_brine_specific_heat_capacity_j_kg_k=NormalizedQuantity(
                value=heat_capacity_value, unit="J/(kg*K)"),
            raw_geothermal_thermal_power_kw=NormalizedQuantity(value=raw_power_kw_value, unit="kW"),
            doublet_pump_electric_power_kw=NormalizedQuantity(value=pump_power_value, unit="kW"),
            raw_cop_dimensionless=NormalizedQuantity(value=cop_value, unit="dimensionless"),
            actual_runs_completed=actual_runs_completed,
            field_provenance=field_provenance,
            warnings=warnings,
            raw_result_sha256=raw_hash,
            raw_result=raw_copy,
            created_at=created_at,
        )

    except _Rejected as rejected:
        return PyDoubletCouplingFailure(
            failure_code=rejected.failure_code,
            message=rejected.message,
            source_pointer=rejected.source_pointer,
            details=rejected.details,
            source_provenance=source_provenance,
            raw_result_sha256=raw_hash,
            raw_result=raw_copy,
            created_at=created_at,
        )
