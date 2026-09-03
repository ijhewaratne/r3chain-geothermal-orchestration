"""Full test matrix for mcp_server/tools.py -- the six geo_ tool functions
called directly (no MCP transport). Covers every scenario T5.1A's
acceptance criteria name explicitly: worked case, malformed input,
unsupported calculation mode, zero-feasible result, unknown run, forbidden
artifact, pagination."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.mcp_server import tools
from r3chain_geothermal.mcp_server.config import load_fixed_server_config
from r3chain_geothermal.mcp_server.errors import ToolError, ToolErrorCode
from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.schemas import (
    ArtifactSlice,
    AuditSummary,
    CapabilitiesSummary,
    PyDoubletValidationSummary,
    RunSummary,
    SourceProvenanceInput,
)

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_LCOH_EUR_PER_MWH = {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance(**overrides) -> SourceProvenanceInput:
    fields = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    fields.update(overrides)
    return SourceProvenanceInput(**fields)


@pytest.fixture
def registry():
    with tempfile.TemporaryDirectory() as td:
        reg = RunRegistry(max_size=10, root_dir=Path(td))
        yield reg


@pytest.fixture
def fixed_config():
    return load_fixed_server_config()


# ── 1. geo_get_capabilities ──────────────────────────────────────────────
def test_get_capabilities_reports_exact_six_tools(fixed_config, registry):
    caps = tools.get_capabilities(fixed_config=fixed_config, registry=registry)
    assert isinstance(caps, CapabilitiesSummary)
    assert sorted(caps.tools) == sorted(tools.GEO_TOOL_NAMES)


def test_get_capabilities_includes_the_mandatory_disclaimer_verbatim(fixed_config, registry):
    caps = tools.get_capabilities(fixed_config=fixed_config, registry=registry)
    assert caps.interim_architecture_disclaimer == tools.INTERIM_ARCHITECTURE_DISCLAIMER
    assert "selected one-server integration architecture" in caps.interim_architecture_disclaimer
    assert "Q1/Q9, decided" in caps.interim_architecture_disclaimer


def test_get_capabilities_reports_the_exact_artifact_allow_list(fixed_config, registry):
    caps = tools.get_capabilities(fixed_config=fixed_config, registry=registry)
    assert caps.allowed_artifact_filenames == list(tools._ALLOWED_ARTIFACT_FILENAMES)


def test_get_capabilities_never_touches_the_registry(fixed_config, registry):
    tools.get_capabilities(fixed_config=fixed_config, registry=registry)
    assert len(registry) == 0


# ── 2. geo_validate_pydoublet_result ─────────────────────────────────────
def test_validate_pydoublet_result_worked_case():
    result = tools.validate_pydoublet_result(_raw(), _provenance())
    assert isinstance(result, PyDoubletValidationSummary)
    assert len(result.raw_result_sha256) == 64
    assert result.raw_geothermal_thermal_power_kw > 0


def test_validate_pydoublet_result_malformed_content_dict():
    """Syntactically a dict, but missing required PyDoublet fields --
    reaches PYDOUBLET_VALIDATION_FAILED, never an unhandled exception."""
    result = tools.validate_pydoublet_result({}, _provenance())
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.PYDOUBLET_VALIDATION_FAILED
    assert result.stage == "parse_pydoublet_result"


def test_validate_pydoublet_result_unsupported_calculation_mode():
    result = tools.validate_pydoublet_result(_raw(), _provenance(calculation_mode="monte_carlo"))
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.PYDOUBLET_VALIDATION_FAILED
    assert result.details["failure_code"] == "PYDOUBLET_UNSUPPORTED_CALCULATION_MODE"


def test_validate_pydoublet_result_unknown_calculation_mode_also_rejected():
    result = tools.validate_pydoublet_result(_raw(), _provenance(calculation_mode="unknown"))
    assert isinstance(result, ToolError)
    assert result.details["failure_code"] == "PYDOUBLET_UNSUPPORTED_CALCULATION_MODE"


def test_source_provenance_input_requires_explicit_fields_no_silent_default():
    """The concrete mechanism behind 'never infer deterministic/trusted
    mode': the three trust-relevant fields are required at the schema
    level -- omitting them is a validation error, not a silent default."""
    with pytest.raises(ValidationError):
        SourceProvenanceInput(source_pydoublet_commit="0" * 40)  # missing the other two


# ── 3. geo_run_workflow ──────────────────────────────────────────────────
def test_run_workflow_worked_case_matches_committed_lcoh(fixed_config, registry):
    result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    assert isinstance(result, RunSummary)
    assert result.workflow_status == "completed"
    assert result.preferred_candidate_id == "C1"
    lcoh_by_id = {r.candidate_id: round(r.indicative_lcoh_eur_per_mwh, 4) for r in result.ranked}
    assert lcoh_by_id == _EXPECTED_LCOH_EUR_PER_MWH
    assert result.infeasible == []
    assert result.reused_existing_run is False


def test_run_workflow_worked_case_publishes_eight_artifacts(fixed_config, registry):
    result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    assert sorted(result.artifact_filenames) == sorted(tools._ALLOWED_ARTIFACT_FILENAMES)


def test_run_workflow_repeated_identical_input_reuses_the_same_run(fixed_config, registry):
    result1 = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result2 = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    assert result1.run_id == result2.run_id
    assert result1.reused_existing_run is False
    assert result2.reused_existing_run is True
    assert len(registry) == 1


def test_run_workflow_different_provenance_gets_a_different_run_id(fixed_config, registry):
    result1 = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result2 = tools.run_workflow_tool(
        _raw(), _provenance(scenario_identifier="a-different-scenario-tag"),
        fixed_config=fixed_config, registry=registry,
    )
    assert result1.run_id != result2.run_id
    assert len(registry) == 2


def test_run_workflow_stopping_failure_publishes_five_artifacts(fixed_config, registry):
    result = tools.run_workflow_tool({}, _provenance(), fixed_config=fixed_config, registry=registry)
    assert isinstance(result, RunSummary)
    assert result.workflow_status == "stopped"
    assert result.stopping_failure_code == "PYDOUBLET_PARSE_FAILED"
    assert result.preferred_candidate_id is None
    assert len(result.artifact_filenames) == 5
    assert "candidate_comparison.csv" not in result.artifact_filenames


def test_run_workflow_zero_feasible_result_via_test_only_config_override(fixed_config, registry):
    """config is never a tool argument -- this exercises the test-only
    fixed_config seam (a distinct, differently-configured registry/config
    pair), never a per-call override of a live server."""
    contrived_config = json.loads(json.dumps(fixed_config))
    contrived_config["network"]["p_supply_bar_abs"] = 4.51
    result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=contrived_config, registry=registry)
    assert isinstance(result, RunSummary)
    assert result.workflow_status == "completed"
    assert result.preferred_candidate_id is None
    assert result.ranked == []
    assert len(result.infeasible) == 4
    assert all(entry.failure_code == "PRESSURE_LIMIT_EXCEEDED" for entry in result.infeasible)


def test_run_workflow_unexpected_internal_failure_maps_to_unexpected_error(fixed_config, registry, monkeypatch):
    """Simulates a genuine internal defect (never a config/input problem)
    -- must be UNEXPECTED_ERROR, never conflated with INVALID_INPUT or
    PYDOUBLET_VALIDATION_FAILED."""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated solver/programming defect")

    monkeypatch.setattr(tools, "run_workflow", _boom)
    result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.UNEXPECTED_ERROR
    assert result.stage == "run_workflow"
    assert len(registry) == 0


def test_run_workflow_non_finite_input_maps_to_invalid_input(fixed_config, registry):
    raw = _raw()
    raw["_probe"] = float("nan")
    result = tools.run_workflow_tool(raw, _provenance(), fixed_config=fixed_config, registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.INVALID_INPUT
    assert result.stage == "compute_run_id"


# ── 4. geo_get_run_summary ───────────────────────────────────────────────
def test_get_run_summary_returns_the_same_summary_geo_run_workflow_did(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    fetched = tools.get_run_summary(run_result.run_id, registry=registry)
    assert isinstance(fetched, RunSummary)
    assert fetched.run_id == run_result.run_id
    assert fetched.ranked == run_result.ranked
    assert fetched.reused_existing_run is True


def test_get_run_summary_unknown_run_id(registry):
    result = tools.get_run_summary("r3chain-run-doesnotexist0000", registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.RUN_NOT_FOUND
    assert result.recoverable is True


def test_get_run_summary_never_runs_the_workflow(fixed_config, registry):
    """A pure lookup -- an unknown run_id must never trigger a run."""
    tools.get_run_summary("r3chain-run-doesnotexist0000", registry=registry)
    assert len(registry) == 0


# ── 5. geo_get_audit ──────────────────────────────────────────────────────
def test_get_audit_worked_case(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    audit_result = tools.get_audit(run_result.run_id, registry=registry)
    assert isinstance(audit_result, AuditSummary)
    assert audit_result.run_id == run_result.run_id
    assert audit_result.audit.run_id == run_result.run_id


def test_get_audit_unknown_run_id(registry):
    result = tools.get_audit("r3chain-run-doesnotexist0000", registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.RUN_NOT_FOUND


# ── 6. geo_get_artifact ───────────────────────────────────────────────────
def test_get_artifact_worked_case_reads_csv(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, "candidate_comparison.csv", registry=registry)
    assert isinstance(result, ArtifactSlice)
    assert result.content.startswith("candidate_id,")
    assert result.offset == 0
    assert result.total_length == len(result.content)  # small file, one slice
    assert result.next_offset is None


def test_get_artifact_manifest_json_is_retrievable(fixed_config, registry):
    """Regression guard: ManifestRecord never lists itself in `files`
    (its own invariant), but the file genuinely exists on disk and must
    still be a valid geo_get_artifact target."""
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, "manifest.json", registry=registry)
    assert isinstance(result, ArtifactSlice)
    assert json.loads(result.content)["run_id"] == run_result.run_id


def test_get_artifact_unknown_run_id(registry):
    result = tools.get_artifact("r3chain-run-doesnotexist0000", "manifest.json", registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.RUN_NOT_FOUND


@pytest.mark.parametrize("filename", [
    "../../etc/passwd", "../escape.txt", "/etc/passwd", ".hidden", "not_a_real_artifact.json",
])
def test_get_artifact_forbidden_filename(fixed_config, registry, filename: str):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, filename, registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.FORBIDDEN_ARTIFACT
    assert result.recoverable is False


def test_get_artifact_forbidden_filename_checked_before_run_id_lookup(registry):
    """A forbidden filename is rejected even for a run_id that was never
    issued -- proves nothing is read from disk before the allow-list check."""
    result = tools.get_artifact("r3chain-run-doesnotexist0000", "../../etc/passwd", registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.FORBIDDEN_ARTIFACT


def test_get_artifact_not_available_for_a_stopped_workflow(fixed_config, registry):
    run_result = tools.run_workflow_tool({}, _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, "candidate_comparison.csv", registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.ARTIFACT_NOT_AVAILABLE


def test_get_artifact_pagination_slices_a_large_file(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    first = tools.get_artifact(run_result.run_id, "workflow_result.json", registry=registry, offset=0, limit=500)
    assert isinstance(first, ArtifactSlice)
    assert len(first.content) == 500
    assert first.next_offset == 500
    assert first.total_length > 500

    second = tools.get_artifact(
        run_result.run_id, "workflow_result.json", registry=registry, offset=first.next_offset, limit=500,
    )
    assert isinstance(second, ArtifactSlice)
    assert second.offset == 500
    assert second.content != ""
    assert first.content != second.content


# ── Pagination bounds: explicit validation, never silent clamping ────────
def test_get_artifact_negative_offset_is_rejected(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, "workflow_result.json", registry=registry, offset=-1)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.INVALID_INPUT
    assert result.stage == "pagination_validation"
    assert result.recoverable is True


def test_get_artifact_zero_limit_is_rejected(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, "workflow_result.json", registry=registry, limit=0)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.INVALID_INPUT
    assert result.stage == "pagination_validation"


def test_get_artifact_negative_limit_is_rejected(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, "workflow_result.json", registry=registry, limit=-5)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.INVALID_INPUT


def test_get_artifact_oversized_limit_is_rejected_not_silently_clamped(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(
        run_result.run_id, "workflow_result.json", registry=registry, offset=0, limit=10_000_000,
    )
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.INVALID_INPUT
    assert str(tools.MAX_ARTIFACT_SLICE_CHARS) in result.message


def test_get_artifact_limit_at_exactly_the_maximum_is_accepted(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(
        run_result.run_id, "workflow_result.json", registry=registry, offset=0, limit=tools.MAX_ARTIFACT_SLICE_CHARS,
    )
    assert isinstance(result, ArtifactSlice)
    assert len(result.content) == tools.MAX_ARTIFACT_SLICE_CHARS


def test_get_artifact_limit_at_exactly_the_minimum_is_accepted(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(
        run_result.run_id, "workflow_result.json", registry=registry, offset=0, limit=tools.MIN_ARTIFACT_SLICE_LIMIT,
    )
    assert isinstance(result, ArtifactSlice)
    assert len(result.content) == tools.MIN_ARTIFACT_SLICE_LIMIT


def test_get_artifact_offset_zero_is_accepted(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(run_result.run_id, "workflow_result.json", registry=registry, offset=0)
    assert isinstance(result, ArtifactSlice)


def test_get_artifact_offset_equal_to_total_length_returns_empty_content_no_next_offset(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    whole = tools.get_artifact(run_result.run_id, "candidate_comparison.csv", registry=registry)
    assert whole.next_offset is None  # small file, one slice already reaches the end

    at_end = tools.get_artifact(
        run_result.run_id, "candidate_comparison.csv", registry=registry, offset=whole.total_length,
    )
    assert isinstance(at_end, ArtifactSlice)
    assert at_end.content == ""
    assert at_end.next_offset is None
    assert at_end.offset == whole.total_length
    assert at_end.total_length == whole.total_length


def test_get_artifact_offset_past_total_length_also_returns_empty_content_safely(fixed_config, registry):
    """Not itself an error case (offset >= 0 is the only required lower
    bound) -- an offset past the end degrades gracefully to an empty
    slice, the same as offset == total_length, never an exception."""
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    result = tools.get_artifact(
        run_result.run_id, "candidate_comparison.csv", registry=registry, offset=10_000_000, limit=100,
    )
    assert isinstance(result, ArtifactSlice)
    assert result.content == ""
    assert result.next_offset is None


def test_get_artifact_full_content_reassembles_via_pagination(fixed_config, registry):
    run_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=registry)
    chunks = []
    offset = 0
    while True:
        result = tools.get_artifact(
            run_result.run_id, "workflow_result.json", registry=registry, offset=offset, limit=1000,
        )
        chunks.append(result.content)
        if result.next_offset is None:
            break
        offset = result.next_offset
    reassembled = "".join(chunks)
    direct = (registry.get(run_result.run_id).artifact_dir / "workflow_result.json").read_text()
    assert reassembled == direct
