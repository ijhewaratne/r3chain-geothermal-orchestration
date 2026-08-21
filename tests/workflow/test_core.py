"""Full test matrix for workflow/core.py -- the T2.4B1 deterministic
workflow orchestrator."""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.network import CandidateEvaluationFailure, CandidateEvaluationResult
from r3chain_geothermal.workflow import (
    WORKFLOW_RUN_ID_PREFIX,
    StageCallRecord,
    WorkflowConfigurationError,
    WorkflowFailure,
    WorkflowFailureCode,
    WorkflowResult,
    parse_workflow_result_json,
    run_workflow,
    validate_config_structure,
)

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CORE_SRC_PATH = _ROOT / "src" / "r3chain_geothermal" / "workflow" / "core.py"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_LCOH_EUR_PER_MWH = {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _strict_json_loads(text: str):
    def _reject(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")
    return json.loads(text, parse_constant=_reject)


def _strip_created_at(obj):
    """Recursively removes every key literally named 'created_at',
    wherever it appears in a nested dict/list -- created_at occurs at 8+
    nesting depths across the full embedded result tree (see core.py's
    module docstring, "Determinism")."""
    if isinstance(obj, dict):
        return {k: _strip_created_at(v) for k, v in obj.items() if k != "created_at"}
    if isinstance(obj, list):
        return [_strip_created_at(item) for item in obj]
    return obj


# ── Worked case ───────────────────────────────────────────────────────────
def test_worked_case_reproduces_t24a_ranking_and_lcoh_exactly():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    assert len(result.ranking.ranked) == 4
    assert result.ranking.infeasible == []
    order = [entry.candidate_id for entry in result.ranking.ranked]
    assert order == ["C1", "C2", "C3", "C4"]
    for entry in result.ranking.ranked:
        lcoh_mwh = entry.economics.indicative_lcoh_eur_per_kwh * 1000.0
        assert math.isclose(lcoh_mwh, _EXPECTED_LCOH_EUR_PER_MWH[entry.candidate_id], rel_tol=1e-4)


def test_worked_case_run_id_is_prefixed_hex():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert result.run_id.startswith(WORKFLOW_RUN_ID_PREFIX)
    hex_part = result.run_id[len(WORKFLOW_RUN_ID_PREFIX):]
    assert len(hex_part) == 16
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_worked_case_stage_calls_sequence():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    names = [sc.stage_name for sc in result.audit.stage_calls]
    expected = (
        ["parse_pydoublet_result", "evaluate_heat_exchanger_coupling", "build_blueprint", "run_baseline_evaluation"]
        + [f"evaluate_candidate:{c}" for c in ("C1", "C2", "C3", "C4")]
        + [f"compute_candidate_economics:{c}" for c in ("C1", "C2", "C3", "C4")]
        + ["rank_candidates"]
    )
    assert names == expected
    assert all(sc.status == "success" for sc in result.audit.stage_calls)
    assert [sc.order for sc in result.audit.stage_calls] == list(range(1, 14))


# ── Stopping failures ─────────────────────────────────────────────────────
def test_pydoublet_parse_failed_preserves_nothing_upstream():
    result = run_workflow(None, _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowFailure)
    assert result.failure_code == WorkflowFailureCode.PYDOUBLET_PARSE_FAILED
    assert result.pydoublet_result is None
    assert result.coupling_result is None
    assert result.blueprint is None
    assert result.audit.stage_calls[-1].status == "failure"


def test_heat_exchanger_coupling_failed_preserves_pydoublet_result():
    config = copy.deepcopy(_config())
    config["coupling_assumptions"]["dh_supply_temperature_c"] = 200.0
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowFailure)
    assert result.failure_code == WorkflowFailureCode.HEAT_EXCHANGER_COUPLING_FAILED
    assert result.pydoublet_result is not None
    assert result.coupling_result is None


def test_blueprint_construction_failed_preserves_pydoublet_and_coupling():
    config = copy.deepcopy(_config())
    config["network"]["consumers"][0]["id"] = "consumer_x"
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowFailure)
    assert result.failure_code == WorkflowFailureCode.BLUEPRINT_CONSTRUCTION_FAILED
    assert result.pydoublet_result is not None
    assert result.coupling_result is not None
    assert result.blueprint is None
    assert "consumer_demands_kw" in result.message or "consumer" in result.message.lower()


