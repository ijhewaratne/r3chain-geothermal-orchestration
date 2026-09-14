"""Fixed-DH-interface drilling-site-optimization correction --
`workflow/fixed_interface_workflow.py`'s own orchestrator, artifact bundle
and CLI dispatch, against the committed config
(config/demo_assumptions_fixed_interface_site_optimization.json) and study
package (config/fixed_interface_site_optimization_synthetic.json). Counts
below (4/4/4/3/16/4/4/3) were measured directly against this fixed
fixture. Implements the task's own required test matrix (numbered
comments below mirror its section numbering)."""
from __future__ import annotations

import json
from pathlib import Path

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow.cli import EXIT_OK, EXIT_WORKFLOW_FAILURE, run_cli
from r3chain_geothermal.workflow.fixed_interface_workflow import (
    FixedInterfaceSiteOptimizationFailure,
    FixedInterfaceSiteOptimizationResult,
    is_fixed_interface_site_optimization_enabled,
    run_fixed_interface_site_optimization,
    write_fixed_interface_site_optimization_artifacts,
)

_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_fixed_interface_site_optimization.json"
_PACKAGE_PATH = _ROOT / "config" / "fixed_interface_site_optimization_synthetic.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_PROVENANCE_PATH = _ROOT / "config" / "demo_source_provenance.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_COUNTS = {
    "site_count": 4, "resource_scenario_count": 4, "generated_route_count": 4, "accepted_route_count": 3,
    "possible_alternative_count": 16, "compatible_alternative_count": 4, "evaluated_alternative_count": 4,
    "feasible_alternative_count": 3,
}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _run() -> FixedInterfaceSiteOptimizationResult:
    result = run_fixed_interface_site_optimization(_raw(), _config(), source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, FixedInterfaceSiteOptimizationResult)
    return result


# ── the config switch itself ─────────────────────────────────────────────────
def test_canonical_config_does_not_enable_fixed_interface_site_optimization():
    canonical = json.loads(_CANONICAL_CONFIG_PATH.read_text())
    assert "fixed_interface_site_optimization" not in canonical
    assert is_fixed_interface_site_optimization_enabled(canonical) is False


def test_committed_config_enables_it_and_names_the_committed_package():
    config = _config()
    assert is_fixed_interface_site_optimization_enabled(config) is True
    assert config["fixed_interface_site_optimization"]["package_path"] == \
        "config/fixed_interface_site_optimization_synthetic.json"


# ── counts, determinism ──────────────────────────────────────────────────────
def test_committed_fixture_produces_the_exact_measured_counts():
    result = _run()
    assert result.counts.model_dump() == _EXPECTED_COUNTS


def test_run_id_matches_audit_run_id_and_is_content_addressed():
    result = _run()
    assert result.run_id == result.audit.run_id
    assert result.run_id.startswith("r3chain-run-")


# ── Test 7 (task spec): deterministic reproducibility ────────────────────────
def test_repeated_runs_produce_identical_run_id_ranking_and_metrics():
    result_1 = _run()
    result_2 = _run()
    assert result_1.run_id == result_2.run_id
    assert result_1.decision.model_dump() == result_2.decision.model_dump()
    ids_1 = [a.identity.alternative_id for a in result_1.alternatives]
    ids_2 = [a.identity.alternative_id for a in result_2.alternatives]
    assert ids_1 == ids_2
    # created_at timestamps legitimately differ between two calls (module
    # docstring precedent, workflow/core.py: determinism is achieved by
    # EXCLUDING every created_at occurrence from any identity/comparison,
    # not by making every timestamp deterministic) -- compare the
    # scientific fields only.
    econ_1 = [
        (a.economics.annualised_cost_total_eur_per_a, a.economics.indicative_lcoh_eur_per_kwh) if a.economics else None
        for a in result_1.alternatives
    ]
    econ_2 = [
        (a.economics.annualised_cost_total_eur_per_a, a.economics.indicative_lcoh_eur_per_kwh) if a.economics else None
        for a in result_2.alternatives
    ]
    assert econ_1 == econ_2


