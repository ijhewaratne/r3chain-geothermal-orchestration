"""Full test matrix for economics/costing.py -- CandidateEconomicResult /
BaselineEconomicResult / compute_candidate_economics() / compute_baseline_economics()."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from r3chain_geothermal.adapter.heat_exchanger import HeatExchangerCouplingResult
from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.economics import (
    BASELINE_SCOPE_CAVEAT,
    BaselineEconomicResult,
    CandidateEconomicResult,
    EconomicAssumptions,
    compute_baseline_economics,
    compute_candidate_economics,
)
from r3chain_geothermal.network import (
    BaselineNetworkResult,
    BlueprintCandidate,
    CandidateEvaluationResult,
    GateTolerances,
    GeothermalInjectionPolicy,
    build_default_blueprint,
    evaluate_candidate,
    run_baseline_evaluation,
)
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_COSTING_SRC_PATH = _ROOT / "src" / "r3chain_geothermal" / "economics" / "costing.py"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}
_CANDIDATES = {
    "C1": ("trunk_1", "ret_trunk_1", 50.0), "C2": ("trunk_2", "ret_trunk_2", 70.0),
    "C3": ("trunk_3", "ret_trunk_3", 90.0), "C4": ("trunk_4", "ret_trunk_4", 120.0),
}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _tolerances() -> GateTolerances:
    return GateTolerances.from_config_dict(_config())


def _policy(**overrides) -> GeothermalInjectionPolicy:
    base = dict(
        curtailment_allowed=True, auxiliary_policy="cost_shortfall",
        minimum_auxiliary_circulation_fraction=0.01, heat_delivery_tolerance_fraction=0.01,
    )
    base.update(overrides)
    return GeothermalInjectionPolicy(**base)


def _econ_assumptions(**overrides) -> EconomicAssumptions:
    assumptions = EconomicAssumptions.from_config_dict(_config())
    return assumptions.model_copy(update=overrides) if overrides else assumptions


def _blueprint(**overrides):
    kwargs = dict(
        consumer_demands_kw=_DEMANDS,
        trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
        created_at=datetime.now(timezone.utc),
    )
    kwargs.update(overrides)
    return build_default_blueprint(**kwargs)


def _golden_coupling_result(**assumption_overrides) -> HeatExchangerCouplingResult:
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired", calculation_mode="deterministic",
    )
    coupling_input = parse_pydoublet_result(raw, source_provenance=provenance)
    assumptions = CouplingAssumptions.from_config_dict(_config())
    if assumption_overrides:
        assumptions = assumptions.model_copy(update=assumption_overrides)
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingResult)
    return result


def _baseline(blueprint=None) -> BaselineNetworkResult:
    bp = blueprint if blueprint is not None else _blueprint()
    result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)
    return result


def _candidate(candidate_id: str) -> BlueprintCandidate:
    supply, ret, length = _CANDIDATES[candidate_id]
    return BlueprintCandidate(id=candidate_id, label=candidate_id, supply_junction=supply, return_junction=ret, surface_connection_length_m=length)


def _evaluate(candidate_id: str, bp=None, coupling_result=None, baseline=None, **policy_overrides) -> CandidateEvaluationResult:
    bp = bp if bp is not None else _blueprint()
    coupling_result = coupling_result if coupling_result is not None else _golden_coupling_result()
    baseline = baseline if baseline is not None else _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate(candidate_id), baseline,
        injection_policy=_policy(**policy_overrides), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult), result
    return result


def _strict_json_loads(text: str):
    def _reject(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")
    return json.loads(text, parse_constant=_reject)


# ── Baseline economics ───────────────────────────────────────────────────────
def test_baseline_economics_has_no_capex_or_doublet_pump_term():
    baseline = _baseline()
    result = compute_baseline_economics(baseline, assumptions=_econ_assumptions())
    assert isinstance(result, BaselineEconomicResult)
    assert result.annualised_cost_total_eur_per_a == result.opex_electricity_dh_pumping_eur_per_a + result.opex_auxiliary_heat_eur_per_a


def test_baseline_scope_caveat_always_present_and_matches_constant():
    """The baseline's LCOH must never be presented as a validated
    full-system baseline LCOH -- scope_caveat is a structurally-guaranteed
    field (mirrors ranking.SHARED_CAPEX_STATEMENT's own established
    pattern), always present with the exact same text."""
    result = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    assert result.scope_caveat == BASELINE_SCOPE_CAVEAT
    assert "prototype-boundary" in result.scope_caveat.lower()
    assert "not a validated full-system baseline lcoh" in result.scope_caveat.lower()
    assert "capex" in result.scope_caveat.lower() and "fixed o&m" in result.scope_caveat.lower()


def test_baseline_economics_hand_computed():
    baseline = _baseline()
    assumptions = _econ_assumptions()
    result = compute_baseline_economics(baseline, assumptions=assumptions)

    expected_electrical_kw = baseline.circulation_pump.hydraulic_pumping_power_kw / assumptions.dh_pump_efficiency
    expected_dh_opex = expected_electrical_kw * assumptions.annual_full_load_hours * assumptions.electricity_price_eur_per_kwh
    expected_aux_opex = baseline.total_heat_delivered_kw * assumptions.annual_full_load_hours * assumptions.auxiliary_heat_price_eur_per_kwh

    assert math.isclose(result.opex_electricity_dh_pumping_eur_per_a, expected_dh_opex, rel_tol=1e-9)
    assert math.isclose(result.opex_auxiliary_heat_eur_per_a, expected_aux_opex, rel_tol=1e-9)
    assert math.isclose(
        result.indicative_lcoh_eur_per_kwh,
        (expected_dh_opex + expected_aux_opex) / (baseline.total_heat_delivered_kw * assumptions.annual_full_load_hours),
        rel_tol=1e-9,
    )


# ── Worked case: all four candidates ────────────────────────────────────────
def test_worked_case_doublet_and_heat_exchanger_capex_identical_across_candidates():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    baseline_econ = compute_baseline_economics(baseline, assumptions=_econ_assumptions())

    capex_doublet_values = set()
    capex_hx_values = set()
    annuity_doublet_values = set()
    annuity_hx_values = set()
    for candidate_id in _CANDIDATES:
        candidate_result = _evaluate(candidate_id, bp, coupling_result, baseline)
        econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
        capex_doublet_values.add(econ.capex_doublet_eur)
        capex_hx_values.add(econ.capex_heat_exchanger_eur)
        annuity_doublet_values.add(econ.annuity_doublet_eur_per_a)
        annuity_hx_values.add(econ.annuity_heat_exchanger_eur_per_a)

    assert len(capex_doublet_values) == 1
    assert len(capex_hx_values) == 1
    assert len(annuity_doublet_values) == 1
    assert len(annuity_hx_values) == 1


def test_worked_case_connection_pipe_capex_strictly_increasing_with_length():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    baseline_econ = compute_baseline_economics(baseline, assumptions=_econ_assumptions())

    capex = {}
    for candidate_id in ("C1", "C2", "C3", "C4"):
        candidate_result = _evaluate(candidate_id, bp, coupling_result, baseline)
        econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
        capex[candidate_id] = econ.capex_connection_pipes_eur

    assert capex["C1"] < capex["C2"] < capex["C3"] < capex["C4"]


def test_worked_case_connection_pipe_capex_is_paired_trench_not_doubled():
    """Resolved cost basis (§2): connection_pipe_per_m x length, ONCE --
    not doubled for the two physical connection pipes."""
    bp = _blueprint()
    candidate_result = _evaluate("C1", bp)
    baseline_econ = compute_baseline_economics(_baseline(bp), assumptions=_econ_assumptions())
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
    assumptions = _econ_assumptions()
    expected_once = assumptions.connection_pipe_capex_eur_per_m * 50.0  # C1's surface_connection_length_m
    assert math.isclose(econ.capex_connection_pipes_eur, expected_once, rel_tol=1e-9)
    assert not math.isclose(econ.capex_connection_pipes_eur, expected_once * 2, rel_tol=1e-9)


def test_worked_case_hand_computed_c1():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    assumptions = _econ_assumptions()
    baseline_econ = compute_baseline_economics(baseline, assumptions=assumptions)
    candidate_result = _evaluate("C1", bp, coupling_result, baseline)
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=assumptions)

    from r3chain_geothermal.economics.annuity import annuity_factor
    a_doublet = annuity_factor(assumptions.interest_rate_real, assumptions.doublet_lifetime_years)
    a_hx = annuity_factor(assumptions.interest_rate_real, assumptions.heat_exchanger_lifetime_years)
    a_pipes = annuity_factor(assumptions.interest_rate_real, assumptions.connection_pipes_lifetime_years)

    expected_capex_pipes = assumptions.connection_pipe_capex_eur_per_m * 50.0
    expected_annuity_capital = (
        assumptions.doublet_capex_eur * a_doublet
        + assumptions.heat_exchanger_capex_eur * a_hx
        + expected_capex_pipes * a_pipes
    )
    expected_total_capex = assumptions.doublet_capex_eur + assumptions.heat_exchanger_capex_eur + expected_capex_pipes
    expected_opex_fixed = assumptions.fixed_om_fraction_of_capex_per_a * expected_total_capex

    expected_doublet_pump_kw = coupling_result.coupling_input.doublet_pump_electric_power_kw.value
    expected_opex_doublet_pump = expected_doublet_pump_kw * assumptions.annual_full_load_hours * assumptions.electricity_price_eur_per_kwh

    expected_dh_hydraulic_kw = candidate_result.circulation_pump.hydraulic_pumping_power_kw + candidate_result.connection_pumping_power_kw
    expected_dh_electrical_kw = expected_dh_hydraulic_kw / assumptions.dh_pump_efficiency
    expected_opex_dh_pumping = expected_dh_electrical_kw * assumptions.annual_full_load_hours * assumptions.electricity_price_eur_per_kwh

    expected_opex_aux = candidate_result.auxiliary_heat_kw * assumptions.annual_full_load_hours * assumptions.auxiliary_heat_price_eur_per_kwh

    expected_total = expected_annuity_capital + expected_opex_fixed + expected_opex_doublet_pump + expected_opex_dh_pumping + expected_opex_aux
    expected_annual_kwh = candidate_result.total_heat_delivered_kw * assumptions.annual_full_load_hours

    assert math.isclose(econ.capex_connection_pipes_eur, expected_capex_pipes, rel_tol=1e-9)
    assert math.isclose(econ.annuity_capital_eur_per_a, expected_annuity_capital, rel_tol=1e-9)
    assert math.isclose(econ.opex_fixed_eur_per_a, expected_opex_fixed, rel_tol=1e-9)
    assert math.isclose(econ.opex_electricity_doublet_pump_eur_per_a, expected_opex_doublet_pump, rel_tol=1e-9)
    assert math.isclose(econ.opex_electricity_dh_pumping_eur_per_a, expected_opex_dh_pumping, rel_tol=1e-9)
    assert math.isclose(econ.opex_auxiliary_heat_eur_per_a, expected_opex_aux, rel_tol=1e-9)
    assert math.isclose(econ.annualised_cost_total_eur_per_a, expected_total, rel_tol=1e-9)
    assert math.isclose(econ.annual_total_heat_delivered_kwh, expected_annual_kwh, rel_tol=1e-9)
    assert math.isclose(econ.indicative_lcoh_eur_per_kwh, expected_total / expected_annual_kwh, rel_tol=1e-9)


def test_worked_case_annualised_cost_ordering_matches_connection_length_ordering():
    """Only connection length differs C1-C4 in the worked case (identical
    doublet/HX CAPEX, near-identical technical KPIs) -- total annualised
    cost should follow the same strict ordering as connection-pipe CAPEX."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    baseline_econ = compute_baseline_economics(baseline, assumptions=_econ_assumptions())

    totals = {}
    for candidate_id in ("C1", "C2", "C3", "C4"):
        candidate_result = _evaluate(candidate_id, bp, coupling_result, baseline)
        econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
        totals[candidate_id] = econ.annualised_cost_total_eur_per_a

    assert totals["C1"] < totals["C2"] < totals["C3"] < totals["C4"]


