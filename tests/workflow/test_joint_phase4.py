"""Phase 4 integration test matrix -- proves AC-J09 and AC-J11 of
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
against the committed synthetic v2 study package
(config/joint_study_synthetic_v2.json), end to end: economics ->
objective values -> decision. See tests/workflow/test_joint_phase2.py for
AC-J02-J07 and tests/decision/, tests/economics/ for isolated unit
coverage of the materiality/costing logic itself."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from r3chain_geothermal.adapter import CouplingAssumptions
from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.data_contracts.joint_study import DecisionPolicyMode, JointStudyPackage
from r3chain_geothermal.decision.joint_policy import compute_alternative_objective_values, decide
from r3chain_geothermal.economics.costing import compute_baseline_economics
from r3chain_geothermal.economics.joint_costing import load_base_assumptions
from r3chain_geothermal.network import GateTolerances, GeothermalInjectionPolicy, build_default_blueprint, run_baseline_evaluation
from r3chain_geothermal.network.site_routing import generate_site_routes
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result
from r3chain_geothermal.workflow.joint_enumeration import enumerate_compatible_alternatives
from r3chain_geothermal.workflow.joint_evaluation import evaluate_compatible_alternatives

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_PACKAGE_PATH = _ROOT / "config" / "joint_study_synthetic_v2.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


def _run_phase4_pipeline(decision_mode: DecisionPolicyMode = DecisionPolicyMode.PARETO_ONLY, **policy_overrides):
    config = json.loads(_CONFIG_PATH.read_text())
    package = JointStudyPackage.model_validate_json(_PACKAGE_PATH.read_text())
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    golden = parse_pydoublet_result(raw, source_provenance=provenance)
    bp = build_default_blueprint(
        consumer_demands_kw=_DEMANDS, trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0, created_at=datetime.now(timezone.utc),
    )
    tolerances = GateTolerances.from_config_dict(config)
    baseline = run_baseline_evaluation(bp, tolerances=tolerances)
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    base_assumptions = load_base_assumptions(package.economics, _ROOT)
    baseline_economics = compute_baseline_economics(baseline, assumptions=base_assumptions)

    routes = generate_site_routes(package.sites, package.network_attachments, package.routing_policy)
    identities = enumerate_compatible_alternatives(package, routes)
    attachments_by_id = {a.attachment_id: a for a in package.network_attachments}
    routes_by_id = {r.route_id: r for r in routes}
    results = evaluate_compatible_alternatives(
        identities, package, routes_by_id, attachments_by_id, golden, bp, baseline, baseline_economics, base_assumptions,
        coupling_assumptions=coupling_assumptions, injection_policy=injection_policy, tolerances=tolerances,
    )
    feasible = [r for r in results if r.feasible]
    assert feasible, "the fixture must produce at least one feasible alternative"

    policy = package.decision_policy.model_copy(update={"mode": decision_mode, **policy_overrides})
    alt_values = [
        compute_alternative_objective_values(r.identity.alternative_id, r.candidate_result, r.economics, policy.objectives)
        for r in feasible
    ]
    decision = decide(alt_values, policy)
    return feasible, decision


# ── AC-J09: economic traceability -- independently recompute from artifacts ──
def test_ac_j09_lcoh_independently_recomputed_from_the_serialized_result():
    feasible, _ = _run_phase4_pipeline()
    one = feasible[0]
    econ = one.economics
    assert econ is not None

    # Round-trip through JSON, simulating reading a persisted artifact
    # rather than the live Python object.
    artifact = json.loads(econ.model_dump_json())

    # Independently recompute LCOH = annualised_cost_total / annual_heat_delivered,
    # from the artifact's own primitive numbers only -- no call into
    # economics.costing or economics.joint_costing.
    recomputed_lcoh_eur_per_kwh = artifact["annualised_cost_total_eur_per_a"] / artifact["annual_total_heat_delivered_kwh"]
    assert recomputed_lcoh_eur_per_kwh == pytest.approx(artifact["indicative_lcoh_eur_per_kwh"], rel=1e-9)

    # Independently recompute total CAPEX and cross-check the annualised
    # total against annuity_capital + opex components.
    recomputed_annualised_total = (
        artifact["annuity_capital_eur_per_a"] + artifact["opex_fixed_eur_per_a"]
        + artifact["opex_electricity_doublet_pump_eur_per_a"] + artifact["opex_electricity_dh_pumping_eur_per_a"]
        + artifact["opex_auxiliary_heat_eur_per_a"]
    )
    assert recomputed_annualised_total == pytest.approx(artifact["annualised_cost_total_eur_per_a"], rel=1e-9)

    # Independently recompute connection-pipe CAPEX from the route length
    # and the alternative's OWN design rate (ECON-006/007).
    package = JointStudyPackage.model_validate_json(_PACKAGE_PATH.read_text())
    design = next(d for d in package.design_options if d.design_option_id == one.identity.design_option_id)
    recomputed_connection_capex = one.candidate_result.candidate.surface_connection_length_m * design.capex_eur_per_paired_trench_m
    assert recomputed_connection_capex == pytest.approx(artifact["capex_connection_pipes_eur"], rel=1e-9)


def test_ac_j09_doublet_capex_traces_to_the_scenarios_own_declared_value():
    feasible, _ = _run_phase4_pipeline()
    package = JointStudyPackage.model_validate_json(_PACKAGE_PATH.read_text())
    scenarios_by_key = {(s.scenario_id, s.site_id): s for s in package.resource_scenarios}
    for alt in feasible:
        scenario = scenarios_by_key[(alt.identity.resource_scenario_id, alt.identity.surface_site_id)]
        assert alt.economics.capex_doublet_eur == pytest.approx(scenario.economic_inputs.doublet_capex_eur, rel=1e-9)


# ── AC-J11: decision modes ────────────────────────────────────────────────────
def test_ac_j11_pareto_only_mode_has_no_preferred_id():
    _, decision = _run_phase4_pipeline(decision_mode=DecisionPolicyMode.PARETO_ONLY)
    assert decision.preferred_alternative_id is None
    assert decision.ranked_alternative_groups == []
    assert decision.pareto_shortlist_alternative_ids  # non-empty on this fixture


def test_ac_j11_primary_objective_ranking_produces_a_deterministic_full_list():
    feasible, decision = _run_phase4_pipeline(
        decision_mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING,
        primary_objective="indicative_system_lcoh_eur_per_mwh",
        tie_breakers=["total_pumping_electric_energy_mwh_per_a"],
    )
    ranked_ids = [aid for group in decision.ranked_alternative_groups for aid in group]
    assert sorted(ranked_ids) == sorted(r.identity.alternative_id for r in feasible)
    # Pareto set preserved alongside the ranking (DEC-013).
    assert decision.pareto_shortlist_alternative_ids


def test_ac_j11_the_two_geometrically_symmetric_gamma_alternatives_share_a_rank():
    """The committed fixture's own site_gamma sits equidistant from
    trunk_2 and trunk_4 (S8.1's own geometry) -- scenario_gamma_higher_flow
    paired with each produces IDENTICAL cost/LCOH, a genuine, measured
    material tie this run must report as one shared rank, not an
    arbitrary ordering (AC-J11)."""
    feasible, decision = _run_phase4_pipeline(
        decision_mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING,
        primary_objective="indicative_system_lcoh_eur_per_mwh",
        tie_breakers=["total_pumping_electric_energy_mwh_per_a"],
    )
    gamma_trunk2 = "scenario_gamma_higher_flow|site_gamma|trunk_2|route-site_gamma-trunk_2-synthetic_polyline|standard|standard"
    gamma_trunk4 = "scenario_gamma_higher_flow|site_gamma|trunk_4|route-site_gamma-trunk_4-synthetic_polyline|standard|standard"
    ids = {r.identity.alternative_id for r in feasible}
    assert gamma_trunk2 in ids and gamma_trunk4 in ids

    owning_group = next(g for g in decision.ranked_alternative_groups if gamma_trunk2 in g)
    assert gamma_trunk4 in owning_group
    assert len(owning_group) == 2


def test_ac_j11_unique_rank_one_yields_a_preferred_id_with_a_caveat():
    _, decision = _run_phase4_pipeline(
        decision_mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING,
        primary_objective="indicative_system_lcoh_eur_per_mwh",
        tie_breakers=["total_pumping_electric_energy_mwh_per_a"],
    )
    if decision.preferred_alternative_id is not None:
        assert len(decision.ranked_alternative_groups[0]) == 1
        assert decision.synthetic_cost_sensitivity_caveat is not None
    else:
        assert len(decision.ranked_alternative_groups[0]) > 1
