#!/usr/bin/env python3
"""Test-only minimal MCP server (T5.1B) -- NOT part of the shipped
package, used ONLY by test_transport_failures.py's mid-session-
transport-failure scenario. Registers all six real `geo_` tool NAMES
(runner.py's own tool-set contract check, added for correction #1, would
otherwise reject this fixture at step 2 with McpContractFailure before it
ever reached the deliberate crash below -- the point of this fixture is a
TRANSPORT failure, not a contract failure) to let a client's runner get
partway through the production 8-step sequence, then deliberately crashes
(`os._exit`) inside `geo_run_workflow` to produce a genuine, deterministic
transport failure at a known point -- a broken pipe/closed connection the
client's own `call_tool()` will observe as an exception. The three tools
past the crash point (get_run_summary/get_audit/get_artifact) are never
actually invoked; their stub bodies exist only so tool discovery sees the
full six-tool set."""
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("crashing-test-server")


@mcp.tool(name="geo_get_capabilities")
def geo_get_capabilities() -> dict:
    return {
        "status": "success",
        "tools": [
            "geo_get_capabilities", "geo_validate_pydoublet_result", "geo_run_workflow",
            "geo_get_run_summary", "geo_get_audit", "geo_get_artifact",
        ],
    }


@mcp.tool(name="geo_validate_pydoublet_result")
def geo_validate_pydoublet_result(pydoublet_raw_result: dict, source_provenance: dict) -> dict:
    return {"status": "success", "raw_result_sha256": "0" * 64}


@mcp.tool(name="geo_run_workflow")
def geo_run_workflow(pydoublet_raw_result: dict, source_provenance: dict) -> dict:
    os._exit(1)  # deliberate crash -- simulates a mid-session transport failure


@mcp.tool(name="geo_get_run_summary")
def geo_get_run_summary(run_id: str) -> dict:
    return {"status": "error"}  # unreachable -- geo_run_workflow crashes first


@mcp.tool(name="geo_get_audit")
def geo_get_audit(run_id: str) -> dict:
    return {"status": "error"}  # unreachable -- geo_run_workflow crashes first


@mcp.tool(name="geo_get_artifact")
def geo_get_artifact(run_id: str, filename: str, offset: int = 0, limit: int = 2000) -> dict:
    return {"status": "error"}  # unreachable -- geo_run_workflow crashes first


if __name__ == "__main__":
    mcp.run(transport="stdio")
