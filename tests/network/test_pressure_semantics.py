"""Pins pandapipes' pressure semantics (T2.2, plan §1) against the real,
installed pandapipes library -- not assumed. This is the "Sprint-2 unit
test" that config/demo_assumptions.json's gates._note anticipated: proving
gauge-vs-absolute before any pressure gate is applied.
"""
from __future__ import annotations

import pytest

from r3chain_geothermal.network.pressure import ATMOSPHERIC_PRESSURE_BAR, to_absolute_bar, to_gauge_bar


def test_pandapipes_ext_grid_pressure_is_reported_as_gauge_not_absolute():
    """A trivial one-pipe network with a known ext_grid pressure: if
    pandapipes reported ABSOLUTE pressure, res_junction.p_bar at the
    ext_grid node would differ from the raw input by ~1 bar (the
    atmospheric offset). It does not -- proving gauge."""
    pandapipes = pytest.importorskip("pandapipes")

    net = pandapipes.create_empty_network(fluid="water")
    j1 = pandapipes.create_junction(net, pn_bar=5.0, tfluid_k=320.0)
    j2 = pandapipes.create_junction(net, pn_bar=5.0, tfluid_k=320.0)
    pandapipes.create_ext_grid(net, j1, p_bar=5.0, t_k=320.0)
    pandapipes.create_sink(net, j2, mdot_kg_per_s=1.0)
    pandapipes.create_pipe_from_parameters(net, j1, j2, length_km=0.1, inner_diameter_mm=100.0)

    pandapipes.pipeflow(net, mode="hydraulics")

    assert net.converged
    reported_p_bar = net.res_junction.loc[j1, "p_bar"]
    # If this were absolute, reported_p_bar would be ~5 + 1.01325 = 6.01325.
    assert reported_p_bar == pytest.approx(5.0, abs=1e-6)
    assert reported_p_bar != pytest.approx(5.0 + ATMOSPHERIC_PRESSURE_BAR, abs=1e-3)


def test_to_absolute_bar_matches_atmospheric_offset():
    gauge_reading = 5.0  # what the test above proved pandapipes reports
    assert to_absolute_bar(gauge_reading) == pytest.approx(5.0 + 1.01325)


def test_to_gauge_bar_is_the_inverse_conversion():
    absolute_config_value = 6.0  # e.g. network.p_supply_bar_abs
    gauge_for_pandapipes = to_gauge_bar(absolute_config_value)
    assert gauge_for_pandapipes == pytest.approx(6.0 - 1.01325)


@pytest.mark.parametrize("value", [0.0, 1.0, 5.0, 6.0, -1.01325, 100.0])
def test_gauge_absolute_round_trip(value):
    assert to_gauge_bar(to_absolute_bar(value)) == pytest.approx(value)
    assert to_absolute_bar(to_gauge_bar(value)) == pytest.approx(value)


def test_atmospheric_pressure_constant_matches_pandapipes_own_normal_pressure():
    """The conversion constant is not independently invented -- it must
    equal pandapipes' own NORMAL_PRESSURE constant (constants.py)."""
    pandapipes = pytest.importorskip("pandapipes")
    from pandapipes.constants import NORMAL_PRESSURE

    assert ATMOSPHERIC_PRESSURE_BAR == pytest.approx(NORMAL_PRESSURE)
