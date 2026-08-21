# Technical observation — `CirculationPump.extract_results()` direction-change check

- **Status:** Confirmed, version-specific solver limitation in pandapipes
  0.14.0 (not a defect in the sense of the heat-capacity-integral
  observation — the check itself is a deliberate correctness guard; the
  limitation is that it has no bypass and an extremely tight tolerance).
  Worked around in this project by construction (a curtailment ceiling
  that keeps the main plant pump's flow away from the edge), not by
  disabling or patching pandapipes.
- **Found during:** T2.3's topology investigation and worked-case
  implementation (independent geothermal candidate evaluator).
- **Package/version:** `pandapipes==0.14.0` (PyPI), installed in
  `.venvs/orchestration` and `.venvs/pandapipesai`. **Version-specific** —
  applies to 0.14.0 as installed; see "Re-verification" below.

## Source expression and location

`pandapipes/component_models/abstract_models/circulation_pump.py`,
`CirculationPump.extract_results()`:

```python
mask = (branch_pit[f:t, MDOTINIT] < 0) & ~np.isclose(branch_pit[f:t, MDOTINIT], 0)
if np.any(mask):
    raise UserWarning(r'Your grid is badly modelled and would lead to a '
                       r'direction change in circulation pump %s' % ...)
```

This runs on the **converged solution** (`extract_all_results()` is only
called after `hydraulics()`/`heat_transfer()` succeed without raising
`PipeflowNotConverged`) — it is not an iteration artifact. It fires
whenever a circulation pump's own solved branch mass flow (`MDOTINIT`) is
negative and not within `numpy.isclose`'s default tolerance of zero
(`rtol=1e-05`, `atol=1e-08`).

## Reproduction

Build the T2.2A/T2.2B default four-consumer blueprint, add the T2.3
geothermal injection branch (`network/candidate.py::_add_geothermal_injection_branch`)
at any candidate's junction pair, and inject a heat amount approaching
100% of the baseline's total consumer demand (3200.0 kW):

```python
# net = build_pandapipes_net(blueprint) + injection branch, various
# injected heat amounts as a fraction of 3200.0 kW baseline demand:
0.990 (3168.0 kW): converges, main pump residual flow = +0.2249 kg/s
0.992 (3174.4 kW): converges, main pump residual flow = +0.1739 kg/s
0.994 (3180.8 kW): converges, main pump residual flow = +0.1228 kg/s
0.995 (3184.0 kW): converges, main pump residual flow = +0.0973 kg/s
0.996 (3187.2 kW): converges, main pump residual flow = +0.0718 kg/s
0.997 (3190.4 kW): converges, main pump residual flow = +0.0463 kg/s
0.998 (3193.6 kW): converges, main pump residual flow = +0.0208 kg/s
0.999 (3196.8 kW): FAILS -- UserWarning('...direction change...')
1.000 (3200.0 kW): FAILS -- UserWarning('...direction change...')
```

Verified at every intermediate value between 0.998 and 1.000 tested
(0.999, 0.9999, 0.99999, 1.0): all fail with the identical `UserWarning`.
The boundary is a genuine, deterministic crossing point for this specific
network/demand combination, not solver noise — `numpy.isclose`'s
`atol=1e-8` is far tighter than any of the residual margins observed at
the passing fractions above, so a candidate that lands the main pump's
flow anywhere near zero (rather than comfortably positive) is at risk.

## Two alternatives tried and rejected before the adopted workaround

1. **Drop the main plant pump entirely once geothermal fully covers
   demand**, replacing it with a bare `ext_grid` at the same junction
   (same pressure/temperature spec). Directly tested: hydraulics converges
   cleanly (no direction-change error, since there is no second circulation
   pump left to check), but the run then **fails at the heat-transfer
   stage** (`PipeflowNotConverged: The heat transfer calculation did not
   converge to a solution.`), both at the exact demand-matching curtailment
   and at the full uncurtailed deliverable value. A bare `ext_grid` fixes
   pressure and temperature only at its own single node; the old
   circulation-pump return-side junction is left without a clear thermal
   boundary condition, and the heat solve becomes ill-posed somewhere in
   the return trunk. Fixing this would need its own separate investigation
   (most likely an explicit thermal boundary at the abandoned return
   junction) — rejected as materially out of scope for a decision that
   needed to be made once, not iterated on.
2. **Treat near-100% coverage as a hard infeasibility** (a dedicated
   failure code, no numerical workaround at all). Rejected because the
   worked case's own geothermal result (~3227.7 kW deliverable vs. 3200.0
   kW baseline demand) sits almost exactly at this boundary — this policy
   would report all four worked candidates (C1–C4) as infeasible, which
   defeats the purpose of the demonstration.

## Adopted workaround

`config/demo_assumptions.json::coupling_assumptions.minimum_auxiliary_circulation_fraction`
(0.01, i.e. 1%) caps injected geothermal heat at `baseline_demand * (1 -
0.01)` = 99% of baseline demand, keeping the main pump's residual flow at
approximately +0.22 kg/s in the worked case — about 2.2×10⁷ times pandapipes'
own `atol=1e-8` tolerance, a comfortable margin against this specific
check. See `network/candidate.py`'s module docstring ("Curtailment") and
`_compute_injected_heat_kw()` for the implementation, and
`PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED` (a `CouplingWarning`
code appended to every affected result) for the audit trail distinguishing
this numerical margin from a genuine physical supply/demand curtailment.