def test_worked_case_doublet_pump_electric_power_preserved_unchanged():
    candidate_result = _evaluate("C1")
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
    assert econ.doublet_pump_electric_power_kw == candidate_result.coupling_input.coupling_input.doublet_pump_electric_power_kw.value


# ── Curtailed heat has zero cost impact ─────────────────────────────────────
def test_no_separate_curtailment_charge_or_credit():
    """geothermal_curtailed_heat_kw has no DEDICATED cost/revenue TERM in
    the chain -- there is no separate curtailment charge or credit keyed
    on that field. Proven structurally: tampering ONLY curtailed_kw (all
    other fields held fixed) never changes the total or LCOH. This is a
    narrower, correct claim than "curtailment is economically inert" --
    see test_more_curtailment_reduces_utilization_and_increases_lcoh for
    the real, INDIRECT effect (via reduced injected_kw -> increased
    auxiliary opex, at constant useful heat)."""
    candidate_result = _evaluate("C1")
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())

    tampered = econ.model_copy(update={"geothermal_curtailed_heat_kw": econ.geothermal_curtailed_heat_kw + 12345.0})
    assert tampered.annualised_cost_total_eur_per_a == econ.annualised_cost_total_eur_per_a
    assert tampered.indicative_lcoh_eur_per_kwh == econ.indicative_lcoh_eur_per_kwh
    assert tampered.opex_auxiliary_heat_eur_per_a == econ.opex_auxiliary_heat_eur_per_a
    assert tampered.opex_electricity_doublet_pump_eur_per_a == econ.opex_electricity_doublet_pump_eur_per_a


