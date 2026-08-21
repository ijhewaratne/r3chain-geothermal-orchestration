"""Full test matrix for parse_pydoublet_result() (T1.5B, twice-corrected).

Fixtures are read directly from fixtures/pydoublet/*.json at the repo root
(no duplication) -- both are read-only reference material and must never be
mutated by these tests.
"""
from __future__ import annotations

import copy
import json
import math
import pathlib
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import PyDoubletCouplingFailure, PyDoubletCouplingResult, SourceProvenance
from r3chain_geothermal.errors import (
    LEGACY_PYDOUBLET_RUN_COUNT_METADATA_CORRECTED,
    LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK,
    FailureCode,
)
from r3chain_geothermal.parsers.pydoublet_parser import (
    POLICY,
    canonical_raw_result_sha256,
    parse_pydoublet_result,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "pydoublet"
_REPAIRED_PATH = _FIXTURES_DIR / "repaired_result.json"
_PRISTINE_PATH = _FIXTURES_DIR / "raw_result.json"

_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_KNOWN_PRISTINE_COMMIT = "4fb328d"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _repaired_provenance(**overrides) -> SourceProvenance:
    kwargs = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    kwargs.update(overrides)
    return SourceProvenance(**kwargs)


def _pristine_provenance(**overrides) -> SourceProvenance:
    kwargs = dict(
        source_pydoublet_commit=_KNOWN_PRISTINE_COMMIT,
        source_format_hint="known_pristine",
        calculation_mode="deterministic",
    )
    kwargs.update(overrides)
    return SourceProvenance(**kwargs)


def _unknown_provenance(**overrides) -> SourceProvenance:
    return SourceProvenance(**overrides)


# ── 1. Parse repaired/current result successfully without warnings ─────────
def test_parse_repaired_result_success_no_warnings():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    assert result.warnings == []
    assert result.field_provenance["producer_wellhead_temperature_c"].extraction_mode == "primary"
    assert result.actual_runs_completed == 1
    assert result.field_provenance["actual_runs_completed"].extraction_mode == "primary"


# ── 2. Parse recognized pristine/legacy fixture with BOTH required warnings ──
def test_parse_pristine_result_success_with_both_legacy_warnings():
    raw = _load(_PRISTINE_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_pristine_provenance())
    assert result.status == "success"
    codes = {w.code for w in result.warnings}
    assert codes == {LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK, LEGACY_PYDOUBLET_RUN_COUNT_METADATA_CORRECTED}
    assert result.field_provenance["producer_wellhead_temperature_c"].extraction_mode == "legacy"
    assert result.actual_runs_completed == 1
    run_count_provenance = result.field_provenance["actual_runs_completed"]
    assert run_count_provenance.extraction_mode == "legacy_corrected"
    assert run_count_provenance.transformation == "legacy_deterministic_run_count_metadata_correction"
    assert run_count_provenance.raw_reported_value == 1000
    assert run_count_provenance.conversion_factor is None


# ── 3. Preserve raw input exactly ───────────────────────────────────────────
@pytest.mark.parametrize("path,provenance", [
    (_REPAIRED_PATH, _repaired_provenance()), (_PRISTINE_PATH, _pristine_provenance()),
])
def test_raw_result_preserved_exactly(path, provenance):
    raw = _load(path)
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "success"
    assert result.raw_result == raw


# ── 4. Verify canonical raw-result hash ─────────────────────────────────────
@pytest.mark.parametrize("path,provenance", [
    (_REPAIRED_PATH, _repaired_provenance()), (_PRISTINE_PATH, _pristine_provenance()),
])
def test_raw_result_sha256_matches_independent_computation(path, provenance):
    raw = _load(path)
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "success"
    assert result.raw_result_sha256 == canonical_raw_result_sha256(raw)


# ── 5. Verify all source pointers and unit conversions (the T1.5 mapping table) ──
def test_field_provenance_matches_mapping_table():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    fp = result.field_provenance
    expected = {
        "producer_wellhead_temperature_c": ("/simulation_results/producer_wellhead_temperature_c", "degC", "degC", 1.0),
        "geothermal_brine_hx_outlet_temperature_c": ("/surface_installations/heat_exchanger/exit_temperature_c", "degC", "degC", 1.0),
        "geothermal_brine_mass_flow_kg_s": ("/simulation_results/mass_flow_rate_kg_per_s", "kg/s", "kg/s", 1.0),
        "geothermal_brine_specific_heat_capacity_j_kg_k": ("/simulation_results/heat_capacity_j_per_kg_k", "J/(kg*K)", "J/(kg*K)", 1.0),
        "raw_geothermal_thermal_power_kw": ("/simulation_results/geothermal_power_mw", "MW", "kW", 1000.0),
        "doublet_pump_electric_power_kw": ("/simulation_results/required_pump_power_kw", "kW", "kW", 1.0),
        "raw_cop_dimensionless": ("/simulation_results/cop_kw_per_kw", "dimensionless", "dimensionless", 1.0),
        "actual_runs_completed": ("/simulation_parameters/actual_runs_completed", "count", "count", 1.0),
    }
    for field, (pointer, src_unit, norm_unit, factor) in expected.items():
        entry = fp[field]
        assert entry.source_pointer == pointer, field
        assert entry.source_unit == src_unit, field
        assert entry.normalized_unit == norm_unit, field
        assert entry.conversion_factor == factor, field


def test_raw_thermal_power_mw_to_kw_conversion_is_correct():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    raw_mw = raw["simulation_results"]["geothermal_power_mw"]
    assert result.raw_geothermal_thermal_power_kw.value == pytest.approx(raw_mw * 1000.0, rel=0, abs=0)


# ── 6. Reject current result missing the named temperature ─────────────────
def test_repaired_shaped_result_missing_named_field_is_rejected():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    del raw["simulation_results"]["producer_wellhead_temperature_c"]
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD
    assert result.source_pointer == "/simulation_results/producer_wellhead_temperature_c"
    assert result.raw_result == raw  # still preserved even on failure


# ── 7. Reject legacy-like input with an unrecognized structure ─────────────
def test_legacy_like_input_unknown_provenance_is_rejected():
    raw = _load(_PRISTINE_PATH)  # genuinely pristine-shaped, but provenance not asserted
    result = parse_pydoublet_result(raw, source_provenance=_unknown_provenance(calculation_mode="deterministic"))
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_UNRECOGNIZED_LEGACY_SCHEMA
    assert result.details["trust_level"] == "unknown"


def test_trusted_pristine_provenance_but_broken_structure_is_rejected():
    """Provenance CLAIMS pristine, but the historical shape is missing --
    the structural half of the policy must still reject it."""
    raw = copy.deepcopy(_load(_PRISTINE_PATH))
    del raw["wells"]  # break the historical structure
    result = parse_pydoublet_result(raw, source_provenance=_pristine_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_UNRECOGNIZED_LEGACY_SCHEMA
    assert "wells" in result.details["missing_historical_keys"]


# ── 8. Reject named/legacy temperature mismatch (with the new tolerance details) ──
def test_named_legacy_temperature_mismatch_is_rejected():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["producer_wellhead_temperature_c"] += 5.0  # force disagreement
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_NAMED_LEGACY_TEMPERATURE_MISMATCH
    assert result.details["relative_difference"] > result.details["relative_tolerance_fraction"]
    assert result.details["absolute_difference"] > result.details["absolute_tolerance_c"]
    assert result.details["absolute_tolerance_c"] == POLICY.temperature_agreement_absolute_tolerance_c
    assert result.details["relative_tolerance_fraction"] == POLICY.temperature_agreement_relative_tolerance_fraction


# ── 9. Reject missing required quantities (each one individually) ──────────
@pytest.mark.parametrize("pointer_path", [
    ("surface_installations", "heat_exchanger", "exit_temperature_c"),
    ("simulation_results", "mass_flow_rate_kg_per_s"),
    ("simulation_results", "heat_capacity_j_per_kg_k"),
    ("simulation_results", "geothermal_power_mw"),
    ("simulation_results", "required_pump_power_kw"),
    ("simulation_results", "cop_kw_per_kw"),
    ("simulation_parameters", "actual_runs_completed"),
])
def test_each_required_quantity_missing_is_rejected(pointer_path):
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    node = raw
    for key in pointer_path[:-1]:
        node = node[key]
    del node[pointer_path[-1]]
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD


# ── 10. Reject NaN, infinity, negative/zero values where physically invalid ──
@pytest.mark.parametrize("pointer_path,bad_value,expected_code", [
    (("simulation_results", "mass_flow_rate_kg_per_s"), float("nan"), FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "mass_flow_rate_kg_per_s"), float("inf"), FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "mass_flow_rate_kg_per_s"), 0.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "mass_flow_rate_kg_per_s"), -1.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "heat_capacity_j_per_kg_k"), 0.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "heat_capacity_j_per_kg_k"), -1.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "geothermal_power_mw"), 0.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "geothermal_power_mw"), -1.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "cop_kw_per_kw"), 0.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "cop_kw_per_kw"), -1.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
    (("simulation_results", "required_pump_power_kw"), -1.0, FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE),
])
def test_invalid_numeric_values_are_rejected(pointer_path, bad_value, expected_code):
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    node = raw
    for key in pointer_path[:-1]:
        node = node[key]
    node[pointer_path[-1]] = bad_value
    if isinstance(bad_value, float) and not math.isfinite(bad_value):
        result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
        assert result.status == "failure"
        assert result.failure_code == FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE
        assert result.raw_result_sha256 is None
        assert result.raw_result is None
        expected_pointer = "/" + "/".join(pointer_path)
        assert result.source_pointer == expected_pointer
        pointers_found = [entry["pointer"] for entry in result.details["invalid_numeric_pointers"]]
        assert expected_pointer in pointers_found
        return
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == expected_code


