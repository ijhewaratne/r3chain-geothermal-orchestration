"""Full test matrix for mcp_client/claude_desktop.py -- valid JSON, no
absolute/user-specific paths, uses the installed command name (T5.1B)."""
from __future__ import annotations

import json
import os

from r3chain_geothermal.mcp_client.claude_desktop import (
    CLAUDE_DESKTOP_COMMAND,
    CLAUDE_DESKTOP_SERVER_NAME,
    render_claude_desktop_config,
    render_claude_desktop_config_json,
)


def test_render_claude_desktop_config_is_valid_json_serializable():
    config = render_claude_desktop_config()
    serialized = json.dumps(config)
    restored = json.loads(serialized)
    assert restored == config


def test_render_claude_desktop_config_json_is_valid_json_text():
    text = render_claude_desktop_config_json()
    parsed = json.loads(text)
    assert parsed == render_claude_desktop_config()


def test_config_uses_the_installed_command_name_not_sys_executable():
    import sys

    config = render_claude_desktop_config()
    command = config["mcpServers"][CLAUDE_DESKTOP_SERVER_NAME]["command"]
    assert command == "r3chain-geothermal-mcp-server"
    assert command != sys.executable
    assert "python" not in command.lower()


def test_config_has_no_absolute_path_or_user_specific_fragment():
    text = render_claude_desktop_config_json()
    assert "/Users/" not in text
    assert "/home/" not in text
    assert "C:\\" not in text
    assert os.path.expanduser("~") not in text


def test_config_has_no_environment_variable_leakage():
    text = render_claude_desktop_config_json()
    for var in ("HOME", "PATH", "USER", "USERNAME"):
        value = os.environ.get(var)
        if value and len(value) > 3:  # skip trivially short values that could false-positive
            assert value not in text


def test_config_shape_matches_the_standard_mcp_servers_convention():
    config = render_claude_desktop_config()
    assert set(config.keys()) == {"mcpServers"}
    assert CLAUDE_DESKTOP_SERVER_NAME in config["mcpServers"]
    entry = config["mcpServers"][CLAUDE_DESKTOP_SERVER_NAME]
    assert set(entry.keys()) == {"command", "args"}
    assert entry["command"] == CLAUDE_DESKTOP_COMMAND
    assert entry["args"] == []


def test_config_is_deterministic_across_repeated_calls():
    assert render_claude_desktop_config() == render_claude_desktop_config()
    assert render_claude_desktop_config_json() == render_claude_desktop_config_json()
