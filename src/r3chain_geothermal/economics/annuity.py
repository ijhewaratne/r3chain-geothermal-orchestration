"""Pure VDI-2067-style annuity (capital-recovery) formula (T2.4A, plan §12.2).

Deliberately the SIMPLE single-investment case only -- no price-dynamic
escalation extension (VDI 2067's own b-factor): no escalation-rate
assumptions exist anywhere in config/demo_assumptions.json, and
implementation plan §12.2 does not call for one. Reimplemented
independently in this project's own pure-function style rather than
imported from repos/pandapipesAI/pandapipesai/special_modules/costing/economics.py
-- that module's `annuity_factor()` is mathematically identical, but this
project's established discipline (T1.5B/T2.1/T2.2B/T2.3) is to reuse the
PATTERN, never the cross-repo import, since repos/pandapipesAI is a
read-only reference checkout, not a dependency of this package.
"""
from __future__ import annotations


def annuity_factor(interest_rate: float, useful_life_years: float) -> float:
    """VDI 2067 Kapitalwiedergewinnungsfaktor (capital-recovery factor):

        a = i(1+i)^n / ((1+i)^n - 1),   i = interest_rate,   n = useful_life_years

    At interest_rate == 0 this is the 0/0-indeterminate limit case,
    defined directly as a = 1/n (VDI 2067's own convention).

    Args:
        interest_rate: real interest rate, e.g. 0.03 for 3%. Must be >= 0.
        useful_life_years: asset useful life in years. Must be > 0.

    Raises:
        ValueError: interest_rate < 0, or useful_life_years <= 0.
    """
    if useful_life_years <= 0:
        raise ValueError(f"useful_life_years must be > 0, got {useful_life_years!r}")
    if interest_rate < 0:
        raise ValueError(f"interest_rate must be >= 0, got {interest_rate!r}")
    if interest_rate == 0:
        return 1.0 / useful_life_years
    q = 1.0 + interest_rate
    q_n = q ** useful_life_years
    return interest_rate * q_n / (q_n - 1.0)
