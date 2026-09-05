"""Cross-baseline comparison, decision reuse, and deterministic sensitivity/
robustness (Phase 4, R3-CHAIN Final Research-Alignment Implementation
Specification, RA-DEC/BASE/SENS).

## Reuse, not reinvention (Phase-0 audit finding)

`decision.joint_policy.decide()` / `pareto_shortlist()` / the materiality-
aware dominance machinery are called UNCHANGED. They operate purely on
`AlternativeObjectiveValues(alternative_id, values: dict[str, float])` +
`data_contracts.joint_study.DecisionPolicy` -- both already fully generic.
This module never re-derives ranking or dominance logic; it only BUILDS
`AlternativeObjectiveValues` directly from each alternative's already-
computed `AnnualizedAlternativeEconomicResult` (bypassing
`decision.joint_policy._OBJECTIVE_EXTRACTORS`, whose extractor signature
is shaped for one single-load-state candidate/economics pair, not a
multi-load-state annualized value -- Phase-0 audit finding).

## The three baselines (RA-BASE)

- **Integrated**: every compatible alternative, decided via the SAME
  `decide()` call any v2-style decision uses.
- **Geothermal-only**: ranks SITES (not full alternatives) by a NEW
  `compute_geothermal_only_lcoh_eur_per_mwh()` -- a genuinely new,
  narrowly-scoped formula (module docstring below explains why no
  existing function fits: every existing costing function requires a
  pandapipes-network-derived `CandidateEvaluationResult`, which a
  network-free source-side baseline has none of). CAPEX is doublet + HX
  only (no connection pipes, no DH network); OPEX is doublet-pump
  electricity only; useful heat is the scenario's own HX-boundary
  deliverable heat, at the SAME `assumptions.annual_full_load_hours`
  single-operating-point convention every other single-state economics
  figure in this project already uses (there is no district-heating
  network in this baseline, so no load-state concept applies to it).
- **Network-only, fixed source**: a FILTER of the already-computed
  integrated alternative set to the one deterministically-chosen fixed
  site/scenario (module's own `select_fixed_reference_scenario()`,
  sorted by `(surface_site_id, resource_scenario_id)` -- DEC-015's own
  established "alternative_id/display order only, never a scientific
  decision" convention, applied here to choosing a reference
  deterministically rather than arbitrarily), re-decided via the SAME
  `decide()` over that subset. No separate evaluation pipeline: this
  baseline costs nothing extra to compute once the integrated set exists.

## Sensitivity (RA-SENS) -- perturbs stored figures, never re-simulates

Each `SensitivityCaseDefinition` perturbs each alternative's ALREADY-
COMPUTED `AnnualizedAlternativeEconomicResult` inputs (the captured
`CandidateEconomicResult`'s CAPEX for `connection_capex_multiplier`, or
each load state's own delivered-heat KPIs for
`geothermal_deliverable_heat_derating_fraction`) and re-calls
`economics.annualized_system_costing.compute_annualized_system_economics()`
-- never re-runs pandapipes or the HX coupling. This matches the spec's
own "small, deterministic what-if" framing: cheap, explicit, and never
probabilistic."""
from __future__ import annotations

from ..adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from ..adapter.heat_exchanger import HeatExchangerCouplingFailure
from ..contracts.coupling_result import PyDoubletCouplingResult
from ..data_contracts.joint_study import DecisionPolicy, GeothermalResourceScenario, SiteEconomicInputs
from ..data_contracts.joint_study_synthetic_v2 import apply_synthetic_derivation
from ..data_contracts.research_experiment import (
    AnnualizedAlternativeEconomicResult,
    BaselineComparisonResult,
    ComparisonInterpretationCode,
    LoadStatePerformanceResult,
    ResearchExperimentDecisionSummary,
    RobustnessClassification,
    SensitivityCaseDefinition,
    SensitivityCaseResult,
    SensitivityFactorName,
)
from ..decision.joint_policy import AlternativeObjectiveValues, decide
from ..economics.annualized_system_costing import compute_annualized_system_economics
from ..economics.annuity import annuity_factor
from ..economics.assumptions import EconomicAssumptions
from ..economics.costing import CandidateEconomicResult

