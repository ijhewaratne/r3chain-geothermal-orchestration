"""Scripted MCP client (T5.1B) -- launches the installed
`r3chain-geothermal-mcp-server` over stdio and runs the exact eight-step
demonstration sequence (see `runner.py`'s module docstring).

Deliberately does NOT import `mcp` here: this package is importable
without the optional `mcp` extra installed. Only `runner.py`'s actual
session functions (and therefore only actually running a session)
require it.
"""
from __future__ import annotations

from .session import SessionRecord, ToolCallRecord, build_session_record, compact_pydoublet_input

__all__ = [
    "SessionRecord",
    "ToolCallRecord",
    "build_session_record",
    "compact_pydoublet_input",
]
