# Issue: authoritative configuration gates and shortfall policy (CFG-003, DSP-001..004)

**Status**: **implemented** (2026-09-03, `feature/config-gates-dispatch-policy`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 3 / Workstreams D and E, partial —
CFG-001/002/005/006 and DSP-005/006 are addressed separately; see "Not covered by this issue"
below). See `docs/decisions/decision-register.md` (IMPL-007) for the design decisions made while
implementing this.

## Problem

`config/demo_assumptions.json::gates` declared two values that no code path ever consumed:

- `max_pump_dp_bar` (6.0) — the plan's own `network.circulation_pump._note` referenced this value
  when justifying the 3.0 bar pressure-lift choice, but no gate ever checked a solved pump's
  pressure lift against it.
- `heat_delivery_tolerance_fraction` (0.01) — declared, never read anywhere.

Separately, `GeothermalInjectionPolicy.auxiliary_policy` accepted `"strict_infeasible"` as a
config value but its own validator unconditionally rejected it at runtime ("plan §9.5 policy
option not yet built"), so the only working shortfall behavior was the default
`"cost_shortfall"` (auxiliary always covers any shortfall).

## Implemented

- `GateTolerances.max_pump_dp_bar` (`network/baseline.py`): a new gate,
  `PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED`, checked against the main plant circulation pump's solved
  `pressure_lift_bar`. Mirrored in `network/candidate.py` against BOTH the main plant pump and the
  geothermal injection pump (the latter reuses the identical
  `blueprint.circulation_pump.pressure_lift_bar` design value and is likewise a pressure-fixing
  boundary component, so in today's topology it can never fail independently of the main pump's
  own check — kept as defensive/future-proofing, documented in the test that exercises it).
- `GeothermalInjectionPolicy.heat_delivery_tolerance_fraction` (`network/candidate.py`): consumed
  only under `auxiliary_policy == "strict_infeasible"` — a candidate is infeasible
  (`GEOTHERMAL_HEAT_SHORTFALL`) when `coupling_input.deliverable_geothermal_heat_kw` falls short of
  `baseline_total_heat_delivered_kw` by more than this fraction. Never checked under the default
  `"cost_shortfall"` policy, where a shortfall is simply covered by `auxiliary_heat_kw` (DSP-004's
  required separation of resource-limited shortfall from the existing 1%
  `minimum_auxiliary_circulation_fraction` numerical-stabilization margin — the two remain
  independent knobs, never conflated).
- `strict_infeasible` is now a fully supported policy value (previously rejected at validation).
- Gate order (CFG-004): both `network/baseline.py` and `network/candidate.py` reordered their
  existing checks so pump-differential-pressure runs between the pressure gate and the velocity
  gate, matching the spec's declared sequence; the delivered-heat/capacity check runs immediately
  after candidate convergence, before the consumer-temperature gate.
- Config-vocabulary decision (IMPL-007): kept this project's existing `"cost_shortfall"` /
  `"strict_infeasible"` naming rather than renaming to the spec's own `"auxiliary_supply"` —
  functionally identical policy, and renaming the config literal would have changed
  `config_sha256`/`run_id` for the canonical fixture for zero functional gain.

## Scientific-identity impact (GOV-004)

`BASELINE_CONTRACT_SCHEMA_VERSION`/`CANDIDATE_CONTRACT_SCHEMA_VERSION` bumped `1.0.0` → `1.1.0`
(NFR-007): both `GateTolerances` and `GeothermalInjectionPolicy` gained a field, and both are
embedded in the audited `workflow_result.json`. This moved `bundle_scientific_sha256` for the
canonical golden run (`90f52416785f0ea8f7f8dc33ede68c9b5529e6e9d51dd60e8d2e1df0389b8d2f` →
`fd1e3408cbccfeb81d2847a60d809c2c8e407fb26de4738a624cb28ad00456f6`, updated in the three tests that
pin it). It did **not** change `run_id` (`r3chain-run-93d41133daa11d1a` — computed only from raw
input/config bytes, source provenance, and `WORKFLOW_CONTRACT_SCHEMA_VERSION`, none of which
changed) and did **not** change any canonical C1-C4 KPI, feasibility, or LCOH-ranking value (the
canonical pump lift is 3.0 bar, comfortably under the 6.0 bar gate, and the canonical policy stays
`"cost_shortfall"` with a genuine geothermal surplus — the new gates are inert no-ops for the
golden case, re-verified live by the same tests that assert the rebaselined hash).

## Tests

- `tests/network/test_baseline.py`: `max_pump_dp_bar` added to the non-positive/non-finite
  rejection parametrizations; a new parametrized case in
  `test_strict_json_round_trip_for_balance_failure_codes` for
  `PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED`; `test_all_seven_failure_codes_covered` (was "all six").
- `tests/network/test_candidate.py`: `test_all_nine_failure_codes_reachable` (was "all seven");
  `test_pump_differential_pressure_exceeded_via_tight_tolerance`;
  `test_geothermal_heat_shortfall_under_strict_infeasible_policy` (AC-05, using the same
  reduced-resource `hx_heat_delivery_factor=0.3` fixture the existing shortfall test already used);
  `test_geothermal_heat_shortfall_absent_under_cost_shortfall_policy` (AC-04, same fixture, default
  policy stays feasible); `test_policy_accepts_strict_infeasible_auxiliary_policy` (replaces the
  now-inverted `test_policy_rejects_strict_infeasible_auxiliary_policy`);
  `test_policy_rejects_out_of_range_heat_delivery_tolerance_fraction`; two new parametrized cases
  added to `test_strict_json_round_trip_for_failure_codes`.
- Full offline suite: 885 passed (was 875 before this phase), 0 failed, 0 skipped.

## Not covered by this issue

- CFG-001/CFG-002 (full configuration classification ledger and the resolved-vs-source config
  hash-boundary documentation) — the two specific "currently ignored gates" named by CFG-003 are
  closed; a complete field-by-field classification of every config value was not attempted here.
- CFG-005 is already satisfied by the existing `network/pressure.py` gauge/absolute discipline —
  no change needed.
- CFG-006's compatibility/golden test requirement is satisfied by the existing pinned-LCOH
  assertions in `tests/mcp_client/test_wheel_install.py` / `tests/mcp_server/test_mcp_protocol.py`
  (value-level, not hash-level) — no new dedicated compatibility test file was added.
- DSP-005 (self-consistent district-heating flow solver, replacing the fixed-design-return-
  temperature approximation) and DSP-006 (stabilization-fraction sensitivity comparison) are
  NOT implemented by this issue — both are substantial, independently-scoped physics changes
  (see `network/candidate.py`'s own module docstring, "Curtailment", for the existing
  investigation and the deferred self-consistent-sizing path) and are left for later, separately
  reported work.
- Workstream F (FAIL-001..004, the intentionally infeasible demonstration candidate) is not part
  of this issue.
