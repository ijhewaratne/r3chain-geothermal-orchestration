"""Synthetic joint site/connection optimisation demonstration (OPT-001..007,
R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Workstream J, AC-10).

## Goal (15.1)

A transparent, bounded, enumerative outer evaluation loop over geological/
surface-site scenarios, network connection candidates, routes and design
options -- explicitly NOT an opaque AI-generated location decision. Every
alternative this module evaluates is produced by reusing ALREADY-EXISTING,
independently-tested functions from `adapter`, `network`, and `economics`
in their own documented order; this module adds only the OUTER identity/
sequencing/Pareto layer, never new physics or economics formulas.

## Decision entity (OPT-001)

`AlternativeIdentity` is always the full six-component tuple
(`geothermal_scenario_id`, `surface_site_id`, `connection_candidate_id`,
`route_id`, `design_option_id`, `operating_policy_id`) -- never collapsed
into one generic "location" field.

## Synthetic geothermal scenarios

This demonstration cannot run real PyDoublet scenarios (out of scope,
CLAUDE.md). Instead, `build_synthetic_geothermal_scenarios()` derives three
EXPLICITLY SYNTHETIC variants from the one golden, already-validated
PyDoublet coupling result (`fixtures/pydoublet/repaired_result.json`) by
adjusting `producer_wellhead_temperature_c` and/or
`geothermal_brine_mass_flow_kg_s`, and RECOMPUTING
`raw_geothermal_thermal_power_kw` via the SAME formula T1.5B's own energy-
consistency check uses (`m_dot * cp * (T_prod - T_brine_outlet)`), so each
variant passes that check by construction rather than by chance. These are
clearly labelled synthetic (`GeothermalSiteScenario.synthetic=True`) and
must never be presented as independent real PyDoublet runs.

Each scenario also carries two site-dependent COST/POWER terms, so a
scenario's own economic consequence is no longer limited to deliverable
heat alone:

- `doublet_pump_electric_power_kw` is RESCALED (not left at the golden
  value) by the scenario's own mass-flow ratio relative to the golden
  result, reusing PyDoublet's OWN internal pump-power relationship
  (`repos/PyDoublet/pydoublet/doublet_config/doublet.py::calc_power_data()`,
  `pump_power = q_vol_pump * pump_pressure_draw_down /
  pump_system_efficiency` -- linear in volumetric/mass flow, every other
  term held fixed) -- reused, not re-derived, exactly like
  `_recompute_raw_power_kw()` reuses T1.5B's own formula above.
- `GeothermalSiteScenario.drilling_capex_multiplier` is an explicit,
  DECLARED synthetic assumption (never a depth-derived cost model -- no
  well-depth-to-cost formula exists anywhere in this codebase or in
  PyDoublet), applied to `assumptions.doublet_capex_eur` only for that
  scenario's own alternatives in `evaluate_alternative()`. It follows the
  SAME declared-multiplier pattern `network/candidate_generation.py`
  (CAN-006) already uses for route/design options ("direct" x1.0,
  "diverted" x1.5) -- an illustrative input chosen before any alternative
  is evaluated, never tuned afterward to produce a particular ranking.

## Evaluation stages (OPT-002)

`evaluate_alternative()` sequences the SAME already-existing calls
`workflow/core.py::run_workflow()` itself uses (parse/validate already done
upstream; `evaluate_heat_exchanger_coupling()`; `evaluate_candidate()`;
`compute_candidate_economics()`), recording which of OPT-002's 10 named
stages each alternative reached (`JointEvaluationStage`). It never
re-derives the underlying physics or economics -- this module's only new
logic is identity construction, stage bookkeeping, and (OPT-003) the
Pareto filter.

## Objective policy (OPT-003)

No approved objective weights exist for this prototype (Q8 approved only
the single-scenario feasibility-first-then-lowest-cost rule, not a
multi-objective weighting scheme -- decision-register.md). This module
therefore NEVER invents weights: `pareto_shortlist()` returns the
non-dominated subset of FEASIBLE alternatives across only the objectives
that actually have computed data for every alternative being compared
(OPT-003: "do not include an objective whose data/source are absent").

## Real-mode safeguard (OPT-006)

`run_joint_optimization_demo()` operates ONLY in synthetic mode -- it
does not accept or process a `classification="real"` StudyPackage.
Real-mode joint optimisation additionally requires
`data_contracts.readiness.generate_readiness_report()` to grant
`connection_optimization_permitted` (and, for a drilling-relevant
combined study, `drilling_location_optimization_permitted`) before any
alternative may be evaluated -- enforcing that check is a real-mode
integration step explicitly deferred alongside Phase 8's own external-
data gate, not implemented in this synthetic-only demonstration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from ..adapter.heat_exchanger import HeatExchangerCouplingFailure, HeatExchangerCouplingResult
from ..contracts import PyDoubletCouplingResult
from ..economics import (
    BaselineEconomicResult,
    CandidateEconomicResult,
    EconomicAssumptions,
    compute_baseline_economics,
    compute_candidate_economics,
)
from ..network import (
    BaselineNetworkResult,
    BlueprintCandidate,
    CandidateEvaluationFailure,
    CandidateEvaluationResult,
    GateTolerances,
    GeothermalInjectionPolicy,
    NetworkBlueprint,
    ScreenedCandidate,
    evaluate_candidate,
)

JOINT_OPTIMIZATION_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""Versioned independently of every other layer's own contract schema."""


