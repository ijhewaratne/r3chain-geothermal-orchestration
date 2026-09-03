"""Reusable geothermal-doublet-connection composite (DLT-001..007,
R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Workstream G).

## Design decision (12.1)

This is a project COMPOSITE builder/result-extractor in THIS orchestration
repository -- it does not modify pandapipes internals and does not touch
the reference-only `repos/pandapipesAI` checkout. A native upstream
pandapipes component may be considered later through a separate ADR and
upstream review (DLT-007); nothing here claims to be one.

## Relationship to network/candidate.py -- parity by construction, not by
## re-derivation

`network/candidate.py::evaluate_candidate()` already builds and solves
this exact topology (its own module docstring, "Selected topology") and
already implements the self-consistent flow root solve (DSP-005). Rather
than re-deriving that physics a second time -- which would risk exactly
the kind of silent divergence DLT-006 (parity) exists to catch -- this
module WRAPS the same private, already-independently-tested functions
(`_add_geothermal_injection_branch`, `_solve_self_consistent_injection`,
`_compute_injected_mass_flow_kg_s`) behind the typed contract DLT-001
asks for. Given identical inputs, this module and
`network/candidate.py::evaluate_candidate()` call the IDENTICAL
underlying code paths, so their results are not merely "within
tolerance" -- they are bit-identical by construction. See
`tests/network/test_doublet_component.py`'s own parity tests for the
executable proof (AC-07).

**Phase-4 exit-gate note**: the exit gate reads "component parity and
isolation pass; legacy duplicate construction logic is removed only
after parity is proven." Parity is proven here (this module and
`evaluate_candidate()` share the same underlying calls, so there is in
fact no *duplicate* physics to remove -- `evaluate_candidate()` itself
is NOT refactored to call this module in this phase, a deliberately
conservative choice given how heavily validated that function already
is; retargeting it is left as a separate, later, independently-reviewable
step. This module is additive: available for future orchestration
re-use and as the documented reference contract, without touching the
canonical evaluation pathway's own code at all.

## Topology (DLT-003)

Exactly `network/candidate.py`'s own selected topology -- reproduced here
because DLT-003 names it directly, not because it is redefined:

```
return attachment (candidate's return_junction)
  --return connection pipe--> geo_return
  --circulation pump (flat lift curve)--> geo_mid
  --controlled heat injection (heat_consumer, qext_w<0)--> geo_supply
  --supply connection pipe--> supply attachment (candidate's supply_junction)
```

This module never models the underground brine loop inside the
district-heating water network -- brine-side results (spec below) enter
only through the already-computed heat-exchanger coupling boundary
(`boundary` below), exactly as CLAUDE.md requires (raw PyDoublet power is
not automatically DH-deliverable power; brine and DH-water flow are never
conflated).

## Scope boundary

This component's own failure surface is limited to what is intrinsic to
ONE geothermal connection's own construction and flow-sizing: pandapipes
non-convergence, its own hydraulic conflict, and (under
DoubletOperatingPolicy.injection_sizing_policy=="self_consistent")
non-convergence of the self-consistent flow solve. Network-wide gates
that depend on the WHOLE network, not just this branch -- consumer
temperature, absolute pressure, pipe velocity, mass balance, physical
energy balance -- remain `network/candidate.py::evaluate_candidate()`'s
own responsibility, applied AFTER this component's own construction
succeeds, exactly as CFG-004's gate order already specifies. Likewise,
auxiliary/unmet heat (a network-wide demand-accounting concept requiring
total consumer demand, which this component never sees) is not computed
here -- `curtailed_heat_kw` below is the single difference between
available and accepted geothermal heat; cause-attribution (true supply
surplus vs. the numerical-stabilization margin) remains the caller's
policy decision, unchanged from `network/candidate.py`'s own documented
"Curtailment" section.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

import pandapipes
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..contracts import CouplingWarning
from .blueprint import BlueprintCandidate, NetworkBlueprint
from .builder import build_pandapipes_net
from .candidate import (
    SELF_CONSISTENT_FLOW_MASS_FLOW_RESIDUAL_TOLERANCE_FRACTION,
    SELF_CONSISTENT_FLOW_MAX_ITERATIONS,
    SELF_CONSISTENT_FLOW_OUTLET_TEMPERATURE_TOLERANCE_K,
    CandidateFailureCode,
    SelfConsistentFlowDiagnostics,
    _add_geothermal_injection_branch,
    _compute_injected_mass_flow_kg_s,
    _SelfConsistentFlowNotConverged,
    _solve_self_consistent_injection,
)
from .pressure import to_absolute_bar

DOUBLET_COMPONENT_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""Versioned independently of every other layer's own contract schema."""


