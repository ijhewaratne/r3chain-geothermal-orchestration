"""Baseline network evaluator (T2.2B): runs the T2.2A-built pandapipes
network, extracts every plan-§12.1 KPI, and applies plan-§11 gates 6-11
(items 1-5 belong to other layers/phases -- see errors.py).

CRITICAL, twice-corrected: pandapipes' own `qext_w` reporting convention is
NOT a true thermodynamic enthalpy difference, and its own integration
helper is independently verified buggy. Two separate findings:

**Finding 1 (first correction round).** Reading pandapipes 0.14.0 source
directly (component_models/abstract_models/circulation_pump.py vs.
component_models/heat_consumer_component.py):
`HeatConsumer.extract_results()` echoes the fixed input `qext_w` verbatim;
`CirculationPump.extract_results()` computes
`mass * (cp(t_out)*t_out - cp(t_from)*t_from)` using pandapipes' real
temperature-dependent water heat capacity. This is pandapipes' own
*reporting convention* for `qext_w` -- **not** a true enthalpy integral.
When cp varies with T, `cp(T_hot)*T_hot - cp(T_cold)*T_cold` != the true
sensible enthalpy change `integral[T_cold, T_hot] cp(T) dT` (they coincide
only if cp is constant). Comparing `res_circ_pump_pressure.qext_w`
(~3289.26 kW) against the consumer demand total (3200.0 kW exactly) shows a
~2.79% gap that is this REPORTING-CONVENTION difference -- not a physical
energy imbalance, and not hidden: both quantities and their difference are
reported explicitly on `PandapipesInternalEnergyConsistency` /
`total_heat_delivered_kw`. Recomputing consumer heat via pandapipes' SAME
(flawed) formula, using each consumer's own solved state, reproduces the
pump's figure to machine precision (~5.7e-16) -- this proves the
RE-IMPLEMENTATION is arithmetically faithful to pandapipes' own convention,
not that physical energy is conserved. Kept as
`PandapipesInternalEnergyConsistency`, a solver self-consistency
*diagnostic*, explicitly not gated on.

**Finding 2 (this correction round).** The TRUE sensible enthalpy change is
`Delta h = integral[T_cold, T_hot] cp(T) dT`. pandapipes DOES expose an
integration helper for this (`FluidPropertyInterExtra.get_at_integral_value()`,
properties/fluids.py) -- but it is a confirmed defect in the installed
version (0.14.0): it evaluates the property at the upper limit twice instead
of averaging upper and lower. Full reproduction, evidence and a
re-verification procedure for future pandapipes versions are recorded in
`docs/technical-observations/pandapipes-heat-capacity-integral-defect.md` --
**not** reproduced in full here, and **not** encoded as a permanent
expected-failure test: this module simply never calls that method (a
structural test enforces the non-dependence, so the suite's health does not
hinge on whether a future pandapipes release fixes it).
`_integrate_specific_heat_j_per_kg()` below is instead a from-scratch
composite trapezoidal integration (`ENTHALPY_INTEGRATION_SEGMENTS` segments,
a named constant; pure Python, no new dependency -- neither NumPy nor SciPy
is imported directly by this module), sampling only the separately-verified-
correct `fluid.get_heat_capacity()` point evaluation. `EnergyBalanceCheck`
records its own `integration_method` and `integration_segments` for
provenance/audit.

`EnergyBalanceCheck` (the field this project's UNCHANGED 2% gate,
gates.energy_balance_tolerance_fraction, actually applies to) is built from
this integral, comparing the pump's physical enthalpy gain against the sum
of consumers' physical enthalpy extraction plus physical pipe heat loss
(same integration method, applied consistently to all three). At this
baseline's operating point the residual is ~5.7e-16. **Read this precisely,
not as more than it is:** every consumer and the pump operate between the
SAME two temperatures (313.15 K <-> 343.15 K, the uniform design ΔT), so
every side of this comparison integrates the identical cp(T) curve over the
identical bounds -- the calculation is consistency under the SAME
integration method applied to values that already satisfy mass balance to
~1e-16 (verified separately), not three independently-measured physical
quantities happening to agree. It demonstrates the physical-balance
CALCULATION is internally consistent and correctly wired, given already-
consistent mass balance -- it is not, by itself, an experimental
confirmation that energy is conserved independent of the mass-balance
result it is built on. A future scenario with per-consumer temperature
diversity (non-uniform ΔT) or non-adiabatic pipes would exercise genuinely
distinct integration bounds per component and could show a different,
informative physical residual -- which is exactly why the physical
calculation (not the reporting-convention comparison) is what must be
gated, even though today's baseline is a comparatively weak test of it.

"Heat delivered" (KPI, `ConsumerBaselineResult.heat_delivered_kw` -- the
simple, correct "was demand met" quantity, `res_heat_consumer.qext_w`
directly), "pandapipes-internal reporting consistency" (diagnostic, not
gated), and "physical energy balance" (the actual gate) are three
deliberately DISTINCT quantities on this model -- never conflate them.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

import pandapipes
from pandapipes.properties.fluids import get_fluid
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..contracts import CouplingWarning
from .blueprint import NetworkBlueprint
from .builder import build_pandapipes_net
from .errors import BaselineFailureCode
from .pressure import to_absolute_bar

BASELINE_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""Versioned independently of every other layer's own contract schema."""

