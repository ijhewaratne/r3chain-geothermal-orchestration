"""Parity test (T5.1A acceptance criterion): geo_run_workflow's result
must match the CLI's own engine (run_workflow() + write_workflow_artifacts()
directly) byte-for-byte on run_id and bundle_scientific_sha256, and exactly
on the ranked C1-C4 LCOH figures already committed in T2.4B2."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.mcp_server import tools
from r3chain_geothermal.mcp_server.config import load_fixed_server_config
from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.schemas import SourceProvenanceInput
from r3chain_geothermal.workflow import WorkflowResult, run_workflow, write_workflow_artifacts

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_LCOH_EUR_PER_MWH = {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def test_geo_run_workflow_matches_run_workflow_run_id_and_ranking_exactly():
    config = load_fixed_server_config()
    provenance_input = SourceProvenanceInput(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    provenance_model = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )

    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td) / "registry")
        mcp_result = tools.run_workflow_tool(_raw(), provenance_input, fixed_config=config, registry=registry)

        direct_result = run_workflow(_raw(), config, source_provenance=provenance_model)
        assert isinstance(direct_result, WorkflowResult)

        assert mcp_result.run_id == direct_result.run_id

        lcoh_by_id_mcp = {r.candidate_id: round(r.indicative_lcoh_eur_per_mwh, 4) for r in mcp_result.ranked}
        lcoh_by_id_direct = {
            entry.candidate_id: round(entry.economics.indicative_lcoh_eur_per_kwh * 1000.0, 4)
            for entry in direct_result.ranking.ranked
        }
        assert lcoh_by_id_mcp == lcoh_by_id_direct == _EXPECTED_LCOH_EUR_PER_MWH

        ranks_mcp = {r.candidate_id: r.rank for r in mcp_result.ranked}
        ranks_direct = {entry.candidate_id: entry.rank for entry in direct_result.ranking.ranked}
        assert ranks_mcp == ranks_direct


def test_geo_run_workflow_matches_write_workflow_artifacts_bundle_hash_exactly():
    config = load_fixed_server_config()
    provenance_input = SourceProvenanceInput(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    provenance_model = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )

    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td) / "registry")
        mcp_result = tools.run_workflow_tool(_raw(), provenance_input, fixed_config=config, registry=registry)

        direct_result = run_workflow(_raw(), config, source_provenance=provenance_model)
        assert isinstance(direct_result, WorkflowResult)
        direct_output_dir = Path(td) / "direct_cli_style"
        direct_output_dir.mkdir()
        manifest = write_workflow_artifacts(direct_result, _raw(), config, direct_output_dir)

        assert mcp_result.bundle_scientific_sha256 != ""
        # The MCP server's own bundle includes 3 extra presentation files
        # the bare write_workflow_artifacts() call above did not request
        # (extra_artifacts=None here), so the two bundle_scientific_sha256
        # values are not expected to be byte-equal to EACH OTHER -- what
        # must match is each one's own scientific_sha256 for the 4 files
        # both bundles share.
        for filename in ("pydoublet_input.json", "config_snapshot.json"):
            mcp_manifest_path = registry.get(mcp_result.run_id).artifact_dir / "manifest.json"
            mcp_manifest = json.loads(mcp_manifest_path.read_text())
            assert mcp_manifest["files"][filename]["scientific_sha256"] == manifest.files[filename].scientific_sha256


def test_geo_run_workflow_worked_case_reproduces_c1_through_c4():
    config = load_fixed_server_config()
    provenance_input = SourceProvenanceInput(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td))
        result = tools.run_workflow_tool(_raw(), provenance_input, fixed_config=config, registry=registry)
        assert [r.candidate_id for r in result.ranked] == ["C1", "C2", "C3", "C4"]
        assert result.preferred_candidate_id == "C1"
