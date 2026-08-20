"""Full test matrix for network/baseline.py -- the T2.2B baseline evaluator."""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.network import (
    BaselineFailureCode,
    BaselineNetworkFailure,
    BaselineNetworkResult,
    GateTolerances,
    build_default_blueprint,
    run_baseline_evaluation,
)
from r3chain_geothermal.network.baseline import parse_baseline_result_json

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_BASELINE_SRC_PATH = _ROOT / "src" / "r3chain_geothermal" / "network" / "baseline.py"

_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _tolerances() -> GateTolerances:
    return GateTolerances.from_config_dict(_config())


def _blueprint(**overrides):
    kwargs = dict(
        consumer_demands_kw=_DEMANDS,
        trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
        created_at=datetime.now(timezone.utc),
    )
    kwargs.update(overrides)
    return build_default_blueprint(**kwargs)


def _strict_json_loads(text: str):
    def _reject(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")
    return json.loads(text, parse_constant=_reject)


# ── Real solve: all KPIs correct ────────────────────────────────────────────
def test_default_baseline_converges_with_correct_kpis():
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)

    assert result.total_heat_delivered_kw == pytest.approx(3200.0)
    for consumer_id, demand_kw in _DEMANDS.items():
        c = result.consumers[consumer_id]
        assert c.heat_delivered_kw == pytest.approx(demand_kw)
        assert c.supply_temperature_c == pytest.approx(70.0)
        assert c.return_temperature_c == pytest.approx(40.0)
        assert c.supply_temperature_drop_k == pytest.approx(0.0, abs=1e-9)

    assert result.min_consumer_supply_temperature_c == pytest.approx(70.0)
    assert result.mean_consumer_return_temperature_c == pytest.approx(40.0)
    assert result.min_pressure_bar_abs == pytest.approx(3.0)
    assert result.max_velocity_m_s == pytest.approx(0.9854, abs=1e-3)
    assert result.circulation_pump.hydraulic_pumping_power_kw == pytest.approx(7.7635, abs=1e-2)
    assert result.circulation_pump.pressure_lift_bar == pytest.approx(3.0)


# ── The energy-balance investigation finding, as a permanent regression test ──
def test_physical_energy_balance_is_the_true_enthalpy_integral_not_pandapipes_formula():
    """EnergyBalanceCheck (the field the 2% gate applies to) must use the
    TRUE integral cp(T) dT, NOT pandapipes' own qext_w reporting-convention
    formula -- the two are verified numerically distinct at this baseline's
    operating point (~3199.18 kW physical vs. ~3289.26 kW pandapipes-formula)."""
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)

    eb = result.energy_balance
    pic = result.pandapipes_internal_energy_consistency

    # The physical figure must differ from the pandapipes-formula figure --
    # proving EnergyBalanceCheck is not secretly reusing the flawed formula.
    assert eb.pump_physical_enthalpy_kw != pytest.approx(pic.pump_reported_qext_kw, rel=1e-6)
    assert eb.pump_physical_enthalpy_kw == pytest.approx(3199.1758, abs=1e-3)
    assert eb.consumer_physical_enthalpy_kw == pytest.approx(3199.1758, abs=1e-3)
    assert eb.pipe_physical_heat_loss_kw == pytest.approx(0.0, abs=1e-9)

    # Physical residual is machine-precision at this operating point --
    # consistency of the SAME integration method applied to the pump and
    # every consumer over the SAME temperature bounds (313.15<->343.15 K,
    # the uniform design delta-T), given already-consistent mass balance
    # (verified separately) -- not an independent experimental proof of
    # energy conservation (see EnergyBalanceCheck's own docstring). The
    # unchanged 2% tolerance is not being loosened to paper over anything;
    # this is a MEASURED result of this specific scenario.
    assert eb.residual_fraction < 1e-6
    assert eb.tolerance_fraction == pytest.approx(0.02)
    assert eb.passed is True
    assert eb.integration_method == "composite_trapezoidal"
    assert eb.integration_segments == 100


