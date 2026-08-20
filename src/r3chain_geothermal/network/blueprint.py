"""NetworkBlueprint -- the JSON-native, versioned description of the T2.2
synthetic four-consumer district-heating network, kept deliberately
separate from the runtime `pandapipesNet` object (builder.py constructs the
latter FROM a blueprint; the blueprint itself contains no pandapipes
objects and round-trips through plain model_dump_json()/model_validate_json()
like every other contract in this project).

Model-level invariants (mirroring T1.5B/T2.1's rigor) enforce: no NaN/
Infinity anywhere (`allow_inf_nan=False` on every model with float fields --
this contract is claimed JSON-native, so non-finite floats can never be
accepted); every dict key equals its own entry's `id` (junctions, pipes,
consumers, candidates alike); every pipe/consumer/candidate/pump junction
reference resolves to a real `junctions` entry AND has the physically
correct `side` (a consumer/candidate's `supply_junction` must be
`side="supply"`, its `return_junction` must be `side="return"`; the pump's
`flow_junction` must be `side="supply"`, its `return_junction` must be
`side="return"`); every pipe's `role` agrees with its endpoints' sides
(`supply_*` roles connect two `side="supply"` junctions, `return_*` roles
connect two `side="return"` junctions); no self-loop pipes and no
consumer/candidate/pump with identical supply and return junctions; all
lengths/diameters/demands are positive.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from . import geometry

BLUEPRINT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""Versioned independently of T1.5B's/T2.1's own contract schema versions --
each layer versions on its own timeline."""


class BlueprintJunction(BaseModel):
    """One pandapipes junction's static, build-time description."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    id: str
    x_m: float
    y_m: float
    side: Literal["supply", "return"]
    kind: Literal["plant", "trunk", "consumer"]
    height_m: float = 0.0


class BlueprintPipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    id: str
    from_junction: str
    to_junction: str
    length_m: float
    inner_diameter_mm: float
    role: Literal["supply_trunk", "supply_branch", "return_trunk", "return_branch"]


class BlueprintConsumer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    id: str
    supply_junction: str
    return_junction: str
    demand_kw: float
    design_delta_t_k: float


class BlueprintCandidate(BaseModel):
    """A candidate connection point -- topology only. No geothermal source
    is attached and no evaluation happens at this layer (T2.2 scope
    boundary): 'create valid candidate supply/return junction pairs,
    without evaluating geothermal connections yet'."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    id: str
    label: str
    supply_junction: str
    return_junction: str
    surface_connection_length_m: float


class CirculationPumpSpec(BaseModel):
    """The baseline surface-plant boundary: one pressure-controlled
    circulation pump (plan §10.1's 'One pressure-controlled DH circulation
    pump representing the surface plant boundary')."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    return_junction: str
    flow_junction: str
    p_flow_bar_abs: float
    """ABSOLUTE pressure (see network/pressure.py) -- converted to gauge by
    the builder immediately before the pandapipes create_* call."""
    pressure_lift_bar: float
    flow_temperature_c: float


class NetworkBuildParameters(BaseModel):
    """Physical build-time parameters, kept separate from pure topology
    (BlueprintJunction/Pipe/Consumer/Candidate above) so the blueprint
    stays a self-contained, fully-reproducible snapshot -- no build-time
    parameter is supplied out-of-band to the builder."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    supply_temperature_c: float
    return_temperature_c: float
    ground_temperature_c: float
    pipe_heat_transfer_coefficient_w_per_m2k: float
    pipe_roughness_mm: float
    fluid: Literal["water"] = "water"


