"""Annualized system economics across load states (Phase 3, R3-CHAIN Final
Research-Alignment Implementation Specification, RA-ECON).

## CAPEX once, OPEX summed (the spec's own explicit rule)

CAPEX/annuity is computed EXACTLY ONCE per alternative, via the existing
`economics.annuity.annuity_factor()` (imported, public) applied to the
alternative's own already-computed CAPEX figures (captured from any one
feasible load state's `CandidateEconomicResult` -- module docstring of
`workflow.load_state_evaluation.LoadStateEvaluationOutcome` explains why
this is exact, not an approximation: CAPEX never depends on consumer
demand). OPEX/auxiliary/pumping terms are computed PER LOAD STATE (that
state's own KPI, that state's own `annual_duration_hours`) and summed.

The three per-state OPEX formula shapes below (`power_kw * hours * price`)
are independently reimplemented from `economics.costing`'s identically-
shaped PRIVATE helpers (`_compute_opex_electricity_eur_per_a`,
`_compute_opex_auxiliary_heat_eur_per_a`, `_compute_annual_heat_delivered_kwh`)
-- this project's established convention (see `economics.annuity`'s own
module docstring: "reuse the PATTERN... this project's established
discipline") is to reuse PUBLIC cross-module functions but keep each
module's own underscore-prefixed helpers private and independently
reimplement their shape elsewhere, rather than importing another
module's private helper. The shapes are identical; only the driving
duration differs (a per-state `annual_duration_hours` here, vs. one
constant `assumptions.annual_full_load_hours` in `economics.costing`).

Pumping electricity (doublet pump + DH pumping, per state) is always
summed into the OPEX numerator -- never subtracted from
`annual_useful_heat_mwh_per_a` (CLAUDE.md: raw thermal power is not
automatically deliverable/useful power; this module goes one step
further and keeps every electrical term strictly on the cost side)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..data_contracts.research_experiment import (
    AnnualizedAlternativeEconomicResult,
    LoadStatePerformanceResult,
)
from .annuity import annuity_factor
from .assumptions import EconomicAssumptions
from .costing import CandidateEconomicResult


def _opex_electricity_eur_per_a(power_kw: float, hours: float, price_eur_per_kwh: float) -> float:
    """Same shape as economics.costing._compute_opex_electricity_eur_per_a,
    independently reimplemented (module docstring) -- driven by a per-state
    `hours`, not `assumptions.annual_full_load_hours`."""
    return power_kw * hours * price_eur_per_kwh


def _opex_auxiliary_heat_eur_per_a(auxiliary_heat_kw: float, hours: float, price_eur_per_kwh: float) -> float:
    return auxiliary_heat_kw * hours * price_eur_per_kwh


def _annual_heat_delivered_kwh(total_heat_delivered_kw: float, hours: float) -> float:
    return total_heat_delivered_kw * hours


def _dh_electrical_pumping_power_kw(hydraulic_pumping_power_kw: float, dh_pump_efficiency: float) -> float:
    """Same conversion as economics.costing._dh_electrical_pumping_power_kw --
    never applied to doublet_pump_electric_power_kw, which is already
    electrical."""
    return hydraulic_pumping_power_kw / dh_pump_efficiency


def compute_annualized_system_economics(
    alternative_id: str,
    load_state_results: list[LoadStatePerformanceResult],
    representative_capex_economics: CandidateEconomicResult | None,
    *,
    assumptions: EconomicAssumptions,
) -> AnnualizedAlternativeEconomicResult:
    """Pure, never raises for an expected SCIENTIFIC outcome: when one or more
    load states are infeasible, the result is `computable=False` with a typed
    `non_computable_reason` -- never estimated, interpolated, or silently
    dropped (Phase-0 audit's own "genuine risk, confirmed and evidenced"
    finding). An EMPTY `load_state_results`, or `representative_capex_economics
    is None` while every load state reports feasible, are not scientific
    outcomes at all -- `workflow.load_state_evaluation.evaluate_alternative_across_load_states()`
    (this function's only real caller) always returns exactly one result per
    declared, non-empty load state, and always captures a representative
    economics record whenever any state is feasible; either combination here
    indicates a caller defect, so it raises loudly rather than being silently
    absorbed into a graceful-looking but meaningless non-computable result."""
    created_at = datetime.now(timezone.utc)
    if not load_state_results:
        raise ValueError("load_state_results must not be empty")

    all_feasible = all(r.feasible for r in load_state_results)
    if not all_feasible:
        infeasible_ids = [r.load_state_id for r in load_state_results if not r.feasible]
        return AnnualizedAlternativeEconomicResult(
            alternative_id=alternative_id, load_state_results=load_state_results, computable=False,
            non_computable_reason=f"load state(s) {infeasible_ids} did not converge/were infeasible",
            capex_doublet_eur=None, capex_heat_exchanger_eur=None, capex_connection_pipes_eur=None,
            annuity_capital_eur_per_a=None, opex_fixed_eur_per_a=None,
            opex_electricity_doublet_pump_eur_per_a=None, opex_electricity_dh_pumping_eur_per_a=None,
            opex_auxiliary_heat_eur_per_a=None, annualized_total_system_cost_eur_per_a=None,
            annual_useful_heat_mwh_per_a=None, annualized_system_lcoh_eur_per_mwh=None, created_at=created_at,
        )

    if representative_capex_economics is None:
        raise ValueError(
            "representative_capex_economics must not be None when every load state is feasible"
        )

    capex_doublet = representative_capex_economics.capex_doublet_eur
    capex_hx = representative_capex_economics.capex_heat_exchanger_eur
    capex_pipes = representative_capex_economics.capex_connection_pipes_eur

    a_doublet = annuity_factor(assumptions.interest_rate_real, assumptions.doublet_lifetime_years)
    a_hx = annuity_factor(assumptions.interest_rate_real, assumptions.heat_exchanger_lifetime_years)
    a_pipes = annuity_factor(assumptions.interest_rate_real, assumptions.connection_pipes_lifetime_years)
    annuity_capital = capex_doublet * a_doublet + capex_hx * a_hx + capex_pipes * a_pipes

    total_capex = capex_doublet + capex_hx + capex_pipes
    opex_fixed = assumptions.fixed_om_fraction_of_capex_per_a * total_capex

    opex_doublet_pump = 0.0
    opex_dh_pumping = 0.0
    opex_aux = 0.0
    useful_kwh = 0.0
    for state in load_state_results:
        opex_doublet_pump += _opex_electricity_eur_per_a(
            state.doublet_pump_electric_power_kw, state.annual_duration_hours, assumptions.electricity_price_eur_per_kwh,
        )
        dh_electrical_kw = _dh_electrical_pumping_power_kw(
            state.dh_hydraulic_pumping_power_kw, assumptions.dh_pump_efficiency,
        )
        opex_dh_pumping += _opex_electricity_eur_per_a(
            dh_electrical_kw, state.annual_duration_hours, assumptions.electricity_price_eur_per_kwh,
        )
        opex_aux += _opex_auxiliary_heat_eur_per_a(
            state.auxiliary_heat_kw, state.annual_duration_hours, assumptions.auxiliary_heat_price_eur_per_kwh,
        )
        useful_kwh += _annual_heat_delivered_kwh(state.total_heat_delivered_kw, state.annual_duration_hours)

    total_cost = annuity_capital + opex_fixed + opex_doublet_pump + opex_dh_pumping + opex_aux
    useful_mwh = useful_kwh / 1000.0

    return AnnualizedAlternativeEconomicResult(
        alternative_id=alternative_id, load_state_results=load_state_results, computable=True,
        non_computable_reason=None,
        capex_doublet_eur=capex_doublet, capex_heat_exchanger_eur=capex_hx, capex_connection_pipes_eur=capex_pipes,
        annuity_capital_eur_per_a=annuity_capital, opex_fixed_eur_per_a=opex_fixed,
        opex_electricity_doublet_pump_eur_per_a=opex_doublet_pump,
        opex_electricity_dh_pumping_eur_per_a=opex_dh_pumping, opex_auxiliary_heat_eur_per_a=opex_aux,
        annualized_total_system_cost_eur_per_a=total_cost, annual_useful_heat_mwh_per_a=useful_mwh,
        annualized_system_lcoh_eur_per_mwh=total_cost / useful_mwh, created_at=created_at,
    )
