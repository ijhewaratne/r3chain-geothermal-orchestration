"""Full test matrix for economics/joint_costing.py -- Phase 4 of
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md:
ECON-001..015, so far as this reuse-only module implements them."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from r3chain_geothermal.adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.data_contracts.joint_study import (
    AssumptionStatus,
    ConnectionDesignOption,
    GeologicalMetadata,
    GeothermalResourceScenario,
    SiteEconomicInputs,
    TemporalBasis,
)
from r3chain_geothermal.data_contracts.schema import DatasetClassification
from r3chain_geothermal.economics.assumptions import EconomicAssumptions
from r3chain_geothermal.economics.costing import compute_baseline_economics
from r3chain_geothermal.economics.joint_costing import compute_alternative_economics, load_base_assumptions, _scenario_doublet_capex_eur
from r3chain_geothermal.network import BlueprintCandidate, GateTolerances, build_default_blueprint, evaluate_candidate, run_baseline_evaluation
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_PACKAGE_PATH = _ROOT / "config" / "joint_study_synthetic_v2.json"
_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


# ── _scenario_doublet_capex_eur (ECON-002/014) ───────────────────────────────
def test_scenario_capex_reads_the_aggregate_value_when_present():
    inputs = SiteEconomicInputs(doublet_capex_eur=9_200_000.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t")
    assert _scenario_doublet_capex_eur(inputs) == 9_200_000.0


def test_scenario_capex_sums_the_component_breakdown_when_aggregate_is_absent():
    inputs = SiteEconomicInputs(
        drilling_producer_well_capex_eur=1_000_000.0, drilling_injector_well_capex_eur=1_000_000.0,
        well_completion_capex_eur=500_000.0, surface_plant_capex_eur=2_000_000.0, contingency_capex_eur=300_000.0,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
    )
    assert _scenario_doublet_capex_eur(inputs) == pytest.approx(4_800_000.0)


# ── load_base_assumptions (S7.16) ────────────────────────────────────────────
def test_load_base_assumptions_from_the_committed_fixture():
    from r3chain_geothermal.data_contracts.joint_study import JointStudyPackage
    package = JointStudyPackage.model_validate_json(_PACKAGE_PATH.read_text())
    assumptions = load_base_assumptions(package.economics, _ROOT)
    assert assumptions.doublet_capex_eur == 8_000_000.0  # config/demo_assumptions.json's own golden value


def test_a_path_escaping_the_package_root_is_rejected_at_contract_construction():
    """DATA-022 is already enforced one layer earlier than
    load_base_assumptions() itself -- JointEconomicPolicy's own Phase-1
    validator (_is_safe_package_relative_path) rejects an unsafe path at
    CONSTRUCTION time, so no already-validated JointEconomicPolicy object
    can ever reach load_base_assumptions() with a traversal path."""
    from r3chain_geothermal.data_contracts.joint_study import JointEconomicPolicy
    with pytest.raises(ValueError):
        JointEconomicPolicy(
            economic_policy_id="e", economic_schema_version="1.0.0",
            base_assumptions_package_relative_path="../../etc/passwd", base_assumptions_sha256="0" * 64,
            annual_operating_hours=8000.0, discount_rate_fraction=0.04, analysis_period_years=25,
            electricity_price_eur_per_mwh=1.0, auxiliary_heat_price_eur_per_mwh=1.0, price_year=2026,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        )


def test_load_base_assumptions_own_defensive_check_still_rejects_an_unsafe_path():
    """Defense in depth: load_base_assumptions() carries its OWN escape
    check too, independent of JointEconomicPolicy's validator, exercised
    directly by bypassing normal construction (model_construct skips
    validation) -- proving this function does not blindly trust its
    caller."""
    from r3chain_geothermal.data_contracts.joint_study import JointEconomicPolicy
    policy = JointEconomicPolicy.model_construct(
        economic_policy_id="e", economic_schema_version="1.0.0",
        base_assumptions_package_relative_path="../../etc/passwd", base_assumptions_sha256="0" * 64,
        annual_operating_hours=8000.0, discount_rate_fraction=0.04, analysis_period_years=25,
        electricity_price_eur_per_mwh=1.0, auxiliary_heat_price_eur_per_mwh=1.0, price_year=2026,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t", currency="EUR",
    )
    with pytest.raises(ValueError):
        load_base_assumptions(policy, _ROOT)


# ── compute_alternative_economics (ECON-001/002/006/007) ────────────────────
def _golden():
    raw = json.loads((_ROOT / "fixtures" / "pydoublet" / "repaired_result.json").read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit="0d649c3e6930d342dac03654d57776e134c2d0b9", source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    return parse_pydoublet_result(raw, source_provenance=provenance)


def _feasible_candidate_result(connection_length_m: float, diameter_mm: float):
    config = json.loads(_CONFIG_PATH.read_text())
    bp = build_default_blueprint(
        consumer_demands_kw=_DEMANDS, trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0, created_at=datetime.now(timezone.utc),
    )
    tolerances = GateTolerances.from_config_dict(config)
    baseline = run_baseline_evaluation(bp, tolerances=tolerances)
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    coupling_result = evaluate_heat_exchanger_coupling(_golden(), assumptions=coupling_assumptions)
    from r3chain_geothermal.network import GeothermalInjectionPolicy
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    candidate = BlueprintCandidate(
        id="test", label="test", supply_junction="trunk_1", return_junction="ret_trunk_1",
        surface_connection_length_m=connection_length_m,
    )
    result = evaluate_candidate(
        coupling_result, bp, candidate, baseline, injection_policy=injection_policy, tolerances=tolerances,
        connection_pipe_inner_diameter_mm=diameter_mm,
    )
    return result, bp, baseline, tolerances


def _scenario(doublet_capex_eur: float) -> GeothermalResourceScenario:
    return GeothermalResourceScenario(
        scenario_id="s", site_id="site_a", scenario_label="s", classification=DatasetClassification.SYNTHETIC,
        resource_input_id="input_a", temporal_basis=TemporalBasis.LIFETIME_AVERAGE_STEADY,
        geological_metadata=GeologicalMetadata(),
        economic_inputs=SiteEconomicInputs(
            doublet_capex_eur=doublet_capex_eur, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        ),
    )


def _design(capex_eur_per_m: float) -> ConnectionDesignOption:
    return ConnectionDesignOption(
        design_option_id="d", connection_pipe_inner_diameter_mm=200.0, pipe_roughness_mm=0.1,
        capex_eur_per_paired_trench_m=capex_eur_per_m, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="t",
    )


def test_alternative_economics_uses_the_scenarios_own_capex_not_the_base_config_value():
    candidate_result, bp, baseline, tolerances = _feasible_candidate_result(connection_length_m=50.0, diameter_mm=200.0)
    config = json.loads(_CONFIG_PATH.read_text())
    base_assumptions = EconomicAssumptions.from_config_dict(config)
    baseline_economics = compute_baseline_economics(baseline, assumptions=base_assumptions)
    assert base_assumptions.doublet_capex_eur == 8_000_000.0  # the canonical/golden base value

    scenario = _scenario(doublet_capex_eur=9_200_000.0)  # deliberately DIFFERENT from the base config
    design = _design(capex_eur_per_m=1000.0)
    econ = compute_alternative_economics(candidate_result, scenario, design, baseline_economics, base_assumptions)
    assert econ.capex_doublet_eur == 9_200_000.0
    assert econ.capex_doublet_eur != base_assumptions.doublet_capex_eur


def test_alternative_economics_uses_the_designs_own_connection_capex_rate():
    candidate_result, bp, baseline, tolerances = _feasible_candidate_result(connection_length_m=90.0, diameter_mm=200.0)
    config = json.loads(_CONFIG_PATH.read_text())
    base_assumptions = EconomicAssumptions.from_config_dict(config)
    baseline_economics = compute_baseline_economics(baseline, assumptions=base_assumptions)

    scenario = _scenario(doublet_capex_eur=8_000_000.0)
    design = _design(capex_eur_per_m=2500.0)  # deliberately different from the base config's own rate
    econ = compute_alternative_economics(candidate_result, scenario, design, baseline_economics, base_assumptions)
    assert econ.capex_connection_pipes_eur == pytest.approx(90.0 * 2500.0)


def test_alternative_economics_consumes_the_same_route_length_pandapipes_used():
    """ECON-007: the connection-pipe CAPEX length is read straight from
    candidate_result.candidate.surface_connection_length_m -- the exact
    value workflow.joint_evaluation already passed into evaluate_candidate()
    as the route's own paired_trench_length_m, never re-derived."""
    candidate_result, bp, baseline, tolerances = _feasible_candidate_result(connection_length_m=123.456, diameter_mm=200.0)
    assert candidate_result.candidate.surface_connection_length_m == pytest.approx(123.456)
    config = json.loads(_CONFIG_PATH.read_text())
    base_assumptions = EconomicAssumptions.from_config_dict(config)
    baseline_economics = compute_baseline_economics(baseline, assumptions=base_assumptions)
    scenario = _scenario(doublet_capex_eur=8_000_000.0)
    design = _design(capex_eur_per_m=1000.0)
    econ = compute_alternative_economics(candidate_result, scenario, design, baseline_economics, base_assumptions)
    assert econ.capex_connection_pipes_eur == pytest.approx(123.456 * 1000.0)
