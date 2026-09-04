"""Typed failure codes for the T2.2B baseline network evaluator.

Reuses the implementation plan's own §8.4 candidate-result failure-code
vocabulary, gates 6-11 of plan §11 order only (items 1-5 -- PyDoublet
convergence, unit/sign+energy consistency, HX hot/cold-end, geothermal
capacity -- belong to T1.5B, T2.1, and the not-yet-built candidate-
evaluation layer respectively; none of those apply to a geothermal-free
baseline).
"""
from __future__ import annotations

from enum import Enum


class BaselineFailureCode(str, Enum):
    """Stable, machine-readable failure codes for a rejected baseline
    network evaluation."""

    THERMAL_PIPEFLOW_NOT_CONVERGED = "THERMAL_PIPEFLOW_NOT_CONVERGED"
    """pandapipes raised PipeflowNotConverged during mode="sequential"
    solving (plan §11 gate 6)."""

    CONSUMER_TEMPERATURE_NOT_MET = "CONSUMER_TEMPERATURE_NOT_MET"
    """A consumer's supply-side temperature dropped below
    build_parameters.supply_temperature_c by more than
    gates.max_consumer_supply_drop_k (plan §11 gate 7)."""

    PRESSURE_LIMIT_EXCEEDED = "PRESSURE_LIMIT_EXCEEDED"
    """A junction's absolute pressure (network/pressure.py::to_absolute_bar)
    fell below gates.min_pressure_bar_abs (plan §11 gate 8)."""

    VELOCITY_LIMIT_EXCEEDED = "VELOCITY_LIMIT_EXCEEDED"
    """A pipe's mean velocity exceeded gates.max_pipe_velocity_m_s
    (plan §11 gate 9)."""

    MASS_BALANCE_FAILED = "MASS_BALANCE_FAILED"
    """The pump-vs-consumer mass-flow residual exceeded
    gates.mass_balance_tolerance_fraction (plan §11 gate 10)."""

    ENERGY_BALANCE_FAILED = "ENERGY_BALANCE_FAILED"
    """The pump-enthalpy-vs-consumer-enthalpy residual (both sides computed
    via the SAME temperature-dependent-cp formula -- see baseline.py's
    module docstring for why a naive comparison is wrong) exceeded
    gates.energy_balance_tolerance_fraction (plan §11 gate 11)."""

    PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED = "PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED"
    """The main plant circulation pump's measured pressure lift
    (CirculationPumpResult.pressure_lift_bar) exceeded
    gates.max_pump_dp_bar (CFG-003/CFG-004 gate 11,
    R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Workstream D). Prior to
    this code's addition, max_pump_dp_bar was declared in configuration but
    never enforced by any gate -- see docs/decisions/decision-register.md
    IMPL-007."""