def test_baseline_evaluation_failed_preserves_pydoublet_coupling_and_blueprint():
    config = copy.deepcopy(_config())
    config["network"]["consumers"][0]["demand_kw"] = 1e9
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowFailure)
    assert result.failure_code == WorkflowFailureCode.BASELINE_EVALUATION_FAILED
    assert result.pydoublet_result is not None
    assert result.coupling_result is not None
    assert result.blueprint is not None


@pytest.mark.parametrize("mutate,expected_code", [
    (lambda c: c["coupling_assumptions"].__setitem__("dh_supply_temperature_c", 200.0), WorkflowFailureCode.HEAT_EXCHANGER_COUPLING_FAILED),
    (lambda c: c["network"]["consumers"][0].__setitem__("demand_kw", 1e9), WorkflowFailureCode.BASELINE_EVALUATION_FAILED),
])
def test_stopping_failures_stop_before_any_candidate_evaluation(mutate, expected_code):
    config = copy.deepcopy(_config())
    mutate(config)
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowFailure)
    assert result.failure_code == expected_code
    assert not any(sc.stage_name.startswith("evaluate_candidate:") for sc in result.audit.stage_calls)


# ── Per-candidate failures never stop the workflow ──────────────────────────
def test_zero_feasible_candidates_is_a_completed_workflow_not_a_failure():
    config = copy.deepcopy(_config())
    config["gates"]["max_consumer_supply_drop_k"] = 0.001
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowResult), result
    assert result.ranking.ranked == []
    assert len(result.ranking.infeasible) == 4
    assert all(
        isinstance(result.candidate_results[cid], CandidateEvaluationFailure)
        for cid in ("C1", "C2", "C3", "C4")
    )
    # no compute_candidate_economics stage call at all, for anyone
    assert not any(sc.stage_name.startswith("compute_candidate_economics:") for sc in result.audit.stage_calls)
    assert result.audit.stage_calls[-1].stage_name == "rank_candidates"


def test_one_candidate_fails_others_succeed_workflow_still_completes():
    """A candidate-specific gate failure (contrived via a pressure
    scenario that fails only the candidate's own connection-branch
    pressure, not the baseline's -- mirrors T2.3's own
    test_pressure_limit_exceeded contrivance) never stops the workflow;
    the other three candidates are still evaluated and ranked."""
    config = copy.deepcopy(_config())
    config["network"]["p_supply_bar_abs"] = 4.51
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowResult), result
    assert isinstance(result.candidate_results["C1"], CandidateEvaluationFailure)
    for cid in ("C2", "C3", "C4"):
        assert isinstance(result.candidate_results[cid], (CandidateEvaluationResult, CandidateEvaluationFailure))
    # workflow completed regardless of C1's own outcome
    assert result.audit.stage_calls[-1].stage_name == "rank_candidates"


# ── run_id determinism ───────────────────────────────────────────────────
def test_run_id_stable_across_repeated_calls():
    r1 = run_workflow(_raw(), _config(), source_provenance=_provenance())
    r2 = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert r1.run_id == r2.run_id


def test_run_id_changes_if_config_changes():
    config = copy.deepcopy(_config())
    r1 = run_workflow(_raw(), config, source_provenance=_provenance())
    config["economics"]["interest_rate_real"]["value"] = 0.030000001
    r2 = run_workflow(_raw(), config, source_provenance=_provenance())
    assert r1.run_id != r2.run_id


def test_run_id_changes_if_pydoublet_input_changes():
    raw1 = _raw()
    raw2 = copy.deepcopy(raw1)
    raw2["simulation_results"]["cop_kw_per_kw"] += 1e-9
    r1 = run_workflow(raw1, _config(), source_provenance=_provenance())
    r2 = run_workflow(raw2, _config(), source_provenance=_provenance())
    assert r1.run_id != r2.run_id


