"""Full test matrix for economics/assumptions.py -- EconomicAssumptions."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.economics import EconomicAssumptions

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _valid(**overrides) -> dict:
    base = dict(
        interest_rate_real=0.03,
        doublet_lifetime_years=30.0, heat_exchanger_lifetime_years=20.0, connection_pipes_lifetime_years=30.0,
        doublet_capex_eur=8_000_000.0, heat_exchanger_capex_eur=150_000.0, connection_pipe_capex_eur_per_m=1000.0,
        fixed_om_fraction_of_capex_per_a=0.02, electricity_price_eur_per_kwh=0.25, auxiliary_heat_price_eur_per_kwh=0.09,
        annual_full_load_hours=5000.0, dh_pump_efficiency=0.70,
    )
    base.update(overrides)
    return base


def test_from_config_dict_reads_real_config():
    config = _config()
    assert config["_meta"]["schema_version"] == "0.9"
    assumptions = EconomicAssumptions.from_config_dict(config)
    assert assumptions.interest_rate_real == 0.03
    assert assumptions.doublet_lifetime_years == 30.0
    assert assumptions.heat_exchanger_lifetime_years == 20.0
    assert assumptions.connection_pipes_lifetime_years == 30.0
    assert assumptions.doublet_capex_eur == 8_000_000.0
    assert assumptions.heat_exchanger_capex_eur == 150_000.0
    assert assumptions.connection_pipe_capex_eur_per_m == 1000.0
    assert assumptions.fixed_om_fraction_of_capex_per_a == 0.02
    assert assumptions.electricity_price_eur_per_kwh == 0.25
    assert assumptions.auxiliary_heat_price_eur_per_kwh == 0.09
    assert assumptions.annual_full_load_hours == 5000.0
    assert math.isclose(assumptions.dh_pump_efficiency, 0.70)


def test_valid_construction_succeeds():
    EconomicAssumptions(**_valid())


def test_rejects_negative_interest_rate():
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(interest_rate_real=-0.01))


@pytest.mark.parametrize("field", ["doublet_lifetime_years", "heat_exchanger_lifetime_years", "connection_pipes_lifetime_years"])
def test_rejects_non_positive_lifetimes(field):
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(**{field: 0.0}))
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(**{field: -5.0}))


@pytest.mark.parametrize("field", [
    "doublet_capex_eur", "heat_exchanger_capex_eur", "connection_pipe_capex_eur_per_m",
    "fixed_om_fraction_of_capex_per_a", "electricity_price_eur_per_kwh", "auxiliary_heat_price_eur_per_kwh",
])
def test_rejects_negative_costs(field):
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(**{field: -1.0}))


@pytest.mark.parametrize("bad_value", [0.0, -100.0, 8761.0])
def test_rejects_out_of_range_annual_full_load_hours(bad_value):
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(annual_full_load_hours=bad_value))


@pytest.mark.parametrize("bad_value", [0.0, -0.1, 1.5])
def test_rejects_out_of_range_dh_pump_efficiency(bad_value):
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(dh_pump_efficiency=bad_value))


def test_rejects_non_finite_values():
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(interest_rate_real=float("nan")))
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(doublet_capex_eur=float("inf")))


def test_model_is_frozen():
    assumptions = EconomicAssumptions(**_valid())
    with pytest.raises(ValidationError):
        assumptions.interest_rate_real = 0.05


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        EconomicAssumptions(**_valid(), unexpected_field=1.0)