class CandidateFailureCode(str, Enum):
    """Stable, machine-readable failure codes for a rejected T2.3 candidate
    evaluation. Reuses BaselineFailureCode's six codes verbatim (redeclared
    here rather than inherited -- Python's str-Enum does not support
    extending an existing Enum's members) plus one candidate-specific code
    for the geothermal injection branch's own hydraulic boundary. Economic
    infeasibility has no code here -- T2.3 is technical-gates only (plan
    §11 items 6-11); ranking/economics are a later, separately-approved
    task."""

    THERMAL_PIPEFLOW_NOT_CONVERGED = "THERMAL_PIPEFLOW_NOT_CONVERGED"
    """pandapipes raised PipeflowNotConverged (hydraulics or heat-transfer
    stage) during mode="sequential" solving on the candidate net (plan §11
    gate 6). Same meaning as BaselineFailureCode's code of the same name."""

    CONSUMER_TEMPERATURE_NOT_MET = "CONSUMER_TEMPERATURE_NOT_MET"
    """A consumer's supply-side temperature dropped below
    build_parameters.supply_temperature_c by more than
    gates.max_consumer_supply_drop_k (plan §11 gate 7)."""

    PRESSURE_LIMIT_EXCEEDED = "PRESSURE_LIMIT_EXCEEDED"
    """A junction's absolute pressure (network/pressure.py::to_absolute_bar),
    across every junction in the candidate net INCLUDING the three new
    geothermal-injection junctions, fell below gates.min_pressure_bar_abs
    (plan §11 gate 8)."""

    VELOCITY_LIMIT_EXCEEDED = "VELOCITY_LIMIT_EXCEEDED"
    """A pipe's mean velocity, across every pipe in the candidate net
    INCLUDING the two new connection pipes, exceeded
    gates.max_pipe_velocity_m_s (plan §11 gate 9)."""

    MASS_BALANCE_FAILED = "MASS_BALANCE_FAILED"
    """The combined (main plant pump + geothermal injection) supply-side
    mass flow vs. total consumer mass-flow residual exceeded
    gates.mass_balance_tolerance_fraction (plan §11 gate 10)."""

    ENERGY_BALANCE_FAILED = "ENERGY_BALANCE_FAILED"
    """The combined (main plant pump + geothermal injection) physical
    enthalpy vs. consumer-plus-pipe-loss physical enthalpy residual
    exceeded gates.energy_balance_tolerance_fraction (plan §11 gate 11)."""

    GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT = "GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT"
    """pandapipes raised UserWarning during pipeflow() -- distinct from
    PipeflowNotConverged -- most commonly
    CirculationPump.extract_results()'s hard-coded, near-zero-tolerance
    direction-change check on the MAIN plant pump firing because this
    candidate's geothermal injection left the main pump's own net mass
    flow numerically negative. T2.3's curtailment policy
    (network/candidate.py, GeothermalInjectionPolicy.minimum_auxiliary_circulation_fraction)
    is specifically designed to keep this unreached in the worked case;
    this code exists so an unanticipated combination fails loudly with an
    exact, documented cause instead of an unhandled exception."""

    PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED = "PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED"
    """Either the main plant circulation pump's or the geothermal injection
    pump's measured pressure lift exceeded gates.max_pump_dp_bar
    (CFG-003/CFG-004 gate 11). Same meaning as BaselineFailureCode's code
    of the same name, extended to also cover the injection branch's own
    pump -- see docs/decisions/decision-register.md IMPL-007."""

    GEOTHERMAL_HEAT_SHORTFALL = "GEOTHERMAL_HEAT_SHORTFALL"
    """Under injection_policy.auxiliary_policy == "strict_infeasible" only:
    coupling_input.deliverable_geothermal_heat_kw fell short of
    baseline.total_heat_delivered_kw by more than
    gates.heat_delivery_tolerance_fraction (DSP-003,
    R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Workstream E). Never
    raised under the default "cost_shortfall" policy, which instead covers
    any shortfall from the auxiliary source (auxiliary_heat_kw) -- see
    GeothermalInjectionPolicy's own docstring."""

    SELF_CONSISTENT_FLOW_NOT_CONVERGED = "SELF_CONSISTENT_FLOW_NOT_CONVERGED"
    """Under injection_policy.injection_sizing_policy == "self_consistent"
    only (DSP-005): the bounded fixed-point iteration that resizes the
    injection branch's mass flow against its own SOLVED (not design)
    return temperature did not meet both the outlet-temperature and
    mass-flow residual tolerances within
    SELF_CONSISTENT_FLOW_MAX_ITERATIONS pipeflow() solves. Distinct from
    THERMAL_PIPEFLOW_NOT_CONVERGED (which is pandapipes itself failing to
    solve one candidate iteration -- still raised, unchanged, if any single
    iteration's own pipeflow() call fails). Never raised under the default
    "fixed_design_temperature" policy, which performs exactly one solve."""

    CONNECTION_DESIGN_INVALID = "CONNECTION_DESIGN_INVALID"
    """DESIGN-004/006, R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    Phase 3: `evaluate_candidate()`'s own `connection_pipe_inner_diameter_mm`
    keyword argument was not a positive number -- checked BEFORE any
    network construction is attempted. Defensive: every existing caller
    (the canonical single-scenario workflow, the v1 joint module) always
    passes the fixed positive `CONNECTION_PIPE_DN_MM` default, and
    `data_contracts.joint_study.ConnectionDesignOption`'s own contract
    validator already rejects a non-positive diameter before it can ever
    reach this function through the Phase-2/3 joint evaluation path --
    this code exists so a direct, unvalidated caller still fails loudly
    with an exact cause rather than an unhandled pandapipes exception
    deep inside pipe construction."""
