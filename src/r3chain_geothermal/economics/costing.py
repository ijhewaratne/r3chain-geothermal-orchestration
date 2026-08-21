"""Transparent prototype economic boundary (T2.4A, implementation plan
§12.2): CAPEX, annualised cost, and indicative LCOH for one already-
technically-feasible candidate and for the baseline (100%-auxiliary)
counterfactual.

Only ever computed on a FEASIBLE `CandidateEvaluationResult` (T2.3) --
hard technical gates are applied upstream by T2.3 and never re-derived
here (CLAUDE.md: "Apply hard technical constraints before economic
ranking"). This module is pure arithmetic on already-published typed
KPIs; it never re-solves pandapipes, never re-checks a gate, and never
invents a technical result.

## Cost chain (plan §12.2, this module's own resolutions)

- **Connection-pipe CAPEX: PAIRED-TRENCH metre.** `connection_pipe_capex_eur_per_m
  * candidate.surface_connection_length_m`, the length used ONCE -- not
  doubled for T2.3's two physical connection pipes (return + supply, same
  length, same DN). See config's own `connection_pipe_per_m_note`.
- **Doublet + heat-exchanger CAPEX are IDENTICAL across every candidate**
  (same PyDoublet scenario, same coupling result) -- this module computes
  them per-candidate for a self-contained result, but never claims they
  drive relative ranking (CLAUDE.md: "the same PyDoublet result is used
  for every candidate, so doublet CAPEX is identical and does not drive
  the relative ranking"). `ranking.py`'s `shared_capex_statement` states
  this explicitly on every ranking output, not only here.
- **Three separate annuity factors** (different asset lifetimes -- doublet
  30a, heat exchanger 20a, connection pipes 30a by default -- give
  different annuity factors; never blended into one).
- **DH pump efficiency (`dh_pump_efficiency`, config schema 0.9) converts
  HYDRAULIC pumping power into ELECTRICAL power** before costing --
  applies to the main plant pump's `circulation_pump.hydraulic_pumping_power_kw`
  and T2.3's injection pump `connection_pumping_power_kw`, summed BEFORE
  the efficiency conversion (one shared assumption, not two). Does NOT
  apply to `doublet_pump_electric_power_kw`, which PyDoublet already
  reports as electrical power (computed with its own internal efficiency).
- **`annual_full_load_hours` is a single-operating-point simplification.**
  T2.2/T2.3 model one static operating point, not an hourly time series;
  every kW-rate KPI is converted to an annual kWh/EUR figure via
  `power_kw * annual_full_load_hours` uniformly (see config's own note).
- **Curtailed heat receives no direct cost, revenue, or credit, and is
  excluded from useful annual heat.** `geothermal_curtailed_heat_kw`
  (T2.3 -- folds a true supply/demand surplus AND the
  `minimum_auxiliary_circulation_fraction` stabilization margin into one
  figure) has no dedicated cost/revenue TERM in the chain below -- there
  is no separate curtailment charge or credit, and this indicative
  boundary assumes no price for excess/unused capacity. It is NOT,
  however, economically inert: `annual_total_heat_delivered_kwh` (the
  LCOH denominator) counts only `geothermal_injected_heat_kw` +
  `auxiliary_heat_kw`, never curtailed heat, while
  `opex_electricity_doublet_pump_eur_per_a` is costed on the FULL
  `doublet_pump_electric_power_kw` regardless of how much of the
  doublet's output actually reaches the network. **Therefore, holding the
  PyDoublet scenario fixed, more curtailment reduces geothermal
  utilization and increases indicative LCOH** (verified:
  `minimum_auxiliary_circulation_fraction` 0.01 -> 0.02 -> 0.05 leaves
  `annual_total_heat_delivered_kwh` exactly constant at 16,000,000 kWh in
  the worked case, since consumer demand is met by construction either
  way, while `annualised_cost_total_eur_per_a` rises 834,742.76 EUR/a ->
  849,154.51 EUR/a -> 892,363.37 EUR/a, driven by rising
  `opex_auxiliary_heat_eur_per_a` as auxiliary makes up the larger
  shortfall). In the T2.3 worked case this effect is **identical across
  C1-C4** (curtailment depends only on the shared coupling result and the
  shared `minimum_auxiliary_circulation_fraction`, never on which
  candidate is evaluated) and therefore does not change their relative
  ranking -- but it is not claimed to be economically invariant in
  general. `geothermal_curtailed_heat_kw` is carried through on
  `CandidateEconomicResult` unchanged, for visibility, alongside
  `stabilization_margin_applied` (read straight off the embedded result's
  own warnings) so a reader can see how much of any given curtailment is
  this solver's own numerical margin rather than a true supply/demand
  surplus.
- **LCOH denominator is TOTAL delivered heat** (geothermal + auxiliary,
  `total_heat_delivered_kw` -- already equals full consumer demand by
  construction, T2.2B/T2.3), not geothermal-only: the conventional LCOH
  definition is cost per unit of heat delivered by the WHOLE candidate
  system, whose auxiliary backup cost is already in the numerator.

## Baseline DH-pumping comparison -- explicit, never merged into the candidate total

- `BaselineEconomicResult.opex_electricity_dh_pumping_eur_per_a` uses ONLY
  the baseline's own main-plant pump: `main_pump_hydraulic_power_kw / dh_pump_efficiency`
  -- there is no injection branch in the 100%-auxiliary counterfactual.
- `CandidateEconomicResult.opex_electricity_dh_pumping_eur_per_a` uses ONLY
  that candidate's own figures: `(dh_hydraulic_pumping_power_kw) / dh_pump_efficiency`,
  where `dh_hydraulic_pumping_power_kw = candidate's own (residual) main-plant
  pump hydraulic power + candidate's own injection-pump hydraulic power`
  (`circulation_pump.hydraulic_pumping_power_kw + connection_pumping_power_kw`,
  both already the CANDIDATE's post-injection figures -- T2.3's main pump
  runs at a reduced, "residual" flow once geothermal covers most of
  demand, never the baseline's own higher-flow figure).
- **The baseline's pumping cost is never added into a candidate's own
  total.** Each side's `annualised_cost_total_eur_per_a` is built purely
  from that side's own opex/capex terms; `baseline_economics` is passed
  into `compute_candidate_economics()` ONLY to compute
  `annualised_cost_delta_eur_per_a` (total-cost delta) and
  `opex_electricity_dh_pumping_delta_eur_per_a` (pumping-cost-only delta,
  `candidate.opex_electricity_dh_pumping_eur_per_a - baseline.opex_electricity_dh_pumping_eur_per_a`)
  -- both are reported as their OWN separate fields, never folded back
  into either side's own total.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ..network.baseline import BaselineNetworkResult
from ..network.blueprint import BlueprintCandidate
from ..network.candidate import (
    PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED,
    CandidateEvaluationResult,
)
from .annuity import annuity_factor
from .assumptions import EconomicAssumptions

ECONOMICS_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

BASELINE_SCOPE_CAVEAT = (
    "This is a PROTOTYPE-BOUNDARY auxiliary-heat counterfactual, not a validated "
    "full-system baseline LCOH. auxiliary_heat_price_eur_per_kwh (config economics.opex."
    "auxiliary_heat_price) is a per-kWh delivered-heat price assumption; it is NOT "
    "confirmed to be an all-inclusive price that already covers an auxiliary plant's own "
    "CAPEX and fixed O&M. Unless that price is explicitly defined as all-inclusive, "
    "indicative_lcoh_eur_per_kwh here EXCLUDES auxiliary-plant CAPEX and fixed O&M, and "
    "must not be read or compared as if computed on the same complete-system cost "
    "boundary as a candidate's own indicative_lcoh_eur_per_kwh (which DOES include "
    "doublet/HX/connection-pipe CAPEX and their fixed O&M)."
)
"""Always present on BaselineEconomicResult (module docstring, "Baseline
scope caveat") -- a structurally-guaranteed caveat field, matching
ranking.SHARED_CAPEX_STATEMENT's own established pattern for a statement
that must never be silently omitted from any consumer of this result."""


# ── Pure computation helpers -- the single source of truth, recomputed by
# each model's own invariant so a hand-tampered payload can never silently
# diverge from a genuine computation. ──

def _compute_connection_pipe_capex_eur(surface_connection_length_m: float, assumptions: EconomicAssumptions) -> float:
    """Paired-trench metre: length used once (module docstring)."""
    return assumptions.connection_pipe_capex_eur_per_m * surface_connection_length_m


def _compute_annuity_capital_eur_per_a(
    capex_doublet_eur: float, capex_heat_exchanger_eur: float, capex_connection_pipes_eur: float,
    assumptions: EconomicAssumptions,
) -> tuple[float, float, float, float]:
    """Returns (annuity_doublet, annuity_heat_exchanger, annuity_connection_pipes, total) --
    three SEPARATE annuity factors (different lifetimes), never blended."""
    a_doublet = annuity_factor(assumptions.interest_rate_real, assumptions.doublet_lifetime_years)
    a_hx = annuity_factor(assumptions.interest_rate_real, assumptions.heat_exchanger_lifetime_years)
    a_pipes = annuity_factor(assumptions.interest_rate_real, assumptions.connection_pipes_lifetime_years)
    annuity_doublet = capex_doublet_eur * a_doublet
    annuity_hx = capex_heat_exchanger_eur * a_hx
    annuity_pipes = capex_connection_pipes_eur * a_pipes
    return annuity_doublet, annuity_hx, annuity_pipes, annuity_doublet + annuity_hx + annuity_pipes


def _compute_opex_fixed_eur_per_a(total_capex_eur: float, assumptions: EconomicAssumptions) -> float:
    return assumptions.fixed_om_fraction_of_capex_per_a * total_capex_eur


def _compute_opex_electricity_eur_per_a(electrical_power_kw: float, assumptions: EconomicAssumptions) -> float:
    """power_kw * annual_full_load_hours * electricity_price -- used for
    BOTH the doublet pump (already electrical) and the DH-side pumping
    (already converted from hydraulic via dh_pump_efficiency by the
    caller -- this helper never applies that conversion itself, so it can
    serve both cases identically)."""
    return electrical_power_kw * assumptions.annual_full_load_hours * assumptions.electricity_price_eur_per_kwh


def _compute_opex_auxiliary_heat_eur_per_a(auxiliary_heat_kw: float, assumptions: EconomicAssumptions) -> float:
    return auxiliary_heat_kw * assumptions.annual_full_load_hours * assumptions.auxiliary_heat_price_eur_per_kwh


def _compute_annual_heat_delivered_kwh(total_heat_delivered_kw: float, assumptions: EconomicAssumptions) -> float:
    return total_heat_delivered_kw * assumptions.annual_full_load_hours


def _dh_electrical_pumping_power_kw(hydraulic_pumping_power_kw_sum: float, assumptions: EconomicAssumptions) -> float:
    """Converts HYDRAULIC pumping power into ELECTRICAL power via
    dh_pump_efficiency (module docstring) -- never applied to
    doublet_pump_electric_power_kw, which is already electrical."""
    return hydraulic_pumping_power_kw_sum / assumptions.dh_pump_efficiency


class BaselineEconomicResult(BaseModel):
    """The 100%-auxiliary counterfactual: no geothermal doublet/HX/
    connection-pipe investment at all, no doublet-pump electricity (no
    doublet exists in this counterfactual) -- used only for delta
    reporting against candidates, never itself ranked.

    Scope caveat (see BASELINE_SCOPE_CAVEAT, always present as
    `scope_caveat` below): this is a PROTOTYPE-BOUNDARY counterfactual,
    not a validated full-system baseline LCOH -- `indicative_lcoh_eur_per_kwh`
    excludes any auxiliary-plant CAPEX/fixed-O&M unless
    `auxiliary_heat_price_eur_per_kwh` is explicitly defined elsewhere as
    an all-inclusive delivered-heat price (this project does not define
    it as such)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = ECONOMICS_CONTRACT_SCHEMA_VERSION
    scope_caveat: Literal[BASELINE_SCOPE_CAVEAT] = BASELINE_SCOPE_CAVEAT
    assumptions: EconomicAssumptions

    total_heat_delivered_kw: float
    """100% from the auxiliary source -- baseline.total_heat_delivered_kw
    (T2.2B), embedded verbatim."""
    main_pump_hydraulic_power_kw: float

    opex_electricity_dh_pumping_eur_per_a: float
    opex_auxiliary_heat_eur_per_a: float
    annualised_cost_total_eur_per_a: float
    """capex is 0 in this counterfactual (no geothermal-specific
    investment) -- annualised_cost_total_eur_per_a == the two opex terms
    above summed, no annuity_capital term."""

    annual_total_heat_delivered_kwh: float
    indicative_lcoh_eur_per_kwh: float

    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "BaselineEconomicResult":
        errors: list[str] = []
        expected_dh_electricity = _compute_opex_electricity_eur_per_a(
            _dh_electrical_pumping_power_kw(self.main_pump_hydraulic_power_kw, self.assumptions), self.assumptions,
        )
        if not math.isclose(expected_dh_electricity, self.opex_electricity_dh_pumping_eur_per_a, rel_tol=1e-9):
            errors.append("opex_electricity_dh_pumping_eur_per_a does not match recomputation")
        expected_aux = _compute_opex_auxiliary_heat_eur_per_a(self.total_heat_delivered_kw, self.assumptions)
        if not math.isclose(expected_aux, self.opex_auxiliary_heat_eur_per_a, rel_tol=1e-9):
            errors.append("opex_auxiliary_heat_eur_per_a does not match recomputation")
        expected_total = self.opex_electricity_dh_pumping_eur_per_a + self.opex_auxiliary_heat_eur_per_a
        if not math.isclose(expected_total, self.annualised_cost_total_eur_per_a, rel_tol=1e-9):
            errors.append("annualised_cost_total_eur_per_a does not match recomputation")
        expected_kwh = _compute_annual_heat_delivered_kwh(self.total_heat_delivered_kw, self.assumptions)
        if not math.isclose(expected_kwh, self.annual_total_heat_delivered_kwh, rel_tol=1e-9):
            errors.append("annual_total_heat_delivered_kwh does not match recomputation")
        if self.annual_total_heat_delivered_kwh <= 0:
            errors.append("annual_total_heat_delivered_kwh must be > 0")
        expected_lcoh = self.annualised_cost_total_eur_per_a / self.annual_total_heat_delivered_kwh
        if not math.isclose(expected_lcoh, self.indicative_lcoh_eur_per_kwh, rel_tol=1e-9):
            errors.append("indicative_lcoh_eur_per_kwh does not match recomputation")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class CandidateEconomicResult(BaseModel):
    """A feasible candidate's full economic breakdown. Model-level
    invariants recompute every stored figure from its own stored detail
    fields via the SAME pure helpers compute_candidate_economics() itself
    uses -- a hand-tampered payload is rejected, not silently accepted."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = ECONOMICS_CONTRACT_SCHEMA_VERSION
    candidate_id: str
    candidate: BlueprintCandidate
    assumptions: EconomicAssumptions

    geothermal_injected_heat_kw: float
    geothermal_curtailed_heat_kw: float
    """Informational only -- NEVER a cost driver (module docstring)."""
    stabilization_margin_applied: bool
    """Read straight off the embedded CandidateEvaluationResult's own
    PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED warning --
    never re-derived here."""
    auxiliary_heat_kw: float
    total_heat_delivered_kw: float

    doublet_pump_electric_power_kw: float
    """Preserved unchanged from coupling_input.coupling_input.doublet_pump_electric_power_kw
    (T1.5B/T2.3) -- already electrical, never divided by dh_pump_efficiency."""
    dh_hydraulic_pumping_power_kw: float
    """Main plant pump + T2.3 injection pump HYDRAULIC power, summed --
    the value dh_pump_efficiency is applied to for
    opex_electricity_dh_pumping_eur_per_a."""

    capex_doublet_eur: float
    capex_heat_exchanger_eur: float
    capex_connection_pipes_eur: float

    annuity_doublet_eur_per_a: float
    annuity_heat_exchanger_eur_per_a: float
    annuity_connection_pipes_eur_per_a: float
    annuity_capital_eur_per_a: float
    """Sum of the three annuity_* fields above -- three SEPARATE annuity
    factors (different lifetimes), never one blended factor."""

    opex_fixed_eur_per_a: float
    opex_electricity_doublet_pump_eur_per_a: float
    opex_electricity_dh_pumping_eur_per_a: float
    opex_auxiliary_heat_eur_per_a: float

    annualised_cost_total_eur_per_a: float
    annual_total_heat_delivered_kwh: float
    indicative_lcoh_eur_per_kwh: float

    baseline_annualised_cost_total_eur_per_a: float
    baseline_opex_electricity_dh_pumping_eur_per_a: float
    """The two baseline scalar reference figures the deltas below are
    computed against -- stored explicitly (not the full embedded
    BaselineEconomicResult, judged out of proportion) so both deltas
    remain fully recomputable from this model alone, matching T2.3's own
    CandidateEvaluationResult.baseline_* precedent exactly."""

    annualised_cost_delta_eur_per_a: float
    """candidate.annualised_cost_total_eur_per_a - baseline.annualised_cost_total_eur_per_a
    (TOTAL-cost delta) -- for delta reporting only, NOT the ranking key
    (ranking.py ranks on the absolute figure; see its own module
    docstring for why the two produce the same relative order here).
    Never added into this candidate's own annualised_cost_total_eur_per_a
    (module docstring, "Baseline DH-pumping comparison")."""
    opex_electricity_dh_pumping_delta_eur_per_a: float
    """candidate.opex_electricity_dh_pumping_eur_per_a - baseline.opex_electricity_dh_pumping_eur_per_a
    -- the PUMPING-COST-ONLY delta (a strict subset of
    annualised_cost_delta_eur_per_a above, reported separately per
    explicit request). Usually negative (the candidate's main pump runs
    at reduced/residual flow once geothermal covers most of demand, so
    its own pumping electricity is normally lower than the baseline's
    full-flow figure) -- but the injection pump's own hydraulic power is
    also included on the candidate side, so this is not guaranteed to be
    negative in every configuration."""

    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "CandidateEconomicResult":
        errors: list[str] = []

        expected_pipe_capex = _compute_connection_pipe_capex_eur(
            self.candidate.surface_connection_length_m, self.assumptions,
        )
        if not math.isclose(expected_pipe_capex, self.capex_connection_pipes_eur, rel_tol=1e-9):
            errors.append("capex_connection_pipes_eur does not match recomputation")
        if not math.isclose(self.capex_doublet_eur, self.assumptions.doublet_capex_eur, rel_tol=1e-9):
            errors.append("capex_doublet_eur does not match assumptions.doublet_capex_eur")
        if not math.isclose(self.capex_heat_exchanger_eur, self.assumptions.heat_exchanger_capex_eur, rel_tol=1e-9):
            errors.append("capex_heat_exchanger_eur does not match assumptions.heat_exchanger_capex_eur")

        exp_a_doublet, exp_a_hx, exp_a_pipes, exp_a_total = _compute_annuity_capital_eur_per_a(
            self.capex_doublet_eur, self.capex_heat_exchanger_eur, self.capex_connection_pipes_eur, self.assumptions,
        )
        for expected, actual, name in (
            (exp_a_doublet, self.annuity_doublet_eur_per_a, "annuity_doublet_eur_per_a"),
            (exp_a_hx, self.annuity_heat_exchanger_eur_per_a, "annuity_heat_exchanger_eur_per_a"),
            (exp_a_pipes, self.annuity_connection_pipes_eur_per_a, "annuity_connection_pipes_eur_per_a"),
            (exp_a_total, self.annuity_capital_eur_per_a, "annuity_capital_eur_per_a"),
        ):
            if not math.isclose(expected, actual, rel_tol=1e-9):
                errors.append(f"{name} does not match recomputation")

        total_capex = self.capex_doublet_eur + self.capex_heat_exchanger_eur + self.capex_connection_pipes_eur
        expected_opex_fixed = _compute_opex_fixed_eur_per_a(total_capex, self.assumptions)
        if not math.isclose(expected_opex_fixed, self.opex_fixed_eur_per_a, rel_tol=1e-9):
            errors.append("opex_fixed_eur_per_a does not match recomputation")

        expected_opex_doublet_pump = _compute_opex_electricity_eur_per_a(
            self.doublet_pump_electric_power_kw, self.assumptions,
        )
        if not math.isclose(expected_opex_doublet_pump, self.opex_electricity_doublet_pump_eur_per_a, rel_tol=1e-9):
            errors.append("opex_electricity_doublet_pump_eur_per_a does not match recomputation")

        expected_opex_dh_pumping = _compute_opex_electricity_eur_per_a(
            _dh_electrical_pumping_power_kw(self.dh_hydraulic_pumping_power_kw, self.assumptions), self.assumptions,
        )
        if not math.isclose(expected_opex_dh_pumping, self.opex_electricity_dh_pumping_eur_per_a, rel_tol=1e-9):
            errors.append("opex_electricity_dh_pumping_eur_per_a does not match recomputation")

        expected_opex_aux = _compute_opex_auxiliary_heat_eur_per_a(self.auxiliary_heat_kw, self.assumptions)
        if not math.isclose(expected_opex_aux, self.opex_auxiliary_heat_eur_per_a, rel_tol=1e-9):
            errors.append("opex_auxiliary_heat_eur_per_a does not match recomputation")

        expected_total = (
            self.annuity_capital_eur_per_a + self.opex_fixed_eur_per_a
            + self.opex_electricity_doublet_pump_eur_per_a + self.opex_electricity_dh_pumping_eur_per_a
            + self.opex_auxiliary_heat_eur_per_a
        )
        if not math.isclose(expected_total, self.annualised_cost_total_eur_per_a, rel_tol=1e-9):
            errors.append("annualised_cost_total_eur_per_a does not match recomputation")

        expected_kwh = _compute_annual_heat_delivered_kwh(self.total_heat_delivered_kw, self.assumptions)
        if not math.isclose(expected_kwh, self.annual_total_heat_delivered_kwh, rel_tol=1e-9):
            errors.append("annual_total_heat_delivered_kwh does not match recomputation")
        if self.annual_total_heat_delivered_kwh <= 0:
            errors.append("annual_total_heat_delivered_kwh must be > 0")
        expected_lcoh = self.annualised_cost_total_eur_per_a / self.annual_total_heat_delivered_kwh
        if not math.isclose(expected_lcoh, self.indicative_lcoh_eur_per_kwh, rel_tol=1e-9):
            errors.append("indicative_lcoh_eur_per_kwh does not match recomputation")

        if self.geothermal_curtailed_heat_kw < 0:
            errors.append("geothermal_curtailed_heat_kw must be >= 0")
        if self.opex_electricity_doublet_pump_eur_per_a < 0:
            errors.append("opex_electricity_doublet_pump_eur_per_a must be >= 0")
        if self.opex_electricity_dh_pumping_eur_per_a < 0:
            errors.append("opex_electricity_dh_pumping_eur_per_a must be >= 0")

        expected_cost_delta = self.annualised_cost_total_eur_per_a - self.baseline_annualised_cost_total_eur_per_a
        if not math.isclose(expected_cost_delta, self.annualised_cost_delta_eur_per_a, rel_tol=1e-9, abs_tol=1e-6):
            errors.append("annualised_cost_delta_eur_per_a does not match recomputation")
        expected_pumping_delta = (
            self.opex_electricity_dh_pumping_eur_per_a - self.baseline_opex_electricity_dh_pumping_eur_per_a
        )
        if not math.isclose(expected_pumping_delta, self.opex_electricity_dh_pumping_delta_eur_per_a, rel_tol=1e-9, abs_tol=1e-6):
            errors.append("opex_electricity_dh_pumping_delta_eur_per_a does not match recomputation")
        # Note: `expected_total` above (annualised_cost_total_eur_per_a's
        # own recomputation) is built purely from this candidate's own five
        # terms -- no baseline_* field appears in that formula at all. That
        # check already structurally proves the baseline's cost is never
        # folded into this candidate's own total (module docstring,
        # "Baseline DH-pumping comparison"); the deltas above are the only
        # place baseline_* figures enter this model.

        if errors:
            raise ValueError("; ".join(errors))
        return self


def compute_baseline_economics(
    baseline: BaselineNetworkResult, *, assumptions: EconomicAssumptions,
) -> BaselineEconomicResult:
    """The 100%-auxiliary counterfactual (module docstring). Pure, never
    fails -- baseline is already a successful T2.2B result by type."""
    created_at = datetime.now(timezone.utc)
    main_pump_hydraulic_kw = baseline.circulation_pump.hydraulic_pumping_power_kw
    dh_electrical_kw = _dh_electrical_pumping_power_kw(main_pump_hydraulic_kw, assumptions)
    opex_dh_pumping = _compute_opex_electricity_eur_per_a(dh_electrical_kw, assumptions)
    opex_aux = _compute_opex_auxiliary_heat_eur_per_a(baseline.total_heat_delivered_kw, assumptions)
    annual_kwh = _compute_annual_heat_delivered_kwh(baseline.total_heat_delivered_kw, assumptions)
    total = opex_dh_pumping + opex_aux
    return BaselineEconomicResult(
        assumptions=assumptions,
        total_heat_delivered_kw=baseline.total_heat_delivered_kw,
        main_pump_hydraulic_power_kw=main_pump_hydraulic_kw,
        opex_electricity_dh_pumping_eur_per_a=opex_dh_pumping,
        opex_auxiliary_heat_eur_per_a=opex_aux,
        annualised_cost_total_eur_per_a=total,
        annual_total_heat_delivered_kwh=annual_kwh,
        indicative_lcoh_eur_per_kwh=total / annual_kwh,
        created_at=created_at,
    )


def compute_candidate_economics(
    candidate_result: CandidateEvaluationResult, baseline_economics: BaselineEconomicResult,
    *, assumptions: EconomicAssumptions,
) -> CandidateEconomicResult:
    """Pure, never fails -- requires the already-technically-feasible
    SUCCESS type (CandidateEvaluationResult), not the boundary union,
    matching T2.1/T2.3's "requires the already-validated success model"
    precedent (a caller holding a CandidateEvaluationFailure never calls
    this -- see ranking.py, which enforces this partition)."""
    created_at = datetime.now(timezone.utc)
    candidate = candidate_result.candidate
    capex_doublet = assumptions.doublet_capex_eur
    capex_hx = assumptions.heat_exchanger_capex_eur
    capex_pipes = _compute_connection_pipe_capex_eur(candidate.surface_connection_length_m, assumptions)

    annuity_doublet, annuity_hx, annuity_pipes, annuity_capital = _compute_annuity_capital_eur_per_a(
        capex_doublet, capex_hx, capex_pipes, assumptions,
    )
    total_capex = capex_doublet + capex_hx + capex_pipes
    opex_fixed = _compute_opex_fixed_eur_per_a(total_capex, assumptions)

    doublet_pump_electric_kw = candidate_result.coupling_input.coupling_input.doublet_pump_electric_power_kw.value
    opex_doublet_pump = _compute_opex_electricity_eur_per_a(doublet_pump_electric_kw, assumptions)

    dh_hydraulic_kw = candidate_result.circulation_pump.hydraulic_pumping_power_kw + candidate_result.connection_pumping_power_kw
    dh_electrical_kw = _dh_electrical_pumping_power_kw(dh_hydraulic_kw, assumptions)
    opex_dh_pumping = _compute_opex_electricity_eur_per_a(dh_electrical_kw, assumptions)

    opex_aux = _compute_opex_auxiliary_heat_eur_per_a(candidate_result.auxiliary_heat_kw, assumptions)

    total = annuity_capital + opex_fixed + opex_doublet_pump + opex_dh_pumping + opex_aux
    annual_kwh = _compute_annual_heat_delivered_kwh(candidate_result.total_heat_delivered_kw, assumptions)

    stabilization_applied = any(
        w.code == PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED for w in candidate_result.warnings
    )

    return CandidateEconomicResult(
        candidate_id=candidate.id, candidate=candidate, assumptions=assumptions,
        geothermal_injected_heat_kw=candidate_result.geothermal_injected_heat_kw,
        geothermal_curtailed_heat_kw=candidate_result.geothermal_curtailed_heat_kw,
        stabilization_margin_applied=stabilization_applied,
        auxiliary_heat_kw=candidate_result.auxiliary_heat_kw,
        total_heat_delivered_kw=candidate_result.total_heat_delivered_kw,
        doublet_pump_electric_power_kw=doublet_pump_electric_kw,
        dh_hydraulic_pumping_power_kw=dh_hydraulic_kw,
        capex_doublet_eur=capex_doublet, capex_heat_exchanger_eur=capex_hx, capex_connection_pipes_eur=capex_pipes,
        annuity_doublet_eur_per_a=annuity_doublet, annuity_heat_exchanger_eur_per_a=annuity_hx,
        annuity_connection_pipes_eur_per_a=annuity_pipes, annuity_capital_eur_per_a=annuity_capital,
        opex_fixed_eur_per_a=opex_fixed, opex_electricity_doublet_pump_eur_per_a=opex_doublet_pump,
        opex_electricity_dh_pumping_eur_per_a=opex_dh_pumping, opex_auxiliary_heat_eur_per_a=opex_aux,
        annualised_cost_total_eur_per_a=total, annual_total_heat_delivered_kwh=annual_kwh,
        indicative_lcoh_eur_per_kwh=total / annual_kwh,
        baseline_annualised_cost_total_eur_per_a=baseline_economics.annualised_cost_total_eur_per_a,
        baseline_opex_electricity_dh_pumping_eur_per_a=baseline_economics.opex_electricity_dh_pumping_eur_per_a,
        annualised_cost_delta_eur_per_a=total - baseline_economics.annualised_cost_total_eur_per_a,
        opex_electricity_dh_pumping_delta_eur_per_a=opex_dh_pumping - baseline_economics.opex_electricity_dh_pumping_eur_per_a,
        created_at=created_at,
    )
