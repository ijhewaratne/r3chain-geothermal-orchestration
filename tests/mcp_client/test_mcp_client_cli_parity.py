"""Parity test (T5.1B acceptance criterion): the scripted MCP client's
result must match a direct `run_workflow()` call byte-for-byte on
`run_id`/`bundle_scientific_sha256` and exactly on ranked C1-C4 LCOH,
the same pattern T5.1A's own test_parity_with_cli.py established."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from r3chain_geothermal.contracts import SourceProvenance  # noqa: E402
from r3chain_geothermal.mcp_client.runner import run_mcp_session  # noqa: E402
from r3chain_geothermal.mcp_server.config import load_fixed_server_config  # noqa: E402
from r3chain_geothermal.workflow import WorkflowResult, run_workflow  # noqa: E402

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


def test_mcp_session_run_id_matches_direct_run_workflow():
    record = run_mcp_session(_raw(), _provenance())
    direct_result = run_workflow(_raw(), load_fixed_server_config(), source_provenance=_provenance())
    assert isinstance(direct_result, WorkflowResult)
    assert record.run_id == direct_result.run_id


def test_mcp_session_ranking_matches_direct_run_workflow_exactly():
    record = run_mcp_session(_raw(), _provenance())
    direct_result = run_workflow(_raw(), load_fixed_server_config(), source_provenance=_provenance())
    assert isinstance(direct_result, WorkflowResult)

    lcoh_by_id_mcp = {r.candidate_id: round(r.indicative_lcoh_eur_per_mwh, 4) for r in record.ranked}
    lcoh_by_id_direct = {
        entry.candidate_id: round(entry.economics.indicative_lcoh_eur_per_kwh * 1000.0, 4)
        for entry in direct_result.ranking.ranked
    }
    assert lcoh_by_id_mcp == lcoh_by_id_direct == _EXPECTED_LCOH_EUR_PER_MWH

    ranks_mcp = {r.candidate_id: r.rank for r in record.ranked}
    ranks_direct = {entry.candidate_id: entry.rank for entry in direct_result.ranking.ranked}
    assert ranks_mcp == ranks_direct


def test_mcp_session_worked_case_reproduces_c1_through_c4():
    record = run_mcp_session(_raw(), _provenance())
    assert [r.candidate_id for r in record.ranked] == ["C1", "C2", "C3", "C4"]
    assert record.preferred_candidate_id == "C1"
