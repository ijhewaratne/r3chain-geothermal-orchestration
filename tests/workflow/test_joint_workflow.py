"""R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase 4: the joint
synthetic site/connection optimisation demonstration exposed as its own
top-level workflow entry point (workflow/joint_workflow.py) --
run_joint_optimization_full_product() (the full, undisclosed-filtering-
free scenario x accepted-candidate product) and run_joint_optimization_
workflow() (the parse/blueprint/baseline/full-product sequence, with its
own audit trail and artifact bundle), plus the CLI dispatch that reaches
it via config["joint_optimization"]["enabled"].

Every numeric expectation below (33 alternatives, 17 feasible, the exact
per-scenario feasible counts) was measured directly against this fixed
synthetic topology/config, not assumed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow.cli import EXIT_OK, EXIT_WORKFLOW_FAILURE, run_cli
from r3chain_geothermal.workflow.joint_workflow import (
    JointOptimizationWorkflowFailure,
    JointOptimizationWorkflowResult,
    is_joint_optimization_enabled,
    run_joint_optimization_workflow,
    write_joint_optimization_artifacts,
)

_ROOT = Path(__file__).resolve().parents[2]
_GENERATED_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_generated_candidates.json"
_CANONICAL_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_TOTAL_ALTERNATIVES = 33
_EXPECTED_FEASIBLE_BY_SCENARIO = {"scenario_A": 8, "scenario_B": 0, "scenario_C": 9}


def _joint_config() -> dict:
    config = json.loads(_GENERATED_CONFIG_PATH.read_text())
    config["joint_optimization"] = {"enabled": True}
    return config


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


# ── the config switch itself ────────────────────────────────────────────────
def test_canonical_config_does_not_enable_joint_optimization():
    canonical = json.loads(_CANONICAL_CONFIG_PATH.read_text())
    assert "joint_optimization" not in canonical
    assert is_joint_optimization_enabled(canonical) is False


def test_is_joint_optimization_enabled_reads_the_explicit_switch():
    assert is_joint_optimization_enabled({}) is False
    assert is_joint_optimization_enabled({"joint_optimization": {"enabled": False}}) is False
    assert is_joint_optimization_enabled({"joint_optimization": {"enabled": True}}) is True


# ── run_joint_optimization_workflow(): the full product, no curation ───────
def test_full_product_evaluates_every_scenario_candidate_pair():
    result = run_joint_optimization_workflow(_raw(), _joint_config(), source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowResult)
    jr = result.joint_result
    assert len(jr.scenarios) == 3
    assert len(result.screened_candidates) == 16
    accepted = sum(1 for sc in result.screened_candidates if sc.accepted)
    assert accepted == 11
    # No curation: len(alternatives) IS the full unfiltered search-space size.
    assert len(jr.alternatives) == len(jr.scenarios) * accepted == _EXPECTED_TOTAL_ALTERNATIVES


def test_full_product_feasible_counts_match_per_scenario():
    result = run_joint_optimization_workflow(_raw(), _joint_config(), source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowResult)
    counts = {"scenario_A": 0, "scenario_B": 0, "scenario_C": 0}
    for alt in result.joint_result.alternatives:
        if alt.feasible:
            counts[alt.identity.geothermal_scenario_id] += 1
    assert counts == _EXPECTED_FEASIBLE_BY_SCENARIO


def test_full_product_scenario_b_is_entirely_infeasible_at_the_hx_stage():
    """scenario_B is deliberately HX-hot-end-infeasible (joint_optimization.py's
    own docstring) -- EVERY candidate paired with it must fail at the same
    stage, regardless of which candidate."""
    result = run_joint_optimization_workflow(_raw(), _joint_config(), source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowResult)
    scenario_b_alts = [a for a in result.joint_result.alternatives if a.identity.geothermal_scenario_id == "scenario_B"]
    assert len(scenario_b_alts) == 11
    assert all(not a.feasible for a in scenario_b_alts)
    assert all(a.failure_code == "HX_SUPPLY_TEMPERATURE_INFEASIBLE" for a in scenario_b_alts)


def test_full_product_is_deterministic():
    result_1 = run_joint_optimization_workflow(_raw(), _joint_config(), source_provenance=_provenance())
    result_2 = run_joint_optimization_workflow(_raw(), _joint_config(), source_provenance=_provenance())
    assert isinstance(result_1, JointOptimizationWorkflowResult) and isinstance(result_2, JointOptimizationWorkflowResult)
    assert result_1.run_id == result_2.run_id
    ids_1 = [a.identity.alternative_id for a in result_1.joint_result.alternatives]
    ids_2 = [a.identity.alternative_id for a in result_2.joint_result.alternatives]
    assert ids_1 == ids_2


def test_full_product_max_candidates_caps_the_grid():
    config = _joint_config()
    config["candidates"]["generated"]["max_candidates"] = 2
    result = run_joint_optimization_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowResult)
    assert len(result.joint_result.alternatives) == 3 * 2  # 3 scenarios x 2 capped candidates


def test_never_recommends_when_no_feasible_alternative_exists():
    """AC-10/OPT-003's own honesty requirement, exercised at the full-
    product level: an unreachably tight max_consumer_supply_drop_k gate
    (0.0001 K, verified empirically to fail every one of the 33
    alternatives while still letting the baseline itself converge, unlike
    a velocity-gate override which was found to fail the BASELINE first
    for this topology) forces every alternative infeasible -- the
    workflow must still complete normally with an honest empty
    shortlist, never an invented recommendation."""
    config = _joint_config()
    config["gates"]["max_consumer_supply_drop_k"] = 0.0001
    result = run_joint_optimization_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowResult)
    assert result.joint_result.pareto_shortlist_alternative_ids == []
    assert all(not a.feasible for a in result.joint_result.alternatives)


# ── stopping failures ────────────────────────────────────────────────────────
def test_missing_generated_candidates_config_fails_loudly_not_with_a_crash():
    config = json.loads(_CANONICAL_CONFIG_PATH.read_text())
    config["joint_optimization"] = {"enabled": True}  # canonical config has no candidates.generated
    result = run_joint_optimization_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowFailure)
    assert result.failure_code.value == "BLUEPRINT_CONSTRUCTION_FAILED"
    assert result.pydoublet_result is not None  # stage 1 completed before this stopped


def test_pydoublet_parse_failure_is_reported_as_such():
    result = run_joint_optimization_workflow({}, _joint_config(), source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowFailure)
    assert result.failure_code.value == "PYDOUBLET_PARSE_FAILED"
    assert result.pydoublet_result is None


# ── artifact bundle ──────────────────────────────────────────────────────────
def test_write_joint_optimization_artifacts_writes_every_file_and_a_valid_manifest(tmp_path):
    result = run_joint_optimization_workflow(_raw(), _joint_config(), source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowResult)
    manifest = write_joint_optimization_artifacts(result, _raw(), _joint_config(), tmp_path)
    expected_files = {
        "pydoublet_input.json", "config_snapshot.json", "joint_optimization_result.json", "audit.json",
        "generated_candidates.json", "screened_alternatives.json", "alternative_comparison.csv",
        "pareto_or_ranking.json", "joint_recommendation.md",
    }
    assert set(manifest.files.keys()) == expected_files
    for filename in expected_files:
        assert (tmp_path / filename).is_file()
    assert (tmp_path / "manifest.json").is_file()
    for record in manifest.files.values():
        assert len(record.byte_sha256) == 64
        assert len(record.scientific_sha256) == 64


def test_write_joint_optimization_artifacts_is_deterministic_apart_from_timestamps(tmp_path):
    """write_joint_optimization_artifacts(), like write_workflow_artifacts()
    itself, requires output_dir to already exist (module docstring's own
    parity claim) -- both target directories are created first."""
    result = run_joint_optimization_workflow(_raw(), _joint_config(), source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowResult)
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    manifest_1 = write_joint_optimization_artifacts(result, _raw(), _joint_config(), dir_a)
    manifest_2 = write_joint_optimization_artifacts(result, _raw(), _joint_config(), dir_b)
    assert manifest_1.bundle_scientific_sha256 == manifest_2.bundle_scientific_sha256


def test_failure_bundle_writes_only_the_four_core_files(tmp_path):
    config = json.loads(_CANONICAL_CONFIG_PATH.read_text())
    config["joint_optimization"] = {"enabled": True}
    result = run_joint_optimization_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, JointOptimizationWorkflowFailure)
    manifest = write_joint_optimization_artifacts(result, _raw(), config, tmp_path)
    assert set(manifest.files.keys()) == {"pydoublet_input.json", "config_snapshot.json", "joint_optimization_result.json", "audit.json"}


# ── CLI dispatch ─────────────────────────────────────────────────────────────
def test_cli_dispatches_to_joint_optimization_when_enabled(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_joint_config()))
    provenance_path = _ROOT / "config" / "demo_source_provenance.json"
    output_dir = tmp_path / "out"
    exit_code = run_cli([
        "--input", str(_REPAIRED_PATH), "--config", str(config_path),
        "--provenance", str(provenance_path), "--output-dir", str(output_dir),
    ])
    assert exit_code == EXIT_OK
    assert (output_dir / "joint_optimization_result.json").is_file()
    assert (output_dir / "manifest.json").is_file()


def test_cli_reports_joint_optimization_stopping_failure_as_exit_code_2(tmp_path):
    config = json.loads(_CANONICAL_CONFIG_PATH.read_text())
    config["joint_optimization"] = {"enabled": True}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    provenance_path = _ROOT / "config" / "demo_source_provenance.json"
    output_dir = tmp_path / "out"
    exit_code = run_cli([
        "--input", str(_REPAIRED_PATH), "--config", str(config_path),
        "--provenance", str(provenance_path), "--output-dir", str(output_dir),
    ])
    assert exit_code == EXIT_WORKFLOW_FAILURE
    assert (output_dir / "manifest.json").is_file()
