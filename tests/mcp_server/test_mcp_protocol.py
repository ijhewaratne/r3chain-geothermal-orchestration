"""Real stdio MCP protocol tests (T5.1A) -- a genuine `initialize` +
`tools/list` + `tools/call` round trip against the actual built server, via
the official `mcp` client SDK (matching the spike's own throwaway-client
precedent, `docs/spikes/mcp-entrypoint-spike.md` §3). Requires the optional
`mcp` extra; skipped cleanly if it is not installed."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _server_params() -> "StdioServerParameters":
    return StdioServerParameters(command=sys.executable, args=["-m", "r3chain_geothermal.mcp_server.server"])


async def _run_session(coro_body):
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro_body(session)


def test_initialize_reports_the_server_name_and_a_protocol_version():
    async def _connect_and_initialize():
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                return await session.initialize()

    init_result = asyncio.run(_connect_and_initialize())
    assert init_result.serverInfo.name == "r3chain-geothermal-mcp"
    assert init_result.protocolVersion


def test_tools_list_returns_exactly_the_six_geo_tools():
    async def body(session: "ClientSession"):
        return await session.list_tools()

    tools_result = asyncio.run(_run_session(body))
    names = sorted(t.name for t in tools_result.tools)
    assert names == sorted([
        "geo_get_capabilities", "geo_validate_pydoublet_result", "geo_run_workflow",
        "geo_get_run_summary", "geo_get_audit", "geo_get_artifact",
    ])


def test_tools_call_geo_get_capabilities():
    async def body(session: "ClientSession"):
        return await session.call_tool("geo_get_capabilities", {})

    call_result = asyncio.run(_run_session(body))
    assert call_result.isError is not True
    payload = call_result.structuredContent
    content = payload.get("result", payload)
    assert content["server_name"] == "r3chain-geothermal-mcp"
    assert "Q1/Q9, decided" in content["interim_architecture_disclaimer"]


def test_tools_call_geo_run_workflow_worked_case_matches_the_cli():
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = {
        "source_pydoublet_commit": _KNOWN_REPAIRED_COMMIT,
        "source_format_hint": "known_repaired",
        "calculation_mode": "deterministic",
    }

    async def body(session: "ClientSession"):
        return await session.call_tool(
            "geo_run_workflow", {"pydoublet_raw_result": raw, "source_provenance": provenance},
        )

    call_result = asyncio.run(_run_session(body))
    assert call_result.isError is not True
    payload = call_result.structuredContent
    content = payload.get("result", payload)
    assert content["run_id"] == "r3chain-run-93d41133daa11d1a"
    # Rebaselined (CFG-003, decision-register.md IMPL-007): schema 1.0.0 ->
    # 1.1.0 added GateTolerances.max_pump_dp_bar / GeothermalInjectionPolicy.
    # heat_delivery_tolerance_fraction -- new fields in workflow_result.json's
    # hashed content. run_id above is unaffected; the LCOH assertion below
    # proves the actual canonical ranking is unchanged too.
    assert content["bundle_scientific_sha256"] == "fd1e3408cbccfeb81d2847a60d809c2c8e407fb26de4738a624cb28ad00456f6"
    lcoh_by_id = {r["candidate_id"]: round(r["indicative_lcoh_eur_per_mwh"], 4) for r in content["ranked"]}
    assert lcoh_by_id == {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}


def test_tools_call_unknown_run_id_returns_a_structured_error_not_a_transport_crash():
    async def body(session: "ClientSession"):
        return await session.call_tool("geo_get_run_summary", {"run_id": "r3chain-run-doesnotexist0000"})

    call_result = asyncio.run(_run_session(body))
    # The tool itself never raises -- it returns a ToolError as a normal,
    # successful MCP call whose payload's own `status` field is "error".
    assert call_result.isError is not True
    payload = call_result.structuredContent
    content = payload.get("result", payload)
    assert content["status"] == "error"
    assert content["code"] == "RUN_NOT_FOUND"
