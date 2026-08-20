"""Typed failure codes for the PyDoublet-to-DH heat-exchanger adapter (T2.1).

Reuses the exact stable failure-code vocabulary from the implementation
plan's §8.4 candidate-result failure-code list -- traceable to the approved
plan text, not invented. This is a deliberately separate namespace from
r3chain_geothermal.errors.FailureCode (T1.5B's PyDoublet-parsing failures):
CLAUDE.md requires PyDoublet, the adapter, pandapipes evaluation, economics,
MCP wrappers and presentation to remain separate layers, and that separation
extends to each layer's own failure vocabulary.

Only three of the plan's candidate-result codes apply at this boundary:
- MISSING_COUPLING_FIELD is not implemented here -- T1.5B's model-level
  invariants already make "a required field is missing from a valid
  PyDoubletCouplingResult" an unreachable state by the time it reaches the
  adapter.
- GEOTHERMAL_CAPACITY_SHORTFALL and the auxiliary/curtailment policy (plan
  §9.5) require a specific candidate's DH demand, which does not exist until
  the network/candidate layer (Phase 4) -- deferred, not implemented here.
- Gate items 5-11 of plan §11 (pandapipes convergence, pressure, velocity,
  mass/energy balance) belong to the candidate evaluator, not this adapter.
"""
from __future__ import annotations

from enum import Enum


class AdapterFailureCode(str, Enum):
    """Stable, machine-readable failure codes for a rejected heat-exchanger
    coupling evaluation."""

    UNIT_OR_SIGN_ERROR = "UNIT_OR_SIGN_ERROR"
    """The independently recomputed raw energy balance
    (m_dot_brine * cp_brine * (T_prod - T_brine_outlet)) disagrees with the
    upstream PyDoubletCouplingResult's raw_geothermal_thermal_power_kw
    beyond the configured tolerance -- usually indicates a unit, field or
    sign error somewhere upstream (plan §9.2)."""

    HX_SUPPLY_TEMPERATURE_INFEASIBLE = "HX_SUPPLY_TEMPERATURE_INFEASIBLE"
    """producer_wellhead_temperature_c < dh_supply_temperature_c +
    minimum_hx_approach_k -- the hot end of the heat exchanger cannot meet
    the DH supply temperature at all (plan §9.3, §11 gate 3)."""

    HX_COLD_END_APPROACH_INFEASIBLE = "HX_COLD_END_APPROACH_INFEASIBLE"
    """producer_wellhead_temperature_c <= allowable_brine_outlet_temperature_c
    -- no positive temperature difference remains once the brine is cooled
    to the allowable outlet, so zero or negative heat could be extracted
    (plan §9.3, §11 gate 4)."""


RAW_POWER_CEILING_BINDING = "RAW_POWER_CEILING_BINDING"
"""Warning code for a successful evaluation where deliverable heat is capped
by the PyDoublet-reported raw geothermal power rather than by the DH-side
temperature limit -- a noteworthy, non-default case, not a failure."""
