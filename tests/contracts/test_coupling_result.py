"""Serialization round-trip, shape, and model-level-invariant tests for the
CouplingResult contract models (T1.5B, twice-corrected). Parser-behavior
tests live in tests/parsers/test_pydoublet_parser.py; this file exercises
the typed models themselves, including tamper/invariant rejection.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.contracts import (
    CouplingWarning,
    FieldProvenance,
    PyDoubletBoundaryResult,
    PyDoubletCouplingFailure,
    PyDoubletCouplingResult,
    SourceProvenance,
    parse_coupling_result_json,
)
from r3chain_geothermal.contracts.coupling_result import CONTRACT_SCHEMA_VERSION
from r3chain_geothermal.errors import (
    LEGACY_PYDOUBLET_RUN_COUNT_METADATA_CORRECTED,
    LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK,
    FailureCode,
)
from r3chain_geothermal.hashing import canonical_raw_result_sha256
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "pydoublet"
_REPAIRED_PATH = _FIXTURES_DIR / "repaired_result.json"
_PRISTINE_PATH = _FIXTURES_DIR / "raw_result.json"

_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_KNOWN_PRISTINE_COMMIT = "4fb328d"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _sample_ok() -> PyDoubletCouplingResult:
    """A genuinely valid PyDoubletCouplingResult, produced by the real
    parser against the real repaired fixture -- guarantees every model-level
    invariant holds by construction, rather than hand-maintaining a
    fixture-like object that could silently drift out of sync with the
    invariants."""
    raw = _load(_REPAIRED_PATH)
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert isinstance(result, PyDoubletCouplingResult)
    return result


def _sample_ok_legacy_corrected() -> PyDoubletCouplingResult:
    """A success variant exercising the legacy_corrected extraction mode
    (run-count correction) and both legacy warnings together -- produced by
    the real parser against the real pristine fixture."""
    raw = _load(_PRISTINE_PATH)
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_PRISTINE_COMMIT,
        source_format_hint="known_pristine",
        calculation_mode="deterministic",
    )
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert isinstance(result, PyDoubletCouplingResult)
    assert result.field_provenance["actual_runs_completed"].extraction_mode == "legacy_corrected"
    assert len(result.warnings) == 2
    return result


def _sample_failure(failure_code: FailureCode = FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD) -> PyDoubletCouplingFailure:
    raw_result = {"simulation_results": {}}
    return PyDoubletCouplingFailure(
        failure_code=failure_code,
        message=f"sample failure for {failure_code.value}",
        source_pointer="/simulation_results/producer_wellhead_temperature_c",
        details={"field_name": "producer_wellhead_temperature_c"},
        source_provenance=SourceProvenance(source_format_hint="known_repaired", calculation_mode="deterministic"),
        raw_result_sha256=canonical_raw_result_sha256(raw_result),
        raw_result=raw_result,
        created_at=datetime.now(timezone.utc),
    )


def _strict_json_loads(text: str):
    """Decode JSON that REJECTS the non-standard NaN/Infinity/-Infinity
    constants Python's json module otherwise accepts by default."""
    def _reject(constant: str):
        raise ValueError(f"Strict JSON decoding rejects non-standard constant: {constant}")
    return json.loads(text, parse_constant=_reject)


# ── Basic contract shape ─────────────────────────────────────────────────
def test_contract_schema_version_is_1_0_0():
    assert CONTRACT_SCHEMA_VERSION == "1.0.0"
    assert _sample_ok().contract_schema_version == "1.0.0"
    assert _sample_failure().contract_schema_version == "1.0.0"


def test_ok_round_trip_via_model_dump_json_and_parse_coupling_result_json():
    original = _sample_ok()
    restored = parse_coupling_result_json(original.model_dump_json())
    assert isinstance(restored, PyDoubletCouplingResult)
    assert restored == original


def test_failure_round_trip_via_model_dump_json_and_parse_coupling_result_json():
    original = _sample_failure()
    restored = parse_coupling_result_json(original.model_dump_json())
    assert isinstance(restored, PyDoubletCouplingFailure)
    assert restored == original


def test_ok_round_trip_via_model_validate_json_directly():
    original = _sample_ok()
    restored = PyDoubletCouplingResult.model_validate_json(original.model_dump_json())
    assert restored == original


def test_failure_round_trip_via_model_validate_json_directly():
    original = _sample_failure()
    restored = PyDoubletCouplingFailure.model_validate_json(original.model_dump_json())
    assert restored == original


def test_parse_coupling_result_json_dispatches_on_status_discriminator():
    ok_json = _sample_ok().model_dump_json()
    failure_json = _sample_failure().model_dump_json()
    assert json.loads(ok_json)["status"] == "success"
    assert json.loads(failure_json)["status"] == "failure"
    assert isinstance(parse_coupling_result_json(ok_json), PyDoubletCouplingResult)
    assert isinstance(parse_coupling_result_json(failure_json), PyDoubletCouplingFailure)