ANNUALIZED_LCOH_OBJECTIVE_NAME = "annualized_system_lcoh_eur_per_mwh"


def _scenario_doublet_capex_eur(economic_inputs: SiteEconomicInputs) -> float:
    """Independently reimplemented from economics.joint_costing's identically
    -named PRIVATE helper -- this project's established convention (see
    economics.annuity's own module docstring) is to reuse PUBLIC cross-module
    functions but reimplement another module's private helper shape rather
    than import it."""
    if economic_inputs.doublet_capex_eur is not None:
        return economic_inputs.doublet_capex_eur
    components = [
        economic_inputs.drilling_producer_well_capex_eur, economic_inputs.drilling_injector_well_capex_eur,
        economic_inputs.well_completion_capex_eur, economic_inputs.surface_plant_capex_eur,
        economic_inputs.contingency_capex_eur,
    ]
    return sum(c for c in components if c is not None)


# ── Integrated decision (reuse, unchanged) ───────────────────────────────────

def build_alternative_objective_values(
    alternative_id: str, annualized: AnnualizedAlternativeEconomicResult,
) -> AlternativeObjectiveValues | None:
    """None when `annualized.computable` is False -- an infeasible-at-some-
    load-state alternative contributes no objective value and is simply
    absent from the decision input, matching `decide()`'s own precondition
    (DEC-010: "only ever called with already-feasible alternatives'
    objective values")."""
    if not annualized.computable:
        return None
    return AlternativeObjectiveValues(
        alternative_id=alternative_id,
        values={ANNUALIZED_LCOH_OBJECTIVE_NAME: annualized.annualized_system_lcoh_eur_per_mwh},
    )


def decide_integrated(
    annualized_by_alternative_id: dict[str, AnnualizedAlternativeEconomicResult], policy: DecisionPolicy,
):
    """Thin wrapper around the EXISTING, unmodified `decision.joint_policy.decide()`."""
    values = [
        v for v in (
            build_alternative_objective_values(aid, a) for aid, a in annualized_by_alternative_id.items()
        ) if v is not None
    ]
    return decide(values, policy)


# ── Geothermal-only baseline (RA-BASE, new narrowly-scoped formula) ──────────

def compute_geothermal_only_lcoh_eur_per_mwh(
    scenario: GeothermalResourceScenario, golden: PyDoubletCouplingResult, *,
    coupling_assumptions: CouplingAssumptions, base_assumptions: EconomicAssumptions,
) -> float | None:
    """Source-side LCOH at the HX boundary only -- no connection-pipe or
    DH-network cost at all (module docstring). Returns None when this
    scenario's own HX coupling is infeasible (e.g.
    HX_SUPPLY_TEMPERATURE_INFEASIBLE): a scenario that cannot even clear its
    own HX boundary has no geothermal-only LCOH to report, never a zero or
    an invented value."""
    coupling_input = apply_synthetic_derivation(golden, scenario.derivation)
    coupling_boundary = evaluate_heat_exchanger_coupling(coupling_input, assumptions=coupling_assumptions)
    if isinstance(coupling_boundary, HeatExchangerCouplingFailure):
        return None

    capex_doublet = _scenario_doublet_capex_eur(scenario.economic_inputs)
    capex_hx = base_assumptions.heat_exchanger_capex_eur
    a_doublet = annuity_factor(base_assumptions.interest_rate_real, base_assumptions.doublet_lifetime_years)
    a_hx = annuity_factor(base_assumptions.interest_rate_real, base_assumptions.heat_exchanger_lifetime_years)
    annuity_capital = capex_doublet * a_doublet + capex_hx * a_hx
    opex_fixed = base_assumptions.fixed_om_fraction_of_capex_per_a * (capex_doublet + capex_hx)

    doublet_pump_kw = coupling_input.doublet_pump_electric_power_kw.value
    opex_doublet_pump = (
        doublet_pump_kw * base_assumptions.annual_full_load_hours * base_assumptions.electricity_price_eur_per_kwh
    )
    total_cost = annuity_capital + opex_fixed + opex_doublet_pump

    useful_mwh = (
        coupling_boundary.deliverable_geothermal_heat_kw.value * base_assumptions.annual_full_load_hours
    ) / 1000.0
    if useful_mwh <= 0:
        return None
    return total_cost / useful_mwh


