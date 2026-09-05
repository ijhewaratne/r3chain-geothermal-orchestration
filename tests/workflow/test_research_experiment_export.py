"""Phase 7 tests for workflow.research_experiment_export (RA-ART),
R3-CHAIN Final Research-Alignment Implementation Specification.

Conformance-round revision: the bundle now publishes every file the
specification's own §17 "shall publish at least" list names, not the smaller
8-file bundle this test file originally covered."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow.research_experiment import ResearchExperimentResult, run_research_experiment
from r3chain_geothermal.workflow.research_experiment_export import (
    ANNUALIZED_ALTERNATIVE_COMPARISON_CSV_FILENAME,
    ANNUALIZED_INTEGRATED_RESULT_FILENAME,
    AUDIT_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    EXPERIMENT_INPUT_FILENAME,
    GEOTHERMAL_ONLY_COMPARISON_CSV_FILENAME,
    GEOTHERMAL_ONLY_RESULT_FILENAME,
    JOINT_STUDY_SNAPSHOT_FILENAME,
    LOAD_STATE_RESULTS_FILENAME,
    LOAD_STATES_FILENAME,
    MANIFEST_FILENAME,
    NETWORK_ONLY_COMPARISON_CSV_FILENAME,
    NETWORK_ONLY_RESULT_FILENAME,
    OBJECTIVE_POLICY_FILENAME,
    PARETO_OR_RANKING_FILENAME,
    PYDOUBLET_INPUT_FILENAME,
    REFERENCED_V2_RESULT_FILENAME,
    RESEARCH_COMPARISON_CSV_FILENAME,
    RESEARCH_COMPARISON_FILENAME,
    RESEARCH_EXPERIMENT_RESULT_FILENAME,
    RESEARCH_FINDINGS_MD_FILENAME,
    SENSITIVITY_COMPARISON_CSV_FILENAME,
    SENSITIVITY_RESULTS_FILENAME,
    ResearchExperimentManifestRecord,
    write_research_experiment_artifacts,
)

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "research_experiment_synthetic.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_SPEC_17_FILENAMES = (
    EXPERIMENT_INPUT_FILENAME, JOINT_STUDY_SNAPSHOT_FILENAME, LOAD_STATES_FILENAME, LOAD_STATE_RESULTS_FILENAME,
    ANNUALIZED_ALTERNATIVE_COMPARISON_CSV_FILENAME, ANNUALIZED_INTEGRATED_RESULT_FILENAME,
    GEOTHERMAL_ONLY_RESULT_FILENAME, GEOTHERMAL_ONLY_COMPARISON_CSV_FILENAME, NETWORK_ONLY_RESULT_FILENAME,
    NETWORK_ONLY_COMPARISON_CSV_FILENAME, RESEARCH_COMPARISON_FILENAME, RESEARCH_COMPARISON_CSV_FILENAME,
    SENSITIVITY_RESULTS_FILENAME, SENSITIVITY_COMPARISON_CSV_FILENAME, OBJECTIVE_POLICY_FILENAME,
    PARETO_OR_RANKING_FILENAME, RESEARCH_FINDINGS_MD_FILENAME, AUDIT_FILENAME, MANIFEST_FILENAME,
)


def _run() -> ResearchExperimentResult:
    config = json.loads(_CONFIG_PATH.read_text())
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    result = run_research_experiment(raw, config, source_provenance=provenance, package_root=_ROOT)
    assert isinstance(result, ResearchExperimentResult)
    return result, config, raw


def test_write_research_experiment_artifacts_writes_every_spec_named_file(tmp_path) -> None:
    result, config, raw = _run()
    manifest = write_research_experiment_artifacts(result, raw, config, tmp_path)
    assert isinstance(manifest, ResearchExperimentManifestRecord)
    assert manifest.run_id == result.run_id
    for filename in (
        PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, REFERENCED_V2_RESULT_FILENAME,
        RESEARCH_EXPERIMENT_RESULT_FILENAME, *_SPEC_17_FILENAMES,
    ):
        assert (tmp_path / filename).exists(), f"{filename} was not published"
    assert MANIFEST_FILENAME not in manifest.files


def test_write_research_experiment_artifacts_is_deterministic_apart_from_timestamps(tmp_path) -> None:
    result, config, raw = _run()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    manifest_a = write_research_experiment_artifacts(result, raw, config, dir_a)
    manifest_b = write_research_experiment_artifacts(result, raw, config, dir_b)
    assert manifest_a.bundle_scientific_sha256 == manifest_b.bundle_scientific_sha256
    for filename, record_a in manifest_a.files.items():
        assert manifest_b.files[filename].scientific_sha256 == record_a.scientific_sha256


def test_research_findings_markdown_carries_the_synthetic_disclaimer_and_every_required_element(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    text = (tmp_path / RESEARCH_FINDINGS_MD_FILENAME).read_text()
    assert "SYNTHETIC" in text
    assert result.run_id in text
    for heading in (
        "Best geothermal-only site", "Best network-only attachment", "Integrated rank-1 group",
        "Did integration change", "Pareto shortlist", "Robustness classification", "Caveats",
    ):
        assert heading in text


def test_annualized_alternative_comparison_csv_has_one_row_per_alternative(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    csv_text = (tmp_path / ANNUALIZED_ALTERNATIVE_COMPARISON_CSV_FILENAME).read_text()
    rows = [line for line in csv_text.splitlines() if line]
    assert len(rows) == len(result.alternative_summaries) + 1  # +1 header


def test_load_state_results_json_has_one_row_per_alternative_times_load_state(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    rows = json.loads((tmp_path / LOAD_STATE_RESULTS_FILENAME).read_text())
    expected = sum(len(s.annualized_economics.load_state_results) for s in result.alternative_summaries)
    assert len(rows) == expected
    assert all("alternative_id" in row and "load_state_id" in row for row in rows)


def test_load_states_json_matches_the_declared_config(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    declared = json.loads((tmp_path / LOAD_STATES_FILENAME).read_text())
    assert len(declared) == len(result.research_config.load_states)
    assert {d["load_state_id"] for d in declared} == {s.load_state_id for s in result.research_config.load_states}


def test_geothermal_only_result_json_and_csv_agree(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    result_json = json.loads((tmp_path / GEOTHERMAL_ONLY_RESULT_FILENAME).read_text())
    assert result_json["preferred_site_id"] == result.geothermal_only_preferred_site_id
    csv_text = (tmp_path / GEOTHERMAL_ONLY_COMPARISON_CSV_FILENAME).read_text()
    csv_rows = [line for line in csv_text.splitlines() if line]
    assert len(csv_rows) == len(result.geothermal_only_lcoh_by_site_id) + 1  # +1 header


def test_network_only_result_json_and_csv_agree(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    result_json = json.loads((tmp_path / NETWORK_ONLY_RESULT_FILENAME).read_text())
    assert result_json["preferred_attachment_id"] == result.network_only_preferred_attachment_id
    csv_text = (tmp_path / NETWORK_ONLY_COMPARISON_CSV_FILENAME).read_text()
    csv_rows = [line for line in csv_text.splitlines() if line]
    assert len(csv_rows) == len(result.network_only_subset) + 1  # +1 header


def test_research_comparison_json_matches_baseline_comparison(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    payload = json.loads((tmp_path / RESEARCH_COMPARISON_FILENAME).read_text())
    assert payload["interpretation_code"] == result.baseline_comparison.interpretation_code.value


def test_sensitivity_results_json_matches_the_decision_summary(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    payload = json.loads((tmp_path / SENSITIVITY_RESULTS_FILENAME).read_text())
    assert payload["robustness_classification"] == result.sensitivity_decision_summary.robustness_classification.value
    assert len(payload["sensitivity_case_results"]) == len(result.research_config.sensitivity_cases)


def test_objective_policy_json_matches_the_declared_decision_policy(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    payload = json.loads((tmp_path / OBJECTIVE_POLICY_FILENAME).read_text())
    assert payload["primary_objective"] == result.research_config.decision_policy.primary_objective


def test_pareto_or_ranking_json_matches_the_integrated_decision(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    payload = json.loads((tmp_path / PARETO_OR_RANKING_FILENAME).read_text())
    assert payload["preferred_alternative_id"] == result.integrated_decision.preferred_alternative_id


def test_experiment_input_json_round_trips_the_research_config(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    payload = json.loads((tmp_path / EXPERIMENT_INPUT_FILENAME).read_text())
    assert payload["referenced_study_package_relative_path"] == result.research_config.referenced_study_package_relative_path


def test_joint_study_snapshot_json_matches_the_referenced_v2_package(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    payload = json.loads((tmp_path / JOINT_STUDY_SNAPSHOT_FILENAME).read_text())
    assert len(payload["sites"]) == len(result.referenced_v2_result.package.sites)


def test_annualized_integrated_result_json_has_every_alternative(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    payload = json.loads((tmp_path / ANNUALIZED_INTEGRATED_RESULT_FILENAME).read_text())
    assert set(payload["alternatives"].keys()) == {s.alternative_id for s in result.alternative_summaries}
