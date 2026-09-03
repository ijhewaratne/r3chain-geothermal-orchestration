# Issue: self-consistent district-heating flow sizing and stabilization-margin sensitivity (DSP-005, DSP-006)

**Status**: **implemented** (2026-09-03, `feature/config-gates-dispatch-policy`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 3 / Workstream E, DSP-005/DSP-006 only —
DSP-001..004 were implemented separately, see `docs/issues/config-gates-and-shortfall-policy.md`).
See `docs/decisions/decision-register.md` (IMPL-008) for the design decisions made while
implementing this.

## Problem

`network/candidate.py::_compute_injected_mass_flow_kg_s()` has always sized the geothermal
injection branch's mass flow from the DESIGN return temperature
(`coupling_input.assumptions.dh_return_temperature_c`, 40 °C), not the network's own solved return
temperature at the injection interface. The module's own docstring already documented the
consequence: at the canonical worked case and margin, the network actually solves to a 36.00 °C
return (not 40 °C), so the injection branch's achieved outlet temperature undershoots the 70 °C DH
design supply temperature by roughly 4 K. DSP-005 asked for a bounded, deterministic mechanism to
resize the injection flow against the network's own solved state instead of the fixed design
assumption; DSP-006 asked for a documented sensitivity comparison of the existing 1% stabilization
margin (`minimum_auxiliary_circulation_fraction`) against lower/higher values.

## Method: bisection, not the literally-worded fixed-point iteration

DSP-005 point 5 reads "apply relaxation if required," suggesting a damped fixed-point update
(`m_next = m + relax*(Q/(cp*(T_supply - T_return_solved(m))) - m)`). This was implemented and
tested FIRST, with `relax` swept at 1.0 (undamped) down to 0.05. It diverges at every value tested.
Direct measurement (holding `injected_kw` fixed at the canonical 3168.0 kW and scanning mass flow
directly, bypassing the iteration) revealed why:

| mass flow (kg/s) | solved return (°C) | achieved outlet (°C) |
|---:|---:|---:|
| 20.0 | 68.55 | 106.23 |
| 24.0 | 64.83 | 96.26 |
| 25.0 | 54.32 | 84.55 |
| **25.2632 (design guess)** | **36.00** | **65.97** |
| 25.5 | — | *hydraulically infeasible* (main-pump direction-change conflict) |
| ≥ 25.5 | — | *hydraulically infeasible* |

The design-temperature guess (25.2632 kg/s) sits essentially AT the edge of the hydraulically
feasible range for this candidate/margin combination — consistent with
`minimum_auxiliary_circulation_fraction`'s own documented purpose (module docstring,
"Curtailment"). The map from mass flow to solved return temperature is extremely steep in the last
~1% below that edge (36.00 °C to 54.32 °C over a 1% change in flow), which is exactly why a
fixed-point substitution on the raw target value overshoots catastrophically regardless of damping
— the update formula's own sensitivity, not insufficient relaxation, was the problem.

DSP-005 itself permits an alternative: point 5 says "a bounded deterministic iteration **or root
solve**." The achieved-outlet-temperature deviation `f(m) = achieved_outlet_c(m) - dh_supply_c` is
empirically monotonic (decreasing in `m`) across the feasible range, so
`_solve_self_consistent_injection()` instead:

1. Solves once at the design-temperature guess (the upper bracket bound). If already within
   tolerance, returns immediately — a candidate needing no correction costs exactly one solve,
   identical to `"fixed_design_temperature"`.
2. Otherwise repeatedly shrinks a lower bound (`SELF_CONSISTENT_FLOW_BRACKET_SHRINK_FACTOR = 0.5`
   per step) until `f` changes sign, bracketing a root.
3. Bisects within that bracket until both `SELF_CONSISTENT_FLOW_OUTLET_TEMPERATURE_TOLERANCE_K`
   (0.05 K) and `SELF_CONSISTENT_FLOW_MASS_FLOW_RESIDUAL_TOLERANCE_FRACTION` (1e-4, the bracket
   width relative to the midpoint) are met.

Measured: converges in **16 solves** for the golden case (all four candidates, canonical margin) —
comfortably under `SELF_CONSISTENT_FLOW_MAX_ITERATIONS = 40`. Final mass flow 25.2331 kg/s (vs.
the 25.2632 kg/s design guess), final deviation ≈0.012 K (vs. the ~-4.03 K undershoot under
`"fixed_design_temperature"`).

## DSP-006 sensitivity findings

Measured at candidate C1, sweeping `minimum_auxiliary_circulation_fraction` ×
`injection_sizing_policy`:

| margin | `fixed_design_temperature` | `self_consistent` |
|---:|---|---|
| 0% | `GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT` | `GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT` |
| 0.5% | `CONSUMER_TEMPERATURE_NOT_MET` | feasible (16 iterations, dev ≈0.023 K) |
| 1% (canonical) | feasible (1 solve, dev ≈-4.03 K) | feasible (16 iterations, dev ≈0.012 K) |
| 2% | feasible (1 solve, dev ≈-1.89 K) | feasible (16 iterations, dev ≈0.006 K) |

