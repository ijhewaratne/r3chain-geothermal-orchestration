"""Deterministic PyDoublet-to-DH heat-exchanger adapter (T2.1).

Decides whether, and how much, of a doublet's raw geothermal power can
actually reach the district-heating (DH) side of a surface heat exchanger.
Enforces the project's central rule: raw PyDoublet thermal power is NOT
automatically DH-deliverable power (implementation plan §9, CLAUDE.md).

Input is always an already-validated PyDoubletCouplingResult (T1.5B's
success model) -- never raw JSON, never PyDoubletCouplingFailure. T1.5B
already owns "is this a valid, convergent, correctly-sourced PyDoublet
result"; re-deriving any of that here would duplicate that authority and
violate the project's separate-layers rule.

Scope boundary (T2.1): no synthetic pandapipes network, no candidate
evaluator, no GEOTHERMAL_CAPACITY_SHORTFALL/auxiliary-heat/curtailment
accounting (needs a candidate's DH demand -- Phase 4), no economics, no MCP.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..contracts import CouplingWarning, NormalizedQuantity, PyDoubletCouplingResult
from .assumptions import CouplingAssumptions
from .errors import RAW_POWER_CEILING_BINDING, AdapterFailureCode

ADAPTER_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""The adapter-contract schema version -- versioned independently of T1.5B's
CONTRACT_SCHEMA_VERSION (r3chain_geothermal.contracts.coupling_result). Each
layer's contract versions on its own timeline."""


# ── Pure computation helpers -- the single source of truth for the physics,
# called both by evaluate_heat_exchanger_coupling() and by
# HeatExchangerCouplingResult's own model-level invariant recomputation, so
# the two can never silently drift apart. ──

def _compute_raw_energy_consistency(
    coupling_input: PyDoubletCouplingResult,
) -> tuple[float, float, float]:
    """Returns (computed_power_kw, reported_power_kw, relative_difference).

    computed_power_kw = m_dot_brine * cp_brine * (T_prod - T_brine_outlet) / 1000,
    using coupling_input.geothermal_brine_hx_outlet_temperature_c -- what
    THIS SPECIFIC PyDoublet run assumed for its own heat-exchanger exit
    temperature (verifying PyDoublet's own arithmetic), NOT
    assumptions.reinjection_minimum_temperature_c (the adapter's separate
    policy floor, used only in _compute_allowable_brine_outlet below).
    """
    mass_flow = coupling_input.geothermal_brine_mass_flow_kg_s.value
    specific_heat = coupling_input.geothermal_brine_specific_heat_capacity_j_kg_k.value
    t_prod = coupling_input.producer_wellhead_temperature_c.value
    t_brine_outlet = coupling_input.geothermal_brine_hx_outlet_temperature_c.value
    reported_kw = coupling_input.raw_geothermal_thermal_power_kw.value

    computed_kw = mass_flow * specific_heat * (t_prod - t_brine_outlet) / 1000.0
    relative_difference = (
        abs(computed_kw - reported_kw) / abs(reported_kw)
        if reported_kw != 0 else abs(computed_kw - reported_kw)
    )
    return computed_kw, reported_kw, relative_difference


def _compute_allowable_brine_outlet(
    assumptions: CouplingAssumptions,
) -> tuple[float, Literal["reinjection_minimum", "dh_return_plus_approach"]]:
    """T_geo,out,allowed = max(T_reinj_min, T_DH,return + minimum_hx_approach_k)
    (plan §9.3). On a tie, reinjection_minimum wins (matches Python's own
    max() semantics for max(a, b), which keeps the first argument on a tie)."""
    reinjection_minimum = assumptions.reinjection_minimum_temperature_c
    dh_return_plus_approach = assumptions.dh_return_temperature_c + assumptions.minimum_hx_approach_k
    if reinjection_minimum >= dh_return_plus_approach:
        return reinjection_minimum, "reinjection_minimum"
    return dh_return_plus_approach, "dh_return_plus_approach"


def _compute_deliverable_heat(
    coupling_input: PyDoubletCouplingResult, assumptions: CouplingAssumptions,
    allowable_brine_outlet_c: float,
) -> tuple[float, Literal["pydoublet_reported_power", "temperature_limited_heat"]]:
    """Q_direct = min(Q_raw, m_dot_brine * cp_brine * (T_prod - T_geo,out,allowed) / 1000) * eta
    (plan §9.3). On a tie, pydoublet_reported_power wins (matches Python's
    min(a, b) semantics, which keeps the first argument on a tie)."""
    mass_flow = coupling_input.geothermal_brine_mass_flow_kg_s.value
    specific_heat = coupling_input.geothermal_brine_specific_heat_capacity_j_kg_k.value
    t_prod = coupling_input.producer_wellhead_temperature_c.value
    reported_kw = coupling_input.raw_geothermal_thermal_power_kw.value

    temperature_limited_kw = mass_flow * specific_heat * (t_prod - allowable_brine_outlet_c) / 1000.0
    if reported_kw <= temperature_limited_kw:
        pre_factor_kw: float = reported_kw
        binding: Literal["pydoublet_reported_power", "temperature_limited_heat"] = "pydoublet_reported_power"
    else:
        pre_factor_kw = temperature_limited_kw
        binding = "temperature_limited_heat"
    return pre_factor_kw * assumptions.hx_heat_delivery_factor, binding


