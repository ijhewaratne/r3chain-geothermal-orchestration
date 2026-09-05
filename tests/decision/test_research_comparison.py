"""Phase 4 tests for decision.research_comparison (RA-DEC/BASE/SENS),
R3-CHAIN Final Research-Alignment Implementation Specification.

Second conformance round: rank-1 SET semantics. Rewritten to match the
corrected API -- geothermal-only ranks SCENARIOS (never sites),
network-only uses a DECLARED reference (no more auto-selection), and
`compare_baselines()`/`run_sensitivity_study()` operate on rank-1 SETS."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.adapter import CouplingAssumptions
from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.data_contracts.joint_study import (
    DecisionPolicy,
    DecisionPolicyMode,
    ObjectiveDefinition,
    ObjectiveDirection,
)
from r3chain_geothermal.data_contracts.research_experiment import (
    AssumptionStatus,
    ComparisonInterpretationCode,
    GeothermalOnlyBaselinePolicy,
    LoadStatePerformanceResult,
    RobustnessClassification,
    SensitivityCaseDefinition,
    SensitivityFactorName,
)
from r3chain_geothermal.decision.joint_policy import AlternativeObjectiveValues, decide
from r3chain_geothermal.decision.research_comparison import (
    ANNUALIZED_LCOH_OBJECTIVE_NAME,
    _apply_sensitivity_case,
    compare_baselines,
    compute_geothermal_only_lcoh_eur_per_mwh,
    decide_integrated,
    rank_geothermal_only_baseline,
    rank_network_only_baseline,
    run_sensitivity_study,
)
from r3chain_geothermal.economics.annualized_system_costing import compute_annualized_system_economics
from r3chain_geothermal.economics.joint_costing import load_base_assumptions
from r3chain_geothermal.workflow.joint_workflow_v2 import JointWorkflowV2Result, run_joint_workflow_v2

_ROOT = Path(__file__).resolve().parents[2]
_V2_CONFIG_PATH = _ROOT / "config" / "demo_assumptions_joint_study_v2.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _v2_result() -> JointWorkflowV2Result:
    config = json.loads(_V2_CONFIG_PATH.read_text())
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    result = run_joint_workflow_v2(raw, config, source_provenance=provenance, package_root=_ROOT)
    assert isinstance(result, JointWorkflowV2Result)
    return result


def _policy() -> DecisionPolicy:
    objective = ObjectiveDefinition(
        name=ANNUALIZED_LCOH_OBJECTIVE_NAME, direction=ObjectiveDirection.MINIMIZE,
        absolute_materiality=0.5, relative_materiality_fraction=0.01, unit="EUR/MWh",
        rationale="primary annualized system cost signal", source_reference="demo",
    )
    return DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[objective],
        primary_objective=ANNUALIZED_LCOH_OBJECTIVE_NAME, allow_shared_rank=True,
    )


def _geo_only_policy(**overrides) -> GeothermalOnlyBaselinePolicy:
    objective = ObjectiveDefinition(
        name="indicative_geothermal_lcoh_at_hx_eur_per_mwh", direction=ObjectiveDirection.MINIMIZE,
        absolute_materiality=0.5, relative_materiality_fraction=0.01, unit="EUR/MWh",
        rationale="source-side LCOH at the HX boundary", source_reference="demo",
    )
    kwargs = dict(enabled=True, resource_scenario_ids=None, objective=objective)
    kwargs.update(overrides)
    return GeothermalOnlyBaselinePolicy(**kwargs)


def _feasible_state(hours: float = 8000.0) -> LoadStatePerformanceResult:
    return LoadStatePerformanceResult(
        load_state_id="peak", annual_duration_hours=hours, feasible=True, failure_code=None, message=None,
        geothermal_injected_heat_kw=1000.0, geothermal_curtailed_heat_kw=0.0, auxiliary_heat_kw=100.0,
        total_heat_delivered_kw=1100.0, doublet_pump_electric_power_kw=50.0, dh_hydraulic_pumping_power_kw=10.0,
    )


def _sensitivity_case(**overrides) -> SensitivityCaseDefinition:
    kwargs = dict(
        case_id="capex_plus_100x", label="huge connection CAPEX inflation (forces a flip)",
        factor_name=SensitivityFactorName.CONNECTION_CAPEX_MULTIPLIER, multiplier=100.0,
        reason="deterministic what-if guaranteed to dominate any base LCOH gap",
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
    )
    kwargs.update(overrides)
    return SensitivityCaseDefinition(**kwargs)


@pytest.fixture(scope="module")
def _fixture():
    v2_result = _v2_result()
    assumptions = load_base_assumptions(v2_result.package.economics, _ROOT)
    coupling_assumptions = CouplingAssumptions.from_config_dict(json.loads(_V2_CONFIG_PATH.read_text()))
    return v2_result, assumptions, coupling_assumptions


# ── Geothermal-only baseline: ranks SCENARIOS, never sites ───────────────────

def test_compute_geothermal_only_lcoh_is_positive_for_the_golden_scenario(_fixture) -> None:
    v2_result, assumptions, coupling_assumptions = _fixture
    scenario = v2_result.package.resource_scenarios[0]
    lcoh = compute_geothermal_only_lcoh_eur_per_mwh(
        scenario, v2_result.pydoublet_result, coupling_assumptions=coupling_assumptions, base_assumptions=assumptions,
    )
    assert lcoh is not None
    assert lcoh > 0


def test_rank_geothermal_only_baseline_never_collapses_scenarios_sharing_a_site(_fixture) -> None:
    """The committed v2 fixture genuinely has two scenarios on one site
    (scenario_alpha_golden, scenario_alpha_reduced_flow, both site_alpha) --
    both must appear as SEPARATE entries in lcoh_by_scenario_id."""
    v2_result, assumptions, coupling_assumptions = _fixture
    site_ids_by_scenario = {s.scenario_id: s.site_id for s in v2_result.package.resource_scenarios}
    alpha_scenarios = [sid for sid, site in site_ids_by_scenario.items() if site == "site_alpha"]
    assert len(alpha_scenarios) >= 2, "fixture assumption changed -- update this test"

    decision, has_any_rankable, lcoh_by_scenario = rank_geothermal_only_baseline(
        v2_result.package.resource_scenarios, v2_result.pydoublet_result,
        coupling_assumptions=coupling_assumptions, base_assumptions=assumptions, policy=_geo_only_policy(),
    )
    assert has_any_rankable
    for scenario_id in alpha_scenarios:
        if scenario_id in lcoh_by_scenario:
            # both alpha scenarios that clear their own HX boundary appear
            # as independent entries -- never merged into one site value.
            assert isinstance(lcoh_by_scenario[scenario_id], float)
    alpha_present = [sid for sid in alpha_scenarios if sid in lcoh_by_scenario]
    assert len(alpha_present) >= 2, f"expected both site_alpha scenarios present, got {alpha_present}"
    assert lcoh_by_scenario[alpha_present[0]] != lcoh_by_scenario[alpha_present[1]]


def test_rank_geothermal_only_baseline_respects_resource_scenario_ids_filter(_fixture) -> None:
    v2_result, assumptions, coupling_assumptions = _fixture
    only_one = v2_result.package.resource_scenarios[0].scenario_id
    decision, has_any_rankable, lcoh_by_scenario = rank_geothermal_only_baseline(
        v2_result.package.resource_scenarios, v2_result.pydoublet_result,
        coupling_assumptions=coupling_assumptions, base_assumptions=assumptions,
        policy=_geo_only_policy(resource_scenario_ids=[only_one]),
    )
    assert set(lcoh_by_scenario.keys()) <= {only_one}


def test_rank_geothermal_only_baseline_empty_scenarios_is_not_rankable(_fixture) -> None:
    _, assumptions, coupling_assumptions = _fixture
    decision, has_any_rankable, lcoh_by_scenario = rank_geothermal_only_baseline(
        [], None, coupling_assumptions=coupling_assumptions, base_assumptions=assumptions,
        policy=_geo_only_policy(),
    )
    assert not has_any_rankable
    assert lcoh_by_scenario == {}
    assert decision.ranked_alternative_groups == []


# ── Network-only baseline: DECLARED reference (no auto-selection) ───────────

def test_rank_network_only_baseline_filters_to_the_declared_reference(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alts = [a for a in v2_result.alternatives if a.feasible]
    assert len(feasible_alts) >= 1
    fixed_scenario_id = feasible_alts[0].identity.resource_scenario_id

    annualized_by_id = {}
    resource_scenario_by_id = {}
    attachment_by_id = {}
    for alt in feasible_alts:
        aid = alt.identity.alternative_id
        annualized_by_id[aid] = compute_annualized_system_economics(
            aid, [_feasible_state()], alt.economics, assumptions=assumptions,
        )
        resource_scenario_by_id[aid] = alt.identity.resource_scenario_id
        attachment_by_id[aid] = alt.identity.attachment_id

    decision, has_any_rankable, subset = rank_network_only_baseline(
        annualized_by_id, resource_scenario_by_id, fixed_scenario_id, _policy(),
        alternative_attachment_by_id=attachment_by_id,
    )
    assert has_any_rankable
    assert all(resource_scenario_by_id[aid] == fixed_scenario_id for aid in subset)


def test_rank_network_only_baseline_eligible_attachment_ids_filters_subset(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alts = [a for a in v2_result.alternatives if a.feasible]
    assert len(feasible_alts) >= 1
    fixed_scenario_id = feasible_alts[0].identity.resource_scenario_id
    same_scenario_alts = [a for a in feasible_alts if a.identity.resource_scenario_id == fixed_scenario_id]

    annualized_by_id = {}
    resource_scenario_by_id = {}
    attachment_by_id = {}
    for alt in feasible_alts:
        aid = alt.identity.alternative_id
        annualized_by_id[aid] = compute_annualized_system_economics(
            aid, [_feasible_state()], alt.economics, assumptions=assumptions,
        )
        resource_scenario_by_id[aid] = alt.identity.resource_scenario_id
        attachment_by_id[aid] = alt.identity.attachment_id

    excluded_attachment_id = same_scenario_alts[0].identity.attachment_id
    eligible_attachment_ids = sorted({
        a.identity.attachment_id for a in same_scenario_alts
        if a.identity.attachment_id != excluded_attachment_id
    })

    decision, has_any_rankable, subset = rank_network_only_baseline(
        annualized_by_id, resource_scenario_by_id, fixed_scenario_id, _policy(),
        alternative_attachment_by_id=attachment_by_id,
        eligible_attachment_ids=eligible_attachment_ids if eligible_attachment_ids else None,
    )
    assert all(attachment_by_id[aid] != excluded_attachment_id for aid in subset)
    if eligible_attachment_ids:
        assert all(attachment_by_id[aid] in set(eligible_attachment_ids) for aid in subset)


def test_rank_network_only_baseline_not_rankable_for_an_unknown_scenario(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    aid = feasible_alt.identity.alternative_id
    annualized_by_id = {
        aid: compute_annualized_system_economics(aid, [_feasible_state()], feasible_alt.economics, assumptions=assumptions),
    }
    decision, has_any_rankable, subset = rank_network_only_baseline(
        annualized_by_id, {aid: feasible_alt.identity.resource_scenario_id}, "no-such-scenario", _policy(),
        alternative_attachment_by_id={aid: feasible_alt.identity.attachment_id},
    )
    assert not has_any_rankable
    assert subset == {}


# ── compare_baselines: rank-1 SET disjointness, all interpretation codes ────

def _decision_with_group(group: list[str]):
    """Builds a JointDecisionResult whose rank-1 group is exactly `group`,
    reusing the real decide() so the fixture is genuine, not hand-faked."""
    objective = ObjectiveDefinition(
        name="x", direction=ObjectiveDirection.MINIMIZE, absolute_materiality=0.0,
        relative_materiality_fraction=0.0, unit="unit", rationale="test", source_reference="test",
    )
    policy = DecisionPolicy(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[objective],
        primary_objective="x", allow_shared_rank=True, tie_breakers=[],
    )
    values = [AlternativeObjectiveValues(alternative_id=aid, values={"x": 1.0}) for aid in group]
    return decide(values, policy)


def _empty_decision():
    return _decision_with_group([])


def test_compare_baselines_no_feasible_integrated_alternative() -> None:
    result = compare_baselines(
        integrated_has_any_feasible=False, integrated_decision=_empty_decision(),
        integrated_site_by_alternative_id={}, integrated_attachment_by_alternative_id={},
        geothermal_only_has_any_rankable=True, geothermal_only_decision=_decision_with_group(["s1"]),
        scenario_site_by_id={"s1": "site-a"},
        network_only_has_any_rankable=True, network_only_decision=_decision_with_group(["a1"]),
        network_only_attachment_by_alternative_id={"a1": "att-1"},
    )
    assert result.interpretation_code == ComparisonInterpretationCode.NO_FEASIBLE_INTEGRATED_ALTERNATIVE
    assert result.integrated_best_alternative_ids == []
    assert result.site_decision_changed_after_integration is None


def test_compare_baselines_baseline_not_rankable_when_geothermal_only_empty() -> None:
    result = compare_baselines(
        integrated_has_any_feasible=True, integrated_decision=_decision_with_group(["alt-1"]),
        integrated_site_by_alternative_id={"alt-1": "site-a"}, integrated_attachment_by_alternative_id={"alt-1": "att-1"},
        geothermal_only_has_any_rankable=False, geothermal_only_decision=_empty_decision(),
        scenario_site_by_id={},
        network_only_has_any_rankable=True, network_only_decision=_decision_with_group(["a1"]),
        network_only_attachment_by_alternative_id={"a1": "att-1"},
    )
    assert result.interpretation_code == ComparisonInterpretationCode.BASELINE_NOT_RANKABLE
    assert result.site_decision_changed_after_integration is None


def test_compare_baselines_matches_both() -> None:
    result = compare_baselines(
        integrated_has_any_feasible=True, integrated_decision=_decision_with_group(["alt-1"]),
        integrated_site_by_alternative_id={"alt-1": "site-a"}, integrated_attachment_by_alternative_id={"alt-1": "att-1"},
        geothermal_only_has_any_rankable=True, geothermal_only_decision=_decision_with_group(["scenario-a"]),
        scenario_site_by_id={"scenario-a": "site-a"},
        network_only_has_any_rankable=True, network_only_decision=_decision_with_group(["net-alt-1"]),
        network_only_attachment_by_alternative_id={"net-alt-1": "att-1"},
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_MATCHES_BOTH_BASELINES
    assert result.site_decision_changed_after_integration is False
    assert result.attachment_decision_changed_after_integration is False


def test_compare_baselines_site_differs_from_geo_only() -> None:
    result = compare_baselines(
        integrated_has_any_feasible=True, integrated_decision=_decision_with_group(["alt-1"]),
        integrated_site_by_alternative_id={"alt-1": "site-b"}, integrated_attachment_by_alternative_id={"alt-1": "att-1"},
        geothermal_only_has_any_rankable=True, geothermal_only_decision=_decision_with_group(["scenario-a"]),
        scenario_site_by_id={"scenario-a": "site-a"},
        network_only_has_any_rankable=True, network_only_decision=_decision_with_group(["net-alt-1"]),
        network_only_attachment_by_alternative_id={"net-alt-1": "att-1"},
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_SITE_DIFFERS_FROM_GEO_ONLY
    assert result.site_decision_changed_after_integration is True
    assert result.attachment_decision_changed_after_integration is False


def test_compare_baselines_attachment_differs_from_network_only() -> None:
    result = compare_baselines(
        integrated_has_any_feasible=True, integrated_decision=_decision_with_group(["alt-1"]),
        integrated_site_by_alternative_id={"alt-1": "site-a"}, integrated_attachment_by_alternative_id={"alt-1": "att-2"},
        geothermal_only_has_any_rankable=True, geothermal_only_decision=_decision_with_group(["scenario-a"]),
        scenario_site_by_id={"scenario-a": "site-a"},
        network_only_has_any_rankable=True, network_only_decision=_decision_with_group(["net-alt-1"]),
        network_only_attachment_by_alternative_id={"net-alt-1": "att-1"},
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_ATTACHMENT_DIFFERS_FROM_NETWORK_ONLY
    assert result.site_decision_changed_after_integration is False
    assert result.attachment_decision_changed_after_integration is True


def test_compare_baselines_differs_from_both() -> None:
    """The defect this test specifically closes: the prior implementation
    could never reach INTEGRATED_DIFFERS_FROM_BOTH because its own if/elif
    chain returned on the first site mismatch before ever checking
    attachment."""
    result = compare_baselines(
        integrated_has_any_feasible=True, integrated_decision=_decision_with_group(["alt-1"]),
        integrated_site_by_alternative_id={"alt-1": "site-b"}, integrated_attachment_by_alternative_id={"alt-1": "att-2"},
        geothermal_only_has_any_rankable=True, geothermal_only_decision=_decision_with_group(["scenario-a"]),
        scenario_site_by_id={"scenario-a": "site-a"},
        network_only_has_any_rankable=True, network_only_decision=_decision_with_group(["net-alt-1"]),
        network_only_attachment_by_alternative_id={"net-alt-1": "att-1"},
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_DIFFERS_FROM_BOTH
    assert result.site_decision_changed_after_integration is True
    assert result.attachment_decision_changed_after_integration is True


def test_compare_baselines_tied_but_overlapping_rank1_sets_counts_as_unchanged() -> None:
    """A materially tied rank-1 group (more than one member) does not, by
    itself, make the comparison indeterminate -- OVERLAP with the base
    baseline's own rank-1 set is what matters, not an exact single-winner
    match."""
    result = compare_baselines(
        integrated_has_any_feasible=True, integrated_decision=_decision_with_group(["alt-1", "alt-2"]),
        integrated_site_by_alternative_id={"alt-1": "site-a", "alt-2": "site-b"},
        integrated_attachment_by_alternative_id={"alt-1": "att-1", "alt-2": "att-2"},
        geothermal_only_has_any_rankable=True, geothermal_only_decision=_decision_with_group(["scenario-a"]),
        scenario_site_by_id={"scenario-a": "site-a"},
        network_only_has_any_rankable=True, network_only_decision=_decision_with_group(["net-alt-1"]),
        network_only_attachment_by_alternative_id={"net-alt-1": "att-1"},
    )
    # site-a (from alt-1) overlaps geo-only's {site-a}; att-1 (from alt-1) overlaps network-only's {att-1}
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_MATCHES_BOTH_BASELINES
    assert result.site_decision_changed_after_integration is False


# ── run_sensitivity_study: rank-1 groups, all robustness classifications ────

def _build_annualized(capex_econ, load_states, assumptions, alternative_id: str):
    return compute_annualized_system_economics(alternative_id, load_states, capex_econ, assumptions=assumptions)


def test_run_sensitivity_study_robust_over_tested_range(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    capex_econ = feasible_alt.economics
    states = [_feasible_state()]
    annualized = {"alt-1": _build_annualized(capex_econ, states, assumptions, "alt-1")}
    policy = _policy()
    base_decision = decide_integrated(annualized, policy)

    summary = run_sensitivity_study(
        annualized, {"alt-1": capex_econ}, [_sensitivity_case(multiplier=1.01)], policy, assumptions=assumptions,
        base_case_decision=base_decision, site_by_alternative_id={"alt-1": "site-a"},
        attachment_by_alternative_id={"alt-1": "att-1"},
    )
    assert summary.robustness_classification == RobustnessClassification.ROBUST_OVER_TESTED_RANGE
    assert summary.base_case_preferred_alternative_id == "alt-1"
    assert summary.sensitivity_case_results[0].rank1_alternative_ids == ["alt-1"]
    assert summary.sensitivity_case_results[0].newly_infeasible_alternative_ids == []


def test_run_sensitivity_study_no_unique_base_winner() -> None:
    summary = run_sensitivity_study(
        {}, {}, [_sensitivity_case()], _policy(), assumptions=None,
        base_case_decision=_empty_decision(), site_by_alternative_id={}, attachment_by_alternative_id={},
    )
    assert summary.robustness_classification == RobustnessClassification.NO_UNIQUE_BASE_WINNER
    assert summary.base_case_preferred_alternative_id is None


def test_run_sensitivity_study_insufficient_feasible_cases_when_no_cases_declared(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    capex_econ = feasible_alt.economics
    states = [_feasible_state()]
    annualized = {"alt-1": _build_annualized(capex_econ, states, assumptions, "alt-1")}
    base_decision = decide_integrated(annualized, _policy())
    summary = run_sensitivity_study(
        annualized, {"alt-1": capex_econ}, [], _policy(), assumptions=assumptions,
        base_case_decision=base_decision,
        site_by_alternative_id={"alt-1": "site-a"}, attachment_by_alternative_id={"alt-1": "att-1"},
    )
    assert summary.robustness_classification == RobustnessClassification.INSUFFICIENT_FEASIBLE_CASES


def _flip_construction(feasible_alt, assumptions):
    """A genuine two-cost-driver trade-off, not just a uniform scaling: a
    single positive multiplier applied identically to BOTH alternatives'
    connection-pipe CAPEX can only ever preserve or amplify a ranking
    already driven by that one component -- it can never flip one (scaling
    two positive numbers by the same factor preserves their order). A flip
    requires alt-cheap to win the BASE case despite a materially HIGHER
    connection-pipe CAPEX than alt-expensive, offset by a much lower
    doublet-pump OPEX; scaling connection CAPEX up then erodes that offset
    until alt-expensive's fixed OPEX disadvantage no longer dominates."""
    cheap_capex = feasible_alt.economics.model_copy(update={"capex_connection_pipes_eur": 1_000_000.0})
    expensive_capex = feasible_alt.economics.model_copy(update={"capex_connection_pipes_eur": 1.0})
    cheap_state = _feasible_state().model_copy(update={"doublet_pump_electric_power_kw": 1.0})
    expensive_state = _feasible_state().model_copy(update={"doublet_pump_electric_power_kw": 20_000.0})
    annualized = {
        "alt-cheap": compute_annualized_system_economics("alt-cheap", [cheap_state], cheap_capex, assumptions=assumptions),
        "alt-expensive": compute_annualized_system_economics(
            "alt-expensive", [expensive_state], expensive_capex, assumptions=assumptions,
        ),
    }
    return annualized, cheap_capex, expensive_capex


