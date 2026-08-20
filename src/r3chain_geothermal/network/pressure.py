"""Gauge <-> absolute pressure conversion (T2.2).

Verified directly against the installed pandapipes 0.14.0 source (not
assumed): `res_junction.p_bar` (the PINIT state variable) is GAUGE pressure,
relative to atmosphere -- NOT absolute. Proof: pandapipes' own
`create_compressor` component computes a genuinely absolute pressure by
explicitly ADDING a separate per-node PAMB field (a barometric-formula
ambient pressure, seeded from pandapipes' own `NORMAL_PRESSURE = 1.01325`
bar constant) to PINIT -- meaning PINIT alone excludes that offset.
Confirmed experimentally: an ext_grid set to p_bar=5 produces
res_junction.p_bar == 5.0 with no atmospheric offset applied anywhere in an
ordinary hydraulic solve (see tests/network/test_pressure_semantics.py).

Every `_bar_abs`-suffixed value in config/demo_assumptions.json is
converted to gauge with to_gauge_bar() BEFORE being passed into any
pandapipes create_* call, and every res_junction.p_bar is converted back to
absolute with to_absolute_bar() BEFORE being compared against a `_bar_abs`
gate or reported as a KPI. Raw gauge values must never be compared directly
against a `_bar_abs` config value anywhere in this project.
"""
from __future__ import annotations

ATMOSPHERIC_PRESSURE_BAR = 1.01325
"""Matches pandapipes' own NORMAL_PRESSURE constant
(pandapipes/constants.py: "pressure under normal conditions (at sea level)
in bar") -- not an independently invented number."""


def to_absolute_bar(gauge_bar: float) -> float:
    """Convert a pandapipes-reported gauge pressure to absolute."""
    return gauge_bar + ATMOSPHERIC_PRESSURE_BAR


def to_gauge_bar(absolute_bar: float) -> float:
    """Convert an absolute (`_bar_abs`) config value to the gauge value
    pandapipes' create_* functions expect."""
    return absolute_bar - ATMOSPHERIC_PRESSURE_BAR
