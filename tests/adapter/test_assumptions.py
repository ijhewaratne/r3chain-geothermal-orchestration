"""Tests for CouplingAssumptions (T2.1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.adapter import CouplingAssumptions

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "demo_assumptions.json"


def _load_config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def test_from_config_dict_reads_real_config():
    config = _load_config()
    assert config["_meta"]["schema_version"] == "0.7"
    assumptions = CouplingAssumptions.from_config_dict(config)
    assert assumptions.dh_supply_temperature_c == 70.0
    assert assumptions.dh_return_temperature_c == 40.0
    assert assumptions.minimum_hx_approach_k == 5.0
    assert assumptions.hx_heat_delivery_factor == 0.98
    assert assumptions.reinjection_minimum_temperature_c == 35.0
    assert assumptions.dh_water_specific_heat_capacity_j_kg_k == 4180.0
    assert assumptions.energy_consistency_tolerance_fraction == 0.02


def test_from_config_dict_does_not_read_any_file():
    """Pure function: passing a hand-built dict must work identically to
    passing the real loaded config -- no hidden file I/O."""
    config = {
        "coupling_assumptions": {
            "dh_supply_temperature_c": 70.0, "dh_return_temperature_c": 40.0,
            "minimum_hx_approach_k": 5.0, "hx_heat_delivery_factor": 0.98,
            "reinjection_minimum_temperature_c": 35.0,
            "dh_water_specific_heat_capacity_j_kg_k": 4180.0,
        },
        "pydoublet": {"energy_consistency_tolerance_fraction": 0.02},
    }
    assumptions = CouplingAssumptions.from_config_dict(config)
    assert assumptions.dh_supply_temperature_c == 70.0


def test_model_is_frozen():
    assumptions = CouplingAssumptions.from_config_dict(_load_config())
    with pytest.raises(Exception):
        assumptions.dh_supply_temperature_c = 999.0  # type: ignore[misc]


def test_forbids_extra_fields():
    with pytest.raises(ValidationError):
        CouplingAssumptions(
            dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0,
            minimum_hx_approach_k=5.0, hx_heat_delivery_factor=0.98,
            reinjection_minimum_temperature_c=35.0,
            dh_water_specific_heat_capacity_j_kg_k=4180.0,
            energy_consistency_tolerance_fraction=0.02,
            extra_field="not allowed",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize("bad_factor", [0.0, -0.1, 1.1, 2.0])
def test_hx_heat_delivery_factor_out_of_range_rejected(bad_factor):
    with pytest.raises(ValidationError):
        CouplingAssumptions(
            dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0,
            minimum_hx_approach_k=5.0, hx_heat_delivery_factor=bad_factor,
            reinjection_minimum_temperature_c=35.0,
            dh_water_specific_heat_capacity_j_kg_k=4180.0,
            energy_consistency_tolerance_fraction=0.02,
        )


def test_hx_heat_delivery_factor_of_exactly_one_is_allowed():
    assumptions = CouplingAssumptions(
        dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0,
        minimum_hx_approach_k=5.0, hx_heat_delivery_factor=1.0,
        reinjection_minimum_temperature_c=35.0,
        dh_water_specific_heat_capacity_j_kg_k=4180.0,
        energy_consistency_tolerance_fraction=0.02,
    )
    assert assumptions.hx_heat_delivery_factor == 1.0


def test_dh_supply_not_greater_than_return_is_rejected():
    with pytest.raises(ValidationError):
        CouplingAssumptions(
            dh_supply_temperature_c=40.0, dh_return_temperature_c=40.0,
            minimum_hx_approach_k=5.0, hx_heat_delivery_factor=0.98,
            reinjection_minimum_temperature_c=35.0,
            dh_water_specific_heat_capacity_j_kg_k=4180.0,
            energy_consistency_tolerance_fraction=0.02,
        )


def test_negative_minimum_hx_approach_is_rejected():
    with pytest.raises(ValidationError):
        CouplingAssumptions(
            dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0,
            minimum_hx_approach_k=-1.0, hx_heat_delivery_factor=0.98,
            reinjection_minimum_temperature_c=35.0,
            dh_water_specific_heat_capacity_j_kg_k=4180.0,
            energy_consistency_tolerance_fraction=0.02,
        )


@pytest.mark.parametrize("bad_cp", [0.0, -100.0])
def test_non_positive_dh_specific_heat_capacity_is_rejected(bad_cp):
    with pytest.raises(ValidationError):
        CouplingAssumptions(
            dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0,
            minimum_hx_approach_k=5.0, hx_heat_delivery_factor=0.98,
            reinjection_minimum_temperature_c=35.0,
            dh_water_specific_heat_capacity_j_kg_k=bad_cp,
            energy_consistency_tolerance_fraction=0.02,
        )


@pytest.mark.parametrize("bad_tolerance", [0.0, -0.01])
def test_non_positive_energy_consistency_tolerance_is_rejected(bad_tolerance):
    with pytest.raises(ValidationError):
        CouplingAssumptions(
            dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0,
            minimum_hx_approach_k=5.0, hx_heat_delivery_factor=0.98,
            reinjection_minimum_temperature_c=35.0,
            dh_water_specific_heat_capacity_j_kg_k=4180.0,
            energy_consistency_tolerance_fraction=bad_tolerance,
        )
