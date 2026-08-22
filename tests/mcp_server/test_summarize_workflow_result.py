"""`summarize_workflow_result()` (T5.1B correction #2): the WorkflowResult/
WorkflowFailure -> RunSummary mapping was made public and exported from
`mcp_server/__init__.py` specifically so `mcp_client.cli_fallback` could
reuse it instead of importing a private name -- these tests pin its public
contract and its parity with what `run_workflow_tool()` itself returns."""
from __future__ import annotations

import json
from pathlib import Path

from r3chain_geothermal.mcp_server import summarize_workflow_result, tools
from r3chain_geothermal.mcp_server.config import load_fixed_server_config
from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.schemas import RunSummary, SourceProvenanceInput
from r3chain_geothermal.workflow import (
    CANDIDATE_COMPARISON_CSV_FILENAME,
    NETWORK_CANDIDATES_SVG_FILENAME,
    RECOMMENDATION_MD_FILENAME,
    WorkflowResult,
    render_candidate_comparison_csv,
    render_network_candidates_svg,
    render_recommendation_markdown,
    run_workflow,
    write_workflow_artifacts,
)

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance(**overrides) -> SourceProvenanceInput:
    fields = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    fields.update(overrides)
    return SourceProvenanceInput(**fields)


def test_summarize_workflow_result_is_exported_from_the_package_root():
    assert summarize_workflow_result is tools.summarize_workflow_result


def test_summarize_workflow_result_matches_run_workflow_tool_worked_case(tmp_path):
    fixed_config = load_fixed_server_config()
    registry = RunRegistry(max_size=10, root_dir=tmp_path / "via-tool")
    via_tool = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)

    result = run_workflow(_raw(), fixed_config, source_provenance=tools._source_provenance_from_input(_provenance()))
    extra_artifacts = None
    if isinstance(result, WorkflowResult):
        extra_artifacts = {
            CANDIDATE_COMPARISON_CSV_FILENAME: render_candidate_comparison_csv(result),
            NETWORK_CANDIDATES_SVG_FILENAME: render_network_candidates_svg(result),
            RECOMMENDATION_MD_FILENAME: render_recommendation_markdown(result),
        }
    direct_dir = tmp_path / "direct"
    direct_dir.mkdir()
    manifest = write_workflow_artifacts(result, _raw(), fixed_config, direct_dir, extra_artifacts=extra_artifacts)
    artifact_filenames = frozenset(manifest.files.keys()) | {"manifest.json"}
    direct = summarize_workflow_result(result, artifact_filenames, reused_existing_run=False)
    direct = direct.model_copy(update={"run_id": via_tool.run_id, "bundle_scientific_sha256": via_tool.bundle_scientific_sha256})

    assert isinstance(direct, RunSummary)
    assert direct == via_tool


def test_summarize_workflow_result_matches_run_workflow_tool_stopped_case(tmp_path):
    fixed_config = load_fixed_server_config()
    registry = RunRegistry(max_size=10, root_dir=tmp_path / "via-tool")
    via_tool = tools.run_workflow_tool({}, _provenance(), fixed_config=fixed_config, registry=registry)

    result = run_workflow({}, fixed_config, source_provenance=tools._source_provenance_from_input(_provenance()))
    direct_dir = tmp_path / "direct"
    direct_dir.mkdir()
    manifest = write_workflow_artifacts(result, {}, fixed_config, direct_dir)
    artifact_filenames = frozenset(manifest.files.keys()) | {"manifest.json"}
    direct = summarize_workflow_result(result, artifact_filenames, reused_existing_run=False)
    direct = direct.model_copy(update={"run_id": via_tool.run_id, "bundle_scientific_sha256": manifest.bundle_scientific_sha256})

    assert direct.workflow_status == "stopped" == via_tool.workflow_status
    assert direct == via_tool


def test_summarize_workflow_result_no_longer_has_a_private_alias():
    assert not hasattr(tools, "_run_summary_from_result")
