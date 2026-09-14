"""Fixed-DH-interface drilling-site-optimization correction, exposed
through the SAME six geo_ tools (config-driven dispatch, existing
artifact allow-list/pagination, a run-type discriminator surviving a
persistent-registry restart) -- never a seventh tool."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from r3chain_geothermal.mcp_server import tools
from r3chain_geothermal.mcp_server.errors import ToolError, ToolErrorCode
from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.schemas import FixedInterfaceWorkflowSummary, RunSummary, SourceProvenanceInput

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_fixed_interface_site_optimization.json"
_CANONICAL_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


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


def test_capabilities_advertise_fixed_interface_mode_as_an_implementation_capability(registry):
    caps = tools.get_capabilities(fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry)
    assert "fixed_interface_site_optimization" in caps.supported_workflow_modes
    assert caps.fixed_interface_site_optimization_enabled is False


def test_capabilities_enabled_flag_reflects_the_actual_loaded_config(registry):
    caps = tools.get_capabilities(fixed_config=_config(), registry=registry)
    assert caps.fixed_interface_site_optimization_enabled is True


def test_dispatch_routes_to_fixed_interface_workflow_when_enabled(registry):
    result = tools.dispatch_run_workflow(_raw(), _provenance_input(), fixed_config=_config(), registry=registry, package_root=_ROOT)
    assert isinstance(result, FixedInterfaceWorkflowSummary)
    assert result.fixed_dh_integration_point_id == "dh_integration_station_1"


def test_dispatch_routes_to_canonical_workflow_when_not_enabled(registry):
    result = tools.dispatch_run_workflow(
        _raw(), _provenance_input(), fixed_config=json.loads(_CANONICAL_CONFIG_PATH.read_text()), registry=registry,
    )
    assert isinstance(result, RunSummary)


def test_summary_names_the_preferred_drilling_site_not_an_attachment(registry):
    result = tools.run_fixed_interface_site_optimization_tool(
        _raw(), _provenance_input(), fixed_config=_config(), registry=registry, package_root=_ROOT,
    )
    assert isinstance(result, FixedInterfaceWorkflowSummary)
    assert result.preferred_drilling_site_id == "site_alpha"
    assert "trunk" not in (result.preferred_drilling_site_id or "")


def test_fixed_interface_artifact_is_retrievable_through_geo_get_artifact(registry):
    run = tools.run_fixed_interface_site_optimization_tool(
        _raw(), _provenance_input(), fixed_config=_config(), registry=registry, package_root=_ROOT,
    )
    result = tools.get_artifact(run.run_id, "research_findings.md", registry=registry)
    assert not isinstance(result, ToolError)
    assert "Fixed DH integration station" in result.content


def test_registry_entry_carries_the_fixed_interface_run_type(registry):
    run = tools.run_fixed_interface_site_optimization_tool(
        _raw(), _provenance_input(), fixed_config=_config(), registry=registry, package_root=_ROOT,
    )
    entry = registry.get(run.run_id)
    assert entry.run_type == "fixed_interface_site_optimization"


def test_restart_recovery_retrieves_the_same_run_without_recomputation():
    with tempfile.TemporaryDirectory() as td:
        run_root = Path(td)

        reg1 = RunRegistry(root_dir=run_root, persistent=True)
        first = tools.run_fixed_interface_site_optimization_tool(
            _raw(), _provenance_input(), fixed_config=_config(), registry=reg1, package_root=_ROOT,
        )
        assert isinstance(first, FixedInterfaceWorkflowSummary)
        reg1.close()

        reg2 = RunRegistry(root_dir=run_root, persistent=True)
        assert reg2.rehydration_warnings == []
        rehydrated_entry = reg2.get(first.run_id)
        assert rehydrated_entry is not None
        assert rehydrated_entry.run_type == "fixed_interface_site_optimization"

        summary = tools.get_run_summary(first.run_id, registry=reg2)
        assert isinstance(summary, FixedInterfaceWorkflowSummary)
        assert summary.bundle_scientific_sha256 == first.bundle_scientific_sha256
        assert summary.preferred_drilling_site_id == first.preferred_drilling_site_id

        third = tools.run_fixed_interface_site_optimization_tool(
            _raw(), _provenance_input(), fixed_config=_config(), registry=reg2, package_root=_ROOT,
        )
        assert third.reused_existing_run is True
        reg2.close()


def test_repeated_identical_input_reuses_the_same_run(registry):
    result1 = tools.run_fixed_interface_site_optimization_tool(
        _raw(), _provenance_input(), fixed_config=_config(), registry=registry, package_root=_ROOT,
    )
    result2 = tools.run_fixed_interface_site_optimization_tool(
        _raw(), _provenance_input(), fixed_config=_config(), registry=registry, package_root=_ROOT,
    )
    assert result1.run_id == result2.run_id
    assert result1.reused_existing_run is False
    assert result2.reused_existing_run is True
    assert len(registry) == 1


def test_provenance_hash_mismatch_creates_no_run_directory(registry):
    provenance = _provenance_input(expected_raw_sha256="0" * 64)
    result = tools.run_fixed_interface_site_optimization_tool(
        _raw(), provenance, fixed_config=_config(), registry=registry, package_root=_ROOT,
    )
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.PYDOUBLET_VALIDATION_FAILED
    assert len(registry) == 0


@pytest.mark.parametrize("filename", ["../../etc/passwd", "/etc/passwd", ".hidden", "not_a_real_artifact.json"])
def test_forbidden_filenames_rejected(registry, filename: str):
    run = tools.run_fixed_interface_site_optimization_tool(
        _raw(), _provenance_input(), fixed_config=_config(), registry=registry, package_root=_ROOT,
    )
    result = tools.get_artifact(run.run_id, filename, registry=registry)
    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.FORBIDDEN_ARTIFACT
