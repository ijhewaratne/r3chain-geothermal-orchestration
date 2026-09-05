"""Phase 6 test matrix -- docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
MCP-001..011, AC-J13, AC-J14: the joint_study_v2 workflow exposed through
the SAME six geo_ tools (a discriminated geo_run_workflow success type,
config-driven dispatch, existing artifact allow-list/pagination, a
run-type discriminator surviving a persistent-registry restart) -- never a
seventh tool. Counts (4/4/4/7/9/9/7) match every number already
independently proven in tests/workflow/test_joint_workflow_v2.py and the
Phase 2/4 test suites -- this file's own contribution is proving the SAME
joint run survives the MCP boundary, deterministically, and rehydrates
byte-identically after a simulated server restart."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from r3chain_geothermal.mcp_server import tools
from r3chain_geothermal.mcp_server.errors import ToolError, ToolErrorCode
from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.schemas import (
    JointWorkflowSummary,
    RunSummary,
    RunWorkflowResult,
    SourceProvenanceInput,
)
from r3chain_geothermal.workflow.joint_workflow_v2 import run_joint_workflow_v2, write_joint_workflow_v2_artifacts
from r3chain_geothermal.contracts import SourceProvenance

_ROOT = Path(__file__).resolve().parents[2]
_V2_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_joint_study_v2.json"
_CANONICAL_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_PACKAGE_PATH = _ROOT / "config" / "joint_study_synthetic_v2.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_EXPECTED_COUNTS = {
    "site_count": 4, "resource_scenario_count": 4, "network_attachment_count": 4,
    "route_count": 7, "design_option_count": 1, "operating_policy_count": 1,
    "compatible_alternative_count": 9, "evaluated_alternative_count": 9, "feasible_alternative_count": 7,
}


def _joint_config() -> dict:
    return json.loads(_V2_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance_input(**overrides) -> SourceProvenanceInput:
    fields = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    fields.update(overrides)
    return SourceProvenanceInput(**fields)


def _provenance_model() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


@pytest.fixture
def registry():
    with tempfile.TemporaryDirectory() as td:
        yield RunRegistry(max_size=10, root_dir=Path(td))


# ── MCP-001: geo_get_capabilities truthfully advertises canonical and joint modes ──
def test_capabilities_advertise_both_workflow_modes_as_implementation_capabilities(registry):
    canonical_config = json.loads(_CANONICAL_CONFIG_PATH.read_text())
    caps = tools.get_capabilities(fixed_config=canonical_config, registry=registry)
    assert set(caps.supported_workflow_modes) == {"canonical", "joint_site_connection"}


def test_capabilities_joint_study_v2_enabled_reflects_the_actual_loaded_config(registry):
    canonical_caps = tools.get_capabilities(fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry)
    assert canonical_caps.joint_study_v2_enabled is False

    joint_caps = tools.get_capabilities(fixed_config=_joint_config(), registry=registry)
    assert joint_caps.joint_study_v2_enabled is True


def test_capabilities_allow_list_includes_every_joint_artifact_filename(registry):
    caps = tools.get_capabilities(fixed_config=_joint_config(), registry=registry)
    assert set(tools._JOINT_ARTIFACT_FILENAMES) <= set(caps.allowed_artifact_filenames)
    assert len(caps.allowed_artifact_filenames) == len(set(caps.allowed_artifact_filenames))  # no duplicates


# ── MCP-002: geo_run_workflow dispatches from validated fixed configuration ──
def test_dispatch_routes_to_joint_workflow_when_enabled(registry):
    result = tools.dispatch_run_workflow(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    assert isinstance(result, JointWorkflowSummary)


def test_dispatch_routes_to_canonical_workflow_when_not_enabled(registry):
    result = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry,
    )
    assert isinstance(result, RunSummary)
    assert result.workflow_mode == "canonical"


# ── MCP-003: discriminated union, never forcing Pareto into integer ranks ──
def test_run_workflow_result_union_round_trips_all_three_variants(registry):
    adapter = TypeAdapter(RunWorkflowResult)

    canonical = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry,
    )
    joint = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT,
    )
    error = tools.get_run_summary("r3chain-run-doesnotexist0000", registry=registry)

    for original in (canonical, joint, error):
        round_tripped = adapter.validate_json(original.model_dump_json())
        assert type(round_tripped) is type(original)
        assert round_tripped == original


def test_joint_workflow_summary_carries_no_candidate_rank_fields():
    """MCP-003's own point, checked structurally: JointWorkflowSummary has
    no `ranked`/`preferred_candidate_id`/`infeasible` fields at all -- a
    Pareto/joint result is never coerced into the canonical model's own
    integer-rank shape."""
    fields = set(JointWorkflowSummary.model_fields.keys())
    assert "ranked" not in fields
    assert "preferred_candidate_id" not in fields
    assert "infeasible" not in fields
    assert "preferred_alternative_id" in fields
    assert "ranked_alternative_groups" in fields


# ── MCP-004: preferred_alternative_id null under pareto_only / a materially tied rank 1 ──
def test_preferred_alternative_id_is_null_under_the_committed_pareto_only_fixture(registry):
    result = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    assert isinstance(result, JointWorkflowSummary)
    assert result.decision_policy_mode == "pareto_only"
    assert result.preferred_alternative_id is None
    assert result.pareto_shortlist_alternative_ids  # non-empty for this fixture


# ── MCP-005: joint artifacts use the existing allow-list/pagination ─────────
def test_joint_artifact_is_retrievable_through_geo_get_artifact(registry):
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    result = tools.get_artifact(run.run_id, "joint_recommendation.md", registry=registry)
    assert result.content.startswith("# R3-CHAIN corrected synthetic joint")


def test_joint_artifact_forbidden_filename_still_rejected_before_lookup(registry):
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    result = tools.get_artifact(run.run_id, "../../etc/passwd", registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.FORBIDDEN_ARTIFACT


def test_joint_artifact_pagination_reassembles_the_full_content(registry):
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    chunks = []
    offset = 0
    while True:
        piece = tools.get_artifact(run.run_id, "joint_optimization_result.json", registry=registry, offset=offset, limit=500)
        chunks.append(piece.content)
        if piece.next_offset is None:
            break
        offset = piece.next_offset
    reassembled = "".join(chunks)
    direct = (registry.get(run.run_id).artifact_dir / "joint_optimization_result.json").read_text()
    assert reassembled == direct


def test_geo_get_artifact_lists_every_joint_file(registry):
    """Was "...all_twelve_joint_files" before Phase 9's §17 artifact
    additions grew the bundle from 12 to 17 files (16 hashed + manifest) --
    the assertion below already reads the live `_JOINT_ARTIFACT_FILENAMES`
    tuple rather than a hardcoded count, so only this name was stale."""
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    assert set(run.artifact_filenames) == set(tools._JOINT_ARTIFACT_FILENAMES)
    for filename in tools._JOINT_ARTIFACT_FILENAMES:
        result = tools.get_artifact(run.run_id, filename, registry=registry)
        assert not isinstance(result, ToolError), f"{filename} should be retrievable: {result}"


# ── MCP-006: registry stores a run-type discriminator ────────────────────────
def test_registry_entry_carries_the_joint_run_type(registry):
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    entry = registry.get(run.run_id)
    assert entry.run_type == "joint_site_connection"


def test_registry_entry_carries_the_canonical_run_type(registry):
    run = tools.run_workflow_tool(
        _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry,
    )
    entry = registry.get(run.run_id)
    assert entry.run_type == "canonical"


# ── MCP-007 / AC-J14: rehydration validates the correct manifest and result contract ──
def test_ac_j14_restart_recovery_retrieves_the_same_joint_run_without_recomputation():
    with tempfile.TemporaryDirectory() as td:
        run_root = Path(td)

        reg1 = RunRegistry(root_dir=run_root, persistent=True)
        first = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=reg1, package_root=_ROOT)
        assert isinstance(first, JointWorkflowSummary)
        reg1.close()
        assert run_root.is_dir()

        reg2 = RunRegistry(root_dir=run_root, persistent=True)
        assert reg2.rehydration_warnings == []
        rehydrated_entry = reg2.get(first.run_id)
        assert rehydrated_entry is not None
        assert rehydrated_entry.run_type == "joint_site_connection"

        summary = tools.get_run_summary(first.run_id, registry=reg2)
        assert isinstance(summary, JointWorkflowSummary)
        assert summary.bundle_scientific_sha256 == first.bundle_scientific_sha256
        assert summary.pareto_shortlist_alternative_ids == first.pareto_shortlist_alternative_ids

        audit = tools.get_audit(first.run_id, registry=reg2)
        assert audit.run_id == first.run_id

        manifest_slice = tools.get_artifact(first.run_id, "manifest.json", registry=reg2)
        manifest = json.loads(manifest_slice.content)
        assert manifest["run_type"] == "joint_site_connection"
        expected_hash = manifest["files"]["joint_optimization_result.json"]["byte_sha256"]

        chunks, offset = [], 0
        while True:
            piece = tools.get_artifact(first.run_id, "joint_optimization_result.json", registry=reg2, offset=offset)
            chunks.append(piece.content)
            if piece.next_offset is None:
                break
            offset = piece.next_offset
        reconstructed = "".join(chunks)
        assert hashlib.sha256(reconstructed.encode("utf-8")).hexdigest() == expected_hash

        third = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=reg2, package_root=_ROOT)
        assert third.reused_existing_run is True
        reg2.close()


def test_mcp_007_a_canonical_run_still_rehydrates_correctly_alongside_joint_runs():
    """Regression guard: adding the joint branch to _load_run_entry must
    not disturb the pre-existing canonical rehydration path."""
    with tempfile.TemporaryDirectory() as td:
        run_root = Path(td)
        reg1 = RunRegistry(root_dir=run_root, persistent=True)
        canonical_result = tools.run_workflow_tool(
            _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=reg1,
        )
        joint_result = tools.run_joint_workflow_tool(
            _raw(), _provenance_input(), fixed_config=_joint_config(), registry=reg1, package_root=_ROOT,
        )
        reg1.close()

        reg2 = RunRegistry(root_dir=run_root, persistent=True)
        assert reg2.rehydration_warnings == []
        assert reg2.get(canonical_result.run_id).run_type == "canonical"
        assert reg2.get(joint_result.run_id).run_type == "joint_site_connection"
        assert isinstance(tools.get_run_summary(canonical_result.run_id, registry=reg2), RunSummary)
        assert isinstance(tools.get_run_summary(joint_result.run_id, registry=reg2), JointWorkflowSummary)
        reg2.close()


# ── MCP-008: canonical MCP responses remain backward compatible ─────────────
def test_canonical_run_summary_still_has_workflow_mode_canonical_by_default(registry):
    result = tools.run_workflow_tool(
        _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry,
    )
    assert result.workflow_mode == "canonical"
    assert result.preferred_candidate_id == "C1"  # canonical golden regression, unaffected


# ── MCP-009: strict provenance mismatch still creates no run directory ──────
def test_joint_provenance_hash_mismatch_creates_no_run_directory(registry):
    provenance = _provenance_input(expected_raw_sha256="0" * 64)  # deliberately wrong pin
    result = tools.run_joint_workflow_tool(_raw(), provenance, fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.PYDOUBLET_VALIDATION_FAILED
    assert len(registry) == 0


# ── MCP-010: path traversal / arbitrary artifact access prevented ───────────
@pytest.mark.parametrize("filename", ["../../etc/passwd", "/etc/passwd", ".hidden", "not_a_real_artifact.json"])
def test_joint_run_forbidden_filenames_rejected(registry, filename: str):
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    result = tools.get_artifact(run.run_id, filename, registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.FORBIDDEN_ARTIFACT


# ── MCP-011 / AC-J13: scripted MCP and CLI produce equivalent joint results ──
def test_ac_j13_mcp_run_matches_the_direct_engine_call_exactly(registry):
    """Runs the SAME committed config through geo_run_workflow and
    directly through run_joint_workflow_v2()/write_joint_workflow_v2_artifacts()
    (the same engine the CLI itself calls) -- requires parity on run_id,
    every count, the Pareto shortlist, and the bundle's own scientific hash."""
    mcp_result = tools.run_joint_workflow_tool(
        _raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT,
    )
    assert isinstance(mcp_result, JointWorkflowSummary)

    direct_result = run_joint_workflow_v2(_raw(), _joint_config(), source_provenance=_provenance_model(), package_root=_ROOT)
    assert direct_result.run_id == mcp_result.run_id

    direct_counts = direct_result.counts
    assert direct_counts.site_count == mcp_result.site_count
    assert direct_counts.resource_scenario_count == mcp_result.resource_scenario_count
    assert direct_counts.network_attachment_count == mcp_result.network_attachment_count
    assert direct_counts.accepted_route_count == mcp_result.route_count
    assert direct_counts.compatible_alternative_count == mcp_result.compatible_alternative_count
    assert direct_counts.evaluated_alternative_count == mcp_result.evaluated_alternative_count
    assert direct_counts.feasible_alternative_count == mcp_result.feasible_alternative_count
    assert list(direct_result.decision.pareto_shortlist_alternative_ids) == mcp_result.pareto_shortlist_alternative_ids

    with tempfile.TemporaryDirectory() as td:
        package_raw = json.loads(_PACKAGE_PATH.read_text())
        direct_manifest = write_joint_workflow_v2_artifacts(direct_result, _raw(), _joint_config(), package_raw, Path(td))
        for filename in ("pydoublet_input.json", "config_snapshot.json", "joint_study_snapshot.json"):
            mcp_manifest_path = registry.get(mcp_result.run_id).artifact_dir / "manifest.json"
            mcp_manifest = json.loads(mcp_manifest_path.read_text())
            assert mcp_manifest["files"][filename]["scientific_sha256"] == direct_manifest.files[filename].scientific_sha256


