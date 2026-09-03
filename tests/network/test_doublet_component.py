"""Full test matrix for network/doublet_component.py -- the DLT-001..007
reusable geothermal-doublet-connection composite.

Parity (DLT-006/AC-07) is the central concern of this file: this module
and network/candidate.py::evaluate_candidate() share the same underlying
private functions, so results must be BIT-IDENTICAL (not merely within a
declared tolerance) for the golden worked case and its DSP-005
self-consistent-mode counterpart.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from r3chain_geothermal.adapter.heat_exchanger import HeatExchangerCouplingResult
from r3chain_geothermal.contracts import PyDoubletCouplingResult, SourceProvenance
from r3chain_geothermal.network import (
    DOUBLET_COMPONENT_CONTRACT_SCHEMA_VERSION,
    BlueprintCandidate,
    CandidateEvaluationResult,
    CandidateFailureCode,
    DistrictHeatingConnectionSpec,
    DoubletOperatingPolicy,
    GateTolerances,
    GeothermalDoubletFailure,
    GeothermalDoubletResult,
    GeothermalDoubletSpec,
    GeothermalInjectionPolicy,
    HeatExchangerBoundary,
    build_and_evaluate_geothermal_doublet,
    build_default_blueprint,
    evaluate_candidate,
    parse_doublet_component_result_json,
    run_baseline_evaluation,
)
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}
_CANDIDATES = {
    "C1": ("trunk_1", "ret_trunk_1", 50.0), "C2": ("trunk_2", "ret_trunk_2", 70.0),
    "C3": ("trunk_3", "ret_trunk_3", 90.0), "C4": ("trunk_4", "ret_trunk_4", 120.0),
}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _tolerances() -> GateTolerances:
    return GateTolerances.from_config_dict(_config())


def _policy(**overrides) -> GeothermalInjectionPolicy:
    base = dict(
        curtailment_allowed=True, auxiliary_policy="cost_shortfall",
        minimum_auxiliary_circulation_fraction=0.01, heat_delivery_tolerance_fraction=0.01,
    )
    base.update(overrides)
    return GeothermalInjectionPolicy(**base)


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


def _candidate(candidate_id: str) -> BlueprintCandidate:
    supply, ret, length = _CANDIDATES[candidate_id]
    return BlueprintCandidate(
        id=candidate_id, label=candidate_id, supply_junction=supply, return_junction=ret,
        surface_connection_length_m=length,
    )


def _golden_coupling_result(**assumption_overrides) -> HeatExchangerCouplingResult:
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired", calculation_mode="deterministic",
    )
    coupling_input = parse_pydoublet_result(raw, source_provenance=provenance)
    assert isinstance(coupling_input, PyDoubletCouplingResult)

    config = _config()
    assumptions = CouplingAssumptions.from_config_dict(config)
    if assumption_overrides:
        assumptions = assumptions.model_copy(update=assumption_overrides)

    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingResult)
    return result


def _spec(coupling_result: HeatExchangerCouplingResult) -> GeothermalDoubletSpec:
    ci = coupling_result.coupling_input
    return GeothermalDoubletSpec(
        producer_wellhead_temperature_c=ci.producer_wellhead_temperature_c.value,
        brine_mass_flow_kg_s=ci.geothermal_brine_mass_flow_kg_s.value,
        brine_specific_heat_capacity_j_kg_k=ci.geothermal_brine_specific_heat_capacity_j_kg_k.value,
        raw_geothermal_thermal_power_kw=ci.raw_geothermal_thermal_power_kw.value,
        minimum_reinjection_temperature_c=coupling_result.assumptions.reinjection_minimum_temperature_c,
        doublet_pump_electric_power_kw=ci.doublet_pump_electric_power_kw.value,
    )


def _boundary(coupling_result: HeatExchangerCouplingResult) -> HeatExchangerBoundary:
    return HeatExchangerBoundary(
        minimum_hx_approach_k=coupling_result.assumptions.minimum_hx_approach_k,
        hx_heat_delivery_factor=coupling_result.assumptions.hx_heat_delivery_factor,
        deliverable_geothermal_heat_kw=coupling_result.deliverable_geothermal_heat_kw.value,
    )


def _connection(coupling_result: HeatExchangerCouplingResult, candidate_id: str) -> DistrictHeatingConnectionSpec:
    return DistrictHeatingConnectionSpec(
        candidate=_candidate(candidate_id),
        dh_supply_temperature_c=coupling_result.assumptions.dh_supply_temperature_c,
        dh_return_temperature_c=coupling_result.assumptions.dh_return_temperature_c,
        dh_water_specific_heat_capacity_j_kg_k=coupling_result.assumptions.dh_water_specific_heat_capacity_j_kg_k,
    )


# ── DLT-006/AC-07: parity with network/candidate.py::evaluate_candidate() ──
@pytest.mark.parametrize("candidate_id", list(_CANDIDATES))
@pytest.mark.parametrize("injection_sizing_policy", ["fixed_design_temperature", "self_consistent"])
def test_parity_with_evaluate_candidate(candidate_id, injection_sizing_policy):
    bp = _blueprint()
    baseline_result = run_baseline_evaluation(bp, tolerances=_tolerances())
    coupling_result = _golden_coupling_result()

    reference = evaluate_candidate(
        coupling_result, bp, _candidate(candidate_id), baseline_result,
        injection_policy=_policy(injection_sizing_policy=injection_sizing_policy), tolerances=_tolerances(),
    )
    assert isinstance(reference, CandidateEvaluationResult)

    component_result = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, candidate_id),
        DoubletOperatingPolicy(
            accepted_heat_kw=reference.geothermal_injected_heat_kw, injection_sizing_policy=injection_sizing_policy,
        ),
    )
    assert isinstance(component_result, GeothermalDoubletResult), component_result

    assert math.isclose(
        component_result.district_heating_water_mass_flow_kg_s,
        reference.district_heating_water_mass_flow_injected_kg_s, rel_tol=1e-12,
    )
    assert math.isclose(component_result.inlet_temperature_c, reference.geothermal_injection_inlet_temperature_c, rel_tol=1e-12)
    assert math.isclose(component_result.outlet_temperature_c, reference.geothermal_injection_outlet_temperature_c, rel_tol=1e-12)
    assert math.isclose(
        component_result.connection_differential_pressure_bar, reference.connection_pressure_drop_bar, rel_tol=1e-12,
    )
    assert math.isclose(
        component_result.circulation_pump_hydraulic_power_kw, reference.connection_pumping_power_kw, rel_tol=1e-12,
    )
    assert component_result.flow_solver.enabled == reference.flow_solver.enabled
    assert component_result.flow_solver.iteration_count == reference.flow_solver.iteration_count
    assert math.isclose(
        component_result.flow_solver.final_mass_flow_kg_s, reference.flow_solver.final_mass_flow_kg_s, rel_tol=1e-12,
    )
    assert math.isclose(
        component_result.available_geothermal_heat_kw, coupling_result.deliverable_geothermal_heat_kw.value, rel_tol=1e-12,
    )
    assert math.isclose(component_result.accepted_heat_kw, reference.geothermal_injected_heat_kw, rel_tol=1e-12)
    assert math.isclose(component_result.curtailed_heat_kw, reference.geothermal_curtailed_heat_kw, rel_tol=1e-9)


# ── DLT-004: isolation and idempotence ───────────────────────────────────────
def test_does_not_mutate_the_blueprint():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline_result = run_baseline_evaluation(bp, tolerances=_tolerances())
    reference = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline_result,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(reference, CandidateEvaluationResult)
    bp_snapshot = bp.model_dump_json()
    for candidate_id in ("C1", "C2", "C3", "C4"):
        build_and_evaluate_geothermal_doublet(
            bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, candidate_id),
            DoubletOperatingPolicy(accepted_heat_kw=reference.geothermal_injected_heat_kw),
        )
    assert bp.model_dump_json() == bp_snapshot


def test_repeated_calls_are_bit_identical():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    policy = DoubletOperatingPolicy(accepted_heat_kw=3168.0)
    result_1 = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"), policy,
    )
    result_2 = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"), policy,
    )
    assert isinstance(result_1, GeothermalDoubletResult) and isinstance(result_2, GeothermalDoubletResult)
    payload_1 = json.loads(result_1.model_dump_json())
    payload_2 = json.loads(result_2.model_dump_json())
    del payload_1["created_at"], payload_2["created_at"]
    assert payload_1 == payload_2


def test_evaluating_multiple_candidates_does_not_cross_contaminate():
    """Two different candidates against the SAME blueprint must produce
    independent, non-identical connection-pressure-drop figures (a
    regression guard against accidentally sharing pandapipes net state
    across calls)."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    policy = DoubletOperatingPolicy(accepted_heat_kw=3168.0)
    result_c1 = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"), policy,
    )
    result_c4 = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C4"), policy,
    )
    assert isinstance(result_c1, GeothermalDoubletResult) and isinstance(result_c4, GeothermalDoubletResult)
    assert result_c1.connection_differential_pressure_bar != result_c4.connection_differential_pressure_bar