def test_pump_power_zero_is_allowed_non_negative():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["required_pump_power_kw"] = 0.0
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    assert result.doublet_pump_electric_power_kw.value == 0.0


def test_actual_runs_completed_below_one_is_rejected():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_parameters"]["actual_runs_completed"] = 0
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE


# ── 11. Convert raw None to typed non-convergence failure (never raises) ───
def test_none_input_produces_typed_non_convergence_failure():
    result = parse_pydoublet_result(None, source_provenance=_unknown_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_NON_CONVERGENCE
    assert result.raw_result is None
    assert result.raw_result_sha256 is None


def test_none_input_never_raises():
    try:
        parse_pydoublet_result(None, source_provenance=_unknown_provenance())
    except Exception as exc:  # pragma: no cover - this must never happen
        pytest.fail(f"parse_pydoublet_result(None, ...) raised {exc!r} instead of returning a typed failure")


# ── 12. Prove geothermal-brine and DH-water quantities are not conflated ───
def test_no_dh_or_district_terminology_in_success_model_fields():
    field_names = set(PyDoubletCouplingResult.model_fields.keys())
    for name in field_names:
        assert "dh_" not in name and not name.startswith("dh") and "district" not in name, name


# ── Deep-copy / mutation isolation ──────────────────────────────────────────
def test_mutating_original_input_after_parse_does_not_affect_stored_result():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    original_hash = result.raw_result_sha256
    original_temp = result.producer_wellhead_temperature_c.value

    raw["simulation_results"]["producer_wellhead_temperature_c"] = -999.0
    raw["new_key_injected_after_parse"] = True

    assert result.raw_result_sha256 == original_hash
    assert result.producer_wellhead_temperature_c.value == original_temp
    assert "new_key_injected_after_parse" not in result.raw_result
    assert result.raw_result["simulation_results"]["producer_wellhead_temperature_c"] != -999.0


# ── Corrected legacy-recognition decision tree: exhaustive branch coverage ──
def test_known_repaired_provenance_with_field_present_uses_primary_regardless_of_legacy_agreement():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    assert result.field_provenance["producer_wellhead_temperature_c"].extraction_mode == "primary"


def test_run_count_equality_alone_without_trusted_provenance_is_still_rejected():
    raw = copy.deepcopy(_load(_PRISTINE_PATH))
    assert raw["simulation_parameters"]["actual_runs_completed"] == raw["simulation_parameters"]["monte_carlo_runs"]
    result = parse_pydoublet_result(raw, source_provenance=_unknown_provenance(calculation_mode="deterministic"))
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_UNRECOGNIZED_LEGACY_SCHEMA


def test_trusted_legacy_provenance_with_diverging_run_count_is_ambiguous_not_guessed():
    raw = copy.deepcopy(_load(_PRISTINE_PATH))
    raw["simulation_parameters"]["actual_runs_completed"] = 1  # no longer equals monte_carlo_runs (1000)
    result = parse_pydoublet_result(raw, source_provenance=_pristine_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_LEGACY_RUN_COUNT_AMBIGUOUS
    assert result.details["actual_runs_completed_raw"] == 1
    assert result.details["monte_carlo_runs_raw"] == 1000


def test_trusted_legacy_provenance_with_matching_defect_signature_corrects_to_one():
    raw = _load(_PRISTINE_PATH)
    assert raw["simulation_parameters"]["actual_runs_completed"] == 1000
    assert raw["simulation_parameters"]["monte_carlo_runs"] == 1000
    result = parse_pydoublet_result(raw, source_provenance=_pristine_provenance())
    assert result.status == "success"
    assert result.actual_runs_completed == 1
    assert result.field_provenance["actual_runs_completed"].raw_reported_value == 1000


# ── Requirement 1 (second correction round): calculation_mode from trusted provenance ──
def test_calculation_mode_defaults_to_unknown_and_blocks_parsing():
    raw = _load(_REPAIRED_PATH)
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
    )  # calculation_mode not set -> defaults to "unknown"
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_UNSUPPORTED_CALCULATION_MODE
    assert result.details["calculation_mode"] == "unknown"


@pytest.mark.parametrize("calculation_mode", ["monte_carlo", "unknown"])
def test_calculation_mode_not_deterministic_is_rejected_for_repaired_shape(calculation_mode):
    raw = _load(_REPAIRED_PATH)
    provenance = _repaired_provenance(calculation_mode=calculation_mode)
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_UNSUPPORTED_CALCULATION_MODE


@pytest.mark.parametrize("calculation_mode", ["monte_carlo", "unknown"])
def test_legacy_defect_signature_not_corrected_when_calculation_mode_not_deterministic(calculation_mode):
    """A legacy result with actual_runs_completed == monte_carlo_runs (the
    known defect signature) must NOT be corrected -- it must not even reach
    the run-count-correction logic -- when calculation_mode is not
    confirmed deterministic."""
    raw = _load(_PRISTINE_PATH)
    assert raw["simulation_parameters"]["actual_runs_completed"] == raw["simulation_parameters"]["monte_carlo_runs"]
    provenance = _pristine_provenance(calculation_mode=calculation_mode)
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_UNSUPPORTED_CALCULATION_MODE
    # Confirm no run-count-correction warning was ever produced (there IS no
    # success result to have warnings on -- but assert failure has no
    # 'legacy_corrected' language leaking into details either).
    assert "actual_runs_completed_raw" not in result.details


def test_source_commit_and_known_format_hint_alone_do_not_imply_deterministic_mode():
    """Both a known commit AND a known format hint are present, but
    calculation_mode is not asserted -- must still fail. Proves format/
    provenance trust never substitutes for an explicit calculation-mode
    assertion."""
    raw = _load(_REPAIRED_PATH)
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired",
        calculation_mode="unknown",
    )
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_UNSUPPORTED_CALCULATION_MODE