# ── Test 1 (task spec): fixed network-entry invariant, end to end ───────────
def test_every_alternative_shares_the_same_fixed_network_entry():
    result = _run()
    attachment_ids = {a.identity.attachment_id for a in result.alternatives}
    assert attachment_ids == {result.fixed_integration_station.station_id} == {"trunk_1"}


# ── Test 2 (task spec): drilling location changes transmission distance ─────
def test_different_sites_produce_different_distances_to_the_fixed_station():
    result = _run()
    lengths = {
        a.identity.surface_site_id: a.candidate_result.candidate.surface_connection_length_m
        for a in result.alternatives if a.candidate_result is not None
    }
    assert len(set(lengths.values())) >= 2  # at least two distinct distances among feasible candidates
    assert len(lengths) == len({round(v, 6) for v in lengths.values()})  # every feasible site's distance is unique here


# ── Test 5 (task spec): geothermal differences propagate ────────────────────
def test_different_scenarios_propagate_distinct_geothermal_metrics():
    result = _run()
    coverage_by_alt = {
        a.identity.alternative_id: a.candidate_result.geothermal_coverage_fraction
        for a in result.alternatives if a.candidate_result is not None
    }
    assert len(set(coverage_by_alt.values())) > 1  # different (site, scenario) pairs yield different coverage


# ── Test 6 (task spec): infeasible candidate rejected before economics ──────
def test_low_temperature_scenario_is_rejected_before_economics():
    result = _run()
    infeasible = [a for a in result.alternatives if not a.feasible]
    assert infeasible
    rejected = next(a for a in infeasible if a.identity.surface_site_id == "site_beta")
    assert rejected.failure_code == "HX_SUPPLY_TEMPERATURE_INFEASIBLE"
    assert rejected.economics is None
    assert rejected.stage_reached.value == "CALCULATE_HX_COUPLING_BOUNDARY"


def test_evaluated_equals_compatible_and_feasible_subset_of_evaluated():
    result = _run()
    assert len(result.alternatives) == result.counts.compatible_alternative_count
    n_feasible = sum(1 for a in result.alternatives if a.feasible)
    assert n_feasible == result.counts.feasible_alternative_count


def test_ranking_never_calls_a_result_the_best_network_attachment():
    """The output must speak in terms of the drilling SITE, never an
    attachment/junction, when naming a preferred alternative."""
    result = _run()
    assert result.decision.preferred_alternative_id is not None
    preferred = next(a for a in result.alternatives if a.identity.alternative_id == result.decision.preferred_alternative_id)
    assert preferred.identity.surface_site_id == "site_alpha"


# ── stopping failures ────────────────────────────────────────────────────────
def test_missing_package_path_key_fails_loudly_not_with_a_crash():
    config = _config()
    del config["fixed_interface_site_optimization"]["package_path"]
    result = run_fixed_interface_site_optimization(_raw(), config, source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, FixedInterfaceSiteOptimizationFailure)
    assert result.failure_code == "JOINT_STUDY_PACKAGE_INVALID"
    assert result.stage == "load_and_validate_joint_study_package"


def test_a_multi_attachment_package_is_rejected_at_station_resolution_not_silently_run(tmp_path):
    """Pointing this mode's OWN config at the v2 (4-attachment) package
    must fail loudly at station resolution -- never silently fall back to
    treating one of the four attachments as fixed."""
    config = {**_config(), "fixed_interface_site_optimization": {
        "enabled": True, "package_path": "config/joint_study_synthetic_v2.json",
    }}
    result = run_fixed_interface_site_optimization(_raw(), config, source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, FixedInterfaceSiteOptimizationFailure)
    assert result.failure_code == "STATION_AMBIGUOUS"
    assert result.stage == "resolve_fixed_integration_station"


def test_resource_input_hash_mismatch_is_reported_before_pydoublet_parsing():
    tampered_raw = dict(_raw())
    tampered_raw["extra_tamper_field_never_used_elsewhere"] = "tamper"
    result = run_fixed_interface_site_optimization(tampered_raw, _config(), source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, FixedInterfaceSiteOptimizationFailure)
    assert result.failure_code == "PYDOUBLET_RAW_HASH_MISMATCH"
    assert result.stage == "verify_resource_input_hash"


