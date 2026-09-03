"""CAN-001..007 (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase
3.2, workflow/core.py::_apply_candidate_mode): candidates.mode=="generated"
wired into run_workflow()/validate_config_structure().

config/demo_assumptions_generated_candidates.json is a SEPARATE config
from the canonical config/demo_assumptions.json (same pattern as
test_workshop_negative_demo.py's own FAIL-001 proof). This file proves:
(1) the canonical config and its golden run are completely unaffected by
candidates.mode existing at all -- absent from the canonical config, it
defaults to "predefined"; (2) the generated config replaces
blueprint.candidates entirely with generate_candidates()'s own
deterministic, verified output (11 accepted of 16 screened for this fixed
topology); (3) every generated candidate is evaluated through the exact
same evaluate_candidate() pathway, producing exact, previously-measured
feasible/infeasible outcomes; (4) the run is deterministic; (5)
malformed candidates.mode/candidates.generated configs fail validation
cleanly, not with a bare KeyError deep in the workflow; (6) max_candidates
caps the accepted set deterministically; (7) a configuration producing
zero accepted candidates fails loudly rather than silently ranking
nothing.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow import (
    WorkflowConfigurationError,
    WorkflowFailure,
    WorkflowFailureCode,
    WorkflowResult,
    run_workflow,
    validate_config_structure,
)

_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_GENERATED_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_generated_candidates.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_STUDY_PREFIX = "r3chain-synthetic-network-v1"
_EXPECTED_FEASIBLE_IDS = {
    f"{_STUDY_PREFIX}-trunk_1-direct-standard", f"{_STUDY_PREFIX}-trunk_1-diverted-standard",
    f"{_STUDY_PREFIX}-trunk_2-direct-standard", f"{_STUDY_PREFIX}-trunk_2-diverted-standard",
    f"{_STUDY_PREFIX}-trunk_3-direct-standard", f"{_STUDY_PREFIX}-trunk_3-diverted-standard",
    f"{_STUDY_PREFIX}-trunk_4-direct-standard", f"{_STUDY_PREFIX}-trunk_4-diverted-standard",
}
_EXPECTED_INFEASIBLE_IDS = {
    f"{_STUDY_PREFIX}-consumer_1-direct-standard", f"{_STUDY_PREFIX}-consumer_2-direct-standard",
    f"{_STUDY_PREFIX}-consumer_3-direct-standard",
}
_EXPECTED_RANKED_ORDER = [
    f"{_STUDY_PREFIX}-trunk_1-direct-standard", f"{_STUDY_PREFIX}-trunk_2-direct-standard",
    f"{_STUDY_PREFIX}-trunk_1-diverted-standard", f"{_STUDY_PREFIX}-trunk_3-direct-standard",
    f"{_STUDY_PREFIX}-trunk_2-diverted-standard", f"{_STUDY_PREFIX}-trunk_4-direct-standard",
    f"{_STUDY_PREFIX}-trunk_3-diverted-standard", f"{_STUDY_PREFIX}-trunk_4-diverted-standard",
]


def _canonical_config() -> dict:
    return json.loads(_CANONICAL_CONFIG_PATH.read_text())


def _generated_config() -> dict:
    return json.loads(_GENERATED_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


# ── the canonical config never opts into generated mode ─────────────────────
def test_canonical_config_does_not_declare_a_candidate_mode():
    candidates_cfg = _canonical_config()["candidates"]
    assert "mode" not in candidates_cfg
    assert "generated" not in candidates_cfg


def test_generated_config_is_identical_to_canonical_outside_its_own_two_additions():
    canonical = _canonical_config()
    generated = _generated_config()
    for section in ("coupling_assumptions", "pydoublet", "network", "gates", "economics"):
        assert generated[section] == canonical[section], f"section {section!r} differs from the canonical config"
    generated_candidates = copy.deepcopy(generated["candidates"])
    del generated_candidates["mode"]
    del generated_candidates["generated"]
    assert generated_candidates == canonical["candidates"]


def test_canonical_run_is_unaffected_by_generated_mode_existing():
    result = run_workflow(_raw(), _canonical_config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    assert result.run_id == "r3chain-run-93d41133daa11d1a"
    assert sorted(result.blueprint.candidates) == ["C1", "C2", "C3", "C4"]


# ── generated mode itself ───────────────────────────────────────────────────
def test_generated_mode_replaces_the_candidate_set():
    result = run_workflow(_raw(), _generated_config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    assert result.run_id != "r3chain-run-93d41133daa11d1a"
    assert set(result.blueprint.candidates) == _EXPECTED_FEASIBLE_IDS | _EXPECTED_INFEASIBLE_IDS
    assert len(result.blueprint.candidates) == 11


def test_generated_mode_produces_the_exact_measured_feasible_infeasible_split():
    result = run_workflow(_raw(), _generated_config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    feasible_ids = {cid for cid, cr in result.candidate_results.items() if cr.status == "success"}
    infeasible_ids = {cid for cid, cr in result.candidate_results.items() if cr.status == "failure"}
    assert feasible_ids == _EXPECTED_FEASIBLE_IDS
    assert infeasible_ids == _EXPECTED_INFEASIBLE_IDS
    for cid in _EXPECTED_INFEASIBLE_IDS:
        assert result.candidate_results[cid].failure_code == "VELOCITY_LIMIT_EXCEEDED"


def test_generated_mode_ranking_matches_the_exact_measured_order():
    result = run_workflow(_raw(), _generated_config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    assert [entry.candidate_id for entry in result.ranking.ranked] == _EXPECTED_RANKED_ORDER
    assert {entry.candidate_id for entry in result.ranking.infeasible} == _EXPECTED_INFEASIBLE_IDS


def test_generated_mode_is_deterministic():
    result_1 = run_workflow(_raw(), _generated_config(), source_provenance=_provenance())
    result_2 = run_workflow(_raw(), _generated_config(), source_provenance=_provenance())
    assert isinstance(result_1, WorkflowResult) and isinstance(result_2, WorkflowResult)
    assert result_1.run_id == result_2.run_id
    assert [e.candidate_id for e in result_1.ranking.ranked] == [e.candidate_id for e in result_2.ranking.ranked]


def test_generated_mode_max_candidates_caps_deterministically():
    config = _generated_config()
    config["candidates"]["generated"]["max_candidates"] = 2
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    assert sorted(result.blueprint.candidates) == sorted(_EXPECTED_FEASIBLE_IDS | _EXPECTED_INFEASIBLE_IDS)[:2]


def test_generated_mode_zero_accepted_candidates_fails_loudly():
    """A connection_pipe_dn_mm that fails DesignOption's own validator
    (<=0) rejects every attachment with MISSING_PIPE_OR_DESIGN_DATA,
    leaving zero accepted candidates -- must raise, never silently
    produce an empty ranking."""
    config = _generated_config()
    config["candidates"]["generated"]["connection_pipe_dn_mm"] = -1.0
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowFailure)
    assert result.failure_code == WorkflowFailureCode.BLUEPRINT_CONSTRUCTION_FAILED


@pytest.mark.parametrize("bad_mode", ["bogus", "", None])
def test_invalid_candidate_mode_fails_validation_cleanly(bad_mode):
    config = _generated_config()
    config["candidates"]["mode"] = bad_mode
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_generated_mode_missing_connection_pipe_dn_mm_fails_validation_cleanly():
    config = _generated_config()
    del config["candidates"]["generated"]["connection_pipe_dn_mm"]
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_validate_config_structure_accepts_the_generated_config():
    validate_config_structure(_generated_config())  # must not raise