# ── DLT-001: the six named typed contracts ──────────────────────────────────

class GeothermalDoubletSpec(BaseModel):
    """Brine-side quantities from an already-validated, already-converged
    PyDoublet coupling result (T1.5B) -- this component never re-derives
    or re-validates any of these; it receives them as trusted input from
    the upstream layer that IS authoritative for them (CLAUDE.md: PyDoublet
    remains authoritative for the doublet/subsurface result)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    producer_wellhead_temperature_c: float
    brine_mass_flow_kg_s: float
    brine_specific_heat_capacity_j_kg_k: float
    raw_geothermal_thermal_power_kw: float
    minimum_reinjection_temperature_c: float
    doublet_pump_electric_power_kw: float
    """PyDoublet's own reported ELECTRICAL power (via its own internal
    efficiency) -- preserved unchanged, never recomputed, never combined
    with any DH-side pumping figure (same rule as
    CandidateEvaluationResult.doublet_pump_electric_power_kw)."""

    @model_validator(mode="after")
    def _validate_positive(self) -> "GeothermalDoubletSpec":
        if self.brine_mass_flow_kg_s <= 0:
            raise ValueError("brine_mass_flow_kg_s must be > 0")
        if self.brine_specific_heat_capacity_j_kg_k <= 0:
            raise ValueError("brine_specific_heat_capacity_j_kg_k must be > 0")
        if self.doublet_pump_electric_power_kw < 0:
            raise ValueError("doublet_pump_electric_power_kw must be >= 0")
        return self


class HeatExchangerBoundary(BaseModel):
    """The already-computed T2.1 heat-exchanger coupling boundary (T2.1's
    `HeatExchangerCouplingResult`) -- CLAUDE.md: the adapter remains
    authoritative for the surface heat-exchanger boundary; this component
    never recomputes deliverable_geothermal_heat_kw or the HX
    hot/cold-end feasibility checks, only consumes their already-decided
    result."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    minimum_hx_approach_k: float
    hx_heat_delivery_factor: float
    deliverable_geothermal_heat_kw: float
    """T2.1's already-curtailment-independent deliverable heat -- the
    ceiling this component's accepted_heat_kw (DoubletOperatingPolicy)
    must never exceed."""

    @model_validator(mode="after")
    def _validate_positive(self) -> "HeatExchangerBoundary":
        if self.minimum_hx_approach_k < 0:
            raise ValueError("minimum_hx_approach_k must be >= 0")
        if not (0.0 < self.hx_heat_delivery_factor <= 1.0):
            raise ValueError("hx_heat_delivery_factor must be in (0, 1]")
        if self.deliverable_geothermal_heat_kw <= 0:
            raise ValueError("deliverable_geothermal_heat_kw must be > 0")
        return self