def test_more_curtailment_reduces_utilization_and_increases_lcoh():
    """The real, INDIRECT economic effect of curtailment: holding the
    PyDoublet scenario fixed, a larger minimum_auxiliary_circulation_fraction
    injects less geothermal heat, so auxiliary makes up a larger share of
    the SAME total consumer demand -- annual_total_heat_delivered_kwh
    (useful heat) stays EXACTLY constant (consumers always receive full
    demand by construction), while annualised_cost_total_eur_per_a rises
    (driven by rising opex_auxiliary_heat_eur_per_a, plus the FULL
    doublet-pump electricity cost being spread over less geothermal
    utilization) -- so indicative LCOH strictly increases with the margin.
    Matches the worked-case figures verified during T2.4A's audit:
    0.01 -> 834742.76 EUR/a, 0.02 -> 849154.51 EUR/a, 0.05 -> 892363.37 EUR/a,
    useful heat constant at 16,000,000 kWh throughout."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    baseline_econ = compute_baseline_economics(baseline, assumptions=_econ_assumptions())

    fractions = [0.01, 0.02, 0.05]
    useful_heat_kwh = set()
    total_costs = []
    lcohs = []
    for fraction in fractions:
        result = _evaluate("C1", bp, coupling_result, baseline, minimum_auxiliary_circulation_fraction=fraction)
        econ = compute_candidate_economics(result, baseline_econ, assumptions=_econ_assumptions())
        useful_heat_kwh.add(round(econ.annual_total_heat_delivered_kwh, 6))
        total_costs.append(econ.annualised_cost_total_eur_per_a)
        lcohs.append(econ.indicative_lcoh_eur_per_kwh)

    assert len(useful_heat_kwh) == 1, "useful heat delivered must stay constant across curtailment levels"
    assert total_costs == sorted(total_costs) and total_costs[0] < total_costs[-1]
    assert lcohs == sorted(lcohs) and lcohs[0] < lcohs[-1]


def test_curtailment_effect_is_identical_across_c1_to_c4_and_does_not_change_ranking_order():
    """In the worked case, curtailment depends only on the shared coupling
    result and the shared minimum_auxiliary_circulation_fraction -- never
    on which candidate is evaluated -- so geothermal_curtailed_heat_kw is
    identical across C1-C4 and this effect never changes their relative
    cost ordering (only connection-pipe CAPEX differs between them)."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    baseline_econ = compute_baseline_economics(baseline, assumptions=_econ_assumptions())

    curtailed_values = set()
    for candidate_id in ("C1", "C2", "C3", "C4"):
        result = _evaluate(candidate_id, bp, coupling_result, baseline)
        curtailed_values.add(round(result.geothermal_curtailed_heat_kw, 9))
    assert len(curtailed_values) == 1


