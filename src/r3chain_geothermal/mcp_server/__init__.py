"""Interim standalone MCP server (T5.1A) -- see `server.py`'s module
docstring for the required architecture disclaimer.

Deliberately does NOT import `mcp` here: this package is importable (and
`tools.py`/`registry.py`/`errors.py`/`schemas.py` fully usable/testable)
without the optional `mcp` extra installed. Only `server.py` -- and
therefore only actually running/importing the live MCP server -- requires
it.
"""
from __future__ import annotations

from .errors import ToolError, ToolErrorCode
from .registry import DEFAULT_MAX_REGISTRY_SIZE, RegistryClosedError, RunEntry, RunRegistry
from .schemas import (
    ArtifactSlice,
    AuditSummary,
    CapabilitiesSummary,
    InfeasibleCandidateSummary,
    PyDoubletValidationSummary,
    RankedCandidateSummary,
    RunSummary,
    SourceProvenanceInput,
)
from .tools import GEO_TOOL_NAMES, GEO_TOOL_REGISTRY, INTERIM_ARCHITECTURE_DISCLAIMER

__all__ = [
    "DEFAULT_MAX_REGISTRY_SIZE",
    "GEO_TOOL_NAMES",
    "GEO_TOOL_REGISTRY",
    "INTERIM_ARCHITECTURE_DISCLAIMER",
    "ArtifactSlice",
    "AuditSummary",
    "CapabilitiesSummary",
    "InfeasibleCandidateSummary",
    "PyDoubletValidationSummary",
    "RankedCandidateSummary",
    "RegistryClosedError",
    "RunEntry",
    "RunRegistry",
    "RunSummary",
    "SourceProvenanceInput",
    "ToolError",
    "ToolErrorCode",
]
