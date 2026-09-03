# Issue: persistent/rehydratable MCP run registry across server restarts

**Status**: specification only, not implemented. Discovered during T5.1C acceptance evidence
(`docs/evidence/t5.1c/2026-09-03-desktop-run-1/run-summary.md`, "Why the run disappeared").

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