# ── Baseline DH-pumping comparison, explicit and never merged into total ───
def test_baseline_pumping_delta_never_folded_into_candidate_total():
    candidate_result = _evaluate("C1")
    baseline = _baseline()
    assumptions = _econ_assumptions()
    baseline_econ = compute_baseline_economics(baseline, assumptions=assumptions)
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=assumptions)

    # The candidate's own total is the sum of its OWN five terms only.
    own_total = (
        econ.annuity_capital_eur_per_a + econ.opex_fixed_eur_per_a + econ.opex_electricity_doublet_pump_eur_per_a
        + econ.opex_electricity_dh_pumping_eur_per_a + econ.opex_auxiliary_heat_eur_per_a
    )
    assert math.isclose(econ.annualised_cost_total_eur_per_a, own_total, rel_tol=1e-9)
    # The baseline's own total never appears as an additive term above.
    assert not math.isclose(
        econ.annualised_cost_total_eur_per_a, own_total + baseline_econ.annualised_cost_total_eur_per_a, rel_tol=1e-6,
    )


def test_baseline_dh_electrical_power_uses_only_baseline_main_pump():
    baseline = _baseline()
    assumptions = _econ_assumptions()
    baseline_econ = compute_baseline_economics(baseline, assumptions=assumptions)
    expected_electrical_kw = baseline.circulation_pump.hydraulic_pumping_power_kw / assumptions.dh_pump_efficiency
    expected_opex = expected_electrical_kw * assumptions.annual_full_load_hours * assumptions.electricity_price_eur_per_kwh
    assert math.isclose(baseline_econ.opex_electricity_dh_pumping_eur_per_a, expected_opex, rel_tol=1e-9)


