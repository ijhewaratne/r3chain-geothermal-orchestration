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
