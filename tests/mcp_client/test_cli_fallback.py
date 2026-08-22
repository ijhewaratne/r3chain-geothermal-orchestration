"""Full test matrix for mcp_client/cli_fallback.py -- the deterministic
CLI-equivalent path (T5.1B), used only via runner.py's own opt-in
fallback boundary."""
from __future__ import annotations

import json
from pathlib import Path

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.mcp_client.cli_fallback import run_cli_fallback_session
from r3chain_geothermal.mcp_server.config import load_fixed_server_config
from r3chain_geothermal.workflow import WorkflowResult, run_workflow

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_LCOH_EUR_PER_MWH = {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def test_cli_fallback_execution_route_and_empty_tool_calls():
    record = run_cli_fallback_session(_raw(), _provenance(), interim_architecture_disclaimer="d")
    assert record.execution_route == "cli_fallback"
    assert record.tool_calls == []
    assert record.server_name is None
    assert record.protocol_version is None
    assert record.tools_discovered == []


def test_cli_fallback_reproduces_the_same_run_id_as_a_direct_run_workflow_call():
    record = run_cli_fallback_session(_raw(), _provenance(), interim_architecture_disclaimer="d")
    direct_result = run_workflow(_raw(), load_fixed_server_config(), source_provenance=_provenance())
    assert isinstance(direct_result, WorkflowResult)
    assert record.run_id == direct_result.run_id


def test_cli_fallback_reproduces_the_committed_lcoh_and_ranking():
    record = run_cli_fallback_session(_raw(), _provenance(), interim_architecture_disclaimer="d")
    lcoh_by_id = {r.candidate_id: round(r.indicative_lcoh_eur_per_mwh, 4) for r in record.ranked}
    assert lcoh_by_id == _EXPECTED_LCOH_EUR_PER_MWH
    assert [r.candidate_id for r in record.ranked] == ["C1", "C2", "C3", "C4"]
    assert record.preferred_candidate_id == "C1"


def test_cli_fallback_reproduces_the_same_bundle_scientific_sha256_as_a_real_mcp_run():
    """The strongest form of "same deterministic identifiers" --
    bundle_scientific_sha256 depends on the FULL set of published
    artifacts' scientific content, not just run_id."""
    import pytest
    pytest.importorskip("mcp")
    from r3chain_geothermal.mcp_client.runner import run_mcp_session

    fallback_record = run_cli_fallback_session(_raw(), _provenance(), interim_architecture_disclaimer="d")
    mcp_record = run_mcp_session(_raw(), _provenance())
    assert fallback_record.bundle_scientific_sha256 == mcp_record.bundle_scientific_sha256


def test_cli_fallback_disclaimer_is_passed_through_verbatim():
    record = run_cli_fallback_session(_raw(), _provenance(), interim_architecture_disclaimer="a specific disclaimer string")
    assert record.interim_architecture_disclaimer == "a specific disclaimer string"


def test_cli_fallback_recommendation_text_is_marked_as_fallback():
    record = run_cli_fallback_session(_raw(), _provenance(), interim_architecture_disclaimer="d")
    assert "fallback" in record.recommendation_text.lower()


def test_cli_fallback_handles_a_stopped_workflow_too():
    record = run_cli_fallback_session({}, _provenance(), interim_architecture_disclaimer="d")
    assert record.execution_route == "cli_fallback"
    assert record.workflow_status == "stopped"
    assert record.run_id is not None


def test_cli_fallback_never_leaves_a_stray_temp_directory():
    """run_cli_fallback_session() uses its own scoped TemporaryDirectory
    for artifact writing -- it must be cleaned up regardless of outcome."""
    import glob
    import tempfile

    before = set(glob.glob(str(Path(tempfile.gettempdir()) / "r3chain-mcp-demo-fallback-*")))
    run_cli_fallback_session(_raw(), _provenance(), interim_architecture_disclaimer="d")
    after = set(glob.glob(str(Path(tempfile.gettempdir()) / "r3chain-mcp-demo-fallback-*")))
    assert after == before