# ── Requirement 2 (second correction round): scenario fallback via a real identifier ──
def test_scenario_identifier_extracted_from_verified_scenario_name_pointer():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    assert result.scenario_identifier == raw["metadata"]["simulation_name"]
    assert result.scenario_identifier == "No Figures Scenario"
    assert POLICY.simulation_name_pointer == "/metadata/simulation_name"


def test_result_identifier_derived_from_canonical_hash_with_expected_prefix():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    expected = f"pydoublet-result-{result.raw_result_sha256[:16]}"
    assert result.result_identifier == expected
    assert result.result_identifier != result.scenario_identifier


def test_source_timestamp_preserved_from_raw_metadata():
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    assert result.source_timestamp == raw["metadata"]["timestamp"]


def test_two_results_differing_only_in_timestamp_share_scenario_identifier_but_not_result_identifier():
    raw_a = _load(_REPAIRED_PATH)
    raw_b = copy.deepcopy(raw_a)
    raw_b["metadata"]["timestamp"] = "2099-01-01T00:00:00.000000"
    assert raw_a != raw_b

    result_a = parse_pydoublet_result(raw_a, source_provenance=_repaired_provenance())
    result_b = parse_pydoublet_result(raw_b, source_provenance=_repaired_provenance())
    assert result_a.status == "success" and result_b.status == "success"

    assert result_a.scenario_identifier == result_b.scenario_identifier
    assert result_a.result_identifier != result_b.result_identifier
    assert result_a.raw_result_sha256 != result_b.raw_result_sha256
    assert result_a.source_timestamp != result_b.source_timestamp


