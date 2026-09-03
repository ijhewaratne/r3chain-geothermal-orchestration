# Issue: reusable geothermal-doublet connection component (DLT-001..007)

**Status**: **implemented** (2026-09-03, `feature/geothermal-doublet-component`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 4 / Workstream G). See
`docs/decisions/decision-register.md` (IMPL-010) and `docs/geothermal-doublet-component-guide.md`
(the DLT-007 component guide).

## What this closes

DLT-001 (six named typed models), DLT-002 (explicit typed inputs, every quantity unit-bearing),
DLT-003 (the documented topology, reproduced not redefined), DLT-004 (isolation/idempotence),
DLT-005 (the required result-extraction fields), DLT-006 (parity), DLT-007 (this component guide),
and AC-07 (parity + no cross-candidate mutation).

## Design decision: parity by construction, not by re-derivation

`network/candidate.py::evaluate_candidate()` already builds and solves this exact topology, and
already implements the DSP-005 self-consistent flow solver. Re-deriving that physics a second time
in a new module would risk exactly the kind of silent divergence DLT-006 exists to catch. Instead,
`network/doublet_component.py` WRAPS the same private functions
(`_add_geothermal_injection_branch`, `_solve_self_consistent_injection`,
`_compute_injected_mass_flow_kg_s`) behind the DLT-001 typed contract. Given identical inputs, the
new module and `evaluate_candidate()` call the IDENTICAL underlying code — so their outputs are
bit-identical (not merely within a declared tolerance), verified for all four candidates under both
`injection_sizing_policy` values by
`tests/network/test_doublet_component.py::test_parity_with_evaluate_candidate`.

## Phase-4 exit gate, read literally

"Component parity and isolation pass; legacy duplicate construction logic is removed only after
parity is proven." Parity is proven (above). `evaluate_candidate()` is **not** retargeted to call
the new component in this phase — a deliberately conservative choice: that function is one of the
most heavily validated modules in this codebase, and there is in fact no *duplicate* physics to
remove today, since both paths already share the same underlying calls. Retargeting
`evaluate_candidate()` to construct its topology through this component (rather than calling the
same private helpers directly) is left as a separate, later, independently-reviewable step, not
bundled into this phase.

## The six DLT-001 models

`GeothermalDoubletSpec` (brine-side, from PyDoublet), `HeatExchangerBoundary` (T2.1's already-
computed coupling boundary), `DistrictHeatingConnectionSpec` (topology — wraps `BlueprintCandidate`
directly rather than duplicating its fields, plus the DH-side design temperatures/water property),
`DoubletOperatingPolicy` (the DECIDED `accepted_heat_kw` plus flow-solver tolerances — validated to
equal `network.candidate`'s own named constants in this version, not yet independently overridable),
`GeothermalDoubletHandles` (pandapipes element names for audit), `GeothermalDoubletResult` /
`GeothermalDoubletFailure` (a discriminated `GeothermalDoubletBoundaryResult`, this project's
established house pattern).

## Scope boundary (documented, not silently dropped)

This component's own failure surface covers only what is intrinsic to ONE connection's own
construction/flow-sizing (`THERMAL_PIPEFLOW_NOT_CONVERGED`, `GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT`,
`SELF_CONSISTENT_FLOW_NOT_CONVERGED` — reusing `CandidateFailureCode`, not a parallel enum).
Network-wide gates (consumer temperature, pressure, velocity, mass/energy balance) and auxiliary/
unmet-heat accounting (which needs total consumer demand, information this component never
receives) remain outside its scope, owned by the caller one layer above — see the module's own
"Scope boundary" docstring section and the component guide's "Limitations".

## Tests

`tests/network/test_doublet_component.py` (20 tests): parity (4 candidates × 2 sizing policies, 8
parametrized cases); isolation/idempotence (no blueprint mutation, repeated calls bit-identical,
two different candidates against the same blueprint don't cross-contaminate); all three failure
codes reachable; model validation (rejected tolerance overrides, non-positive heat, out-of-range
delivery factor, inverted DH temperatures); strict-JSON round trip for both success and failure.
Full offline suite: 938 passed (was 918), 0 failed.

## Not covered by this issue

- `evaluate_candidate()` itself is not refactored to call this component (see "Phase-4 exit gate,
  read literally" above).
- `DoubletOperatingPolicy`'s solver tolerances remain fixed to `network.candidate`'s own constants
  — independent overriding is not yet supported.
- Workstream H (CAN-001..007, deterministic candidate generation) is not part of this issue.