def test_pandapipes_internal_energy_consistency_is_a_labelled_diagnostic_not_the_gate():
    """PandapipesInternalEnergyConsistency reports pandapipes' own
    reporting-convention qext_w (NOT a true enthalpy integral -- see
    baseline.py's module docstring) against the simple consumer-demand
    total, with the ~2.79% reporting-convention difference EXPLICITLY
    visible, never hidden and never called a physical imbalance."""
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)

    pic = result.pandapipes_internal_energy_consistency
    assert pic.consumer_demand_total_kw == pytest.approx(3200.0)
    assert pic.pump_reported_qext_kw == pytest.approx(3289.2596, abs=1e-3)
    assert pic.reporting_convention_difference_fraction == pytest.approx(0.02789, abs=1e-4)

    # Internal self-consistency (my own re-implementation of pandapipes'
    # formula matches pandapipes' own reported value) is machine-precision --
    # this proves arithmetic fidelity, NOT physical energy conservation.
    assert pic.residual_fraction < 1e-6

    # No pass/fail concept on a diagnostic.
    assert not hasattr(pic, "passed")
    assert not hasattr(pic, "tolerance_fraction")


def test_physical_and_pandapipes_metrics_are_numerically_and_semantically_distinct():
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)
    eb = result.energy_balance
    pic = result.pandapipes_internal_energy_consistency

    # Distinct fields, distinct model classes, distinct numeric values --
    # never conflated.
    assert type(eb).__name__ == "EnergyBalanceCheck"
    assert type(pic).__name__ == "PandapipesInternalEnergyConsistency"
    assert eb.pump_physical_enthalpy_kw != pic.pump_reported_qext_kw
    relative_gap = abs(pic.pump_reported_qext_kw - eb.pump_physical_enthalpy_kw) / eb.pump_physical_enthalpy_kw
    assert relative_gap > 0.02  # the ~2.79%/2.82% reporting-vs-physical gap, clearly non-negligible


def test_mass_balance_residual_is_machine_precision():
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)
    assert result.mass_balance.residual_fraction < 1e-9
    assert result.mass_balance.passed is True


# ── Convergence handling ────────────────────────────────────────────────────
def test_absurd_demand_produces_thermal_pipeflow_not_converged():
    bp = _blueprint(consumer_demands_kw={**_DEMANDS, "consumer_1": 1e9})
    result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == BaselineFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED
    assert result.blueprint == bp


def test_evaluation_never_raises_for_any_contrived_input():
    scenarios = [
        _blueprint(consumer_demands_kw={**_DEMANDS, "consumer_1": 1e9}),
        _blueprint(p_supply_bar_abs=4.4),
        _blueprint(p_supply_bar_abs=10.0, trunk_pipe_dn_mm=100.0),
        _blueprint(pipe_heat_transfer_coefficient_w_per_m2k=10.0),
    ]
    for bp in scenarios:
        try:
            result = run_baseline_evaluation(bp, tolerances=_tolerances())
        except Exception as exc:  # pragma: no cover - must never happen
            pytest.fail(f"run_baseline_evaluation raised {exc!r} instead of returning a typed failure")
        assert result.status == "failure"


# ── Each of the six failure codes, individually isolated ──────────────────
def test_consumer_temperature_not_met():
    bp = _blueprint(pipe_heat_transfer_coefficient_w_per_m2k=10.0)
    result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == BaselineFailureCode.CONSUMER_TEMPERATURE_NOT_MET
    assert result.details["consumer_id"] == "consumer_4"
    assert result.details["supply_temperature_drop_k"] > result.details["max_consumer_supply_drop_k"]


def test_pressure_limit_exceeded():
    bp = _blueprint(p_supply_bar_abs=4.4)
    result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == BaselineFailureCode.PRESSURE_LIMIT_EXCEEDED
    assert result.details["pressure_bar_abs"] < result.details["min_pressure_bar_abs"]


def test_velocity_limit_exceeded():
    bp = _blueprint(p_supply_bar_abs=10.0, trunk_pipe_dn_mm=100.0)
    result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == BaselineFailureCode.VELOCITY_LIMIT_EXCEEDED
    assert result.details["velocity_m_s"] > result.details["max_pipe_velocity_m_s"]


