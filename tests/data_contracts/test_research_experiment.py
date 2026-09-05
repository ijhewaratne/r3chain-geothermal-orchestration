"""Phase 1 tests for the research-experiment layer contracts
(data_contracts.research_experiment), R3-CHAIN Final Research-Alignment
Implementation Specification."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r3chain_geothermal.data_contracts.joint_study import (
    AssumptionStatus,
    DecisionPolicy,
    DecisionPolicyMode,
    ObjectiveDefinition,
    ObjectiveDirection,
)
from r3chain_geothermal.data_contracts.research_experiment import (
    AnnualizedAlternativeEconomicResult,
    BaselineComparisonResult,
    ComparisonInterpretationCode,
    LoadStateDefinition,
    LoadStatePerformanceResult,
    ResearchExperimentConfig,
    ResearchExperimentDecisionSummary,
    RobustnessClassification,
    SensitivityCaseDefinition,
    SensitivityCaseResult,
    SensitivityFactorName,
    validate_load_state_durations,
)

_NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _load_state(**overrides) -> LoadStateDefinition:
    kwargs = dict(
        load_state_id="peak", label="Peak demand", demand_scale_fraction=1.0,
        annual_duration_hours=2000.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
    )
    kwargs.update(overrides)
    return LoadStateDefinition(**kwargs)


def _decision_policy(**overrides) -> DecisionPolicy:
    objective = ObjectiveDefinition(
        name="annualized_system_lcoh_eur_per_mwh", direction=ObjectiveDirection.MINIMIZE,
        absolute_materiality=0.5, relative_materiality_fraction=0.01, unit="EUR/MWh",
        rationale="primary annualized system cost signal", source_reference="demo",
    )
    kwargs = dict(
        mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, objectives=[objective],
        primary_objective="annualized_system_lcoh_eur_per_mwh", allow_shared_rank=True,
    )
    kwargs.update(overrides)
    return DecisionPolicy(**kwargs)


def _sensitivity_case(**overrides) -> SensitivityCaseDefinition:
    kwargs = dict(
        case_id="capex_plus_20pct", label="+20% connection CAPEX",
        factor_name=SensitivityFactorName.CONNECTION_CAPEX_MULTIPLIER, multiplier=1.2,
        reason="illustrative deterministic what-if, not a probabilistic estimate",
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
    )
    kwargs.update(overrides)
    return SensitivityCaseDefinition(**kwargs)


def _config(**overrides) -> ResearchExperimentConfig:
    kwargs = dict(
        referenced_study_package_relative_path="config/joint_study_synthetic_v2.json",
        referenced_study_package_expected_sha256="a" * 64,
        load_states=[_load_state()],
        sensitivity_cases=[_sensitivity_case()],
        decision_policy=_decision_policy(),
    )
    kwargs.update(overrides)
    return ResearchExperimentConfig(**kwargs)


def _feasible_state_result(**overrides) -> LoadStatePerformanceResult:
    kwargs = dict(
        load_state_id="peak", annual_duration_hours=2000.0, feasible=True, failure_code=None, message=None,
        geothermal_injected_heat_kw=3000.0, geothermal_curtailed_heat_kw=0.0, auxiliary_heat_kw=200.0,
        total_heat_delivered_kw=3200.0, doublet_pump_electric_power_kw=177.45, dh_hydraulic_pumping_power_kw=12.0,
    )
    kwargs.update(overrides)
    return LoadStatePerformanceResult(**kwargs)


def _infeasible_state_result(**overrides) -> LoadStatePerformanceResult:
    kwargs = dict(
        load_state_id="base", annual_duration_hours=2000.0, feasible=False,
        failure_code="THERMAL_PIPEFLOW_NOT_CONVERGED", message="did not converge at low demand",
        geothermal_injected_heat_kw=None, geothermal_curtailed_heat_kw=None, auxiliary_heat_kw=None,
        total_heat_delivered_kw=None, doublet_pump_electric_power_kw=None, dh_hydraulic_pumping_power_kw=None,
    )
    kwargs.update(overrides)
    return LoadStatePerformanceResult(**kwargs)


# ── LoadStateDefinition ───────────────────────────────────────────────────────

def test_load_state_definition_accepts_valid_values() -> None:
    state = _load_state()
    assert state.demand_scale_fraction == 1.0


@pytest.mark.parametrize("field,value", [
    ("load_state_id", ""), ("label", ""), ("demand_scale_fraction", 0.0),
    ("demand_scale_fraction", 1.5), ("demand_scale_fraction", -0.1), ("annual_duration_hours", 0.0),
    ("annual_duration_hours", -1.0),
])
def test_load_state_definition_rejects_invalid_values(field: str, value) -> None:
    with pytest.raises(ValidationError):
        _load_state(**{field: value})


def test_validate_load_state_durations_flags_duplicate_ids() -> None:
    states = [_load_state(), _load_state()]
    errors = validate_load_state_durations(states, annual_operating_hours=8000.0)
    assert any("unique" in e for e in errors)


def test_validate_load_state_durations_flags_overrun() -> None:
    states = [_load_state(annual_duration_hours=9000.0)]
    errors = validate_load_state_durations(states, annual_operating_hours=8000.0)
    assert any("exceeds" in e for e in errors)


def test_validate_load_state_durations_passes_for_valid_set() -> None:
    states = [
        _load_state(load_state_id="peak", annual_duration_hours=2000.0),
        _load_state(load_state_id="shoulder", annual_duration_hours=3000.0),
        _load_state(load_state_id="base", annual_duration_hours=3000.0),
    ]
    assert validate_load_state_durations(states, annual_operating_hours=8000.0) == []


# ── SensitivityCaseDefinition ─────────────────────────────────────────────────

def test_sensitivity_case_definition_accepts_valid_values() -> None:
    case = _sensitivity_case()
    assert case.multiplier == 1.2


@pytest.mark.parametrize("field,value", [
    ("case_id", ""), ("label", ""), ("reason", ""), ("multiplier", 0.0), ("multiplier", -1.0),
])
def test_sensitivity_case_definition_rejects_invalid_values(field: str, value) -> None:
    with pytest.raises(ValidationError):
        _sensitivity_case(**{field: value})


# ── ResearchExperimentConfig ──────────────────────────────────────────────────

def test_research_experiment_config_accepts_valid_values() -> None:
    config = _config()
    assert config.decision_policy.primary_objective == "annualized_system_lcoh_eur_per_mwh"


@pytest.mark.parametrize("bad_path", ["/abs/path.json", "../escape.json", "", "C:/windows/path.json"])
def test_research_experiment_config_rejects_unsafe_package_path(bad_path: str) -> None:
    with pytest.raises(ValidationError):
        _config(referenced_study_package_relative_path=bad_path)


def test_research_experiment_config_rejects_bad_sha256() -> None:
    with pytest.raises(ValidationError):
        _config(referenced_study_package_expected_sha256="not-a-hash")


def test_research_experiment_config_rejects_empty_load_states() -> None:
    with pytest.raises(ValidationError):
        _config(load_states=[])


def test_research_experiment_config_rejects_duplicate_load_state_ids() -> None:
    with pytest.raises(ValidationError):
        _config(load_states=[_load_state(), _load_state()])


def test_research_experiment_config_rejects_duplicate_sensitivity_case_ids() -> None:
    with pytest.raises(ValidationError):
        _config(sensitivity_cases=[_sensitivity_case(), _sensitivity_case()])


# ── LoadStatePerformanceResult ────────────────────────────────────────────────

def test_load_state_performance_result_feasible_case() -> None:
    result = _feasible_state_result()
    assert result.feasible
    assert result.total_heat_delivered_kw == 3200.0


def test_load_state_performance_result_infeasible_case() -> None:
    result = _infeasible_state_result()
    assert not result.feasible
    assert result.failure_code == "THERMAL_PIPEFLOW_NOT_CONVERGED"


def test_load_state_performance_result_rejects_feasible_with_missing_kpi() -> None:
    with pytest.raises(ValidationError):
        _feasible_state_result(total_heat_delivered_kw=None)


def test_load_state_performance_result_rejects_feasible_with_failure_code() -> None:
    with pytest.raises(ValidationError):
        _feasible_state_result(failure_code="SOMETHING")


def test_load_state_performance_result_rejects_infeasible_without_failure_code() -> None:
    with pytest.raises(ValidationError):
        _infeasible_state_result(failure_code=None)


def test_load_state_performance_result_rejects_infeasible_with_kpi_present() -> None:
    with pytest.raises(ValidationError):
        _infeasible_state_result(total_heat_delivered_kw=100.0)


def test_load_state_performance_result_rejects_negative_kpi() -> None:
    with pytest.raises(ValidationError):
        _feasible_state_result(auxiliary_heat_kw=-1.0)


# ── AnnualizedAlternativeEconomicResult ───────────────────────────────────────

def _computable_annualized_result(**overrides) -> AnnualizedAlternativeEconomicResult:
    annuity_capital = 500_000.0
    opex_fixed = 20_000.0
    opex_doublet_pump = 30_000.0
    opex_dh_pumping = 5_000.0
    opex_aux = 10_000.0
    total_cost = annuity_capital + opex_fixed + opex_doublet_pump + opex_dh_pumping + opex_aux
    state = _feasible_state_result()
    useful_mwh = (state.total_heat_delivered_kw * state.annual_duration_hours) / 1000.0
    kwargs = dict(
        alternative_id="alt-1", load_state_results=[state], computable=True, non_computable_reason=None,
        capex_doublet_eur=2_000_000.0, capex_heat_exchanger_eur=300_000.0, capex_connection_pipes_eur=100_000.0,
        annuity_capital_eur_per_a=annuity_capital, opex_fixed_eur_per_a=opex_fixed,
        opex_electricity_doublet_pump_eur_per_a=opex_doublet_pump, opex_electricity_dh_pumping_eur_per_a=opex_dh_pumping,
        opex_auxiliary_heat_eur_per_a=opex_aux, annualized_total_system_cost_eur_per_a=total_cost,
        annual_useful_heat_mwh_per_a=useful_mwh, annualized_system_lcoh_eur_per_mwh=total_cost / useful_mwh,
        created_at=_NOW,
    )
    kwargs.update(overrides)
    return AnnualizedAlternativeEconomicResult(**kwargs)


def _non_computable_annualized_result(**overrides) -> AnnualizedAlternativeEconomicResult:
    kwargs = dict(
        alternative_id="alt-2", load_state_results=[_feasible_state_result(), _infeasible_state_result()],
        computable=False, non_computable_reason="load state 'base' did not converge (THERMAL_PIPEFLOW_NOT_CONVERGED)",
        capex_doublet_eur=None, capex_heat_exchanger_eur=None, capex_connection_pipes_eur=None,
        annuity_capital_eur_per_a=None, opex_fixed_eur_per_a=None, opex_electricity_doublet_pump_eur_per_a=None,
        opex_electricity_dh_pumping_eur_per_a=None, opex_auxiliary_heat_eur_per_a=None,
        annualized_total_system_cost_eur_per_a=None, annual_useful_heat_mwh_per_a=None,
        annualized_system_lcoh_eur_per_mwh=None, created_at=_NOW,
    )
    kwargs.update(overrides)
    return AnnualizedAlternativeEconomicResult(**kwargs)


def test_annualized_result_computable_case_valid() -> None:
    result = _computable_annualized_result()
    assert result.computable
    assert result.annualized_system_lcoh_eur_per_mwh > 0


def test_annualized_result_non_computable_case_valid() -> None:
    result = _non_computable_annualized_result()
    assert not result.computable
    assert result.non_computable_reason


def test_annualized_result_rejects_computable_flag_mismatch_with_infeasible_state() -> None:
    with pytest.raises(ValidationError):
        _computable_annualized_result(load_state_results=[_feasible_state_result(), _infeasible_state_result()])


def test_annualized_result_rejects_non_computable_with_reason_missing() -> None:
    with pytest.raises(ValidationError):
        _non_computable_annualized_result(non_computable_reason=None)


def test_annualized_result_rejects_non_computable_with_economics_field_present() -> None:
    with pytest.raises(ValidationError):
        _non_computable_annualized_result(annuity_capital_eur_per_a=1.0)


def test_annualized_result_rejects_tampered_total_cost() -> None:
    with pytest.raises(ValidationError):
        _computable_annualized_result(annualized_total_system_cost_eur_per_a=1.0)


def test_annualized_result_rejects_tampered_useful_heat() -> None:
    with pytest.raises(ValidationError):
        _computable_annualized_result(annual_useful_heat_mwh_per_a=1.0)


def test_annualized_result_rejects_tampered_lcoh() -> None:
    with pytest.raises(ValidationError):
        _computable_annualized_result(annualized_system_lcoh_eur_per_mwh=1.0)


def test_annualized_result_rejects_empty_load_state_results() -> None:
    with pytest.raises(ValidationError):
        _computable_annualized_result(load_state_results=[])


# ── BaselineComparisonResult ──────────────────────────────────────────────────

def test_baseline_comparison_result_valid_case() -> None:
    result = BaselineComparisonResult(
        interpretation_code=ComparisonInterpretationCode.INTEGRATED_MATCHES_BOTH_BASELINES,
        geothermal_only_preferred_site_id="site-a", network_only_preferred_attachment_id="att-1",
        integrated_preferred_alternative_id="alt-1", explanation="all three tiers agree on the same choice",
    )
    assert result.interpretation_code == ComparisonInterpretationCode.INTEGRATED_MATCHES_BOTH_BASELINES


def test_baseline_comparison_result_rejects_empty_explanation() -> None:
    with pytest.raises(ValidationError):
        BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.NO_FEASIBLE_INTEGRATED_ALTERNATIVE,
            geothermal_only_preferred_site_id=None, network_only_preferred_attachment_id=None,
            integrated_preferred_alternative_id=None, explanation="",
        )


def test_baseline_comparison_result_rejects_preferred_alternative_when_none_feasible() -> None:
    with pytest.raises(ValidationError):
        BaselineComparisonResult(
            interpretation_code=ComparisonInterpretationCode.NO_FEASIBLE_INTEGRATED_ALTERNATIVE,
            geothermal_only_preferred_site_id=None, network_only_preferred_attachment_id=None,
            integrated_preferred_alternative_id="alt-1", explanation="should be rejected",
        )


# ── Sensitivity / robustness ──────────────────────────────────────────────────

def test_sensitivity_case_result_valid() -> None:
    result = SensitivityCaseResult(
        case_id="capex_plus_20pct", preferred_alternative_id="alt-1",
        preferred_site_id="site-a", preferred_attachment_id="att-1",
    )
    assert result.case_id == "capex_plus_20pct"


def test_sensitivity_case_result_rejects_empty_case_id() -> None:
    with pytest.raises(ValidationError):
        SensitivityCaseResult(
            case_id="", preferred_alternative_id=None, preferred_site_id=None, preferred_attachment_id=None,
        )


def test_decision_summary_robust_case() -> None:
    summary = ResearchExperimentDecisionSummary(
        base_case_preferred_alternative_id="alt-1",
        sensitivity_case_results=[
            SensitivityCaseResult(
                case_id="capex_plus_20pct", preferred_alternative_id="alt-1",
                preferred_site_id="site-a", preferred_attachment_id="att-1",
            ),
        ],
        robustness_classification=RobustnessClassification.ROBUST_OVER_TESTED_RANGE,
        explanation="alt-1 remains preferred across every tested sensitivity case",
    )
    assert summary.robustness_classification == RobustnessClassification.ROBUST_OVER_TESTED_RANGE


def test_decision_summary_no_unique_base_winner_requires_null_preferred_id() -> None:
    with pytest.raises(ValidationError):
        ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id="alt-1", sensitivity_case_results=[],
            robustness_classification=RobustnessClassification.NO_UNIQUE_BASE_WINNER,
            explanation="should be rejected",
        )


def test_decision_summary_rejects_duplicate_sensitivity_case_ids() -> None:
    case = SensitivityCaseResult(
        case_id="dup", preferred_alternative_id=None, preferred_site_id=None, preferred_attachment_id=None,
    )
    with pytest.raises(ValidationError):
        ResearchExperimentDecisionSummary(
            base_case_preferred_alternative_id=None, sensitivity_case_results=[case, case],
            robustness_classification=RobustnessClassification.ASSUMPTION_SENSITIVE,
            explanation="duplicate case ids should be rejected",
        )
