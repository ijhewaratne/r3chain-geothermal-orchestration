"""Builds a real pandapipes `pandapipesNet` from a `NetworkBlueprint`
(T2.2). Pure translation: every pandapipes object created here corresponds
directly to a blueprint entry -- no topology decisions are made here, only
in `blueprint.build_default_blueprint()` / `network/geometry.py`.

Deterministic: the same blueprint always produces a structurally identical
net (same junction/pipe/component order, same parameter values) --
independent of the blueprint's dict insertion order, since JSON object
order is not semantically meaningful and two blueprints holding identical
entries in a different key order must still produce identical pandapipes
indices/tables. Every dict is therefore iterated in sorted-key order here,
never in raw dict insertion order.
"""
from __future__ import annotations

import pandapipes

from .blueprint import NetworkBlueprint
from .pressure import to_gauge_bar


def build_pandapipes_net(blueprint: NetworkBlueprint) -> "pandapipes.pandapipesNet":
    """Construct a pandapipesNet from `blueprint`. Never mutates `blueprint`
    (a frozen pydantic model, so mutation would raise regardless)."""
    net = pandapipes.create_empty_network(fluid=blueprint.build_parameters.fluid)

    bp = blueprint.build_parameters
    supply_t_k = bp.supply_temperature_c + 273.15
    return_t_k = bp.return_temperature_c + 273.15
    ground_t_k = bp.ground_temperature_c + 273.15
    initial_pn_bar_gauge = to_gauge_bar(blueprint.circulation_pump.p_flow_bar_abs)

    junction_index: dict[str, int] = {}
    # Sorted-key order: dict insertion order is NOT semantically meaningful
    # in a JSON-native blueprint -- two blueprints with identical entries in
    # a different key order must produce identical pandapipes indices.
    for junction_id in sorted(blueprint.junctions):
        junction = blueprint.junctions[junction_id]
        tfluid_k = supply_t_k if junction.side == "supply" else return_t_k
        junction_index[junction_id] = pandapipes.create_junction(
            net, pn_bar=initial_pn_bar_gauge, tfluid_k=tfluid_k,
            height_m=junction.height_m, name=junction_id,
            geodata=(junction.x_m, junction.y_m),
        )

    for pipe_id in sorted(blueprint.pipes):
        pipe = blueprint.pipes[pipe_id]
        pandapipes.create_pipe_from_parameters(
            net,
            from_junction=junction_index[pipe.from_junction],
            to_junction=junction_index[pipe.to_junction],
            length_km=pipe.length_m / 1000.0,
            inner_diameter_mm=pipe.inner_diameter_mm,
            k_mm=bp.pipe_roughness_mm,
            u_w_per_m2k=bp.pipe_heat_transfer_coefficient_w_per_m2k,
            text_k=ground_t_k,
            name=pipe_id,
        )

    for consumer_id in sorted(blueprint.consumers):
        consumer = blueprint.consumers[consumer_id]
        pandapipes.create_heat_consumer(
            net,
            from_junction=junction_index[consumer.supply_junction],
            to_junction=junction_index[consumer.return_junction],
            qext_w=consumer.demand_kw * 1000.0,
            deltat_k=consumer.design_delta_t_k,
            name=consumer_id,
        )

    pump = blueprint.circulation_pump
    pandapipes.create_circ_pump_const_pressure(
        net,
        return_junction=junction_index[pump.return_junction],
        flow_junction=junction_index[pump.flow_junction],
        p_flow_bar=to_gauge_bar(pump.p_flow_bar_abs),
        plift_bar=pump.pressure_lift_bar,
        t_flow_k=pump.flow_temperature_c + 273.15,
        name="baseline_circulation_pump",
    )

    return net
