"""Tests for network/builder.py -- build_pandapipes_net() structural
correctness and a real convergence smoke test (T2.2A)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

pandapipes = pytest.importorskip("pandapipes")

from r3chain_geothermal.network.blueprint import build_default_blueprint
from r3chain_geothermal.network.builder import build_pandapipes_net
from r3chain_geothermal.network.pressure import to_absolute_bar

_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


def _default_blueprint():
    return build_default_blueprint(
        consumer_demands_kw=_DEMANDS,
        trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
        created_at=datetime.now(timezone.utc),
    )


def test_builder_produces_correct_element_counts():
    bp = _default_blueprint()
    net = build_pandapipes_net(bp)
    assert len(net.junction) == 18
    assert len(net.pipe) == 16
    assert len(net.heat_consumer) == 4
    assert len(net.circ_pump_pressure) == 1


def test_builder_pipe_lengths_and_diameters_match_blueprint_exactly():
    bp = _default_blueprint()
    net = build_pandapipes_net(bp)
    pipe_by_name = {name: idx for idx, name in enumerate(net.pipe["name"])}
    for pipe_id, pipe in bp.pipes.items():
        idx = pipe_by_name[pipe_id]
        assert net.pipe.loc[idx, "length_km"] == pytest.approx(pipe.length_m / 1000.0)
        assert net.pipe.loc[idx, "inner_diameter_mm"] == pytest.approx(pipe.inner_diameter_mm)


def test_builder_mirrored_return_network_structure():
    bp = _default_blueprint()
    net = build_pandapipes_net(bp)
    junction_names = set(net.junction["name"])
    for trunk_id in ["trunk_0", "trunk_1", "trunk_2", "trunk_3", "trunk_4"]:
        assert trunk_id in junction_names
        assert f"ret_{trunk_id}" in junction_names
    for consumer_id in _DEMANDS:
        assert consumer_id in junction_names
        assert f"ret_{consumer_id}" in junction_names

    pipe_names = set(net.pipe["name"])
    supply_trunk_pipes = {p.id for p in bp.pipes.values() if p.role == "supply_trunk"}
    return_trunk_pipes = {p.id for p in bp.pipes.values() if p.role == "return_trunk"}
    assert len(supply_trunk_pipes) == len(return_trunk_pipes) == 4
    assert supply_trunk_pipes <= pipe_names
    assert return_trunk_pipes <= pipe_names


def test_builder_heat_consumer_qext_and_deltat_match_blueprint():
    bp = _default_blueprint()
    net = build_pandapipes_net(bp)
    hc_by_name = {name: idx for idx, name in enumerate(net.heat_consumer["name"])}
    for consumer_id, consumer in bp.consumers.items():
        idx = hc_by_name[consumer_id]
        assert net.heat_consumer.loc[idx, "qext_w"] == pytest.approx(consumer.demand_kw * 1000.0)
        assert net.heat_consumer.loc[idx, "deltat_k"] == pytest.approx(consumer.design_delta_t_k)


def test_builder_circulation_pump_converted_to_gauge_correctly():
    bp = _default_blueprint()
    net = build_pandapipes_net(bp)
    p_flow_bar_gauge = net.circ_pump_pressure.loc[0, "p_flow_bar"]
    assert to_absolute_bar(p_flow_bar_gauge) == pytest.approx(bp.circulation_pump.p_flow_bar_abs)
    assert net.circ_pump_pressure.loc[0, "plift_bar"] == pytest.approx(bp.circulation_pump.pressure_lift_bar)


def test_builder_never_mutates_the_blueprint():
    bp = _default_blueprint()
    snapshot = bp.model_dump_json()
    build_pandapipes_net(bp)
    assert bp.model_dump_json() == snapshot


# ── Real convergence smoke test (T2.2A) ─────────────────────────────────────
def test_default_blueprint_converges_under_sequential_pipeflow():
    """Full end-to-end proof the builder produces a physically valid,
    solvable network at the empirically-determined plift_bar=3.0 bar."""
    bp = _default_blueprint()
    net = build_pandapipes_net(bp)
    pandapipes.pipeflow(net, mode="sequential")

    assert bool(net.converged) is True

    for idx, name in enumerate(net.pipe["name"]):
        assert abs(net.res_pipe.loc[idx, "v_mean_m_per_s"]) <= 1.5

    max_v = net.res_pipe["v_mean_m_per_s"].abs().max()
    # DN150 originally gave max_v=1.475 (98% of the 1.5 m/s gate) -- not a
    # comfortable baseline margin. Upsized to DN200 (config
    # network.pipe_sizing.trunk_pipe_dn_mm); pin at least 10% headroom
    # (<=1.35 m/s) as a durable regression check, not just "under the gate".
    assert max_v <= 1.35, f"baseline velocity margin regressed: {max_v} m/s (gate 1.5 m/s)"

    min_p_abs = min(to_absolute_bar(p) for p in net.res_junction["p_bar"])
    assert min_p_abs >= 1.5

    hc_by_name = {name: idx for idx, name in enumerate(net.heat_consumer["name"])}
    for consumer_id, consumer in bp.consumers.items():
        idx = hc_by_name[consumer_id]
        assert net.res_heat_consumer.loc[idx, "qext_w"] == pytest.approx(consumer.demand_kw * 1000.0)
        assert net.res_heat_consumer.loc[idx, "deltat_k"] == pytest.approx(consumer.design_delta_t_k)
