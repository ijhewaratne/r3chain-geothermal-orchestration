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
parity is proven." Parity is proven (above).

**Update (2026-09-03, `feature/complete-synthetic-prototype`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 3.1)**: `evaluate_candidate()` is now
retargeted to call `build_and_evaluate_geothermal_doublet_with_net()` — the earlier entry below,
which deferred this retargeting, is superseded. The prior reasoning ("no *duplicate* physics to
remove today, since both paths already share the same underlying calls") was correct about the
underlying private functions, but a second, independent audit judged the ORCHESTRATION/sequencing
code around those calls — construction of the four typed inputs, the try/except dispatch on
`injection_sizing_policy`, and result extraction — to itself be a duplicate worth eliminating in
favor of one authoritative call path, per that specification's explicit instruction not to preserve
duplicate implementations without a documented reason. `evaluate_candidate()` now:

1. Builds `GeothermalDoubletSpec`/`HeatExchangerBoundary`/`DistrictHeatingConnectionSpec`/
   `DoubletOperatingPolicy` from its own already-available `coupling_result`/`candidate`/
   `injected_kw`/`injection_policy` inputs (mirroring exactly the construction
   `tests/network/test_doublet_component.py`'s own `_spec()`/`_boundary()`/`_connection()` helpers
   already used to prove parity).
2. Calls `build_and_evaluate_geothermal_doublet_with_net(blueprint, spec, boundary, connection,
   policy)` once, imported locally inside the function to break the module cycle (this module
   already imports several of `network/candidate.py`'s own private helpers at its top level).
3. Maps a `GeothermalDoubletFailure` directly onto `CandidateEvaluationFailure` (both share
   `CandidateFailureCode` already, so no code-translation table is needed).
4. On success, reads `district_heating_water_mass_flow_kg_s`, `connection_differential_pressure_bar`,
   `circulation_pump_hydraulic_power_kw`, the inlet/outlet temperatures, and `flow_solver` directly
   off the returned `GeothermalDoubletResult` instead of re-extracting them from `net` a second
   time, and uses `handles.*` (not a locally-rebuilt `refs` dict) wherever it still needs a
   pandapipes element name for its OWN whole-network gates (pump differential pressure, junction
   pressure at `geo_mid`/`geo_return`) — the only computation genuinely outside this component's own
   documented "Scope boundary" (consumer temperature, absolute pressure, pump differential pressure,
   pipe velocity, mass balance, physical energy balance; module docstring above).

One genuine cross-module subtlety surfaced and was fixed during this retargeting:
`DoubletOperatingPolicy`'s three solver-tolerance fields previously defaulted from a
`from .candidate import SELF_CONSISTENT_FLOW_MAX_ITERATIONS` (etc.) plain import — a value COPIED
at this module's own import time. A monkeypatch-based reachability test
(`test_self_consistent_flow_not_converged_via_monkeypatched_max_iterations`) patches
`network.candidate`'s own module attribute directly; `_solve_self_consistent_injection()` (defined
IN that module) correctly observes the patched value, but the doublet component's own copied-at-
import-time default did not, producing a mismatched `details["max_iterations"]` in the returned
failure. Fixed by referencing `network.candidate`'s constants through a module reference
(`from . import candidate as _candidate_module`, then `_candidate_module.SELF_CONSISTENT_FLOW_MAX_ITERATIONS`)
with `Field(default_factory=...)` instead of a plain default, in both the field defaults and the
validator's equality check — both now re-read the live module attribute rather than a frozen
snapshot. This is a test/constant-propagation correctness fix, not a scientific-default change: the
value used in every non-monkeypatched execution (40 iterations, in `network/candidate.py`) is
identical before and after.

Full parity/candidate/baseline suite re-run after retargeting: all pre-existing tests pass unchanged
(no test file was edited to accommodate this refactor, other than the one genuine bug fix above).

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

- `DoubletOperatingPolicy`'s solver tolerances remain fixed to `network.candidate`'s own constants
  — independent overriding is not yet supported.
- Workstream H (CAN-001..007, deterministic candidate generation) is not part of this issue.