# ── artifact bundle ───────────────────────────────────────────────────────────
_EXPECTED_ARTIFACT_FILES = {
    "pydoublet_input.json", "config_snapshot.json", "joint_study_snapshot.json", "fixed_interface_result.json",
    "fixed_integration_station.json", "candidate_sites.json", "candidate_sites.csv", "geothermal_results.json",
    "candidate_network_feasibility.json", "candidate_economics.json", "drilling_site_ranking.json",
    "drilling_site_ranking.csv", "research_findings.md", "audit.json",
}


def test_write_artifacts_writes_every_file_and_a_valid_manifest(tmp_path):
    result = _run()
    package_raw = json.loads(_PACKAGE_PATH.read_text())
    manifest = write_fixed_interface_site_optimization_artifacts(result, _raw(), _config(), package_raw, tmp_path)
    assert set(manifest.files.keys()) == _EXPECTED_ARTIFACT_FILES
    for filename in _EXPECTED_ARTIFACT_FILES:
        assert (tmp_path / filename).is_file()
    assert (tmp_path / "manifest.json").is_file()


def test_write_artifacts_is_deterministic_apart_from_timestamps(tmp_path):
    result = _run()
    package_raw = json.loads(_PACKAGE_PATH.read_text())
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    manifest_1 = write_fixed_interface_site_optimization_artifacts(result, _raw(), _config(), package_raw, dir_a)
    manifest_2 = write_fixed_interface_site_optimization_artifacts(result, _raw(), _config(), package_raw, dir_b)
    assert manifest_1.bundle_scientific_sha256 == manifest_2.bundle_scientific_sha256


def test_failure_bundle_writes_only_the_core_files(tmp_path):
    config = _config()
    del config["fixed_interface_site_optimization"]["package_path"]
    result = run_fixed_interface_site_optimization(_raw(), config, source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, FixedInterfaceSiteOptimizationFailure)
    manifest = write_fixed_interface_site_optimization_artifacts(result, _raw(), config, {}, tmp_path)
    assert set(manifest.files.keys()) == {
        "pydoublet_input.json", "config_snapshot.json", "joint_study_snapshot.json",
        "fixed_interface_result.json", "audit.json",
    }
    assert not (tmp_path / "fixed_integration_station.json").exists()


def test_research_findings_states_the_fixed_point_and_disables_attachment_optimization(tmp_path):
    result = _run()
    package_raw = json.loads(_PACKAGE_PATH.read_text())
    write_fixed_interface_site_optimization_artifacts(result, _raw(), _config(), package_raw, tmp_path)
    text = (tmp_path / "research_findings.md").read_text()
    assert "Fixed DH integration point:** `trunk_1`" in text
    assert "Network attachment optimization:** disabled for this methodology" in text
    assert "SYNTHETIC" in text
    assert "Fündigkeitsrisiko" in text


