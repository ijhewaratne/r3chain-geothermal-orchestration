"""Tests for network/blueprint.py -- NetworkBlueprint model invariants and
the build_default_blueprint() factory (T2.2)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r3chain_geothermal.network.blueprint import (
    BlueprintCandidate,
    BlueprintConsumer,
    BlueprintJunction,
    BlueprintPipe,
    CirculationPumpSpec,
    NetworkBlueprint,
    NetworkBuildParameters,
    build_default_blueprint,
)

_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


def _default_blueprint() -> NetworkBlueprint:
    return build_default_blueprint(
        consumer_demands_kw=_DEMANDS,
        trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
        created_at=datetime.now(timezone.utc),
    )


# ── Structural correctness of the default blueprint ────────────────────────
def test_default_blueprint_has_expected_counts():
    bp = _default_blueprint()
    assert len(bp.junctions) == 18  # 5 trunk + 5 ret_trunk + 4 consumer + 4 ret_consumer
    assert len(bp.pipes) == 16  # 4 supply_trunk + 4 return_trunk + 4 supply_branch + 4 return_branch
    assert len(bp.consumers) == 4
    assert len(bp.candidates) == 4


def test_default_blueprint_consumer_demands_match_input():
    bp = _default_blueprint()
    for consumer_id, demand_kw in _DEMANDS.items():
        assert bp.consumers[consumer_id].demand_kw == demand_kw
        assert bp.consumers[consumer_id].design_delta_t_k == 30.0


def test_default_blueprint_candidate_junction_pairs_reference_real_junctions():
    bp = _default_blueprint()
    for candidate in bp.candidates.values():
        assert candidate.supply_junction in bp.junctions
        assert candidate.return_junction in bp.junctions
        assert candidate.surface_connection_length_m > 0


def test_default_blueprint_pipe_lengths_match_geometry():
    bp = _default_blueprint()
    trunk_pipes = [p for p in bp.pipes.values() if p.role == "supply_trunk"]
    assert len(trunk_pipes) == 4
    for p in trunk_pipes:
        assert p.length_m == pytest.approx(250.0)
    branch_pipes = [p for p in bp.pipes.values() if p.role == "supply_branch"]
    for p in branch_pipes:
        assert p.length_m == pytest.approx(80.0)


def test_default_blueprint_round_trips_through_strict_json():
    bp = _default_blueprint()
    dumped = bp.model_dump_json()

    def _reject(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")
    json.loads(dumped, parse_constant=_reject)  # must not contain NaN/Infinity

    restored = NetworkBlueprint.model_validate_json(dumped)
    assert restored == bp


def test_blueprint_is_frozen():
    bp = _default_blueprint()
    with pytest.raises(Exception):
        bp.blueprint_schema_version = "9.9.9"  # type: ignore[misc]


def test_blueprint_forbids_extra_fields():
    with pytest.raises(ValidationError):
        BlueprintJunction(id="x", x_m=0.0, y_m=0.0, side="supply", kind="trunk", extra_field=1)  # type: ignore[call-arg]


# ── Referential-integrity / positivity invariants ───────────────────────────
def _minimal_valid_kwargs():
    j1 = BlueprintJunction(id="j1", x_m=0.0, y_m=0.0, side="supply", kind="plant")
    j2 = BlueprintJunction(id="j2", x_m=100.0, y_m=0.0, side="supply", kind="trunk")
    rj1 = BlueprintJunction(id="rj1", x_m=0.0, y_m=-10.0, side="return", kind="plant")
    rj2 = BlueprintJunction(id="rj2", x_m=100.0, y_m=-10.0, side="return", kind="trunk")
    cj = BlueprintJunction(id="cj", x_m=100.0, y_m=50.0, side="supply", kind="consumer")
    rcj = BlueprintJunction(id="rcj", x_m=100.0, y_m=-50.0, side="return", kind="consumer")
    junctions = {j.id: j for j in [j1, j2, rj1, rj2, cj, rcj]}
    pipes = {
        "p1": BlueprintPipe(id="p1", from_junction="j1", to_junction="j2", length_m=100.0, inner_diameter_mm=150.0, role="supply_trunk"),
        "p2": BlueprintPipe(id="p2", from_junction="rj2", to_junction="rj1", length_m=100.0, inner_diameter_mm=150.0, role="return_trunk"),
        "p3": BlueprintPipe(id="p3", from_junction="j2", to_junction="cj", length_m=50.0, inner_diameter_mm=100.0, role="supply_branch"),
        "p4": BlueprintPipe(id="p4", from_junction="rcj", to_junction="rj2", length_m=50.0, inner_diameter_mm=100.0, role="return_branch"),
    }
    consumers = {"c1": BlueprintConsumer(id="c1", supply_junction="cj", return_junction="rcj", demand_kw=100.0, design_delta_t_k=30.0)}
    candidates = {"C1": BlueprintCandidate(id="C1", label="test", supply_junction="j2", return_junction="rj2", surface_connection_length_m=10.0)}
    pump = CirculationPumpSpec(return_junction="rj1", flow_junction="j1", p_flow_bar_abs=6.0, pressure_lift_bar=3.0, flow_temperature_c=70.0)
    build_params = NetworkBuildParameters(
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
    )
    return dict(
        junctions=junctions, pipes=pipes, consumers=consumers, candidates=candidates,
        circulation_pump=pump, build_parameters=build_params, created_at=datetime.now(timezone.utc),
    )


def test_minimal_valid_blueprint_constructs_successfully():
    NetworkBlueprint(**_minimal_valid_kwargs())


def test_pipe_referencing_missing_junction_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["pipes"]["p1"] = BlueprintPipe(
        id="p1", from_junction="does_not_exist", to_junction="j2", length_m=100.0,
        inner_diameter_mm=150.0, role="supply_trunk",
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_candidate_referencing_missing_junction_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["candidates"]["C1"] = BlueprintCandidate(
        id="C1", label="test", supply_junction="ghost", return_junction="rj2", surface_connection_length_m=10.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_consumer_referencing_missing_junction_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["consumers"]["c1"] = BlueprintConsumer(
        id="c1", supply_junction="ghost", return_junction="rcj", demand_kw=100.0, design_delta_t_k=30.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_non_positive_pipe_length_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["pipes"]["p1"] = BlueprintPipe(
        id="p1", from_junction="j1", to_junction="j2", length_m=0.0, inner_diameter_mm=150.0, role="supply_trunk",
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_non_positive_consumer_demand_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["consumers"]["c1"] = BlueprintConsumer(
        id="c1", supply_junction="cj", return_junction="rcj", demand_kw=0.0, design_delta_t_k=30.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_non_positive_candidate_connection_length_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["candidates"]["C1"] = BlueprintCandidate(
        id="C1", label="test", supply_junction="j2", return_junction="rj2", surface_connection_length_m=0.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_supply_temperature_not_greater_than_return_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["build_parameters"] = NetworkBuildParameters(
        supply_temperature_c=40.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_junction_dict_key_must_match_its_own_id():
    kwargs = _minimal_valid_kwargs()
    kwargs["junctions"]["wrong_key"] = kwargs["junctions"].pop("j1")
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


# ── Dict key == id, for pipes/consumers/candidates too (not only junctions) ─
def test_pipe_dict_key_must_match_its_own_id():
    kwargs = _minimal_valid_kwargs()
    kwargs["pipes"]["wrong_key"] = kwargs["pipes"].pop("p1")
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_consumer_dict_key_must_match_its_own_id():
    kwargs = _minimal_valid_kwargs()
    kwargs["consumers"]["wrong_key"] = kwargs["consumers"].pop("c1")
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_candidate_dict_key_must_match_its_own_id():
    kwargs = _minimal_valid_kwargs()
    kwargs["candidates"]["wrong_key"] = kwargs["candidates"].pop("C1")
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


# ── Non-finite (NaN/Infinity) values rejected everywhere (allow_inf_nan=False) ──
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_junction_coordinates_reject_non_finite(bad_value):
    with pytest.raises(ValidationError):
        BlueprintJunction(id="x", x_m=bad_value, y_m=0.0, side="supply", kind="trunk")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_pipe_length_rejects_non_finite(bad_value):
    with pytest.raises(ValidationError):
        BlueprintPipe(
            id="p", from_junction="a", to_junction="b", length_m=bad_value,
            inner_diameter_mm=100.0, role="supply_trunk",
        )


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_consumer_demand_rejects_non_finite(bad_value):
    with pytest.raises(ValidationError):
        BlueprintConsumer(id="c", supply_junction="a", return_junction="b", demand_kw=bad_value, design_delta_t_k=30.0)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_candidate_connection_length_rejects_non_finite(bad_value):
    with pytest.raises(ValidationError):
        BlueprintCandidate(id="C", label="x", supply_junction="a", return_junction="b", surface_connection_length_m=bad_value)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_circulation_pump_pressure_rejects_non_finite(bad_value):
    with pytest.raises(ValidationError):
        CirculationPumpSpec(return_junction="a", flow_junction="b", p_flow_bar_abs=bad_value, pressure_lift_bar=3.0, flow_temperature_c=70.0)


def test_blueprint_with_non_finite_value_injected_via_json_is_rejected():
    """End-to-end: a hand-tampered JSON payload with a NaN-equivalent
    (Infinity, since JSON itself has no NaN literal support in strict mode --
    but Python's json.dumps CAN emit non-standard 'NaN'/'Infinity' tokens,
    which allow_inf_nan=False must still reject on model_validate_json)."""
    bp = _default_blueprint()
    payload = bp.model_dump_json()
    tampered = payload.replace('"x_m":0.0', '"x_m":Infinity', 1)
    if tampered == payload:  # no exact zero present; fall back to a known coordinate
        tampered = payload.replace('"x_m":250.0', '"x_m":Infinity', 1)
    with pytest.raises(ValidationError):
        NetworkBlueprint.model_validate_json(tampered)


# ── Junction side correctness (swapped supply/return) ───────────────────────
def test_consumer_supply_junction_must_be_side_supply():
    kwargs = _minimal_valid_kwargs()
    kwargs["consumers"]["c1"] = BlueprintConsumer(
        id="c1", supply_junction="rcj", return_junction="cj", demand_kw=100.0, design_delta_t_k=30.0,
    )  # swapped: supply_junction points at a side="return" junction
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_consumer_return_junction_must_be_side_return():
    kwargs = _minimal_valid_kwargs()
    kwargs["consumers"]["c1"] = BlueprintConsumer(
        id="c1", supply_junction="cj", return_junction="j2", demand_kw=100.0, design_delta_t_k=30.0,
    )  # return_junction points at a side="supply" junction
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_candidate_supply_and_return_junctions_swapped_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["candidates"]["C1"] = BlueprintCandidate(
        id="C1", label="test", supply_junction="rj2", return_junction="j2", surface_connection_length_m=10.0,
    )  # swapped
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_circulation_pump_flow_junction_must_be_side_supply():
    kwargs = _minimal_valid_kwargs()
    kwargs["circulation_pump"] = CirculationPumpSpec(
        return_junction="rj1", flow_junction="rj2",  # flow_junction is side="return"
        p_flow_bar_abs=6.0, pressure_lift_bar=3.0, flow_temperature_c=70.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_circulation_pump_return_junction_must_be_side_return():
    kwargs = _minimal_valid_kwargs()
    kwargs["circulation_pump"] = CirculationPumpSpec(
        return_junction="j1", flow_junction="j2",  # return_junction is side="supply"
        p_flow_bar_abs=6.0, pressure_lift_bar=3.0, flow_temperature_c=70.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


# ── Pipe role must agree with endpoint sides ────────────────────────────────
def test_supply_role_pipe_connecting_two_return_junctions_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["pipes"]["p1"] = BlueprintPipe(
        id="p1", from_junction="rj1", to_junction="rj2", length_m=100.0,
        inner_diameter_mm=150.0, role="supply_trunk",  # role says supply, endpoints are return
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_return_role_pipe_connecting_two_supply_junctions_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["pipes"]["p2"] = BlueprintPipe(
        id="p2", from_junction="j1", to_junction="j2", length_m=100.0,
        inner_diameter_mm=150.0, role="return_trunk",  # role says return, endpoints are supply
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_pipe_mixing_supply_and_return_endpoint_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["pipes"]["p1"] = BlueprintPipe(
        id="p1", from_junction="j1", to_junction="rj2", length_m=100.0,
        inner_diameter_mm=150.0, role="supply_trunk",
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


# ── Self-loops and identical supply/return junctions rejected ──────────────
def test_self_loop_pipe_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["pipes"]["p1"] = BlueprintPipe(
        id="p1", from_junction="j1", to_junction="j1", length_m=100.0,
        inner_diameter_mm=150.0, role="supply_trunk",
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_consumer_identical_supply_and_return_junction_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["consumers"]["c1"] = BlueprintConsumer(
        id="c1", supply_junction="cj", return_junction="cj", demand_kw=100.0, design_delta_t_k=30.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_candidate_identical_supply_and_return_junction_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["candidates"]["C1"] = BlueprintCandidate(
        id="C1", label="test", supply_junction="j2", return_junction="j2", surface_connection_length_m=10.0,
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


def test_circulation_pump_identical_flow_and_return_junction_is_rejected():
    kwargs = _minimal_valid_kwargs()
    kwargs["circulation_pump"] = CirculationPumpSpec(
        return_junction="j1", flow_junction="j1",  # both "j1" -- also wrong side, but this must
        p_flow_bar_abs=6.0, pressure_lift_bar=3.0, flow_temperature_c=70.0,  # still be caught even if side happened to be right
    )
    with pytest.raises(ValidationError):
        NetworkBlueprint(**kwargs)


# ── Factory: consumer_demands_kw key validation (deliberate ValueError) ────
def test_build_default_blueprint_missing_consumer_key_raises_value_error():
    demands = dict(_DEMANDS)
    del demands["consumer_3"]
    with pytest.raises(ValueError, match="consumer_3"):
        build_default_blueprint(
            consumer_demands_kw=demands,
            trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
            supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
            pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
            p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
            created_at=datetime.now(timezone.utc),
        )


def test_build_default_blueprint_extra_consumer_key_raises_value_error():
    demands = dict(_DEMANDS)
    demands["consumer_5_unexpected"] = 100.0
    with pytest.raises(ValueError, match="consumer_5_unexpected"):
        build_default_blueprint(
            consumer_demands_kw=demands,
            trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
            supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
            pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
            p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
            created_at=datetime.now(timezone.utc),
        )


def test_build_default_blueprint_empty_demands_raises_value_error():
    with pytest.raises(ValueError, match="consumer_demands_kw"):
        build_default_blueprint(
            consumer_demands_kw={},
            trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
            supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
            pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
            p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
            created_at=datetime.now(timezone.utc),
        )