def test_scenario_identifier_falls_back_to_caller_supplied_provenance_scenario_identifier():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    del raw["metadata"]["simulation_name"]
    provenance = _repaired_provenance(scenario_identifier="R3-CHAIN Doublet Scenario A")
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "success"
    assert result.scenario_identifier == "R3-CHAIN Doublet Scenario A"
    # Never a source commit, format hint, or raw-result hash.
    assert result.scenario_identifier != _KNOWN_REPAIRED_COMMIT
    assert "commit" not in result.scenario_identifier.lower()
    assert "known_repaired" not in result.scenario_identifier
    assert result.raw_result_sha256[:16] not in result.scenario_identifier


def test_scenario_identifier_fails_when_no_name_field_and_no_caller_supplied_identifier():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    del raw["metadata"]["simulation_name"]
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())  # no scenario_identifier set
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD
    assert result.source_pointer == "/metadata/simulation_name"


def test_scenario_identifier_fails_on_blank_caller_supplied_identifier():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    del raw["metadata"]["simulation_name"]
    provenance = _repaired_provenance(scenario_identifier="   ")  # blank/whitespace-only
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_MISSING_REQUIRED_FIELD


# ── Requirement 4 (second correction round): legacy temperature validated whenever present ──
@pytest.mark.parametrize("bad_legacy_value", ["76.3", None, True, False])
def test_legacy_temperature_present_but_nonnumeric_is_rejected(bad_legacy_value):
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["temperature_profile_c"][2] = bad_legacy_value
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE
    assert result.source_pointer == "/simulation_results/temperature_profile_c/2"


