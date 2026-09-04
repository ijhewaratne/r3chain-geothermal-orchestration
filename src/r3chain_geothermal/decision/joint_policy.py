"""Materiality-aware Pareto and optional primary-objective ranking (S14,
DEC-001..015, docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 4).

## No invented weights (DEC-001..003)

Objectives, directions, and materiality thresholds all come from the
study package's own `DecisionPolicy` (data_contracts.joint_study, Phase
1) -- this module never hard-codes a weight or threshold. Only the
non-duplicative default objective set S14.2 names has a registered data
source (`_OBJECTIVE_EXTRACTORS`); a `DecisionPolicy` naming any other
objective fails loudly (OP-003: never silently include an objective
with no data source) rather than guessing.

## Reuse, not reinvention

Every objective value is read from ALREADY-COMPUTED fields on the
existing `CandidateEvaluationResult`/`CandidateEconomicResult` types
(`network.candidate`, `economics.costing`) -- no KPI is recalculated
here. `total_pumping_electric_energy_mwh_per_a` (DEC-004: energy, not
cost, since cost is already inside LCOH) is derived from the ALREADY-
COMPUTED OPEX EUR figures divided by the SAME electricity price that
produced them (a unit conversion, not a new formula).

## Grouping simplification, stated plainly

`_group_by_materiality()` below groups values into materially-equivalent
CONTIGUOUS clusters after sorting (A~B and B~C implies A and C share a
group even if A and C alone would not test as materially equivalent).
This is a standard, deterministic approximation of a genuinely
non-transitive relation -- not claimed to be a formally exhaustive
equivalence-class computation.

## DEC-012 (sensitivity), scoped

A full sensitivity analysis (re-running the decision under perturbed
synthetic cost assumptions) is not implemented in this phase -- `
JointDecisionResult.synthetic_cost_sensitivity_caveat` states this
honestly whenever a single preferred alternative is returned, rather
than silently presenting one "winner" as if it were assumption-robust."""
from __future__ import annotations

from enum import Enum
from typing import Callable

from pydantic import BaseModel, ConfigDict

from ..data_contracts.joint_study import DecisionPolicy, DecisionPolicyMode, ObjectiveDefinition, ObjectiveDirection
from ..economics.costing import CandidateEconomicResult
from ..network import CandidateEvaluationResult

DECISION_CONTRACT_SCHEMA_VERSION: str = "1.0.0"
"""Versioned independently of every other layer's own contract schema."""


def _pumping_electric_energy_mwh_per_a(econ: CandidateEconomicResult) -> float:
    total_opex_eur_per_a = econ.opex_electricity_doublet_pump_eur_per_a + econ.opex_electricity_dh_pumping_eur_per_a
    price = econ.assumptions.electricity_price_eur_per_kwh
    if price <= 0:
        return 0.0
    return (total_opex_eur_per_a / price) / 1000.0


_OBJECTIVE_EXTRACTORS: dict[str, Callable[[CandidateEvaluationResult, CandidateEconomicResult], float]] = {
    "indicative_system_lcoh_eur_per_mwh": lambda cr, econ: econ.indicative_lcoh_eur_per_kwh * 1000.0,
    "geothermal_coverage_fraction": lambda cr, econ: cr.geothermal_coverage_fraction,
    "total_pumping_electric_energy_mwh_per_a": lambda cr, econ: _pumping_electric_energy_mwh_per_a(econ),
}
"""S14.2's own non-duplicative default objective set -- the only names
this module can compute a value for."""