**A second, independently-discovered constraint reinforces (does not
merely coincide with) the same 1% choice.** Sweeping
`minimum_auxiliary_circulation_fraction` below 1% during T2.3's own
sensitivity testing (`tests/network/test_candidate.py::test_sensitivity_below_chosen_value_fails_consumer_temperature_not_pressure`)
reveals a **second, distinct failure mechanism**, unrelated to the
direction-change check above: as the fraction shrinks, the main plant
pump's own share of total network flow shrinks toward zero, so the
network's thermal field becomes increasingly dominated by the geothermal
injection branch's own achieved outlet temperature — which is not exactly
the design DH supply temperature, because
`_compute_injected_mass_flow_kg_s()` sizes the injected mass flow assuming
a fixed temperature rise from the *design* DH return temperature (40 °C),
while the branch's actual inlet temperature is a real mixed-flow solver
result that measurably undershoots 40 °C once the main pump's anchoring
flow shrinks (verified directly: at `minimum_auxiliary_circulation_fraction=0.01`,
`ret_trunk_1` solves to 36.00 °C, not 40.00 °C, and the injection branch's
own outlet — `geo_supply_C1` — solves to 65.97 °C, not the design 70.00 °C).
This under-temperature propagates through the trunk to `consumer_1` (the
plant-nearest consumer) for **every** candidate (C1–C4 alike — the
injected kW/mass-flow amount does not depend on which candidate is being
evaluated, only on the fraction, so all four show identical failure
magnitudes at a given fraction), triggering `CONSUMER_TEMPERATURE_NOT_MET`,
not the direction-change `UserWarning`. Measured boundary (all four
candidates, always at `consumer_1`):

| `minimum_auxiliary_circulation_fraction` | Outcome | `consumer_1` supply-temperature drop |
|---:|---|---:|
| 0.003 | fails, `CONSUMER_TEMPERATURE_NOT_MET` | 19.54 K |
| 0.005 | fails, `CONSUMER_TEMPERATURE_NOT_MET` | 9.27 K |
| 0.0075 | fails, `CONSUMER_TEMPERATURE_NOT_MET` | 5.58 K (just over the 5.0 K gate) |
| 0.01 (chosen) | feasible | 3.99 K (C1) / 4.17 K (C2, C3, C4) |
| 0.02 | feasible | (not the binding constraint at this fraction) |
| 0.05 | feasible | (not the binding constraint at this fraction) |

At the chosen 1% value the margin against `gates.max_consumer_supply_drop_k`
(5.0 K) is real but thin — roughly 0.8–1.0 K of headroom, about 17–20% of
the gate's own budget, not a large safety margin. This is disclosed here
explicitly rather than left implicit in a single passing test.

## Consequence for this project

- `evaluate_candidate()` never attempts to curtail geothermal injection
  all the way to exactly 100% of baseline demand — see
  `network/candidate.py::_compute_injected_heat_kw()`.
- The 1% choice is now known to be justified by **two independent**
  reasons (the direction-change check's near-zero tolerance, and the
  temperature-anchoring effect above), not one — both are cited on the
  relevant config value and in this document, rather than only the first
  reason that was known at the time the value was chosen.
- The temperature-anchoring effect is a genuine limitation of the current
  `_compute_injected_mass_flow_kg_s()` formula (it assumes a fixed design
  return temperature rather than solving self-consistently for the
  network's actual mixed return temperature) — not a pandapipes defect.
  It is documented here because it was discovered *while* investigating
  the pandapipes-specific issue and shares the same practical mitigation
  (keep the margin at or above 1%), but its root cause and its fix (if a
  fix is ever wanted) belong to this project's own code, not to pandapipes.

## Future investigation path

1. **Narrow the true pandapipes boundary further** (this document
   currently brackets it to (0.998, 0.999) coverage for the specific
   worked-case network; a tighter bracket was not pursued once the 1%
   margin was shown to comfortably clear it).
2. **Self-consistent injection-temperature sizing.** Replace
   `_compute_injected_mass_flow_kg_s()`'s fixed-design-return-temperature
   assumption with an iterative or two-pass scheme that sizes the injected
   mass flow against the network's *actual* solved return temperature at
   the candidate's own return junction, which would likely narrow or
   eliminate the temperature-anchoring effect independently of the
   direction-change margin — decoupling the two constraints so each could
   be tuned (or removed) on its own terms. Out of scope for T2.3; flagged
   here as the natural next step if a smaller margin (or a genuinely
   100%-coverage worked case) is ever wanted.
3. **Re-verify both findings on a future pandapipes release.** If a later
   `0.14.x` or newer release changes `CirculationPump.extract_results()`'s
   tolerance or adds a bypass option, re-run this document's reproduction
   steps; the temperature-anchoring effect (item 2) is independent of
   pandapipes' version and would need to be re-verified against this
   project's own formula regardless.

## Status

Confirmed, version-specific pandapipes limitation, worked around by a
documented, typed, auditable config value
(`minimum_auxiliary_circulation_fraction`) — not by patching or monkeying
with pandapipes' own source, which is a pinned third-party dependency, not
a repository this project modifies. The second, independently-discovered
temperature-anchoring effect is a limitation in this project's own
`_compute_injected_mass_flow_kg_s()` formula, documented here for its
shared practical mitigation and flagged above as a candidate for future
work, not fixed in T2.3.