def test_parse_coupling_result_json_uses_pydantic_discriminated_union():
    from pydantic import TypeAdapter
    adapter = TypeAdapter(PyDoubletBoundaryResult)
    ok = _sample_ok()
    restored = adapter.validate_json(ok.model_dump_json())
    assert isinstance(restored, PyDoubletCouplingResult)
    assert restored == ok


def test_parse_coupling_result_json_rejects_unrecognized_status():
    bad_json = json.dumps({"status": "something_else"})
    with pytest.raises(Exception):
        parse_coupling_result_json(bad_json)


def test_models_are_frozen():
    ok = _sample_ok()
    with pytest.raises(Exception):
        ok.actual_runs_completed = 2  # type: ignore[misc]
    failure = _sample_failure()
    with pytest.raises(Exception):
        failure.message = "changed"  # type: ignore[misc]


def test_models_forbid_extra_fields():
    from r3chain_geothermal.contracts import NormalizedQuantity
    with pytest.raises(Exception):
        NormalizedQuantity(value=1.0, unit="kW", extra_field="not allowed")  # type: ignore[call-arg]


def test_source_provenance_defaults():
    provenance = SourceProvenance()
    assert provenance.source_format_hint == "unknown"
    assert provenance.source_pydoublet_commit is None
    assert provenance.calculation_mode == "unknown"
    assert provenance.scenario_identifier is None


def test_source_provenance_accepts_calculation_mode_and_scenario_identifier():
    provenance = SourceProvenance(calculation_mode="deterministic", scenario_identifier="My Scenario")
    assert provenance.calculation_mode == "deterministic"
    assert provenance.scenario_identifier == "My Scenario"


def test_ok_and_failure_both_serialize_raw_result_as_plain_dict():
    ok = _sample_ok()
    payload = json.loads(ok.model_dump_json())
    assert isinstance(payload["raw_result"], dict)
    failure = _sample_failure()
    payload = json.loads(failure.model_dump_json())
    assert isinstance(payload["raw_result"], dict)


def test_field_provenance_legacy_corrected_mode_round_trips():
    original = _sample_ok_legacy_corrected()
    restored = PyDoubletCouplingResult.model_validate_json(original.model_dump_json())
    assert restored == original
    entry = restored.field_provenance["actual_runs_completed"]
    assert entry.extraction_mode == "legacy_corrected"
    assert entry.transformation == "legacy_deterministic_run_count_metadata_correction"
    assert entry.raw_reported_value == 1000
    assert entry.conversion_factor is None
    assert len(restored.warnings) == 2


# ── Strict-JSON round trip for every success/failure variant ───────────────
_ALL_FAILURE_CODES = list(FailureCode)


def test_all_failure_codes_are_covered_by_the_strict_round_trip_matrix():
    assert len(_ALL_FAILURE_CODES) >= 8  # the twice-corrected T1.5B set


@pytest.mark.parametrize("failure_code", _ALL_FAILURE_CODES)
def test_strict_json_round_trip_for_every_failure_code(failure_code):
    original = _sample_failure(failure_code)
    dumped = original.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["failure_code"] == failure_code.value
    restored = parse_coupling_result_json(dumped)
    assert isinstance(restored, PyDoubletCouplingFailure)
    assert restored == original


@pytest.mark.parametrize("sample_factory", [_sample_ok, _sample_ok_legacy_corrected])
def test_strict_json_round_trip_for_success_variants(sample_factory):
    original = sample_factory()
    dumped = original.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["status"] == "success"
    restored = parse_coupling_result_json(dumped)
    assert isinstance(restored, PyDoubletCouplingResult)
    assert restored == original


def test_none_raw_result_sha256_and_raw_result_serialize_as_json_null():
    failure = PyDoubletCouplingFailure(
        failure_code=FailureCode.PYDOUBLET_NON_CONVERGENCE,
        message="no result",
        source_provenance=SourceProvenance(),
        raw_result_sha256=None,
        raw_result=None,
        created_at=datetime.now(timezone.utc),
    )
    payload = _strict_json_loads(failure.model_dump_json())
    assert payload["raw_result_sha256"] is None
    assert payload["raw_result"] is None
    restored = parse_coupling_result_json(failure.model_dump_json())
    assert restored == failure


# ── Model-level invariant / tamper-rejection tests (second correction round) ──
def _valid_ok_payload() -> dict:
    return json.loads(_sample_ok().model_dump_json())