class JointEvaluationStage(str, Enum):
    """OPT-002's ten evaluation stages, COLLAPSED to the granularity this
    module can actually observe: stage 1 (provenance) is satisfied
    upstream by construction (every `scenario.coupling_input` is already
    an validated `PyDoubletCouplingResult`, so it is never re-checked or
    reported as its own stage_reached value here); stages 4-6 (construct
    the doublet connection, run the independent solve, apply technical
    gates) are ALL performed inside one already-tested
    `network/candidate.py::evaluate_candidate()` call, which reports only
    the final outcome, not intermediate sub-stage checkpoints -- so
    `APPLY_TECHNICAL_GATES` is this module's own `stage_reached` value for
    ANY failure arising from that call, whether the true cause was
    construction, the solve, or a specific gate; the exact cause is still
    fully preserved in `AlternativeEvaluation.failure_code`/`message`.
    Stage 10 ("retain all rejected alternatives") is not its own stage
    value -- it is a structural property of this module (every
    alternative is always returned, feasible or not), not a state an
    alternative passes through."""

    SCREEN_SITE_AND_ROUTE_CONSTRAINTS = "SCREEN_SITE_AND_ROUTE_CONSTRAINTS"
    CALCULATE_HX_COUPLING_BOUNDARY = "CALCULATE_HX_COUPLING_BOUNDARY"
    APPLY_TECHNICAL_GATES = "APPLY_TECHNICAL_GATES"
    ADDED_TO_DECISION_SET = "ADDED_TO_DECISION_SET"
    """Terminal success stage (covers OPT-002 steps 6-9: gates passed,
    economics computed, risk metadata attached, added to the decision
    set)."""


class AlternativeIdentity(BaseModel):
    """OPT-001: the full six-component decision-entity identity."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    geothermal_scenario_id: str
    surface_site_id: str
    connection_candidate_id: str
    route_id: str
    design_option_id: str
    operating_policy_id: str

    @property
    def alternative_id(self) -> str:
        return (
            f"{self.geothermal_scenario_id}|{self.surface_site_id}|{self.connection_candidate_id}"
            f"|{self.route_id}|{self.design_option_id}|{self.operating_policy_id}"
        )


class GeothermalSiteScenario(BaseModel):
    """One (geothermal_scenario_id, surface_site_id) pairing -- OPT-001's
    first two identity axes are deliberately distinct fields, never
    merged. `synthetic=True` always -- see module docstring.

    `drilling_capex_multiplier` is a DECLARED, illustrative synthetic
    assumption (module docstring) -- multiplied against
    `EconomicAssumptions.doublet_capex_eur` in `evaluate_alternative()`
    only for this scenario's own alternatives. It is not derived from
    `coupling_input` or from any depth/geological model; no such model
    exists in this prototype."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    surface_site_id: str
    description: str
    synthetic: Literal[True] = True
    coupling_input: PyDoubletCouplingResult
    drilling_capex_multiplier: float = Field(gt=0)