def _compute_dh_mass_flow(deliverable_heat_kw: float, assumptions: CouplingAssumptions) -> float:
    """m_dot_DH = Q_DH / (cp_water * (T_supply - T_return)) (plan §9.4) --
    computed entirely independently from geothermal_brine_mass_flow_kg_s."""
    cp_dh_water_kj_per_kg_k = assumptions.dh_water_specific_heat_capacity_j_kg_k / 1000.0
    delta_t_dh = assumptions.dh_supply_temperature_c - assumptions.dh_return_temperature_c
    return deliverable_heat_kw / (cp_dh_water_kj_per_kg_k * delta_t_dh)


class EnergyConsistencyCheck(BaseModel):
    """Result of independently recomputing PyDoublet's raw energy balance
    and comparing it against the upstream reported value (plan §9.2)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    computed_power_kw: NormalizedQuantity
    reported_power_kw: NormalizedQuantity
    relative_difference: float
    tolerance_fraction: float
    passed: Literal[True] = True


class HeatExchangerCouplingResult(BaseModel):
    """A successful heat-exchanger coupling evaluation.

    Model-level invariants (enforced on every construction/deserialization,
    mirroring T1.5B's contract): every recorded quantity is finite and
    carries its required unit; the entire physics chain is recomputed from
    `coupling_input` + `assumptions` via the same pure helper functions the
    evaluator itself uses, and every stored value/binding-constraint must
    match that recomputation exactly -- a hand-tampered or hand-constructed
    payload that doesn't reflect a genuine evaluation is rejected, not
    silently accepted.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_schema_version: Literal["1.0.0"] = ADAPTER_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    coupling_input: PyDoubletCouplingResult
    """The complete upstream T1.5B result, embedded verbatim -- not just its
    identifiers. This is what "preserve the complete coupling input" means
    concretely."""
    assumptions: CouplingAssumptions
    """The exact coupling-boundary assumptions snapshot used for this
    evaluation."""

    raw_energy_consistency_check: EnergyConsistencyCheck

    hot_end_feasibility_margin_k: float
    """T_prod - (dh_supply_temperature_c + minimum_hx_approach_k). Always
    >= 0 on a success result -- a signed margin (not just a pass/fail bool)
    for the ranking layer's "greater technical margin" tie-breaker
    (plan §12.3)."""

    allowable_brine_outlet_temperature_c: NormalizedQuantity
    allowable_brine_outlet_binding_constraint: Literal["reinjection_minimum", "dh_return_plus_approach"]

    deliverable_geothermal_heat_kw: NormalizedQuantity
    deliverable_heat_binding_constraint: Literal["pydoublet_reported_power", "temperature_limited_heat"]

    district_heating_water_mass_flow_kg_s: NormalizedQuantity
    """Computed entirely independently from
    coupling_input.geothermal_brine_mass_flow_kg_s -- brine flow and DH-water
    flow are never conflated (CLAUDE.md)."""

    warnings: list[CouplingWarning] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "HeatExchangerCouplingResult":
        errors: list[str] = []

        required_units = {
            "allowable_brine_outlet_temperature_c": "degC",
            "deliverable_geothermal_heat_kw": "kW",
            "district_heating_water_mass_flow_kg_s": "kg/s",
        }
        for field_name, expected_unit in required_units.items():
            quantity: NormalizedQuantity = getattr(self, field_name)
            if not math.isfinite(quantity.value):
                errors.append(f"{field_name}.value must be finite, got {quantity.value!r}")
            if quantity.unit != expected_unit:
                errors.append(f"{field_name}.unit must be {expected_unit!r}, got {quantity.unit!r}")

        check = self.raw_energy_consistency_check
        if check.computed_power_kw.unit != "kW" or check.reported_power_kw.unit != "kW":
            errors.append("raw_energy_consistency_check quantities must be in kW")
        if not check.passed:
            errors.append("raw_energy_consistency_check.passed must be True on a success result")
        if check.relative_difference > check.tolerance_fraction:
            errors.append(
                "raw_energy_consistency_check.relative_difference exceeds its own tolerance_fraction"
            )

        if self.hot_end_feasibility_margin_k < 0:
            errors.append("hot_end_feasibility_margin_k must be >= 0 on a success result")
        if self.district_heating_water_mass_flow_kg_s.value <= 0:
            errors.append("district_heating_water_mass_flow_kg_s.value must be > 0")
        if self.deliverable_geothermal_heat_kw.value <= 0:
            errors.append("deliverable_geothermal_heat_kw.value must be > 0")
        # NOTE: district_heating_water_mass_flow_kg_s and
        # geothermal_brine_mass_flow_kg_s are REQUIRED to be computed via
        # independent formulas (enforced below by recomputation from
        # coupling_input/assumptions), but their VALUES may coincidentally
        # be numerically equal -- that is not itself a defect and must not
        # be rejected. "Separately derived" is enforced by the
        # recomputation check, not by a value-inequality check.

        # Recompute the entire physics chain and cross-check every stored value.
        computed_kw, reported_kw, rel_diff = _compute_raw_energy_consistency(self.coupling_input)
        if not math.isclose(computed_kw, check.computed_power_kw.value, rel_tol=1e-9):
            errors.append("raw_energy_consistency_check.computed_power_kw does not match recomputation")
        if not math.isclose(reported_kw, check.reported_power_kw.value, rel_tol=1e-9):
            errors.append("raw_energy_consistency_check.reported_power_kw does not match coupling_input")
        if not math.isclose(rel_diff, check.relative_difference, rel_tol=1e-9, abs_tol=1e-15):
            errors.append("raw_energy_consistency_check.relative_difference does not match recomputation")

        allowable_c, allowable_binding = _compute_allowable_brine_outlet(self.assumptions)
        if not math.isclose(allowable_c, self.allowable_brine_outlet_temperature_c.value, rel_tol=1e-9):
            errors.append("allowable_brine_outlet_temperature_c does not match recomputation")
        if allowable_binding != self.allowable_brine_outlet_binding_constraint:
            errors.append("allowable_brine_outlet_binding_constraint does not match recomputation")

        deliverable_kw, deliverable_binding = _compute_deliverable_heat(
            self.coupling_input, self.assumptions, self.allowable_brine_outlet_temperature_c.value,
        )
        if not math.isclose(deliverable_kw, self.deliverable_geothermal_heat_kw.value, rel_tol=1e-9):
            errors.append("deliverable_geothermal_heat_kw does not match recomputation")
        if deliverable_binding != self.deliverable_heat_binding_constraint:
            errors.append("deliverable_heat_binding_constraint does not match recomputation")

        dh_flow = _compute_dh_mass_flow(self.deliverable_geothermal_heat_kw.value, self.assumptions)
        if not math.isclose(dh_flow, self.district_heating_water_mass_flow_kg_s.value, rel_tol=1e-9):
            errors.append("district_heating_water_mass_flow_kg_s does not match recomputation")

        expected_margin = self.coupling_input.producer_wellhead_temperature_c.value - (
            self.assumptions.dh_supply_temperature_c + self.assumptions.minimum_hx_approach_k
        )
        if not math.isclose(expected_margin, self.hot_end_feasibility_margin_k, rel_tol=1e-9, abs_tol=1e-9):
            errors.append("hot_end_feasibility_margin_k does not match recomputation")

        if errors:
            raise ValueError("; ".join(errors))
        return self


class HeatExchangerCouplingFailure(BaseModel):
    """A rejected heat-exchanger coupling evaluation. Always preserves the
    complete coupling input and the assumptions used -- a failure is still
    fully auditable, same rule as T1.5B."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_schema_version: Literal["1.0.0"] = ADAPTER_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"
    failure_code: AdapterFailureCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    coupling_input: PyDoubletCouplingResult
    assumptions: CouplingAssumptions
    created_at: datetime


HeatExchangerBoundaryResult = Annotated[
    Union[HeatExchangerCouplingResult, HeatExchangerCouplingFailure],
    Field(discriminator="status"),
]
"""Real Pydantic discriminated union on `status`, resolved via a TypeAdapter
-- the same established pattern as PyDoubletBoundaryResult (T1.5B)."""

_boundary_result_adapter: TypeAdapter = TypeAdapter(HeatExchangerBoundaryResult)


def parse_heat_exchanger_result_json(json_str: str) -> HeatExchangerBoundaryResult:
    """Deserialize a JSON string produced by either model's
    model_dump_json() back into the correct typed model via Pydantic's
    discriminated-union validation -- full model-level invariant
    re-validation included."""
    return _boundary_result_adapter.validate_json(json_str)


def evaluate_heat_exchanger_coupling(
    coupling_input: PyDoubletCouplingResult,
    *,
    assumptions: CouplingAssumptions,
) -> HeatExchangerBoundaryResult:
    """Evaluate one PyDoublet coupling result against the DH heat-exchanger
    boundary. Gate order (implementation plan §11, items 1-4; items 5-11 are
    pandapipes/network, out of T2.1's scope):

    1. (T1.5B's job -- coupling_input's very type guarantees this.)
    2. Unit/sign + raw energy consistency -> UNIT_OR_SIGN_ERROR.
    3. HX hot-end feasibility -> HX_SUPPLY_TEMPERATURE_INFEASIBLE.
    4. HX cold-end/pinch feasibility -> HX_COLD_END_APPROACH_INFEASIBLE.

    Never raises for any of the three recognized failure modes.
    """
    created_at = datetime.now(timezone.utc)

    computed_kw, reported_kw, relative_difference = _compute_raw_energy_consistency(coupling_input)
    if relative_difference > assumptions.energy_consistency_tolerance_fraction:
        return HeatExchangerCouplingFailure(
            failure_code=AdapterFailureCode.UNIT_OR_SIGN_ERROR,
            message=(
                "Independently recomputed raw energy balance "
                "(m_dot_brine * cp_brine * (T_prod - T_brine_outlet)) disagrees "
                "with the upstream raw_geothermal_thermal_power_kw beyond the "
                "configured tolerance."
            ),
            details={
                "computed_power_kw": computed_kw, "reported_power_kw": reported_kw,
                "relative_difference": relative_difference,
                "tolerance_fraction": assumptions.energy_consistency_tolerance_fraction,
            },
            coupling_input=coupling_input, assumptions=assumptions, created_at=created_at,
        )

    t_prod = coupling_input.producer_wellhead_temperature_c.value
    required_minimum_c = assumptions.dh_supply_temperature_c + assumptions.minimum_hx_approach_k
    hot_end_feasibility_margin_k = t_prod - required_minimum_c
    if hot_end_feasibility_margin_k < 0:
        return HeatExchangerCouplingFailure(
            failure_code=AdapterFailureCode.HX_SUPPLY_TEMPERATURE_INFEASIBLE,
            message=(
                "producer_wellhead_temperature_c is below dh_supply_temperature_c "
                "+ minimum_hx_approach_k -- the hot end of the heat exchanger "
                "cannot meet the DH supply temperature."
            ),
            details={
                "producer_wellhead_temperature_c": t_prod,
                "required_minimum_c": required_minimum_c,
                "shortfall_k": -hot_end_feasibility_margin_k,
            },
            coupling_input=coupling_input, assumptions=assumptions, created_at=created_at,
        )

    allowable_brine_outlet_c, allowable_binding = _compute_allowable_brine_outlet(assumptions)
    if t_prod <= allowable_brine_outlet_c:
        return HeatExchangerCouplingFailure(
            failure_code=AdapterFailureCode.HX_COLD_END_APPROACH_INFEASIBLE,
            message=(
                "producer_wellhead_temperature_c does not exceed the allowable "
                "brine outlet temperature -- no positive temperature difference "
                "remains from which to extract heat."
            ),
            details={
                "producer_wellhead_temperature_c": t_prod,
                "allowable_brine_outlet_temperature_c": allowable_brine_outlet_c,
            },
            coupling_input=coupling_input, assumptions=assumptions, created_at=created_at,
        )

    deliverable_kw, deliverable_binding = _compute_deliverable_heat(
        coupling_input, assumptions, allowable_brine_outlet_c,
    )
    dh_mass_flow = _compute_dh_mass_flow(deliverable_kw, assumptions)

    warnings: list[CouplingWarning] = []
    if deliverable_binding == "pydoublet_reported_power":
        warnings.append(CouplingWarning(
            code=RAW_POWER_CEILING_BINDING,
            message=(
                "Deliverable heat is capped by the PyDoublet-reported raw "
                "geothermal power, not by the DH-side temperature limit."
            ),
            affects=["deliverable_geothermal_heat_kw"],
        ))

    return HeatExchangerCouplingResult(
        coupling_input=coupling_input,
        assumptions=assumptions,
        raw_energy_consistency_check=EnergyConsistencyCheck(
            computed_power_kw=NormalizedQuantity(value=computed_kw, unit="kW"),
            reported_power_kw=NormalizedQuantity(value=reported_kw, unit="kW"),
            relative_difference=relative_difference,
            tolerance_fraction=assumptions.energy_consistency_tolerance_fraction,
        ),
        hot_end_feasibility_margin_k=hot_end_feasibility_margin_k,
        allowable_brine_outlet_temperature_c=NormalizedQuantity(value=allowable_brine_outlet_c, unit="degC"),
        allowable_brine_outlet_binding_constraint=allowable_binding,
        deliverable_geothermal_heat_kw=NormalizedQuantity(value=deliverable_kw, unit="kW"),
        deliverable_heat_binding_constraint=deliverable_binding,
        district_heating_water_mass_flow_kg_s=NormalizedQuantity(value=dh_mass_flow, unit="kg/s"),
        warnings=warnings,
        created_at=created_at,
    )
