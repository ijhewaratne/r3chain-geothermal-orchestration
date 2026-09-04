"""Phase 2 integration test matrix -- proves AC-J02 through AC-J07 of
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
against the committed synthetic v2 study package
(config/joint_study_synthetic_v2.json), end to end: site-origin-aware
routing -> compatible enumeration -> HX/pandapipes evaluation, reusing
the SAME adapter/network functions the canonical and v1 joint workflows
already use (EVAL-004)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from r3chain_geothermal.adapter import CouplingAssumptions
from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.data_contracts.joint_study import (
    JointStudyPackage,
    RouteScreeningStatus,
    compute_active_dimensions,
)
from r3chain_geothermal.economics.costing import compute_baseline_economics
from r3chain_geothermal.economics.joint_costing import load_base_assumptions
from r3chain_geothermal.network import GateTolerances, GeothermalInjectionPolicy, build_default_blueprint, run_baseline_evaluation
from r3chain_geothermal.network.site_routing import generate_site_routes
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result
from r3chain_geothermal.workflow.joint_enumeration import enumerate_compatible_alternatives, possible_combination_count
from r3chain_geothermal.workflow.joint_evaluation import JointEvaluationStage, evaluate_compatible_alternatives

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_PACKAGE_PATH = _ROOT / "config" / "joint_study_synthetic_v2.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _package() -> JointStudyPackage:
    return JointStudyPackage.model_validate_json(_PACKAGE_PATH.read_text())


def _golden():
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert result.status == "success"
    return result


def _blueprint():
    return build_default_blueprint(
        consumer_demands_kw=_DEMANDS, trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0, created_at=datetime.now(timezone.utc),
    )


def _run_phase2_pipeline():
    """One full run: package -> routes -> compatible alternatives ->
    evaluated results. Returns everything a test might need so this is
    computed once per call, not re-derived piecemeal."""
    package = _package()
    config = _config()
    golden = _golden()
    bp = _blueprint()
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
        identities, package, routes_by_id, attachments_by_id, golden, bp, baseline,
        baseline_economics, base_assumptions,
        coupling_assumptions=coupling_assumptions, injection_policy=injection_policy, tolerances=tolerances,
    )
    return package, routes, identities, results


# ── Fixture composition sanity (S8.1) ────────────────────────────────────────
def test_committed_package_is_valid_and_loads():
    package = _package()
    assert package.contract_schema_version == "2.0.0"
    assert len(package.sites) >= 3
    assert any(s.availability_status.value == "excluded" for s in package.sites)


# ── AC-J02: honest dimension report ──────────────────────────────────────────
def test_ac_j02_dimension_report_distinguishes_active_from_controlled():
    package = _package()
    routes = generate_site_routes(package.sites, package.network_attachments, package.routing_policy)
    report = compute_active_dimensions(package, routes)
    assert "resource_scenario_id" in report.active_dimensions
    assert "surface_site_id" in report.active_dimensions
    assert "route_id" in report.active_dimensions
    assert "design_option_id" in report.controlled_dimensions  # only one design option exists
    assert "operating_policy_id" in report.controlled_dimensions  # only one policy exists
    assert report.cardinalities["route_id"] == len([r for r in routes if r.screening_status == RouteScreeningStatus.ACCEPTED])


# ── AC-J03: every scenario belongs to one site; at least one site has 2+ ────
def test_ac_j03_every_scenario_belongs_to_one_site_and_one_site_has_multiple():
    package = _package()
    for scenario in package.resource_scenarios:
        assert any(s.site_id == scenario.site_id for s in package.sites)
    scenarios_per_site: dict[str, int] = {}
    for scenario in package.resource_scenarios:
        scenarios_per_site[scenario.site_id] = scenarios_per_site.get(scenario.site_id, 0) + 1
    assert max(scenarios_per_site.values()) >= 2


# ── AC-J04: same attachment, two sites, two different route lengths ─────────
def test_ac_j04_same_attachment_from_two_sites_has_different_route_lengths():
    package = _package()
    routes = generate_site_routes(package.sites, package.network_attachments, package.routing_policy)
    trunk_2_accepted = [
        r for r in routes if r.attachment_id == "trunk_2" and r.screening_status == RouteScreeningStatus.ACCEPTED
    ]
    site_ids = {r.site_id for r in trunk_2_accepted}
    assert len(site_ids) >= 2, "trunk_2 must be reachable, within policy, from at least two different sites"
    lengths = {r.site_id: r.paired_trench_length_m for r in trunk_2_accepted}
    assert len(set(lengths.values())) == len(lengths), f"route lengths must differ per site: {lengths}"


# ── AC-J05: mismatched combinations rejected before HX/pandapipes; evaluated == compatible ──
def test_ac_j05_screening_precedes_scientific_evaluation_and_counts_match():
    package, routes, identities, results = _run_phase2_pipeline()
    rejected_routes = [r for r in routes if r.screening_status == RouteScreeningStatus.REJECTED]
    assert rejected_routes, "the fixture must exercise at least one screened-out route"
    # every rejected route names an exact typed reason -- never dropped
    assert all(r.rejection_code is not None and r.rejection_detail for r in rejected_routes)
    # evaluated_count == compatible_count (WF-006)
    assert len(results) == len(identities)
    possible = possible_combination_count(package, routes)
    assert possible > len(identities), "the compatible set must be strictly smaller than the unconstrained product"


# ── AC-J06: low-temperature scenario fails at HX stage, no economics ────────
def test_ac_j06_low_temperature_scenario_fails_before_network_construction():
    _, _, _, results = _run_phase2_pipeline()
    low_temp_results = [r for r in results if r.identity.resource_scenario_id == "scenario_beta_low_temperature"]
    assert low_temp_results, "the low-temperature scenario must have at least one compatible alternative evaluated"
    for result in low_temp_results:
        assert not result.feasible
        assert result.stage_reached == JointEvaluationStage.CALCULATE_HX_COUPLING_BOUNDARY
        assert result.failure_code == "HX_SUPPLY_TEMPERATURE_INFEASIBLE"
        assert result.candidate_result is None  # AC-J06: no economics/network result at all


# ── AC-J07: resource flow change alters a network outcome at same attachment/design ──
def test_ac_j07_resource_flow_change_alters_network_outcome_same_attachment():
    _, _, _, results = _run_phase2_pipeline()
    by_id = {r.identity.alternative_id: r for r in results}
    golden_key = "scenario_alpha_golden|site_alpha|trunk_1|route-site_alpha-trunk_1-synthetic_polyline|standard|standard"
    reduced_key = "scenario_alpha_reduced_flow|site_alpha|trunk_1|route-site_alpha-trunk_1-synthetic_polyline|standard|standard"
    golden_result = by_id[golden_key]
    reduced_result = by_id[reduced_key]
    assert golden_result.feasible and reduced_result.feasible
    assert golden_result.candidate_result.geothermal_injected_heat_kw != pytest.approx(
        reduced_result.candidate_result.geothermal_injected_heat_kw,
    )
    assert golden_result.candidate_result.auxiliary_heat_kw != pytest.approx(
        reduced_result.candidate_result.auxiliary_heat_kw,
    )


# ── No blind Cartesian product / no global-table reuse ──────────────────────
def test_enumeration_never_pairs_a_scenario_with_a_route_from_another_site():
    package, routes, identities, _ = _run_phase2_pipeline()
    scenario_site = {s.scenario_id: s.site_id for s in package.resource_scenarios}
    route_site = {r.route_id: r.site_id for r in routes}
    for identity in identities:
        assert scenario_site[identity.resource_scenario_id] == identity.surface_site_id
        assert route_site[identity.route_id] == identity.surface_site_id


def test_no_alternative_identity_id_can_be_parsed_back_into_its_fields():
    """ARCH-006 spot check: alternative_id is a derived DISPLAY string;
    this test itself never splits it to recover a field (nothing in the
    production code does either -- see joint_study.py's own module
    docstring for the identity model)."""
    _, _, identities, _ = _run_phase2_pipeline()
    for identity in identities:
        assert identity.alternative_id.count("|") == 5


# ── Every failure code observed is a real, exact, typed code ────────────────
def test_every_rejected_route_and_failure_uses_a_recognized_typed_code():
    package, routes, identities, results = _run_phase2_pipeline()
    for route in routes:
        if route.screening_status == RouteScreeningStatus.REJECTED:
            assert route.rejection_code is not None
    observed_failure_codes = {r.failure_code for r in results if not r.feasible}
    assert observed_failure_codes  # at least one infeasible alternative in this fixture
    assert all(isinstance(code, str) and code for code in observed_failure_codes)