def test_drilling_site_ranking_csv_has_one_row_per_evaluated_alternative(tmp_path):
    import csv
    result = _run()
    package_raw = json.loads(_PACKAGE_PATH.read_text())
    write_fixed_interface_site_optimization_artifacts(result, _raw(), _config(), package_raw, tmp_path)
    with (tmp_path / "drilling_site_ranking.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(result.alternatives)
    assert {row["network_entry_attachment_id"] for row in rows} == {"trunk_1"}


def test_candidate_sites_csv_lists_every_declared_site_with_a_depth_and_distance(tmp_path):
    import csv
    result = _run()
    package_raw = json.loads(_PACKAGE_PATH.read_text())
    write_fixed_interface_site_optimization_artifacts(result, _raw(), _config(), package_raw, tmp_path)
    with (tmp_path / "candidate_sites.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert {row["site_id"] for row in rows} == {s.site_id for s in result.package.sites}
    alpha_row = next(r for r in rows if r["site_id"] == "site_alpha")
    assert alpha_row["target_depth_m"] != ""
    assert float(alpha_row["distance_to_fixed_station_m"]) > 0


# ── CLI dispatch ──────────────────────────────────────────────────────────────
def test_cli_dispatches_to_fixed_interface_site_optimization_when_enabled(tmp_path):
    output_dir = tmp_path / "out"
    exit_code = run_cli([
        "--input", str(_REPAIRED_PATH), "--config", str(_CONFIG_PATH),
        "--provenance", str(_PROVENANCE_PATH), "--output-dir", str(output_dir),
    ])
    assert exit_code == EXIT_OK
    assert (output_dir / "fixed_interface_result.json").is_file()
    assert (output_dir / "drilling_site_ranking.csv").is_file()
    assert (output_dir / "manifest.json").is_file()


def test_cli_run_twice_yields_identical_counts_and_bundle_hash(tmp_path):
    outputs = []
    for label in ("run1", "run2"):
        output_dir = tmp_path / label
        exit_code = run_cli([
            "--input", str(_REPAIRED_PATH), "--config", str(_CONFIG_PATH),
            "--provenance", str(_PROVENANCE_PATH), "--output-dir", str(output_dir),
        ])
        assert exit_code == EXIT_OK
        outputs.append(output_dir)

    manifests = [json.loads((d / "manifest.json").read_text()) for d in outputs]
    assert manifests[0]["bundle_scientific_sha256"] == manifests[1]["bundle_scientific_sha256"]

    results = [json.loads((d / "fixed_interface_result.json").read_text()) for d in outputs]
    assert results[0]["run_id"] == results[1]["run_id"]
    for result in results:
        assert result["counts"] == _EXPECTED_COUNTS


def test_cli_reports_stopping_failure_as_exit_code_2(tmp_path):
    config = _config()
    del config["fixed_interface_site_optimization"]["package_path"]
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    output_dir = tmp_path / "out"
    exit_code = run_cli([
        "--input", str(_REPAIRED_PATH), "--config", str(config_path),
        "--provenance", str(_PROVENANCE_PATH), "--output-dir", str(output_dir),
    ])
    assert exit_code == EXIT_WORKFLOW_FAILURE
    assert (output_dir / "manifest.json").is_file()


def test_fixed_interface_site_optimization_takes_precedence_when_multiple_modes_enabled(tmp_path):
    """`_run_fixed_interface_site_optimization_cli`'s own `package_root`
    is derived from `--config`'s own path as
    `config_path.resolve().parent.parent` -- so the synthetic config file
    must live inside a `config/` directory whose parent plays the role of
    "repo root," mirroring the real
    `config/demo_assumptions_fixed_interface_site_optimization.json`
    layout, with the committed study packages and base-assumptions file
    copied alongside it so every package-relative path still resolves."""
    import shutil

    fake_root = tmp_path / "fake_repo_root"
    fake_config_dir = fake_root / "config"
    fake_config_dir.mkdir(parents=True)
    shutil.copy(_PACKAGE_PATH, fake_config_dir / _PACKAGE_PATH.name)
    shutil.copy(_ROOT / "config" / "joint_study_synthetic_v2.json", fake_config_dir / "joint_study_synthetic_v2.json")
    shutil.copy(_CANONICAL_CONFIG_PATH, fake_config_dir / _CANONICAL_CONFIG_PATH.name)

    config = _config()
    config["joint_study_v2"] = {"enabled": True, "package_path": "config/joint_study_synthetic_v2.json"}
    config_path = fake_config_dir / "config.json"
    config_path.write_text(json.dumps(config))
    output_dir = tmp_path / "out"
    exit_code = run_cli([
        "--input", str(_REPAIRED_PATH), "--config", str(config_path),
        "--provenance", str(_PROVENANCE_PATH), "--output-dir", str(output_dir),
    ])
    assert exit_code == EXIT_OK
    # The fixed-interface layer's own richer bundle (fixed_integration_station.json)
    # is proof the fixed-interface path ran, not v2's.
    assert (output_dir / "fixed_integration_station.json").is_file()