class NetworkBlueprint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    blueprint_schema_version: Literal["1.0.0"] = BLUEPRINT_SCHEMA_VERSION
    junctions: dict[str, BlueprintJunction]
    pipes: dict[str, BlueprintPipe]
    consumers: dict[str, BlueprintConsumer]
    candidates: dict[str, BlueprintCandidate]
    circulation_pump: CirculationPumpSpec
    build_parameters: NetworkBuildParameters
    created_at: datetime

    @model_validator(mode="after")
    def _validate_referential_integrity_and_positivity(self) -> "NetworkBlueprint":
        errors: list[str] = []
        junction_ids = set(self.junctions.keys())

        def _side_of(junction_id: str) -> str | None:
            junction = self.junctions.get(junction_id)
            return junction.side if junction is not None else None

        for key, junction in self.junctions.items():
            if key != junction.id:
                errors.append(f"junctions[{key!r}].id must equal its own dict key, got {junction.id!r}")

        for key, pipe in self.pipes.items():
            if key != pipe.id:
                errors.append(f"pipes[{key!r}].id must equal its own dict key, got {pipe.id!r}")

            from_ok = pipe.from_junction in junction_ids
            to_ok = pipe.to_junction in junction_ids
            if not from_ok:
                errors.append(f"pipes[{pipe.id!r}].from_junction {pipe.from_junction!r} does not exist")
            if not to_ok:
                errors.append(f"pipes[{pipe.id!r}].to_junction {pipe.to_junction!r} does not exist")
            if from_ok and to_ok and pipe.from_junction == pipe.to_junction:
                errors.append(f"pipes[{pipe.id!r}] is a self-loop: from_junction == to_junction == {pipe.from_junction!r}")

            if from_ok and to_ok:
                expected_side = "supply" if pipe.role in ("supply_trunk", "supply_branch") else "return"
                from_side, to_side = _side_of(pipe.from_junction), _side_of(pipe.to_junction)
                if from_side != expected_side or to_side != expected_side:
                    errors.append(
                        f"pipes[{pipe.id!r}] role={pipe.role!r} requires both endpoints "
                        f"side={expected_side!r}, got from_junction side={from_side!r}, "
                        f"to_junction side={to_side!r}"
                    )

            if pipe.length_m <= 0:
                errors.append(f"pipes[{pipe.id!r}].length_m must be > 0, got {pipe.length_m!r}")
            if pipe.inner_diameter_mm <= 0:
                errors.append(f"pipes[{pipe.id!r}].inner_diameter_mm must be > 0, got {pipe.inner_diameter_mm!r}")

        for key, consumer in self.consumers.items():
            if key != consumer.id:
                errors.append(f"consumers[{key!r}].id must equal its own dict key, got {consumer.id!r}")

            supply_ok = consumer.supply_junction in junction_ids
            return_ok = consumer.return_junction in junction_ids
            if not supply_ok:
                errors.append(f"consumers[{consumer.id!r}].supply_junction does not exist")
            if not return_ok:
                errors.append(f"consumers[{consumer.id!r}].return_junction does not exist")
            if supply_ok and _side_of(consumer.supply_junction) != "supply":
                errors.append(
                    f"consumers[{consumer.id!r}].supply_junction {consumer.supply_junction!r} "
                    f"must have side='supply', got {_side_of(consumer.supply_junction)!r}"
                )
            if return_ok and _side_of(consumer.return_junction) != "return":
                errors.append(
                    f"consumers[{consumer.id!r}].return_junction {consumer.return_junction!r} "
                    f"must have side='return', got {_side_of(consumer.return_junction)!r}"
                )
            if supply_ok and return_ok and consumer.supply_junction == consumer.return_junction:
                errors.append(f"consumers[{consumer.id!r}].supply_junction and return_junction must differ")

            if consumer.demand_kw <= 0:
                errors.append(f"consumers[{consumer.id!r}].demand_kw must be > 0, got {consumer.demand_kw!r}")
            if consumer.design_delta_t_k <= 0:
                errors.append(f"consumers[{consumer.id!r}].design_delta_t_k must be > 0")

        for key, candidate in self.candidates.items():
            if key != candidate.id:
                errors.append(f"candidates[{key!r}].id must equal its own dict key, got {candidate.id!r}")

            supply_ok = candidate.supply_junction in junction_ids
            return_ok = candidate.return_junction in junction_ids
            if not supply_ok:
                errors.append(f"candidates[{candidate.id!r}].supply_junction does not exist")
            if not return_ok:
                errors.append(f"candidates[{candidate.id!r}].return_junction does not exist")
            if supply_ok and _side_of(candidate.supply_junction) != "supply":
                errors.append(
                    f"candidates[{candidate.id!r}].supply_junction {candidate.supply_junction!r} "
                    f"must have side='supply', got {_side_of(candidate.supply_junction)!r}"
                )
            if return_ok and _side_of(candidate.return_junction) != "return":
                errors.append(
                    f"candidates[{candidate.id!r}].return_junction {candidate.return_junction!r} "
                    f"must have side='return', got {_side_of(candidate.return_junction)!r}"
                )
            if supply_ok and return_ok and candidate.supply_junction == candidate.return_junction:
                errors.append(f"candidates[{candidate.id!r}].supply_junction and return_junction must differ")

            if candidate.surface_connection_length_m <= 0:
                errors.append(f"candidates[{candidate.id!r}].surface_connection_length_m must be > 0")

        pump = self.circulation_pump
        flow_ok = pump.flow_junction in junction_ids
        return_ok = pump.return_junction in junction_ids
        if not flow_ok:
            errors.append(f"circulation_pump.flow_junction {pump.flow_junction!r} does not exist")
        if not return_ok:
            errors.append(f"circulation_pump.return_junction {pump.return_junction!r} does not exist")
        if flow_ok and _side_of(pump.flow_junction) != "supply":
            errors.append(
                f"circulation_pump.flow_junction {pump.flow_junction!r} must have side='supply', "
                f"got {_side_of(pump.flow_junction)!r}"
            )
        if return_ok and _side_of(pump.return_junction) != "return":
            errors.append(
                f"circulation_pump.return_junction {pump.return_junction!r} must have side='return', "
                f"got {_side_of(pump.return_junction)!r}"
            )
        if flow_ok and return_ok and pump.flow_junction == pump.return_junction:
            errors.append("circulation_pump.flow_junction and return_junction must differ")
        if pump.pressure_lift_bar <= 0:
            errors.append("circulation_pump.pressure_lift_bar must be > 0")

        bp = self.build_parameters
        if bp.supply_temperature_c <= bp.return_temperature_c:
            errors.append("build_parameters.supply_temperature_c must be > return_temperature_c")
        if bp.pipe_heat_transfer_coefficient_w_per_m2k < 0:
            errors.append("build_parameters.pipe_heat_transfer_coefficient_w_per_m2k must be >= 0")

        if errors:
            raise ValueError("; ".join(errors))
        return self