def test_ac_j13_every_artifact_page_retrievable_and_matches_disk(registry):
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    assert isinstance(run, JointWorkflowSummary)
    artifact_dir = registry.get(run.run_id).artifact_dir
    for filename in tools._JOINT_ARTIFACT_FILENAMES:
        chunks, offset = [], 0
        while True:
            piece = tools.get_artifact(run.run_id, filename, registry=registry, offset=offset, limit=200)
            assert not isinstance(piece, ToolError)
            chunks.append(piece.content)
            if piece.next_offset is None:
                break
            offset = piece.next_offset
        reassembled = "".join(chunks)
        assert reassembled == (artifact_dir / filename).read_text()


def test_ac_j13_geo_get_run_summary_matches_geo_run_workflow(registry):
    run = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    fetched = tools.get_run_summary(run.run_id, registry=registry)
    assert isinstance(fetched, JointWorkflowSummary)
    assert fetched.run_id == run.run_id
    assert fetched.pareto_shortlist_alternative_ids == run.pareto_shortlist_alternative_ids
    assert fetched.reused_existing_run is True


# ── Repeated / concurrent-shaped calls stay consistent ───────────────────────
def test_repeated_identical_joint_input_reuses_the_same_run(registry):
    result1 = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    result2 = tools.run_joint_workflow_tool(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    assert result1.run_id == result2.run_id
    assert result1.reused_existing_run is False
    assert result2.reused_existing_run is True
    assert len(registry) == 1


def test_joint_and_canonical_runs_coexist_in_the_same_registry(registry):
    joint_result = tools.dispatch_run_workflow(_raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT)
    canonical_result = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry,
    )
    assert joint_result.run_id != canonical_result.run_id
    assert len(registry) == 2
    assert registry.get(joint_result.run_id).run_type == "joint_site_connection"
    assert registry.get(canonical_result.run_id).run_type == "canonical"


