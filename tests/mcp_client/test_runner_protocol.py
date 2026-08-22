"""Real subprocess MCP protocol tests for mcp_client/runner.py (T5.1B) --
requires the optional `mcp` extra; skipped cleanly if not installed."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from r3chain_geothermal.contracts import SourceProvenance  # noqa: E402
from r3chain_geothermal.mcp_client.runner import (  # noqa: E402
    ARTIFACT_PAGE_LIMIT_CHARS,
    McpTransportFailure,
    default_server_params_factory,
    run_mcp_session,
)
from r3chain_geothermal.mcp_server.schemas import RunSummary  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_LCOH_EUR_PER_MWH = {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance(**overrides) -> SourceProvenance:
    fields = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    fields.update(overrides)
    return SourceProvenance(**fields)


def _contrived_config_env_factory(overrides: dict) -> "mcp.StdioServerParameters":
    """Writes a contrived config JSON (a deep copy of the real committed
    config with `overrides` applied) and returns a server_params_factory
    launching the real server with R3CHAIN_MCP_CONFIG_PATH pointing at
    it -- a genuine end-to-end MCP protocol exercise of the zero-feasible/
    mixed-feasibility scenarios, using T5.1A's own already-approved
    operator-level config override, no server-side code changes."""
    config = json.loads(_CONFIG_PATH.read_text())
    node = config
    *path, leaf = overrides["path"]
    for key in path:
        node = node[key]
    node[leaf] = overrides["value"]

    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="r3chain-mcp-demo-test-config-")
    config_path = Path(tmp_dir) / "contrived_config.json"
    config_path.write_text(json.dumps(config))

    def factory():
        from mcp import StdioServerParameters
        return StdioServerParameters(
            command=sys.executable, args=["-m", "r3chain_geothermal.mcp_server.server"],
            env={**os.environ, "R3CHAIN_MCP_CONFIG_PATH": str(config_path)},
        )
    return factory


# ── Real subprocess: exact six-tool discovery ────────────────────────────
def test_worked_case_discovers_exactly_six_tools():
    record = run_mcp_session(_raw(), _provenance())
    assert record.tools_discovered == sorted([
        "geo_get_capabilities", "geo_validate_pydoublet_result", "geo_run_workflow",
        "geo_get_run_summary", "geo_get_audit", "geo_get_artifact",
    ])


# ── Full worked-case 8-step sequence ──────────────────────────────────────
def test_worked_case_full_sequence_matches_committed_lcoh():
    record = run_mcp_session(_raw(), _provenance())
    assert record.execution_route == "mcp"
    assert record.server_name == "r3chain-geothermal-mcp"
    assert record.protocol_version
    assert [tc.order for tc in record.tool_calls] == [3, 4, 5, 6, 7, 8]
    assert [tc.tool_name for tc in record.tool_calls] == [
        "geo_get_capabilities", "geo_validate_pydoublet_result", "geo_run_workflow",
        "geo_get_run_summary", "geo_get_audit", "geo_get_artifact",
    ]
    assert all(tc.status == "success" for tc in record.tool_calls)
    lcoh_by_id = {r.candidate_id: round(r.indicative_lcoh_eur_per_mwh, 4) for r in record.ranked}
    assert lcoh_by_id == _EXPECTED_LCOH_EUR_PER_MWH
    assert record.preferred_candidate_id == "C1"
    assert record.run_id == "r3chain-run-93d41133daa11d1a"


def test_worked_case_compact_inputs_never_contain_the_raw_result():
    record = run_mcp_session(_raw(), _provenance())
    serialized = record.model_dump_json()
    assert "raw_geothermal_thermal_power_kw" not in serialized or "field_provenance" not in serialized
    assert "temperature_profile_c" not in serialized  # a real, large field of the raw PyDoublet result


# ── Pagination reconstruction and artifact/hash verification ─────────────
async def _fetch_manifest_hash_for(session, run_id: str, filename: str) -> str:
    result = await session.call_tool("geo_get_artifact", {"run_id": run_id, "filename": "manifest.json"})
    payload = result.structuredContent
    content = payload.get("result", payload)["content"]
    manifest = json.loads(content)
    return manifest["files"][filename]["byte_sha256"]


def test_pagination_reconstructs_the_exact_artifact_content():
    import asyncio
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from r3chain_geothermal.mcp_client.runner import _fetch_full_artifact_text

    async def scenario():
        params = default_server_params_factory()
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                run_result = await session.call_tool(
                    "geo_run_workflow",
                    {"pydoublet_raw_result": _raw(), "source_provenance": _provenance().model_dump(mode="json")},
                )
                payload = run_result.structuredContent
                run_summary = RunSummary.model_validate(payload.get("result", payload))
                run_id = run_summary.run_id

                reconstructed_text, pages_fetched = await _fetch_full_artifact_text(
                    session, run_id, "workflow_result.json", page_limit=500,
                )
                expected_hash = await _fetch_manifest_hash_for(session, run_id, "workflow_result.json")
                actual_hash = hashlib.sha256(reconstructed_text.encode("utf-8")).hexdigest()
                return pages_fetched, expected_hash, actual_hash

    pages_fetched, expected_hash, actual_hash = asyncio.run(scenario())
    assert pages_fetched > 1, "expected genuine multi-page pagination at a 500-char page size"
    assert actual_hash == expected_hash


def test_production_sequence_pagination_uses_a_smaller_page_than_the_server_max():
    assert ARTIFACT_PAGE_LIMIT_CHARS < 16_384


# ── Zero-feasible and mixed-feasibility completion (via config env override) ──
def test_zero_feasible_candidates_completes_with_no_recommendation():
    factory = _contrived_config_env_factory({"path": ["network", "p_supply_bar_abs"], "value": 4.51})
    record = run_mcp_session(_raw(), _provenance(), server_params_factory=factory)
    assert record.execution_route == "mcp"
    assert record.workflow_status == "completed"
    assert record.preferred_candidate_id is None
    assert record.ranked == []
    assert len(record.infeasible) == 4
    assert "no candidate is feasible" in record.recommendation_text.lower()


def test_mixed_feasibility_ranks_feasible_candidates_and_reports_the_rejected_one():
    factory = _contrived_config_env_factory({"path": ["gates", "min_pressure_bar_abs"], "value": 2.95})
    record = run_mcp_session(_raw(), _provenance(), server_params_factory=factory)
    assert record.execution_route == "mcp"
    assert record.preferred_candidate_id == "C1"
    assert [r.candidate_id for r in record.ranked] == ["C1", "C2", "C3"]
    assert len(record.infeasible) == 1
    assert record.infeasible[0].candidate_id == "C4"
    assert record.infeasible[0].failure_code == "PRESSURE_LIMIT_EXCEEDED"


# ── geo_get_capabilities' config hash reflects the ACTIVE server config ───
def test_capabilities_config_hash_reflects_r3chain_mcp_config_path_override():
    """`R3CHAIN_MCP_CONFIG_PATH` is a server-operator/test launch setting
    (never a tool or client argument, mcp_server/config.py's own module
    docstring) -- this proves geo_get_capabilities' own
    demo_assumptions_config_sha256 is computed from whichever config the
    server process actually loaded at startup, not a value hardcoded/
    cached independent of that override."""
    default_record = run_mcp_session(_raw(), _provenance())
    default_caps = next(tc for tc in default_record.tool_calls if tc.tool_name == "geo_get_capabilities")

    contrived_factory = _contrived_config_env_factory({"path": ["network", "p_supply_bar_abs"], "value": 4.51})
    contrived_record = run_mcp_session(_raw(), _provenance(), server_params_factory=contrived_factory)
    contrived_caps = next(tc for tc in contrived_record.tool_calls if tc.tool_name == "geo_get_capabilities")

    assert default_caps.compact_output["demo_assumptions_config_sha256"] != contrived_caps.compact_output["demo_assumptions_config_sha256"]


# ── Typed workflow failure WITHOUT fallback ───────────────────────────────
def test_typed_workflow_failure_stays_execution_route_mcp_no_fallback():
    """A stopped workflow (malformed PyDoublet content) is a normal,
    typed MCP result -- never a fallback trigger, even with fallback
    disabled (the default)."""
    record = run_mcp_session({}, _provenance())  # empty dict -> PYDOUBLET_PARSE_FAILED
    assert record.execution_route == "mcp"
    assert record.workflow_status == "stopped"
    assert record.run_id is not None  # run_id is computed before the workflow runs
    # Steps 6-8 still proceed for a stopped workflow (it publishes a
    # 5-file audit trail with a real run_id).
    assert [tc.order for tc in record.tool_calls] == [3, 4, 5, 6, 7, 8]


def test_typed_workflow_failure_with_fallback_allowed_still_does_not_fall_back():
    """Even with allow_cli_fallback=True, a typed domain outcome must
    never trigger the fallback path -- it is not a transport failure."""
    record = run_mcp_session({}, _provenance(), allow_cli_fallback=True)
    assert record.execution_route == "mcp"
    assert record.workflow_status == "stopped"


# ── Invalid input and malformed provenance ────────────────────────────────
def test_invalid_pydoublet_content_reaches_pydoublet_validation_failed_at_step_4():
    record = run_mcp_session({}, _provenance())
    validate_call = next(tc for tc in record.tool_calls if tc.tool_name == "geo_validate_pydoublet_result")
    assert validate_call.status == "error"
    assert validate_call.compact_output["code"] == "PYDOUBLET_VALIDATION_FAILED"


def test_unsupported_calculation_mode_is_a_typed_error_not_a_transport_failure():
    record = run_mcp_session(_raw(), _provenance(calculation_mode="monte_carlo"))
    assert record.execution_route == "mcp"
    validate_call = next(tc for tc in record.tool_calls if tc.tool_name == "geo_validate_pydoublet_result")
    assert validate_call.status == "error"
    run_call = next(tc for tc in record.tool_calls if tc.tool_name == "geo_run_workflow")
    assert run_call.status == "success"  # geo_run_workflow itself still returns a normal, stopped RunSummary
    assert record.workflow_status == "stopped"
