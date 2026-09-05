"""Phase 4 tests for decision.research_comparison (RA-DEC/BASE/SENS),
R3-CHAIN Final Research-Alignment Implementation Specification."""
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
    LoadStatePerformanceResult,
    RobustnessClassification,
    SensitivityCaseDefinition,
    SensitivityFactorName,
)
from r3chain_geothermal.decision.research_comparison import (
    ANNUALIZED_LCOH_OBJECTIVE_NAME,
    compare_baselines,
    compute_geothermal_only_lcoh_eur_per_mwh,
    decide_integrated,
    rank_geothermal_only_baseline,
    rank_network_only_baseline,
    run_sensitivity_study,
    select_fixed_reference_scenario,
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


# ── Geothermal-only baseline ─────────────────────────────────────────────────

def test_compute_geothermal_only_lcoh_is_positive_for_the_golden_scenario(_fixture) -> None:
    v2_result, assumptions, coupling_assumptions = _fixture
    scenario = v2_result.package.resource_scenarios[0]
    lcoh = compute_geothermal_only_lcoh_eur_per_mwh(
        scenario, v2_result.pydoublet_result, coupling_assumptions=coupling_assumptions, base_assumptions=assumptions,
    )
    assert lcoh is not None
    assert lcoh > 0


def test_rank_geothermal_only_baseline_picks_the_lowest_lcoh_site(_fixture) -> None:
    v2_result, assumptions, coupling_assumptions = _fixture
    preferred_site, has_any_rankable, lcoh_by_site = rank_geothermal_only_baseline(
        v2_result.package.resource_scenarios, v2_result.pydoublet_result,
        coupling_assumptions=coupling_assumptions, base_assumptions=assumptions,
    )
    assert has_any_rankable
    assert lcoh_by_site
    if preferred_site is not None:
        assert preferred_site == min(lcoh_by_site, key=lambda s: lcoh_by_site[s])


def test_rank_geothermal_only_baseline_empty_scenarios_is_not_rankable(_fixture) -> None:
    _, assumptions, coupling_assumptions = _fixture
    preferred, has_any_rankable, lcoh_by_site = rank_geothermal_only_baseline(
        [], None, coupling_assumptions=coupling_assumptions, base_assumptions=assumptions,
    )
    assert preferred is None
    assert not has_any_rankable
    assert lcoh_by_site == {}


def test_select_fixed_reference_scenario_is_deterministic(_fixture) -> None:
    v2_result, _, _ = _fixture
    scenarios = v2_result.package.resource_scenarios
    chosen = select_fixed_reference_scenario(scenarios)
    assert chosen is not None
    assert chosen == min(scenarios, key=lambda s: (s.site_id, s.scenario_id))


def test_select_fixed_reference_scenario_empty_list_returns_none() -> None:
    assert select_fixed_reference_scenario([]) is None


# ── compare_baselines: all 7 interpretation codes ────────────────────────────

def test_compare_baselines_no_feasible_integrated_alternative() -> None:
    result = compare_baselines(
        integrated_preferred_alternative_id=None, integrated_has_any_feasible=False,
        integrated_site_by_alternative_id={}, integrated_attachment_by_alternative_id={},
        geothermal_only_preferred_site_id="site-a", geothermal_only_has_any_rankable=True,
        network_only_preferred_attachment_id="att-1", network_only_has_any_rankable=True,
    )
    assert result.interpretation_code == ComparisonInterpretationCode.NO_FEASIBLE_INTEGRATED_ALTERNATIVE
    assert result.integrated_preferred_alternative_id is None


def test_compare_baselines_baseline_not_rankable_when_geothermal_only_empty() -> None:
    result = compare_baselines(
        integrated_preferred_alternative_id="alt-1", integrated_has_any_feasible=True,
        integrated_site_by_alternative_id={"alt-1": "site-a"}, integrated_attachment_by_alternative_id={"alt-1": "att-1"},
        geothermal_only_preferred_site_id=None, geothermal_only_has_any_rankable=False,
        network_only_preferred_attachment_id="att-1", network_only_has_any_rankable=True,
    )
    assert result.interpretation_code == ComparisonInterpretationCode.BASELINE_NOT_RANKABLE


def test_compare_baselines_material_tie_prevents_unique_comparison() -> None:
    result = compare_baselines(
        integrated_preferred_alternative_id=None, integrated_has_any_feasible=True,
        integrated_site_by_alternative_id={"alt-1": "site-a"}, integrated_attachment_by_alternative_id={"alt-1": "att-1"},
        geothermal_only_preferred_site_id="site-a", geothermal_only_has_any_rankable=True,
        network_only_preferred_attachment_id="att-1", network_only_has_any_rankable=True,
    )
    assert result.interpretation_code == ComparisonInterpretationCode.MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON


def test_compare_baselines_matches_both() -> None:
    result = compare_baselines(
        integrated_preferred_alternative_id="alt-1", integrated_has_any_feasible=True,
        integrated_site_by_alternative_id={"alt-1": "site-a"}, integrated_attachment_by_alternative_id={"alt-1": "att-1"},
        geothermal_only_preferred_site_id="site-a", geothermal_only_has_any_rankable=True,
        network_only_preferred_attachment_id="att-1", network_only_has_any_rankable=True,
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_MATCHES_BOTH_BASELINES


def test_compare_baselines_site_differs_from_geo_only() -> None:
    result = compare_baselines(
        integrated_preferred_alternative_id="alt-1", integrated_has_any_feasible=True,
        integrated_site_by_alternative_id={"alt-1": "site-b"}, integrated_attachment_by_alternative_id={"alt-1": "att-1"},
        geothermal_only_preferred_site_id="site-a", geothermal_only_has_any_rankable=True,
        network_only_preferred_attachment_id="att-1", network_only_has_any_rankable=True,
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_SITE_DIFFERS_FROM_GEO_ONLY


def test_compare_baselines_attachment_differs_from_network_only() -> None:
    result = compare_baselines(
        integrated_preferred_alternative_id="alt-1", integrated_has_any_feasible=True,
        integrated_site_by_alternative_id={"alt-1": "site-a"}, integrated_attachment_by_alternative_id={"alt-1": "att-2"},
        geothermal_only_preferred_site_id="site-a", geothermal_only_has_any_rankable=True,
        network_only_preferred_attachment_id="att-1", network_only_has_any_rankable=True,
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_ATTACHMENT_DIFFERS_FROM_NETWORK_ONLY


# ── run_sensitivity_study: all 6 robustness classifications ──────────────────

def _build_annualized(capex_econ, load_states, assumptions, alternative_id: str):
    return compute_annualized_system_economics(alternative_id, load_states, capex_econ, assumptions=assumptions)


def test_run_sensitivity_study_robust_over_tested_range(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    capex_econ = feasible_alt.economics
    states = [_feasible_state()]
    annualized = {"alt-1": _build_annualized(capex_econ, states, assumptions, "alt-1")}
    policy = _policy()
    decision = decide_integrated(annualized, policy)

    summary = run_sensitivity_study(
        annualized, {"alt-1": capex_econ}, [_sensitivity_case(multiplier=1.01)], policy, assumptions=assumptions,
        base_case_preferred_alternative_id=decision.preferred_alternative_id,
        site_by_alternative_id={"alt-1": "site-a"}, attachment_by_alternative_id={"alt-1": "att-1"},
    )
    assert summary.robustness_classification == RobustnessClassification.ROBUST_OVER_TESTED_RANGE
    assert summary.base_case_preferred_alternative_id == "alt-1"


def test_run_sensitivity_study_no_unique_base_winner() -> None:
    summary = run_sensitivity_study(
        {}, {}, [_sensitivity_case()], _policy(), assumptions=None,
        base_case_preferred_alternative_id=None, site_by_alternative_id={}, attachment_by_alternative_id={},
    )
    assert summary.robustness_classification == RobustnessClassification.NO_UNIQUE_BASE_WINNER
    assert summary.base_case_preferred_alternative_id is None


def test_run_sensitivity_study_insufficient_feasible_cases_when_no_cases_declared(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    capex_econ = feasible_alt.economics
    states = [_feasible_state()]
    annualized = {"alt-1": _build_annualized(capex_econ, states, assumptions, "alt-1")}
    summary = run_sensitivity_study(
        annualized, {"alt-1": capex_econ}, [], _policy(), assumptions=assumptions,
        base_case_preferred_alternative_id="alt-1",
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
        base_case_preferred_alternative_id="alt-cheap",
        site_by_alternative_id={"alt-cheap": "site-a", "alt-expensive": "site-b"},
        attachment_by_alternative_id={"alt-cheap": "att-1", "alt-expensive": "att-2"},
    )
    assert summary.sensitivity_case_results[0].preferred_alternative_id == "alt-expensive"
    assert summary.robustness_classification == RobustnessClassification.ASSUMPTION_SENSITIVE


def test_run_sensitivity_study_robust_site_but_connection_sensitive(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    annualized, cheap_capex, expensive_capex = _flip_construction(feasible_alt, assumptions)
    policy = _policy()
    summary = run_sensitivity_study(
        annualized, {"alt-cheap": cheap_capex, "alt-expensive": expensive_capex},
        [_sensitivity_case(case_id="flip_it", multiplier=1_000_000.0)], policy, assumptions=assumptions,
        base_case_preferred_alternative_id="alt-cheap",
        # SAME site for both alternatives -- only the attachment differs.
        site_by_alternative_id={"alt-cheap": "site-a", "alt-expensive": "site-a"},
        attachment_by_alternative_id={"alt-cheap": "att-1", "alt-expensive": "att-2"},
    )
    assert summary.robustness_classification == RobustnessClassification.ROBUST_SITE_BUT_CONNECTION_SENSITIVE


# ── Network-only baseline ─────────────────────────────────────────────────────

def test_rank_network_only_baseline_filters_to_the_fixed_scenario(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alts = [a for a in v2_result.alternatives if a.feasible]
    assert len(feasible_alts) >= 1
    fixed_scenario_id = feasible_alts[0].identity.resource_scenario_id

    annualized_by_id = {}
    attachment_by_id = {}
    resource_scenario_by_id = {}
    for alt in feasible_alts:
        aid = alt.identity.alternative_id
        annualized_by_id[aid] = compute_annualized_system_economics(
            aid, [_feasible_state()], alt.economics, assumptions=assumptions,
        )
        attachment_by_id[aid] = alt.identity.attachment_id
        resource_scenario_by_id[aid] = alt.identity.resource_scenario_id

    preferred_attachment, has_any_rankable, subset = rank_network_only_baseline(
        annualized_by_id, attachment_by_id, resource_scenario_by_id, fixed_scenario_id, _policy(),
    )
    assert has_any_rankable
    assert all(resource_scenario_by_id[aid] == fixed_scenario_id for aid in subset)
    if preferred_attachment is not None:
        assert preferred_attachment in attachment_by_id.values()


def test_rank_network_only_baseline_not_rankable_for_an_unknown_scenario(_fixture) -> None:
    v2_result, assumptions, _ = _fixture
    feasible_alt = next(a for a in v2_result.alternatives if a.feasible)
    aid = feasible_alt.identity.alternative_id
    annualized_by_id = {
        aid: compute_annualized_system_economics(aid, [_feasible_state()], feasible_alt.economics, assumptions=assumptions),
    }
    preferred, has_any_rankable, subset = rank_network_only_baseline(
        annualized_by_id, {aid: "att-1"}, {aid: feasible_alt.identity.resource_scenario_id},
        "no-such-scenario", _policy(),
    )
    assert preferred is None
    assert not has_any_rankable
    assert subset == {}