def select_fixed_reference_scenario(
    scenarios: list[GeothermalResourceScenario],
) -> GeothermalResourceScenario | None:
    """Deterministic, documented choice for the network-only baseline's ONE
    fixed geothermal source/site (DEC-015's own "display/selection order is
    never a scientific decision" convention, applied to picking a reference
    rather than to ranking): sorted by (surface_site_id, resource_scenario_id),
    first wins. None when `scenarios` is empty."""
    if not scenarios:
        return None
    return min(scenarios, key=lambda s: (s.site_id, s.scenario_id))


def rank_geothermal_only_baseline(
    scenarios: list[GeothermalResourceScenario], golden: PyDoubletCouplingResult, *,
    coupling_assumptions: CouplingAssumptions, base_assumptions: EconomicAssumptions,
) -> tuple[str | None, bool, dict[str, float]]:
    """Returns (preferred_site_id | None, has_any_rankable, lcoh_by_site_id).
    `has_any_rankable` is True iff at least one scenario cleared its own HX
    boundary (`lcoh_by_site` non-empty); `preferred_site_id` is additionally
    None when `has_any_rankable` is True but more than one site exactly ties
    at the minimum LCOH -- these two null-but-different states are why both
    values are returned rather than folding "no unique preference" and "no
    rankable site at all" into one flag. One scenario per site is assumed
    (this prototype's committed fixture); if a site has more than one
    scenario, the LOWEST-LCOH scenario represents that site. Ties (multiple
    sites at the minimum) make `preferred_site_id` None -- no arbitrary
    tie-break is invented (mirrors DEC-011's own "materially tied" spirit,
    applied here as an exact-tie check since no materiality threshold is
    declared for this baseline)."""
    lcoh_by_site: dict[str, float] = {}
    for scenario in scenarios:
        lcoh = compute_geothermal_only_lcoh_eur_per_mwh(
            scenario, golden, coupling_assumptions=coupling_assumptions, base_assumptions=base_assumptions,
        )
        if lcoh is None:
            continue
        if scenario.site_id not in lcoh_by_site or lcoh < lcoh_by_site[scenario.site_id]:
            lcoh_by_site[scenario.site_id] = lcoh

    if not lcoh_by_site:
        return None, False, {}
    best_lcoh = min(lcoh_by_site.values())
    best_sites = sorted(site_id for site_id, lcoh in lcoh_by_site.items() if lcoh == best_lcoh)
    preferred = best_sites[0] if len(best_sites) == 1 else None
    return preferred, True, lcoh_by_site


# ── Network-only, fixed-source baseline (filters the integrated set) ────────

def rank_network_only_baseline(
    annualized_by_alternative_id: dict[str, AnnualizedAlternativeEconomicResult],
    alternative_attachment_by_id: dict[str, str],
    alternative_resource_scenario_by_id: dict[str, str],
    fixed_resource_scenario_id: str,
    policy: DecisionPolicy,
) -> tuple[str | None, bool, dict[str, AnnualizedAlternativeEconomicResult]]:
    """Returns (preferred_attachment_id | None, has_any_rankable, the filtered
    subset). Filters the already-computed integrated alternative set to
    those whose resource_scenario_id matches the fixed reference scenario,
    then re-decides via the SAME decide() over that subset. `has_any_rankable`
    is True iff at least one alternative in that subset is `computable`
    (distinct from `preferred_attachment_id is None`, which can also mean
    "computable but materially tied" -- same two-flag reasoning as
    rank_geothermal_only_baseline's own docstring)."""
    subset = {
        aid: a for aid, a in annualized_by_alternative_id.items()
        if alternative_resource_scenario_by_id.get(aid) == fixed_resource_scenario_id
    }
    has_any_rankable = any(a.computable for a in subset.values())
    if not has_any_rankable:
        return None, False, subset
    decision = decide_integrated(subset, policy)
    if decision.preferred_alternative_id is None:
        return None, True, subset
    return alternative_attachment_by_id[decision.preferred_alternative_id], True, subset


