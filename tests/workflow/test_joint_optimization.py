"""Full test matrix for workflow/joint_optimization.py and
workflow/joint_optimization_export.py -- OPT-001..007 and AC-10."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from r3chain_geothermal.adapter import CouplingAssumptions
from r3chain_geothermal.contracts import PyDoubletCouplingResult, SourceProvenance
from r3chain_geothermal.economics import EconomicAssumptions
from r3chain_geothermal.network import (
    BaselineNetworkResult,
    GateTolerances,
    GeothermalInjectionPolicy,
    build_default_blueprint,
    generate_candidates,
    run_baseline_evaluation,
)
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result
from r3chain_geothermal.workflow.joint_optimization import (
    AlternativeIdentity,
    JointEvaluationStage,
    build_synthetic_geothermal_scenarios,
    pareto_shortlist,
    run_joint_optimization_demo,
)
from r3chain_geothermal.workflow.joint_optimization_export import export_joint_optimization_bundle

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _golden_coupling_input() -> PyDoubletCouplingResult:
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert isinstance(result, PyDoubletCouplingResult)
    return result


def _blueprint():
    return build_default_blueprint(
        consumer_demands_kw=_DEMANDS, trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0, created_at=datetime.now(timezone.utc),
    )


def _run_demo():
    config = _config()
    bp = _blueprint()
    tolerances = GateTolerances.from_config_dict(config)
    baseline = run_baseline_evaluation(bp, tolerances=tolerances)
    assert isinstance(baseline, BaselineNetworkResult)
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    economic_assumptions = EconomicAssumptions.from_config_dict(config)
    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    screened_by_id = {s.candidate_id: s for s in screened}
    result = run_joint_optimization_demo(
        _golden_coupling_input(), bp, baseline, screened_by_id,
        coupling_assumptions=coupling_assumptions, injection_policy=injection_policy,
        tolerances=tolerances, economic_assumptions=economic_assumptions,
    )
    return result, screened


# ── OPT-001: decision entity ─────────────────────────────────────────────────
def test_alternative_identity_has_six_distinct_fields():
    identity = AlternativeIdentity(
        geothermal_scenario_id="s", surface_site_id="site", connection_candidate_id="c",
        route_id="direct", design_option_id="standard", operating_policy_id="standard",
    )
    assert identity.alternative_id == "s|site|c|direct|standard|standard"


# ── Synthetic scenarios ──────────────────────────────────────────────────────
def test_build_synthetic_geothermal_scenarios_returns_at_least_three():
    scenarios = build_synthetic_geothermal_scenarios(_golden_coupling_input())
    assert len(scenarios) >= 3
    assert all(s.synthetic is True for s in scenarios)
    scenario_ids = {s.scenario_id for s in scenarios}
    site_ids = {s.surface_site_id for s in scenarios}
    assert len(scenario_ids) == len(scenarios)  # all distinct
    assert len(site_ids) == len(scenarios)  # distinct surface sites too


def test_scenario_b_is_hx_infeasible_by_construction():
    scenarios = {s.scenario_id: s for s in build_synthetic_geothermal_scenarios(_golden_coupling_input())}
    scenario_b = scenarios["scenario_B"]
    assumptions = CouplingAssumptions.from_config_dict(_config())
    from r3chain_geothermal.adapter import evaluate_heat_exchanger_coupling
    from r3chain_geothermal.adapter.heat_exchanger import HeatExchangerCouplingFailure
    from r3chain_geothermal.adapter.errors import AdapterFailureCode
    boundary = evaluate_heat_exchanger_coupling(scenario_b.coupling_input, assumptions=assumptions)
    assert isinstance(boundary, HeatExchangerCouplingFailure)
    assert boundary.failure_code == AdapterFailureCode.HX_SUPPLY_TEMPERATURE_INFEASIBLE


def test_scenario_variants_satisfy_their_own_energy_consistency_by_construction():
    """Every synthetic variant's raw_geothermal_thermal_power_kw was
    recomputed via the same formula T1.5B's own consistency check uses --
    none of them should ever fail with UNIT_OR_SIGN_ERROR."""
    from r3chain_geothermal.adapter import evaluate_heat_exchanger_coupling
    from r3chain_geothermal.adapter.errors import AdapterFailureCode
    from r3chain_geothermal.adapter.heat_exchanger import HeatExchangerCouplingFailure
    assumptions = CouplingAssumptions.from_config_dict(_config())
    for scenario in build_synthetic_geothermal_scenarios(_golden_coupling_input()):
        boundary = evaluate_heat_exchanger_coupling(scenario.coupling_input, assumptions=assumptions)
        if isinstance(boundary, HeatExchangerCouplingFailure):
            assert boundary.failure_code != AdapterFailureCode.UNIT_OR_SIGN_ERROR, scenario.scenario_id


# ── OPT-005/AC-10: the synthetic demonstration ──────────────────────────────
def test_demonstration_satisfies_every_opt005_minimum():
    result, screened = _run_demo()

    assert len(result.scenarios) >= 3
    referenced_candidate_ids = {a.identity.connection_candidate_id for a in result.alternatives}
    assert len(referenced_candidate_ids) >= 4

    route_and_design_axes = {(a.identity.route_id, a.identity.design_option_id) for a in result.alternatives}
    assert len({rid for rid, _ in route_and_design_axes}) >= 2  # at least two distinct route/design options

    site_screening_failures = [
        a for a in result.alternatives
        if not a.feasible and a.stage_reached == JointEvaluationStage.CALCULATE_HX_COUPLING_BOUNDARY
    ]
    assert len(site_screening_failures) >= 1

    hydraulic_thermal_failures = [
        a for a in result.alternatives
        if not a.feasible and a.stage_reached == JointEvaluationStage.APPLY_TECHNICAL_GATES
    ]
    assert len(hydraulic_thermal_failures) >= 1

    feasible = [a for a in result.alternatives if a.feasible]
    assert len(feasible) >= 2

    assert result.synthetic is True


def test_ac10_technical_and_economic_results_are_kept_separate():
    """An infeasible alternative must never carry economics -- feasibility
    is evaluated strictly before any economic figure exists (AC-10:
    "technical failures remain separate from economic results")."""
    result, _ = _run_demo()
    for alt in result.alternatives:
        if not alt.feasible:
            assert alt.economics is None
        else:
            assert alt.economics is not None


def test_ac10_pareto_shortlist_is_returned_not_an_invented_ranking():
    result, _ = _run_demo()
    feasible_ids = {a.identity.alternative_id for a in result.alternatives if a.feasible}
    assert set(result.pareto_shortlist_alternative_ids).issubset(feasible_ids)
    assert len(result.pareto_shortlist_alternative_ids) >= 1
    assert len(result.objectives_considered) >= 1


def test_demonstration_is_deterministic():
    result_1, _ = _run_demo()
    result_2, _ = _run_demo()
    ids_1 = [(a.identity.alternative_id, a.feasible, a.failure_code) for a in result_1.alternatives]
    ids_2 = [(a.identity.alternative_id, a.feasible, a.failure_code) for a in result_2.alternatives]
    assert ids_1 == ids_2
    assert result_1.pareto_shortlist_alternative_ids == result_2.pareto_shortlist_alternative_ids


# ── Pareto shortlist logic, isolated ─────────────────────────────────────────
def test_pareto_shortlist_empty_for_no_feasible_alternatives():
    ids, objectives = pareto_shortlist([])
    assert ids == []
    assert objectives == []


def test_pareto_dominance_excludes_a_strictly_worse_alternative():
    from r3chain_geothermal.workflow.joint_optimization import AlternativeEvaluation
    from r3chain_geothermal.economics.costing import CandidateEconomicResult
    from r3chain_geothermal.network import BlueprintCandidate

    result, _ = _run_demo()
    feasible = [a for a in result.alternatives if a.feasible]
    assert len(feasible) >= 2
    # Clone the first feasible alternative but make every objective
    # strictly worse -- it must never appear in the shortlist.
    base = feasible[0]
    worse_economics = base.economics.model_copy(update={
        "annualised_cost_total_eur_per_a": base.economics.annualised_cost_total_eur_per_a * 10,
        "indicative_lcoh_eur_per_kwh": base.economics.indicative_lcoh_eur_per_kwh * 10,
        "auxiliary_heat_kw": base.economics.auxiliary_heat_kw + 1000.0,
        "opex_electricity_dh_pumping_eur_per_a": base.economics.opex_electricity_dh_pumping_eur_per_a * 10,
    })
    worse_candidate = base.candidate_result.model_copy(update={
        "candidate": base.candidate_result.candidate.model_copy(update={
            "id": "worse-clone", "surface_connection_length_m": base.candidate_result.candidate.surface_connection_length_m * 10,
        }),
    })
    worse_identity = base.identity.model_copy(update={"connection_candidate_id": "worse-clone"})
    worse_alt = base.model_copy(update={"identity": worse_identity, "economics": worse_economics, "candidate_result": worse_candidate})

    ids, _ = pareto_shortlist(feasible + [worse_alt])
    assert worse_alt.identity.alternative_id not in ids


# ── OPT-007 export ───────────────────────────────────────────────────────────
def test_export_writes_every_expected_file(tmp_path):
    result, screened = _run_demo()
    written = export_joint_optimization_bundle(result, screened, tmp_path)
    expected = {
        "generated_candidates.json", "screened_alternatives.json", "alternative_comparison.csv",
        "pareto_or_ranking.json", "recommendation.md",
    }
    assert set(written.keys()) == expected
    for path in written.values():
        assert path.exists()
        assert path.stat().st_size > 0


def test_exported_recommendation_states_the_result_is_synthetic():
    result, screened = _run_demo()
    from r3chain_geothermal.workflow.joint_optimization_export import render_joint_recommendation_markdown
    text = render_joint_recommendation_markdown(result).decode("utf-8")
    assert "SYNTHETIC" in text
    assert "real" in text.lower()


def test_exported_csv_lists_every_alternative_with_pareto_membership(tmp_path):
    import csv
    result, screened = _run_demo()
    written = export_joint_optimization_bundle(result, screened, tmp_path)
    with open(written["alternative_comparison.csv"], newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(result.alternatives)
    pareto_rows = [r for r in rows if r["in_pareto_shortlist"] == "True"]
    assert len(pareto_rows) == len(result.pareto_shortlist_alternative_ids)


def test_export_is_deterministic(tmp_path):
    result, screened = _run_demo()
    written_1 = export_joint_optimization_bundle(result, screened, tmp_path / "run1")
    written_2 = export_joint_optimization_bundle(result, screened, tmp_path / "run2")
    for filename in written_1:
        assert written_1[filename].read_bytes() == written_2[filename].read_bytes()