ENTHALPY_INTEGRATION_METHOD: Literal["composite_trapezoidal"] = "composite_trapezoidal"
ENTHALPY_INTEGRATION_SEGMENTS = 100
"""Named, auditable choice for `_integrate_specific_heat_j_per_kg()`'s
composite-trapezoidal integral cp(T) dT. Verified (see
test_baseline.py::test_integration_segment_count_converges_to_exact_integral)
to agree with the hand-computed exact piecewise-linear integral (using the
water heat_capacity property table's own node temperatures) to ~9e-7
relative error at this count, and to change negligibly between 100 and 200
segments -- 100 is not an arbitrary/unaudited magic number. Recorded on
every EnergyBalanceCheck for provenance."""


class GateTolerances(BaseModel):
    """The subset of config/demo_assumptions.json::gates this evaluator
    consumes. Named `tolerances`, not `assumptions`, to avoid confusion
    with adapter.CouplingAssumptions -- a distinct concept."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    max_consumer_supply_drop_k: float
    min_pressure_bar_abs: float
    max_pipe_velocity_m_s: float
    mass_balance_tolerance_fraction: float
    energy_balance_tolerance_fraction: float

    @model_validator(mode="after")
    def _validate_positive(self) -> "GateTolerances":
        errors: list[str] = []
        for name in (
            "max_consumer_supply_drop_k", "min_pressure_bar_abs", "max_pipe_velocity_m_s",
            "mass_balance_tolerance_fraction", "energy_balance_tolerance_fraction",
        ):
            if getattr(self, name) <= 0:
                errors.append(f"{name} must be > 0, got {getattr(self, name)!r}")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @classmethod
    def from_config_dict(cls, config: dict[str, Any]) -> "GateTolerances":
        """Pure function -- no file I/O, mirrors adapter.CouplingAssumptions'
        established pattern."""
        gates = config["gates"]
        return cls(
            max_consumer_supply_drop_k=gates["max_consumer_supply_drop_k"],
            min_pressure_bar_abs=gates["min_pressure_bar_abs"],
            max_pipe_velocity_m_s=gates["max_pipe_velocity_m_s"],
            mass_balance_tolerance_fraction=gates["mass_balance_tolerance_fraction"],
            energy_balance_tolerance_fraction=gates["energy_balance_tolerance_fraction"],
        )


class ConsumerBaselineResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    heat_delivered_kw: float
    """The simple, correct KPI: res_heat_consumer.qext_w, kW. Equals design
    demand by construction (qext_w is a forced boundary condition in this
    component model) -- NOT the enthalpy-based quantity used in
    EnergyBalanceCheck."""
    supply_temperature_c: float
    return_temperature_c: float
    mass_flow_kg_s: float
    supply_temperature_drop_k: float
    """build_parameters.supply_temperature_c - supply_temperature_c. Zero
    under T2.2A's adiabatic pipes; the quantity CONSUMER_TEMPERATURE_NOT_MET
    gates on."""


class MassBalanceCheck(BaseModel):
    """Component boundary: the circulation pump's own branch mass flow vs.
    the sum of every consumer's supply-branch mass flow."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    pump_mass_flow_kg_s: float
    total_consumer_mass_flow_kg_s: float
    residual_fraction: float
    tolerance_fraction: float
    passed: bool