def test_legacy_temperature_present_and_absent_are_both_fine_when_primary_present():
    raw_with_legacy = _load(_REPAIRED_PATH)  # legacy present, agrees with primary
    result_with = parse_pydoublet_result(raw_with_legacy, source_provenance=_repaired_provenance())
    assert result_with.status == "success"

    raw_without_legacy = copy.deepcopy(_load(_REPAIRED_PATH))
    del raw_without_legacy["simulation_results"]["temperature_profile_c"]
    result_without = parse_pydoublet_result(raw_without_legacy, source_provenance=_repaired_provenance())
    assert result_without.status == "success"


# ── Requirement 5 (second correction round): canonical hashing must not leak TypeError ──
def test_pathlib_path_in_raw_result_produces_result_validation_failed_not_typeerror():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["mass_flow_rate_kg_per_s"] = pathlib.Path("/tmp/not-json-native")
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_RESULT_VALIDATION_FAILED
    assert result.raw_result_sha256 is None
    assert result.raw_result is None
    entry = result.details["non_json_native_pointers"][0]
    assert entry["pointer"] == "/simulation_results/mass_flow_rate_kg_per_s"
    assert "Path" in entry["type"]


def test_set_in_raw_result_produces_result_validation_failed():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["cop_kw_per_kw"] = {1, 2, 3}
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_RESULT_VALIDATION_FAILED
    entry = result.details["non_json_native_pointers"][0]
    assert entry["pointer"] == "/simulation_results/cop_kw_per_kw"
    assert entry["type"] == "set"