# ── Cross-baseline comparison (RA-BASE) ──────────────────────────────────────

def compare_baselines(
    *,
    integrated_preferred_alternative_id: str | None,
    integrated_has_any_feasible: bool,
    integrated_site_by_alternative_id: dict[str, str],
    integrated_attachment_by_alternative_id: dict[str, str],
    geothermal_only_preferred_site_id: str | None,
    geothermal_only_has_any_rankable: bool,
    network_only_preferred_attachment_id: str | None,
    network_only_has_any_rankable: bool,
) -> BaselineComparisonResult:
    """Deterministic SET-based comparison (never a first-tied-element
    comparison): each of the three baselines contributes exactly one
    preferred identifier (or None), compared by equality. Uniqueness is
    read directly off each `*_preferred_*_id is None` (given its paired
    `has_any_rankable`/`has_any_feasible` flag is True) -- a separate
    "is_unique" flag would be redundant with that, since every baseline's
    own ranking function already returns None exactly when no unique
    preference exists."""
    if not integrated_has_any_feasible:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.NO_FEASIBLE_INTEGRATED_ALTERNATIVE,
            geothermal_only_preferred_site_id=geothermal_only_preferred_site_id,
            network_only_preferred_attachment_id=network_only_preferred_attachment_id,
            integrated_preferred_alternative_id=None,
            explanation="no compatible alternative in the integrated search space was computable "
                        "(every load state feasible) -- there is nothing to compare against either baseline",
        )
    if not geothermal_only_has_any_rankable or not network_only_has_any_rankable:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.BASELINE_NOT_RANKABLE,
            geothermal_only_preferred_site_id=geothermal_only_preferred_site_id,
            network_only_preferred_attachment_id=network_only_preferred_attachment_id,
            integrated_preferred_alternative_id=integrated_preferred_alternative_id,
            explanation="the geothermal-only or network-only baseline had no rankable candidate "
                        "(e.g. every scenario failed its own HX boundary, or the fixed reference "
                        "scenario had no feasible attachment) -- a comparison would be meaningless",
        )
    if (
        integrated_preferred_alternative_id is None
        or geothermal_only_preferred_site_id is None
        or network_only_preferred_attachment_id is None
    ):
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON,
            geothermal_only_preferred_site_id=geothermal_only_preferred_site_id,
            network_only_preferred_attachment_id=network_only_preferred_attachment_id,
            integrated_preferred_alternative_id=integrated_preferred_alternative_id,
            explanation="at least one of the three baselines has no single unique preferred choice "
                        "(a materially-tied or exactly-tied top group) -- no unique cross-baseline "
                        "comparison can be made",
        )

    integrated_site = integrated_site_by_alternative_id[integrated_preferred_alternative_id]
    integrated_attachment = integrated_attachment_by_alternative_id[integrated_preferred_alternative_id]
    site_matches = integrated_site == geothermal_only_preferred_site_id
    attachment_matches = integrated_attachment == network_only_preferred_attachment_id

    if site_matches and attachment_matches:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.INTEGRATED_MATCHES_BOTH_BASELINES,
            geothermal_only_preferred_site_id=geothermal_only_preferred_site_id,
            network_only_preferred_attachment_id=network_only_preferred_attachment_id,
            integrated_preferred_alternative_id=integrated_preferred_alternative_id,
            explanation="the integrated preferred alternative's site and attachment both match the "
                        "geothermal-only and network-only baselines' own preferred choices",
        )
    if not site_matches:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.INTEGRATED_SITE_DIFFERS_FROM_GEO_ONLY,
            geothermal_only_preferred_site_id=geothermal_only_preferred_site_id,
            network_only_preferred_attachment_id=network_only_preferred_attachment_id,
            integrated_preferred_alternative_id=integrated_preferred_alternative_id,
            explanation=f"the integrated preferred alternative's site ({integrated_site!r}) differs from "
                        f"the geothermal-only baseline's preferred site ({geothermal_only_preferred_site_id!r})",
        )
    return BaselineComparisonResult(
        interpretation_code=ComparisonInterpretationCode.INTEGRATED_ATTACHMENT_DIFFERS_FROM_NETWORK_ONLY,
        geothermal_only_preferred_site_id=geothermal_only_preferred_site_id,
        network_only_preferred_attachment_id=network_only_preferred_attachment_id,
        integrated_preferred_alternative_id=integrated_preferred_alternative_id,
        explanation=f"the integrated preferred alternative's site matches the geothermal-only baseline, "
                    f"but its attachment ({integrated_attachment!r}) differs from the network-only "
                    f"baseline's preferred attachment ({network_only_preferred_attachment_id!r})",
    )


