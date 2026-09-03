# Issue: intentionally infeasible workshop/negative-demo candidate (FAIL-001..004)

**Status**: **implemented** (2026-09-03, `feature/config-gates-dispatch-policy`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 3 / Workstream F — closes Phase 3 alongside
`docs/issues/config-gates-and-shortfall-policy.md` and `docs/issues/self-consistent-flow-solver.md`).
See `docs/decisions/decision-register.md` (IMPL-009).

## Requirement

FAIL-001 asks for "a clearly named workshop/negative-test configuration" that does **not** modify
the canonical successful C1-C4 comparison. FAIL-002 asks for at least one candidate designed to
fail exactly one primary gate, deterministically. FAIL-003 asks the result/audit/CSV/recommendation
to show the failure explicitly (id, label, `feasible: false`, exact code, measured value/threshold/
unit, exclusion from ranking, no invented LCOH). FAIL-004 asks for unit and end-to-end tests.

## Discovery: candidates are not config-driven at runtime

`config/demo_assumptions.json::candidates.list` turned out to be **descriptive, not executable**
(a CFG-001 gap noted but not closed by this issue): `network/blueprint.py::build_default_blueprint()`
builds its four candidates entirely from `network/geometry.py`'s Python constants
(`CANDIDATE_TRUNK_ATTACHMENT`, `CANDIDATE_LABELS`, `candidate_surface_connection_length_m()`) — the
JSON list is never read by any code path. Adding a JSON-only negative-candidate entry would have
been exactly the kind of unenforced/undocumented-as-such config drift CFG-003 exists to close, so a
real code path was added instead (see below), keeping candidate config genuinely executable rather
than descriptive.

## Design

- **A genuinely separate config file**, `config/demo_assumptions_workshop_negative.json`, forked
  from `config/demo_assumptions.json` (byte-identical outside `_meta` and `candidates`) — never the
  canonical file itself (FAIL-001). It adds two keys under `candidates`:
  `include_workshop_negative_demo: true` and `workshop_negative_demo: {id, label, supply_junction,
  return_junction, surface_connection_length_m}`.
- `workflow/core.py::_apply_workshop_negative_demo(blueprint, config)`: reads both keys via
  `.get(..., False)` / `candidates_cfg["workshop_negative_demo"]` — **absent from the canonical
  config on purpose**, so for the canonical config this function is a pure no-op returning
  `blueprint` unchanged (not even a copy). Wired into `run_workflow()`'s Stage 3, immediately after
  `build_default_blueprint()`, and into `validate_config_structure()` (which now also builds a real
  blueprint, not just `_build_blueprint_kwargs()`, so a malformed workshop spec is caught before
  `run_workflow()` runs at all).
- Reconstructs `NetworkBlueprint` via its own constructor (not `model_copy(update=...)`, which
  bypasses validation) — the injected candidate's junction references and positive length are
  checked by the SAME model-level invariant every other candidate is checked by.
- `workflow/svg_export.py`: the candidate-marker loop indexed `CANDIDATE_SITE_COORDINATES[candidate_id]`
  directly, which would `KeyError` for a candidate outside geometry.py's mapped C1-C4 site set.
  Changed to `.get(candidate_id)` with a small fixed-offset fallback from the candidate's own trunk
  junction — a presentation-layer-only fallback (FAIL-003 does not require the SVG map; this only
  prevents a crash during full artifact generation).

## The chosen negative candidate

`C5_negative`: same junction pair as C1 (`trunk_1`/`ret_trunk_1`), `surface_connection_length_m`
increased 200x from C1's own 50.0 m to **10000.0 m** — the connection pipe's own DN
(`CONNECTION_PIPE_DN_MM`) stays fixed regardless of length, so velocity is unaffected; only the
friction pressure drop scales with length, giving a deterministic, purely-hydraulic path to
`PRESSURE_LIMIT_EXCEEDED` (FAIL-002: "not depend on random solver behavior").

Measured margin, to avoid a fragile/borderline choice:

| length (m) | min pressure (bar_abs) | outcome |
|---:|---:|---|
| 5000.0 | ≈1.62 | feasible (only ~8% margin above the 1.5 threshold — deliberately rejected) |
| **10000.0 (chosen)** | **≈0.24** | **`PRESSURE_LIMIT_EXCEEDED`, ~84% below the 1.5 threshold** |

## Verified end-to-end

```
$ r3chain-geothermal-demo --input fixtures/pydoublet/repaired_result.json \
    --config config/demo_assumptions_workshop_negative.json \
    --provenance config/demo_source_provenance.json --output-dir /tmp/out
run_id: r3chain-run-440e06b197eaae18   # different from the canonical r3chain-run-93d41133daa11d1a
preferred candidate: C1 (rank 1 of 4 feasible)
```

`candidate_comparison.csv`'s `C5_negative` row: `converged=True, feasible=False,
failure_code=PRESSURE_LIMIT_EXCEEDED`, every economic column blank (no invented LCOH/rank).
`recommendation.md`'s "Rejected candidates" table lists it explicitly with its exact failure code
and message. C1-C4 remain feasible, ranked identically, with the exact canonical LCOH values.

## Scientific-identity impact (GOV-004)

**None for the canonical config** — `_apply_workshop_negative_demo()` is a no-op when its two keys
are absent (true for `config/demo_assumptions.json`), so `config_sha256`, `run_id`
(`r3chain-run-93d41133daa11d1a`), `bundle_scientific_sha256`, and every C1-C4 KPI/feasibility/
LCOH-ranking value are **completely unaffected** — re-verified live by
`test_canonical_run_is_unaffected_by_the_workshop_negative_feature_existing`. No schema version
bump was needed this time (`BlueprintCandidate`/`NetworkBlueprint` are unchanged types; the feature
only conditionally adds one more dict entry using the existing `BlueprintCandidate` model). Running
the SEPARATE workshop config naturally produces a different `run_id`
(`r3chain-run-440e06b197eaae18`) — expected and intended for a deliberately different scenario, not
a silent change to any existing identity.

## Tests

`tests/workflow/test_workshop_negative_demo.py` (14 tests): canonical/workshop config parity
outside the two new keys; canonical run unaffected; end-to-end infeasibility with exact failure
code/measured values/exclusion from ranking; stage-call audit record; determinism (two runs
bit-identical); `validate_config_structure()` accepts the valid workshop config and rejects five
distinct malformed variants (one per required spec field) plus an invalid junction reference;
`run_workflow()` fails the same way for a malformed spec. `tests/network/test_candidate.py`: one
unit-level test reusing the exact published candidate spec directly against `evaluate_candidate()`.
Full offline suite: 918 passed (was 903), 0 failed.