def test_mass_balance_failed_via_artificially_tight_tolerance():
    """Proves the gate is reachable and correctly wired -- the TRUE residual
    is nowhere near the default tolerance (see test_mass_balance_residual_is_machine_precision)."""
    bp = _blueprint()
    tight = _tolerances().model_copy(update={"mass_balance_tolerance_fraction": 1e-18})
    result = run_baseline_evaluation(bp, tolerances=tight)
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == BaselineFailureCode.MASS_BALANCE_FAILED
    assert result.details["residual_fraction"] > result.details["tolerance_fraction"]


def test_energy_balance_failed_via_artificially_tight_tolerance():
    bp = _blueprint()
    tight = _tolerances().model_copy(update={"energy_balance_tolerance_fraction": 1e-18})
    result = run_baseline_evaluation(bp, tolerances=tight)
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == BaselineFailureCode.ENERGY_BALANCE_FAILED
    assert result.details["residual_fraction"] > result.details["tolerance_fraction"]


def test_all_six_failure_codes_covered():
    assert {c.value for c in BaselineFailureCode} == {
        "THERMAL_PIPEFLOW_NOT_CONVERGED", "CONSUMER_TEMPERATURE_NOT_MET",
        "PRESSURE_LIMIT_EXCEEDED", "VELOCITY_LIMIT_EXCEEDED",
        "MASS_BALANCE_FAILED", "ENERGY_BALANCE_FAILED",
    }


# ── to_absolute_bar()-only discipline ───────────────────────────────────────
def test_baseline_module_never_does_inline_pressure_arithmetic():
    """Every pressure conversion must go through pressure.py's
    to_absolute_bar()/to_gauge_bar() -- never a raw +/- 1.01325 literal."""
    source = _BASELINE_SRC_PATH.read_text()
    assert "1.01325" not in source
    assert "to_absolute_bar" in source  # sanity: the function IS used
    # No raw arithmetic on a variable named like a pressure, outside the import line.
    import_line = "from .pressure import to_absolute_bar"
    assert import_line in source
    body = source.replace(import_line, "")
    assert not re.search(r"p_bar\s*[+-]\s*\d", body)


# ── Determinism and non-mutation ────────────────────────────────────────────
def test_evaluation_does_not_mutate_the_blueprint():
    bp = _blueprint()
    snapshot = bp.model_dump_json()
    run_baseline_evaluation(bp, tolerances=_tolerances())
    assert bp.model_dump_json() == snapshot


def test_two_evaluations_of_the_same_blueprint_are_bit_identical():
    fixed_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bp = _blueprint(created_at=fixed_created_at)
    tolerances = _tolerances()

    result_1 = run_baseline_evaluation(bp, tolerances=tolerances)
    result_2 = run_baseline_evaluation(bp, tolerances=tolerances)
    assert isinstance(result_1, BaselineNetworkResult) and isinstance(result_2, BaselineNetworkResult)

    payload_1 = json.loads(result_1.model_dump_json())
    payload_2 = json.loads(result_2.model_dump_json())
    del payload_1["created_at"], payload_2["created_at"]
    assert payload_1 == payload_2


def test_independent_evaluations_do_not_interfere():
    bp_a = _blueprint()
    bp_b = _blueprint(p_supply_bar_abs=4.4)  # would fail
    result_a = run_baseline_evaluation(bp_a, tolerances=_tolerances())
    result_b = run_baseline_evaluation(bp_b, tolerances=_tolerances())
    assert isinstance(result_a, BaselineNetworkResult)
    assert isinstance(result_b, BaselineNetworkFailure)
    # Re-running A after B must still succeed identically (no shared mutable state).
    result_a_again = run_baseline_evaluation(bp_a, tolerances=_tolerances())
    assert isinstance(result_a_again, BaselineNetworkResult)
    assert result_a_again.total_heat_delivered_kw == result_a.total_heat_delivered_kw