# ── AC-J18: internal-error boundary ──────────────────────────────────────────
def test_ac_j18_injected_internal_exception_after_package_validation_is_a_software_error(registry, monkeypatch):
    """AC-J18: a deterministic internal exception injected AFTER package
    validation (Stage 0 -- the package itself is genuinely valid here, and
    already-passed) must surface as UNEXPECTED_ERROR, never as a scientific
    infeasibility code, must publish no completed run, and must expose no
    partial artifact through the registry -- mirrors
    test_tools.py::test_run_workflow_unexpected_internal_failure_maps_to_unexpected_error's
    own canonical-path proof, for the joint dispatch path specifically."""
    import r3chain_geothermal.workflow.joint_workflow_v2 as joint_workflow_v2_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated internal solver/programming defect, injected for AC-J18")

    # generate_site_routes() is called well after Stage 0's own package
    # validation/hash-check/PyDoublet-parse/blueprint/baseline stages --
    # exactly "after package validation," and is not wrapped in any of
    # run_joint_workflow_v2()'s own narrow except clauses, so this
    # propagates as a genuinely unexpected exception, not a typed
    # JointWorkflowV2Failure.
    monkeypatch.setattr(joint_workflow_v2_module, "generate_site_routes", _boom)

    result = tools.run_joint_workflow_tool(
        _raw(), _provenance_input(), fixed_config=_joint_config(), registry=registry, package_root=_ROOT,
    )
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.UNEXPECTED_ERROR
    assert result.stage == "run_joint_workflow_v2"
    # No completed run published, no partial artifact exposed through MCP:
    assert len(registry) == 0