This cleanly separates the module docstring's two previously-conflated reasons for the 1% margin
(DSP-004's requirement): self-consistent sizing **rescues** reason 2 (the achieved-outlet
undershoot causing `CONSUMER_TEMPERATURE_NOT_MET` at 0.5%) but does **not** rescue reason 1 (the
pandapipes main-pump direction-change conflict at 0%, which is a pure hydraulic/mass-balance
constraint independent of how precisely the injection outlet hits its design temperature).

**Per DSP-006's explicit instruction** ("retain the existing policy only as an explicit,
configurable fallback until the self-consistent method proves it can safely reach higher
geothermal fractions... do not silently select a new physical policy from numerical convenience"):
this finding is reported, not acted on. `config/demo_assumptions.json`'s canonical
`minimum_auxiliary_circulation_fraction` (1%) and `injection_sizing_policy` (absent →
`"fixed_design_temperature"`) are both **unchanged**. Whether to adopt a lower margin and/or
`"self_consistent"` sizing as the new canonical default is a domain-owner decision (Tanja), not
made here.

## Implemented

- `GeothermalInjectionPolicy.injection_sizing_policy: Literal["fixed_design_temperature",
  "self_consistent"] = "fixed_design_temperature"` (`network/candidate.py`) — read via
  `coupling.get(...)`, not `coupling[...]`, so its absence from the canonical config is
  byte-for-byte equivalent to the field not existing (`config_sha256`/`run_id` untouched).
- `_solve_self_consistent_injection()` — the bisection root solve described above.
- `SelfConsistentFlowDiagnostics` (`enabled`, `converged`, `iteration_count`,
  `initial_mass_flow_kg_s`, `final_mass_flow_kg_s`, `final_outlet_temperature_deviation_k`,
  tolerances, `max_iterations`) on every `CandidateEvaluationResult` as `flow_solver` — DSP-005's
  required iteration record, present (with trivial single-solve values) under
  `"fixed_design_temperature"` too, so the result shape never depends on which policy produced it.
- `CandidateFailureCode.SELF_CONSISTENT_FLOW_NOT_CONVERGED` — raised only when
  `SELF_CONSISTENT_FLOW_MAX_ITERATIONS` is exhausted (no bracket found, or bisection did not meet
  both tolerances in budget); never raised under the default policy.
- Model-level invariants: `flow_solver`'s own fields are cross-checked against
  `geothermal_injection_outlet_temperature_deviation_k` and recomputed where possible; the
  pre-existing `district_heating_water_mass_flow_injected_kg_s` invariant was made
  policy-conditional (it must match the design formula under `"fixed_design_temperature"`, or
  `flow_solver.final_mass_flow_kg_s` exactly under `"self_consistent"` — checking the wrong one
  would defeat the purpose of self-consistent sizing).

## Scientific-identity impact (GOV-004)

`CANDIDATE_CONTRACT_SCHEMA_VERSION` bumped `1.1.0` → `1.2.0` (two new fields on
`CandidateEvaluationResult`/`GeothermalInjectionPolicy`, both embedded in the audited
`workflow_result.json`). This moved `bundle_scientific_sha256` for the canonical golden run again
(`fd1e3408cbccfeb81d2847a60d809c2c8e407fb26de4738a624cb28ad00456f6` →
`f85243d16a6e43365f12081a6af346d2ea1aa5bbb51a70f760404eb64a1188a1`, updated in the same three
pinned tests as the CFG-003 rebaseline). It did **not** change `run_id`
(`r3chain-run-93d41133daa11d1a` — unaffected, and additionally unaffected here because
`config/demo_assumptions.json`'s raw bytes were not touched at all: the new policy field is
opt-in-only via `.get()`) and did **not** change any canonical C1-C4 KPI, feasibility, or
LCOH-ranking value (canonical policy stays `"fixed_design_temperature"`, reproducing the exact
pre-DSP-005 single-solve behavior and its historically-documented ~-4 K deviation) — re-verified
live by the same tests that assert the rebaselined hash.

## Tests

`tests/network/test_candidate.py`: policy acceptance/rejection for the new field;
`test_fixed_design_temperature_mode_has_trivial_flow_solver_diagnostics`;
`test_self_consistent_mode_converges_for_all_four_candidates` (parametrized C1-C4);
`test_self_consistent_mode_achieves_much_smaller_outlet_deviation_than_fixed_design_temperature`;
`test_self_consistent_flow_not_converged_via_monkeypatched_max_iterations`;
`test_dsp006_stabilization_margin_sensitivity` (the documented 4-margin × 2-mode sweep, asserting
the exact table above); `test_all_ten_failure_codes_reachable`; a new parametrized case in
`test_strict_json_round_trip_for_failure_codes`. Full offline suite: 903 collected, 902 passed, 1
failed (`test_real_server_process_cleans_up_its_temp_directory_on_sigterm`, a pre-existing
subprocess-timing test unrelated to this change — confirmed to pass in isolation both before and
after this work; flaky under concurrent system load, not a regression).

## Not covered by this issue

- No change to the canonical default policy or margin — that decision remains with Tanja per
  DSP-006's own instruction.
- Workstream F (FAIL-001..004, the intentionally infeasible demonstration candidate) is not part
  of this issue.
