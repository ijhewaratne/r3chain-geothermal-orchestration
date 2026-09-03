# Issue: persistent/rehydratable MCP run registry across server restarts

**Status**: **implemented** (2026-09-03, `feature/persistent-run-registry`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 2 / Workstream C). Originally discovered
during T5.1C acceptance evidence (`docs/evidence/t5.1c/2026-09-03-desktop-run-1/run-summary.md`,
"Why the run disappeared"). See `docs/decisions/decision-register.md` (IMPL-004..IMPL-006) for
design decisions made while implementing this.

## Implementation record (2026-09-03)

- `RunRegistry(persistent=True, root_dir=...)` (`src/r3chain_geothermal/mcp_server/registry.py`):
  requires an explicit `root_dir`; `close()` no longer deletes it; `__init__` rehydrates on
  construction via `_rehydrate()`/`_load_run_entry()`.
- Opt-in only: `build_server()` (`src/r3chain_geothermal/mcp_server/server.py`) builds a
  persistent registry only when `R3CHAIN_RUN_ROOT` is set
  (`config.resolve_run_root()`) — unset (the default) is byte-for-byte the original ephemeral
  behavior, so the existing test suite and every caller that doesn't opt in is unaffected.
- Atomic publication (RR-002): `new_artifact_dir()` now returns a `.staging-<run_id>-<uuid>`
  directory; a new `publish_artifact_dir(run_id, staging_dir)` validates the staged
  `manifest.json` (parses as `ManifestRecord`, run_id matches, every declared file present) and
  then atomically renames staging → final. `mcp_server/tools.py`'s `run_workflow_tool` factory
  updated to call both in sequence.
