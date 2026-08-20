"""CouplingAssumptions -- the explicit, typed set of coupling-boundary
policy values the heat-exchanger adapter (T2.1) consumes.

Deliberately mirrors T1.5B's approved no-runtime-config-dependency design
(see r3chain_geothermal.parsers.pydoublet_parser's _ParserPolicy docstring):
the adapter never reads config/demo_assumptions.json from disk itself --
the package must remain importable and usable from a wheel installed
outside this repository. CouplingAssumptions.from_config_dict() is a pure
function (dict in, model out, no file I/O) for callers who have already
loaded that config.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class CouplingAssumptions(BaseModel):
    """Coupling-boundary policy assumptions for one heat-exchanger
    evaluation. All values are provisional demo_assumption values (see
    config/demo_assumptions.json::coupling_assumptions) -- not claimed
    engineering standards.

    Args:
        dh_supply_temperature_c: District-heating supply temperature.
        dh_return_temperature_c: District-heating return temperature.
        minimum_hx_approach_k: Minimum heat-exchanger pinch/approach
            temperature difference.
        hx_heat_delivery_factor: Fractional heat-delivery efficiency applied
            to the temperature-limited deliverable heat, in (0, 1].
        reinjection_minimum_temperature_c: The adapter's policy floor on how
            cold the brine may leave the surface heat exchanger --
            independent of what any specific PyDoublet run itself assumed
            for its own heat-exchanger exit temperature (that is a separate
            quantity, PyDoubletCouplingResult.geothermal_brine_hx_outlet_temperature_c,
            used only for the raw energy-consistency check). Provisional
            pending Phase-0 Q3.
        dh_water_specific_heat_capacity_j_kg_k: Specific heat capacity of
            DH-side water, in J/(kg*K) -- kept in the same SI base unit as
            geothermal_brine_specific_heat_capacity_j_kg_k for consistency.
        energy_consistency_tolerance_fraction: Relative tolerance for the
            raw energy-consistency check (plan §9.2).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    dh_supply_temperature_c: float
    dh_return_temperature_c: float
    minimum_hx_approach_k: float
    hx_heat_delivery_factor: float
    reinjection_minimum_temperature_c: float
    dh_water_specific_heat_capacity_j_kg_k: float
    energy_consistency_tolerance_fraction: float

    @model_validator(mode="after")
    def _validate_assumptions(self) -> "CouplingAssumptions":
        errors: list[str] = []
        if not (0.0 < self.hx_heat_delivery_factor <= 1.0):
            errors.append(
                f"hx_heat_delivery_factor must be in (0, 1], got {self.hx_heat_delivery_factor!r}"
            )
        if self.dh_supply_temperature_c <= self.dh_return_temperature_c:
            errors.append(
                "dh_supply_temperature_c must be strictly greater than "
                f"dh_return_temperature_c (got {self.dh_supply_temperature_c!r} <= "
                f"{self.dh_return_temperature_c!r})"
            )
        if self.minimum_hx_approach_k < 0:
            errors.append(f"minimum_hx_approach_k must be >= 0, got {self.minimum_hx_approach_k!r}")
        if self.dh_water_specific_heat_capacity_j_kg_k <= 0:
            errors.append(
                "dh_water_specific_heat_capacity_j_kg_k must be > 0, got "
                f"{self.dh_water_specific_heat_capacity_j_kg_k!r}"
            )
        if self.energy_consistency_tolerance_fraction <= 0:
            errors.append(
                "energy_consistency_tolerance_fraction must be > 0, got "
                f"{self.energy_consistency_tolerance_fraction!r}"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @classmethod
    def from_config_dict(cls, config: dict[str, Any]) -> "CouplingAssumptions":
        """Construct from an already-loaded config/demo_assumptions.json
        dict (schema >= 0.6). Pure function -- does not read any file."""
        coupling = config["coupling_assumptions"]
        pydoublet = config["pydoublet"]
        return cls(
            dh_supply_temperature_c=coupling["dh_supply_temperature_c"],
            dh_return_temperature_c=coupling["dh_return_temperature_c"],
            minimum_hx_approach_k=coupling["minimum_hx_approach_k"],
            hx_heat_delivery_factor=coupling["hx_heat_delivery_factor"],
            reinjection_minimum_temperature_c=coupling["reinjection_minimum_temperature_c"],
            dh_water_specific_heat_capacity_j_kg_k=coupling["dh_water_specific_heat_capacity_j_kg_k"],
            energy_consistency_tolerance_fraction=pydoublet["energy_consistency_tolerance_fraction"],
        )
