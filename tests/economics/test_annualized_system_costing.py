"""Phase 3 tests for economics.annualized_system_costing (RA-ECON),
R3-CHAIN Final Research-Alignment Implementation Specification.

`representative_capex_economics` is taken from the REAL, already-proven v2
fixture (config/demo_assumptions_joint_study_v2.json +
config/joint_study_synthetic_v2.json) so CAPEX/annuity figures are genuine,
already-validated CandidateEconomicResult values -- not hand-constructed. The
per-load-state KPI values are hand-picked LoadStatePerformanceResult objects so
the expected annualized totals can be hand-calculated exactly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.data_contracts.joint_study import AssumptionStatus
from r3chain_geothermal.data_contracts.research_experiment import LoadStatePerformanceResult
from r3chain_geothermal.economics.annualized_system_costing import compute_annualized_system_economics
from r3chain_geothermal.economics.annuity import annuity_factor
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


def _feasible_state(load_state_id: str, hours: float, **overrides) -> LoadStatePerformanceResult:
    kwargs = dict(
        load_state_id=load_state_id, annual_duration_hours=hours, feasible=True, failure_code=None, message=None,
        geothermal_injected_heat_kw=1000.0, geothermal_curtailed_heat_kw=0.0, auxiliary_heat_kw=100.0,
        total_heat_delivered_kw=1100.0, doublet_pump_electric_power_kw=50.0, dh_hydraulic_pumping_power_kw=10.0,
    )
    kwargs.update(overrides)
    return LoadStatePerformanceResult(**kwargs)


def _infeasible_state(load_state_id: str, hours: float) -> LoadStatePerformanceResult:
    return LoadStatePerformanceResult(
        load_state_id=load_state_id, annual_duration_hours=hours, feasible=False,
        failure_code="THERMAL_PIPEFLOW_NOT_CONVERGED", message="did not converge",
        geothermal_injected_heat_kw=None, geothermal_curtailed_heat_kw=None, auxiliary_heat_kw=None,
        total_heat_delivered_kw=None, doublet_pump_electric_power_kw=None, dh_hydraulic_pumping_power_kw=None,
    )


@pytest.fixture(scope="module")
def _fixture():
    v2_result = _v2_result()
    alt = next(a for a in v2_result.alternatives if a.feasible)
    assumptions = load_base_assumptions(v2_result.package.economics, _ROOT)
    return alt, assumptions


def test_computable_case_hand_calculated(_fixture) -> None:
    alt, assumptions = _fixture
    capex_econ = alt.economics
    states = [
        _feasible_state("peak", 2000.0),
        _feasible_state("shoulder", 3000.0, geothermal_injected_heat_kw=700.0, auxiliary_heat_kw=50.0,
                         total_heat_delivered_kw=750.0, doublet_pump_electric_power_kw=40.0,
                         dh_hydraulic_pumping_power_kw=8.0),
    ]
    result = compute_annualized_system_economics("alt-x", states, capex_econ, assumptions=assumptions)

    assert result.computable
    a_doublet = annuity_factor(assumptions.interest_rate_real, assumptions.doublet_lifetime_years)
    a_hx = annuity_factor(assumptions.interest_rate_real, assumptions.heat_exchanger_lifetime_years)
    a_pipes = annuity_factor(assumptions.interest_rate_real, assumptions.connection_pipes_lifetime_years)
    expected_annuity = (
        capex_econ.capex_doublet_eur * a_doublet + capex_econ.capex_heat_exchanger_eur * a_hx
        + capex_econ.capex_connection_pipes_eur * a_pipes
    )
    assert result.annuity_capital_eur_per_a == pytest.approx(expected_annuity)

    expected_opex_doublet_pump = (
        50.0 * 2000.0 * assumptions.electricity_price_eur_per_kwh + 40.0 * 3000.0 * assumptions.electricity_price_eur_per_kwh
    )
    assert result.opex_electricity_doublet_pump_eur_per_a == pytest.approx(expected_opex_doublet_pump)

    expected_dh_pumping = (
        (10.0 / assumptions.dh_pump_efficiency) * 2000.0 * assumptions.electricity_price_eur_per_kwh
        + (8.0 / assumptions.dh_pump_efficiency) * 3000.0 * assumptions.electricity_price_eur_per_kwh
    )
    assert result.opex_electricity_dh_pumping_eur_per_a == pytest.approx(expected_dh_pumping)

    expected_aux = 100.0 * 2000.0 * assumptions.auxiliary_heat_price_eur_per_kwh + 50.0 * 3000.0 * assumptions.auxiliary_heat_price_eur_per_kwh
    assert result.opex_auxiliary_heat_eur_per_a == pytest.approx(expected_aux)

    expected_useful_mwh = (1100.0 * 2000.0 + 750.0 * 3000.0) / 1000.0
    assert result.annual_useful_heat_mwh_per_a == pytest.approx(expected_useful_mwh)

    expected_total_cost = expected_annuity + result.opex_fixed_eur_per_a + expected_opex_doublet_pump + expected_dh_pumping + expected_aux
    assert result.annualized_total_system_cost_eur_per_a == pytest.approx(expected_total_cost)
    assert result.annualized_system_lcoh_eur_per_mwh == pytest.approx(expected_total_cost / expected_useful_mwh)


def test_capex_is_identical_regardless_of_load_state_count(_fixture) -> None:
    alt, assumptions = _fixture
    capex_econ = alt.economics
    one_state = [_feasible_state("only", 8000.0)]
    two_states = [_feasible_state("a", 4000.0), _feasible_state("b", 4000.0)]

    result_one = compute_annualized_system_economics("alt-1", one_state, capex_econ, assumptions=assumptions)
    result_two = compute_annualized_system_economics("alt-2", two_states, capex_econ, assumptions=assumptions)

    assert result_one.annuity_capital_eur_per_a == pytest.approx(result_two.annuity_capital_eur_per_a)
    assert result_one.capex_doublet_eur == pytest.approx(result_two.capex_doublet_eur)
    # OPEX/useful-heat totals across two 4000h half-scale-duration states with
    # identical per-state KPIs equal the single 8000h state's own totals.
    assert result_one.annual_useful_heat_mwh_per_a == pytest.approx(result_two.annual_useful_heat_mwh_per_a)
    assert result_one.annualized_total_system_cost_eur_per_a == pytest.approx(result_two.annualized_total_system_cost_eur_per_a)


def test_infeasible_load_state_makes_the_result_non_computable(_fixture) -> None:
    alt, assumptions = _fixture
    states = [_feasible_state("peak", 2000.0), _infeasible_state("base", 6000.0)]
    result = compute_annualized_system_economics("alt-x", states, alt.economics, assumptions=assumptions)

    assert not result.computable
    assert "base" in result.non_computable_reason
    assert result.annualized_system_lcoh_eur_per_mwh is None
    assert result.annuity_capital_eur_per_a is None


def test_no_load_states_raises_as_a_caller_defect(_fixture) -> None:
    _, assumptions = _fixture
    with pytest.raises(ValueError, match="must not be empty"):
        compute_annualized_system_economics("alt-x", [], None, assumptions=assumptions)


def test_missing_representative_capex_with_feasible_states_raises_as_a_caller_defect(_fixture) -> None:
    _, assumptions = _fixture
    states = [_feasible_state("peak", 8000.0)]
    with pytest.raises(ValueError, match="must not be None"):
        compute_annualized_system_economics("alt-x", states, None, assumptions=assumptions)