class AlternativeObjectiveValues(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    alternative_id: str
    values: dict[str, float]


def compute_alternative_objective_values(
    alternative_id: str, candidate_result: CandidateEvaluationResult, economics: CandidateEconomicResult,
    objectives: list[ObjectiveDefinition],
) -> AlternativeObjectiveValues:
    values: dict[str, float] = {}
    for objective in objectives:
        extractor = _OBJECTIVE_EXTRACTORS.get(objective.name)
        if extractor is None:
            raise ValueError(
                f"objective {objective.name!r} has no registered data source in this prototype (OP-003: "
                "never include an objective whose data/source are absent) -- supported names: "
                f"{sorted(_OBJECTIVE_EXTRACTORS)}"
            )
        values[objective.name] = extractor(candidate_result, economics)
    return AlternativeObjectiveValues(alternative_id=alternative_id, values=values)


def _materially_equivalent(a: float, b: float, objective: ObjectiveDefinition) -> bool:
    """S14.3's formula: |a-b| <= max(eps_abs, eps_rel * max(|a|,|b|))."""
    return abs(a - b) <= max(objective.absolute_materiality, objective.relative_materiality_fraction * max(abs(a), abs(b)))


def _dominates(a: AlternativeObjectiveValues, b: AlternativeObjectiveValues, objectives: list[ObjectiveDefinition]) -> bool:
    """A dominates B only when A is no worse (materially) on every
    objective and materially better on at least one (S14.3)."""
    at_least_as_good = True
    strictly_better = False
    for objective in objectives:
        av, bv = a.values[objective.name], b.values[objective.name]
        if _materially_equivalent(av, bv, objective):
            continue
        a_better = (av < bv) if objective.direction == ObjectiveDirection.MINIMIZE else (av > bv)
        a_worse = (av > bv) if objective.direction == ObjectiveDirection.MINIMIZE else (av < bv)
        if a_worse:
            at_least_as_good = False
            break
        if a_better:
            strictly_better = True
    return at_least_as_good and strictly_better


def _explain_non_domination(
    alt: AlternativeObjectiveValues, others: list[AlternativeObjectiveValues], objectives: list[ObjectiveDefinition],
) -> str:
    """DEC-006/014: names the objective(s) this alternative is at least
    materially tied for best on -- never calls it "optimal" without
    naming a concrete objective."""
    strengths: list[str] = []
    for objective in objectives:
        this_v = alt.values[objective.name]
        best_or_tied = True
        for other in others:
            other_v = other.values[objective.name]
            if _materially_equivalent(this_v, other_v, objective):
                continue
            better = (this_v < other_v) if objective.direction == ObjectiveDirection.MINIMIZE else (this_v > other_v)
            if not better:
                best_or_tied = False
                break
        if best_or_tied:
            strengths.append(objective.name)
    if strengths:
        return f"not materially dominated -- among the best (or materially tied for best) on: {', '.join(strengths)}"
    return (
        "not materially dominated -- no other alternative is at least as good, within the configured "
        "materiality thresholds, on every considered objective simultaneously"
    )


def pareto_shortlist(
    alternatives: list[AlternativeObjectiveValues], objectives: list[ObjectiveDefinition],
) -> tuple[list[str], dict[str, str]]:
    """DEC-005/006: returns (non_dominated_alternative_ids, explanations).
    Deterministic: sorted by alternative_id; ties are never arbitrarily
    broken (DEC-015: alternative_id orders DISPLAY, never a scientific
    decision)."""
    if not alternatives:
        return [], {}
    by_id = {a.alternative_id: a for a in alternatives}
    ids = sorted(by_id)
    non_dominated = [
        aid for aid in ids
        if not any(_dominates(by_id[other], by_id[aid], objectives) for other in ids if other != aid)
    ]
    explanations = {
        aid: _explain_non_domination(by_id[aid], [by_id[o] for o in ids if o != aid], objectives)
        for aid in non_dominated
    }
    return non_dominated, explanations


def _group_by_materiality(
    ordered: list[AlternativeObjectiveValues], objective: ObjectiveDefinition,
) -> list[list[AlternativeObjectiveValues]]:
    """Module docstring's own stated simplification: contiguous
    materially-equivalent clustering against each group's own first
    (anchor) member, not a full pairwise equivalence-class computation."""
    groups: list[list[AlternativeObjectiveValues]] = []
    for value in ordered:
        if groups and _materially_equivalent(value.values[objective.name], groups[-1][0].values[objective.name], objective):
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups


def _order_group_for_display(
    group: list[AlternativeObjectiveValues], tie_breakers: list[str], objectives: list[ObjectiveDefinition],
) -> list[AlternativeObjectiveValues]:
    """DEC-007/011/015: declared tie-breakers set a deterministic DISPLAY
    order within a materially-tied rank group -- they never change which
    RANK the group as a whole receives (DEC-011: alternatives remaining
    materially tied after tie-breakers still share one rank).
    `alternative_id` is the final fallback key, ordering only, never a
    scientific tie-break (DEC-015)."""
    objectives_by_name = {o.name: o for o in objectives}

    def sort_key(value: AlternativeObjectiveValues) -> tuple:
        key: list[float | str] = []
        for name in tie_breakers:
            objective = objectives_by_name.get(name)
            if objective is None:
                continue
            raw = value.values.get(name)
            if raw is None:
                continue
            key.append(raw if objective.direction == ObjectiveDirection.MINIMIZE else -raw)
        key.append(value.alternative_id)
        return tuple(key)

    return sorted(group, key=sort_key)


def _rank_by_primary_objective(
    alternatives: list[AlternativeObjectiveValues], policy: DecisionPolicy,
) -> list[list[str]]:
    objectives_by_name = {o.name: o for o in policy.objectives}
    primary = objectives_by_name[policy.primary_objective]  # DecisionPolicy's own validator guarantees this exists
    reverse = primary.direction == ObjectiveDirection.MAXIMIZE
    ordered = sorted(alternatives, key=lambda v: v.values[primary.name], reverse=reverse)
    groups = _group_by_materiality(ordered, primary)
    return [
        [v.alternative_id for v in _order_group_for_display(group, policy.tie_breakers, policy.objectives)]
        for group in groups
    ]


class JointDecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_schema_version: str = DECISION_CONTRACT_SCHEMA_VERSION
    mode: DecisionPolicyMode
    pareto_shortlist_alternative_ids: list[str]
    pareto_explanations: dict[str, str]
    ranked_alternative_groups: list[list[str]]
    """Empty under pareto_only (DEC-008). Under primary_objective_ranking,
    one entry per rank, in rank order -- entry 0 is rank 1. A group with
    more than one member means those alternatives remain materially tied
    (DEC-011)."""
    preferred_alternative_id: str | None
    """Non-null ONLY when mode==primary_objective_ranking AND rank 1's
    own group has exactly one member (DEC-008/009, AC-J11)."""
    synthetic_cost_sensitivity_caveat: str | None


def decide(alternatives: list[AlternativeObjectiveValues], policy: DecisionPolicy) -> JointDecisionResult:
    """DEC-010: only ever called with already-feasible alternatives'
    objective values -- feasibility is the caller's own, separate,
    earlier concern (workflow.joint_evaluation), never re-derived here."""
    non_dominated, explanations = pareto_shortlist(alternatives, policy.objectives)

    if policy.mode == DecisionPolicyMode.PARETO_ONLY:
        return JointDecisionResult(
            mode=policy.mode, pareto_shortlist_alternative_ids=non_dominated, pareto_explanations=explanations,
            ranked_alternative_groups=[], preferred_alternative_id=None,
            synthetic_cost_sensitivity_caveat=None,
        )

    ranked_groups = _rank_by_primary_objective(alternatives, policy)
    preferred = ranked_groups[0][0] if ranked_groups and len(ranked_groups[0]) == 1 else None
    caveat = (
        "DEC-012: no sensitivity analysis was run against this prototype's synthetic, illustrative cost "
        "assumptions -- a different (still plausible) synthetic assumption set could change which "
        "alternative ranks first. This preferred_alternative_id is not claimed to be assumption-robust."
        if preferred is not None else None
    )
    return JointDecisionResult(
        mode=policy.mode, pareto_shortlist_alternative_ids=non_dominated, pareto_explanations=explanations,
        ranked_alternative_groups=ranked_groups, preferred_alternative_id=preferred,
        synthetic_cost_sensitivity_caveat=caveat,
    )