class _ArbitraryObject:
    pass


def test_arbitrary_object_in_raw_result_produces_result_validation_failed():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["cop_kw_per_kw"] = _ArbitraryObject()
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_RESULT_VALIDATION_FAILED
    entry = result.details["non_json_native_pointers"][0]
    assert entry["type"] == "_ArbitraryObject"


def test_non_json_native_failure_never_raises_typeerror_to_caller():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["cop_kw_per_kw"] = _ArbitraryObject()
    try:
        result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    except TypeError as exc:  # pragma: no cover - this must never happen
        pytest.fail(f"parse_pydoublet_result leaked TypeError: {exc!r}")
    assert result.status == "failure"


# ── NaN/Infinity failures still safe (unchanged from first correction round) ──
def test_nan_anywhere_in_raw_result_produces_safe_failure_with_pointer():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["mass_flow_rate_kg_per_s"] = float("nan")
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE
    assert result.raw_result_sha256 is None
    assert result.raw_result is None
    entry = result.details["invalid_numeric_pointers"][0]
    assert entry["pointer"] == "/simulation_results/mass_flow_rate_kg_per_s"
    assert entry["value"] == "NaN"
    dumped = result.model_dump_json()
    json.loads(dumped, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))


def test_infinity_anywhere_in_raw_result_produces_safe_failure():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["required_pump_power_kw"] = float("inf")
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_INVALID_NUMERIC_VALUE
    assert result.raw_result is None
    entry = result.details["invalid_numeric_pointers"][0]
    assert entry["pointer"] == "/simulation_results/required_pump_power_kw"
    assert entry["value"] == "Infinity"


def test_negative_infinity_gets_safe_text_representation():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    raw["simulation_results"]["required_pump_power_kw"] = float("-inf")
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    entry = result.details["invalid_numeric_pointers"][0]
    assert entry["value"] == "-Infinity"


# ── Temperature agreement uses BOTH absolute and relative tolerance ────────
def test_temperature_agreement_exact_equality_passes():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    value = raw["simulation_results"]["producer_wellhead_temperature_c"]
    raw["simulation_results"]["temperature_profile_c"][2] = value
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"


def test_temperature_agreement_difference_inside_absolute_tolerance_passes():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    value = raw["simulation_results"]["producer_wellhead_temperature_c"]
    delta = POLICY.temperature_agreement_absolute_tolerance_c * 0.5
    raw["simulation_results"]["temperature_profile_c"][2] = value + delta
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "success"
    assert math.isclose(delta, POLICY.temperature_agreement_absolute_tolerance_c * 0.5)


def test_temperature_agreement_difference_immediately_outside_tolerance_fails():
    raw = copy.deepcopy(_load(_REPAIRED_PATH))
    value = raw["simulation_results"]["producer_wellhead_temperature_c"]
    delta = POLICY.temperature_agreement_absolute_tolerance_c * 2.0
    raw["simulation_results"]["temperature_profile_c"][2] = value + delta
    result = parse_pydoublet_result(raw, source_provenance=_repaired_provenance())
    assert result.status == "failure"
    assert result.failure_code == FailureCode.PYDOUBLET_NAMED_LEGACY_TEMPERATURE_MISMATCH


def test_math_isclose_semantics_match_policy_tolerances_directly():
    a, b = 76.313, 76.313 + POLICY.temperature_agreement_absolute_tolerance_c * 0.9
    assert math.isclose(
        a, b, rel_tol=POLICY.temperature_agreement_relative_tolerance_fraction,
        abs_tol=POLICY.temperature_agreement_absolute_tolerance_c,
    )
    a, b = 76.313, 76.313 + POLICY.temperature_agreement_absolute_tolerance_c * 5.0
    assert not math.isclose(
        a, b, rel_tol=POLICY.temperature_agreement_relative_tolerance_fraction,
        abs_tol=POLICY.temperature_agreement_absolute_tolerance_c,
    )


