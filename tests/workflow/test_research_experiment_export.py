"""Phase 7 tests for workflow.research_experiment_export (RA-ART),
R3-CHAIN Final Research-Alignment Implementation Specification."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow.research_experiment import ResearchExperimentResult, run_research_experiment
from r3chain_geothermal.workflow.research_experiment_export import (
    AUDIT_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    MANIFEST_FILENAME,
    PYDOUBLET_INPUT_FILENAME,
    RESEARCH_EXPERIMENT_RESULT_FILENAME,
    ResearchExperimentManifestRecord,
    write_research_experiment_artifacts,
)

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "research_experiment_synthetic.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


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


def test_write_research_experiment_artifacts_writes_every_file_and_a_valid_manifest(tmp_path) -> None:
    result, config, raw = _run()
    manifest = write_research_experiment_artifacts(result, raw, config, tmp_path)
    assert isinstance(manifest, ResearchExperimentManifestRecord)
    assert manifest.run_id == result.run_id
    for filename in (
        PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, RESEARCH_EXPERIMENT_RESULT_FILENAME, AUDIT_FILENAME,
        MANIFEST_FILENAME,
    ):
        assert (tmp_path / filename).exists()
    assert manifest.files.keys() == set(manifest.files.keys())  # sanity: files is a proper dict
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


def test_report_markdown_carries_the_synthetic_disclaimer(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    report_text = (tmp_path / "research_experiment_report.md").read_text()
    assert "SYNTHETIC" in report_text
    assert result.run_id in report_text


def test_alternative_comparison_csv_has_one_row_per_alternative(tmp_path) -> None:
    result, config, raw = _run()
    write_research_experiment_artifacts(result, raw, config, tmp_path)
    csv_text = (tmp_path / "alternative_annualized_comparison.csv").read_text()
    rows = [line for line in csv_text.splitlines() if line]
    assert len(rows) == len(result.alternative_summaries) + 1  # +1 header