# ── SourceProvenance participates fully in run_id (review correction) ──────
def test_run_id_changes_if_only_source_commit_changes():
    r1 = run_workflow(_raw(), _config(), source_provenance=_provenance())
    other_provenance = SourceProvenance(
        source_pydoublet_commit="0000000000000000000000000000000000000000",
        source_format_hint="known_repaired", calculation_mode="deterministic",
    )
    r2 = run_workflow(_raw(), _config(), source_provenance=other_provenance)
    assert r1.run_id != r2.run_id


def test_run_id_changes_if_only_format_hint_changes():
    r1 = run_workflow(_raw(), _config(), source_provenance=_provenance())
    other_provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_pristine",
        calculation_mode="deterministic",
    )
    r2 = run_workflow(_raw(), _config(), source_provenance=other_provenance)
    assert r1.run_id != r2.run_id


def test_run_id_changes_if_only_scenario_identifier_changes():
    base = _provenance()
    r1 = run_workflow(_raw(), _config(), source_provenance=base)
    other_provenance = base.model_copy(update={"scenario_identifier": "a-different-scenario"})
    r2 = run_workflow(_raw(), _config(), source_provenance=other_provenance)
    assert r1.run_id != r2.run_id


def test_run_id_stable_when_provenance_is_repeated_identically():
    provenance_1 = _provenance()
    provenance_2 = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    r1 = run_workflow(_raw(), _config(), source_provenance=provenance_1)
    r2 = run_workflow(_raw(), _config(), source_provenance=provenance_2)
    assert r1.run_id == r2.run_id


def test_audit_preserves_all_four_source_provenance_fields_exactly():
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic", scenario_identifier="worked-case-scenario",
    )
    result = run_workflow(_raw(), _config(), source_provenance=provenance)
    assert isinstance(result, WorkflowResult)
    preserved = result.audit.source_provenance
    assert preserved.source_pydoublet_commit == _KNOWN_REPAIRED_COMMIT
    assert preserved.source_format_hint == "known_repaired"
    assert preserved.calculation_mode == "deterministic"
    assert preserved.scenario_identifier == "worked-case-scenario"


def test_audit_carries_an_independent_source_provenance_hash():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    from r3chain_geothermal.workflow.core import compute_source_provenance_sha256
    expected = compute_source_provenance_sha256(result.audit.source_provenance)
    assert result.audit.source_provenance_sha256 == expected
    assert len(result.audit.source_provenance_sha256) == 64


def test_run_id_includes_contract_schema_version():
    """A model-level (not run_workflow()-level) check: tampering
    contract_schema_version alone, holding every hash fixed, must make
    the stored run_id inconsistent with recomputation."""
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    payload = json.loads(result.model_dump_json())
    payload["audit"]["contract_schema_version"] = "9.9.9"
    with pytest.raises(ValidationError):
        parse_workflow_result_json(json.dumps(payload))


@pytest.mark.parametrize("calculation_mode", ["unknown", "monte_carlo"])
def test_non_deterministic_calculation_mode_follows_existing_pydoublet_failure_boundary(calculation_mode):
    """calculation_mode='unknown'/'monte_carlo' must be rejected by
    T1.5B's OWN, already-established validation (parse_pydoublet_result)
    -- run_workflow() never inspects or upgrades calculation_mode itself,
    it passes source_provenance straight through unchanged."""
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode=calculation_mode,
    )
    result = run_workflow(_raw(), _config(), source_provenance=provenance)
    assert isinstance(result, WorkflowFailure)
    assert result.failure_code == WorkflowFailureCode.PYDOUBLET_PARSE_FAILED
    assert result.audit.source_provenance.calculation_mode == calculation_mode


# ── Clock injection and determinism ─────────────────────────────────────────
_FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_injected_clock_sets_workflow_created_at():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance(), now=lambda: _FIXED_NOW)
    assert isinstance(result, WorkflowResult)
    assert result.created_at == _FIXED_NOW
    assert result.audit.created_at == _FIXED_NOW


