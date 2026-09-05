"""Phase 6 test matrix -- R3-CHAIN Final Research-Alignment Implementation
Specification, MCP dispatch extension: the research-experiment workflow
exposed through the SAME six geo_ tools (a discriminated geo_run_workflow
success type, config-driven dispatch, existing artifact allow-list/pagination,
a run-type discriminator surviving a persistent-registry restart) -- never a
seventh tool."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.mcp_server import tools
from r3chain_geothermal.mcp_server.errors import ToolError, ToolErrorCode
from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.schemas import (
    JointWorkflowSummary,
    ResearchExperimentSummary,
    RunSummary,
    RunWorkflowResult,
    SourceProvenanceInput,
)

_ROOT = Path(__file__).resolve().parents[2]
_RESEARCH_CONFIG_PATH = _ROOT / "config" / "research_experiment_synthetic.json"
_V2_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_joint_study_v2.json"
_CANONICAL_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _research_config() -> dict:
    return json.loads(_RESEARCH_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance_input(**overrides) -> SourceProvenanceInput:
    fields = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    fields.update(overrides)
    return SourceProvenanceInput(**fields)


@pytest.fixture
def registry():
    with tempfile.TemporaryDirectory() as td:
        yield RunRegistry(max_size=10, root_dir=Path(td))


# ── capabilities ──────────────────────────────────────────────────────────────

def test_capabilities_research_experiment_enabled_reflects_the_actual_loaded_config(registry):
    joint_only_caps = tools.get_capabilities(fixed_config=json.loads(_V2_CONFIG_PATH.read_text()), registry=registry)
    assert joint_only_caps.research_experiment_enabled is False

    research_caps = tools.get_capabilities(fixed_config=_research_config(), registry=registry)
    assert research_caps.research_experiment_enabled is True


def test_capabilities_allow_list_includes_every_research_experiment_artifact_filename(registry):
    caps = tools.get_capabilities(fixed_config=_research_config(), registry=registry)
    for filename in tools._RESEARCH_EXPERIMENT_ARTIFACT_FILENAMES:
        assert filename in caps.allowed_artifact_filenames


# ── dispatch: research_experiment takes priority over joint_study_v2 ─────────

def test_dispatch_routes_to_research_experiment_when_enabled(registry):
    result = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    assert isinstance(result, ResearchExperimentSummary)


def test_dispatch_routes_to_joint_workflow_when_research_experiment_not_enabled(registry):
    result = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=json.loads(_V2_CONFIG_PATH.read_text()), registry=registry,
        package_root=_ROOT,
    )
    assert isinstance(result, JointWorkflowSummary)


def test_dispatch_routes_to_canonical_when_neither_enabled(registry):
    result = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry,
    )
    assert isinstance(result, RunSummary)


# ── discriminated union round trip ────────────────────────────────────────────

def test_run_workflow_result_union_round_trips_the_research_experiment_variant(registry):
    adapter = TypeAdapter(RunWorkflowResult)
    result = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    round_tripped = adapter.validate_json(result.model_dump_json())
    assert type(round_tripped) is type(result)
    assert round_tripped == result


def test_research_experiment_summary_carries_no_candidate_rank_fields():
    fields = set(ResearchExperimentSummary.model_fields.keys())
    assert "ranked" not in fields
    assert "preferred_candidate_id" not in fields
    assert "infeasible" not in fields
    assert "preferred_alternative_id" in fields


# ── artifacts ──────────────────────────────────────────────────────────────────

def test_research_experiment_artifact_is_retrievable_through_geo_get_artifact(registry):
    run = tools.run_research_experiment_tool(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    result = tools.get_artifact(run.run_id, "research_experiment_report.md", registry=registry)
    assert "SYNTHETIC" in result.content


def test_research_experiment_artifact_forbidden_filename_still_rejected(registry):
    run = tools.run_research_experiment_tool(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    result = tools.get_artifact(run.run_id, "../../etc/passwd", registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.FORBIDDEN_ARTIFACT


def test_geo_get_artifact_lists_every_research_experiment_file(registry):
    run = tools.run_research_experiment_tool(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    assert set(run.artifact_filenames) == set(tools._RESEARCH_EXPERIMENT_ARTIFACT_FILENAMES)
    for filename in tools._RESEARCH_EXPERIMENT_ARTIFACT_FILENAMES:
        result = tools.get_artifact(run.run_id, filename, registry=registry)
        assert not isinstance(result, ToolError), f"{filename} should be retrievable: {result}"


# ── registry run-type discriminator ───────────────────────────────────────────

def test_registry_entry_carries_the_research_experiment_run_type(registry):
    run = tools.run_research_experiment_tool(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    entry = registry.get(run.run_id)
    assert entry.run_type == "research_experiment"


# ── restart recovery / rehydration ────────────────────────────────────────────

def test_restart_recovery_retrieves_the_same_research_experiment_run_without_recomputation():
    with tempfile.TemporaryDirectory() as td:
        run_root = Path(td)

        reg1 = RunRegistry(root_dir=run_root, persistent=True)
        first = tools.run_research_experiment_tool(
            _raw(), _provenance_input(), fixed_config=_research_config(), registry=reg1, package_root=_ROOT,
        )
        assert isinstance(first, ResearchExperimentSummary)
        reg1.close()

        reg2 = RunRegistry(root_dir=run_root, persistent=True)
        rehydrated = reg2.get(first.run_id)
        assert rehydrated is not None
        assert rehydrated.run_type == "research_experiment"
        assert rehydrated.summary.run_id == first.run_id
        assert rehydrated.summary.preferred_alternative_id == first.preferred_alternative_id
        reg2.close()


# ── caching ────────────────────────────────────────────────────────────────────

def test_repeated_identical_research_experiment_input_reuses_the_same_run(registry):
    first = tools.run_research_experiment_tool(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    second = tools.run_research_experiment_tool(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    assert first.run_id == second.run_id
    assert first.reused_existing_run is False
    assert second.reused_existing_run is True


def test_research_experiment_and_joint_runs_coexist_in_the_same_registry(registry):
    research_run = tools.run_research_experiment_tool(
        _raw(), _provenance_input(), fixed_config=_research_config(), registry=registry, package_root=_ROOT,
    )
    joint_run = tools.run_joint_workflow_tool(
        _raw(), _provenance_input(), fixed_config=json.loads(_V2_CONFIG_PATH.read_text()), registry=registry,
        package_root=_ROOT,
    )
    assert research_run.run_id != joint_run.run_id
    assert registry.get(research_run.run_id).run_type == "research_experiment"
    assert registry.get(joint_run.run_id).run_type == "joint_site_connection"
