"""Per-(alternative, load-state) evaluation (Phase 2, R3-CHAIN Final
Research-Alignment Implementation Specification, RA-LOAD).

## Reuse, not reinvention

This module adds NO new coupling or network-evaluation logic. Every load
state reuses `workflow.joint_evaluation.evaluate_alternative()` UNCHANGED
-- the same function the corrected v2 joint workflow already calls once
per alternative -- against a FRESH blueprint/baseline/baseline-economics
triple built for that state's own SCALED consumer demand. The only new
logic here is: scaling `workflow.core._build_blueprint_kwargs()`'s own
`consumer_demands_kw` by a load state's `demand_scale_fraction`, and
mapping `JointAlternativeEvaluation`'s already-computed economics (which
already exposes every KPI this module needs, in the right units --
`network.candidate.evaluate_candidate()` -> `economics.joint_costing
.compute_alternative_economics()` -> `economics.costing
.compute_candidate_economics()`) onto `LoadStatePerformanceResult`.

Nothing here mutates a shared network object across load states or
alternatives: `build_scaled_blueprint()` constructs an independent
`NetworkBlueprint` per call (matching `evaluate_candidate()`'s own
per-candidate, fresh-`pandapipes.pandapipesNet` discipline one level up).

## The Phase-0 audit's flagged risk area (low-load curtailment)

A load state with a much-reduced `demand_scale_fraction` produces a much
larger geothermal-surplus-over-demand ratio than the golden case's own
~1% surplus, which is the only regime `network.candidate
.GeothermalInjectionPolicy`'s `minimum_auxiliary_circulation_fraction`
stabilization margin was empirically verified against (see that module's
own docstring and `docs/technical-observations/pandapipes-circulation-pump-direction-check.md`).
This module treats `THERMAL_PIPEFLOW_NOT_CONVERGED` /
`CONSUMER_TEMPERATURE_NOT_MET` at a low-load state as a first-class,
expected-possible outcome: it is reported as an ordinary infeasible
`LoadStatePerformanceResult` with its own failure_code, never masked,
retried with a widened margin, or silently dropped. A SCALED BASELINE
that itself fails to converge (distinct from the geothermal-candidate
evaluation failing) is reported with a `BASELINE_`-prefixed failure_code
so the two failure sources stay distinguishable."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..adapter import CouplingAssumptions
from ..contracts.coupling_result import PyDoubletCouplingResult
from ..data_contracts.joint_study import (
    AlternativeIdentity,
    ConnectionDesignOption,
    GeothermalResourceScenario,
    NetworkAttachment,
    SiteConnectionRoute,
)
from ..data_contracts.research_experiment import LoadStateDefinition, LoadStatePerformanceResult
from ..economics.assumptions import EconomicAssumptions
from ..economics.costing import CandidateEconomicResult, compute_baseline_economics
from ..network import (
    BaselineNetworkFailure,
    GateTolerances,
    GeothermalInjectionPolicy,
    NetworkBlueprint,
    build_default_blueprint,
    run_baseline_evaluation,
)
from .core import _build_blueprint_kwargs
from .joint_evaluation import evaluate_alternative


def build_scaled_blueprint(
    config: dict[str, Any], *, demand_scale_fraction: float, created_at: datetime,
) -> NetworkBlueprint:
    """Same construction path as the canonical/v2 workflow's own
    `build_default_blueprint(**_build_blueprint_kwargs(config))` -- only
    `consumer_demands_kw` is scaled, uniformly across every consumer, by
    `demand_scale_fraction`. Every other blueprint parameter (pipe sizing,
    temperatures, pump lift, ...) is identical across load states, matching
    the spec's own scope: only the load level varies, not the network
    design."""
    kwargs = _build_blueprint_kwargs(config)
    kwargs["consumer_demands_kw"] = {
        consumer_id: demand_kw * demand_scale_fraction
        for consumer_id, demand_kw in kwargs["consumer_demands_kw"].items()
    }
    return build_default_blueprint(created_at=created_at, **kwargs)


def _infeasible_result(
    load_state: LoadStateDefinition, *, failure_code: str, message: str,
) -> LoadStatePerformanceResult:
    return LoadStatePerformanceResult(
        load_state_id=load_state.load_state_id, annual_duration_hours=load_state.annual_duration_hours,
        feasible=False, failure_code=failure_code, message=message,
        geothermal_injected_heat_kw=None, geothermal_curtailed_heat_kw=None, auxiliary_heat_kw=None,
        total_heat_delivered_kw=None, doublet_pump_electric_power_kw=None, dh_hydraulic_pumping_power_kw=None,
        warnings=[],
    )


@dataclass(frozen=True)
class LoadStateEvaluationOutcome:
    """`representative_capex_economics` is the first FEASIBLE load state's own
    `CandidateEconomicResult`, kept ONLY for its CAPEX/annuity fields
    (`capex_doublet_eur`, `capex_heat_exchanger_eur`, `capex_connection_pipes_eur`,
    `annuity_*_eur_per_a`) -- these depend only on the alternative's own site/
    scenario/design (`economics.joint_costing.compute_alternative_economics()`),
    never on consumer demand, so they are identical across every feasible load
    state for this alternative; capturing one is not an approximation. `None`
    when every load state was infeasible (nothing to capture CAPEX from)."""
    load_state_results: list[LoadStatePerformanceResult]
    representative_capex_economics: CandidateEconomicResult | None


def evaluate_alternative_across_load_states(
    identity: AlternativeIdentity,
    scenario: GeothermalResourceScenario,
    route: SiteConnectionRoute,
    attachment: NetworkAttachment,
    design: ConnectionDesignOption,
    golden: PyDoubletCouplingResult,
    config: dict[str, Any],
    base_assumptions: EconomicAssumptions,
    load_states: list[LoadStateDefinition],
    *,
    coupling_assumptions: CouplingAssumptions,
    injection_policy: GeothermalInjectionPolicy,
    tolerances: GateTolerances,
) -> LoadStateEvaluationOutcome:
    """Evaluates one alternative at every declared load state, independently
    (RA-LOAD-002: never mutates or reuses a network object across states).
    One load state's failure never aborts evaluation of the others --
    matching `workflow.joint_evaluation.evaluate_compatible_alternatives()`'s
    own "one alternative's expected failure never aborts the others"
    discipline, one level down."""
    results: list[LoadStatePerformanceResult] = []
    representative_capex_economics: CandidateEconomicResult | None = None
    for load_state in load_states:
        created_at = datetime.now(timezone.utc)
        blueprint = build_scaled_blueprint(
            config, demand_scale_fraction=load_state.demand_scale_fraction, created_at=created_at,
        )
        baseline_boundary = run_baseline_evaluation(blueprint, tolerances=tolerances)
        if isinstance(baseline_boundary, BaselineNetworkFailure):
            results.append(_infeasible_result(
                load_state, failure_code=f"BASELINE_{baseline_boundary.failure_code.value}",
                message=f"scaled baseline (demand_scale_fraction={load_state.demand_scale_fraction!r}) "
                        f"failed to converge: {baseline_boundary.message}",
            ))
            continue
        baseline = baseline_boundary
        baseline_economics = compute_baseline_economics(baseline, assumptions=base_assumptions)

        evaluation = evaluate_alternative(
            identity, scenario, route, attachment, design, golden, blueprint, baseline,
            baseline_economics, base_assumptions,
            coupling_assumptions=coupling_assumptions, injection_policy=injection_policy, tolerances=tolerances,
        )
        if not evaluation.feasible:
            results.append(_infeasible_result(
                load_state, failure_code=evaluation.failure_code or "UNKNOWN_INFEASIBLE", message=evaluation.message,
            ))
            continue

        economics = evaluation.economics
        assert economics is not None  # JointAlternativeEvaluation's own invariant: non-null iff feasible
        if representative_capex_economics is None:
            representative_capex_economics = economics
        results.append(LoadStatePerformanceResult(
            load_state_id=load_state.load_state_id, annual_duration_hours=load_state.annual_duration_hours,
            feasible=True, failure_code=None, message=None,
            geothermal_injected_heat_kw=economics.geothermal_injected_heat_kw,
            geothermal_curtailed_heat_kw=economics.geothermal_curtailed_heat_kw,
            auxiliary_heat_kw=economics.auxiliary_heat_kw,
            total_heat_delivered_kw=economics.total_heat_delivered_kw,
            doublet_pump_electric_power_kw=economics.doublet_pump_electric_power_kw,
            dh_hydraulic_pumping_power_kw=economics.dh_hydraulic_pumping_power_kw,
            warnings=[w.code for w in evaluation.candidate_result.warnings] if evaluation.candidate_result else [],
        ))
    return LoadStateEvaluationOutcome(
        load_state_results=results, representative_capex_economics=representative_capex_economics,
    )