# ── Sensitivity / robustness (RA-SENS) ───────────────────────────────────────

def _apply_sensitivity_case(
    annualized: AnnualizedAlternativeEconomicResult,
    representative_capex_economics: CandidateEconomicResult | None,
    case: SensitivityCaseDefinition,
    *,
    assumptions: EconomicAssumptions,
) -> AnnualizedAlternativeEconomicResult:
    """Perturbs already-computed inputs and re-calls
    economics.annualized_system_costing.compute_annualized_system_economics()
    -- never re-runs pandapipes or the HX coupling (module docstring)."""
    if not annualized.computable or representative_capex_economics is None:
        return annualized

    if case.factor_name == SensitivityFactorName.CONNECTION_CAPEX_MULTIPLIER:
        perturbed_capex = representative_capex_economics.model_copy(update={
            "capex_connection_pipes_eur": representative_capex_economics.capex_connection_pipes_eur * case.multiplier,
        })
        return compute_annualized_system_economics(
            annualized.alternative_id, annualized.load_state_results, perturbed_capex, assumptions=assumptions,
        )

    # GEOTHERMAL_DELIVERABLE_HEAT_DERATING_FRACTION: derate each load state's
    # own injected geothermal heat; auxiliary heat rises to cover exactly the
    # shortfall so total_heat_delivered_kw (fixed by consumer demand) is
    # unchanged -- geothermal_curtailed_heat_kw is untouched (curtailment is
    # about excess above what is usable, unrelated to a derating of the
    # delivered fraction).
    perturbed_states: list[LoadStatePerformanceResult] = []
    for state in annualized.load_state_results:
        derated_injected = state.geothermal_injected_heat_kw * case.multiplier
        shortfall = state.geothermal_injected_heat_kw - derated_injected
        perturbed_states.append(state.model_copy(update={
            "geothermal_injected_heat_kw": derated_injected,
            "auxiliary_heat_kw": state.auxiliary_heat_kw + shortfall,
        }))
    return compute_annualized_system_economics(
        annualized.alternative_id, perturbed_states, representative_capex_economics, assumptions=assumptions,
    )


