"""EconomicAssumptions -- the explicit, typed set of cost-boundary policy
values the T2.4A candidate economics/ranking layer consumes.

Mirrors adapter.CouplingAssumptions / network.baseline.GateTolerances /
network.candidate.GeothermalInjectionPolicy's established pattern exactly:
frozen, no runtime config-file dependency (from_config_dict() is a pure
function -- dict in, model out, no file I/O, so this package stays
importable from a wheel installed outside this repository), all values
provisional demo_assumption figures (config/demo_assumptions.json::economics),
not claimed engineering/market facts.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class EconomicAssumptions(BaseModel):
    """One cost-boundary assumption snapshot for T2.4A. All values are
    provisional demo_assumption values pending Q7 (cost data source) and
    Q8 (ranking rule) -- see docs/decisions/phase0-questions.md.

    Args:
        interest_rate_real: real (not nominal) calculatory interest rate,
            e.g. 0.03 for 3%/a.
        doublet_lifetime_years, heat_exchanger_lifetime_years,
            connection_pipes_lifetime_years: useful life per asset class --
            annuitized SEPARATELY (different lifetimes give different
            annuity factors), never blended into one factor.
        doublet_capex_eur, heat_exchanger_capex_eur: identical across every
            candidate (same PyDoublet scenario, same coupling result) --
            does not drive relative ranking; see costing.py.
        connection_pipe_capex_eur_per_m: PAIRED-TRENCH metre rate --
            applied once per candidate (surface_connection_length_m used
            as-is, not doubled for the two physical connection pipes).
            See config's own connection_pipe_per_m_note for the full
            resolution.
        fixed_om_fraction_of_capex_per_a: applied to TOTAL CAPEX
            (doublet + heat exchanger + this candidate's connection
            pipes), matching plan §12.2's single fixed-O&M term.
        electricity_price_eur_per_kwh, auxiliary_heat_price_eur_per_kwh:
            first-year prices, no escalation (see module docstring).
        annual_full_load_hours: converts every kW-rate KPI into an annual
            kWh/EUR figure -- a stated single-operating-point
            simplification (see config's own annual_full_load_hours.note).
        dh_pump_efficiency: wire-to-water efficiency converting
            HYDRAULIC pumping power (network.baseline.CirculationPumpResult,
            network.candidate.CandidateEvaluationResult.connection_pumping_power_kw)
            into ELECTRICAL power for costing -- does NOT apply to
            doublet_pump_electric_power_kw, which PyDoublet already
            reports as electrical.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    interest_rate_real: float
    doublet_lifetime_years: float
    heat_exchanger_lifetime_years: float
    connection_pipes_lifetime_years: float
    doublet_capex_eur: float
    heat_exchanger_capex_eur: float
    connection_pipe_capex_eur_per_m: float
    fixed_om_fraction_of_capex_per_a: float
    electricity_price_eur_per_kwh: float
    auxiliary_heat_price_eur_per_kwh: float
    annual_full_load_hours: float
    dh_pump_efficiency: float

    @model_validator(mode="after")
    def _validate_assumptions(self) -> "EconomicAssumptions":
        errors: list[str] = []
        if self.interest_rate_real < 0:
            errors.append(f"interest_rate_real must be >= 0, got {self.interest_rate_real!r}")
        for name in ("doublet_lifetime_years", "heat_exchanger_lifetime_years", "connection_pipes_lifetime_years"):
            value = getattr(self, name)
            if value <= 0:
                errors.append(f"{name} must be > 0, got {value!r}")
        for name in (
            "doublet_capex_eur", "heat_exchanger_capex_eur", "connection_pipe_capex_eur_per_m",
            "fixed_om_fraction_of_capex_per_a", "electricity_price_eur_per_kwh",
            "auxiliary_heat_price_eur_per_kwh",
        ):
            value = getattr(self, name)
            if value < 0:
                errors.append(f"{name} must be >= 0, got {value!r}")
        if self.annual_full_load_hours <= 0 or self.annual_full_load_hours > 8760:
            errors.append(
                f"annual_full_load_hours must be in (0, 8760], got {self.annual_full_load_hours!r}"
            )
        if not (0.0 < self.dh_pump_efficiency <= 1.0):
            errors.append(f"dh_pump_efficiency must be in (0, 1], got {self.dh_pump_efficiency!r}")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @classmethod
    def from_config_dict(cls, config: dict[str, Any]) -> "EconomicAssumptions":
        """Construct from an already-loaded config/demo_assumptions.json
        dict (schema >= 0.9). Pure function -- does not read any file."""
        econ = config["economics"]
        return cls(
            interest_rate_real=econ["interest_rate_real"]["value"],
            doublet_lifetime_years=econ["lifetime_years"]["doublet"]["value"],
            heat_exchanger_lifetime_years=econ["lifetime_years"]["heat_exchanger"]["value"],
            connection_pipes_lifetime_years=econ["lifetime_years"]["connection_pipes"]["value"],
            doublet_capex_eur=econ["capex"]["doublet_capex"]["value"],
            heat_exchanger_capex_eur=econ["capex"]["heat_exchanger_capex"]["value"],
            connection_pipe_capex_eur_per_m=econ["capex"]["connection_pipe_per_m"]["value"],
            fixed_om_fraction_of_capex_per_a=econ["opex"]["fixed_om_fraction_of_capex_per_a"]["value"],
            electricity_price_eur_per_kwh=econ["opex"]["electricity_price"]["value"],
            auxiliary_heat_price_eur_per_kwh=econ["opex"]["auxiliary_heat_price"]["value"],
            annual_full_load_hours=econ["annual_full_load_hours"]["value"],
            dh_pump_efficiency=econ["dh_pump_efficiency"]["value"],
        )
