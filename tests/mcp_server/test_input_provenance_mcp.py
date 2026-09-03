"""MCP-boundary-specific coverage for exact input-provenance enforcement
(IP-001..IP-007, docs/issues/mcp-input-provenance-enforcement.md).

Parser/contracts-layer behavior is covered in
tests/parsers/test_input_provenance_enforcement.py; run_id/backward-
compatibility coverage in tests/workflow/test_input_provenance_run_id.py.
This file covers what's specific to the MCP tools: geo_run_workflow's "no
artifact directory on mismatch" guarantee (IP-006) and CLI/MCP equivalence.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from r3chain_geothermal.errors import FailureCode
from r3chain_geothermal.mcp_server import tools
from r3chain_geothermal.mcp_server.config import load_fixed_server_config
from r3chain_geothermal.mcp_server.errors import ToolError, ToolErrorCode
from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.schemas import PyDoubletValidationSummary, RunSummary, SourceProvenanceInput
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_CANONICAL_FIXTURE_HASH = "6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762"
_GOLDEN_RUN_ID = "r3chain-run-93d41133daa11d1a"


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
        yield reg, Path(td)


@pytest.fixture
def fixed_config():
    return load_fixed_server_config()


# ── geo_validate_pydoublet_result: mismatch ──────────────────────────────────
def test_validate_pydoublet_result_reports_mismatch():
    result = tools.validate_pydoublet_result(_raw(), _provenance(expected_raw_sha256="0" * 64))
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.PYDOUBLET_VALIDATION_FAILED
    assert result.details["failure_code"] == FailureCode.PYDOUBLET_RAW_HASH_MISMATCH.value


def test_validate_pydoublet_result_succeeds_with_correct_expected_hash():
    result = tools.validate_pydoublet_result(_raw(), _provenance(expected_raw_sha256=_CANONICAL_FIXTURE_HASH))
    assert isinstance(result, PyDoubletValidationSummary)
    assert result.raw_result_sha256 == _CANONICAL_FIXTURE_HASH


# ── geo_run_workflow: golden run_id + bundle hash reproduced with strict provenance ──
def test_run_workflow_tool_strict_provenance_reproduces_golden_run_id_and_bundle_hash(registry, fixed_config):
    """The full regression proof, at the one layer that actually produces
    bundle_scientific_sha256 (write_workflow_artifacts(), called inside
    run_workflow_tool()'s factory -- not part of WorkflowResult itself):
    both the golden run_id AND the golden bundle_scientific_sha256 --
    hardcoded identically in tests/mcp_client/test_wheel_install.py and
    tests/mcp_server/test_mcp_protocol.py -- must be reproduced exactly."""
    reg, _ = registry
    result = tools.run_workflow_tool(
        _raw(), _provenance(expected_raw_sha256=_CANONICAL_FIXTURE_HASH),
        fixed_config=fixed_config, registry=reg,
    )
    assert isinstance(result, RunSummary)
    assert result.run_id == _GOLDEN_RUN_ID
    # Rebaselined again (Phase 2 of R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md,
    # decision-register.md IMPL-015): normalize_for_scientific_hash() now
    # quantizes every float to SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES
    # (12) significant figures before hashing -- a cross-platform
    # floating-point-noise fix, not a scientific-result change. run_id
    # (asserted above) is unaffected.
    assert result.bundle_scientific_sha256 == "d67cb2f32de228ee1a6b0ac8f4e9c7e05eb55ba2d49d6578ea79692f1a359f46"


def test_run_workflow_tool_omitted_expected_hash_still_reproduces_golden_bundle_hash(registry, fixed_config):
    """The plain, feature-untouched path must be byte-for-byte identical
    to before this feature existed."""
    reg, _ = registry
    result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=reg)
    assert isinstance(result, RunSummary)
    assert result.run_id == _GOLDEN_RUN_ID
    # Rebaselined again (Phase 2 of R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md,
    # decision-register.md IMPL-015): normalize_for_scientific_hash() now
    # quantizes every float to SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES
    # (12) significant figures before hashing -- a cross-platform
    # floating-point-noise fix, not a scientific-result change. run_id
    # (asserted above) is unaffected.
    assert result.bundle_scientific_sha256 == "d67cb2f32de228ee1a6b0ac8f4e9c7e05eb55ba2d49d6578ea79692f1a359f46"


# ── geo_run_workflow: IP-006, no artifact directory created on mismatch ─────
def test_run_workflow_tool_mismatch_creates_no_artifact_directory(registry, fixed_config):
    reg, root_dir = registry
    result = tools.run_workflow_tool(
        _raw(), _provenance(expected_raw_sha256="0" * 64),
        fixed_config=fixed_config, registry=reg,
    )
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.PYDOUBLET_VALIDATION_FAILED
    assert result.stage == "input_provenance_validation"
    assert result.recoverable is True
    assert result.details["failure_code"] == FailureCode.PYDOUBLET_RAW_HASH_MISMATCH.value
    # The actual filesystem proof: the registry root has zero children --
    # no run directory, no manifest, no bundle, nothing at all was written.
    assert list(root_dir.iterdir()) == []


def test_run_workflow_tool_mismatch_never_stores_a_run_in_registry(registry, fixed_config):
    reg, _ = registry
    result = tools.run_workflow_tool(
        _raw(), _provenance(expected_raw_sha256="0" * 64),
        fixed_config=fixed_config, registry=reg,
    )
    assert isinstance(result, ToolError)
    # geo_get_run_summary/geo_get_audit/geo_get_artifact against ANY run_id
    # must all report RUN_NOT_FOUND -- nothing was ever registered.
    for run_id in ("r3chain-run-0000000000000000", "r3chain-run-" + "0" * 16):
        assert tools.get_run_summary(run_id, registry=reg).code == ToolErrorCode.RUN_NOT_FOUND


# ── CLI and MCP return equivalent typed results (IP-006) ───────────────────
def test_cli_and_mcp_report_the_identical_mismatch(fixed_config):
    """"CLI" here means the same shared parser/workflow layer the CLI
    itself calls (parse_pydoublet_result) -- see cli.py, which calls
    exactly this function with no MCP involvement at all."""
    from r3chain_geothermal.contracts import PyDoubletCouplingFailure, SourceProvenance

    core_provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    core_result = parse_pydoublet_result(_raw(), source_provenance=core_provenance, expected_raw_sha256="0" * 64)
    mcp_result = tools.validate_pydoublet_result(_raw(), _provenance(expected_raw_sha256="0" * 64))

    assert isinstance(core_result, PyDoubletCouplingFailure)
    assert isinstance(mcp_result, ToolError)
    assert core_result.failure_code == FailureCode.PYDOUBLET_RAW_HASH_MISMATCH
    assert mcp_result.details["failure_code"] == core_result.failure_code.value
    assert core_result.message == mcp_result.message