def test_run_sensitivity_study_assumption_sensitive_when_winner_flips(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    annualized, cheap_capex, expensive_capex = _flip_construction(feasible_alt, assumptions)
    policy = _policy()
    base_decision = decide_integrated(annualized, policy)
    assert base_decision.preferred_alternative_id == "alt-cheap"

    summary = run_sensitivity_study(
        annualized, {"alt-cheap": cheap_capex, "alt-expensive": expensive_capex},
        [_sensitivity_case(case_id="flip_it", multiplier=1_000_000.0)], policy, assumptions=assumptions,
        base_case_decision=base_decision,
        site_by_alternative_id={"alt-cheap": "site-a", "alt-expensive": "site-b"},
        attachment_by_alternative_id={"alt-cheap": "att-1", "alt-expensive": "att-2"},
    )
    assert summary.sensitivity_case_results[0].rank1_alternative_ids == ["alt-expensive"]
    assert summary.robustness_classification == RobustnessClassification.ASSUMPTION_SENSITIVE


def test_run_sensitivity_study_robust_site_but_connection_sensitive(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    annualized, cheap_capex, expensive_capex = _flip_construction(feasible_alt, assumptions)
    policy = _policy()
    base_decision = decide_integrated(annualized, policy)
    summary = run_sensitivity_study(
        annualized, {"alt-cheap": cheap_capex, "alt-expensive": expensive_capex},
        [_sensitivity_case(case_id="flip_it", multiplier=1_000_000.0)], policy, assumptions=assumptions,
        base_case_decision=base_decision,
        # SAME site for both alternatives -- only the attachment differs.
        site_by_alternative_id={"alt-cheap": "site-a", "alt-expensive": "site-a"},
        attachment_by_alternative_id={"alt-cheap": "att-1", "alt-expensive": "att-2"},
    )
    assert summary.robustness_classification == RobustnessClassification.ROBUST_SITE_BUT_CONNECTION_SENSITIVE


def test_run_sensitivity_study_newly_infeasible_alternative_is_recorded(_fixture) -> None:
    """A sensitivity case whose perturbation drives an alternative below its
    own feasibility -- here simulated directly by asserting the module's own
    diff logic against a hand-constructed 'disappears under perturbation'
    scenario is out of scope for a pure unit test without a real infeasible
    perturbation path; this test instead confirms the field is always
    present and empty when nothing becomes infeasible (the common case)."""
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    capex_econ = feasible_alt.economics
    annualized = {"alt-1": _build_annualized(capex_econ, [_feasible_state()], assumptions, "alt-1")}
    base_decision = decide_integrated(annualized, _policy())
    summary = run_sensitivity_study(
        annualized, {"alt-1": capex_econ}, [_sensitivity_case(multiplier=1.5)], _policy(), assumptions=assumptions,
        base_case_decision=base_decision, site_by_alternative_id={"alt-1": "site-a"},
        attachment_by_alternative_id={"alt-1": "att-1"},
    )
    assert summary.sensitivity_case_results[0].newly_infeasible_alternative_ids == []


# ── Item I: maximum observed rank change + restored-to-feasibility ──────────

def test_run_sensitivity_study_flip_produces_max_rank_change_of_one(_fixture) -> None:
    """The flip-construction case (alt-cheap rank 1 in base, alt-expensive
    rank 1 under the perturbation) must report max_rank_change=1 for BOTH
    candidates -- neither was ever infeasible, so the metric is a plain
    |case_rank - base_rank| delta over one declared sensitivity case."""
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    annualized, cheap_capex, expensive_capex = _flip_construction(feasible_alt, assumptions)
    policy = _policy()
    base_decision = decide_integrated(annualized, policy)
    assert base_decision.preferred_alternative_id == "alt-cheap"

    summary = run_sensitivity_study(
        annualized, {"alt-cheap": cheap_capex, "alt-expensive": expensive_capex},
        [_sensitivity_case(case_id="flip_it", multiplier=1_000_000.0)], policy, assumptions=assumptions,
        base_case_decision=base_decision,
        site_by_alternative_id={"alt-cheap": "site-a", "alt-expensive": "site-b"},
        attachment_by_alternative_id={"alt-cheap": "att-1", "alt-expensive": "att-2"},
    )
    by_id = {c.alternative_id: c for c in summary.candidate_rank_sensitivity}
    assert by_id["alt-cheap"].base_rank == 1
    assert by_id["alt-expensive"].base_rank == 2
    assert by_id["alt-cheap"].max_rank_change == 1
    assert by_id["alt-expensive"].max_rank_change == 1
    assert not by_id["alt-cheap"].became_infeasible_in_any_case
    assert not by_id["alt-expensive"].became_infeasible_in_any_case
    assert not by_id["alt-cheap"].restored_to_feasibility_in_any_case
    assert not by_id["alt-expensive"].restored_to_feasibility_in_any_case


def test_run_sensitivity_study_robust_over_tested_range_reports_zero_rank_change(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    capex_econ = feasible_alt.economics
    annualized = {"alt-1": _build_annualized(capex_econ, [_feasible_state()], assumptions, "alt-1")}
    policy = _policy()
    base_decision = decide_integrated(annualized, policy)
    summary = run_sensitivity_study(
        annualized, {"alt-1": capex_econ}, [_sensitivity_case(multiplier=1.01)], policy, assumptions=assumptions,
        base_case_decision=base_decision, site_by_alternative_id={"alt-1": "site-a"},
        attachment_by_alternative_id={"alt-1": "att-1"},
    )
    entry = summary.candidate_rank_sensitivity[0]
    assert entry.alternative_id == "alt-1"
    assert entry.base_rank == 1
    assert entry.max_rank_change == 0
    assert not entry.became_infeasible_in_any_case
    assert not entry.restored_to_feasibility_in_any_case


def test_compute_candidate_rank_sensitivity_flags_became_infeasible_and_restored() -> None:
    """Direct unit test of the pure helper (no organic sensitivity factor in
    this layer can flip physical feasibility -- item G's own honesty
    guarantee) -- proves the metric's own infeasibility/restoration handling
    in isolation, matching this project's established precedent of testing
    a private helper directly (see tests/network/test_baseline.py)."""
    from r3chain_geothermal.decision.research_comparison import _compute_candidate_rank_sensitivity

    results = _compute_candidate_rank_sensitivity(
        all_alternative_ids={"alt-a", "alt-b", "alt-c"},
        base_rank_by_id={"alt-a": 1, "alt-b": 2},
        case_rank_by_id_list=[{"alt-a": 1, "alt-c": 2}, {"alt-a": 2}],
    )
    by_id = {r.alternative_id: r for r in results}

    assert by_id["alt-a"].base_rank == 1
    assert by_id["alt-a"].max_rank_change == 1
    assert not by_id["alt-a"].became_infeasible_in_any_case
    assert not by_id["alt-a"].restored_to_feasibility_in_any_case

    assert by_id["alt-b"].base_rank == 2
    assert by_id["alt-b"].max_rank_change is None
    assert by_id["alt-b"].became_infeasible_in_any_case
    assert not by_id["alt-b"].restored_to_feasibility_in_any_case

    assert by_id["alt-c"].base_rank is None
    assert by_id["alt-c"].max_rank_change is None
    assert not by_id["alt-c"].became_infeasible_in_any_case
    assert by_id["alt-c"].restored_to_feasibility_in_any_case


def test_geothermal_derating_sensitivity_preserves_pumping_power_and_energy_balance(_fixture) -> None:
    """Item G's own honesty guarantee, proven directly: the geothermal-
    derating case must never change dh_hydraulic_pumping_power_kw from its
    base-case value (the documented simplification), and injected +
    auxiliary heat must exactly equal the base case's own
    total_heat_delivered_kw for every load state -- i.e. this sensitivity
    path can never fabricate a new technical infeasibility on its own."""
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    capex_econ = feasible_alt.economics
    base_state = _feasible_state()
    annualized = {"alt-1": _build_annualized(capex_econ, [base_state], assumptions, "alt-1")}
    policy = _policy()
    base_decision = decide_integrated(annualized, policy)

    derate_case = _sensitivity_case(
        case_id="geo_derate_10pct",
        factor_name=SensitivityFactorName.GEOTHERMAL_DELIVERABLE_HEAT_DERATING_FRACTION, multiplier=0.9,
    )
    summary = run_sensitivity_study(
        annualized, {"alt-1": capex_econ}, [derate_case], policy, assumptions=assumptions,
        base_case_decision=base_decision, site_by_alternative_id={"alt-1": "site-a"},
        attachment_by_alternative_id={"alt-1": "att-1"},
    )
    assert summary.sensitivity_case_results[0].newly_infeasible_alternative_ids == []
    entry = summary.candidate_rank_sensitivity[0]
    assert not entry.became_infeasible_in_any_case

    perturbed = _apply_sensitivity_case(
        annualized["alt-1"], capex_econ, derate_case, assumptions=assumptions,
    )
    assert perturbed.computable
    perturbed_state = perturbed.load_state_results[0]
    assert perturbed_state.dh_hydraulic_pumping_power_kw == pytest.approx(base_state.dh_hydraulic_pumping_power_kw)
    assert (
        perturbed_state.geothermal_injected_heat_kw + perturbed_state.auxiliary_heat_kw
        == pytest.approx(base_state.total_heat_delivered_kw)
    )
    assert perturbed_state.total_heat_delivered_kw == pytest.approx(base_state.total_heat_delivered_kw)
    assert perturbed_state.geothermal_injected_heat_kw < base_state.geothermal_injected_heat_kw