class AlternativeEvaluation(BaseModel):
    """The full OPT-002 record for one alternative -- retained whether
    feasible or not (OPT-002 step 10)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_schema_version: Literal["1.0.0"] = JOINT_OPTIMIZATION_CONTRACT_SCHEMA_VERSION
    identity: AlternativeIdentity
    stage_reached: JointEvaluationStage
    feasible: bool
    failure_code: str | None
    failure_stage: JointEvaluationStage | None
    message: str
    risk_note: str
    candidate_result: CandidateEvaluationResult | None = None
    economics: CandidateEconomicResult | None = None
    created_at: datetime


class ParetoObjective(BaseModel):
    """One objective's value for one alternative, with its own declared
    optimisation direction (OPT-003)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: float
    lower_is_better: bool


class JointOptimizationResult(BaseModel):
    """OPT-005's full demonstration record."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_schema_version: Literal["1.0.0"] = JOINT_OPTIMIZATION_CONTRACT_SCHEMA_VERSION
    synthetic: Literal[True] = True
    scenarios: list[GeothermalSiteScenario]
    alternatives: list[AlternativeEvaluation]
    objectives_considered: list[str]
    pareto_shortlist_alternative_ids: list[str]
    """OPT-003: since no approved objective weights exist, this is a
    Pareto/non-dominated shortlist, never a single invented-weight
    ranking."""
    created_at: datetime


def _recompute_raw_power_kw(mass_flow_kg_s: float, specific_heat_j_kg_k: float, t_prod_c: float, t_brine_outlet_c: float) -> float:
    """The SAME formula adapter/heat_exchanger.py::_compute_raw_energy_consistency()
    uses -- reused here (not re-derived independently) so every synthetic
    scenario variant satisfies that energy-consistency check by
    construction, not by chance."""
    return mass_flow_kg_s * specific_heat_j_kg_k * (t_prod_c - t_brine_outlet_c) / 1000.0


def _scale_pump_power_kw(mass_flow_kg_s: float, golden_mass_flow_kg_s: float, golden_pump_power_kw: float) -> float:
    """Scales the golden doublet-pump electrical power linearly with the
    scenario's own mass-flow ratio, reusing PyDoublet's OWN internal
    pump-power relationship (`repos/PyDoublet/pydoublet/doublet_config/
    doublet.py::calc_power_data()`: `pump_power = q_vol_pump *
    pump_pressure_draw_down / pump_system_efficiency`, linear in
    volumetric/mass flow with every other term -- density, pressure
    drawdown, pump efficiency -- held fixed). Reused, not re-derived,
    exactly like `_recompute_raw_power_kw()` above. A ratio of 1.0 (mass
    flow unchanged from golden) leaves the golden pump power unchanged."""
    return golden_pump_power_kw * (mass_flow_kg_s / golden_mass_flow_kg_s)


def build_synthetic_geothermal_scenarios(golden_coupling_input: PyDoubletCouplingResult) -> list[GeothermalSiteScenario]:
    """OPT-005: at least three explicitly synthetic geothermal/site
    scenarios, derived from the ONE golden PyDoublet result (this
    demonstration cannot run real PyDoublet scenarios). `scenario_B` is
    deliberately hot-end HX-infeasible (OPT-005's required "at least one
    geological/site screening failure") -- its
    producer_wellhead_temperature_c is lowered while
    raw_geothermal_thermal_power_kw is recomputed via the SAME
    energy-consistency formula T1.5B applies, so it fails the HX
    hot-end check specifically, not the earlier, unrelated energy-
    consistency gate.

    Each scenario also carries a rescaled doublet_pump_electric_power_kw
    (linear in its own mass-flow ratio, reusing PyDoublet's own pump-power
    formula -- module docstring) and a declared, illustrative
    `drilling_capex_multiplier` (1.0 / 0.85 / 1.15 below) chosen before any
    alternative is evaluated, never tuned afterward to produce a
    particular ranking outcome."""
    mass_flow = golden_coupling_input.geothermal_brine_mass_flow_kg_s.value
    specific_heat = golden_coupling_input.geothermal_brine_specific_heat_capacity_j_kg_k.value
    t_brine_outlet = golden_coupling_input.geothermal_brine_hx_outlet_temperature_c.value
    golden_pump_power = golden_coupling_input.doublet_pump_electric_power_kw.value

    def _variant(t_prod_c: float, mass_flow_kg_s: float) -> PyDoubletCouplingResult:
        raw_power_kw = _recompute_raw_power_kw(mass_flow_kg_s, specific_heat, t_prod_c, t_brine_outlet)
        pump_power_kw = _scale_pump_power_kw(mass_flow_kg_s, mass_flow, golden_pump_power)
        return golden_coupling_input.model_copy(update={
            "producer_wellhead_temperature_c": golden_coupling_input.producer_wellhead_temperature_c.model_copy(
                update={"value": t_prod_c},
            ),
            "geothermal_brine_mass_flow_kg_s": golden_coupling_input.geothermal_brine_mass_flow_kg_s.model_copy(
                update={"value": mass_flow_kg_s},
            ),
            "raw_geothermal_thermal_power_kw": golden_coupling_input.raw_geothermal_thermal_power_kw.model_copy(
                update={"value": raw_power_kw},
            ),
            "doublet_pump_electric_power_kw": golden_coupling_input.doublet_pump_electric_power_kw.model_copy(
                update={"value": pump_power_kw},
            ),
        })

    return [
        GeothermalSiteScenario(
            scenario_id="scenario_A", surface_site_id="site_A",
            description="Synthetic scenario A: the golden PyDoublet result, unmodified.",
            coupling_input=golden_coupling_input,
            drilling_capex_multiplier=1.0,
        ),
        GeothermalSiteScenario(
            scenario_id="scenario_B", surface_site_id="site_B",
            description=(
                "Synthetic scenario B: producer_wellhead_temperature_c deliberately lowered to "
                "60.0 degC (below dh_supply_temperature_c=70.0 + minimum_hx_approach_k=5.0=75.0) "
                "to demonstrate a geological/site-level HX_SUPPLY_TEMPERATURE_INFEASIBLE screening "
                "failure -- raw_geothermal_thermal_power_kw is recomputed via the same "
                "mass_flow*cp*(T_prod-T_brine_outlet) formula so this variant passes the "
                "unrelated raw-energy-consistency check. drilling_capex_multiplier=0.85 is a "
                "declared, illustrative 'shallower/cheaper reservoir' assumption; it never reaches "
                "the economics stage in the curated demo below since this scenario fails HX "
                "screening first."
            ),
            coupling_input=_variant(t_prod_c=60.0, mass_flow_kg_s=mass_flow),
            drilling_capex_multiplier=0.85,
        ),
        GeothermalSiteScenario(
            scenario_id="scenario_C", surface_site_id="site_C",
            description=(
                "Synthetic scenario C: brine mass flow scaled to 70% of the golden value "
                "(producer_wellhead_temperature_c unchanged) -- a genuinely different, still "
                "HX-feasible scenario with a lower deliverable heat ceiling, a proportionally "
                "scaled doublet-pump power, and drilling_capex_multiplier=1.15 (a declared, "
                "illustrative 'deeper/more difficult reservoir' assumption)."
            ),
            coupling_input=_variant(
                t_prod_c=golden_coupling_input.producer_wellhead_temperature_c.value, mass_flow_kg_s=mass_flow * 0.7,
            ),
            drilling_capex_multiplier=1.15,
        ),
    ]


def evaluate_alternative(
    identity: AlternativeIdentity,
    scenario: GeothermalSiteScenario,
    screened_candidate: ScreenedCandidate,
    blueprint: NetworkBlueprint,
    baseline: BaselineNetworkResult,
    baseline_economics: BaselineEconomicResult,
    *,
    coupling_assumptions: CouplingAssumptions,
    injection_policy: GeothermalInjectionPolicy,
    tolerances: GateTolerances,
    economic_assumptions: EconomicAssumptions,
) -> AlternativeEvaluation:
    """OPT-002's full per-alternative sequence. Never raises; every
    outcome (feasible or not, and at whichever stage it stopped) is
    returned as a typed record (OPT-002 step 10)."""
    created_at = datetime.now(timezone.utc)

    # Stage 1 (provenance) is already satisfied -- scenario.coupling_input
    # is an already-validated PyDoubletCouplingResult (T1.5B success type).
    # Stage 2: site/route screening (Workstream H's own generator).
    if not screened_candidate.accepted:
        return AlternativeEvaluation(
            identity=identity, stage_reached=JointEvaluationStage.SCREEN_SITE_AND_ROUTE_CONSTRAINTS,
            feasible=False, failure_code=(screened_candidate.rejection_reason.value if screened_candidate.rejection_reason else None),
            failure_stage=JointEvaluationStage.SCREEN_SITE_AND_ROUTE_CONSTRAINTS,
            message=screened_candidate.rejection_detail, risk_note="not evaluated -- screened out before coupling",
            created_at=created_at,
        )

    # Stage 3: HX coupling boundary.
    coupling_boundary = evaluate_heat_exchanger_coupling(scenario.coupling_input, assumptions=coupling_assumptions)
    if isinstance(coupling_boundary, HeatExchangerCouplingFailure):
        return AlternativeEvaluation(
            identity=identity, stage_reached=JointEvaluationStage.CALCULATE_HX_COUPLING_BOUNDARY,
            feasible=False, failure_code=coupling_boundary.failure_code.value,
            failure_stage=JointEvaluationStage.CALCULATE_HX_COUPLING_BOUNDARY,
            message=coupling_boundary.message, risk_note="not evaluated -- geological/site HX boundary infeasible",
            created_at=created_at,
        )
    coupling_result: HeatExchangerCouplingResult = coupling_boundary

    # Stage 4-5: construct the doublet connection and run the independent
    # network solve (network/candidate.py::evaluate_candidate() already
    # does both, plus stage 6's technical gates, in one already-tested call).
    blueprint_candidate = screened_candidate.spec.to_blueprint_candidate()  # type: ignore[union-attr]
    candidate_boundary = evaluate_candidate(
        coupling_result, blueprint, blueprint_candidate, baseline,
        injection_policy=injection_policy, tolerances=tolerances,
    )
    if isinstance(candidate_boundary, CandidateEvaluationFailure):
        return AlternativeEvaluation(
            identity=identity, stage_reached=JointEvaluationStage.APPLY_TECHNICAL_GATES,
            feasible=False, failure_code=candidate_boundary.failure_code.value,
            failure_stage=JointEvaluationStage.APPLY_TECHNICAL_GATES,
            message=candidate_boundary.message, risk_note="not evaluated -- network-connection technical gate failed",
            created_at=created_at,
        )
    candidate_result: CandidateEvaluationResult = candidate_boundary

    # Stage 7: economics, only now that the alternative is technically feasible.
    # scenario.drilling_capex_multiplier applies ONLY to this scenario's own
    # alternatives -- compute_candidate_economics() itself is unchanged (module
    # docstring); a scenario-adjusted EconomicAssumptions copy is passed in its
    # place so doublet CAPEX (and its annuity) reflects this scenario's own
    # declared drilling-cost assumption.
    scenario_economic_assumptions = economic_assumptions.model_copy(update={
        "doublet_capex_eur": economic_assumptions.doublet_capex_eur * scenario.drilling_capex_multiplier,
    })
    economics = compute_candidate_economics(candidate_result, baseline_economics, assumptions=scenario_economic_assumptions)

    # Stage 8: risk/uncertainty metadata -- this prototype has no formal
    # uncertainty quantification (OPT-004's own scope), so this is a
    # single descriptive note, never a fabricated numeric risk score.
    risk_note = (
        f"deterministic single-scenario evaluation of {scenario.scenario_id!r}; no probabilistic "
        "uncertainty quantification is performed by this prototype (OPT-004)"
    )

    return AlternativeEvaluation(
        identity=identity, stage_reached=JointEvaluationStage.ADDED_TO_DECISION_SET,
        feasible=True, failure_code=None, failure_stage=None, message="feasible", risk_note=risk_note,
        candidate_result=candidate_result, economics=economics, created_at=created_at,
    )


_OBJECTIVE_SPECS: list[tuple[str, bool]] = [
    ("annualised_cost_total_eur_per_a", True),
    ("indicative_lcoh_eur_per_mwh", True),
    ("geothermal_injected_heat_kw", False),
    ("auxiliary_heat_kw", True),
    ("total_pumping_electricity_eur_per_a", True),
    ("surface_connection_length_m", True),
]
"""OPT-003's supported objective fields, restricted to those this
prototype actually computes data for (annualized cost, indicative LCOH,
geothermal heat delivered, auxiliary heat, pumping electricity,
connection length). Drilling/site cost is now DIFFERENTIATED per scenario
(GeothermalSiteScenario.drilling_capex_multiplier, module docstring) and
flows into annualised_cost_total_eur_per_a/indicative_lcoh_eur_per_mwh
above -- it has no SEPARATE objective entry of its own only because it is
not an independently reported KPI on CandidateEconomicResult, not because
it is undifferentiated. Risk/success-probability and emissions remain
DELIBERATELY excluded: no data/source exists for them in this prototype
(OPT-003's own explicit instruction)."""


def _objective_values(alt: AlternativeEvaluation) -> dict[str, ParetoObjective]:
    assert alt.economics is not None and alt.candidate_result is not None
    econ = alt.economics
    raw = {
        "annualised_cost_total_eur_per_a": econ.annualised_cost_total_eur_per_a,
        "indicative_lcoh_eur_per_mwh": econ.indicative_lcoh_eur_per_kwh * 1000.0,
        "geothermal_injected_heat_kw": econ.geothermal_injected_heat_kw,
        "auxiliary_heat_kw": econ.auxiliary_heat_kw,
        "total_pumping_electricity_eur_per_a": (
            econ.opex_electricity_dh_pumping_eur_per_a + econ.opex_electricity_doublet_pump_eur_per_a
        ),
        "surface_connection_length_m": alt.candidate_result.candidate.surface_connection_length_m,
    }
    return {name: ParetoObjective(name=name, value=raw[name], lower_is_better=lower) for name, lower in _OBJECTIVE_SPECS}


def pareto_shortlist(feasible_alternatives: list[AlternativeEvaluation]) -> tuple[list[str], list[str]]:
    """OPT-003: returns (non_dominated_alternative_ids, objectives_considered).
    An alternative A dominates B iff A is at least as good as B on EVERY
    considered objective and strictly better on at least one. Deterministic:
    ties are never arbitrarily broken -- both remain in the shortlist."""
    if not feasible_alternatives:
        return [], []
    objectives_by_id = {alt.identity.alternative_id: _objective_values(alt) for alt in feasible_alternatives}
    objective_names = [name for name, _ in _OBJECTIVE_SPECS]

    def _dominates(a_id: str, b_id: str) -> bool:
        a, b = objectives_by_id[a_id], objectives_by_id[b_id]
        at_least_as_good = True
        strictly_better = False
        for name in objective_names:
            av, bv, lower_is_better = a[name].value, b[name].value, a[name].lower_is_better
            a_better = (av < bv) if lower_is_better else (av > bv)
            a_worse = (av > bv) if lower_is_better else (av < bv)
            if a_worse:
                at_least_as_good = False
                break
            if a_better:
                strictly_better = True
        return at_least_as_good and strictly_better

    ids = sorted(objectives_by_id)
    non_dominated = [
        alt_id for alt_id in ids
        if not any(_dominates(other_id, alt_id) for other_id in ids if other_id != alt_id)
    ]
    return non_dominated, objective_names


def run_joint_optimization_demo(
    golden_coupling_input: PyDoubletCouplingResult,
    blueprint: NetworkBlueprint,
    baseline: BaselineNetworkResult,
    screened_candidates_by_id: dict[str, ScreenedCandidate],
    *,
    coupling_assumptions: CouplingAssumptions,
    injection_policy: GeothermalInjectionPolicy,
    tolerances: GateTolerances,
    economic_assumptions: EconomicAssumptions,
) -> JointOptimizationResult:
    """OPT-005: the curated, deterministic synthetic demonstration.
    Deliberately a CURATED alternative list, not a full cross-product of
    every scenario x every candidate -- see docs/issues/joint-location-optimization.md
    for why a full cross-product was judged disproportionate to a
    demonstration, and how this curated set still satisfies every OPT-005
    minimum (>=3 scenarios, >=4 generated candidates referenced, >=2
    route/design options, >=1 site screening failure, >=1 hydraulic/
    thermal failure, >=2 feasible alternatives)."""
    created_at = datetime.now(timezone.utc)
    scenarios = build_synthetic_geothermal_scenarios(golden_coupling_input)
    scenarios_by_id = {s.scenario_id: s for s in scenarios}
    baseline_economics = compute_baseline_economics(baseline, assumptions=economic_assumptions)

    plan = [
        ("scenario_A", "r3chain-synthetic-network-v1-trunk_1-direct-standard", "standard"),
        ("scenario_A", "r3chain-synthetic-network-v1-trunk_2-diverted-standard", "standard"),
        ("scenario_A", "r3chain-synthetic-network-v1-consumer_1-direct-standard", "standard"),
        ("scenario_B", "r3chain-synthetic-network-v1-trunk_1-direct-standard", "standard"),
        ("scenario_C", "r3chain-synthetic-network-v1-trunk_3-direct-standard", "standard"),
        ("scenario_C", "r3chain-synthetic-network-v1-trunk_4-diverted-standard", "standard"),
    ]

    alternatives: list[AlternativeEvaluation] = []
    for scenario_id, candidate_id, operating_policy_id in plan:
        scenario = scenarios_by_id[scenario_id]
        screened_candidate = screened_candidates_by_id[candidate_id]
        route_id = screened_candidate.spec.route_id if screened_candidate.spec else candidate_id.split("-")[-2]
        design_option_id = screened_candidate.spec.design_option_id if screened_candidate.spec else candidate_id.split("-")[-1]
        identity = AlternativeIdentity(
            geothermal_scenario_id=scenario.scenario_id, surface_site_id=scenario.surface_site_id,
            connection_candidate_id=candidate_id, route_id=route_id, design_option_id=design_option_id,
            operating_policy_id=operating_policy_id,
        )
        alternatives.append(evaluate_alternative(
            identity, scenario, screened_candidate, blueprint, baseline, baseline_economics,
            coupling_assumptions=coupling_assumptions, injection_policy=injection_policy,
            tolerances=tolerances, economic_assumptions=economic_assumptions,
        ))

    feasible = [a for a in alternatives if a.feasible]
    shortlist_ids, objectives = pareto_shortlist(feasible)

    return JointOptimizationResult(
        scenarios=scenarios, alternatives=alternatives, objectives_considered=objectives,
        pareto_shortlist_alternative_ids=shortlist_ids, created_at=created_at,
    )


def run_joint_optimization_full_product(
    golden_coupling_input: PyDoubletCouplingResult,
    blueprint: NetworkBlueprint,
    baseline: BaselineNetworkResult,
    screened_candidates_by_id: dict[str, ScreenedCandidate],
    *,
    coupling_assumptions: CouplingAssumptions,
    injection_policy: GeothermalInjectionPolicy,
    tolerances: GateTolerances,
    economic_assumptions: EconomicAssumptions,
) -> JointOptimizationResult:
    """R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase 4: the FULL
    deterministic product of every synthetic geothermal scenario
    (`build_synthetic_geothermal_scenarios()`) x every ACCEPTED generated
    candidate (`screened_candidates_by_id`, `network.candidate_generation
    .generate_candidates()`'s own output) -- no hand-curated subset, no
    undisclosed filtering, unlike `run_joint_optimization_demo()`'s own
    six-alternative demonstration above (kept unchanged, still available,
    documented with its OWN audited justification in
    docs/issues/joint-location-optimization.md).

    Every alternative in the resulting `scenarios x accepted_candidates`
    grid is evaluated and returned in `result.alternatives` --
    `len(result.alternatives)` therefore EQUALS the full, unfiltered
    search-space size by construction; nothing is silently dropped before
    ranking. The one filtering step that DOES happen -- CAN-005's own
    site/route screening inside `generate_candidates()` (rejecting, e.g.,
    excessive route length or protected geometry) -- is a separate,
    already-audited, upstream step with its own stable reason codes
    (`screened_candidates_by_id` itself, passed in by the caller, still
    carries every rejected candidate and its exact reason) -- it is not
    hidden by this function, and this function does not additionally
    filter beyond it.

    The design-option axis currently contributes exactly ONE value
    ("standard", `network.candidate_generation.DesignOption`'s only
    implemented variant) for every accepted candidate -- stated plainly
    rather than silently multiplied by a design-option count that does
    not yet vary (see `docs/issues/candidate-generation.md`'s own
    documented limitation)."""
    created_at = datetime.now(timezone.utc)
    scenarios = build_synthetic_geothermal_scenarios(golden_coupling_input)
    baseline_economics = compute_baseline_economics(baseline, assumptions=economic_assumptions)

    accepted_candidate_ids = sorted(cid for cid, sc in screened_candidates_by_id.items() if sc.accepted)

    alternatives: list[AlternativeEvaluation] = []
    for scenario in scenarios:
        for candidate_id in accepted_candidate_ids:
            screened_candidate = screened_candidates_by_id[candidate_id]
            spec = screened_candidate.spec
            assert spec is not None  # accepted implies spec is set (ScreenedCandidate's own invariant)
            identity = AlternativeIdentity(
                geothermal_scenario_id=scenario.scenario_id, surface_site_id=scenario.surface_site_id,
                connection_candidate_id=candidate_id, route_id=spec.route_id, design_option_id=spec.design_option_id,
                operating_policy_id="standard",
            )
            alternatives.append(evaluate_alternative(
                identity, scenario, screened_candidate, blueprint, baseline, baseline_economics,
                coupling_assumptions=coupling_assumptions, injection_policy=injection_policy,
                tolerances=tolerances, economic_assumptions=economic_assumptions,
            ))

    feasible = [a for a in alternatives if a.feasible]
    shortlist_ids, objectives = pareto_shortlist(feasible)

    return JointOptimizationResult(
        scenarios=scenarios, alternatives=alternatives, objectives_considered=objectives,
        pareto_shortlist_alternative_ids=shortlist_ids, created_at=created_at,
    )
