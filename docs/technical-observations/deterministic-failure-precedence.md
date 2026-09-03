# Deterministic technical-gate failure precedence

`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` CFG-004 defines the exact evaluation order for
every technical gate this project enforces. This note exists to make that precedence findable in
one place, cross-referenced to its actual implementation and test coverage, per Phase 1.4 of that
same specification (a second-pass audit flagged a concern that a specific extreme-demand test case
might non-deterministically receive `PRESSURE_LIMIT_EXCEEDED` instead of the expected
`THERMAL_PIPEFLOW_NOT_CONVERGED`).

## The order (CFG-004, as implemented)

For a candidate evaluation (`network/candidate.py::evaluate_candidate()`), after the geothermal
injection branch is constructed:

1. Sequential thermo-hydraulic pipeflow convergence (`THERMAL_PIPEFLOW_NOT_CONVERGED` /
   `GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT`) — checked first; nothing below is ever reached
   unless pandapipes itself reports a converged solution.
2. Delivered-heat/capacity gate under `strict_infeasible` only (`GEOTHERMAL_HEAT_SHORTFALL`).
3. Consumer-temperature gate (`CONSUMER_TEMPERATURE_NOT_MET`).
4. Absolute-pressure gate (`PRESSURE_LIMIT_EXCEEDED`).
5. Pump differential-pressure gate (`PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED`).
6. Pipe-velocity gate (`VELOCITY_LIMIT_EXCEEDED`).
7. Mass-balance gate (`MASS_BALANCE_FAILED`).
8. Physical-energy-balance gate (`ENERGY_BALANCE_FAILED`).

The baseline evaluator (`network/baseline.py::run_baseline_evaluation()`) follows the same relative
order for the gates it applies (1, 3, 4, 5, 6, 7, 8 — it has no geothermal injection branch, so gate
2 does not apply).

**The first gate that fails is the one reported.** A scenario that would ALSO violate a later gate
(e.g. an extreme demand that would eventually blow both convergence and pressure limits) is never
double-reported — only the first, deterministic failure in the list above is returned, and no
later gate is even evaluated.

## The specific concern: extreme consumer demand (`consumer_1 = 1e9` kW)

`tests/network/test_baseline.py`'s `_FAILURE_SCENARIOS[BaselineFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED]`
sets one consumer's demand to `1e9` kW (roughly a million times the design value) specifically to
force pandapipes' own sequential solver to fail to converge at all — gate 1 above, the very first
one checked, so no other gate's numeric behaviour is even relevant to this test's outcome. Verified
directly in this session (macOS ARM64, Python 3.11.16, pandapipes 0.14.0, numpy 2.4.6, scipy
1.16.3): this test passes reliably, including across a genuinely clean from-scratch virtual
environment separate from any pre-existing development environment, and across multiple repeated
runs. The reported "may expect X but receive Y" concern was not reproduced on this platform/
dependency combination.

**Why this could still differ on another platform, honestly stated:** whether an extreme,
deliberately-pathological linear system reports outright non-convergence (`PipeflowNotConverged`,
mapped to gate 1) versus converging to a numerically valid but physically absurd state that then
fails a LATER gate (e.g. an absurd pressure) is a property of the underlying sparse solver's own
numerical behaviour at an extreme, out-of-design operating point — not a property this project's
own gate-ordering code controls. If a different BLAS/LAPACK/scipy combination is ever found to
converge where this one does not, the deterministic FIX is not to weaken or relax the gate that
fires instead (CLAUDE.md, and this specification's own non-negotiable rules, both prohibit that) --
it is to choose an even more extreme, more robustly-non-convergent demand value for that specific
test scenario, re-verified empirically on the platform(s) where the change is needed, with the
before/after evidence recorded here.

## Cross-reference

- `network/errors.py` — `BaselineFailureCode`/`CandidateFailureCode`, both fully documented with
  which CFG-004 gate number each corresponds to.
- `network/baseline.py::run_baseline_evaluation()` / `network/candidate.py::evaluate_candidate()`
  — the actual gate-order implementation (reordered explicitly during the config-gates-and-
  shortfall-policy work — see `docs/issues/config-gates-and-shortfall-policy.md`).
- `tests/network/test_baseline.py::_FAILURE_SCENARIOS`,
  `tests/network/test_candidate.py::test_all_ten_failure_codes_reachable` — one dedicated,
  independently-verified reachability test per failure code, run on every full-suite execution.
