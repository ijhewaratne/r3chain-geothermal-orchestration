"""Full test matrix for economics/annuity.py -- the T2.4A VDI-2067-style
capital-recovery factor."""
from __future__ import annotations

import math

import pytest

from r3chain_geothermal.economics.annuity import annuity_factor


def test_matches_hand_computed_value_at_known_rate_and_life():
    # a = i(1+i)^n / ((1+i)^n - 1), i=0.03, n=30
    i, n = 0.03, 30.0
    expected = i * (1 + i) ** n / ((1 + i) ** n - 1)
    assert math.isclose(annuity_factor(i, n), expected, rel_tol=1e-12)


@pytest.mark.parametrize("rate,life,expected", [
    (0.03, 30.0, 0.05101925932025256),
    (0.03, 20.0, 0.06721570759685909),
    (0.05, 30.0, 0.06505143508027657),
])
def test_matches_known_reference_values(rate, life, expected):
    assert math.isclose(annuity_factor(rate, life), expected, rel_tol=1e-9)


def test_zero_interest_rate_uses_limit_case():
    assert annuity_factor(0.0, 25.0) == pytest.approx(1.0 / 25.0, rel=1e-12)


def test_rejects_non_positive_useful_life():
    with pytest.raises(ValueError):
        annuity_factor(0.03, 0.0)
    with pytest.raises(ValueError):
        annuity_factor(0.03, -5.0)


def test_rejects_negative_interest_rate():
    with pytest.raises(ValueError):
        annuity_factor(-0.01, 30.0)


def test_longer_life_gives_smaller_factor_at_fixed_rate():
    assert annuity_factor(0.03, 40.0) < annuity_factor(0.03, 20.0)


def test_higher_rate_gives_larger_factor_at_fixed_life():
    assert annuity_factor(0.05, 30.0) > annuity_factor(0.02, 30.0)
