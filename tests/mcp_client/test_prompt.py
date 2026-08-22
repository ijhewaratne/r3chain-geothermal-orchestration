"""Structural tests for mcp_client/prompt.py -- the workshop prompt must
require the interim disclaimer verbatim and instruct Claude to make
every technical/economic/ranking decision via the tools, never itself
(T5.1B)."""
from __future__ import annotations

from r3chain_geothermal.mcp_client.prompt import render_workshop_prompt
from r3chain_geothermal.mcp_server.tools import GEO_TOOL_NAMES, INTERIM_ARCHITECTURE_DISCLAIMER


def test_prompt_contains_the_interim_disclaimer_verbatim():
    prompt = render_workshop_prompt()
    assert INTERIM_ARCHITECTURE_DISCLAIMER in prompt


def test_prompt_names_all_six_tools():
    prompt = render_workshop_prompt()
    for tool_name in GEO_TOOL_NAMES:
        assert tool_name in prompt


def test_prompt_explicitly_forbids_self_calculation():
    prompt = render_workshop_prompt().lower()
    assert "never calculate, estimate, or approximate" in prompt
    assert "physics" in prompt
    assert "economics" in prompt
    assert "ranking" in prompt


def test_prompt_requires_warnings_to_be_preserved():
    prompt = render_workshop_prompt().lower()
    assert "warning" in prompt
    assert "verbatim" in prompt


def test_prompt_states_the_call_order():
    prompt = render_workshop_prompt()
    order = ["geo_get_capabilities", "geo_validate_pydoublet_result", "geo_run_workflow", "geo_get_run_summary", "geo_get_audit"]
    positions = [prompt.index(name) for name in order]
    assert positions == sorted(positions), "tool names should appear in call order in the prompt text"


def test_prompt_instructs_honest_zero_feasible_and_stopped_handling():
    prompt = render_workshop_prompt().lower()
    assert "zero feasible" in prompt
    assert "stopped" in prompt
    assert "do not invent a" in prompt or "not a failure to paper over" in prompt


def test_prompt_is_deterministic_across_repeated_calls():
    assert render_workshop_prompt() == render_workshop_prompt()


def test_prompt_is_a_plain_string_not_a_template_with_unresolved_placeholders():
    prompt = render_workshop_prompt()
    assert "{" not in prompt
    assert "}" not in prompt