# ── Strict-JSON round trip ──────────────────────────────────────────────────
def test_strict_json_round_trip_for_success():
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    dumped = result.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["status"] == "success"
    restored = parse_baseline_result_json(dumped)
    assert isinstance(restored, BaselineNetworkResult)
    assert restored == result


_FAILURE_SCENARIOS = {
    BaselineFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED: lambda: _blueprint(consumer_demands_kw={**_DEMANDS, "consumer_1": 1e9}),
    BaselineFailureCode.CONSUMER_TEMPERATURE_NOT_MET: lambda: _blueprint(pipe_heat_transfer_coefficient_w_per_m2k=10.0),
    BaselineFailureCode.PRESSURE_LIMIT_EXCEEDED: lambda: _blueprint(p_supply_bar_abs=4.4),
    BaselineFailureCode.VELOCITY_LIMIT_EXCEEDED: lambda: _blueprint(p_supply_bar_abs=10.0, trunk_pipe_dn_mm=100.0),
}


@pytest.mark.parametrize("failure_code", list(_FAILURE_SCENARIOS))
def test_strict_json_round_trip_for_failure_codes(failure_code):
    bp = _FAILURE_SCENARIOS[failure_code]()
    result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == failure_code

    dumped = result.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["failure_code"] == failure_code.value
    restored = parse_baseline_result_json(dumped)
    assert isinstance(restored, BaselineNetworkFailure)
    assert restored == result


@pytest.mark.parametrize("tight_field,failure_code", [
    ("mass_balance_tolerance_fraction", BaselineFailureCode.MASS_BALANCE_FAILED),
    ("energy_balance_tolerance_fraction", BaselineFailureCode.ENERGY_BALANCE_FAILED),
])
def test_strict_json_round_trip_for_balance_failure_codes(tight_field, failure_code):
    tight = _tolerances().model_copy(update={tight_field: 1e-18})
    result = run_baseline_evaluation(_blueprint(), tolerances=tight)
    assert isinstance(result, BaselineNetworkFailure)
    assert result.failure_code == failure_code

    dumped = result.model_dump_json()
    payload = _strict_json_loads(dumped)
    restored = parse_baseline_result_json(dumped)
    assert restored == result


# ── Model-level tamper tests ────────────────────────────────────────────────
def _valid_success_payload() -> dict:
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)
    return json.loads(result.model_dump_json())


def test_control_untouched_payload_round_trips_cleanly():
    payload = _valid_success_payload()
    restored = parse_baseline_result_json(json.dumps(payload))
    assert isinstance(restored, BaselineNetworkResult)


def test_tamper_negative_heat_delivered_is_rejected():
    payload = _valid_success_payload()
    payload["consumers"]["consumer_1"]["heat_delivered_kw"] = -1.0
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_total_heat_delivered_inconsistent_with_sum_is_rejected():
    payload = _valid_success_payload()
    payload["total_heat_delivered_kw"] = 9999.0
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_min_pressure_inconsistent_with_junction_dict_is_rejected():
    payload = _valid_success_payload()
    payload["min_pressure_bar_abs"] = 0.5
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_max_velocity_inconsistent_with_pipe_dict_is_rejected():
    payload = _valid_success_payload()
    payload["max_velocity_m_s"] = 99.0
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_mass_balance_passed_flag_flipped_is_rejected():
    payload = _valid_success_payload()
    payload["mass_balance"]["passed"] = False
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_energy_balance_residual_inconsistent_is_rejected():
    payload = _valid_success_payload()
    payload["energy_balance"]["residual_fraction"] = 0.5
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_energy_balance_passed_but_residual_exceeds_tolerance_is_rejected():
    payload = _valid_success_payload()
    payload["energy_balance"]["residual_fraction"] = 0.5
    payload["energy_balance"]["passed"] = True  # inconsistent: 0.5 > tolerance_fraction
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_energy_balance_wrong_integration_segments_is_rejected():
    payload = _valid_success_payload()
    payload["energy_balance"]["integration_segments"] = 7
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_tamper_energy_balance_wrong_integration_method_is_rejected():
    payload = _valid_success_payload()
    payload["energy_balance"]["integration_method"] = "simpsons_rule"
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