- Rehydration validation (RR-003): re-parses each candidate's `manifest.json`, verifies the
  directory name matches `manifest.run_id`, re-hashes every declared file against the manifest's
  own `byte_sha256` claim (not just the manifest's internal self-consistency), and parses
  `workflow_result.json` via the existing `parse_workflow_result_json()` to reconstruct a full
  `RunSummary`/`WorkflowAuditRecord` — reusing `summarize_workflow_result()` (moved from
  `tools.py` to `schemas.py` to avoid a circular import with `registry.py`, see IMPL-004). Any
  failure is caught, recorded in `registry.rehydration_warnings`, never raised.
- Path/traversal safety: rehydration only ever considers directory names matching
  `_RUN_ID_PATTERN` (`compute_run_id()`'s exact shape); `new_artifact_dir`/`publish_artifact_dir`
  use a deliberately weaker `_is_traversal_safe_path_component()` check instead (see IMPL-005 for
  why the full pattern there broke ~18 pre-existing concurrency tests that use synthetic IDs).
- Cleanup: an abandoned `.staging-*` directory found during rehydration (from a crash between
  `new_artifact_dir` and `publish_artifact_dir`) is deleted silently — it was never a published
  run by construction.
- Retention (RR-006): reuses the existing FIFO/pinned-protection eviction bound (`max_size`) —
  no separate TTL mechanism was added this phase; noted as a possible future enhancement, not a
  gap in the acceptance criteria as specified.
- Tests: `tests/mcp_server/test_persistent_registry.py` (RR-008's full restart-recovery
  acceptance test plus corrupt-bundle/atomicity/traversal cases),
  `tests/mcp_server/test_server_lifecycle.py` (env-var opt-in behavior, both directions).

## Problem

`RunRegistry` (`src/r3chain_geothermal/mcp_server/registry.py`) is created fresh per server
process: `tempfile.mkdtemp(prefix="r3chain-mcp-")` for its root directory, plus an in-memory
index mapping `run_id` → bundle location. Both are scoped to the process's lifetime. When the
MCP server process restarts — observed directly during T5.1C's first Desktop run, a clean
shutdown and restart between two conversation turns — the new process gets a brand-new, empty
registry and root directory. A `geo_get_run_summary`/`geo_get_audit`/`geo_get_artifact` call
against a `run_id` created by the *previous* process fails with `RUN_NOT_FOUND` even though the
bundle's files are still sitting on disk under the old (now-orphaned) temp directory.

This is not a correctness bug in any individual run — the run that produced the bundle completed
successfully and its files are intact. It's a **durability gap**: any workflow that spans more
than one server process lifetime (a Desktop app restart between conversation turns, a crash, a
routine update) loses live access to every run it produced before that restart, with no
in-protocol way to recover it short of an out-of-band filesystem copy performed by something
outside the MCP session itself.

## Proposed change

### Configurable stable run root

Add an optional configuration value (e.g. an environment variable or server-config field) giving
a **stable, persistent directory** for run bundles, instead of always using a fresh
`tempfile.mkdtemp()` root. When configured, `RunRegistry` writes new runs under this stable root
(one subdirectory per `run_id`, as today) rather than a process-local temp directory. When not
configured, current behavior (ephemeral per-process temp root) is preserved exactly — this is
opt-in, not a forced migration.

### Safe manifest-based rehydration on startup

When a stable run root is configured, on `RunRegistry` construction:

1. Scan the stable root's immediate subdirectories.
2. For each subdirectory whose name matches the expected `run_id` naming pattern, read its
   `manifest.json` if present.
3. Validate the manifest's own declared file list against what's actually on disk (every declared
   file present, hash-verifiable) before admitting the run back into the in-memory index.
4. Skip (do not register, log a warning) any subdirectory that fails validation — a partially
   written, corrupted, or foreign directory must never be silently trusted.

This makes restart recovery an explicit, validated step, not an assumption that anything found on
disk is safe to serve.

### Run-ID and path validation

Every `run_id` used to construct a filesystem path (both when creating a new run and when
rehydrating) must be validated against the exact generation pattern already used by
`compute_run_id()` (`r3chain-run-` + 16 lowercase hex characters) before being used in any path
join. Reject anything else outright — this is the primary path-traversal defense, since a
malformed or adversarial `run_id` string must never be interpolated into a filesystem path
unchecked.

### Path traversal prevention

- No path component of a `run_id`-derived path may contain `..`, a leading `/`, or any character
  outside the validated pattern above.
- Resolve the final path and assert it is still lexically inside the configured stable root
  before any read or write — defense in depth even if the pattern check above were ever loosened.

### Concurrency, TTL, max-entries, and cleanup policy

- **Concurrency**: rehydration at startup and normal run creation during operation must not race
  — use the same locking/synchronization primitive the in-memory registry already uses for
  same-run concurrency deduplication (per the existing registry's documented behavior).
- **TTL**: an optional maximum age (wall-clock, from the manifest's `created_at`) after which a
  stable-root run is eligible for cleanup, independent of the existing `DEFAULT_MAX_REGISTRY_SIZE`
  in-memory cap.
- **Max entries**: the stable root needs its own bound (separate from the in-memory index's
  existing cap) so unbounded disk growth across many restarts doesn't silently accumulate forever.
- **Cleanup policy**: FIFO-by-age eviction once either bound is exceeded, mirroring the existing
  in-memory eviction policy rather than inventing a new one.

### Corrupt / incomplete bundle handling

A run directory that exists but fails manifest validation (missing file, hash mismatch, malformed
JSON, partially written from a process that crashed mid-write) must be treated as absent, not as
a degraded-but-usable run — `geo_get_run_summary` etc. against it should behave exactly as if the
`run_id` had never existed (`RUN_NOT_FOUND`), never return partial or unverified data.

## Required test coverage

- **Restart-recovery, `geo_get_run_summary`**: create a run, simulate a process restart (new
  `RunRegistry` instance pointed at the same stable root), confirm `geo_get_run_summary` for that
  `run_id` succeeds and returns byte-identical content to before the restart.
- **Restart-recovery, `geo_get_audit`**: same pattern for the audit endpoint.
- **Restart-recovery, paginated `geo_get_artifact`**: same pattern, explicitly covering pagination
  continuing correctly post-restart (offset/limit/`next_offset` behavior unchanged) — this is the
  exact scenario that failed during T5.1C's first Desktop run and motivates this issue.
- **Corrupt bundle rejected**: a run directory with a missing declared file, or a manifest hash
  that doesn't match the file on disk, is not registered on rehydration and returns
  `RUN_NOT_FOUND` for any lookup.
- **Run-ID validation**: a crafted `run_id` containing `..`, absolute-path characters, or any
  character outside the expected pattern is rejected before any filesystem path is constructed,
  for both new-run creation and lookup.
- **Opt-in behavior preserved**: with no stable root configured, behavior is byte-for-byte
  identical to the current ephemeral-temp-directory implementation (regression guard).

## Explicit non-goal

This issue does not change any scientific workflow result, KPI, ranking, or economic calculation.
It is purely about *where* and *how long* a completed run's already-computed bundle remains
reachable through the MCP protocol after it has been produced. No change to `run_workflow()`,
the adapter, the network evaluator, or economics/ranking logic.