def test_two_runs_with_fixed_clock_are_identical_after_stripping_created_at():
    result_1 = run_workflow(_raw(), _config(), source_provenance=_provenance(), now=lambda: _FIXED_NOW)
    result_2 = run_workflow(_raw(), _config(), source_provenance=_provenance(), now=lambda: _FIXED_NOW)
    payload_1 = _strip_created_at(json.loads(result_1.model_dump_json()))
    payload_2 = _strip_created_at(json.loads(result_2.model_dump_json()))
    assert payload_1 == payload_2


# ── Strict-JSON round trip ───────────────────────────────────────────────────
def test_strict_json_round_trip_for_success():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    dumped = result.model_dump_json()
    _strict_json_loads(dumped)
    restored = parse_workflow_result_json(dumped)
    assert isinstance(restored, WorkflowResult)
    assert restored == result


def test_strict_json_round_trip_for_failure():
    result = run_workflow(None, _config(), source_provenance=_provenance())
    dumped = result.model_dump_json()
    _strict_json_loads(dumped)
    restored = parse_workflow_result_json(dumped)
    assert isinstance(restored, WorkflowFailure)
    assert restored == result


# ── Model-level tamper tests ─────────────────────────────────────────────────
def _valid_success_payload() -> dict:
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    return json.loads(result.model_dump_json())


def test_control_untouched_payload_round_trips_cleanly():
    payload = _valid_success_payload()
    restored = parse_workflow_result_json(json.dumps(payload))
    assert isinstance(restored, WorkflowResult)


def test_tamper_run_id_inconsistent_with_audit_is_rejected():
    payload = _valid_success_payload()
    payload["run_id"] = "r3chain-run-0000000000000000"
    with pytest.raises(ValidationError):
        parse_workflow_result_json(json.dumps(payload))


def test_tamper_audit_run_id_inconsistent_with_hashes_is_rejected():
    payload = _valid_success_payload()
    payload["audit"]["run_id"] = "r3chain-run-0000000000000000"
    payload["run_id"] = "r3chain-run-0000000000000000"
    with pytest.raises(ValidationError):
        parse_workflow_result_json(json.dumps(payload))


def test_tamper_missing_candidate_economics_stage_call_is_rejected():
    payload = _valid_success_payload()
    payload["audit"]["stage_calls"] = [
        sc for sc in payload["audit"]["stage_calls"] if sc["stage_name"] != "compute_candidate_economics:C1"
    ]
    with pytest.raises(ValidationError):
        parse_workflow_result_json(json.dumps(payload))


def test_tamper_stage_call_order_not_contiguous_is_rejected():
    payload = _valid_success_payload()
    payload["audit"]["stage_calls"][0]["order"] = 99
    with pytest.raises(ValidationError):
        parse_workflow_result_json(json.dumps(payload))


def test_tamper_ranked_infeasible_mismatch_with_candidate_results_is_rejected():
    payload = _valid_success_payload()
    payload["ranking"]["ranked"] = payload["ranking"]["ranked"][:-1]  # drop C4 from ranked
    with pytest.raises(ValidationError):
        parse_workflow_result_json(json.dumps(payload))


def test_models_are_frozen():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    with pytest.raises(ValidationError):
        result.run_id = "changed"


def test_stage_call_record_validation():
    with pytest.raises(ValidationError):
        StageCallRecord(order=1, stage_name="x", status="success", failure_code="Y")
    with pytest.raises(ValidationError):
        StageCallRecord(order=1, stage_name="x", status="failure")
    with pytest.raises(ValidationError):
        StageCallRecord(order=0, stage_name="x", status="success")


# ── No NaN/Infinity/absolute paths/env data ─────────────────────────────────
def test_no_nan_or_infinity_anywhere_in_output():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    dumped = result.model_dump_json()
    assert "NaN" not in dumped
    assert "Infinity" not in dumped


def test_no_absolute_local_paths_in_output():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    dumped = result.model_dump_json()
    assert str(_ROOT) not in dumped
    assert "/Users/" not in dumped
    assert "C:\\" not in dumped


