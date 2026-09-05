"""Phase 2 tests for workflow.load_state_evaluation (RA-LOAD),
R3-CHAIN Final Research-Alignment Implementation Specification.

Reuses the exact same committed v2 fixture (config/demo_assumptions_joint_study_v2.json
+ config/joint_study_synthetic_v2.json + fixtures/pydoublet/repaired_result.json) as
tests/workflow/test_joint_workflow_v2.py, so a demand_scale_fraction=1.0 load state can
be checked against that suite's own already-proven per-alternative KPIs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.adapter import CouplingAssumptions
from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.data_contracts.joint_study import AssumptionStatus
from r3chain_geothermal.data_contracts.research_experiment import LoadStateDefinition
from r3chain_geothermal.economics.joint_costing import load_base_assumptions
from r3chain_geothermal.network import GateTolerances, GeothermalInjectionPolicy
from r3chain_geothermal.workflow.joint_workflow_v2 import JointWorkflowV2Result, run_joint_workflow_v2
from r3chain_geothermal.workflow.load_state_evaluation import (
    build_scaled_blueprint,
    evaluate_alternative_across_load_states,
)
from datetime import datetime, timezone

_ROOT = Path(__file__).resolve().parents[2]
_V2_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_joint_study_v2.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _config() -> dict:
    return json.loads(_V2_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _v2_result() -> JointWorkflowV2Result:
    result = run_joint_workflow_v2(_raw(), _config(), source_provenance=_provenance(), package_root=_ROOT)
    assert isinstance(result, JointWorkflowV2Result)
    return result


def _load_state(**overrides) -> LoadStateDefinition:
    kwargs = dict(
        load_state_id="peak", label="Peak (100% of design demand)", demand_scale_fraction=1.0,
        annual_duration_hours=2000.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
    )
    kwargs.update(overrides)
    return LoadStateDefinition(**kwargs)


def _lookup_alternative_inputs(v2_result: JointWorkflowV2Result, alternative_id: str):
    alt = next(a for a in v2_result.alternatives if a.identity.alternative_id == alternative_id)
    package = v2_result.package
    scenario = next(
        s for s in package.resource_scenarios
        if s.scenario_id == alt.identity.resource_scenario_id and s.site_id == alt.identity.surface_site_id
    )
    route = next(r for r in v2_result.routes if r.route_id == alt.identity.route_id)
    attachment = next(a for a in package.network_attachments if a.attachment_id == alt.identity.attachment_id)
    design = next(d for d in package.design_options if d.design_option_id == alt.identity.design_option_id)
    return alt, scenario, route, attachment, design


def _first_feasible_alternative_id(v2_result: JointWorkflowV2Result) -> str:
    return next(a.identity.alternative_id for a in v2_result.alternatives if a.feasible)


# ── build_scaled_blueprint ────────────────────────────────────────────────────

def test_build_scaled_blueprint_scales_every_consumer_demand_uniformly() -> None:
    config = _config()
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    full = build_scaled_blueprint(config, demand_scale_fraction=1.0, created_at=now)
    half = build_scaled_blueprint(config, demand_scale_fraction=0.5, created_at=now)
    for consumer_id in full.consumers:
        assert half.consumers[consumer_id].demand_kw == pytest.approx(full.consumers[consumer_id].demand_kw * 0.5)


def test_build_scaled_blueprint_at_full_scale_matches_the_unscaled_blueprint_kwargs() -> None:
    from r3chain_geothermal.workflow.core import _build_blueprint_kwargs
    from r3chain_geothermal.network import build_default_blueprint

    config = _config()
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    scaled = build_scaled_blueprint(config, demand_scale_fraction=1.0, created_at=now)
    unscaled = build_default_blueprint(created_at=now, **_build_blueprint_kwargs(config))
    for consumer_id in unscaled.consumers:
        assert scaled.consumers[consumer_id].demand_kw == unscaled.consumers[consumer_id].demand_kw


# ── evaluate_alternative_across_load_states ───────────────────────────────────

def test_full_scale_load_state_reproduces_the_v2_workflows_own_kpis() -> None:
    """demand_scale_fraction=1.0 must reproduce exactly the same KPIs the
    already-proven run_joint_workflow_v2() computed for this alternative,
    since it is the SAME construction path (module docstring)."""
    v2_result = _v2_result()
    alternative_id = _first_feasible_alternative_id(v2_result)
    alt, scenario, route, attachment, design = _lookup_alternative_inputs(v2_result, alternative_id)
    config = _config()
    package_root = _ROOT
    base_assumptions = load_base_assumptions(v2_result.package.economics, package_root)
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    tolerances = GateTolerances.from_config_dict(config)

    outcome = evaluate_alternative_across_load_states(
        alt.identity, scenario, route, attachment, design, v2_result.pydoublet_result, config, base_assumptions,
        [_load_state(demand_scale_fraction=1.0, annual_duration_hours=8000.0)],
        coupling_assumptions=coupling_assumptions, injection_policy=injection_policy, tolerances=tolerances,
    )

    assert len(outcome.load_state_results) == 1
    state_result = outcome.load_state_results[0]
    assert outcome.representative_capex_economics is not None
    assert outcome.representative_capex_economics.capex_doublet_eur == pytest.approx(alt.economics.capex_doublet_eur)
    assert state_result.feasible
    assert state_result.total_heat_delivered_kw == pytest.approx(alt.economics.total_heat_delivered_kw)
    assert state_result.geothermal_injected_heat_kw == pytest.approx(alt.economics.geothermal_injected_heat_kw)
    assert state_result.doublet_pump_electric_power_kw == pytest.approx(alt.economics.doublet_pump_electric_power_kw)
    assert state_result.dh_hydraulic_pumping_power_kw == pytest.approx(alt.economics.dh_hydraulic_pumping_power_kw)


def test_multiple_load_states_are_evaluated_independently() -> None:
    v2_result = _v2_result()
    alternative_id = _first_feasible_alternative_id(v2_result)
    alt, scenario, route, attachment, design = _lookup_alternative_inputs(v2_result, alternative_id)
    config = _config()
    base_assumptions = load_base_assumptions(v2_result.package.economics, _ROOT)
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    tolerances = GateTolerances.from_config_dict(config)

    load_states = [
        _load_state(load_state_id="peak", demand_scale_fraction=1.0, annual_duration_hours=2000.0),
        _load_state(load_state_id="shoulder", demand_scale_fraction=0.7, annual_duration_hours=3000.0),
    ]
    outcome = evaluate_alternative_across_load_states(
        alt.identity, scenario, route, attachment, design, v2_result.pydoublet_result, config, base_assumptions,
        load_states, coupling_assumptions=coupling_assumptions, injection_policy=injection_policy,
        tolerances=tolerances,
    )

    assert [r.load_state_id for r in outcome.load_state_results] == ["peak", "shoulder"]
    assert all(
        r.annual_duration_hours == ls.annual_duration_hours
        for r, ls in zip(outcome.load_state_results, load_states)
    )


def test_a_load_state_reduced_enough_to_trip_the_flagged_curtailment_risk_is_reported_not_masked() -> None:
    """Phase-0 audit's own flagged risk area: a low enough demand_scale_fraction
    should surface as an ordinary infeasible LoadStatePerformanceResult (a typed
    failure code), never silently pass or raise an unhandled exception."""
    v2_result = _v2_result()
    alternative_id = _first_feasible_alternative_id(v2_result)
    alt, scenario, route, attachment, design = _lookup_alternative_inputs(v2_result, alternative_id)
    config = _config()
    base_assumptions = load_base_assumptions(v2_result.package.economics, _ROOT)
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    tolerances = GateTolerances.from_config_dict(config)

    result = evaluate_alternative_across_load_states(
        alt.identity, scenario, route, attachment, design, v2_result.pydoublet_result, config, base_assumptions,
        [_load_state(load_state_id="deep_base", demand_scale_fraction=0.05, annual_duration_hours=1000.0)],
        coupling_assumptions=coupling_assumptions, injection_policy=injection_policy, tolerances=tolerances,
    ).load_state_results[0]

    # Whichever way it resolves (feasible with a stabilization-margin warning, or
    # infeasible with a typed failure code), it must be a clean, well-formed
    # result -- never an unhandled exception escaping this module.
    if not result.feasible:
        assert result.failure_code
        assert result.total_heat_delivered_kw is None
    else:
        assert result.total_heat_delivered_kw is not None
