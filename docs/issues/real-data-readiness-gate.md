# Issue: mandatory real-data readiness gate (Phase 5)

**Status**: **implemented** (2026-09-03, `feature/complete-synthetic-prototype`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 5). See `docs/decisions/decision-register.md`
(IMPL-019) and `docs/issues/real-data-contracts.md` (DATA-001..009, the contracts this gate builds
on, unchanged).

## What this closes

Phase 5's instruction: "wire the existing study-package/readiness validation into every real-data
entry point... returning a structured `DATA_REQUIREMENTS_NOT_MET` result enumerating missing/
invalid datasets if anything is missing, never silently falling back to synthetic data while
calling it real."

## The honest scope of "every real-data entry point": there are none yet

Checked directly before writing any code: `grep -rn "DatasetClassification.REAL"` across
`src/r3chain_geothermal/` outside `data_contracts/` itself and its tests returns nothing.
`network/blueprint.py::build_default_blueprint()` only ever constructs the fixed synthetic topology
(no real-data parameter exists on it at all); `workflow/core.py::run_workflow()` and
`workflow/joint_workflow.py::run_joint_optimization_workflow()` (Phase 4) only ever consume the
`config`-driven synthetic assumptions and synthetic scenario derivation. There is, today, genuinely
no code path in this repository that accepts or acts on a real `StudyPackage` at all — by design,
since Phase 8 (real Wuppertal data) is explicitly out of scope for this prototype and this session
was explicitly instructed not to attempt it.

Given that, "wiring the gate into every real-data entry point" cannot mean adding real-data
ingestion to `network/blueprint.py`/`workflow/*` — doing so would itself BE Phase 8 work under a
different name. What Phase 5 CAN honestly deliver now, and what this issue implements, is the
**enforced choke point**: a single, well-tested, mandatory gate function that any FUTURE,
separately-approved real-data entry point has no honest way to bypass, built entirely on the
already-implemented DATA-001..009 contracts (`docs/issues/real-data-contracts.md`) with zero new
validation logic of its own.

## `enforce_real_data_readiness()`

`data_contracts/readiness.py` (existing file, extended):

```python
def enforce_real_data_readiness(
    package: StudyPackage, *, requested_optimization: Literal["connection", "drilling_location"],
) -> RealDataReadinessBoundaryResult:  # RealDataReadinessGranted | DataRequirementsNotMet
```

- Calls `generate_readiness_report(package)` (unchanged) and reads its existing
  `connection_optimization_permitted`/`drilling_location_optimization_permitted` flags — the ONE
  source of truth for whether optimisation may proceed (OPT-006). This function adds no new
  permission logic; it only shapes the existing report into an actionable, discriminated result.
- **Granted** (`RealDataReadinessGranted`, `status="ready"`): synthetic packages always (unchanged
  OPT-006 policy); real packages only when `generate_readiness_report()` already says fully
  supplied, valid, and approved.
- **Denied** (`DataRequirementsNotMet`, `status="failure"`, `failure_code="DATA_REQUIREMENTS_NOT_MET"`):
  enumerates every contributing gap as one or more of eight named `RealDataRequirement` values
  (`NETWORK_TOPOLOGY`, `PIPE_ATTRIBUTES`, `DEMANDS_AND_TEMPERATURES`, `SPATIAL_CRS`,
  `GEOTHERMAL_SCENARIOS`, `ECONOMICS_AND_PLANNING`, `PROVENANCE_OR_LICENSING`, `APPROVAL_STATUS`),
  deduplicated and sorted — mapped directly from `generate_readiness_report()`'s own
  `missing_datasets`/`validation_errors`/`unresolved_approvals`/`provisional_assumptions` fields, one
  requirement category per distinct root cause, never one entry per individual field error (that
  finer detail stays available on the embedded `readiness: StudyReadinessReport` field, unchanged).
  Echoes `package.manifest.classification` back unmodified via `readiness.classification` — there is
  no code path by which a real package's own denial result could be mistaken for, or silently
  converted into, a synthetic one.

## Why no new validation logic

Every check `enforce_real_data_readiness()` relies on already existed and was already tested
(`validate_study_package()`, `generate_readiness_report()`, `docs/issues/real-data-contracts.md`'s
own AC-09 proof). Adding a second, parallel validation pass here would risk exactly the kind of
divergent-implementation drift this project's own established pattern (DLT-006, "parity by
construction") exists to prevent. This function is a pure re-shaping of already-computed,
already-correct data into the named result shape Phase 5 asks for.

## Tests

`tests/data_contracts/test_readiness_gate.py` (7 tests): a synthetic package is always granted; a
genuinely complete, approved REAL package (built by fixing all three AC-09 gaps in the existing
intentionally-incomplete fixture, plus supplying economics/decisions and approving the manifest) is
granted for both `"connection"` and `"drilling_location"`, proving the granted path is reachable for
real data too, not only synthetic; the AC-09 incomplete package is denied with all five expected
`RealDataRequirement` values named (`SPATIAL_CRS`, `PIPE_ATTRIBUTES`, `PROVENANCE_OR_LICENSING`,
`APPROVAL_STATUS`, `ECONOMICS_AND_PLANNING`), deduplicated and sorted; the denial never relabels a
real package's own classification; an empty `geothermal_scenarios` list denies a real package for
BOTH optimisation kinds (a top-level required dataset, not merely drilling-specific — a genuine
finding from writing this test, not assumed); JSON round-trip for both outcomes via the
discriminated union.

## Not covered by this issue

- No real-data entry point is added anywhere (see "The honest scope" above) — Phase 8 remains
  blocked, exactly as instructed.
- `enforce_real_data_readiness()` is therefore not called by any production code path today; it
  exists as the enforced mechanism a future, separately-approved real-data integration must use.