@pytest.mark.parametrize("field_path", [
    ("consumers", "consumer_1", "heat_delivered_kw"),
    ("min_pressure_bar_abs",),
    ("max_velocity_m_s",),
    ("circulation_pump", "hydraulic_pumping_power_kw"),
])
def test_tamper_non_finite_values_are_rejected(field_path):
    payload = _valid_success_payload()
    node = payload
    for key in field_path[:-1]:
        node = node[key]
    node[field_path[-1]] = float("nan")
    dumped = json.dumps(payload)  # json.dumps emits non-standard "NaN" -- still parseable by json.loads
    with pytest.raises(ValidationError):
        parse_baseline_result_json(dumped)


def test_empty_consumers_dict_is_rejected():
    payload = _valid_success_payload()
    payload["consumers"] = {}
    with pytest.raises(ValidationError):
        parse_baseline_result_json(json.dumps(payload))


def test_models_are_frozen():
    result = run_baseline_evaluation(_blueprint(), tolerances=_tolerances())
    with pytest.raises(Exception):
        result.total_heat_delivered_kw = 0.0  # type: ignore[misc]

    failure = run_baseline_evaluation(
        _blueprint(consumer_demands_kw={**_DEMANDS, "consumer_1": 1e9}), tolerances=_tolerances(),
    )
    with pytest.raises(Exception):
        failure.message = "changed"  # type: ignore[misc]


# ── GateTolerances ───────────────────────────────────────────────────────────
def test_gate_tolerances_from_config_dict_reads_real_config():
    tolerances = _tolerances()
    config = _config()
    gates = config["gates"]
    assert tolerances.max_consumer_supply_drop_k == gates["max_consumer_supply_drop_k"]
    assert tolerances.min_pressure_bar_abs == gates["min_pressure_bar_abs"]
    assert tolerances.max_pipe_velocity_m_s == gates["max_pipe_velocity_m_s"]
    assert tolerances.mass_balance_tolerance_fraction == gates["mass_balance_tolerance_fraction"]
    assert tolerances.energy_balance_tolerance_fraction == gates["energy_balance_tolerance_fraction"]


@pytest.mark.parametrize("field", [
    "max_consumer_supply_drop_k", "min_pressure_bar_abs", "max_pipe_velocity_m_s",
    "mass_balance_tolerance_fraction", "energy_balance_tolerance_fraction",
])
def test_gate_tolerances_rejects_non_positive(field):
    kwargs = dict(
        max_consumer_supply_drop_k=5.0, min_pressure_bar_abs=1.5, max_pipe_velocity_m_s=1.5,
        mass_balance_tolerance_fraction=0.005, energy_balance_tolerance_fraction=0.02,
    )
    kwargs[field] = 0.0
    with pytest.raises(ValidationError):
        GateTolerances(**kwargs)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_gate_tolerances_rejects_non_finite(bad_value):
    with pytest.raises(ValidationError):
        GateTolerances(
            max_consumer_supply_drop_k=bad_value, min_pressure_bar_abs=1.5, max_pipe_velocity_m_s=1.5,
            mass_balance_tolerance_fraction=0.005, energy_balance_tolerance_fraction=0.02,
        )


# ── The true-enthalpy-integral correction: verified independently ──────────
def test_integrate_specific_heat_matches_hand_computed_exact_piecewise_linear_integral():
    """network/baseline.py::_integrate_specific_heat_j_per_kg is NOT
    delegated to pandapipes' own FluidProperty.get_at_integral_value()
    (see test_evaluator_never_calls_pandapipes_get_at_integral_value and
    docs/technical-observations/pandapipes-heat-capacity-integral-defect.md)
    -- it must independently reproduce the exact integral, computed here by
    hand from the water heat_capacity property table's own node
    temperatures (313, 323, 333, 343 K)."""
    pandapipes = pytest.importorskip("pandapipes")
    from pandapipes.properties.fluids import get_fluid
    from r3chain_geothermal.network.baseline import _integrate_specific_heat_j_per_kg

    net = pandapipes.create_empty_network(fluid="water")
    fluid = get_fluid(net)

    nodes = [313.15, 323.0, 333.0, 343.15]
    exact = 0.0
    for a, b in zip(nodes[:-1], nodes[1:]):
        cp_a, cp_b = fluid.get_heat_capacity(a), fluid.get_heat_capacity(b)
        exact += (cp_a + cp_b) / 2 * (b - a)

    computed = _integrate_specific_heat_j_per_kg(fluid, 313.15, 343.15, n_segments=100)
    assert computed == pytest.approx(exact, rel=1e-5)
    assert computed == pytest.approx(125516.7154, abs=1.0)