def test_candidate_dh_electrical_power_uses_connection_plus_residual_main_pump():
    candidate_result = _evaluate("C1")
    assumptions = _econ_assumptions()
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=assumptions)
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=assumptions)

    expected_hydraulic_kw = candidate_result.circulation_pump.hydraulic_pumping_power_kw + candidate_result.connection_pumping_power_kw
    assert math.isclose(econ.dh_hydraulic_pumping_power_kw, expected_hydraulic_kw, rel_tol=1e-9)
    # The candidate's own main pump runs at reduced (residual) flow, never
    # the baseline's own higher-flow figure.
    assert candidate_result.circulation_pump.hydraulic_pumping_power_kw < baseline_econ.main_pump_hydraulic_power_kw

    expected_electrical_kw = expected_hydraulic_kw / assumptions.dh_pump_efficiency
    expected_opex = expected_electrical_kw * assumptions.annual_full_load_hours * assumptions.electricity_price_eur_per_kwh
    assert math.isclose(econ.opex_electricity_dh_pumping_eur_per_a, expected_opex, rel_tol=1e-9)


def test_pumping_cost_delta_matches_candidate_minus_baseline():
    candidate_result = _evaluate("C1")
    assumptions = _econ_assumptions()
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=assumptions)
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=assumptions)
    expected_delta = econ.opex_electricity_dh_pumping_eur_per_a - baseline_econ.opex_electricity_dh_pumping_eur_per_a
    assert math.isclose(econ.opex_electricity_dh_pumping_delta_eur_per_a, expected_delta, rel_tol=1e-9)


def test_stabilization_margin_applied_flag_reflects_the_embedded_warning():
    candidate_result = _evaluate("C1")  # 1% margin, worked case: stabilization applies
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    econ = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
    assert econ.stabilization_margin_applied is True


# ── Strict-JSON round trip ───────────────────────────────────────────────────
def test_baseline_economics_strict_json_round_trip():
    result = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    dumped = result.model_dump_json()
    _strict_json_loads(dumped)
    restored = BaselineEconomicResult.model_validate_json(dumped)
    assert restored == result


def test_tamper_baseline_scope_caveat_altered_is_rejected():
    result = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    payload = json.loads(result.model_dump_json())
    payload["scope_caveat"] = "a shortened, unapproved caveat"
    with pytest.raises(ValidationError):
        BaselineEconomicResult.model_validate_json(json.dumps(payload))


def test_candidate_economics_strict_json_round_trip():
    candidate_result = _evaluate("C1")
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    result = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
    dumped = result.model_dump_json()
    _strict_json_loads(dumped)
    restored = CandidateEconomicResult.model_validate_json(dumped)
    assert restored == result


# ── Model-level tamper tests ─────────────────────────────────────────────────
def _valid_candidate_economics_payload() -> dict:
    candidate_result = _evaluate("C1")
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    result = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
    return json.loads(result.model_dump_json())