class EnergyBalanceCheck(BaseModel):
    """The PHYSICAL energy-balance gate -- the field
    gates.energy_balance_tolerance_fraction (unchanged, 0.02) actually
    applies to. Component boundary, explicit:
    pump_physical_enthalpy_kw ~= consumer_physical_enthalpy_kw + pipe_physical_heat_loss_kw.
    All three are computed via `_integrate_specific_heat_j_per_kg()` -- a
    genuine `integral cp(T) dT` (NOT pandapipes' own qext_w formula and NOT
    pandapipes' own get_at_integral_value() helper, a confirmed defect in
    the installed version -- see module docstring and
    docs/technical-observations/pandapipes-heat-capacity-integral-defect.md).
    pipe_physical_heat_loss_kw is 0.0 under T2.2A's adiabatic
    pipe_heat_transfer_coefficient_w_per_m2k=0.0 simplification, computed
    genuinely (not hardcoded) so a future non-adiabatic pipe model needs no
    restructuring here.

    integration_method/integration_segments record the exact numerical
    method used, for audit -- see ENTHALPY_INTEGRATION_METHOD/
    ENTHALPY_INTEGRATION_SEGMENTS.

    residual_fraction here reflects consistency of the SAME integration
    method applied to the pump and every consumer over the SAME temperature
    bounds, given already-consistent mass balance -- not an independent
    experimental confirmation of energy conservation. See module docstring."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    pump_physical_enthalpy_kw: float
    consumer_physical_enthalpy_kw: float
    pipe_physical_heat_loss_kw: float
    integration_method: Literal["composite_trapezoidal"]
    integration_segments: int
    residual_fraction: float
    tolerance_fraction: float
    passed: bool


class PandapipesInternalEnergyConsistency(BaseModel):
    """A solver self-consistency DIAGNOSTIC -- NOT a physical energy-balance
    check, and NOT gated on gates.energy_balance_tolerance_fraction (see
    EnergyBalanceCheck for that). Compares pandapipes' own `qext_w`
    reporting-convention formula (`mass * (cp(T_hot)*T_hot - cp(T_cold)*T_cold)`,
    which is NOT a true enthalpy integral when cp varies with T -- module
    docstring) applied to the pump's own reported result against an
    independent per-consumer recomputation using the SAME formula. Near-zero
    residual here proves this project's re-implementation of pandapipes' own
    formula is arithmetically faithful to what pandapipes itself reports --
    it does not prove physical energy conservation.

    reporting_convention_difference_fraction is the (pump_reported_qext_kw -
    consumer_demand_total_kw) / consumer_demand_total_kw gap -- reported
    explicitly, visibly, and never called a physical imbalance."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    pump_reported_qext_kw: float
    """res_circ_pump_pressure.qext_w, kW -- pandapipes' own reporting-convention result."""
    consumer_recomputed_qext_kw: float
    """Sum of res_heat_consumer rows recomputed via the SAME pandapipes
    reporting-convention formula (not the simple qext_w echo -- see
    ConsumerBaselineResult.heat_delivered_kw for that)."""
    consumer_demand_total_kw: float
    """The simple, correct KPI total (sum of ConsumerBaselineResult.heat_delivered_kw)
    -- same value as BaselineNetworkResult.total_heat_delivered_kw, repeated
    here for direct side-by-side comparison with pump_reported_qext_kw."""
    residual_fraction: float
    """|pump_reported_qext_kw - consumer_recomputed_qext_kw| / pump_reported_qext_kw
    -- the internal-consistency figure (machine precision when this
    project's own re-implementation is correct)."""
    reporting_convention_difference_fraction: float
    """|pump_reported_qext_kw - consumer_demand_total_kw| / consumer_demand_total_kw
    -- ~0.0279 at this baseline's operating point. A reporting-convention
    difference, explicitly NOT a physical imbalance (see EnergyBalanceCheck),
    and explicitly not hidden."""


class CirculationPumpResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    mass_flow_kg_s: float
    pressure_lift_bar: float
    """Measured (p_to_bar - p_from_bar) from results, not the blueprint's
    input spec -- cross-checked against it by a model invariant."""
    flow_temperature_c: float
    return_temperature_c: float
    hydraulic_pumping_power_kw: float
    """pressure_lift_bar[Pa] * vdot_m3_per_s / 1000 -- HYDRAULIC (fluid)
    power only. No electrical_pump_power_kw field: no pump-efficiency
    assumption exists anywhere in config/demo_assumptions.json (verified by
    grep) -- adding one is a new assumption requiring separate approval,
    not something to invent inline."""


