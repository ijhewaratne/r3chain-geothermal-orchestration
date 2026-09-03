# Issue: real network/GIS/geological study-package data contracts (DATA-001..009)

**Status**: **implemented** (2026-09-03, `feature/real-data-contracts`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 6 / Workstream I, AC-09). See
`docs/decisions/decision-register.md` (IMPL-012).

## What this closes

DATA-001 (study package structure), DATA-002 (manifest), DATA-003 (network requirements),
DATA-004 (GIS/CRS requirements, at the metadata layer), DATA-005 (geological scenarios),
DATA-006 (economics/planning line items), DATA-007 (validation policy — no silent imputation),
DATA-008 (synthetic sample package), DATA-009 (readiness reporting), AC-09.

## Principle honoured (14.1)

Claude implements data CONTRACTS, validation and example packages — it does not fabricate a real
Wuppertal dataset. `src/r3chain_geothermal/data_contracts/` is a new, independent top-level package
(CLAUDE.md's layer-separation rule). It is **not** wired into `network/blueprint.py` or
`workflow/core.py` in this phase — actual real-data ingestion (constructing a running network from a
validated `NetworkDataPackage`) remains Phase 8's own external-data-gated concern.

## Scope decision: metadata-level GIS, not a GIS engine

`SpatialLayerReference` records a spatial file's DECLARED metadata (path, CRS, hash, feature count,
whether geometry validity was actually checked) rather than parsing GeoJSON geometry itself. No new
GIS library dependency (e.g. `shapely`) was introduced for this prototype (NFR-005/CLAUDE.md
dependency discipline). DATA-004's core requirement — CRS must be declared, never silently guessed —
is enforced at this metadata layer.

## AC-09, verified directly

`sample_packages.build_intentionally_incomplete_real_package()` is missing exactly the three items
AC-09 names — a spatial layer's CRS, one pipe's `internal_diameter_mm` (0.0), and one geothermal
scenario's PyDoublet provenance hashes (`None`). `validate_study_package()` catches all three with
exact typed errors (`MISSING_CRS`, `INVALID_DIMENSION`, `MISSING_PROVENANCE`) and never raises;
`generate_readiness_report()` lists them and denies both `connection_optimization_permitted` and
`drilling_location_optimization_permitted`. No solver or recommendation code is anywhere in this
package's call graph — there is nothing to run to before validation.

## A design correction made during implementation

The first `_validate_network_topology()` draft required the ENTIRE junction set (supply + return
combined) to form one connected component via pipes alone. This immediately misclassified the
DATA-008 synthetic sample package itself as `DISCONNECTED_TOPOLOGY`, because a real two-sided DH
network's supply and return graphs are legitimately SEPARATE pipe graphs, joined only through
non-pipe components (consumers, plants) this simplified schema doesn't model as graph edges.
Corrected to check connectivity WITHIN each side (`NetworkSide.SUPPLY`, `NetworkSide.RETURN`)
independently — caught before commit by the deliberate act of running the synthetic sample package
through its own validator, not merely asserted to work.

## Fields deliberately made optional at the type level

`SpatialLayerReference.crs` and `GeothermalScenarioRecord.pydoublet_input_sha256` /
`pydoublet_result_sha256` are `str | None` (not a required, non-empty, pattern-constrained field) —
specifically so an incomplete real package missing them can still be CONSTRUCTED as a valid Pydantic
object and then caught uniformly, by the same semantic validator, alongside every other DATA-007
check — rather than rejected earlier, at a different layer, with a less specific error.

## Tests

`tests/data_contracts/test_schema.py` and `tests/data_contracts/test_validation_and_readiness.py`
(33 tests total): model-level validation for every DATA-002/003/005/006 model; the AC-09 proof; the
DATA-008 synthetic package's own full validity and readiness permission; duplicate-ID, disconnected-
topology (both the true-positive and the two-sided-network false-positive regression guard),
unknown-junction-reference, and inconsistent-unit-convention detection; the "missing network section
is a readiness gap, not a validation error" distinction. Full offline suite: 994 passed (was 962), 1
failed (the same pre-existing subprocess-timing test noted in earlier phase issues, confirmed
unrelated and flaky under load).

## Update (2026-09-03, `feature/complete-synthetic-prototype`, Phase 5): the mandatory gate

`data_contracts/readiness.py::enforce_real_data_readiness()` (new function) wraps
`generate_readiness_report()` (unchanged, no new validation logic) in a discriminated
`RealDataReadinessGranted`/`DataRequirementsNotMet` boundary result — the `DATA_REQUIREMENTS_NOT_MET`
result Phase 5 names explicitly, enumerating every missing/invalid dataset via a small, stable
`RealDataRequirement` enum (topology, pipe attributes, demands/temperatures, spatial CRS,
geothermal scenarios, economics, provenance/licensing, approval status) mapped from the existing
`missing_datasets`/`validation_errors`/`unresolved_approvals` fields `generate_readiness_report()`
already computed. A synthetic package is always granted (OPT-006's own policy, unchanged); a real
package is granted only when fully supplied, valid, and approved — never a silent fallback to
synthetic data while still labelled real (the failure result echoes `readiness.classification`
unchanged). See `docs/issues/real-data-readiness-gate.md` for the full account, including why NO
production code currently calls this function with a real package (there is no real-data entry
point anywhere in this repository to wire it into — Phase 8 remains blocked).

## Not covered by this issue

- No wiring into `network/blueprint.py` or `workflow/core.py` — real-data ingestion stays Phase
  8-gated. `enforce_real_data_readiness()` (above) is the ENFORCED CHOKE POINT any such future
  wiring must call; it is not itself that wiring.
- No GeoJSON geometry parsing/validity engine — metadata-level CRS/hash declarations only.
- Workstream J (OPT-001..007, synthetic joint site/connection optimisation) is not part of this
  issue, though it is expected to consume this workstream's `StudyPackage`/readiness contracts.