def run_sensitivity_study(
    annualized_by_alternative_id: dict[str, AnnualizedAlternativeEconomicResult],
    representative_capex_economics_by_alternative_id: dict[str, CandidateEconomicResult | None],
    sensitivity_cases: list[SensitivityCaseDefinition],
    policy: DecisionPolicy,
    *,
    assumptions: EconomicAssumptions,
    base_case_preferred_alternative_id: str | None,
    site_by_alternative_id: dict[str, str],
    attachment_by_alternative_id: dict[str, str],
) -> ResearchExperimentDecisionSummary:
    """`base_case_preferred_alternative_id` is None exactly when the
    unperturbed (base) integrated decision has no unique winner -- the same
    "None means not unique" convention every ranking function in this module
    uses, so no separate uniqueness flag is needed here either."""
    case_results: list[SensitivityCaseResult] = []
    for case in sensitivity_cases:
        perturbed = {
            aid: _apply_sensitivity_case(
                a, representative_capex_economics_by_alternative_id.get(aid), case, assumptions=assumptions,
            )
            for aid, a in annualized_by_alternative_id.items()
        }
        decision = decide_integrated(perturbed, policy)
        preferred = decision.preferred_alternative_id
        case_results.append(SensitivityCaseResult(
            case_id=case.case_id, preferred_alternative_id=preferred,
            preferred_site_id=site_by_alternative_id.get(preferred) if preferred is not None else None,
            preferred_attachment_id=attachment_by_alternative_id.get(preferred) if preferred is not None else None,
        ))

    if base_case_preferred_alternative_id is None:
        return ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=None, sensitivity_case_results=case_results,
            robustness_classification=RobustnessClassification.NO_UNIQUE_BASE_WINNER,
            explanation="the base (unperturbed) case has no single unique preferred alternative -- "
                        "robustness cannot be classified relative to a winner that does not exist",
        )
    if not case_results:
        return ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=base_case_preferred_alternative_id, sensitivity_case_results=[],
            robustness_classification=RobustnessClassification.INSUFFICIENT_FEASIBLE_CASES,
            explanation="no sensitivity cases were declared -- nothing to classify",
        )
    if any(r.preferred_alternative_id is None for r in case_results):
        return ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=base_case_preferred_alternative_id, sensitivity_case_results=case_results,
            robustness_classification=RobustnessClassification.INSUFFICIENT_FEASIBLE_CASES,
            explanation="one or more sensitivity cases had no unique preferred alternative to compare",
        )

    base_site = site_by_alternative_id[base_case_preferred_alternative_id]
    base_attachment = attachment_by_alternative_id[base_case_preferred_alternative_id]
    alternative_unchanged = [r.preferred_alternative_id == base_case_preferred_alternative_id for r in case_results]

    if all(alternative_unchanged):
        classification = RobustnessClassification.ROBUST_OVER_TESTED_RANGE
        explanation = f"{base_case_preferred_alternative_id!r} remains preferred across every tested sensitivity case"
    else:
        site_always_matches = all(r.preferred_site_id == base_site for r in case_results)
        attachment_always_matches = all(r.preferred_attachment_id == base_attachment for r in case_results)
        changed_cases = [r.case_id for r, ok in zip(case_results, alternative_unchanged) if not ok]
        if site_always_matches and not attachment_always_matches:
            classification = RobustnessClassification.ROBUST_SITE_BUT_CONNECTION_SENSITIVE
            explanation = (
                f"the preferred SITE ({base_site!r}) is unchanged across every tested case, but the preferred "
                f"connection (attachment/route/design) changed under case(s) {changed_cases}"
            )
        elif attachment_always_matches and not site_always_matches:
            classification = RobustnessClassification.ROBUST_CONNECTION_BUT_SITE_SENSITIVE
            explanation = (
                f"the preferred connection (attachment {base_attachment!r}) is unchanged across every tested "
                f"case, but the preferred SITE changed under case(s) {changed_cases}"
            )
        else:
            classification = RobustnessClassification.ASSUMPTION_SENSITIVE
            explanation = (
                f"the preferred alternative changed under sensitivity case(s) {changed_cases}, with neither the "
                f"site nor the connection choice staying fixed on its own -- the base-case preference is not "
                f"robust to every tested synthetic assumption perturbation"
            )

    return ResearchExperimentDecisionSummary(
        base_case_preferred_alternative_id=base_case_preferred_alternative_id, sensitivity_case_results=case_results,
        robustness_classification=classification, explanation=explanation,
    )
