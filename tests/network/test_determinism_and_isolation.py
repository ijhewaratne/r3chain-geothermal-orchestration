"""Determinism and isolation tests for network/builder.py (T2.2A).

- Determinism must be independent of NetworkBlueprint's dict key order --
  JSON object order carries no semantic meaning, so two blueprints holding
  the same entries in a different key order must build structurally
  identical pandapipesNet objects.
- The template/baseline net must be safely deep-copyable and isolated from
  mutation of the copy (plan §10.4's candidate-mutation rule).
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

pandapipes = pytest.importorskip("pandapipes")

from r3chain_geothermal.network.blueprint import NetworkBlueprint, build_default_blueprint
from r3chain_geothermal.network.builder import build_pandapipes_net

_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}
_FIXED_CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _default_blueprint(created_at=None) -> NetworkBlueprint:
    return build_default_blueprint(
        consumer_demands_kw=_DEMANDS,
        trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
        created_at=created_at or _FIXED_CREATED_AT,
    )


def _reordered_copy(bp: NetworkBlueprint) -> NetworkBlueprint:
    """Same content as `bp`, but every dict field rebuilt with REVERSED key
    insertion order -- proves the builder doesn't depend on dict order."""
    return NetworkBlueprint(
        blueprint_schema_version=bp.blueprint_schema_version,
        junctions=dict(reversed(list(bp.junctions.items()))),
        pipes=dict(reversed(list(bp.pipes.items()))),
        consumers=dict(reversed(list(bp.consumers.items()))),
        candidates=dict(reversed(list(bp.candidates.items()))),
        circulation_pump=bp.circulation_pump,
        build_parameters=bp.build_parameters,
        created_at=bp.created_at,
    )


def test_reordered_blueprint_is_equal_as_a_model():
    """Pydantic model equality does not depend on dict key order either --
    a sanity check before testing the builder's own order-independence."""
    bp = _default_blueprint()
    reordered = _reordered_copy(bp)
    assert reordered == bp
    assert list(reordered.junctions.keys()) != list(bp.junctions.keys())  # genuinely reordered


def test_builder_produces_identical_net_regardless_of_blueprint_dict_order():
    bp = _default_blueprint()
    reordered = _reordered_copy(bp)

    net_a = build_pandapipes_net(bp)
    net_b = build_pandapipes_net(reordered)

    assert list(net_a.junction["name"]) == list(net_b.junction["name"])
    assert list(net_a.pipe["name"]) == list(net_b.pipe["name"])
    assert list(net_a.heat_consumer["name"]) == list(net_b.heat_consumer["name"])
    assert net_a.junction["name"].tolist() == sorted(net_a.junction["name"].tolist())
    assert net_a.pipe.equals(net_b.pipe)
    assert net_a.heat_consumer.equals(net_b.heat_consumer)


def test_builder_junction_indices_are_stable_across_reordered_blueprints():
    """Not just the same NAMES in the same order -- the same pandapipes
    integer index must be assigned to the same named junction."""
    bp = _default_blueprint()
    reordered = _reordered_copy(bp)

    net_a = build_pandapipes_net(bp)
    net_b = build_pandapipes_net(reordered)

    index_a = {name: idx for idx, name in enumerate(net_a.junction["name"])}
    index_b = {name: idx for idx, name in enumerate(net_b.junction["name"])}
    assert index_a == index_b


def test_same_blueprint_built_twice_produces_structurally_identical_nets():
    bp = _default_blueprint()
    net_1 = build_pandapipes_net(bp)
    net_2 = build_pandapipes_net(bp)
    assert net_1.junction.equals(net_2.junction)
    assert net_1.pipe.equals(net_2.pipe)
    assert net_1.heat_consumer.equals(net_2.heat_consumer)
    assert net_1.circ_pump_pressure.equals(net_2.circ_pump_pressure)


def test_reordered_and_solved_networks_converge_to_the_same_result():
    bp = _default_blueprint()
    reordered = _reordered_copy(bp)

    net_a = build_pandapipes_net(bp)
    net_b = build_pandapipes_net(reordered)
    pandapipes.pipeflow(net_a, mode="sequential")
    pandapipes.pipeflow(net_b, mode="sequential")

    assert bool(net_a.converged) and bool(net_b.converged)
    assert net_a.res_junction["p_bar"].tolist() == pytest.approx(net_b.res_junction["p_bar"].tolist())
    assert net_a.res_heat_consumer["qext_w"].tolist() == pytest.approx(net_b.res_heat_consumer["qext_w"].tolist())


# ── Deep-copy / network isolation (plan §10.4's candidate-mutation rule) ───
def test_pandapipes_net_deep_copy_is_a_distinct_object():
    bp = _default_blueprint()
    net = build_pandapipes_net(bp)
    net_copy = copy.deepcopy(net)
    assert net_copy is not net
    assert type(net_copy) is type(net)


def test_mutating_deep_copy_does_not_affect_the_original_template_net():
    bp = _default_blueprint()
    template_net = build_pandapipes_net(bp)
    original_junction_count = len(template_net.junction)
    original_pipe_count = len(template_net.pipe)

    candidate_net = copy.deepcopy(template_net)
    # Mutate the copy the way a later candidate-evaluation task would:
    # add a new junction and pipe representing a surface connection.
    new_j = pandapipes.create_junction(candidate_net, pn_bar=1.0, tfluid_k=343.15, name="mutation_probe")
    pandapipes.create_pipe_from_parameters(
        candidate_net, from_junction=new_j, to_junction=new_j - 1 if new_j > 0 else new_j,
        length_km=0.01, inner_diameter_mm=50.0, name="mutation_probe_pipe",
    )

    assert len(candidate_net.junction) == original_junction_count + 1
    assert len(candidate_net.pipe) == original_pipe_count + 1
    # The ORIGINAL template must be completely untouched.
    assert len(template_net.junction) == original_junction_count
    assert len(template_net.pipe) == original_pipe_count
    assert "mutation_probe" not in set(template_net.junction["name"])
