"""Full test matrix for decision/joint_policy.py -- Phase 4 of
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md:
DEC-001..015, AC-J10, AC-J11 -- proven with tightly controlled synthetic
objective values (not the full committed fixture; see
tests/workflow/test_joint_phase4.py for the end-to-end proof)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from r3chain_geothermal.data_contracts.joint_study import DecisionPolicy, DecisionPolicyMode, ObjectiveDefinition, ObjectiveDirection
from r3chain_geothermal.decision.joint_policy import (
    AlternativeObjectiveValues,
    _dominates,
    _materially_equivalent,
    decide,
    pareto_shortlist,
)


def _objective(name: str, direction: ObjectiveDirection, abs_eps: float = 0.5, rel_eps: float = 0.01) -> ObjectiveDefinition:
    return ObjectiveDefinition(
        name=name, direction=direction, absolute_materiality=abs_eps, relative_materiality_fraction=rel_eps,
        unit="x", rationale="t", source_reference="t",
    )


def _values(alternative_id: str, **kwargs) -> AlternativeObjectiveValues:
    return AlternativeObjectiveValues(alternative_id=alternative_id, values=kwargs)


_LCOH = _objective("lcoh", ObjectiveDirection.MINIMIZE, abs_eps=0.5, rel_eps=0.01)
_COVERAGE = _objective("coverage", ObjectiveDirection.MAXIMIZE, abs_eps=0.01, rel_eps=0.0)


# ── AC-J10: materiality-aware dominance ignores insignificant differences ───
def test_materially_equivalent_values_within_absolute_threshold():
    assert _materially_equivalent(52.171, 52.200, _LCOH)  # 0.029 diff, well under 0.5 abs threshold


def test_materially_different_values_outside_threshold():
    assert not _materially_equivalent(52.0, 60.0, _LCOH)


def test_ac_j10_a_tiny_lcoh_difference_does_not_create_dominance():
    a = _values("a", lcoh=52.171, coverage=0.99)
    b = _values("b", lcoh=52.180, coverage=0.99)  # 0.009 diff -- immaterial
    assert not _dominates(a, b, [_LCOH, _COVERAGE])
    assert not _dominates(b, a, [_LCOH, _COVERAGE])


def test_a_material_lcoh_difference_with_equal_coverage_does_create_dominance():
    a = _values("a", lcoh=50.0, coverage=0.99)
    b = _values("b", lcoh=79.0, coverage=0.99)
    assert _dominates(a, b, [_LCOH, _COVERAGE])
    assert not _dominates(b, a, [_LCOH, _COVERAGE])


def test_pareto_shortlist_excludes_a_materially_dominated_alternative():
    a = _values("a", lcoh=50.0, coverage=0.99)
    b = _values("b", lcoh=79.0, coverage=0.70)  # worse on both, materially
    ids, explanations = pareto_shortlist([a, b], [_LCOH, _COVERAGE])
    assert ids == ["a"]
    assert "lcoh" in explanations["a"] or "coverage" in explanations["a"]


def test_pareto_shortlist_keeps_a_genuine_tradeoff():
    a = _values("a", lcoh=50.0, coverage=0.70)  # cheaper, less coverage
    b = _values("b", lcoh=79.0, coverage=0.99)  # pricier, more coverage
    ids, explanations = pareto_shortlist([a, b], [_LCOH, _COVERAGE])
    assert set(ids) == {"a", "b"}
    assert "lcoh" in explanations["a"]
    assert "coverage" in explanations["b"]


def test_pareto_shortlist_is_empty_for_no_alternatives():
    ids, explanations = pareto_shortlist([], [_LCOH, _COVERAGE])
    assert ids == []
    assert explanations == {}


# ── DEC-002/003: objective definition validation is already Phase-1's own ───
def test_duplicate_objective_names_already_rejected_at_the_policy_level():
    dup = _objective("lcoh", ObjectiveDirection.MINIMIZE)
    with pytest.raises(ValidationError):
        DecisionPolicy(mode=DecisionPolicyMode.PARETO_ONLY, objectives=[dup, dup], allow_shared_rank=True)


# ── DEC-008: pareto_only returns no preferred ID ─────────────────────────────
def test_pareto_only_mode_returns_no_preferred_id_and_no_ranked_groups():
    policy = DecisionPolicy(mode=DecisionPolicyMode.PARETO_ONLY, objectives=[_LCOH, _COVERAGE], allow_shared_rank=True)
    a = _values("a", lcoh=50.0, coverage=0.99)
    b = _values("b", lcoh=79.0, coverage=0.70)
    result = decide([a, b], policy)
    assert result.preferred_alternative_id is None
    assert result.ranked_alternative_groups == []
    assert result.synthetic_cost_sensitivity_caveat is None


# ── DEC-009/011/013: primary-objective ranking, ties share a rank ───────────
def test_primary_objective_ranking_orders_distinct_values_into_distinct_ranks():
    policy = DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[_LCOH, _COVERAGE],
        primary_objective="lcoh", allow_shared_rank=True,
    )
    a = _values("a", lcoh=50.0, coverage=0.99)
    b = _values("b", lcoh=79.0, coverage=0.70)
    result = decide([a, b], policy)
    assert result.ranked_alternative_groups == [["a"], ["b"]]
    assert result.preferred_alternative_id == "a"
    assert result.pareto_shortlist_alternative_ids  # DEC-013: Pareto set still present


def test_ac_j11_materially_tied_alternatives_share_one_rank_and_no_unique_preferred():
    """AC-J11: two alternatives whose primary-objective values remain
    materially tied even considered against the declared tie-breaker
    share ONE rank; preferred_alternative_id is null because rank 1 has
    more than one member."""
    policy = DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[_LCOH, _COVERAGE],
        primary_objective="lcoh", tie_breakers=["coverage"], allow_shared_rank=True,
    )
    a = _values("a", lcoh=52.171, coverage=0.99)
    b = _values("b", lcoh=52.180, coverage=0.99)  # materially tied with a on lcoh AND coverage
    c = _values("c", lcoh=79.0, coverage=0.70)
    result = decide([a, b, c], policy)
    assert result.ranked_alternative_groups[0] == sorted(["a", "b"])  # tie-break by alternative_id when all else ties
    assert result.ranked_alternative_groups[1] == ["c"]
    assert result.preferred_alternative_id is None
    assert result.synthetic_cost_sensitivity_caveat is None  # no unique preferred -> no caveat needed


def test_tie_breaker_produces_a_deterministic_display_order_within_a_shared_rank():
    """A tie-breaker CAN separate group members for display order even
    though they still share one rank (DEC-007/011)."""
    policy = DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[_LCOH, _COVERAGE],
        primary_objective="lcoh", tie_breakers=["coverage"], allow_shared_rank=True,
    )
    a = _values("a", lcoh=52.171, coverage=0.70)  # tied on lcoh, but LOWER coverage
    b = _values("b", lcoh=52.180, coverage=0.99)  # tied on lcoh, HIGHER coverage
    result = decide([a, b], policy)
    assert result.ranked_alternative_groups[0] == ["b", "a"]  # coverage maximize -> b (0.99) before a (0.70)
    assert result.preferred_alternative_id is None  # still one shared rank


def test_primary_objective_ranking_is_deterministic_across_repeated_calls():
    policy = DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[_LCOH, _COVERAGE],
        primary_objective="lcoh", tie_breakers=["coverage"], allow_shared_rank=True,
    )
    alts = [_values("a", lcoh=52.171, coverage=0.99), _values("b", lcoh=52.180, coverage=0.99), _values("c", lcoh=79.0, coverage=0.70)]
    result_1 = decide(alts, policy)
    result_2 = decide(alts, policy)
    assert result_1.ranked_alternative_groups == result_2.ranked_alternative_groups


def test_unique_rank_one_alternative_produces_a_preferred_id_with_a_sensitivity_caveat():
    policy = DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[_LCOH, _COVERAGE],
        primary_objective="lcoh", allow_shared_rank=True,
    )
    a = _values("a", lcoh=50.0, coverage=0.99)
    b = _values("b", lcoh=79.0, coverage=0.70)
    result = decide([a, b], policy)
    assert result.preferred_alternative_id == "a"
    assert result.synthetic_cost_sensitivity_caveat is not None
    assert "DEC-012" in result.synthetic_cost_sensitivity_caveat


# ── Unknown objective name has no data source (OP-003) ──────────────────────
def test_unregistered_objective_name_raises_rather_than_guessing():
    from r3chain_geothermal.decision.joint_policy import compute_alternative_objective_values

    unknown = _objective("some_unregistered_kpi", ObjectiveDirection.MINIMIZE)
    with pytest.raises(ValueError, match="no registered data source"):
        compute_alternative_objective_values("alt-1", candidate_result=None, economics=None, objectives=[unknown])
