"""Claude Desktop MCP configuration template (T5.1B).

Uses the INSTALLED command name (`r3chain-geothermal-mcp-server`, the
console script registered by `pyproject.toml`'s `[project.scripts]`),
never `sys.executable` or any other machine-specific absolute path --
this file is meant to be copied to another machine's Claude Desktop
config, so it must work anywhere the package was installed with the
`mcp` extra, with no editing required.
"""
from __future__ import annotations

import json
from typing import Any

CLAUDE_DESKTOP_SERVER_NAME = "r3chain-geothermal"
CLAUDE_DESKTOP_COMMAND = "r3chain-geothermal-mcp-server"


def render_claude_desktop_config() -> dict[str, Any]:
    """The `mcpServers` fragment a user adds to their own Claude Desktop
    `claude_desktop_config.json` -- a pure, JSON-serializable dict, no
    absolute paths, no environment-specific data."""
    return {
        "mcpServers": {
            CLAUDE_DESKTOP_SERVER_NAME: {
                "command": CLAUDE_DESKTOP_COMMAND,
                "args": [],
            },
        },
    }


def render_claude_desktop_config_json(*, indent: int = 2) -> str:
    return json.dumps(render_claude_desktop_config(), indent=indent) + "\n"
