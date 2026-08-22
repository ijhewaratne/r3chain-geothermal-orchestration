"""Deterministic CLI fallback (T5.1B) -- used ONLY when the MCP transport
itself is unavailable (server-start failure, mid-session transport
failure) and the caller opted in (`allow_cli_fallback=True`). NEVER
triggered by a typed workflow/domain outcome (a `ToolError`, or a
completed workflow with `workflow_status == "stopped"`/zero feasible
candidates) -- those are valid, audited results reachable only through
`runner.py`'s own real MCP path.

Calls `workflow.run_workflow()` + `workflow.write_workflow_artifacts()`
DIRECTLY -- the exact same functions `mcp_server.tools.run_workflow_tool()`
itself calls, via the exact same
`mcp_server.config.load_fixed_server_config()` fixed config -- never
subprocesses the CLI, never reimplements physics/economics/ranking. This
is what makes "fallback output must reproduce the same deterministic
identifiers and ranking" true by construction rather than by careful
re-derivation.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..contracts import SourceProvenance
from ..mcp_server.config import load_fixed_server_config

# Public helper (T5.1B-authorized addition to mcp_server/tools.py): the ONE
# WorkflowResult/WorkflowFailure -> RunSummary mapping, shared by
# run_workflow_tool() and this fallback path so they cannot silently drift.
from ..mcp_server.tools import summarize_workflow_result
from ..workflow import (
    CANDIDATE_COMPARISON_CSV_FILENAME,
    MANIFEST_FILENAME,
    NETWORK_CANDIDATES_SVG_FILENAME,
    RECOMMENDATION_MD_FILENAME,
    WorkflowResult,
    render_candidate_comparison_csv,
    render_network_candidates_svg,
    render_recommendation_markdown,
    run_workflow,
    write_workflow_artifacts,
)
from .session import SessionRecord, build_session_record


def run_cli_fallback_session(
    pydoublet_raw_result: dict[str, Any],
    source_provenance: SourceProvenance,
    *,
    interim_architecture_disclaimer: str,
) -> SessionRecord:
    """Runs the deterministic pipeline directly (no MCP transport at
    all), returning a `SessionRecord` with `execution_route="cli_fallback"`
    and an EMPTY `tool_calls` list -- the honest representation: no MCP
    tool was actually invoked on this path, so there is nothing to log as
    a tool call. `run_id`/`bundle_scientific_sha256`/ranking are identical
    to what `geo_run_workflow` would have produced for the same inputs,
    by construction (same functions, same fixed config)."""
    fixed_config = load_fixed_server_config()
    result = run_workflow(pydoublet_raw_result, fixed_config, source_provenance=source_provenance)

    with tempfile.TemporaryDirectory(prefix="r3chain-mcp-demo-fallback-") as td:
        run_dir = Path(td)
        extra_artifacts: dict[str, bytes] | None = None
        if isinstance(result, WorkflowResult):
            extra_artifacts = {
                CANDIDATE_COMPARISON_CSV_FILENAME: render_candidate_comparison_csv(result),
                NETWORK_CANDIDATES_SVG_FILENAME: render_network_candidates_svg(result),
                RECOMMENDATION_MD_FILENAME: render_recommendation_markdown(result),
            }
        manifest = write_workflow_artifacts(result, pydoublet_raw_result, fixed_config, run_dir, extra_artifacts=extra_artifacts)
        artifact_filenames = frozenset(manifest.files.keys()) | {MANIFEST_FILENAME}
        run_summary = summarize_workflow_result(result, artifact_filenames, reused_existing_run=False)
        run_summary = run_summary.model_copy(update={"bundle_scientific_sha256": manifest.bundle_scientific_sha256})

    return build_session_record(
        execution_route="cli_fallback",
        server_name=None,
        protocol_version=None,
        tool_calls=[],
        run_summary=run_summary,
        created_at=datetime.now(timezone.utc),
        interim_architecture_disclaimer=interim_architecture_disclaimer,
    )