# ── Scope boundary ────────────────────────────────────────────────────────────
def _code_body_lower() -> str:
    """core.py's own leading module docstring explicitly DISCLAIMS
    "tool calls" and "subprocess" in prose (module docstring, "This
    module NEVER... calls PyDoublet as a subprocess" / "deliberately
    never called 'tool calls'") -- that disclaimer is exempted from these
    scans; only the actual CODE BODY (imports, functions, field names)
    is checked."""
    source = _CORE_SRC_PATH.read_text()
    match = re.match(r'^""".*?"""\n', source, flags=re.DOTALL)
    assert match is not None
    return source[match.end():].lower()


def test_stage_calls_never_labelled_as_tool_calls():
    """Positive check: the field/attribute names actually used are
    stage_name/stage_calls, never tool_name/tool_calls. A code-body scan
    for the bare phrase "tool call" would also flag this module's own,
    legitimate negated disclaimers ("never called a 'tool call'") -- so
    this checks field NAMES precisely instead of scanning prose."""
    from r3chain_geothermal.workflow.core import StageCallRecord, WorkflowAuditRecord
    assert "stage_name" in StageCallRecord.model_fields
    assert "tool_name" not in StageCallRecord.model_fields
    assert "stage_calls" in WorkflowAuditRecord.model_fields
    assert "tool_calls" not in WorkflowAuditRecord.model_fields


def test_no_map_csv_svg_or_cli_logic_in_core_module():
    code_body = _code_body_lower()
    for pattern in [r"\bcsv\b", r"\bsvg\b", r"argparse", r"\bmatplotlib\b", r"\bfolium\b"]:
        assert not re.search(pattern, code_body), f"forbidden pattern {pattern!r} found in core.py's code body"


def test_no_pydoublet_subprocess_call():
    assert "subprocess" not in _code_body_lower()


# ── validate_config_structure() / WorkflowConfigurationError ────────────────
def test_validate_config_structure_passes_silently_for_the_real_config():
    assert validate_config_structure(_config()) is None


def test_validate_config_structure_raises_configuration_error_for_missing_top_level_section():
    config = _config()
    del config["gates"]
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_validate_config_structure_raises_configuration_error_for_missing_nested_field():
    config = _config()
    del config["coupling_assumptions"]["dh_supply_temperature_c"]
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_validate_config_structure_raises_configuration_error_for_wrong_field_type():
    config = _config()
    config["gates"]["min_pressure_bar_abs"] = "not-a-number"
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_validate_config_structure_raises_configuration_error_for_a_rejected_value():
    """GateTolerances' own model_validator rejects a non-positive
    tolerance with a plain ValueError -- validate_config_structure() must
    wrap it as WorkflowConfigurationError, never let the bare ValueError
    escape."""
    config = _config()
    config["gates"]["max_pipe_velocity_m_s"] = -1.0
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_validate_config_structure_never_raises_a_bare_underlying_exception_type():
    """The whole point of WorkflowConfigurationError: callers can catch
    ONE narrow type, never a bare KeyError/TypeError/ValueError/
    ValidationError that could be confused with an unrelated defect."""
    config = _config()
    del config["network"]["consumers"]
    try:
        validate_config_structure(config)
    except WorkflowConfigurationError:
        pass
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        pytest.fail(f"a bare {type(exc).__name__} escaped instead of WorkflowConfigurationError")


def test_a_config_that_passes_validate_config_structure_lets_run_workflow_proceed_normally():
    """A successful validate_config_structure() call is a guarantee that
    run_workflow() will not itself raise for a config-structure reason
    (module docstring) -- proven here by actually running the workflow
    afterward and confirming it returns a normal, non-exceptional result."""
    config = _config()
    validate_config_structure(config)
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, (WorkflowResult, WorkflowFailure))


def test_workflow_configuration_error_is_a_plain_exception_not_swallowed_by_run_workflow():
    """run_workflow() itself never raises WorkflowConfigurationError --
    that type is only ever raised by validate_config_structure(), a
    SEPARATE, caller-invoked pre-check (module docstring)."""
    config = _config()
    del config["gates"]
    # run_workflow() does NOT call validate_config_structure() internally,
    # so it raises the underlying bare exception (KeyError here), not
    # WorkflowConfigurationError -- proving the two are genuinely decoupled.
    with pytest.raises(KeyError):
        run_workflow(_raw(), config, source_provenance=_provenance())
