# Technical observation — `FluidPropertyInterExtra.get_at_integral_value()` defect

- **Status:** Confirmed defect in the observed version. Not filed upstream
  (out of scope for this project). This project works around it by never
  calling the affected method — see "Consequence" below.
- **Found during:** T2.2B's energy-balance correction (the physical-vs-
  reporting-convention investigation).
- **Package/version:** `pandapipes==0.14.0` (PyPI), installed in
  `.venvs/orchestration` and `.venvs/pandapipesai`. **Version-specific** —
  this observation applies to 0.14.0 as installed; a future `0.14.x` or
  later release may fix it (see "Re-verification" below).

## Source expression and location

`pandapipes/properties/fluids.py`, `FluidPropertyInterExtra.get_at_integral_value()`:

```python
def get_at_integral_value(self, upper_limit_arg, lower_limit_arg):
    mean = (self.prop_getter(upper_limit_arg) + self.prop_getter(upper_limit_arg)) / 2
    return mean * (upper_limit_arg - lower_limit_arg)
```

`self.prop_getter(upper_limit_arg)` is evaluated **twice** — the second
occurrence should be `self.prop_getter(lower_limit_arg)`. As written, `mean`
always equals `self.prop_getter(upper_limit_arg)` exactly (averaging a value
with itself), so the method silently returns
`cp(T_upper) * (T_upper - T_lower)` — a one-sided rectangle-rule estimate
using only the upper endpoint — never a trapezoid, regardless of how far
`T_lower` is from `T_upper`.

## Reproduction (water's `heat_capacity` property, `FluidPropertyInterExtra`)

```python
import pandapipes
net = pandapipes.create_empty_network(fluid="water")
from pandapipes.properties.fluids import get_fluid
prop = get_fluid(net).all_properties["heat_capacity"]

t_lower, t_upper = 313.15, 343.15
cp_lower, cp_upper = prop.get_at_value(t_lower), prop.get_at_value(t_upper)

prop.get_at_integral_value(t_upper, t_lower)   # -> 125709.015
cp_upper * (t_upper - t_lower)                 # -> 125709.015  (matches exactly)
(cp_lower + cp_upper) / 2 * (t_upper - t_lower) # -> 125548.935  (correct single-segment trapezoid, does NOT match)
```

The exact integral (computed by hand from the property table's own node
temperatures at 313/323/333/343 K, since water's `heat_capacity` is
piecewise-linear-interpolated) is `125516.7154` — the buggy method's
`125709.015` differs from it by ~1.5%, and from even the naive single-segment
trapezoid by ~0.13%.

## Consequence for this project

`get_at_value()` (point evaluation, used to fetch `cp(T)` at a single
temperature) is **not** affected — verified separately, matches expected
water heat-capacity values exactly. Only `get_at_integral_value()` is wrong.

This project's `network/baseline.py::_integrate_specific_heat_j_per_kg()`
therefore **never calls `get_at_integral_value()`** — it performs its own
composite trapezoidal integration, sampling only the verified-correct
`get_at_value()`/`get_heat_capacity()` point evaluation. This is enforced by
a structural test
(`tests/network/test_baseline.py::test_evaluator_never_calls_pandapipes_get_at_integral_value`)
that greps the module source for the method name — the test passes whether
or not a given pandapipes version's `get_at_integral_value()` is buggy,
because this project's own correctness never depends on it.

## Re-verification

If pandapipes is upgraded beyond 0.14.0 in the future, re-run the
reproduction snippet above against the new version. If it now returns
`125548.935` (or the version's own correct trapezoid/interpolated value)
rather than `125709.015`, the defect is fixed upstream — this observation
can be closed, though there is no need to change this project's own
integration method (it is correct regardless, and intentionally
independent of pandapipes' helper).

## Status

Confirmed defect in pandapipes 0.14.0. Worked around by non-dependence, not
by waiting for or requiring an upstream fix. No pandapipes source change has
been made or is proposed here (out of scope, and pandapipes is a pinned
third-party dependency, not a repository this project modifies).