class BaselineNetworkResult(BaseModel):
    """A successful baseline network evaluation.

    Model-level invariants cross-check every stored SUMMARY field against
    the STORED DETAIL fields it is computed from (total_heat_delivered_kw
    vs. sum of per-consumer values, min_pressure_bar_abs vs. the full
    per-junction dict, etc.) -- proving internal arithmetic consistency.
    This does NOT re-derive physics from raw pandapipes result tables (those
    are not embedded here, unlike PyDoubletCouplingResult's raw_result --
    embedding full pandapipes DataFrames was judged out of proportion to
    what this task asked for); it proves the reported numbers are mutually
    consistent, not independently re-solved.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = BASELINE_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    blueprint: NetworkBlueprint
    tolerances: GateTolerances

    consumers: dict[str, ConsumerBaselineResult]
    total_heat_delivered_kw: float
    min_consumer_supply_temperature_c: float
    mean_consumer_return_temperature_c: float

    junction_pressures_bar_abs: dict[str, float]
    min_pressure_bar_abs: float

    pipe_velocities_m_s: dict[str, float]
    max_velocity_m_s: float

    mass_balance: MassBalanceCheck
    energy_balance: EnergyBalanceCheck
    """The PHYSICAL energy-balance gate (true integral cp(T) dT) -- what
    gates.energy_balance_tolerance_fraction actually applies to."""
    pandapipes_internal_energy_consistency: PandapipesInternalEnergyConsistency
    """A solver self-consistency DIAGNOSTIC only, not gated -- see its own
    docstring and the module docstring."""
    circulation_pump: CirculationPumpResult

    warnings: list[CouplingWarning] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "BaselineNetworkResult":
        errors: list[str] = []

        if set(self.consumers.keys()) == set():
            errors.append("consumers must not be empty")

        computed_total = sum(c.heat_delivered_kw for c in self.consumers.values())
        if not math.isclose(computed_total, self.total_heat_delivered_kw, rel_tol=1e-9):
            errors.append("total_heat_delivered_kw does not match sum of per-consumer heat_delivered_kw")

        if self.consumers:
            computed_min_supply = min(c.supply_temperature_c for c in self.consumers.values())
            if not math.isclose(computed_min_supply, self.min_consumer_supply_temperature_c, rel_tol=1e-9, abs_tol=1e-9):
                errors.append("min_consumer_supply_temperature_c does not match recomputation")
            computed_mean_return = sum(c.return_temperature_c for c in self.consumers.values()) / len(self.consumers)
            if not math.isclose(computed_mean_return, self.mean_consumer_return_temperature_c, rel_tol=1e-9, abs_tol=1e-9):
                errors.append("mean_consumer_return_temperature_c does not match recomputation")

        if not self.junction_pressures_bar_abs:
            errors.append("junction_pressures_bar_abs must not be empty")
        else:
            computed_min_p = min(self.junction_pressures_bar_abs.values())
            if not math.isclose(computed_min_p, self.min_pressure_bar_abs, rel_tol=1e-9):
                errors.append("min_pressure_bar_abs does not match recomputation")
        if self.min_pressure_bar_abs <= 0:
            errors.append("min_pressure_bar_abs must be > 0")

        if not self.pipe_velocities_m_s:
            errors.append("pipe_velocities_m_s must not be empty")
        else:
            computed_max_v = max(self.pipe_velocities_m_s.values())
            if not math.isclose(computed_max_v, self.max_velocity_m_s, rel_tol=1e-9):
                errors.append("max_velocity_m_s does not match recomputation")
        if self.max_velocity_m_s < 0:
            errors.append("max_velocity_m_s must be >= 0")

        mb = self.mass_balance
        if mb.pump_mass_flow_kg_s <= 0:
            errors.append("mass_balance.pump_mass_flow_kg_s must be > 0")
        expected_mass_residual = (
            abs(mb.pump_mass_flow_kg_s - mb.total_consumer_mass_flow_kg_s) / mb.pump_mass_flow_kg_s
            if mb.pump_mass_flow_kg_s else float("inf")
        )
        if not math.isclose(expected_mass_residual, mb.residual_fraction, rel_tol=1e-9, abs_tol=1e-12):
            errors.append("mass_balance.residual_fraction does not match recomputation")
        if mb.passed != (mb.residual_fraction <= mb.tolerance_fraction):
            errors.append("mass_balance.passed is inconsistent with residual_fraction vs. tolerance_fraction")
        if not mb.passed:
            errors.append("mass_balance.passed must be True on a success result")

        eb = self.energy_balance
        if eb.pump_physical_enthalpy_kw <= 0:
            errors.append("energy_balance.pump_physical_enthalpy_kw must be > 0")
        expected_energy_residual = (
            abs(eb.pump_physical_enthalpy_kw - (eb.consumer_physical_enthalpy_kw + eb.pipe_physical_heat_loss_kw))
            / eb.pump_physical_enthalpy_kw if eb.pump_physical_enthalpy_kw else float("inf")
        )
        if not math.isclose(expected_energy_residual, eb.residual_fraction, rel_tol=1e-9, abs_tol=1e-12):
            errors.append("energy_balance.residual_fraction does not match recomputation")
        if eb.passed != (eb.residual_fraction <= eb.tolerance_fraction):
            errors.append("energy_balance.passed is inconsistent with residual_fraction vs. tolerance_fraction")
        if not eb.passed:
            errors.append("energy_balance.passed must be True on a success result")
        if eb.integration_method != ENTHALPY_INTEGRATION_METHOD:
            errors.append(
                f"energy_balance.integration_method must be {ENTHALPY_INTEGRATION_METHOD!r}, got {eb.integration_method!r}"
            )
        if eb.integration_segments != ENTHALPY_INTEGRATION_SEGMENTS:
            errors.append(
                f"energy_balance.integration_segments must be {ENTHALPY_INTEGRATION_SEGMENTS!r}, got {eb.integration_segments!r}"
            )

        pic = self.pandapipes_internal_energy_consistency
        if pic.pump_reported_qext_kw <= 0:
            errors.append("pandapipes_internal_energy_consistency.pump_reported_qext_kw must be > 0")
        expected_pic_residual = (
            abs(pic.pump_reported_qext_kw - pic.consumer_recomputed_qext_kw) / pic.pump_reported_qext_kw
        )
        if not math.isclose(expected_pic_residual, pic.residual_fraction, rel_tol=1e-9, abs_tol=1e-12):
            errors.append("pandapipes_internal_energy_consistency.residual_fraction does not match recomputation")
        expected_convention_diff = (
            abs(pic.pump_reported_qext_kw - pic.consumer_demand_total_kw) / pic.consumer_demand_total_kw
            if pic.consumer_demand_total_kw else float("inf")
        )
        if not math.isclose(expected_convention_diff, pic.reporting_convention_difference_fraction, rel_tol=1e-9, abs_tol=1e-12):
            errors.append("pandapipes_internal_energy_consistency.reporting_convention_difference_fraction does not match recomputation")
        if not math.isclose(pic.consumer_demand_total_kw, self.total_heat_delivered_kw, rel_tol=1e-9):
            errors.append("pandapipes_internal_energy_consistency.consumer_demand_total_kw must equal total_heat_delivered_kw")

        if self.circulation_pump.mass_flow_kg_s <= 0:
            errors.append("circulation_pump.mass_flow_kg_s must be > 0")
        if self.circulation_pump.hydraulic_pumping_power_kw < 0:
            errors.append("circulation_pump.hydraulic_pumping_power_kw must be >= 0")

        if errors:
            raise ValueError("; ".join(errors))
        return self


class BaselineNetworkFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = BASELINE_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"
    failure_code: BaselineFailureCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    blueprint: NetworkBlueprint
    created_at: datetime


BaselineBoundaryResult = Annotated[
    Union[BaselineNetworkResult, BaselineNetworkFailure],
    Field(discriminator="status"),
]
_boundary_result_adapter: TypeAdapter = TypeAdapter(BaselineBoundaryResult)


def parse_baseline_result_json(json_str: str) -> BaselineBoundaryResult:
    return _boundary_result_adapter.validate_json(json_str)


def _pandapipes_formula_qext_w(fluid, mdot_kg_s: float, t_from_k: float, t_outlet_k: float) -> float:
    """mdot * (cp(t_from)*t_from - cp(t_outlet)*t_outlet) -- pandapipes'
    OWN qext_w reporting-convention formula (module docstring, Finding 1).
    NOT a true enthalpy integral when cp varies with T. Used only to build
    PandapipesInternalEnergyConsistency, a diagnostic -- never the physical
    EnergyBalanceCheck."""
    cp_from = fluid.get_heat_capacity(t_from_k)
    cp_outlet = fluid.get_heat_capacity(t_outlet_k)
    return mdot_kg_s * (cp_from * t_from_k - cp_outlet * t_outlet_k)


def _integrate_specific_heat_j_per_kg(
    fluid, t_lower_k: float, t_upper_k: float, n_segments: int = ENTHALPY_INTEGRATION_SEGMENTS,
) -> float:
    """integral[t_lower_k, t_upper_k] cp(T) dT via composite trapezoidal
    rule, sampling only fluid.get_heat_capacity() (verified correct
    point-evaluation). This function does NOT call and never depends on
    pandapipes' own get_at_integral_value() helper -- see module docstring
    and docs/technical-observations/pandapipes-heat-capacity-integral-defect.md
    for why (a confirmed defect in the installed pandapipes version; this
    project's correctness does not hinge on that defect's presence or a
    future fix). Pure Python -- no NumPy/SciPy import.

    n_segments defaults to ENTHALPY_INTEGRATION_SEGMENTS (a named, audited
    constant, not a magic number) -- see
    test_baseline.py::test_integration_segment_count_converges_to_exact_integral
    for the 100-vs-200-segment convergence check against the hand-computed
    exact piecewise-linear integral.

    Requires t_lower_k <= t_upper_k; returns a non-negative magnitude.
    """
    if t_upper_k < t_lower_k:
        raise ValueError(f"t_upper_k ({t_upper_k}) must be >= t_lower_k ({t_lower_k})")
    if t_upper_k == t_lower_k:
        return 0.0
    step = (t_upper_k - t_lower_k) / n_segments
    total = 0.0
    cp_prev = fluid.get_heat_capacity(t_lower_k)
    t = t_lower_k
    for _ in range(n_segments):
        t += step
        cp_next = fluid.get_heat_capacity(t)
        total += (cp_prev + cp_next) / 2.0 * step
        cp_prev = cp_next
    return total


def _physical_enthalpy_delta_w(fluid, mdot_kg_s: float, t_hot_k: float, t_cold_k: float) -> float:
    """mdot * integral[t_cold_k, t_hot_k] cp(T) dT -- the TRUE sensible
    enthalpy magnitude of the fluid moving between t_hot_k and t_cold_k
    (order-independent; caller assigns the physical sign/meaning -- heat
    added by a pump, heat extracted by a consumer, heat lost by a pipe)."""
    lower, upper = (t_cold_k, t_hot_k) if t_hot_k >= t_cold_k else (t_hot_k, t_cold_k)
    return mdot_kg_s * _integrate_specific_heat_j_per_kg(fluid, lower, upper)


def run_baseline_evaluation(
    blueprint: NetworkBlueprint, *, tolerances: GateTolerances,
) -> BaselineBoundaryResult:
    """Build and solve `blueprint`, extract every KPI, apply gates 6-11
    (plan §11) in order. Never raises for any of the six recognized failure
    modes. Never mutates `blueprint` (frozen; build_pandapipes_net() only
    reads it)."""
    created_at = datetime.now(timezone.utc)
    net = build_pandapipes_net(blueprint)

    try:
        pandapipes.pipeflow(net, mode="sequential")
    except pandapipes.PipeflowNotConverged as exc:
        return BaselineNetworkFailure(
            failure_code=BaselineFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED,
            message=f"pandapipes pipeflow(mode='sequential') did not converge: {exc}",
            details={}, blueprint=blueprint, created_at=created_at,
        )

    if not bool(net.converged):
        # Defensive: verified unreachable in pandapipes 0.14.0 (every
        # non-convergent path raises PipeflowNotConverged before returning)
        # -- kept in case a future pandapipes version changes this.
        return BaselineNetworkFailure(
            failure_code=BaselineFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED,
            message="pipeflow returned without raising but net.converged is False.",
            details={}, blueprint=blueprint, created_at=created_at,
        )

    fluid = get_fluid(net)
    junction_idx = {name: idx for idx, name in enumerate(net.junction["name"])}
    pipe_idx = {name: idx for idx, name in enumerate(net.pipe["name"])}
    hc_idx = {name: idx for idx, name in enumerate(net.heat_consumer["name"])}

    # ── Per-consumer KPIs ──
    consumers: dict[str, ConsumerBaselineResult] = {}
    for consumer_id in blueprint.consumers:
        row = net.res_heat_consumer.iloc[hc_idx[consumer_id]]
        supply_temperature_c = row["t_from_k"] - 273.15
        consumers[consumer_id] = ConsumerBaselineResult(
            heat_delivered_kw=row["qext_w"] / 1000.0,
            supply_temperature_c=supply_temperature_c,
            return_temperature_c=row["t_outlet_k"] - 273.15,
            mass_flow_kg_s=abs(row["mdot_from_kg_per_s"]),
            supply_temperature_drop_k=blueprint.build_parameters.supply_temperature_c - supply_temperature_c,
        )

    for consumer_id, consumer_result in consumers.items():
        if consumer_result.supply_temperature_drop_k > tolerances.max_consumer_supply_drop_k:
            return BaselineNetworkFailure(
                failure_code=BaselineFailureCode.CONSUMER_TEMPERATURE_NOT_MET,
                message=(
                    f"consumers[{consumer_id!r}] supply_temperature_drop_k "
                    f"exceeds max_consumer_supply_drop_k."
                ),
                details={
                    "consumer_id": consumer_id,
                    "supply_temperature_drop_k": consumer_result.supply_temperature_drop_k,
                    "max_consumer_supply_drop_k": tolerances.max_consumer_supply_drop_k,
                },
                blueprint=blueprint, created_at=created_at,
            )

    # ── Pressure (absolute, via pressure.py exclusively) ──
    junction_pressures_bar_abs = {
        name: to_absolute_bar(net.res_junction.loc[idx, "p_bar"]) for name, idx in junction_idx.items()
    }
    min_pressure_bar_abs = min(junction_pressures_bar_abs.values())
    if min_pressure_bar_abs < tolerances.min_pressure_bar_abs:
        worst_junction = min(junction_pressures_bar_abs, key=junction_pressures_bar_abs.get)
        return BaselineNetworkFailure(
            failure_code=BaselineFailureCode.PRESSURE_LIMIT_EXCEEDED,
            message=f"junction {worst_junction!r} absolute pressure below min_pressure_bar_abs.",
            details={
                "junction": worst_junction, "pressure_bar_abs": min_pressure_bar_abs,
                "min_pressure_bar_abs": tolerances.min_pressure_bar_abs,
            },
            blueprint=blueprint, created_at=created_at,
        )

    # ── Velocity ──
    pipe_velocities_m_s = {
        name: abs(net.res_pipe.loc[idx, "v_mean_m_per_s"]) for name, idx in pipe_idx.items()
    }
    max_velocity_m_s = max(pipe_velocities_m_s.values())
    if max_velocity_m_s > tolerances.max_pipe_velocity_m_s:
        worst_pipe = max(pipe_velocities_m_s, key=pipe_velocities_m_s.get)
        return BaselineNetworkFailure(
            failure_code=BaselineFailureCode.VELOCITY_LIMIT_EXCEEDED,
            message=f"pipe {worst_pipe!r} velocity exceeds max_pipe_velocity_m_s.",
            details={
                "pipe": worst_pipe, "velocity_m_s": max_velocity_m_s,
                "max_pipe_velocity_m_s": tolerances.max_pipe_velocity_m_s,
            },
            blueprint=blueprint, created_at=created_at,
        )

    # ── Circulation pump ──
    pump_row = net.res_circ_pump_pressure.iloc[0]
    pump_mass_flow_kg_s = abs(pump_row["mdot_from_kg_per_s"])
    pressure_lift_bar = pump_row["p_to_bar"] - pump_row["p_from_bar"]
    hydraulic_pumping_power_kw = (pressure_lift_bar * 1e5 * pump_row["vdot_m3_per_s"]) / 1000.0
    circulation_pump = CirculationPumpResult(
        mass_flow_kg_s=pump_mass_flow_kg_s, pressure_lift_bar=pressure_lift_bar,
        flow_temperature_c=pump_row["t_outlet_k"] - 273.15, return_temperature_c=pump_row["t_from_k"] - 273.15,
        hydraulic_pumping_power_kw=hydraulic_pumping_power_kw,
    )

    # ── Mass balance: pump branch flow vs. sum of consumer branch flows ──
    total_consumer_mass_flow_kg_s = sum(c.mass_flow_kg_s for c in consumers.values())
    mass_residual_fraction = abs(pump_mass_flow_kg_s - total_consumer_mass_flow_kg_s) / pump_mass_flow_kg_s
    mass_balance = MassBalanceCheck(
        pump_mass_flow_kg_s=pump_mass_flow_kg_s, total_consumer_mass_flow_kg_s=total_consumer_mass_flow_kg_s,
        residual_fraction=mass_residual_fraction, tolerance_fraction=tolerances.mass_balance_tolerance_fraction,
        passed=mass_residual_fraction <= tolerances.mass_balance_tolerance_fraction,
    )
    if not mass_balance.passed:
        return BaselineNetworkFailure(
            failure_code=BaselineFailureCode.MASS_BALANCE_FAILED,
            message="pump-vs-consumer mass-flow residual exceeds mass_balance_tolerance_fraction.",
            details={
                "residual_fraction": mass_residual_fraction,
                "tolerance_fraction": tolerances.mass_balance_tolerance_fraction,
            },
            blueprint=blueprint, created_at=created_at,
        )

    total_heat_delivered_kw = sum(c.heat_delivered_kw for c in consumers.values())
    min_consumer_supply_temperature_c = min(c.supply_temperature_c for c in consumers.values())
    mean_consumer_return_temperature_c = sum(c.return_temperature_c for c in consumers.values()) / len(consumers)

    # ── PandapipesInternalEnergyConsistency: solver diagnostic only, using
    # pandapipes' OWN reporting-convention formula on both sides (module
    # docstring, Finding 1) -- NOT the physical balance, NOT gated. ──
    pump_reported_qext_kw = pump_row["qext_w"] / 1000.0
    consumer_recomputed_qext_w = sum(
        _pandapipes_formula_qext_w(
            fluid, net.res_heat_consumer.iloc[hc_idx[cid]]["mdot_from_kg_per_s"],
            net.res_heat_consumer.iloc[hc_idx[cid]]["t_from_k"], net.res_heat_consumer.iloc[hc_idx[cid]]["t_outlet_k"],
        )
        for cid in blueprint.consumers
    )
    consumer_recomputed_qext_kw = consumer_recomputed_qext_w / 1000.0
    pic_residual_fraction = abs(pump_reported_qext_kw - consumer_recomputed_qext_kw) / pump_reported_qext_kw
    reporting_convention_difference_fraction = (
        abs(pump_reported_qext_kw - total_heat_delivered_kw) / total_heat_delivered_kw
    )
    pandapipes_internal_energy_consistency = PandapipesInternalEnergyConsistency(
        pump_reported_qext_kw=pump_reported_qext_kw, consumer_recomputed_qext_kw=consumer_recomputed_qext_kw,
        consumer_demand_total_kw=total_heat_delivered_kw, residual_fraction=pic_residual_fraction,
        reporting_convention_difference_fraction=reporting_convention_difference_fraction,
    )

    # ── EnergyBalanceCheck: the PHYSICAL balance -- true integral cp(T) dT
    # (module docstring, Finding 2), what the 2% gate actually applies to. ──
    pump_physical_w = _physical_enthalpy_delta_w(fluid, pump_mass_flow_kg_s, pump_row["t_outlet_k"], pump_row["t_from_k"])
    consumer_physical_w = sum(
        _physical_enthalpy_delta_w(
            fluid, net.res_heat_consumer.iloc[hc_idx[cid]]["mdot_from_kg_per_s"],
            net.res_heat_consumer.iloc[hc_idx[cid]]["t_from_k"], net.res_heat_consumer.iloc[hc_idx[cid]]["t_outlet_k"],
        )
        for cid in blueprint.consumers
    )
    pipe_physical_loss_w = sum(
        _physical_enthalpy_delta_w(
            fluid, net.res_pipe.iloc[pipe_idx[pid]]["mdot_from_kg_per_s"],
            net.res_pipe.iloc[pipe_idx[pid]]["t_from_k"], net.res_pipe.iloc[pipe_idx[pid]]["t_outlet_k"],
        )
        for pid in blueprint.pipes
    )
    pump_physical_enthalpy_kw = pump_physical_w / 1000.0
    consumer_physical_enthalpy_kw = consumer_physical_w / 1000.0
    pipe_physical_heat_loss_kw = pipe_physical_loss_w / 1000.0

    physical_energy_residual_fraction = (
        abs(pump_physical_enthalpy_kw - (consumer_physical_enthalpy_kw + pipe_physical_heat_loss_kw))
        / pump_physical_enthalpy_kw
    )
    energy_balance = EnergyBalanceCheck(
        pump_physical_enthalpy_kw=pump_physical_enthalpy_kw, consumer_physical_enthalpy_kw=consumer_physical_enthalpy_kw,
        pipe_physical_heat_loss_kw=pipe_physical_heat_loss_kw,
        integration_method=ENTHALPY_INTEGRATION_METHOD, integration_segments=ENTHALPY_INTEGRATION_SEGMENTS,
        residual_fraction=physical_energy_residual_fraction,
        tolerance_fraction=tolerances.energy_balance_tolerance_fraction,
        passed=physical_energy_residual_fraction <= tolerances.energy_balance_tolerance_fraction,
    )
    if not energy_balance.passed:
        return BaselineNetworkFailure(
            failure_code=BaselineFailureCode.ENERGY_BALANCE_FAILED,
            message="physical pump-vs-consumer enthalpy-balance residual exceeds energy_balance_tolerance_fraction.",
            details={
                "residual_fraction": physical_energy_residual_fraction,
                "tolerance_fraction": tolerances.energy_balance_tolerance_fraction,
                "pump_physical_enthalpy_kw": pump_physical_enthalpy_kw,
                "consumer_physical_enthalpy_kw": consumer_physical_enthalpy_kw,
                "pipe_physical_heat_loss_kw": pipe_physical_heat_loss_kw,
            },
            blueprint=blueprint, created_at=created_at,
        )

    return BaselineNetworkResult(
        blueprint=blueprint, tolerances=tolerances,
        consumers=consumers, total_heat_delivered_kw=total_heat_delivered_kw,
        min_consumer_supply_temperature_c=min_consumer_supply_temperature_c,
        mean_consumer_return_temperature_c=mean_consumer_return_temperature_c,
        junction_pressures_bar_abs=junction_pressures_bar_abs, min_pressure_bar_abs=min_pressure_bar_abs,
        pipe_velocities_m_s=pipe_velocities_m_s, max_velocity_m_s=max_velocity_m_s,
        mass_balance=mass_balance, energy_balance=energy_balance,
        pandapipes_internal_energy_consistency=pandapipes_internal_energy_consistency,
        circulation_pump=circulation_pump,
        warnings=[], created_at=created_at,
    )
