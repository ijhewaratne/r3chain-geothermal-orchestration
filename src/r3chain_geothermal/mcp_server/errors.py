"""Structured tool-error contract for the interim MCP server (T5.1A).

Every `geo_` tool's return type is a status-discriminated union of a
success model and `ToolError` -- this project's own established
`BoundaryResult` idiom (`WorkflowBoundaryResult`,
`CandidateEvaluationBoundaryResult`, etc.), reused here so no tool ever
raises a bare exception across the MCP boundary for an expected failure
condition.

`ToolError.message` is always built from an already-typed upstream
`message`/`failure_code` string -- NEVER `str(exc)` on an arbitrary caught
exception, never `traceback.format_exc()`. No field here may ever contain
a stack-trace fragment or an absolute filesystem path.

Exactly six codes exist, each one actually reachable from at least one of
the six `geo_` tools (`tests/mcp_server/test_errors.py` pins the exact
set). A stopped workflow (`RunSummary.workflow_status == "stopped"`) is
deliberately NOT one of them -- CLAUDE.md's "completed with zero feasible
candidates is not an error" principle, extended here to "stopped is not
an error either, it is an audited, typed outcome" -- so no code for it
belongs in this enum; adding one that no tool can ever return would be a
misleading public contract.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolErrorCode(str, Enum):
    PYDOUBLET_VALIDATION_FAILED = "PYDOUBLET_VALIDATION_FAILED"
    """parse_pydoublet_result() returned a PyDoubletCouplingFailure --
    the upstream failure_code/message are embedded verbatim in `details`."""
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    """An unknown run_id was supplied to geo_get_run_summary/geo_get_audit/
    geo_get_artifact. Recoverable: resubmitting the same
    pydoublet_raw_result/source_provenance to geo_run_workflow
    deterministically reconstructs the identical run_id."""
    FORBIDDEN_ARTIFACT = "FORBIDDEN_ARTIFACT"
    """`filename` is outside the exact allow-list of known artifact
    filenames (path traversal, a hidden file, or any other unexpected
    name) -- checked before any filesystem access."""
    ARTIFACT_NOT_AVAILABLE = "ARTIFACT_NOT_AVAILABLE"
    """`filename` IS one of the known artifact names, but this specific
    run never wrote it (e.g. a presentation file requested for a stopped
    workflow, which only publishes the 5 core/audit files)."""
    INVALID_INPUT = "INVALID_INPUT"
    """A tool-level input shape problem this server itself detects before
    calling any deterministic layer function (e.g. source_provenance
    fields that fail SourceProvenance's own typed validation)."""
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
    """A genuinely unexpected internal failure -- a solver/programming
    defect -- reachable only from the narrow catch-all around
    run_workflow() itself, mirroring cli.py's EXIT_UNEXPECTED_ERROR
    boundary. Never used to report a config/input problem."""


class ToolError(BaseModel):
    """The one failure shape every `geo_` tool returns -- never raised,
    always the `status == "error"` half of that tool's own discriminated
    return type."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["error"] = "error"
    code: ToolErrorCode
    message: str
    stage: str
    recoverable: bool
    details: dict[str, Any] = Field(default_factory=dict)
    """Upstream typed failure content (e.g. an upstream failure_code/
    message pair), embedded verbatim -- never paraphrased, never a raw
    exception repr, never a path."""
