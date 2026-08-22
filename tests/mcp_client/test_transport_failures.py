"""Transport-failure rehearsal tests for mcp_client/runner.py (T5.1B) --
server-start failure with fallback disabled and enabled, and a
mid-session transport failure (a real, purpose-built crashing server)
with fallback-enabled recovery."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from r3chain_geothermal.contracts import SourceProvenance  # noqa: E402
from r3chain_geothermal.mcp_client.runner import McpTransportFailure, run_mcp_session  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_CRASHING_SERVER_SCRIPT = str(Path(__file__).resolve().parent / "fixtures" / "crashing_server.py")

_EXPECTED_LCOH_EUR_PER_MWH = {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _nonexistent_command_factory():
    from mcp import StdioServerParameters
    return StdioServerParameters(command="this-command-definitely-does-not-exist-r3chain-xyz", args=[])


def _crashing_server_factory():
    from mcp import StdioServerParameters
    return StdioServerParameters(command=sys.executable, args=[_CRASHING_SERVER_SCRIPT])


# ── Server-start failure, fallback disabled ──────────────────────────────
def test_server_start_failure_with_fallback_disabled_raises_mcp_transport_error():
    with pytest.raises(McpTransportFailure):
        run_mcp_session(_raw(), _provenance(), allow_cli_fallback=False, server_params_factory=_nonexistent_command_factory)


def test_server_start_failure_error_message_contains_no_raw_traceback_markers():
    try:
        run_mcp_session(_raw(), _provenance(), allow_cli_fallback=False, server_params_factory=_nonexistent_command_factory)
        pytest.fail("expected McpTransportFailure")
    except McpTransportFailure as exc:
        message = str(exc)
        assert "Traceback (most recent call last)" not in message


# ── Server-start failure, fallback enabled ───────────────────────────────
def test_server_start_failure_with_fallback_enabled_completes_via_cli_fallback():
    record = run_mcp_session(_raw(), _provenance(), allow_cli_fallback=True, server_params_factory=_nonexistent_command_factory)
    assert record.execution_route == "cli_fallback"
    assert record.tool_calls == []
    lcoh_by_id = {r.candidate_id: round(r.indicative_lcoh_eur_per_mwh, 4) for r in record.ranked}
    assert lcoh_by_id == _EXPECTED_LCOH_EUR_PER_MWH
    assert record.preferred_candidate_id == "C1"


# ── Mid-session transport failure, fallback enabled: rollback/cleanup ────
def test_mid_session_transport_failure_with_fallback_enabled_recovers_completely():
    """The crashing_server.py fixture succeeds through geo_get_capabilities
    then crashes inside geo_run_workflow -- a genuine mid-sequence
    transport failure. With fallback enabled, the client abandons the
    partial MCP attempt entirely (never resumes it) and produces a
    complete, correct result via a fresh deterministic run."""
    record = run_mcp_session(_raw(), _provenance(), allow_cli_fallback=True, server_params_factory=_crashing_server_factory)
    assert record.execution_route == "cli_fallback"
    assert record.tool_calls == []  # the partial MCP attempt's own calls are never carried over
    assert record.run_id is not None
    lcoh_by_id = {r.candidate_id: round(r.indicative_lcoh_eur_per_mwh, 4) for r in record.ranked}
    assert lcoh_by_id == _EXPECTED_LCOH_EUR_PER_MWH


def test_mid_session_transport_failure_with_fallback_disabled_raises_cleanly():
    with pytest.raises(McpTransportFailure):
        run_mcp_session(_raw(), _provenance(), allow_cli_fallback=False, server_params_factory=_crashing_server_factory)


def test_mid_session_transport_failure_leaves_no_orphan_crashed_process():
    """The crashed server process must not linger as a zombie/orphan --
    mcp.client.stdio's own async-context-manager cleanup handles this;
    this test just confirms the call actually returns within a bounded
    time rather than hanging on a dead pipe."""
    import time

    start = time.monotonic()
    run_mcp_session(_raw(), _provenance(), allow_cli_fallback=True, server_params_factory=_crashing_server_factory)
    elapsed = time.monotonic() - start
    assert elapsed < 15.0, f"mid-session failure + fallback took too long ({elapsed:.1f}s) -- possible hang"


# ── Narrowed fallback boundary: contract/client-bug failures never fall back ──
def test_injected_parsing_bug_does_not_trigger_cli_fallback(monkeypatch):
    """A bug in THIS client's own response-parsing code is never an MCP
    transport/protocol failure -- it must propagate as itself, even with
    allow_cli_fallback=True. Silently substituting a deterministic CLI
    run for a client-side bug would hide the bug instead of surfacing
    it."""
    from r3chain_geothermal.mcp_client import runner

    def _broken_unwrap(call_result):
        raise TypeError("simulated client-side parsing bug")

    monkeypatch.setattr(runner, "_unwrap_tool_result", _broken_unwrap)
    with pytest.raises(TypeError, match="simulated client-side parsing bug"):
        run_mcp_session(_raw(), _provenance(), allow_cli_fallback=True)


def test_artifact_hash_mismatch_raises_contract_failure_not_fallback(monkeypatch):
    """A `workflow_result.json` reconstructed via pagination that does
    not match manifest.json's own recorded byte_sha256 is a malformed
    RESPONSE, not a transport failure -- McpContractFailure, and
    allow_cli_fallback=True must NOT trigger a fallback for it."""
    from r3chain_geothermal.mcp_client import runner

    real_fetch = runner._fetch_full_artifact_text

    async def _corrupting_fetch(session, run_id, filename, *, page_limit=runner.ARTIFACT_PAGE_LIMIT_CHARS):
        text, pages = await real_fetch(session, run_id, filename, page_limit=page_limit)
        if filename == runner.PAGINATED_ARTIFACT_FILENAME:
            text = text + " corrupted"
        return text, pages

    monkeypatch.setattr(runner, "_fetch_full_artifact_text", _corrupting_fetch)
    with pytest.raises(runner.McpContractFailure, match="does not match manifest.json"):
        run_mcp_session(_raw(), _provenance(), allow_cli_fallback=True)