def test_integrate_specific_heat_zero_width_interval_is_zero():
    pandapipes = pytest.importorskip("pandapipes")
    from pandapipes.properties.fluids import get_fluid
    from r3chain_geothermal.network.baseline import _integrate_specific_heat_j_per_kg

    net = pandapipes.create_empty_network(fluid="water")
    fluid = get_fluid(net)
    assert _integrate_specific_heat_j_per_kg(fluid, 313.15, 313.15) == 0.0


def test_integrate_specific_heat_rejects_upper_below_lower():
    pandapipes = pytest.importorskip("pandapipes")
    from pandapipes.properties.fluids import get_fluid
    from r3chain_geothermal.network.baseline import _integrate_specific_heat_j_per_kg

    net = pandapipes.create_empty_network(fluid="water")
    fluid = get_fluid(net)
    with pytest.raises(ValueError):
        _integrate_specific_heat_j_per_kg(fluid, 343.15, 313.15)


def test_evaluator_never_calls_pandapipes_get_at_integral_value():
    """Structural test, NOT dependent on whether pandapipes' own
    get_at_integral_value() is currently buggy (docs/technical-observations/
    pandapipes-heat-capacity-integral-defect.md records the observed 0.14.0
    defect and a re-verification procedure -- it is not encoded as a
    permanent expected-failure test here). This project's correctness must
    hold whether that upstream helper is broken or a future release fixes
    it -- proven by simply never calling it: baseline.py's own integration
    (_integrate_specific_heat_j_per_kg) only ever calls
    fluid.get_heat_capacity()/get_at_value() for point evaluation, never
    get_at_integral_value().

    Uses AST call-site detection (not a plain substring search) so the
    module docstring is free to name get_at_integral_value() in prose
    (explaining why it is avoided) without tripping this check -- only an
    actual CALL expression would fail it."""
    tree = ast.parse(_BASELINE_SRC_PATH.read_text())
    call_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "get_at_integral_value" not in call_names


def test_integration_segment_count_converges_to_exact_integral():
    """Convergence/accuracy check for ENTHALPY_INTEGRATION_SEGMENTS: 100 and
    200 segments must both closely match the hand-computed exact
    piecewise-linear integral (using the property table's own node
    temperatures), and 200 must not meaningfully improve on 100 -- proving
    100 is not an under-resolved, unaudited choice."""
    pandapipes = pytest.importorskip("pandapipes")
    from pandapipes.properties.fluids import get_fluid
    from r3chain_geothermal.network.baseline import _integrate_specific_heat_j_per_kg

    net = pandapipes.create_empty_network(fluid="water")
    fluid = get_fluid(net)

    nodes = [313.15, 323.0, 333.0, 343.15]
    exact = 0.0
    for a, b in zip(nodes[:-1], nodes[1:]):
        cp_a, cp_b = fluid.get_heat_capacity(a), fluid.get_heat_capacity(b)
        exact += (cp_a + cp_b) / 2 * (b - a)

    at_100 = _integrate_specific_heat_j_per_kg(fluid, 313.15, 343.15, n_segments=100)
    at_200 = _integrate_specific_heat_j_per_kg(fluid, 313.15, 343.15, n_segments=200)

    assert at_100 == pytest.approx(exact, rel=1e-5)
    assert at_200 == pytest.approx(exact, rel=1e-5)
    # 100 -> 200 segments changes the result by a negligible amount relative
    # to the already-tiny error against the exact integral.
    assert abs(at_200 - at_100) / exact < 1e-5