class DistrictHeatingConnectionSpec(BaseModel):
    """Topology/geometry inputs: the candidate connection point (junction
    pair + surface connection length -- reuses BlueprintCandidate directly
    rather than duplicating its fields) plus the DH-side design
    temperatures and water property this component sizes flow against.
    Connection-pipe DN/roughness and the circulation-pump's own lift curve
    are read from the supplied NetworkBlueprint at build time (the SAME
    fixed, shared values every candidate already uses -- plan §10.1's
    "fixed pipe diameters across candidate evaluations"), not duplicated
    here."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    candidate: BlueprintCandidate
    dh_supply_temperature_c: float
    dh_return_temperature_c: float
    dh_water_specific_heat_capacity_j_kg_k: float

    @model_validator(mode="after")
    def _validate_positive(self) -> "DistrictHeatingConnectionSpec":
        if self.dh_water_specific_heat_capacity_j_kg_k <= 0:
            raise ValueError("dh_water_specific_heat_capacity_j_kg_k must be > 0")
        if self.dh_supply_temperature_c <= self.dh_return_temperature_c:
            raise ValueError("dh_supply_temperature_c must be > dh_return_temperature_c")
        return self


class DoubletOperatingPolicy(BaseModel):
    """The accepted-heat decision (DLT-002: "accepted-heat/shortfall
    policy") plus the flow-solver tolerances (DLT-002: "flow-solver
    tolerances") this component consumes. `accepted_heat_kw` is a DECIDED
    input, not computed here -- the curtailment/shortfall DECISION
    (surplus vs. resource-limited vs. numerical-stabilization-margin,
    network/candidate.py's own `_compute_injected_heat_kw`) is network-wide
    policy that stays with the caller, one layer above this component
    (CLAUDE.md: deterministic code is authoritative for feasibility;
    the separation of concerns this component exists to preserve)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    accepted_heat_kw: float
    injection_sizing_policy: Literal["fixed_design_temperature", "self_consistent"] = "fixed_design_temperature"
    outlet_temperature_tolerance_k: float = SELF_CONSISTENT_FLOW_OUTLET_TEMPERATURE_TOLERANCE_K
    mass_flow_residual_tolerance_fraction: float = SELF_CONSISTENT_FLOW_MASS_FLOW_RESIDUAL_TOLERANCE_FRACTION
    max_iterations: int = SELF_CONSISTENT_FLOW_MAX_ITERATIONS
    """Defaults reuse network/candidate.py's own named constants exactly --
    this component does not (yet) support overriding the solver's
    tolerances independently of network/candidate.py's own values; the
    fields exist per DLT-002's explicit requirement and to make the
    values that WERE used self-documenting on every result, not to offer
    a currently-exercised extension point. Overriding them would call
    _solve_self_consistent_injection() with different module-level
    constants than the ones actually used -- not supported by this
    version; validated below."""

    @model_validator(mode="after")
    def _validate(self) -> "DoubletOperatingPolicy":
        if self.accepted_heat_kw <= 0:
            raise ValueError("accepted_heat_kw must be > 0")
        if self.outlet_temperature_tolerance_k != SELF_CONSISTENT_FLOW_OUTLET_TEMPERATURE_TOLERANCE_K:
            raise ValueError(
                "outlet_temperature_tolerance_k must equal "
                "network.candidate.SELF_CONSISTENT_FLOW_OUTLET_TEMPERATURE_TOLERANCE_K in this version"
            )
        if self.mass_flow_residual_tolerance_fraction != SELF_CONSISTENT_FLOW_MASS_FLOW_RESIDUAL_TOLERANCE_FRACTION:
            raise ValueError(
                "mass_flow_residual_tolerance_fraction must equal "
                "network.candidate.SELF_CONSISTENT_FLOW_MASS_FLOW_RESIDUAL_TOLERANCE_FRACTION in this version"
            )
        if self.max_iterations != SELF_CONSISTENT_FLOW_MAX_ITERATIONS:
            raise ValueError(
                "max_iterations must equal network.candidate.SELF_CONSISTENT_FLOW_MAX_ITERATIONS in this version"
            )
        return self


class GeothermalDoubletHandles(BaseModel):
    """pandapipes element NAMES (not raw indices -- same convention as
    network/candidate.py's own `_add_geothermal_injection_branch` return
    value) for audit/debugging (DLT-005)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    return_junction_name: str
    mid_junction_name: str
    supply_junction_name: str
    return_pipe_name: str
    supply_pipe_name: str
    pump_name: str
    heat_consumer_name: str


class GeothermalDoubletResult(BaseModel):
    """DLT-005's required result-extraction fields, for ONE geothermal
    connection's own construction+solve. Model-level invariants recompute
    every summary figure from its own stored fields, mirroring this
    project's established rigor (BaselineNetworkResult,
    CandidateEvaluationResult)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = DOUBLET_COMPONENT_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    available_geothermal_heat_kw: float
    """boundary.deliverable_geothermal_heat_kw, passthrough."""
    accepted_heat_kw: float
    """policy.accepted_heat_kw, passthrough -- the heat actually injected."""
    curtailed_heat_kw: float
    """available_geothermal_heat_kw - accepted_heat_kw. Cause-attribution
    (true surplus vs. numerical-stabilization margin) is NOT this
    component's concern -- see module docstring, "Scope boundary"."""

    brine_mass_flow_kg_s: float
    """spec.brine_mass_flow_kg_s, passthrough -- exposed for audit
    completeness; NEVER used in this component's own DH-side sizing
    (CLAUDE.md: brine and DH-water flow stay separate)."""
    district_heating_water_mass_flow_kg_s: float
    """The SOLVED (not merely requested) injection-branch mass flow."""

    inlet_temperature_c: float
    """The injection branch's ACTUAL solved inlet (return-side) temperature."""
    inlet_design_temperature_c: float
    outlet_temperature_c: float
    """The injection branch's ACTUAL solved outlet (supply-side) temperature."""
    outlet_design_temperature_c: float

    connection_differential_pressure_bar: float
    """Friction-loss-only pressure drop across the two connection pipes --
    excludes the injection pump's own lift (a separate quantity below)."""
    circulation_pump_hydraulic_power_kw: float
    """This component's OWN injection pump's hydraulic power -- distinct
    from the main plant circulation pump's own (a network-level, not
    per-connection, quantity outside this component's scope)."""

    flow_solver: SelfConsistentFlowDiagnostics
    """Reuses network/candidate.py's own diagnostics model directly
    (DRY -- an identical concept, no reason for a parallel type)."""

    handles: GeothermalDoubletHandles
    warnings: list[CouplingWarning] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "GeothermalDoubletResult":
        errors: list[str] = []
        if self.available_geothermal_heat_kw <= 0:
            errors.append("available_geothermal_heat_kw must be > 0")
        if self.accepted_heat_kw <= 0:
            errors.append("accepted_heat_kw must be > 0")
        if self.accepted_heat_kw > self.available_geothermal_heat_kw + 1e-9:
            errors.append("accepted_heat_kw must not exceed available_geothermal_heat_kw")
        expected_curtailed = self.available_geothermal_heat_kw - self.accepted_heat_kw
        if not math.isclose(expected_curtailed, self.curtailed_heat_kw, rel_tol=1e-9, abs_tol=1e-9):
            errors.append("curtailed_heat_kw does not match recomputation")
        if self.curtailed_heat_kw < 0:
            errors.append("curtailed_heat_kw must be >= 0")
        if self.district_heating_water_mass_flow_kg_s <= 0:
            errors.append("district_heating_water_mass_flow_kg_s must be > 0")
        if self.connection_differential_pressure_bar < 0:
            errors.append("connection_differential_pressure_bar must be >= 0")
        if self.circulation_pump_hydraulic_power_kw < 0:
            errors.append("circulation_pump_hydraulic_power_kw must be >= 0")
        expected_outlet_dev = self.outlet_temperature_c - self.outlet_design_temperature_c
        if not math.isclose(
            self.flow_solver.final_outlet_temperature_deviation_k, expected_outlet_dev, rel_tol=1e-9, abs_tol=1e-9,
        ):
            errors.append("flow_solver.final_outlet_temperature_deviation_k does not match outlet temperatures")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class GeothermalDoubletFailure(BaseModel):
    """A rejected component construction/solve -- always preserves the
    complete input spec set, same rule as every earlier layer."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = DOUBLET_COMPONENT_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"
    failure_code: CandidateFailureCode
    """Reuses CandidateFailureCode -- restricted in practice to the three
    codes intrinsic to this component's own scope (module docstring,
    "Scope boundary"): THERMAL_PIPEFLOW_NOT_CONVERGED,
    GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT,
    SELF_CONSISTENT_FLOW_NOT_CONVERGED."""
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    spec: GeothermalDoubletSpec
    boundary: HeatExchangerBoundary
    connection: DistrictHeatingConnectionSpec
    policy: DoubletOperatingPolicy
    created_at: datetime


GeothermalDoubletBoundaryResult = Annotated[
    Union[GeothermalDoubletResult, GeothermalDoubletFailure],
    Field(discriminator="status"),
]
"""Real Pydantic discriminated union on `status`, resolved via a
TypeAdapter -- the same established pattern as every earlier layer's
BoundaryResult."""

_boundary_result_adapter: TypeAdapter = TypeAdapter(GeothermalDoubletBoundaryResult)


def parse_doublet_component_result_json(json_str: str) -> GeothermalDoubletBoundaryResult:
    """Deserialize a JSON string produced by either model's
    model_dump_json() back into the correct typed model via Pydantic's
    discriminated-union validation -- full model-level invariant
    re-validation included."""
    return _boundary_result_adapter.validate_json(json_str)


def build_and_evaluate_geothermal_doublet(
    blueprint: NetworkBlueprint,
    spec: GeothermalDoubletSpec,
    boundary: HeatExchangerBoundary,
    connection: DistrictHeatingConnectionSpec,
    policy: DoubletOperatingPolicy,
) -> GeothermalDoubletBoundaryResult:
    """DLT-001's reusable construction+extraction entry point.

    DLT-004 (isolation/idempotence): builds a FRESH net from `blueprint`
    on every call (never a shared/cached net, never mutating `blueprint`
    itself -- it is a frozen Pydantic model regardless); repeated calls
    with identical inputs produce identical scientific outputs (see
    tests/network/test_doublet_component.py's own determinism test).

    Delegates topology construction and (when
    policy.injection_sizing_policy=="self_consistent") flow-sizing to
    network/candidate.py's own already-tested private functions -- module
    docstring, "Relationship to network/candidate.py" -- guaranteeing
    parity by construction (DLT-006/AC-07), not merely by a tolerance
    check."""
    created_at = datetime.now(timezone.utc)

    def _failure(failure_code: CandidateFailureCode, message: str, details: dict[str, Any]) -> GeothermalDoubletFailure:
        return GeothermalDoubletFailure(
            failure_code=failure_code, message=message, details=details,
            spec=spec, boundary=boundary, connection=connection, policy=policy, created_at=created_at,
        )

    candidate = connection.candidate
    dh_supply_c = connection.dh_supply_temperature_c
    dh_return_c = connection.dh_return_temperature_c
    cp_j_kg_k = connection.dh_water_specific_heat_capacity_j_kg_k

    if policy.injection_sizing_policy == "self_consistent":
        try:
            net, refs, iteration_count, mass_flow_kg_s = _solve_self_consistent_injection(
                blueprint, candidate, policy.accepted_heat_kw, dh_supply_c, dh_return_c, cp_j_kg_k,
            )
        except pandapipes.PipeflowNotConverged as exc:
            return _failure(
                CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED,
                f"pandapipes pipeflow(mode='sequential') did not converge: {exc}", {},
            )
        except UserWarning as exc:
            return _failure(
                CandidateFailureCode.GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT,
                f"pandapipes raised UserWarning during pipeflow(): {exc}", {},
            )
        except _SelfConsistentFlowNotConverged as exc:
            return _failure(
                CandidateFailureCode.SELF_CONSISTENT_FLOW_NOT_CONVERGED, str(exc),
                {
                    "iteration_count": exc.iteration_count, "max_iterations": policy.max_iterations,
                    "final_mass_flow_kg_s": exc.final_mass_flow_kg_s,
                    "final_outlet_temperature_deviation_k": exc.final_outlet_temperature_deviation_k,
                },
            )
    else:
        mass_flow_kg_s = _compute_injected_mass_flow_kg_s(policy.accepted_heat_kw, dh_supply_c, dh_return_c, cp_j_kg_k)
        net = build_pandapipes_net(blueprint)
        refs = _add_geothermal_injection_branch(
            net, candidate, blueprint, policy.accepted_heat_kw, mass_flow_kg_s, dh_supply_c, dh_return_c,
        )
        iteration_count = 1
        try:
            pandapipes.pipeflow(net, mode="sequential")
        except pandapipes.PipeflowNotConverged as exc:
            return _failure(
                CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED,
                f"pandapipes pipeflow(mode='sequential') did not converge: {exc}", {},
            )
        except UserWarning as exc:
            return _failure(
                CandidateFailureCode.GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT,
                f"pandapipes raised UserWarning during pipeflow(): {exc}", {},
            )

    hc_idx = {name: idx for idx, name in enumerate(net.heat_consumer["name"])}
    pump_idx = {name: idx for idx, name in enumerate(net.pump["name"])}
    junction_idx = {name: idx for idx, name in enumerate(net.junction["name"])}

    geo_hc_row = net.res_heat_consumer.iloc[hc_idx[refs["heat_consumer"]]]
    geo_mass_flow_kg_s = abs(geo_hc_row["mdot_from_kg_per_s"])
    geo_pump_row = net.res_pump.iloc[pump_idx[refs["pump"]]]
    connection_pumping_power_kw = float(geo_pump_row["compr_power_mw"]) * 1000.0

    return_pressure_bar_abs = to_absolute_bar(net.res_junction.at[junction_idx[candidate.return_junction], "p_bar"])
    geo_return_pressure_bar_abs = to_absolute_bar(net.res_junction.at[junction_idx[refs["geo_return"]], "p_bar"])
    geo_supply_pressure_bar_abs = to_absolute_bar(net.res_junction.at[junction_idx[refs["geo_supply"]], "p_bar"])
    supply_pressure_bar_abs = to_absolute_bar(net.res_junction.at[junction_idx[candidate.supply_junction], "p_bar"])
    connection_pressure_drop_bar = (
        (return_pressure_bar_abs - geo_return_pressure_bar_abs) + (geo_supply_pressure_bar_abs - supply_pressure_bar_abs)
    )

    inlet_actual_c = float(geo_hc_row["t_from_k"]) - 273.15
    outlet_actual_c = float(geo_hc_row["t_outlet_k"]) - 273.15

    flow_solver = SelfConsistentFlowDiagnostics(
        enabled=policy.injection_sizing_policy == "self_consistent", iteration_count=iteration_count,
        initial_mass_flow_kg_s=_compute_injected_mass_flow_kg_s(policy.accepted_heat_kw, dh_supply_c, dh_return_c, cp_j_kg_k),
        final_mass_flow_kg_s=mass_flow_kg_s, final_outlet_temperature_deviation_k=outlet_actual_c - dh_supply_c,
        outlet_temperature_tolerance_k=policy.outlet_temperature_tolerance_k,
        mass_flow_residual_tolerance_fraction=policy.mass_flow_residual_tolerance_fraction,
        max_iterations=policy.max_iterations,
    )

    handles = GeothermalDoubletHandles(
        return_junction_name=refs["geo_return"], mid_junction_name=refs["geo_mid"], supply_junction_name=refs["geo_supply"],
        return_pipe_name=refs["return_pipe"], supply_pipe_name=refs["supply_pipe"],
        pump_name=refs["pump"], heat_consumer_name=refs["heat_consumer"],
    )

    return GeothermalDoubletResult(
        available_geothermal_heat_kw=boundary.deliverable_geothermal_heat_kw,
        accepted_heat_kw=policy.accepted_heat_kw,
        curtailed_heat_kw=boundary.deliverable_geothermal_heat_kw - policy.accepted_heat_kw,
        brine_mass_flow_kg_s=spec.brine_mass_flow_kg_s,
        district_heating_water_mass_flow_kg_s=geo_mass_flow_kg_s,
        inlet_temperature_c=inlet_actual_c, inlet_design_temperature_c=dh_return_c,
        outlet_temperature_c=outlet_actual_c, outlet_design_temperature_c=dh_supply_c,
        connection_differential_pressure_bar=connection_pressure_drop_bar,
        circulation_pump_hydraulic_power_kw=connection_pumping_power_kw,
        flow_solver=flow_solver, handles=handles, warnings=[], created_at=created_at,
    )