def test_control_untouched_payload_round_trips_cleanly():
    payload = _valid_candidate_economics_payload()
    CandidateEconomicResult.model_validate_json(json.dumps(payload))


def test_tamper_annualised_cost_total_inconsistent_is_rejected():
    payload = _valid_candidate_economics_payload()
    payload["annualised_cost_total_eur_per_a"] += 100.0
    with pytest.raises(ValidationError):
        CandidateEconomicResult.model_validate_json(json.dumps(payload))


def test_tamper_connection_pipe_capex_inconsistent_with_length_is_rejected():
    payload = _valid_candidate_economics_payload()
    payload["capex_connection_pipes_eur"] = 999999.0
    with pytest.raises(ValidationError):
        CandidateEconomicResult.model_validate_json(json.dumps(payload))


def test_tamper_lcoh_inconsistent_with_cost_and_heat_is_rejected():
    payload = _valid_candidate_economics_payload()
    payload["indicative_lcoh_eur_per_kwh"] = 0.0
    with pytest.raises(ValidationError):
        CandidateEconomicResult.model_validate_json(json.dumps(payload))


def test_tamper_negative_curtailed_heat_is_rejected():
    payload = _valid_candidate_economics_payload()
    payload["geothermal_curtailed_heat_kw"] = -1.0
    with pytest.raises(ValidationError):
        CandidateEconomicResult.model_validate_json(json.dumps(payload))


def test_tamper_annuity_capital_inconsistent_is_rejected():
    payload = _valid_candidate_economics_payload()
    payload["annuity_capital_eur_per_a"] = payload["annuity_doublet_eur_per_a"]  # drops hx/pipes contributions
    with pytest.raises(ValidationError):
        CandidateEconomicResult.model_validate_json(json.dumps(payload))


def test_models_are_frozen():
    candidate_result = _evaluate("C1")
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=_econ_assumptions())
    result = compute_candidate_economics(candidate_result, baseline_econ, assumptions=_econ_assumptions())
    with pytest.raises(ValidationError):
        result.annualised_cost_total_eur_per_a = 0.0


# ── Determinism and non-mutation ─────────────────────────────────────────────
def test_computation_does_not_mutate_inputs():
    bp = _blueprint()
    baseline = _baseline(bp)
    candidate_result = _evaluate("C1", bp, baseline=baseline)
    baseline_snapshot = baseline.model_dump_json()
    candidate_snapshot = candidate_result.model_dump_json()
    assumptions = _econ_assumptions()
    baseline_econ = compute_baseline_economics(baseline, assumptions=assumptions)
    compute_candidate_economics(candidate_result, baseline_econ, assumptions=assumptions)
    assert baseline.model_dump_json() == baseline_snapshot
    assert candidate_result.model_dump_json() == candidate_snapshot


def test_two_computations_of_the_same_candidate_are_bit_identical():
    candidate_result = _evaluate("C1")
    assumptions = _econ_assumptions()
    baseline_econ = compute_baseline_economics(_baseline(), assumptions=assumptions)

    result_1 = compute_candidate_economics(candidate_result, baseline_econ, assumptions=assumptions)
    result_2 = compute_candidate_economics(candidate_result, baseline_econ, assumptions=assumptions)
    payload_1 = json.loads(result_1.model_dump_json())
    payload_2 = json.loads(result_2.model_dump_json())
    del payload_1["created_at"], payload_2["created_at"]
    assert payload_1 == payload_2


# ── Scope boundary ────────────────────────────────────────────────────────────
def test_no_map_report_or_mcp_identifiers_in_costing_module():
    """costing.py may legitimately MENTION ranking.py by name in
    docstrings (a correct cross-module pointer) -- this only checks it
    never implements map/report/MCP concerns itself."""
    source = _COSTING_SRC_PATH.read_text()
    match = re.match(r'^""".*?"""\n', source, flags=re.DOTALL)
    assert match is not None
    code_body = source[match.end():].lower()
    for pattern in [r"\bMCP\b", r"\bfastmcp\b", r"\bmatplotlib\b", r"\bfolium\b"]:
        assert not re.search(pattern, code_body), f"forbidden pattern {pattern!r} found in costing.py's code body"