def build_default_blueprint(
    *,
    consumer_demands_kw: dict[str, float],
    trunk_pipe_dn_mm: float,
    branch_pipe_dn_mm: float,
    design_delta_t_k: float,
    supply_temperature_c: float,
    return_temperature_c: float,
    ground_temperature_c: float,
    pipe_heat_transfer_coefficient_w_per_m2k: float,
    pipe_roughness_mm: float,
    p_supply_bar_abs: float,
    pump_pressure_lift_bar: float,
    created_at: datetime,
) -> NetworkBlueprint:
    """Construct the T2.2 synthetic network's NetworkBlueprint from
    network/geometry.py's single coordinate source plus the given build
    parameters. Deterministic: identical arguments always produce a
    structurally identical blueprint (no randomness, no wall-clock
    dependence except the explicitly-passed `created_at`).

    Args:
        consumer_demands_kw: {"consumer_1": 650.0, ...} -- keys must be
            EXACTLY geometry.CONSUMER_TRUNK_ATTACHMENT's keys, no more, no
            fewer (raises ValueError otherwise -- see below).
        pipe_roughness_mm: currently recorded in build_parameters for
            completeness/future use; the builder passes it to every
            create_pipe_from_parameters call as `k_mm`.

    Raises:
        ValueError: consumer_demands_kw is missing an expected consumer id
            or contains an unexpected one -- deliberate, not an incidental
            KeyError from a later dict lookup or a silently-ignored extra key.
    """
    expected_consumer_ids = set(geometry.CONSUMER_TRUNK_ATTACHMENT.keys())
    given_consumer_ids = set(consumer_demands_kw.keys())
    if given_consumer_ids != expected_consumer_ids:
        missing = sorted(expected_consumer_ids - given_consumer_ids)
        extra = sorted(given_consumer_ids - expected_consumer_ids)
        raise ValueError(
            "consumer_demands_kw must contain exactly the expected consumer ids "
            f"{sorted(expected_consumer_ids)}; missing={missing}, extra={extra}"
        )

    junctions: dict[str, BlueprintJunction] = {}
    pipes: dict[str, BlueprintPipe] = {}
    consumers: dict[str, BlueprintConsumer] = {}
    candidates: dict[str, BlueprintCandidate] = {}

    # ── Supply-side trunk junctions ──
    for trunk_id, coord in geometry.TRUNK_JUNCTION_COORDINATES.items():
        junctions[trunk_id] = BlueprintJunction(
            id=trunk_id, x_m=coord.x_m, y_m=coord.y_m, side="supply",
            kind="plant" if trunk_id == "trunk_0" else "trunk",
        )

    # ── Return-side trunk junctions (mirrored, map-legibility coordinates only) ──
    for trunk_id, coord in geometry.TRUNK_JUNCTION_COORDINATES.items():
        ret_id = geometry.ret_junction_id(trunk_id)
        ret_coord = geometry.ret_coordinate(coord)
        junctions[ret_id] = BlueprintJunction(
            id=ret_id, x_m=ret_coord.x_m, y_m=ret_coord.y_m, side="return",
            kind="plant" if trunk_id == "trunk_0" else "trunk",
        )

    # ── Supply trunk pipes (mirrored return trunk pipes too) ──
    for from_id, to_id in geometry.trunk_pipe_pairs():
        length_m = geometry.trunk_pipe_length_m(from_id, to_id)
        pipes[f"pipe_{from_id}_{to_id}"] = BlueprintPipe(
            id=f"pipe_{from_id}_{to_id}", from_junction=from_id, to_junction=to_id,
            length_m=length_m, inner_diameter_mm=trunk_pipe_dn_mm, role="supply_trunk",
        )
        ret_from, ret_to = geometry.ret_junction_id(from_id), geometry.ret_junction_id(to_id)
        # Return flow direction is reversed relative to supply (mirrors physical flow).
        pipes[f"pipe_{ret_to}_{ret_from}"] = BlueprintPipe(
            id=f"pipe_{ret_to}_{ret_from}", from_junction=ret_to, to_junction=ret_from,
            length_m=length_m, inner_diameter_mm=trunk_pipe_dn_mm, role="return_trunk",
        )

    # ── Consumers: supply/return junctions, branch pipes, heat-consumer spec ──
    for consumer_id, trunk_id in geometry.CONSUMER_TRUNK_ATTACHMENT.items():
        coord = geometry.CONSUMER_JUNCTION_COORDINATES[consumer_id]
        ret_consumer_id = geometry.ret_junction_id(consumer_id)
        ret_coord = geometry.ret_coordinate(coord)

        junctions[consumer_id] = BlueprintJunction(
            id=consumer_id, x_m=coord.x_m, y_m=coord.y_m, side="supply", kind="consumer",
        )
        junctions[ret_consumer_id] = BlueprintJunction(
            id=ret_consumer_id, x_m=ret_coord.x_m, y_m=ret_coord.y_m, side="return", kind="consumer",
        )

        branch_length_m = geometry.consumer_branch_length_m(consumer_id)
        ret_trunk_id = geometry.ret_junction_id(trunk_id)
        pipes[f"pipe_{trunk_id}_{consumer_id}"] = BlueprintPipe(
            id=f"pipe_{trunk_id}_{consumer_id}", from_junction=trunk_id, to_junction=consumer_id,
            length_m=branch_length_m, inner_diameter_mm=branch_pipe_dn_mm, role="supply_branch",
        )
        pipes[f"pipe_{ret_consumer_id}_{ret_trunk_id}"] = BlueprintPipe(
            id=f"pipe_{ret_consumer_id}_{ret_trunk_id}", from_junction=ret_consumer_id, to_junction=ret_trunk_id,
            length_m=branch_length_m, inner_diameter_mm=branch_pipe_dn_mm, role="return_branch",
        )

        consumers[consumer_id] = BlueprintConsumer(
            id=consumer_id, supply_junction=consumer_id, return_junction=ret_consumer_id,
            demand_kw=consumer_demands_kw[consumer_id], design_delta_t_k=design_delta_t_k,
        )

    # ── Candidates: topology only, no geothermal source attached (T2.2 scope) ──
    for candidate_id, trunk_id in geometry.CANDIDATE_TRUNK_ATTACHMENT.items():
        candidates[candidate_id] = BlueprintCandidate(
            id=candidate_id, label=geometry.CANDIDATE_LABELS[candidate_id],
            supply_junction=trunk_id, return_junction=geometry.ret_junction_id(trunk_id),
            surface_connection_length_m=geometry.candidate_surface_connection_length_m(candidate_id),
        )

    circulation_pump = CirculationPumpSpec(
        return_junction=geometry.ret_junction_id("trunk_0"), flow_junction="trunk_0",
        p_flow_bar_abs=p_supply_bar_abs, pressure_lift_bar=pump_pressure_lift_bar,
        flow_temperature_c=supply_temperature_c,
    )

    build_parameters = NetworkBuildParameters(
        supply_temperature_c=supply_temperature_c, return_temperature_c=return_temperature_c,
        ground_temperature_c=ground_temperature_c,
        pipe_heat_transfer_coefficient_w_per_m2k=pipe_heat_transfer_coefficient_w_per_m2k,
        pipe_roughness_mm=pipe_roughness_mm,
    )

    return NetworkBlueprint(
        junctions=junctions, pipes=pipes, consumers=consumers, candidates=candidates,
        circulation_pump=circulation_pump, build_parameters=build_parameters, created_at=created_at,
    )