# ── Failure surface ──────────────────────────────────────────────────────────
def test_thermal_pipeflow_not_converged(monkeypatch):
    import r3chain_geothermal.network.candidate as candidate_module
    monkeypatch.setattr(candidate_module, "CONNECTION_PIPE_DN_MM", 1.0)
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    result = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"),
        DoubletOperatingPolicy(accepted_heat_kw=3168.0),
    )
    assert isinstance(result, GeothermalDoubletFailure)
    assert result.failure_code == CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED


def test_geothermal_injection_hydraulic_conflict():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    # Requesting the full deliverable heat (no curtailment margin at all)
    # reproduces network/candidate.py's own documented "reason 1" conflict.
    result = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"),
        DoubletOperatingPolicy(accepted_heat_kw=coupling_result.deliverable_geothermal_heat_kw.value),
    )
    assert isinstance(result, GeothermalDoubletFailure)
    assert result.failure_code == CandidateFailureCode.GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT


def test_self_consistent_flow_not_converged(monkeypatch):
    """_solve_self_consistent_injection() (network/candidate.py) reads
    SELF_CONSISTENT_FLOW_MAX_ITERATIONS as its own module-level constant,
    not a parameter -- patching it there is what actually bounds the
    solve; DoubletOperatingPolicy.max_iterations is a self-documenting
    record of the value used (see its own docstring), not itself an input
    to the solver, so it is left at its default (which must, and does,
    still equal the -- now-patched-in-candidate.py-only -- module
    constant's ORIGINAL value; the mismatch this would otherwise create
    is exactly why DoubletOperatingPolicy validates against
    network.candidate's constant directly rather than silently drifting)."""
    import r3chain_geothermal.network.candidate as candidate_module
    monkeypatch.setattr(candidate_module, "SELF_CONSISTENT_FLOW_MAX_ITERATIONS", 1)
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    result = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"),
        DoubletOperatingPolicy(accepted_heat_kw=3168.0, injection_sizing_policy="self_consistent"),
    )
    assert isinstance(result, GeothermalDoubletFailure)
    assert result.failure_code == CandidateFailureCode.SELF_CONSISTENT_FLOW_NOT_CONVERGED


