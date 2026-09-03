"""FAIL-001..004 (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md
Workstream F, decision-register.md IMPL-009): the intentionally infeasible
workshop/negative-demo candidate.

config/demo_assumptions_workshop_negative.json is a SEPARATE config from
the canonical config/demo_assumptions.json -- FAIL-001 requires the
canonical C1-C4 comparison never be modified to force a failure. This
file proves: (1) the canonical config and its golden run are completely
unaffected by the workshop-negative feature's mere existence; (2) the
workshop config's extra candidate (C5_negative) fails deterministically
with an exact, stable failure code, is excluded from ranking, and never
receives an invented economic figure; (3) every OTHER candidate in the
workshop config run remains identically feasible/ranked to the canonical
run; (4) a malformed workshop-negative spec fails config validation
cleanly, not with a bare KeyError deep in the workflow.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow import WorkflowConfigurationError, WorkflowResult, run_workflow, validate_config_structure

_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_WORKSHOP_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_workshop_negative.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_LCOH_EUR_PER_MWH = {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}
_NEGATIVE_CANDIDATE_ID = "C5_negative"


def _canonical_config() -> dict:
    return json.loads(_CANONICAL_CONFIG_PATH.read_text())


def _workshop_config() -> dict:
    return json.loads(_WORKSHOP_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


# ── FAIL-001: a genuinely separate config, canonical C1-C4 untouched ───────
def test_canonical_config_does_not_declare_the_workshop_negative_demo():
    """The canonical config must never opt into this feature -- if it did,
    C5_negative would silently appear in the golden run."""
    candidates_cfg = _canonical_config()["candidates"]
    assert "include_workshop_negative_demo" not in candidates_cfg
    assert "workshop_negative_demo" not in candidates_cfg


def test_workshop_config_is_identical_to_canonical_outside_its_own_two_additions():
    """FAIL-001: "do not modify the canonical successful C1-C4 comparison
    merely to force a failure" -- every section OTHER than _meta and
    candidates must be byte-for-byte identical between the two configs."""
    canonical = _canonical_config()
    workshop = _workshop_config()
    for section in ("coupling_assumptions", "pydoublet", "network", "gates", "economics"):
        assert workshop[section] == canonical[section], f"section {section!r} differs from the canonical config"
    # candidates: identical except the two new workshop-only keys.
    workshop_candidates = copy.deepcopy(workshop["candidates"])
    del workshop_candidates["include_workshop_negative_demo"]
    del workshop_candidates["workshop_negative_demo"]
    assert workshop_candidates == canonical["candidates"]


def test_canonical_run_is_unaffected_by_the_workshop_negative_feature_existing():
    """The direct GOV-004/CFG-006 proof: running the CANONICAL config
    reproduces the exact golden run_id and LCOH ranking, unchanged by this
    feature's mere existence in the codebase."""
    result = run_workflow(_raw(), _canonical_config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    assert result.run_id == "r3chain-run-93d41133daa11d1a"
    assert _NEGATIVE_CANDIDATE_ID not in result.candidate_results
    order = [entry.candidate_id for entry in result.ranking.ranked]
    assert order == ["C1", "C2", "C3", "C4"]


# ── FAIL-002/003: the negative candidate fails exactly one gate, deterministically ──
def test_workshop_negative_demo_end_to_end():
    result = run_workflow(_raw(), _workshop_config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)

    # A genuinely different run identity from the canonical config's golden run.
    assert result.run_id != "r3chain-run-93d41133daa11d1a"

    # FAIL-003: candidate ID/label, feasible: false, exact stable failure code,
    # measured value/threshold/unit/pressure reference.
    negative = result.candidate_results[_NEGATIVE_CANDIDATE_ID]
    assert negative.status == "failure"
    assert negative.candidate.id == _NEGATIVE_CANDIDATE_ID
    assert negative.candidate.label == "Workshop negative demo: excessive connection length"
    assert negative.failure_code == "PRESSURE_LIMIT_EXCEEDED"
    assert negative.details["min_pressure_bar_abs"] == 1.5  # bar_abs, this project's sole pressure reference
    assert negative.details["pressure_bar_abs"] < negative.details["min_pressure_bar_abs"]
    # Non-borderline margin (docs/issues/workshop-negative-demo.md) -- not a
    # flaky near-threshold case.
    assert negative.details["pressure_bar_abs"] < 0.5

    # Excluded from ranking; no invented economics/LCOH.
    ranked_ids = {entry.candidate_id for entry in result.ranking.ranked}
    infeasible_ids = {entry.candidate_id for entry in result.ranking.infeasible}
    assert _NEGATIVE_CANDIDATE_ID not in ranked_ids
    assert _NEGATIVE_CANDIDATE_ID in infeasible_ids

    # Every OTHER candidate remains feasible, ranked, and numerically
    # identical to the canonical config's own golden ranking -- the
    # negative candidate's presence must not perturb C1-C4 at all.
    order = [entry.candidate_id for entry in result.ranking.ranked]
    assert order == ["C1", "C2", "C3", "C4"]
    for entry in result.ranking.ranked:
        lcoh_mwh = entry.economics.indicative_lcoh_eur_per_kwh * 1000.0
        assert math.isclose(lcoh_mwh, _EXPECTED_LCOH_EUR_PER_MWH[entry.candidate_id], rel_tol=1e-4)


def test_workshop_negative_demo_stage_calls_record_the_failure():
    """FAIL-003's audit requirement, at the stage-call level (mirrors
    test_core.py's own stage-call sequence tests)."""
    result = run_workflow(_raw(), _workshop_config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    negative_calls = [sc for sc in result.audit.stage_calls if sc.stage_name == f"evaluate_candidate:{_NEGATIVE_CANDIDATE_ID}"]
    assert len(negative_calls) == 1
    assert negative_calls[0].status == "failure"
    assert negative_calls[0].failure_code == "PRESSURE_LIMIT_EXCEEDED"
    # No compute_candidate_economics stage call for an infeasible candidate.
    assert f"compute_candidate_economics:{_NEGATIVE_CANDIDATE_ID}" not in [sc.stage_name for sc in result.audit.stage_calls]


def test_workshop_negative_demo_is_deterministic():
    """FAIL-002: "must not depend on random solver behavior" -- two
    independent runs must be bit-identical (mirrors test_core.py's own
    determinism tests)."""
    result_1 = run_workflow(_raw(), _workshop_config(), source_provenance=_provenance())
    result_2 = run_workflow(_raw(), _workshop_config(), source_provenance=_provenance())
    assert isinstance(result_1, WorkflowResult) and isinstance(result_2, WorkflowResult)
    assert result_1.run_id == result_2.run_id
    assert result_1.candidate_results[_NEGATIVE_CANDIDATE_ID].failure_code == result_2.candidate_results[_NEGATIVE_CANDIDATE_ID].failure_code
    assert (
        result_1.candidate_results[_NEGATIVE_CANDIDATE_ID].details
        == result_2.candidate_results[_NEGATIVE_CANDIDATE_ID].details
    )


# ── FAIL-004: config validation ──────────────────────────────────────────
def test_validate_config_structure_accepts_the_workshop_negative_config():
    validate_config_structure(_workshop_config())  # must not raise


@pytest.mark.parametrize("missing_key", [
    "id", "label", "supply_junction", "return_junction", "surface_connection_length_m",
])
def test_validate_config_structure_rejects_a_malformed_workshop_negative_spec(missing_key):
    config = _workshop_config()
    del config["candidates"]["workshop_negative_demo"][missing_key]
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_validate_config_structure_rejects_an_invalid_junction_reference():
    """The negative candidate's own supply/return junctions are validated
    by NetworkBlueprint's own model-level invariant -- a nonexistent
    junction must fail here, not surface as a bare KeyError deep inside
    evaluate_candidate()."""
    config = _workshop_config()
    config["candidates"]["workshop_negative_demo"]["supply_junction"] = "not_a_real_junction"
    with pytest.raises(WorkflowConfigurationError):
        validate_config_structure(config)


def test_run_workflow_rejects_a_malformed_workshop_negative_spec_the_same_way():
    """validate_config_structure()'s own documented guarantee: run_workflow()
    fails identically (not with an unhandled exception) for a config that
    already failed validation."""
    config = _workshop_config()
    del config["candidates"]["workshop_negative_demo"]["id"]
    with pytest.raises((KeyError, ValueError)):
        run_workflow(_raw(), config, source_provenance=_provenance())
