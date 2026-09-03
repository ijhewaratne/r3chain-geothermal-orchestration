"""Independent geothermal candidate evaluator (T2.3): injects the T2.1
heat-exchanger coupling result's deliverable geothermal heat into ONE
candidate's supply/return junction pair, on a FRESH copy of the T2.2
network, and evaluates it against the same plan-§11 gates 6-11 the T2.2B
baseline evaluator applies -- now on a larger net that also carries the
geothermal injection branch and (unlike the baseline) two heat sources.

This module answers ONE question per call: "if the surface heat exchanger
delivers Q_direct kW at candidate N's junction pair, does the resulting
network still converge, deliver consumer demand, and stay inside every
technical gate?" It does **not** rank candidates, compute economics, or
claim a drilling-site recommendation -- see the module's own scope-boundary
test (test_candidate.py) and CLAUDE.md.

## Topology (investigation evidence, not assumption)

Read `pandapipes/create.py` (0.14.0, `.venvs/orchestration`) and ran
controlled probes against both an isolated loop and the real T2.2A/T2.2B
default blueprint network before selecting this topology. Three findings:

**Finding A -- circulation pumps are absolute pressure references, and a
network can only carry one per connected hydraulic zone.** Both
`create_circ_pump_const_pressure` and `create_circ_pump_const_mass_flow`
"set the pressure at [their] outlet (flow junction)" (docstring, verbatim)
-- the same role an `ext_grid` plays. Confirmed empirically three ways
(all `PipeflowNotConverged`, `MatrixRankWarning: Matrix is exactly
singular`): (1) `create_circ_pump_const_mass_flow` as the sole boundary of
an isolated loop fails at every tested mass flow, while
`create_circ_pump_const_pressure` in the same loop converges; (2) either
circ_pump variant embedded alongside the baseline's own already-fixed
plant pump fails at every tested mass flow; (3) the same embedding with
`p_flow_bar` set to the *exact* baseline-solved pressure at that junction
still fails -- ruling out "wrong numeric guess," confirming this is
structural. This also explains why pandapipesAI's own `tb_add_heat_source`
(`create_circ_pump_const_pressure`, already flagged in T2.2A as an
"effectively unlimited pump" anti-pattern) is doubly unsuitable here.

**Finding B -- `create_pump`/`create_pump_from_parameters` is a *relative*
pressure-lift-vs-flow device, not an absolute reference, and does not
conflict.** Its docstring describes a characteristic curve relating
pressure lift to flow rate -- a differential, not a fixed absolute node
pressure. Empirically: `create_pump_from_parameters` (flat lift curve)
embedded alongside the baseline's existing plant pump converges, including
at realistic full scale (~25 kg/s injected).

**Finding C -- `create_heat_consumer` (not `create_heat_exchanger`) is the
injection element.** Both document the identical convention: negative
`qext_w` means heat is fed INTO the network. `create_heat_exchanger` only
takes `qext_w` (no mass-flow control), so capacity-capping it needs a
separate `create_flow_control` in series -- pandapipesAI's own test suite
already shows that combination is equivalent to `create_heat_consumer`'s
combined `qext_w` + `controlled_mdot_kg_per_s` form for the positive/
consuming case. `create_heat_consumer` gives the same physics in one
component; verified directly (not just by the consuming-case equivalence)
at full realistic scale.

**Selected topology, per candidate N** (`_add_geothermal_injection_branch`
below):

```
candidate.return_junction --return_connection_pipe(len, DN)--> geo_return_N
geo_return_N --create_pump_from_parameters(flat lift curve)--> geo_mid_N
geo_mid_N --create_heat_consumer(qext_w<0, controlled_mdot)--> geo_supply_N
geo_supply_N --supply_connection_pipe(len, DN)--> candidate.supply_junction
```

Both connection pipes reuse `candidate.surface_connection_length_m` (T2.2A's
own mirrored-length convention -- no new geometry decision). The lift
curve reuses `blueprint.circulation_pump.pressure_lift_bar` (3.0 bar,
already an approved config value) rather than inventing a new one --
empirically verified (all four real candidates, near-full-scale injected
flow) to keep the injection branch's flow direction correctly supply-ward
with comfortable margin. `CONNECTION_PIPE_DN_MM` (200.0 mm, matching the
already-approved trunk DN) was sized the same way T2.2A sized the trunk:
empirically verified to keep connection-pipe velocity comfortably under
`gates.max_pipe_velocity_m_s` at the worked case's near-full injected flow
(~0.82 m/s, ~55% of the 1.5 m/s gate) -- DN100/DN150 were tried first and
rejected (3.2 m/s and 1.44 m/s respectively, the latter only ~4% below the
gate, an uncomfortably tight margin matching the exact problem T2.2A's own
trunk-pipe sizing note already describes and corrected once for the trunk).

## Curtailment -- two distinct floors, not one (implementation-phase
finding, explicit user decision)

The worked case is a genuine *surplus*: `deliverable_geothermal_heat_kw`
(~3227.7 kW) exceeds the baseline's total consumer demand (3200.0 kW).
Curtailing supply-side surplus down to exactly 100% of demand was the
plan's original design -- but pandapipes 0.14.0's
`CirculationPump.extract_results()` contains a hard-coded, near-zero-
tolerance check (`numpy.isclose(mdot, 0)`, default `atol=1e-8`) that
raises `UserWarning` on the *converged* solution whenever the MAIN plant
pump's own net mass flow would go numerically negative. Empirically,
curtailing to exactly 100% of demand lands in that failing band for every
candidate (verified: converges cleanly through 99.8% coverage with a
small positive residual main-pump flow; fails from 99.9% up). There is no
bypass option in `pipeflow()`'s kwargs and no supported way to relax this
pandapipes-internal check. An alternative -- dropping the main plant pump
entirely once geothermal fully covers demand, replacing it with a bare
`ext_grid` -- was directly tested and fails at the heat-transfer stage (a
bare `ext_grid` does not propagate a thermal boundary condition to the
abandoned return-side junction; fixing that would be a separate,
open-ended investigation).

**Decision (explicit user approval):** `coupling_assumptions.minimum_auxiliary_circulation_fraction`
(0.01, one new config value) caps maximum curtailment at 99% of baseline
demand, keeping the main plant pump's residual flow safely clear of
pandapipes' ~1e-8 kg/s tolerance (empirically ~0.22 kg/s margin at 99%
coverage). `_compute_injected_heat_kw` folds BOTH floors (the true supply/
demand surplus and this solver-stability margin) into one
`geothermal_curtailed_heat_kw` figure -- reported explicitly, never
silently dropped, with this module docstring and the config value's own
note making clear which part of any given curtailment is physical surplus
versus numerical margin. Whenever the margin (not the true deliverable
value) is what limited injection, `PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED`
is appended to the result's `warnings` -- see
`_compute_injected_heat_kw`'s own `stabilization_margin_applied` return
value.

**A second, independently-discovered reason reinforces the same 1%
choice** (found during T2.3's own sensitivity testing, not anticipated
when 0.01 was first chosen): sweeping the fraction below 1% triggers a
*different* failure -- `CONSUMER_TEMPERATURE_NOT_MET` at `consumer_1`,
for all four candidates, with identical magnitudes per fraction (0.003 ->
19.54 K drop, 0.005 -> 9.27 K, 0.0075 -> 5.58 K, all exceeding
`gates.max_consumer_supply_drop_k`=5.0 K; 0.01 passes with a thin
~0.8-1.0 K margin). Root cause, traced directly: as the fraction shrinks,
the main pump's own share of network flow shrinks toward zero, so the
network's thermal field is increasingly dominated by the injection
branch's own achieved outlet temperature -- which undershoots the design
70 degC supply temperature because `_compute_injected_mass_flow_kg_s`
assumes a fixed rise from the *design* return temperature (40 degC)
rather than the network's actual solved return temperature (verified:
`ret_trunk_1` solves to 36.00 degC, not 40.00 degC, at the chosen 1%
margin). Full evidence, the measured boundary table, and a future
self-consistent-sizing investigation path are in
`docs/technical-observations/pandapipes-circulation-pump-direction-check.md`.

## Scope boundary (T2.3)

No economic calculation, no ranking, no MCP tools, no maps, no
`repos/pandapipesAI` modifications, and no claim about drilling location --
this evaluates network CONNECTION location only (plan, "Executive
decision"). Enforced by a grep-based structural test
(test_candidate.py::test_no_economics_ranking_or_mcp_identifiers_in_module),
mirroring T2.2B's `to_absolute_bar()`-only-discipline test pattern.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

import pandapipes
from pandapipes.properties.fluids import get_fluid
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..adapter.heat_exchanger import HeatExchangerCouplingResult
from ..contracts import CouplingWarning
from .baseline import (
    ENTHALPY_INTEGRATION_METHOD,
    ENTHALPY_INTEGRATION_SEGMENTS,
    BaselineNetworkResult,
    CirculationPumpResult,
    ConsumerBaselineResult,
    EnergyBalanceCheck,
    GateTolerances,
    MassBalanceCheck,
    _physical_enthalpy_delta_w,
)
from .blueprint import BlueprintCandidate, NetworkBlueprint
from .builder import build_pandapipes_net
from .errors import CandidateFailureCode
from .pressure import to_absolute_bar

CANDIDATE_CONTRACT_SCHEMA_VERSION: Literal["1.1.0"] = "1.1.0"
"""Versioned independently of every other layer's own contract schema.
Bumped 1.0.0 -> 1.1.0 (Workstream D/E,
R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md, decision-register.md
IMPL-007): GeothermalInjectionPolicy now accepts and enforces
"strict_infeasible" (previously rejected), gaining a
heat_delivery_tolerance_fraction field; GateTolerances (network/baseline.py)
gained max_pump_dp_bar, now enforced against both the main plant pump and
the geothermal injection pump here. Both are previously-declared-but-
unenforced configuration fields (CFG-003) -- see that module's own
docstring for the same note. Changes bundle_scientific_sha256 for any
bundle embedding CandidateEvaluationResult (new fields in the audited
schema) but not run_id, and not any C1-C4 canonical numeric KPI,
feasibility, or candidate-ordering value under the canonical
"cost_shortfall" policy and 3.0 bar canonical pump lift (CFG-006)."""

CONNECTION_PIPE_DN_MM = 200.0
"""Empirically sized (module docstring, "Selected topology") to keep both
geothermal connection pipes' velocity comfortably under
gates.max_pipe_velocity_m_s at the worked case's near-full-scale injected
flow. Fixed across all four candidates (plan §10.1's "fixed pipe diameters
across candidate evaluations"), matching the already-approved trunk DN."""


# ── Pure computation helpers -- the single source of truth, recomputed by
# CandidateEvaluationResult's own model-level invariant so a hand-tampered
# payload can never silently diverge from a genuine evaluation. ──

PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED = "PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED"
"""Warning code, appended to a successful result's `warnings` whenever
`_compute_injected_heat_kw`'s solver-stability ceiling -- not the true
deliverable-heat ceiling -- is what limited the injected amount (module
docstring, "Curtailment"). Distinguishes "we curtailed because geothermal
physically exceeded demand" from "we ALSO held back part of that surplus
purely to keep pandapipes' main-pump direction-change check from firing" --
the second is a numerical-stability artifact of this solver, not a fact
about physical supply or demand, and must never be silently folded into
`geothermal_curtailed_heat_kw` without a visible marker."""


def _compute_injected_heat_kw(
    deliverable_geothermal_heat_kw: float,
    baseline_total_heat_delivered_kw: float,
    minimum_auxiliary_circulation_fraction: float,
) -> tuple[float, float, bool]:
    """Returns (injected_kw, curtailed_kw, stabilization_margin_applied).
    injected_kw = min(deliverable, demand * (1 - minimum_auxiliary_circulation_fraction))
    -- folding BOTH a true supply/demand surplus AND the solver-stability
    margin (module docstring, "Curtailment") into one curtailed_kw figure.
    Never negative.

    stabilization_margin_applied is True exactly when there IS a genuine
    surplus (deliverable >= demand) AND the fraction's own ceiling -- not
    the deliverable value itself -- is what capped injected_kw below
    baseline_total_heat_delivered_kw. False for a shortfall (no surplus to
    curtail at all) and False whenever minimum_auxiliary_circulation_fraction
    is exactly 0.0 (no margin to apply)."""
    max_injectable_kw = baseline_total_heat_delivered_kw * (1.0 - minimum_auxiliary_circulation_fraction)
    injected_kw = min(deliverable_geothermal_heat_kw, max_injectable_kw)
    curtailed_kw = max(0.0, deliverable_geothermal_heat_kw - injected_kw)
    is_surplus_case = deliverable_geothermal_heat_kw >= baseline_total_heat_delivered_kw
    stabilization_margin_applied = (
        is_surplus_case
        and minimum_auxiliary_circulation_fraction > 0.0
        and injected_kw < baseline_total_heat_delivered_kw
    )
    return injected_kw, curtailed_kw, stabilization_margin_applied


def _compute_injected_mass_flow_kg_s(
    injected_kw: float,
    dh_supply_temperature_c: float,
    dh_return_temperature_c: float,
    dh_water_specific_heat_capacity_j_kg_k: float,
) -> float:
    """m = Q / (cp * dT) -- the same formula shape as
    adapter/heat_exchanger.py's private _compute_dh_mass_flow, independently
    reimplemented here (not imported: that function computes T2.1's
    UNCURTAILED district_heating_water_mass_flow_kg_s, a different physical
    quantity from this module's CURTAILED injected mass flow). Never reads
    coupling_input.geothermal_brine_mass_flow_kg_s -- brine and DH-water
    flow stay separate (CLAUDE.md)."""
    cp_kj_per_kg_k = dh_water_specific_heat_capacity_j_kg_k / 1000.0
    delta_t = dh_supply_temperature_c - dh_return_temperature_c
    return injected_kw / (cp_kj_per_kg_k * delta_t)


class GeothermalInjectionPolicy(BaseModel):
    """The subset of config/demo_assumptions.json::coupling_assumptions
    this evaluator consumes for curtailment/auxiliary policy. Named
    separately from adapter.CouplingAssumptions (T2.1's own, distinct
    concept) and from network.baseline.GateTolerances."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    curtailment_allowed: bool
    auxiliary_policy: Literal["cost_shortfall", "strict_infeasible"]
    """DSP-001's typed shortfall-policy enum, under this project's existing
    config vocabulary (decision-register.md IMPL-007 records the
    correspondence to the spec's own "auxiliary_supply"/"strict_infeasible"
    naming: this project's pre-existing "cost_shortfall" IS
    "auxiliary_supply" -- same policy, kept under its established name
    rather than renamed, since renaming config/demo_assumptions.json's
    literal value would change config_sha256/run_id for zero functional
    gain, and config/demo_assumptions.json's own
    coupling_assumptions.auxiliary_policy_options already lists both
    values). "strict_infeasible" (DSP-003) is now implemented: see
    heat_delivery_tolerance_fraction below and
    CandidateFailureCode.GEOTHERMAL_HEAT_SHORTFALL."""
    minimum_auxiliary_circulation_fraction: float
    heat_delivery_tolerance_fraction: float
    """gates.heat_delivery_tolerance_fraction (CFG-003/DSP-003, added
    schema 1.1.0). Previously declared in config but never consumed by any
    check -- see decision-register.md IMPL-007. Consumed ONLY under
    auxiliary_policy=="strict_infeasible": a candidate is infeasible
    (GEOTHERMAL_HEAT_SHORTFALL) when
    coupling_input.deliverable_geothermal_heat_kw falls short of
    baseline_total_heat_delivered_kw by more than this fraction. Never
    consulted under "cost_shortfall" (DSP-004: a genuine resource shortfall
    there is simply covered by auxiliary_heat_kw, not gated)."""

    @model_validator(mode="after")
    def _validate_policy(self) -> "GeothermalInjectionPolicy":
        errors: list[str] = []
        if not self.curtailment_allowed:
            errors.append(
                "curtailment_allowed=False is not implemented by this evaluator "
                "(T2.3 scope: surplus curtailment always applies when the "
                "deliverable heat exceeds the curtailment ceiling) -- changing "
                "this is a scientific-assumption change requiring separate approval"
            )
        if not (0.0 <= self.minimum_auxiliary_circulation_fraction < 1.0):
            errors.append(
                "minimum_auxiliary_circulation_fraction must be in [0, 1), got "
                f"{self.minimum_auxiliary_circulation_fraction!r}"
            )
        if not (0.0 <= self.heat_delivery_tolerance_fraction < 1.0):
            errors.append(
                "heat_delivery_tolerance_fraction must be in [0, 1), got "
                f"{self.heat_delivery_tolerance_fraction!r}"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @classmethod
    def from_config_dict(cls, config: dict[str, Any]) -> "GeothermalInjectionPolicy":
        """Pure function -- no file I/O, mirrors GateTolerances/
        CouplingAssumptions' established pattern."""
        coupling = config["coupling_assumptions"]
        gates = config["gates"]
        return cls(
            curtailment_allowed=coupling["curtailment_allowed"],
            auxiliary_policy=coupling["auxiliary_policy"],
            minimum_auxiliary_circulation_fraction=coupling["minimum_auxiliary_circulation_fraction"],
            heat_delivery_tolerance_fraction=gates["heat_delivery_tolerance_fraction"],
        )


class CandidateKpiDeltas(BaseModel):
    """Baseline-vs-candidate KPI deltas (candidate minus baseline)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    total_heat_delivered_delta_kw: float
    main_pump_mass_flow_delta_kg_s: float
    main_pump_hydraulic_power_delta_kw: float
    """HYDRAULIC power delta only -- see CirculationPumpResult's own
    documented reason for having no electrical_pump_power_kw field (no
    pump-efficiency assumption exists in config); this delta must not be
    read as an electrical-power figure."""
    min_pressure_delta_bar_abs: float
    max_velocity_delta_m_s: float


class CandidateEvaluationResult(BaseModel):
    """A successful candidate evaluation. Model-level invariants recompute
    every summary figure from its own stored detail fields (mirroring
    BaselineNetworkResult's rigor) AND cross-check the curtailment/mass-flow
    physics chain via the same pure helpers evaluate_candidate() itself
    uses -- a hand-tampered payload is rejected, not silently accepted."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.1.0"] = CANDIDATE_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    candidate: BlueprintCandidate
    coupling_input: HeatExchangerCouplingResult
    """The complete upstream T2.1 result, embedded verbatim -- includes
    coupling_input.coupling_input.doublet_pump_electric_power_kw (T1.5B's
    field), also surfaced as its own top-level KPI below per explicit
    instruction: preserved unchanged, never recomputed, never mixed with
    DH-pump electricity."""
    injection_policy: GeothermalInjectionPolicy
    tolerances: GateTolerances

    consumers: dict[str, ConsumerBaselineResult]
    """The four ORIGINAL blueprint demand-side consumers only -- the
    geothermal injection's own heat_consumer is a SOURCE, never mixed in
    here."""
    total_heat_delivered_kw: float
    min_consumer_supply_temperature_c: float
    mean_consumer_return_temperature_c: float

    junction_pressures_bar_abs: dict[str, float]
    """Every junction in the candidate net, INCLUDING the three new
    geothermal-injection junctions (geo_return_N/geo_mid_N/geo_supply_N)."""
    min_pressure_bar_abs: float

    pipe_velocities_m_s: dict[str, float]
    """Every pipe in the candidate net, INCLUDING the two new connection
    pipes."""
    max_velocity_m_s: float

    mass_balance: MassBalanceCheck
    """pump_mass_flow_kg_s here is the COMBINED main-plant-pump plus
    geothermal-injection mass flow -- see main_pump_mass_flow_kg_s /
    geothermal_injected_mass_flow_kg_s below for the individual breakdown,
    never hidden inside the combined figure alone."""
    energy_balance: EnergyBalanceCheck
    """pump_physical_enthalpy_kw here is likewise the COMBINED main-plant-
    pump plus geothermal-injection physical enthalpy."""

    circulation_pump: CirculationPumpResult
    """The MAIN PLANT pump's own KPIs on this candidate net -- present and
    gated exactly as in the baseline (plan's "continued auxiliary-plant
    operation")."""

    geothermal_injected_heat_kw: float
    geothermal_curtailed_heat_kw: float
    auxiliary_heat_kw: float
    """max(0, total_heat_delivered_kw - geothermal_injected_heat_kw) -- the
    main plant's own contribution, under the 'cost_shortfall' policy
    (auxiliary always covers any shortfall)."""
    unmet_heat_kw: Literal[0.0] = 0.0
    """Always 0.0 under 'cost_shortfall' (the only policy this evaluator
    implements -- GeothermalInjectionPolicy rejects any other value)."""
    geothermal_coverage_fraction: float
    """geothermal_injected_heat_kw / baseline_total_heat_delivered_kw --
    <= 1.0 always, by construction of _compute_injected_heat_kw's min()."""

    district_heating_water_mass_flow_injected_kg_s: float
    """The SOLVED (not merely requested) mass flow through the geothermal
    injection branch -- explicitly distinct from any brine-flow field
    (CLAUDE.md's brine/DH-water separation, continued from T2.1)."""

    geothermal_injection_inlet_temperature_c: float
    """The geothermal injection branch's ACTUAL solved inlet temperature
    (the heat_consumer's own t_from_k, i.e. the network's real mixed
    return-water temperature arriving at this candidate's return
    junction) -- NOT assumed to equal
    geothermal_injection_inlet_design_temperature_c. See
    geothermal_injection_inlet_temperature_deviation_k and the module
    docstring's "Curtailment" section for why these can differ
    (approximately 36 degC actual vs. 40 degC design at the chosen 1%
    margin, in the worked case)."""
    geothermal_injection_inlet_design_temperature_c: float
    """coupling_input.assumptions.dh_return_temperature_c -- the design
    target _compute_injected_mass_flow_kg_s sizes the injection against."""
    geothermal_injection_inlet_temperature_deviation_k: float
    """geothermal_injection_inlet_temperature_c - geothermal_injection_inlet_design_temperature_c
    (signed; negative means the branch's actual inlet ran colder than
    design)."""

    geothermal_injection_outlet_temperature_c: float
    """The geothermal injection branch's ACTUAL solved outlet temperature
    (the heat_consumer's own t_outlet_k) -- what is actually injected into
    the candidate's supply junction, distinct from the design target."""
    geothermal_injection_outlet_design_temperature_c: float
    """coupling_input.assumptions.dh_supply_temperature_c -- the design DH
    supply temperature."""
    geothermal_injection_outlet_temperature_deviation_k: float
    """geothermal_injection_outlet_temperature_c - geothermal_injection_outlet_design_temperature_c
    (signed; negative means the branch's actual outlet ran colder than
    design)."""

    connection_pipe_dn_mm: float
    connection_pressure_drop_bar: float
    """Friction-loss-only pressure drop across the two connection pipes
    (return connection pipe drop + supply connection pipe drop) --
    EXCLUDES the injection pump's own lift, a separate quantity."""
    connection_pumping_power_kw: float
    """The geothermal injection pump's own hydraulic hydraulic power
    (pandapipes' own res_pump.compr_power_mw, converted to kW) -- separate
    from circulation_pump.hydraulic_pumping_power_kw (the MAIN plant
    pump's own, unrelated figure)."""

    doublet_pump_electric_power_kw: float
    """Top-level convenience copy of
    coupling_input.coupling_input.doublet_pump_electric_power_kw.value,
    preserved unchanged -- never recomputed, never combined with any DH-
    side pumping figure. Cross-checked for exact equality by this model's
    own invariant."""

    baseline_total_heat_delivered_kw: float
    baseline_main_pump_mass_flow_kg_s: float
    baseline_main_pump_hydraulic_power_kw: float
    baseline_min_pressure_bar_abs: float
    baseline_max_velocity_m_s: float
    """The five baseline scalar reference points kpi_deltas is computed
    against -- stored explicitly (not the full embedded BaselineNetworkResult,
    judged out of proportion, matching BaselineNetworkResult's own choice
    not to embed raw pandapipes tables) so kpi_deltas remains fully
    recomputable from this model alone."""
    kpi_deltas: CandidateKpiDeltas

    warnings: list[CouplingWarning] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "CandidateEvaluationResult":
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
        if mb.passed != (mb.residual_fraction <= mb.tolerance_fraction):
            errors.append("mass_balance.passed is inconsistent with residual_fraction vs. tolerance_fraction")
        if not mb.passed:
            errors.append("mass_balance.passed must be True on a success result")

        eb = self.energy_balance
        if eb.pump_physical_enthalpy_kw <= 0:
            errors.append("energy_balance.pump_physical_enthalpy_kw must be > 0")
        if eb.passed != (eb.residual_fraction <= eb.tolerance_fraction):
            errors.append("energy_balance.passed is inconsistent with residual_fraction vs. tolerance_fraction")
        if not eb.passed:
            errors.append("energy_balance.passed must be True on a success result")
        if eb.integration_method != ENTHALPY_INTEGRATION_METHOD:
            errors.append("energy_balance.integration_method does not match the project's fixed method")
        if eb.integration_segments != ENTHALPY_INTEGRATION_SEGMENTS:
            errors.append("energy_balance.integration_segments does not match the project's fixed segment count")

        if self.circulation_pump.mass_flow_kg_s <= 0:
            errors.append("circulation_pump.mass_flow_kg_s must be > 0")
        if self.circulation_pump.hydraulic_pumping_power_kw < 0:
            errors.append("circulation_pump.hydraulic_pumping_power_kw must be >= 0")

        # ── Curtailment/injection physics chain -- recomputed via the SAME
        # pure helper evaluate_candidate() itself uses. ──
        expected_injected_kw, expected_curtailed_kw, expected_stabilization_applied = _compute_injected_heat_kw(
            self.coupling_input.deliverable_geothermal_heat_kw.value,
            self.baseline_total_heat_delivered_kw,
            self.injection_policy.minimum_auxiliary_circulation_fraction,
        )
        if not math.isclose(expected_injected_kw, self.geothermal_injected_heat_kw, rel_tol=1e-9):
            errors.append("geothermal_injected_heat_kw does not match recomputation")
        if not math.isclose(expected_curtailed_kw, self.geothermal_curtailed_heat_kw, rel_tol=1e-9, abs_tol=1e-9):
            errors.append("geothermal_curtailed_heat_kw does not match recomputation")
        warning_codes = {w.code for w in self.warnings}
        stabilization_warning_present = PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED in warning_codes
        if expected_stabilization_applied != stabilization_warning_present:
            errors.append(
                "warnings does not correctly reflect whether the solver-stability "
                "curtailment margin was applied -- PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED "
                f"must be present iff stabilization was applied (expected present={expected_stabilization_applied}, "
                f"actual present={stabilization_warning_present})"
            )

        # ── The chain must feed from coupling_input.deliverable_geothermal_heat_kw
        # exclusively (CLAUDE.md: raw PyDoublet power is not automatically
        # DH-deliverable power) -- checked by an EQUALITY, not an inequality
        # against raw power. A prior version of this check instead asserted
        # injected+curtailed is never numerically close to raw power, which
        # is WRONG: a physically valid T2.1 result can have
        # deliverable_geothermal_heat_kw == raw_geothermal_thermal_power_kw
        # exactly (hx_heat_delivery_factor=1.0 with the raw-power term
        # binding -- see adapter/heat_exchanger.py's own
        # test_deliverable_heat_may_equal_raw_power_when_factor_is_one_and_raw_power_binds,
        # commit 81319978), and the old check would have wrongly rejected
        # that legitimate case. Checking equality against `deliverable_geothermal_heat_kw`
        # directly is correct regardless of whether that value happens to
        # coincide with raw power upstream. ──
        if not math.isclose(
            self.geothermal_injected_heat_kw + self.geothermal_curtailed_heat_kw,
            self.coupling_input.deliverable_geothermal_heat_kw.value, rel_tol=1e-9,
        ):
            errors.append(
                "geothermal_injected_heat_kw + geothermal_curtailed_heat_kw must equal "
                "coupling_input.deliverable_geothermal_heat_kw exactly"
            )

        expected_mass_flow = _compute_injected_mass_flow_kg_s(
            self.geothermal_injected_heat_kw,
            self.coupling_input.assumptions.dh_supply_temperature_c,
            self.coupling_input.assumptions.dh_return_temperature_c,
            self.coupling_input.assumptions.dh_water_specific_heat_capacity_j_kg_k,
        )
        if not math.isclose(expected_mass_flow, self.district_heating_water_mass_flow_injected_kg_s, rel_tol=1e-6):
            errors.append(
                "district_heating_water_mass_flow_injected_kg_s does not match the "
                "requested-injection recomputation within solver precision"
            )

        # ── Geothermal-branch actual vs. design temperatures (deviation
        # figures must be pure arithmetic on the stored actual/design pair). ──
        if not math.isclose(
            self.geothermal_injection_inlet_design_temperature_c,
            self.coupling_input.assumptions.dh_return_temperature_c, rel_tol=1e-9,
        ):
            errors.append("geothermal_injection_inlet_design_temperature_c does not match coupling_input.assumptions.dh_return_temperature_c")
        if not math.isclose(
            self.geothermal_injection_outlet_design_temperature_c,
            self.coupling_input.assumptions.dh_supply_temperature_c, rel_tol=1e-9,
        ):
            errors.append("geothermal_injection_outlet_design_temperature_c does not match coupling_input.assumptions.dh_supply_temperature_c")
        expected_inlet_deviation = self.geothermal_injection_inlet_temperature_c - self.geothermal_injection_inlet_design_temperature_c
        if not math.isclose(expected_inlet_deviation, self.geothermal_injection_inlet_temperature_deviation_k, rel_tol=1e-9, abs_tol=1e-9):
            errors.append("geothermal_injection_inlet_temperature_deviation_k does not match recomputation")
        expected_outlet_deviation = self.geothermal_injection_outlet_temperature_c - self.geothermal_injection_outlet_design_temperature_c
        if not math.isclose(expected_outlet_deviation, self.geothermal_injection_outlet_temperature_deviation_k, rel_tol=1e-9, abs_tol=1e-9):
            errors.append("geothermal_injection_outlet_temperature_deviation_k does not match recomputation")

        if self.geothermal_injected_heat_kw <= 0:
            errors.append("geothermal_injected_heat_kw must be > 0")
        if self.geothermal_curtailed_heat_kw < 0:
            errors.append("geothermal_curtailed_heat_kw must be >= 0")
        if not (0.0 < self.geothermal_coverage_fraction <= 1.0):
            errors.append("geothermal_coverage_fraction must be in (0, 1]")
        expected_coverage = self.geothermal_injected_heat_kw / self.baseline_total_heat_delivered_kw
        if not math.isclose(expected_coverage, self.geothermal_coverage_fraction, rel_tol=1e-9):
            errors.append("geothermal_coverage_fraction does not match recomputation")

        expected_auxiliary = max(0.0, self.total_heat_delivered_kw - self.geothermal_injected_heat_kw)
        if not math.isclose(expected_auxiliary, self.auxiliary_heat_kw, rel_tol=1e-9, abs_tol=1e-9):
            errors.append("auxiliary_heat_kw does not match recomputation")
        if self.auxiliary_heat_kw < 0:
            errors.append("auxiliary_heat_kw must be >= 0")
        if self.unmet_heat_kw != 0.0:
            errors.append("unmet_heat_kw must be 0.0 under the only implemented policy (cost_shortfall)")

        if self.connection_pipe_dn_mm != CONNECTION_PIPE_DN_MM:
            errors.append("connection_pipe_dn_mm does not match the project's fixed connection DN")
        if self.connection_pressure_drop_bar < 0:
            errors.append("connection_pressure_drop_bar must be >= 0")
        if self.connection_pumping_power_kw < 0:
            errors.append("connection_pumping_power_kw must be >= 0")

        expected_doublet_kw = self.coupling_input.coupling_input.doublet_pump_electric_power_kw.value
        if not math.isclose(expected_doublet_kw, self.doublet_pump_electric_power_kw, rel_tol=1e-12):
            errors.append(
                "doublet_pump_electric_power_kw does not exactly match "
                "coupling_input.coupling_input.doublet_pump_electric_power_kw -- "
                "must be preserved unchanged, never recomputed"
            )

        deltas = self.kpi_deltas
        expected_deltas = {
            "total_heat_delivered_delta_kw": self.total_heat_delivered_kw - self.baseline_total_heat_delivered_kw,
            "main_pump_mass_flow_delta_kg_s": self.circulation_pump.mass_flow_kg_s - self.baseline_main_pump_mass_flow_kg_s,
            "main_pump_hydraulic_power_delta_kw": self.circulation_pump.hydraulic_pumping_power_kw - self.baseline_main_pump_hydraulic_power_kw,
            "min_pressure_delta_bar_abs": self.min_pressure_bar_abs - self.baseline_min_pressure_bar_abs,
            "max_velocity_delta_m_s": self.max_velocity_m_s - self.baseline_max_velocity_m_s,
        }
        for field_name, expected_value in expected_deltas.items():
            if not math.isclose(expected_value, getattr(deltas, field_name), rel_tol=1e-9, abs_tol=1e-9):
                errors.append(f"kpi_deltas.{field_name} does not match recomputation")

        if errors:
            raise ValueError("; ".join(errors))
        return self


class CandidateEvaluationFailure(BaseModel):
    """A rejected candidate evaluation. Always preserves the candidate spec
    and the complete upstream coupling result -- a failure is still fully
    auditable, same rule as every earlier layer."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.1.0"] = CANDIDATE_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"
    failure_code: CandidateFailureCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    candidate: BlueprintCandidate
    coupling_input: HeatExchangerCouplingResult
    created_at: datetime


CandidateEvaluationBoundaryResult = Annotated[
    Union[CandidateEvaluationResult, CandidateEvaluationFailure],
    Field(discriminator="status"),
]
"""Real Pydantic discriminated union on `status`, resolved via a
TypeAdapter -- the same established pattern as every earlier layer's
BoundaryResult."""

_boundary_result_adapter: TypeAdapter = TypeAdapter(CandidateEvaluationBoundaryResult)


def parse_candidate_result_json(json_str: str) -> CandidateEvaluationBoundaryResult:
    """Deserialize a JSON string produced by either model's
    model_dump_json() back into the correct typed model via Pydantic's
    discriminated-union validation -- full model-level invariant
    re-validation included."""
    return _boundary_result_adapter.validate_json(json_str)


def _add_geothermal_injection_branch(
    net: "pandapipes.pandapipesNet",
    candidate: BlueprintCandidate,
    blueprint: NetworkBlueprint,
    injected_kw: float,
    injected_mass_flow_kg_s: float,
    dh_supply_temperature_c: float,
    dh_return_temperature_c: float,
) -> dict[str, str]:
    """Mutates `net` (a freshly-built pandapipesNet -- never `blueprint`,
    a frozen Pydantic model incapable of mutation regardless) by adding the
    selected topology (module docstring). Returns the new pandapipes
    element NAMES (not raw indices -- callers re-look-up indices from
    net.junction/net.pipe/net.heat_consumer/net.pump AFTER pipeflow(),
    since result extraction always goes through the *_idx name->index maps
    built fresh from the solved net, matching baseline.py's own pattern)."""
    junction_by_name = {name: idx for idx, name in enumerate(net.junction["name"])}
    j_return_trunk = junction_by_name[candidate.return_junction]
    j_supply_trunk = junction_by_name[candidate.supply_junction]

    return_t_k = dh_return_temperature_c + 273.15
    supply_t_k = dh_supply_temperature_c + 273.15
    pn_bar_gauge = float(net.junction.at[j_supply_trunk, "pn_bar"])

    geo_return_name = f"geo_return_{candidate.id}"
    geo_mid_name = f"geo_mid_{candidate.id}"
    geo_supply_name = f"geo_supply_{candidate.id}"
    return_pipe_name = f"geo_return_connection_{candidate.id}"
    supply_pipe_name = f"geo_supply_connection_{candidate.id}"
    pump_name = f"geo_injection_pump_{candidate.id}"
    heat_consumer_name = f"geo_injection_{candidate.id}"

    j_geo_return = pandapipes.create_junction(
        net, pn_bar=pn_bar_gauge, tfluid_k=return_t_k, name=geo_return_name,
    )
    j_geo_mid = pandapipes.create_junction(
        net, pn_bar=pn_bar_gauge, tfluid_k=return_t_k, name=geo_mid_name,
    )
    j_geo_supply = pandapipes.create_junction(
        net, pn_bar=pn_bar_gauge, tfluid_k=supply_t_k, name=geo_supply_name,
    )

    bp = blueprint.build_parameters
    length_km = candidate.surface_connection_length_m / 1000.0
    ground_t_k = bp.ground_temperature_c + 273.15
    pandapipes.create_pipe_from_parameters(
        net, j_return_trunk, j_geo_return, length_km=length_km,
        inner_diameter_mm=CONNECTION_PIPE_DN_MM, k_mm=bp.pipe_roughness_mm,
        u_w_per_m2k=bp.pipe_heat_transfer_coefficient_w_per_m2k, text_k=ground_t_k,
        name=return_pipe_name,
    )

    lift_bar = blueprint.circulation_pump.pressure_lift_bar
    pandapipes.create_pump_from_parameters(
        net, j_geo_return, j_geo_mid, new_std_type_name=f"geo_injection_lift_curve_{candidate.id}",
        pressure_list=[lift_bar, lift_bar], flowrate_list=[0.0, 100.0], reg_polynomial_degree=1,
        name=pump_name,
    )

    pandapipes.create_heat_consumer(
        net, j_geo_mid, j_geo_supply,
        qext_w=-injected_kw * 1000.0, controlled_mdot_kg_per_s=injected_mass_flow_kg_s,
        name=heat_consumer_name,
    )

    pandapipes.create_pipe_from_parameters(
        net, j_geo_supply, j_supply_trunk, length_km=length_km,
        inner_diameter_mm=CONNECTION_PIPE_DN_MM, k_mm=bp.pipe_roughness_mm,
        u_w_per_m2k=bp.pipe_heat_transfer_coefficient_w_per_m2k, text_k=ground_t_k,
        name=supply_pipe_name,
    )

    return {
        "geo_return": geo_return_name, "geo_mid": geo_mid_name, "geo_supply": geo_supply_name,
        "return_pipe": return_pipe_name, "supply_pipe": supply_pipe_name,
        "pump": pump_name, "heat_consumer": heat_consumer_name,
    }


def evaluate_candidate(
    coupling_result: HeatExchangerCouplingResult,
    blueprint: NetworkBlueprint,
    candidate: BlueprintCandidate,
    baseline: BaselineNetworkResult,
    *,
    injection_policy: GeothermalInjectionPolicy,
    tolerances: GateTolerances,
) -> CandidateEvaluationBoundaryResult:
    """Evaluate one candidate independently: build a FRESH net from
    `blueprint` (never a shared/cached net -- non-mutation and
    candidate-independence both depend on this), add the geothermal
    injection branch (module docstring), solve, extract every KPI, apply
    gates 6-11 (plan §11) plus the geothermal-injection-specific hydraulic
    gate, in order. Never raises for any of the seven recognized failure
    modes; never mutates `blueprint`, `coupling_result`, or `baseline`."""
    created_at = datetime.now(timezone.utc)
    net = build_pandapipes_net(blueprint)

    injected_kw, curtailed_kw, stabilization_margin_applied = _compute_injected_heat_kw(
        coupling_result.deliverable_geothermal_heat_kw.value,
        baseline.total_heat_delivered_kw,
        injection_policy.minimum_auxiliary_circulation_fraction,
    )
    warnings: list[CouplingWarning] = []
    if stabilization_margin_applied:
        warnings.append(CouplingWarning(
            code=PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED,
            message=(
                "Geothermal injection was capped below baseline demand for two "
                "independent reasons documented in "
                "docs/technical-observations/pandapipes-circulation-pump-direction-check.md: "
                "(1) it keeps the main plant pump's converged net mass flow safely "
                "clear of pandapipes 0.14.0's near-zero-tolerance direction-change "
                "check; (2) it keeps the main pump's own design-temperature flow "
                "large enough to anchor the network's thermal field, since the "
                "injection branch's own achieved outlet temperature undershoots "
                "the DH design supply temperature once the main pump's share of "
                "flow shrinks too far (see geothermal_injection_inlet_temperature_c/"
                "geothermal_injection_outlet_temperature_c and their _deviation_k "
                "fields on this result for the measured values). This is a "
                "numerical-stability margin, not a supply/demand-driven curtailment."
            ),
            affects=["geothermal_injected_heat_kw", "geothermal_curtailed_heat_kw"],
        ))
    injected_mass_flow_kg_s = _compute_injected_mass_flow_kg_s(
        injected_kw,
        coupling_result.assumptions.dh_supply_temperature_c,
        coupling_result.assumptions.dh_return_temperature_c,
        coupling_result.assumptions.dh_water_specific_heat_capacity_j_kg_k,
    )

    refs = _add_geothermal_injection_branch(
        net, candidate, blueprint, injected_kw, injected_mass_flow_kg_s,
        coupling_result.assumptions.dh_supply_temperature_c,
        coupling_result.assumptions.dh_return_temperature_c,
    )

    try:
        pandapipes.pipeflow(net, mode="sequential")
    except pandapipes.PipeflowNotConverged as exc:
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED,
            message=f"pandapipes pipeflow(mode='sequential') did not converge: {exc}",
            details={}, candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )
    except UserWarning as exc:
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT,
            message=f"pandapipes raised UserWarning during pipeflow() (see module docstring, 'Curtailment'): {exc}",
            details={}, candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )

    if not bool(net.converged):
        # Defensive: verified unreachable in pandapipes 0.14.0 (T2.2B),
        # kept in case a future pandapipes version changes this.
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED,
            message="pipeflow returned without raising but net.converged is False.",
            details={}, candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )

    # ── Delivered-heat/capacity gate (CFG-004 gate 8, DSP-003): a genuine
    # RESOURCE shortfall -- deliverable geothermal heat below total demand
    # by more than the configured tolerance -- is infeasible ONLY under the
    # "strict_infeasible" policy. Checked against the raw
    # deliverable_geothermal_heat_kw (never the curtailed injected_kw), so
    # this stays independent of the surplus-curtailment/stabilization-margin
    # bookkeeping above (DSP-004's required separation) -- a surplus case
    # can never trigger this by construction (deliverable >= demand implies
    # no shortfall). Under the default "cost_shortfall" policy a shortfall
    # is instead covered by auxiliary_heat_kw below, never gated here. ──
    if injection_policy.auxiliary_policy == "strict_infeasible":
        required_minimum_kw = baseline.total_heat_delivered_kw * (1.0 - injection_policy.heat_delivery_tolerance_fraction)
        if coupling_result.deliverable_geothermal_heat_kw.value < required_minimum_kw:
            return CandidateEvaluationFailure(
                failure_code=CandidateFailureCode.GEOTHERMAL_HEAT_SHORTFALL,
                message=(
                    "deliverable_geothermal_heat_kw falls short of "
                    "baseline_total_heat_delivered_kw by more than "
                    "heat_delivery_tolerance_fraction under the "
                    "strict_infeasible policy."
                ),
                details={
                    "deliverable_geothermal_heat_kw": coupling_result.deliverable_geothermal_heat_kw.value,
                    "baseline_total_heat_delivered_kw": baseline.total_heat_delivered_kw,
                    "heat_delivery_tolerance_fraction": injection_policy.heat_delivery_tolerance_fraction,
                    "required_minimum_kw": required_minimum_kw,
                },
                candidate=candidate, coupling_input=coupling_result, created_at=created_at,
            )

    fluid = get_fluid(net)
    junction_idx = {name: idx for idx, name in enumerate(net.junction["name"])}
    pipe_idx = {name: idx for idx, name in enumerate(net.pipe["name"])}
    hc_idx = {name: idx for idx, name in enumerate(net.heat_consumer["name"])}
    pump_idx = {name: idx for idx, name in enumerate(net.pump["name"])}

    # ── Per-consumer KPIs: ORIGINAL blueprint consumers only -- the geo
    # injection's own heat_consumer is a SOURCE, never mixed in here. ──
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
            return CandidateEvaluationFailure(
                failure_code=CandidateFailureCode.CONSUMER_TEMPERATURE_NOT_MET,
                message=f"consumers[{consumer_id!r}] supply_temperature_drop_k exceeds max_consumer_supply_drop_k.",
                details={
                    "consumer_id": consumer_id,
                    "supply_temperature_drop_k": consumer_result.supply_temperature_drop_k,
                    "max_consumer_supply_drop_k": tolerances.max_consumer_supply_drop_k,
                },
                candidate=candidate, coupling_input=coupling_result, created_at=created_at,
            )

    # ── Pressure: EVERY junction in the candidate net (blueprint's own
    # plus the three new geothermal-injection junctions). ──
    junction_pressures_bar_abs = {
        name: to_absolute_bar(net.res_junction.loc[idx, "p_bar"]) for name, idx in junction_idx.items()
    }
    min_pressure_bar_abs = min(junction_pressures_bar_abs.values())
    if min_pressure_bar_abs < tolerances.min_pressure_bar_abs:
        worst_junction = min(junction_pressures_bar_abs, key=junction_pressures_bar_abs.get)
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.PRESSURE_LIMIT_EXCEEDED,
            message=f"junction {worst_junction!r} absolute pressure below min_pressure_bar_abs.",
            details={
                "junction": worst_junction, "pressure_bar_abs": min_pressure_bar_abs,
                "min_pressure_bar_abs": tolerances.min_pressure_bar_abs,
            },
            candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )

    # ── Main plant pump (unchanged component, plan's "continued
    # auxiliary-plant operation"), moved ahead of velocity (CFG-004 gate
    # order: pressure(10) -> pump differential-pressure(11) -> velocity(12)) ──
    pump_row = net.res_circ_pump_pressure.iloc[0]
    main_pump_mass_flow_kg_s = abs(pump_row["mdot_from_kg_per_s"])
    main_pump_pressure_lift_bar = pump_row["p_to_bar"] - pump_row["p_from_bar"]
    main_pump_hydraulic_power_kw = (main_pump_pressure_lift_bar * 1e5 * pump_row["vdot_m3_per_s"]) / 1000.0
    circulation_pump = CirculationPumpResult(
        mass_flow_kg_s=main_pump_mass_flow_kg_s, pressure_lift_bar=main_pump_pressure_lift_bar,
        flow_temperature_c=pump_row["t_outlet_k"] - 273.15, return_temperature_c=pump_row["t_from_k"] - 273.15,
        hydraulic_pumping_power_kw=main_pump_hydraulic_power_kw,
    )

    # ── Geothermal injection branch's own solved results ──
    geo_hc_row = net.res_heat_consumer.iloc[hc_idx[refs["heat_consumer"]]]
    geo_mass_flow_kg_s = abs(geo_hc_row["mdot_from_kg_per_s"])
    geo_pump_row = net.res_pump.iloc[pump_idx[refs["pump"]]]
    connection_pumping_power_kw = float(geo_pump_row["compr_power_mw"]) * 1000.0
    connection_pressure_drop_bar = (
        (junction_pressures_bar_abs[candidate.return_junction] - junction_pressures_bar_abs[refs["geo_return"]])
        + (junction_pressures_bar_abs[refs["geo_supply"]] - junction_pressures_bar_abs[candidate.supply_junction])
    )
    geo_injection_pump_pressure_lift_bar = (
        junction_pressures_bar_abs[refs["geo_mid"]] - junction_pressures_bar_abs[refs["geo_return"]]
    )
    """Absolute-pressure difference across the geothermal injection pump
    (geo_mid minus geo_return) -- the ABSOLUTE-reference difference equals
    the GAUGE-reference difference (a constant atmospheric offset cancels
    in a subtraction), so this is valid despite junction_pressures_bar_abs
    itself being converted via to_absolute_bar()."""

    # ── Actual vs. design temperatures at the injection branch (module
    # docstring, "Curtailment" -- exposed as typed KPIs, not left only in
    # the technical-observation document). ──
    geo_inlet_actual_c = float(geo_hc_row["t_from_k"]) - 273.15
    geo_inlet_design_c = coupling_result.assumptions.dh_return_temperature_c
    geo_outlet_actual_c = float(geo_hc_row["t_outlet_k"]) - 273.15
    geo_outlet_design_c = coupling_result.assumptions.dh_supply_temperature_c

    # ── Pump differential-pressure gate (CFG-003/CFG-004 gate 11): applies
    # to BOTH the main plant pump and the geothermal injection pump. ──
    if circulation_pump.pressure_lift_bar > tolerances.max_pump_dp_bar:
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED,
            message="main plant circulation pump pressure_lift_bar exceeds max_pump_dp_bar.",
            details={
                "pump": "circulation_pump", "pressure_lift_bar": circulation_pump.pressure_lift_bar,
                "max_pump_dp_bar": tolerances.max_pump_dp_bar,
            },
            candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )
    if geo_injection_pump_pressure_lift_bar > tolerances.max_pump_dp_bar:
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED,
            message="geothermal injection pump pressure lift exceeds max_pump_dp_bar.",
            details={
                "pump": refs["pump"], "pressure_lift_bar": geo_injection_pump_pressure_lift_bar,
                "max_pump_dp_bar": tolerances.max_pump_dp_bar,
            },
            candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )

    # ── Velocity: EVERY pipe in the candidate net (blueprint's own plus
    # the two new connection pipes). ──
    pipe_velocities_m_s = {
        name: abs(net.res_pipe.loc[idx, "v_mean_m_per_s"]) for name, idx in pipe_idx.items()
    }
    max_velocity_m_s = max(pipe_velocities_m_s.values())
    if max_velocity_m_s > tolerances.max_pipe_velocity_m_s:
        worst_pipe = max(pipe_velocities_m_s, key=pipe_velocities_m_s.get)
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.VELOCITY_LIMIT_EXCEEDED,
            message=f"pipe {worst_pipe!r} velocity exceeds max_pipe_velocity_m_s.",
            details={
                "pipe": worst_pipe, "velocity_m_s": max_velocity_m_s,
                "max_pipe_velocity_m_s": tolerances.max_pipe_velocity_m_s,
            },
            candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )

    # ── Mass balance: COMBINED (main pump + geothermal injection) supply
    # vs. total consumer demand. ──
    total_consumer_mass_flow_kg_s = sum(c.mass_flow_kg_s for c in consumers.values())
    combined_pump_mass_flow_kg_s = main_pump_mass_flow_kg_s + geo_mass_flow_kg_s
    mass_residual_fraction = abs(combined_pump_mass_flow_kg_s - total_consumer_mass_flow_kg_s) / combined_pump_mass_flow_kg_s
    mass_balance = MassBalanceCheck(
        pump_mass_flow_kg_s=combined_pump_mass_flow_kg_s, total_consumer_mass_flow_kg_s=total_consumer_mass_flow_kg_s,
        residual_fraction=mass_residual_fraction, tolerance_fraction=tolerances.mass_balance_tolerance_fraction,
        passed=mass_residual_fraction <= tolerances.mass_balance_tolerance_fraction,
    )
    if not mass_balance.passed:
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.MASS_BALANCE_FAILED,
            message="combined (main pump + geothermal injection) mass-flow residual exceeds mass_balance_tolerance_fraction.",
            details={
                "residual_fraction": mass_residual_fraction,
                "tolerance_fraction": tolerances.mass_balance_tolerance_fraction,
            },
            candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )

    total_heat_delivered_kw = sum(c.heat_delivered_kw for c in consumers.values())
    min_consumer_supply_temperature_c = min(c.supply_temperature_c for c in consumers.values())
    mean_consumer_return_temperature_c = sum(c.return_temperature_c for c in consumers.values()) / len(consumers)

    # ── Energy balance: COMBINED (main pump + geothermal injection)
    # physical enthalpy -- true integral cp(T) dT, same method as T2.2B. ──
    main_pump_physical_w = _physical_enthalpy_delta_w(fluid, main_pump_mass_flow_kg_s, pump_row["t_outlet_k"], pump_row["t_from_k"])
    geo_physical_w = _physical_enthalpy_delta_w(fluid, geo_mass_flow_kg_s, geo_hc_row["t_outlet_k"], geo_hc_row["t_from_k"])
    consumer_physical_w = sum(
        _physical_enthalpy_delta_w(
            fluid, net.res_heat_consumer.iloc[hc_idx[cid]]["mdot_from_kg_per_s"],
            net.res_heat_consumer.iloc[hc_idx[cid]]["t_from_k"], net.res_heat_consumer.iloc[hc_idx[cid]]["t_outlet_k"],
        )
        for cid in blueprint.consumers
    )
    pipe_physical_loss_w = sum(
        _physical_enthalpy_delta_w(
            fluid, net.res_pipe.iloc[idx]["mdot_from_kg_per_s"],
            net.res_pipe.iloc[idx]["t_from_k"], net.res_pipe.iloc[idx]["t_outlet_k"],
        )
        for idx in pipe_idx.values()
    )
    combined_pump_physical_enthalpy_kw = (main_pump_physical_w + geo_physical_w) / 1000.0
    consumer_physical_enthalpy_kw = consumer_physical_w / 1000.0
    pipe_physical_heat_loss_kw = pipe_physical_loss_w / 1000.0
    physical_energy_residual_fraction = (
        abs(combined_pump_physical_enthalpy_kw - (consumer_physical_enthalpy_kw + pipe_physical_heat_loss_kw))
        / combined_pump_physical_enthalpy_kw
    )
    energy_balance = EnergyBalanceCheck(
        pump_physical_enthalpy_kw=combined_pump_physical_enthalpy_kw, consumer_physical_enthalpy_kw=consumer_physical_enthalpy_kw,
        pipe_physical_heat_loss_kw=pipe_physical_heat_loss_kw,
        integration_method=ENTHALPY_INTEGRATION_METHOD, integration_segments=ENTHALPY_INTEGRATION_SEGMENTS,
        residual_fraction=physical_energy_residual_fraction,
        tolerance_fraction=tolerances.energy_balance_tolerance_fraction,
        passed=physical_energy_residual_fraction <= tolerances.energy_balance_tolerance_fraction,
    )
    if not energy_balance.passed:
        return CandidateEvaluationFailure(
            failure_code=CandidateFailureCode.ENERGY_BALANCE_FAILED,
            message="combined (main pump + geothermal injection) physical enthalpy-balance residual exceeds energy_balance_tolerance_fraction.",
            details={
                "residual_fraction": physical_energy_residual_fraction,
                "tolerance_fraction": tolerances.energy_balance_tolerance_fraction,
            },
            candidate=candidate, coupling_input=coupling_result, created_at=created_at,
        )

    geothermal_coverage_fraction = injected_kw / baseline.total_heat_delivered_kw
    auxiliary_heat_kw = max(0.0, total_heat_delivered_kw - injected_kw)

    kpi_deltas = CandidateKpiDeltas(
        total_heat_delivered_delta_kw=total_heat_delivered_kw - baseline.total_heat_delivered_kw,
        main_pump_mass_flow_delta_kg_s=main_pump_mass_flow_kg_s - baseline.circulation_pump.mass_flow_kg_s,
        main_pump_hydraulic_power_delta_kw=main_pump_hydraulic_power_kw - baseline.circulation_pump.hydraulic_pumping_power_kw,
        min_pressure_delta_bar_abs=min_pressure_bar_abs - baseline.min_pressure_bar_abs,
        max_velocity_delta_m_s=max_velocity_m_s - baseline.max_velocity_m_s,
    )

    return CandidateEvaluationResult(
        candidate=candidate, coupling_input=coupling_result, injection_policy=injection_policy, tolerances=tolerances,
        consumers=consumers, total_heat_delivered_kw=total_heat_delivered_kw,
        min_consumer_supply_temperature_c=min_consumer_supply_temperature_c,
        mean_consumer_return_temperature_c=mean_consumer_return_temperature_c,
        junction_pressures_bar_abs=junction_pressures_bar_abs, min_pressure_bar_abs=min_pressure_bar_abs,
        pipe_velocities_m_s=pipe_velocities_m_s, max_velocity_m_s=max_velocity_m_s,
        mass_balance=mass_balance, energy_balance=energy_balance, circulation_pump=circulation_pump,
        geothermal_injected_heat_kw=injected_kw, geothermal_curtailed_heat_kw=curtailed_kw,
        auxiliary_heat_kw=auxiliary_heat_kw, geothermal_coverage_fraction=geothermal_coverage_fraction,
        district_heating_water_mass_flow_injected_kg_s=geo_mass_flow_kg_s,
        geothermal_injection_inlet_temperature_c=geo_inlet_actual_c,
        geothermal_injection_inlet_design_temperature_c=geo_inlet_design_c,
        geothermal_injection_inlet_temperature_deviation_k=geo_inlet_actual_c - geo_inlet_design_c,
        geothermal_injection_outlet_temperature_c=geo_outlet_actual_c,
        geothermal_injection_outlet_design_temperature_c=geo_outlet_design_c,
        geothermal_injection_outlet_temperature_deviation_k=geo_outlet_actual_c - geo_outlet_design_c,
        connection_pipe_dn_mm=CONNECTION_PIPE_DN_MM, connection_pressure_drop_bar=connection_pressure_drop_bar,
        connection_pumping_power_kw=connection_pumping_power_kw,
        doublet_pump_electric_power_kw=coupling_result.coupling_input.doublet_pump_electric_power_kw.value,
        baseline_total_heat_delivered_kw=baseline.total_heat_delivered_kw,
        baseline_main_pump_mass_flow_kg_s=baseline.circulation_pump.mass_flow_kg_s,
        baseline_main_pump_hydraulic_power_kw=baseline.circulation_pump.hydraulic_pumping_power_kw,
        baseline_min_pressure_bar_abs=baseline.min_pressure_bar_abs,
        baseline_max_velocity_m_s=baseline.max_velocity_m_s,
        kpi_deltas=kpi_deltas, warnings=warnings, created_at=created_at,
    )
