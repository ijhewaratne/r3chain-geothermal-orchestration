"""Phase 5 tests for workflow.research_experiment (the top-level orchestrator),
R3-CHAIN Final Research-Alignment Implementation Specification, against the
committed config/research_experiment_synthetic.json fixture."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow.research_experiment import (
    ResearchExperimentFailure,
    ResearchExperimentResult,
    is_research_experiment_enabled,
    run_research_experiment,
)

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "research_experiment_synthetic.json"
_V2_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_joint_study_v2.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _run() -> ResearchExperimentResult:
    result = run_research_experiment(_raw(), _config(), source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, ResearchExperimentResult), result
    return result


def test_canonical_and_v2_only_configs_do_not_enable_this_layer() -> None:
    canonical = json.loads((_ROOT / "config" / "demo_assumptions.json").read_text())
    v2_only = json.loads(_V2_CONFIG_PATH.read_text())
    assert is_research_experiment_enabled(canonical) is False
    assert is_research_experiment_enabled(v2_only) is False


def test_committed_config_enables_this_layer_and_names_the_committed_package() -> None:
    config = _config()
    assert is_research_experiment_enabled(config) is True
    assert config["research_experiment"]["referenced_study_package_relative_path"] == "config/joint_study_synthetic_v2.json"


def test_run_research_experiment_end_to_end_succeeds() -> None:
    result = _run()
    assert result.run_id.startswith("r3chain-run-")
    assert result.alternative_summaries
    assert len(result.alternative_summaries) == len(result.referenced_v2_result.alternatives)


def test_every_alternative_has_three_load_state_results() -> None:
    result = _run()
    for summary in result.alternative_summaries:
        assert len(summary.annualized_economics.load_state_results) == 3
        assert [r.load_state_id for r in summary.annualized_economics.load_state_results] == [
            "peak", "shoulder", "base",
        ]


def test_run_id_matches_audit_run_id() -> None:
    result = _run()
    assert result.run_id == result.audit.run_id


def test_run_is_deterministic_across_repeated_calls() -> None:
    first = _run()
    second = _run()
    assert first.run_id == second.run_id
    assert first.integrated_decision.model_dump() == second.integrated_decision.model_dump()
    assert first.baseline_comparison.model_dump() == second.baseline_comparison.model_dump()
    assert (
        first.sensitivity_decision_summary.robustness_classification
        == second.sensitivity_decision_summary.robustness_classification
    )


def test_baseline_comparison_is_well_formed() -> None:
    result = _run()
    assert result.baseline_comparison.interpretation_code is not None
    assert result.baseline_comparison.explanation


def test_sensitivity_summary_has_one_result_per_declared_case() -> None:
    result = _run()
    assert len(result.sensitivity_decision_summary.sensitivity_case_results) == len(
        result.research_config.sensitivity_cases
    )


def test_package_reference_mismatch_fails_loudly_not_with_a_crash() -> None:
    config = _config()
    config["research_experiment"]["referenced_study_package_relative_path"] = "config/some_other_package.json"
    result = run_research_experiment(_raw(), config, source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, ResearchExperimentFailure)
    assert result.failure_code == "RESEARCH_EXPERIMENT_PACKAGE_REFERENCE_MISMATCH"


def test_malformed_research_experiment_config_fails_before_any_simulation() -> None:
    config = _config()
    config["research_experiment"]["load_states"] = []
    result = run_research_experiment(_raw(), config, source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, ResearchExperimentFailure)
    assert result.failure_code == "RESEARCH_EXPERIMENT_CONFIG_INVALID"


def test_load_state_durations_exceeding_base_assumptions_hours_fails_loudly() -> None:
    config = _config()
    config["research_experiment"]["load_states"][0]["annual_duration_hours"] = 999999.0
    result = run_research_experiment(_raw(), config, source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, ResearchExperimentFailure)
    assert result.failure_code == "RESEARCH_EXPERIMENT_LOAD_STATE_DURATIONS_INVALID"


# ── CLI dispatch ──────────────────────────────────────────────────────────────

def test_cli_dispatches_to_research_experiment_when_enabled(tmp_path) -> None:
    from r3chain_geothermal.workflow.cli import EXIT_OK, run_cli

    provenance_path = _ROOT / "config" / "demo_source_provenance.json"
    output_dir = tmp_path / "out"
    exit_code = run_cli([
        "--input", str(_REPAIRED_PATH), "--config", str(_CONFIG_PATH),
        "--provenance", str(provenance_path), "--output-dir", str(output_dir),
    ])
    assert exit_code == EXIT_OK
    assert (output_dir / "research_experiment_result.json").is_file()
    assert (output_dir / "manifest.json").is_file()
    assert (output_dir / "research_experiment_report.md").is_file()


def test_cli_run_twice_via_cli_yields_identical_bundle_hash(tmp_path) -> None:
    from r3chain_geothermal.workflow.cli import EXIT_OK, run_cli

    provenance_path = _ROOT / "config" / "demo_source_provenance.json"
    manifests = []
    for label in ("run1", "run2"):
        output_dir = tmp_path / label
        exit_code = run_cli([
            "--input", str(_REPAIRED_PATH), "--config", str(_CONFIG_PATH),
            "--provenance", str(provenance_path), "--output-dir", str(output_dir),
        ])
        assert exit_code == EXIT_OK
        manifests.append(json.loads((output_dir / "manifest.json").read_text()))
    assert manifests[0]["bundle_scientific_sha256"] == manifests[1]["bundle_scientific_sha256"]
