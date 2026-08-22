"""Compact, machine-readable session-record schema (T5.1B).

Records the order of tool calls a session made, compact per-call inputs/
outputs, warnings, execution route (`"mcp"` or `"cli_fallback"`), and a
deterministic recommendation -- deliberately NEVER the raw PyDoublet
result, an absolute filesystem path, or environment data:

- `geo_run_workflow`/`geo_validate_pydoublet_result`'s `compact_input` is
  `{raw_result_sha256, source_provenance}` -- the same
  `hashing.canonical_raw_result_sha256()` every other layer already uses,
  never re-implemented, never the raw dict itself.
- `geo_get_artifact`'s `compact_output` per page is `{filename, offset,
  bytes_fetched, total_length}` -- never the fetched text.
- Every other tool's `compact_output` is that tool's own ALREADY-compact
  response (`RunSummary`/`CapabilitiesSummary`/`AuditSummary`/
  `PyDoubletValidationSummary`), `model_dump()`-ed as-is -- T5.1A's own
  tools never return the enormous full `WorkflowResult`, so there is
  nothing further to compact there.

`recommendation_text` is built by `_build_recommendation_text()` below --
a fixed, deterministic Python string template over already-typed
`RunSummary` fields only, never an LLM call, matching
`workflow/recommendation.py`'s own discipline (CLAUDE.md: "Claude may
orchestrate and explain results but must never invent simulation
results, feasibility decisions, costs, or rankings").
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import CouplingWarning, SourceProvenance
from ..hashing import canonical_raw_result_sha256
from ..mcp_server.schemas import InfeasibleCandidateSummary, RankedCandidateSummary, RunSummary

SESSION_RECORD_SCHEMA_VERSION = "1.0.0"


def compact_pydoublet_input(pydoublet_raw_result: dict[str, Any], source_provenance: SourceProvenance) -> dict[str, Any]:
    """The one place raw_result_sha256 is computed for session-record
    purposes -- reuses `canonical_raw_result_sha256` verbatim, the SAME
    function `mcp_server.tools.run_workflow_tool()` itself uses to derive
    `run_id`, never a separate/competing hash implementation."""
    return {
        "raw_result_sha256": canonical_raw_result_sha256(pydoublet_raw_result),
        "source_provenance": source_provenance.model_dump(mode="json"),
    }


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order: int
    """1-based, matches this record's position in the 8-step sequence."""
    tool_name: str
    compact_input: dict[str, Any]
    compact_output: dict[str, Any]
    status: Literal["success", "error"]


class SessionRecord(BaseModel):
    """The complete, compact record of one client session -- published as
    `session_record.json` by `cli.py`."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SESSION_RECORD_SCHEMA_VERSION
    execution_route: Literal["mcp", "cli_fallback"]
    server_name: str | None
    protocol_version: str | None
    tools_discovered: list[str]
    """`tools/list`'s own result (step 2) -- always the six `geo_` names
    for a genuine MCP session; `[]` for `cli_fallback` (no protocol
    handshake happened)."""
    tool_calls: list[ToolCallRecord]
    run_id: str | None
    bundle_scientific_sha256: str | None
    workflow_status: Literal["completed", "stopped"] | None
    preferred_candidate_id: str | None
    ranked: list[RankedCandidateSummary]
    infeasible: list[InfeasibleCandidateSummary]
    warnings: list[CouplingWarning]
    interim_architecture_disclaimer: str
    recommendation_text: str
    created_at: datetime


def build_recommendation_text(run_summary: RunSummary | None, *, execution_route: Literal["mcp", "cli_fallback"]) -> str:
    """Deterministic, fixed Python string template over `RunSummary`
    fields only -- never an LLM call. `run_summary` is `None` only for a
    session that never reached a workflow outcome at all (should not
    normally happen once this is called; guarded defensively)."""
    if run_summary is None:
        return "No workflow outcome was reached in this session."
    prefix = "" if execution_route == "mcp" else "[via deterministic CLI fallback] "
    if run_summary.workflow_status == "stopped":
        return (
            f"{prefix}The workflow stopped before candidate evaluation "
            f"(run_id={run_summary.run_id}, failure_code={run_summary.stopping_failure_code}). "
            f"No candidate recommendation is made."
        )
    if not run_summary.ranked:
        return (
            f"{prefix}The workflow completed but no candidate is feasible "
            f"(run_id={run_summary.run_id}). No recommendation is made -- "
            f"a completed evaluation with zero feasible candidates is a valid, honest result."
        )
    winner = run_summary.ranked[0]
    return (
        f"{prefix}{winner.candidate_id} is preferred (rank 1 of {len(run_summary.ranked)} "
        f"feasible candidate(s), indicative LCOH "
        f"{winner.indicative_lcoh_eur_per_mwh:.4f} EUR/MWh, run_id={run_summary.run_id})."
    )


def build_session_record(
    *,
    execution_route: Literal["mcp", "cli_fallback"],
    server_name: str | None,
    protocol_version: str | None,
    tools_discovered: list[str] | None = None,
    tool_calls: list[ToolCallRecord],
    run_summary: RunSummary | None,
    created_at: datetime,
    interim_architecture_disclaimer: str,
) -> SessionRecord:
    return SessionRecord(
        execution_route=execution_route,
        server_name=server_name,
        protocol_version=protocol_version,
        tools_discovered=tools_discovered if tools_discovered is not None else [],
        tool_calls=tool_calls,
        run_id=run_summary.run_id if run_summary is not None else None,
        bundle_scientific_sha256=run_summary.bundle_scientific_sha256 if run_summary is not None else None,
        workflow_status=run_summary.workflow_status if run_summary is not None else None,
        preferred_candidate_id=run_summary.preferred_candidate_id if run_summary is not None else None,
        ranked=run_summary.ranked if run_summary is not None else [],
        infeasible=run_summary.infeasible if run_summary is not None else [],
        warnings=run_summary.warnings if run_summary is not None else [],
        interim_architecture_disclaimer=interim_architecture_disclaimer,
        recommendation_text=build_recommendation_text(run_summary, execution_route=execution_route),
        created_at=created_at,
    )
