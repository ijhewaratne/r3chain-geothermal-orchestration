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

## Second conformance round -- rank-1 SET semantics (this module's own second edit)

A closer re-read of the spec's own §10-14 (against the actual committed v2
fixture, which genuinely has two resource scenarios on one site --
`scenario_alpha_golden`/`scenario_alpha_reduced_flow`, both `site_alpha`)
found this module's first implementation collapsed the geothermal-only
baseline to one best-site value (explicitly forbidden: "do not silently
collapse multiple scenarios at one site into one best-site value"),
auto-selected the network-only reference instead of using a declared
config value, compared single winner IDs instead of rank-1 SETS, and could
never produce `INTEGRATED_DIFFERS_FROM_BOTH`. All four are corrected here:

- **Geothermal-only** now ranks SCENARIOS (not sites) via the SAME
  materiality-aware `decide()` every other baseline already uses -- a
  throwaway `DecisionPolicy` is constructed from the config's own declared
  `GeothermalOnlyBaselinePolicy.objective`, then `decide()` is called
  unchanged. The site set is DERIVED from the resulting rank-1 scenario
  group, never computed directly.
- **Network-only** now uses the config's own DECLARED
  `NetworkOnlyBaselinePolicy.reference_site_id`/`reference_resource_scenario_id`
  (validated by the orchestrator against the referenced v2 package before
  this module ever runs) -- `select_fixed_reference_scenario()` is removed.
- **`compare_baselines()`** now takes rank-1 SETS (already derived by the
  orchestrator from each baseline's own `JointDecisionResult
  .ranked_alternative_groups[0]`) and computes disjointness directly,
  checking BOTH site and attachment before deciding which interpretation
  code applies -- fixing the unreachable-`INTEGRATED_DIFFERS_FROM_BOTH`
  defect directly.
- **Sensitivity** now records each case's own rank-1 group (site/attachment
  sets derived the same way) plus which alternatives became newly
  infeasible, not merely a single winner.

## Third conformance round -- eligible-attachment filter + rank-change metric

Two further gaps found by direct code inspection (never assumed correct
merely because a prior round claimed the layer complete):

- `NetworkOnlyBaselinePolicy.eligible_attachment_ids` was declared in the
  contract but never referenced anywhere in this module (a documentation-
  only field). `rank_network_only_baseline()` now takes
  `alternative_attachment_by_id`/`eligible_attachment_ids` and genuinely
  filters the network-only subset by attachment membership when declared
  (`None` still means "use every eligible attachment," matching this
  project's established null-means-unrestricted filter convention). This
  filter applies ONLY to the network-only baseline's own subset -- the
  INTEGRATED search (`decide_integrated()`) is never passed this filter and
  its own universe is unaffected.
- `CandidateRankSensitivity`/`_compute_candidate_rank_sensitivity()` add the
  spec's own §14.3 "maximum observed rank change for each base candidate"
  metric, plus the symmetric "restored to feasibility" case item H asks for
  -- computed purely from each already-computed `JointDecisionResult`'s own
  `ranked_alternative_groups` (via `_rank_index_by_alternative_id()`), never
  a re-derived ranking or new simulation."""
from __future__ import annotations

from ..adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from ..adapter.heat_exchanger import HeatExchangerCouplingFailure
from ..contracts.coupling_result import PyDoubletCouplingResult
from ..data_contracts.joint_study import (
    DecisionPolicy,
    DecisionPolicyMode,
    GeothermalResourceScenario,
    SiteEconomicInputs,
)
from ..data_contracts.joint_study_synthetic_v2 import apply_synthetic_derivation
from ..data_contracts.research_experiment import (
    AnnualizedAlternativeEconomicResult,
    BaselineComparisonResult,
    CandidateRankSensitivity,
    ComparisonInterpretationCode,
    GeothermalOnlyBaselinePolicy,
    LoadStatePerformanceResult,
    ResearchExperimentDecisionSummary,
    RobustnessClassification,
    SensitivityCaseDefinition,
    SensitivityCaseResult,
    SensitivityFactorName,
)
from ..decision.joint_policy import AlternativeObjectiveValues, JointDecisionResult, decide
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


def _rank1_group(decision: JointDecisionResult) -> list[str]:
    """The rank-1 alternative group under primary_objective_ranking mode --
    empty when there is nothing computable at all. Never the pareto
    shortlist (a different, secondary diagnostic) and never a single
    first-tied-element pick."""
    return list(decision.ranked_alternative_groups[0]) if decision.ranked_alternative_groups else []


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
) -> JointDecisionResult:
    """Thin wrapper around the EXISTING, unmodified `decision.joint_policy.decide()`."""
    values = [
        v for v in (
            build_alternative_objective_values(aid, a) for aid, a in annualized_by_alternative_id.items()
        ) if v is not None
    ]
    return decide(values, policy)


# ── Geothermal-only baseline (RA-BASE) -- ranks SCENARIOS, never sites ───────

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


def rank_geothermal_only_baseline(
    scenarios: list[GeothermalResourceScenario], golden: PyDoubletCouplingResult, *,
    coupling_assumptions: CouplingAssumptions, base_assumptions: EconomicAssumptions,
    policy: GeothermalOnlyBaselinePolicy,
) -> tuple[JointDecisionResult, bool, dict[str, float]]:
    """Returns (decision, has_any_rankable, lcoh_by_scenario_id). Ranks
    SCENARIOS (spec §10.2: "do not silently collapse multiple scenarios at
    one site into one best-site value") via the SAME materiality-aware
    `decide()` every baseline in this project already uses -- a throwaway
    `DecisionPolicy` is built from `policy.objective` (this baseline's own
    declared metric/materiality), never a new ranking algorithm. The caller
    derives the rank-1 SITE set from `decision.ranked_alternative_groups[0]`
    (each id there is a scenario_id) plus its own scenario->site map --
    this function never computes a site-level value itself.
    `resource_scenario_ids` (when declared) restricts which scenarios are
    even considered eligible."""
    eligible = (
        scenarios if policy.resource_scenario_ids is None
        else [s for s in scenarios if s.scenario_id in set(policy.resource_scenario_ids)]
    )
    lcoh_by_scenario: dict[str, float] = {}
    for scenario in eligible:
        lcoh = compute_geothermal_only_lcoh_eur_per_mwh(
            scenario, golden, coupling_assumptions=coupling_assumptions, base_assumptions=base_assumptions,
        )
        if lcoh is not None:
            lcoh_by_scenario[scenario.scenario_id] = lcoh

    if not lcoh_by_scenario:
        empty_decision = decide([], DecisionPolicy(
            mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[policy.objective],
            primary_objective=policy.objective.name, tie_breakers=[], allow_shared_rank=True,
        ))
        return empty_decision, False, {}

    scenario_policy = DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[policy.objective],
        primary_objective=policy.objective.name, tie_breakers=[], allow_shared_rank=True,
    )
    values = [
        AlternativeObjectiveValues(alternative_id=scenario_id, values={policy.objective.name: lcoh})
        for scenario_id, lcoh in lcoh_by_scenario.items()
    ]
    decision = decide(values, scenario_policy)
    return decision, True, lcoh_by_scenario


# ── Network-only, fixed-source baseline (filters the integrated set) ────────

def rank_network_only_baseline(
    annualized_by_alternative_id: dict[str, AnnualizedAlternativeEconomicResult],
    alternative_resource_scenario_by_id: dict[str, str],
    fixed_resource_scenario_id: str,
    policy: DecisionPolicy,
    *,
    alternative_attachment_by_id: dict[str, str],
    eligible_attachment_ids: list[str] | None = None,
) -> tuple[JointDecisionResult, bool, dict[str, AnnualizedAlternativeEconomicResult]]:
    """Returns (decision, has_any_rankable, the filtered subset). Filters the
    already-computed INTEGRATED alternative set (never mutating or
    restricting it -- this function only ever builds a NEW, separate `subset`
    dict; the caller's own `annualized_by_alternative_id` and any integrated
    decision built from it are completely unaffected) to those whose
    resource_scenario_id matches the DECLARED fixed reference scenario
    (`data_contracts.research_experiment.NetworkOnlyBaselinePolicy
    .reference_resource_scenario_id`, validated by the orchestrator against
    the referenced v2 package before this function is ever called -- this
    function itself does not re-validate that), AND -- when declared --
    whose attachment_id is one of `eligible_attachment_ids`
    (`NetworkOnlyBaselinePolicy`'s own filter; `None` means every attachment
    compatible with the reference site/scenario is eligible, matching this
    project's established "null means unrestricted" convention). Re-decides
    via the SAME `decide()` over that subset. The caller derives the rank-1
    ATTACHMENT set from `decision.ranked_alternative_groups[0]` plus its own
    alternative->attachment map."""
    subset = {
        aid: a for aid, a in annualized_by_alternative_id.items()
        if alternative_resource_scenario_by_id.get(aid) == fixed_resource_scenario_id
        and (eligible_attachment_ids is None or alternative_attachment_by_id.get(aid) in set(eligible_attachment_ids))
    }
    has_any_rankable = any(a.computable for a in subset.values())
    decision = decide_integrated(subset, policy)
    return decision, has_any_rankable, subset


# ── Cross-baseline comparison (RA-BASE) ──────────────────────────────────────

def compare_baselines(
    *,
    integrated_has_any_feasible: bool,
    integrated_decision: JointDecisionResult,
    integrated_site_by_alternative_id: dict[str, str],
    integrated_attachment_by_alternative_id: dict[str, str],
    geothermal_only_has_any_rankable: bool,
    geothermal_only_decision: JointDecisionResult,
    scenario_site_by_id: dict[str, str],
    network_only_has_any_rankable: bool,
    network_only_decision: JointDecisionResult,
    network_only_attachment_by_alternative_id: dict[str, str],
) -> BaselineComparisonResult:
    """Genuinely SET-based (spec §13: "compare sets, not arbitrary first
    elements of tied groups") -- every rank-1 group here is derived from its
    own `JointDecisionResult.ranked_alternative_groups[0]`, and disjointness
    is computed directly between the resulting site/attachment sets. Checks
    BOTH site and attachment before choosing an interpretation code (fixing
    the prior implementation's unreachable INTEGRATED_DIFFERS_FROM_BOTH
    defect)."""
    if not integrated_has_any_feasible:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.NO_FEASIBLE_INTEGRATED_ALTERNATIVE,
            geothermal_only_best_scenario_ids=[], network_only_best_attachment_ids=[],
            integrated_best_alternative_ids=[], integrated_best_site_ids=[], integrated_best_attachment_ids=[],
            site_decision_changed_after_integration=None, attachment_decision_changed_after_integration=None,
            explanation="no compatible alternative in the integrated search space was computable "
                        "(every load state feasible) -- there is nothing to compare against either baseline",
        )

    integrated_rank1_alt_ids = sorted(_rank1_group(integrated_decision))
    integrated_rank1_site_ids = sorted({integrated_site_by_alternative_id[a] for a in integrated_rank1_alt_ids})
    integrated_rank1_attachment_ids = sorted({integrated_attachment_by_alternative_id[a] for a in integrated_rank1_alt_ids})

    if not geothermal_only_has_any_rankable or not network_only_has_any_rankable:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.BASELINE_NOT_RANKABLE,
            geothermal_only_best_scenario_ids=[], network_only_best_attachment_ids=[],
            integrated_best_alternative_ids=integrated_rank1_alt_ids,
            integrated_best_site_ids=integrated_rank1_site_ids,
            integrated_best_attachment_ids=integrated_rank1_attachment_ids,
            site_decision_changed_after_integration=None, attachment_decision_changed_after_integration=None,
            explanation="the geothermal-only or network-only baseline had no rankable candidate "
                        "(e.g. every scenario failed its own HX boundary, or the fixed reference "
                        "scenario had no feasible attachment) -- a comparison would be meaningless",
        )

    geo_rank1_scenario_ids = sorted(_rank1_group(geothermal_only_decision))
    geo_rank1_site_ids = {scenario_site_by_id[s] for s in geo_rank1_scenario_ids}
    network_rank1_alt_ids = _rank1_group(network_only_decision)
    network_rank1_attachment_ids = {network_only_attachment_by_alternative_id[a] for a in network_rank1_alt_ids}

    site_changed = set(integrated_rank1_site_ids).isdisjoint(geo_rank1_site_ids)
    attachment_changed = set(integrated_rank1_attachment_ids).isdisjoint(network_rank1_attachment_ids)

    common = dict(
        geothermal_only_best_scenario_ids=geo_rank1_scenario_ids,
        network_only_best_attachment_ids=sorted(network_rank1_attachment_ids),
        integrated_best_alternative_ids=integrated_rank1_alt_ids,
        integrated_best_site_ids=integrated_rank1_site_ids,
        integrated_best_attachment_ids=integrated_rank1_attachment_ids,
        site_decision_changed_after_integration=site_changed,
        attachment_decision_changed_after_integration=attachment_changed,
    )

    if site_changed and attachment_changed:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.INTEGRATED_DIFFERS_FROM_BOTH,
            explanation=f"the integrated rank-1 site set {integrated_rank1_site_ids} is disjoint from the "
                        f"geothermal-only rank-1 site set {sorted(geo_rank1_site_ids)}, AND the integrated "
                        f"rank-1 attachment set {integrated_rank1_attachment_ids} is disjoint from the "
                        f"network-only rank-1 attachment set {sorted(network_rank1_attachment_ids)}",
            **common,
        )
    if site_changed:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.INTEGRATED_SITE_DIFFERS_FROM_GEO_ONLY,
            explanation=f"the integrated rank-1 site set {integrated_rank1_site_ids} is disjoint from the "
                        f"geothermal-only rank-1 site set {sorted(geo_rank1_site_ids)} (attachment sets overlap)",
            **common,
        )
    if attachment_changed:
        return BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.INTEGRATED_ATTACHMENT_DIFFERS_FROM_NETWORK_ONLY,
            explanation=f"the integrated rank-1 attachment set {integrated_rank1_attachment_ids} is disjoint "
                        f"from the network-only rank-1 attachment set {sorted(network_rank1_attachment_ids)} "
                        f"(site sets overlap)",
            **common,
        )
    return BaselineComparisonResult(
        interpretation_code=ComparisonInterpretationCode.INTEGRATED_MATCHES_BOTH_BASELINES,
        explanation="the integrated rank-1 site and attachment sets both overlap their respective "
                    "geothermal-only and network-only baselines' own rank-1 sets",
        **common,
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

    # GEOTHERMAL_DELIVERABLE_HEAT_DERATING_FRACTION -- explicit honesty boundary
    # (spec item G): this path re-derives ECONOMICS only from already-computed
    # KPIs. It never re-runs pandapipes or the HX evaluator, so it structurally
    # cannot discover a new technical infeasibility (a candidate already
    # infeasible in the base case stays infeasible here; a candidate feasible
    # in the base case can never newly fail a hard gate under this
    # perturbation). Auxiliary heat rises to cover exactly the geothermal
    # shortfall, so total_heat_delivered_kw (fixed by consumer demand) is
    # unchanged and mass/energy balance is exact for every load state --
    # geothermal_curtailed_heat_kw is untouched (curtailment is about excess
    # above what is usable, unrelated to a derating of the delivered
    # fraction). The one documented simplification: dh_hydraulic_pumping_power_kw
    # is held at its base-case value rather than re-derived for the (slightly
    # smaller) actual injected geothermal mass flow under derating -- re-deriving
    # it would require re-running pandapipes per (case x load-state x
    # alternative), which this project's synthetic sensitivity design
    # deliberately does not do for ANY sensitivity case (see module docstring).
    # This sensitivity therefore represents a synthetic geothermal-availability
    # what-if on the ECONOMIC boundary, not a re-evaluated hydraulic/thermal
    # state, a geological exploration-risk model, or a new PyDoublet simulation.
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


def _rank_index_by_alternative_id(decision: JointDecisionResult) -> dict[str, int]:
    """1-based rank-GROUP index per computable alternative (rank 1 = the
    first/best group) -- reads `decide()`'s own already-computed
    `ranked_alternative_groups` verbatim, never a re-derived ranking."""
    return {
        aid: rank_index + 1
        for rank_index, group in enumerate(decision.ranked_alternative_groups)
        for aid in group
    }


def _compute_candidate_rank_sensitivity(
    all_alternative_ids: set[str], base_rank_by_id: dict[str, int], case_rank_by_id_list: list[dict[str, int]],
) -> list[CandidateRankSensitivity]:
    """spec §14.3's "maximum observed rank change for each base candidate" --
    computed over every candidate ever evaluated (not only those ranked in
    the base case), so a candidate that only appears under a perturbation is
    still reported (`restored_to_feasibility_in_any_case`)."""
    results: list[CandidateRankSensitivity] = []
    for aid in sorted(all_alternative_ids):
        base_rank = base_rank_by_id.get(aid)
        rank_changes: list[int] = []
        became_infeasible = False
        restored = False
        for case_rank_by_id in case_rank_by_id_list:
            case_rank = case_rank_by_id.get(aid)
            if base_rank is not None and case_rank is None:
                became_infeasible = True
            elif base_rank is None and case_rank is not None:
                restored = True
            elif base_rank is not None and case_rank is not None:
                rank_changes.append(abs(case_rank - base_rank))
        results.append(CandidateRankSensitivity(
            alternative_id=aid, base_rank=base_rank,
            max_rank_change=max(rank_changes) if rank_changes else None,
            became_infeasible_in_any_case=became_infeasible, restored_to_feasibility_in_any_case=restored,
        ))
    return results


def run_sensitivity_study(
    annualized_by_alternative_id: dict[str, AnnualizedAlternativeEconomicResult],
    representative_capex_economics_by_alternative_id: dict[str, CandidateEconomicResult | None],
    sensitivity_cases: list[SensitivityCaseDefinition],
    policy: DecisionPolicy,
    *,
    assumptions: EconomicAssumptions,
    base_case_decision: JointDecisionResult,
    site_by_alternative_id: dict[str, str],
    attachment_by_alternative_id: dict[str, str],
) -> ResearchExperimentDecisionSummary:
    """Each `SensitivityCaseResult` now carries its own rank-1 GROUP (spec
    §14.3: "rank-1 group for every sensitivity case"), the sites/attachments
    it represents, and which alternatives became newly infeasible under that
    perturbation -- not merely a single winner. Robustness classification
    uses set OVERLAP (not exact-group equality) against the base case's own
    rank-1 site/attachment sets, mirroring `compare_baselines()`'s own
    disjointness convention exactly. `candidate_rank_sensitivity` (spec
    §14.3's own "maximum observed rank change for each base candidate")
    is computed for every candidate ever evaluated, on EVERY return path --
    it never depends on a unique base winner existing, since rank movement
    is meaningful even when the base case itself is tied."""
    base_rank1_alt_ids = _rank1_group(base_case_decision)
    base_case_preferred_alternative_id = base_rank1_alt_ids[0] if len(base_rank1_alt_ids) == 1 else None
    base_rank1_site_ids = {site_by_alternative_id[a] for a in base_rank1_alt_ids}
    base_rank1_attachment_ids = {attachment_by_alternative_id[a] for a in base_rank1_alt_ids}
    base_computable_ids = {aid for aid, a in annualized_by_alternative_id.items() if a.computable}
    base_rank_by_id = _rank_index_by_alternative_id(base_case_decision)

    case_results: list[SensitivityCaseResult] = []
    case_rank_by_id_list: list[dict[str, int]] = []
    for case in sensitivity_cases:
        perturbed = {
            aid: _apply_sensitivity_case(
                a, representative_capex_economics_by_alternative_id.get(aid), case, assumptions=assumptions,
            )
            for aid, a in annualized_by_alternative_id.items()
        }
        decision = decide_integrated(perturbed, policy)
        case_rank_by_id_list.append(_rank_index_by_alternative_id(decision))
        rank1_alt_ids = sorted(_rank1_group(decision))
        rank1_site_ids = sorted({site_by_alternative_id[a] for a in rank1_alt_ids})
        rank1_attachment_ids = sorted({attachment_by_alternative_id[a] for a in rank1_alt_ids})
        perturbed_computable_ids = {aid for aid, a in perturbed.items() if a.computable}
        newly_infeasible = sorted(base_computable_ids - perturbed_computable_ids)
        case_results.append(SensitivityCaseResult(
            case_id=case.case_id, rank1_alternative_ids=rank1_alt_ids, rank1_site_ids=rank1_site_ids,
            rank1_attachment_ids=rank1_attachment_ids, newly_infeasible_alternative_ids=newly_infeasible,
            preferred_alternative_id=rank1_alt_ids[0] if len(rank1_alt_ids) == 1 else None,
        ))

    candidate_rank_sensitivity = _compute_candidate_rank_sensitivity(
        set(annualized_by_alternative_id.keys()), base_rank_by_id, case_rank_by_id_list,
    )

    if not base_rank1_alt_ids:
        return ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=None, sensitivity_case_results=case_results,
            candidate_rank_sensitivity=candidate_rank_sensitivity,
            robustness_classification=RobustnessClassification.NO_UNIQUE_BASE_WINNER,
            explanation="the base (unperturbed) case has no computable alternative at all -- "
                        "robustness cannot be classified relative to a winner that does not exist",
        )
    if base_case_preferred_alternative_id is None:
        return ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=None, sensitivity_case_results=case_results,
            candidate_rank_sensitivity=candidate_rank_sensitivity,
            robustness_classification=RobustnessClassification.NO_UNIQUE_BASE_WINNER,
            explanation="the base (unperturbed) case has no single unique preferred alternative -- "
                        "robustness cannot be classified relative to a winner that does not exist",
        )
    if not case_results:
        return ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=base_case_preferred_alternative_id, sensitivity_case_results=[],
            candidate_rank_sensitivity=candidate_rank_sensitivity,
            robustness_classification=RobustnessClassification.INSUFFICIENT_FEASIBLE_CASES,
            explanation="no sensitivity cases were declared -- nothing to classify",
        )
    if any(not r.rank1_alternative_ids for r in case_results):
        return ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=base_case_preferred_alternative_id, sensitivity_case_results=case_results,
            candidate_rank_sensitivity=candidate_rank_sensitivity,
            robustness_classification=RobustnessClassification.INSUFFICIENT_FEASIBLE_CASES,
            explanation="one or more sensitivity cases had no computable alternative at all",
        )

    alternative_unchanged = [
        set(r.rank1_alternative_ids) == set(base_rank1_alt_ids) for r in case_results
    ]
    if all(alternative_unchanged):
        classification = RobustnessClassification.ROBUST_OVER_TESTED_RANGE
        explanation = f"{base_case_preferred_alternative_id!r} remains preferred across every tested sensitivity case"
    else:
        site_always_overlaps = all(not base_rank1_site_ids.isdisjoint(r.rank1_site_ids) for r in case_results)
        attachment_always_overlaps = all(
            not base_rank1_attachment_ids.isdisjoint(r.rank1_attachment_ids) for r in case_results
        )
        changed_cases = [r.case_id for r, ok in zip(case_results, alternative_unchanged) if not ok]
        if site_always_overlaps and not attachment_always_overlaps:
            classification = RobustnessClassification.ROBUST_SITE_BUT_CONNECTION_SENSITIVE
            explanation = (
                f"the preferred SITE set ({sorted(base_rank1_site_ids)}) overlaps across every tested case, but "
                f"the preferred connection (attachment/route/design) changed under case(s) {changed_cases}"
            )
        elif attachment_always_overlaps and not site_always_overlaps:
            classification = RobustnessClassification.ROBUST_CONNECTION_BUT_SITE_SENSITIVE
            explanation = (
                f"the preferred connection (attachment set {sorted(base_rank1_attachment_ids)}) overlaps across "
                f"every tested case, but the preferred SITE changed under case(s) {changed_cases}"
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
        candidate_rank_sensitivity=candidate_rank_sensitivity,
        robustness_classification=classification, explanation=explanation,
    )