def test_tamper_negative_mass_flow_is_rejected_on_direct_deserialization():
    payload = _valid_ok_payload()
    payload["geothermal_brine_mass_flow_kg_s"]["value"] = -1.0
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_zero_heat_capacity_is_rejected():
    payload = _valid_ok_payload()
    payload["geothermal_brine_specific_heat_capacity_j_kg_k"]["value"] = 0.0
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_zero_raw_thermal_power_is_rejected():
    payload = _valid_ok_payload()
    payload["raw_geothermal_thermal_power_kw"]["value"] = 0.0
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_negative_pump_power_is_rejected():
    payload = _valid_ok_payload()
    payload["doublet_pump_electric_power_kw"]["value"] = -1.0
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_zero_cop_is_rejected():
    payload = _valid_ok_payload()
    payload["raw_cop_dimensionless"]["value"] = 0.0
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_actual_runs_completed_zero_is_rejected():
    payload = _valid_ok_payload()
    payload["actual_runs_completed"] = 0
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_wrong_unit_is_rejected():
    payload = _valid_ok_payload()
    payload["producer_wellhead_temperature_c"]["unit"] = "degF"  # required unit is degC
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_wrong_unit_on_mass_flow_is_rejected():
    payload = _valid_ok_payload()
    payload["geothermal_brine_mass_flow_kg_s"]["unit"] = "L/s"  # required unit is kg/s
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_incorrect_raw_hash_is_rejected():
    payload = _valid_ok_payload()
    payload["raw_result_sha256"] = "0" * 64  # syntactically valid hex, but wrong
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_malformed_raw_hash_is_rejected():
    payload = _valid_ok_payload()
    payload["raw_result_sha256"] = "not-64-hex-chars"
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_uppercase_raw_hash_is_rejected():
    payload = _valid_ok_payload()
    payload["raw_result_sha256"] = payload["raw_result_sha256"].upper()  # must be lowercase
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_incorrect_result_identifier_is_rejected():
    payload = _valid_ok_payload()
    payload["result_identifier"] = "pydoublet-result-0000000000000000"
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_missing_field_provenance_entry_is_rejected():
    payload = _valid_ok_payload()
    del payload["field_provenance"]["actual_runs_completed"]
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_extra_field_provenance_entry_is_rejected():
    payload = _valid_ok_payload()
    payload["field_provenance"]["unexpected_extra_field"] = copy.deepcopy(
        payload["field_provenance"]["actual_runs_completed"]
    )
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_raw_result_modified_without_updating_hash_is_rejected():
    payload = _valid_ok_payload()
    payload["raw_result"]["simulation_results"]["producer_wellhead_temperature_c"] = -999.0
    # raw_result_sha256 left as-is -- now inconsistent with raw_result.
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_tamper_blank_scenario_identifier_is_rejected():
    payload = _valid_ok_payload()
    payload["scenario_identifier"] = "   "
    with pytest.raises(ValidationError):
        parse_coupling_result_json(json.dumps(payload))


def test_valid_payload_round_trips_cleanly_as_a_control():
    """Sanity control: the untouched valid payload must NOT raise, proving
    the tamper tests above fail because of the specific mutation, not
    because _valid_ok_payload() itself is invalid."""
    payload = _valid_ok_payload()
    restored = parse_coupling_result_json(json.dumps(payload))
    assert isinstance(restored, PyDoubletCouplingResult)


def test_direct_construction_with_negative_quantity_is_rejected():
    """Model-level invariants apply to direct Python construction too, not
    only JSON deserialization."""
    base = _sample_ok()
    from r3chain_geothermal.contracts import NormalizedQuantity
    kwargs = base.model_dump(mode="python")
    kwargs["geothermal_brine_mass_flow_kg_s"] = NormalizedQuantity(value=-5.0, unit="kg/s")
    with pytest.raises(ValidationError):
        PyDoubletCouplingResult(**kwargs)


# ── Failure-side hash-consistency invariant ─────────────────────────────────
def test_failure_hash_consistency_rejects_mismatched_raw_result_and_hash():
    with pytest.raises(ValidationError):
        PyDoubletCouplingFailure(
            failure_code=FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD,
            message="tampered",
            source_provenance=SourceProvenance(),
            raw_result_sha256="0" * 64,
            raw_result={"simulation_results": {}},
            created_at=datetime.now(timezone.utc),
        )


def test_failure_hash_consistency_allows_both_none():
    failure = PyDoubletCouplingFailure(
        failure_code=FailureCode.PYDOUBLET_NON_CONVERGENCE,
        message="no result",
        source_provenance=SourceProvenance(),
        raw_result_sha256=None,
        raw_result=None,
        created_at=datetime.now(timezone.utc),
    )
    assert failure.raw_result is None and failure.raw_result_sha256 is None


def test_failure_hash_consistency_allows_hash_present_result_none():
    """raw_result_sha256 alone (raw_result=None) must not trigger the
    both-present hash-consistency check."""
    failure = PyDoubletCouplingFailure(
        failure_code=FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE,
        message="NaN in raw_result",
        source_provenance=SourceProvenance(),
        raw_result_sha256=None,
        raw_result=None,
        created_at=datetime.now(timezone.utc),
    )
    assert failure.raw_result is None
