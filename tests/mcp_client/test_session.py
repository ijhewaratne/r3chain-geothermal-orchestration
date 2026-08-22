"""Full test matrix for mcp_client/session.py -- SessionRecord's compact,
no-raw-result/no-absolute-path/no-env-data contract (T5.1B)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.hashing import canonical_raw_result_sha256
from r3chain_geothermal.mcp_client.session import (
    SessionRecord,
    ToolCallRecord,
    build_recommendation_text,
    build_session_record,
    compact_pydoublet_input,
)
from r3chain_geothermal.mcp_server.schemas import InfeasibleCandidateSummary, RankedCandidateSummary, RunSummary

_LARGE_RAW_RESULT = {"metadata": {"simulation_name": "x"}, "payload": ["x" * 1000] * 50}  # deliberately large


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit="0" * 40, source_format_hint="known_repaired", calculation_mode="deterministic",
    )


def _run_summary(**overrides) -> RunSummary:
    fields = dict(
        run_id="r3chain-run-abc123", workflow_status="completed", preferred_candidate_id="C1",
        ranked=[RankedCandidateSummary(candidate_id="C1", rank=1, indicative_lcoh_eur_per_mwh=52.1714)],
        infeasible=[], stopping_failure_code=None, warnings=[],
        artifact_filenames=["manifest.json"], bundle_scientific_sha256="a" * 64, reused_existing_run=False,
    )
    fields.update(overrides)
    return RunSummary(**fields)


# ── compact_pydoublet_input: never the raw dict, always a hash reference ──
def test_compact_pydoublet_input_never_contains_the_raw_result():
    compact = compact_pydoublet_input(_LARGE_RAW_RESULT, _provenance())
    serialized = json.dumps(compact)
    assert "payload" not in serialized
    assert "x" * 1000 not in serialized


def test_compact_pydoublet_input_hash_matches_canonical_hash():
    compact = compact_pydoublet_input(_LARGE_RAW_RESULT, _provenance())
    assert compact["raw_result_sha256"] == canonical_raw_result_sha256(_LARGE_RAW_RESULT)


def test_compact_pydoublet_input_is_much_smaller_than_the_raw_result():
    compact = compact_pydoublet_input(_LARGE_RAW_RESULT, _provenance())
    assert len(json.dumps(compact)) < len(json.dumps(_LARGE_RAW_RESULT)) / 10


def test_compact_pydoublet_input_includes_source_provenance():
    compact = compact_pydoublet_input(_LARGE_RAW_RESULT, _provenance())
    assert compact["source_provenance"]["calculation_mode"] == "deterministic"


# ── ToolCallRecord / SessionRecord model contract ─────────────────────────
def test_tool_call_record_is_frozen_and_forbids_extra_fields():
    record = ToolCallRecord(order=1, tool_name="geo_get_capabilities", compact_input={}, compact_output={}, status="success")
    with pytest.raises(ValidationError):
        record.order = 2
    with pytest.raises(ValidationError):
        ToolCallRecord(order=1, tool_name="x", compact_input={}, compact_output={}, status="success", extra="nope")


def test_session_record_json_round_trip():
    record = build_session_record(
        execution_route="mcp", server_name="r3chain-geothermal-mcp", protocol_version="2025-11-25",
        tools_discovered=["geo_get_capabilities"], tool_calls=[], run_summary=_run_summary(),
        created_at=datetime.now(timezone.utc), interim_architecture_disclaimer="disclaimer text",
    )
    restored = SessionRecord.model_validate_json(record.model_dump_json())
    assert restored == record


# ── No absolute paths or environment data anywhere in a rendered record ──
def test_session_record_never_contains_an_absolute_path_or_env_var_marker():
    record = build_session_record(
        execution_route="mcp", server_name="r3chain-geothermal-mcp", protocol_version="2025-11-25",
        tools_discovered=["geo_get_capabilities"],
        tool_calls=[ToolCallRecord(
            order=3, tool_name="geo_get_capabilities", compact_input={},
            compact_output={"status": "success", "server_name": "r3chain-geothermal-mcp"}, status="success",
        )],
        run_summary=_run_summary(), created_at=datetime.now(timezone.utc),
        interim_architecture_disclaimer="disclaimer text",
    )
    serialized = record.model_dump_json()
    assert "/Users/" not in serialized
    assert "/private/tmp" not in serialized
    assert "HOME=" not in serialized
    assert "PATH=" not in serialized
    import sys
    assert sys.executable not in serialized


def test_cli_fallback_session_record_has_no_server_identity():
    record = build_session_record(
        execution_route="cli_fallback", server_name=None, protocol_version=None, tools_discovered=[],
        tool_calls=[], run_summary=_run_summary(), created_at=datetime.now(timezone.utc),
        interim_architecture_disclaimer="disclaimer text",
    )
    assert record.server_name is None
    assert record.protocol_version is None
    assert record.tool_calls == []
    assert record.tools_discovered == []


# ── Deterministic recommendation text (never an LLM call) ────────────────
def test_recommendation_text_worked_case_names_the_winner():
    text = build_recommendation_text(_run_summary(), execution_route="mcp")
    assert "C1" in text
    assert "52.1714" in text
    assert "r3chain-run-abc123" in text


def test_recommendation_text_zero_feasible_makes_no_recommendation():
    summary = _run_summary(ranked=[], preferred_candidate_id=None)
    text = build_recommendation_text(summary, execution_route="mcp")
    assert "no candidate is feasible" in text.lower()
    assert "C1" not in text


def test_recommendation_text_stopped_workflow_states_the_failure_code():
    summary = _run_summary(
        workflow_status="stopped", ranked=[], infeasible=[], preferred_candidate_id=None,
        stopping_failure_code="PYDOUBLET_PARSE_FAILED",
    )
    text = build_recommendation_text(summary, execution_route="mcp")
    assert "PYDOUBLET_PARSE_FAILED" in text
    assert "stopped" in text.lower()


def test_recommendation_text_marks_cli_fallback_route():
    text_mcp = build_recommendation_text(_run_summary(), execution_route="mcp")
    text_fallback = build_recommendation_text(_run_summary(), execution_route="cli_fallback")
    assert text_mcp != text_fallback
    assert "fallback" in text_fallback.lower()
    assert "fallback" not in text_mcp.lower()


def test_recommendation_text_is_deterministic_across_repeated_calls():
    summary = _run_summary()
    assert build_recommendation_text(summary, execution_route="mcp") == build_recommendation_text(summary, execution_route="mcp")


def test_recommendation_text_none_summary_is_handled_safely():
    text = build_recommendation_text(None, execution_route="mcp")
    assert isinstance(text, str)
    assert text != ""


def test_build_session_record_infeasible_candidates_are_preserved():
    summary = _run_summary(
        ranked=[], preferred_candidate_id=None,
        infeasible=[InfeasibleCandidateSummary(candidate_id="C4", failure_code="PRESSURE_LIMIT_EXCEEDED")],
    )
    record = build_session_record(
        execution_route="mcp", server_name="x", protocol_version="y", tool_calls=[], run_summary=summary,
        created_at=datetime.now(timezone.utc), interim_architecture_disclaimer="d",
    )
    assert record.infeasible == summary.infeasible