# ── Policy/configuration traceability ────────────────────────────────────────
def test_parser_policy_matches_demo_assumptions_config():
    config = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "demo_assumptions.json").read_text()
    )
    assert config["_meta"]["schema_version"] == "0.8"

    temp_mapping = config["pydoublet"]["producer_wellhead_temperature"]
    assert temp_mapping["path_format"] == "json_pointer"
    assert temp_mapping["primary_field_path"] == POLICY.primary_temperature_pointer
    assert temp_mapping["legacy_fallback_field_path"] == POLICY.legacy_temperature_pointer
    assert temp_mapping["audit_warning_code"] == POLICY.legacy_temperature_fallback_warning_code
    assert temp_mapping["agreement_absolute_tolerance_c"] == POLICY.temperature_agreement_absolute_tolerance_c
    assert temp_mapping["agreement_relative_tolerance_fraction"] == POLICY.temperature_agreement_relative_tolerance_fraction

    identity = config["pydoublet"]["scenario_identity"]
    assert identity["scenario_name_field_path"] == POLICY.simulation_name_pointer
    assert identity["timestamp_field_path"] == POLICY.timestamp_pointer
    assert identity["result_identifier_prefix"] == POLICY.result_identifier_prefix
    assert identity["result_identifier_hash_length"] == POLICY.result_identifier_hash_length

    run_count = config["pydoublet"]["legacy_run_count_correction"]
    assert run_count["normalized_value"] == 1
    assert run_count["transformation_code"] == POLICY.legacy_run_count_correction_transformation
    assert run_count["audit_warning_code"] == POLICY.legacy_run_count_correction_warning_code
    assert run_count["ambiguous_case_failure_code"] == FailureCode.PYDOUBLET_LEGACY_RUN_COUNT_AMBIGUOUS.value

    calc_mode = config["pydoublet"]["calculation_mode_policy"]
    assert calc_mode["supported_calculation_mode"] == "deterministic"
    assert calc_mode["unsupported_calculation_mode_failure_code"] == FailureCode.PYDOUBLET_UNSUPPORTED_CALCULATION_MODE.value


def test_parser_policy_object_itself_is_validated_at_import_and_frozen():
    with pytest.raises(Exception):
        POLICY.primary_temperature_pointer = "/something/else"  # type: ignore[misc]


def test_parser_policy_rejects_malformed_construction():
    from r3chain_geothermal.parsers.pydoublet_parser import _ParserPolicy

    with pytest.raises(Exception):
        _ParserPolicy(
            primary_temperature_pointer="not-a-pointer",  # missing leading '/'
            legacy_temperature_pointer=POLICY.legacy_temperature_pointer,
            hx_outlet_temperature_pointer=POLICY.hx_outlet_temperature_pointer,
            mass_flow_pointer=POLICY.mass_flow_pointer,
            heat_capacity_pointer=POLICY.heat_capacity_pointer,
            raw_thermal_power_mw_pointer=POLICY.raw_thermal_power_mw_pointer,
            pump_power_kw_pointer=POLICY.pump_power_kw_pointer,
            cop_pointer=POLICY.cop_pointer,
            actual_runs_completed_pointer=POLICY.actual_runs_completed_pointer,
            monte_carlo_runs_pointer=POLICY.monte_carlo_runs_pointer,
            simulation_name_pointer=POLICY.simulation_name_pointer,
            timestamp_pointer=POLICY.timestamp_pointer,
            mw_to_kw_factor=POLICY.mw_to_kw_factor,
            temperature_agreement_absolute_tolerance_c=POLICY.temperature_agreement_absolute_tolerance_c,
            temperature_agreement_relative_tolerance_fraction=POLICY.temperature_agreement_relative_tolerance_fraction,
            legacy_temperature_fallback_warning_code=POLICY.legacy_temperature_fallback_warning_code,
            legacy_run_count_correction_warning_code=POLICY.legacy_run_count_correction_warning_code,
            legacy_run_count_correction_transformation=POLICY.legacy_run_count_correction_transformation,
            result_identifier_prefix=POLICY.result_identifier_prefix,
            result_identifier_hash_length=POLICY.result_identifier_hash_length,
        )