# ── Model validation ─────────────────────────────────────────────────────────
def test_doublet_operating_policy_rejects_a_tolerance_override():
    with pytest.raises(ValidationError):
        DoubletOperatingPolicy(accepted_heat_kw=3168.0, outlet_temperature_tolerance_k=1.0)


def test_doublet_operating_policy_rejects_non_positive_accepted_heat():
    with pytest.raises(ValidationError):
        DoubletOperatingPolicy(accepted_heat_kw=0.0)


def test_heat_exchanger_boundary_rejects_out_of_range_delivery_factor():
    with pytest.raises(ValidationError):
        HeatExchangerBoundary(minimum_hx_approach_k=5.0, hx_heat_delivery_factor=1.5, deliverable_geothermal_heat_kw=3000.0)


def test_district_heating_connection_spec_rejects_inverted_temperatures():
    with pytest.raises(ValidationError):
        DistrictHeatingConnectionSpec(
            candidate=_candidate("C1"), dh_supply_temperature_c=40.0, dh_return_temperature_c=70.0,
            dh_water_specific_heat_capacity_j_kg_k=4180.0,
        )


# ── Strict-JSON round trip ───────────────────────────────────────────────────
def test_strict_json_round_trip_for_success():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    result = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"),
        DoubletOperatingPolicy(accepted_heat_kw=3168.0),
    )
    assert isinstance(result, GeothermalDoubletResult)
    dumped = result.model_dump_json()
    restored = parse_doublet_component_result_json(dumped)
    assert isinstance(restored, GeothermalDoubletResult)
    assert restored == result
    assert result.contract_schema_version == DOUBLET_COMPONENT_CONTRACT_SCHEMA_VERSION


def test_strict_json_round_trip_for_failure():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    result = build_and_evaluate_geothermal_doublet(
        bp, _spec(coupling_result), _boundary(coupling_result), _connection(coupling_result, "C1"),
        DoubletOperatingPolicy(accepted_heat_kw=coupling_result.deliverable_geothermal_heat_kw.value),
    )
    assert isinstance(result, GeothermalDoubletFailure)
    dumped = result.model_dump_json()
    restored = parse_doublet_component_result_json(dumped)
    assert isinstance(restored, GeothermalDoubletFailure)
    assert restored == result
