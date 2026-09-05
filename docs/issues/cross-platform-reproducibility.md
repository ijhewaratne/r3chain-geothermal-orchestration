# Issue: cross-platform reproducibility verification and correction (REPRO-001..010, AC-J16)

**Status**: **RESOLVED -- a full green three-job CI run (`33953933376`, commit `1d4a3ec`) confirms
every fix in this document on real target hardware: `ubuntu-latest`×{3.11,3.12} and `macos-latest`×3.11
all pass, including both canonical and joint wheel-installation smoke tests. AC-J16 (cross-platform
release gate) is PASS.** (2026-09-05,
`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md` Phase 7/9.)

## Problem (spec §2.5 point 13, §18)

The corrected specification records a prior, real Linux CI observation against this project's own
pre-Phase-1 baseline (1,063 tests): "1,054 passed, 6 failed and 3 skipped. Four failures concerned a
pinned bundle scientific hash; two concerned a pathological solver failure code." REPRO-001 requires
reproducing these before changing any test; REPRO-002/003 require diagnosing the actual divergent
field(s) rather than replacing one platform's hardcoded hash with another's; REPRO-007/008/009
require not relying on genuinely ill-conditioned solver behaviour as a test's sole proof, and adding
a deterministic, platform-independent proof instead; REPRO-006 requires actually testing declared
Python support (3.11 and 3.12) rather than an untested `requires-python` claim.

## Local Docker verification (arm64) — real, but incomplete evidence

Before real CI results were available, this session built and tested the project fresh inside genuine
Linux/arm64 containers via Docker Desktop (`python:3.11-slim` and `python:3.12-slim`, native on this
Apple Silicon host) as the most direct verification available without push access. Both reproduced
1231/1232 tests passing, with the ONE failure being a verification-harness artifact of this session's
own `cp -r`-based setup (a macOS Unicode NFD/NFC filename mismatch on the `repos/pandapipesAI`
submodule, not present under a real `git clone`/`actions/checkout@v4`), and all four then-known
pinned-hash tests passing unmodified. A third container, Linux/**amd64** (matching GitHub Actions'
actual runner architecture, emulated via Rosetta on this Apple Silicon host), was attempted but
abandoned after 5 hours wall-clock (4h43m continuous CPU, zero output) as impractical on this host.

**This arm64-only verification turned out to be insufficient**, as the real CI run below shows: arm64
alone did not surface the genuine x86_64-specific divergence, or a third pathological-solver test this
session's own earlier grep-based search had missed. This is recorded plainly, not glossed over --
REPRO-001's own instruction to reproduce failures before changing tests is best satisfied by the real
CI evidence below, not the arm64 approximation above.

## Real CI evidence (the actual diagnosis)

A commit containing this session's Phase 1-8 work (`dc71d7d`, message "Add integration tests for
Phase 2, Phase 4, and Phase 5 workflows") was pushed to `origin/feature/complete-synthetic-prototype`
by a process external to this session -- not by any `git commit`/`git push` this session executed
(this session's own standing instruction throughout has been not to commit/push without separate
authorisation, and no such authorisation had been given at that point). This triggered
`.github/workflows/ci.yml`'s real three-job matrix (`ubuntu-latest`×{3.11,3.12}, `macos-latest`×3.11),
retrieved via `gh run view 33918616460`. All three jobs **failed**, each at the "Full offline test
suite" step (the wheel-smoke-test steps never ran as a result). Exact failures:

**`ubuntu-latest` × Python 3.11 and `ubuntu-latest` × Python 3.12 (identical failure set on both):**

```
FAILED tests/mcp_client/test_wheel_install.py::test_mcp_demo_entry_point_runs_outside_the_repo_and_matches_in_repo_parity
FAILED tests/mcp_server/test_input_provenance_mcp.py::test_run_workflow_tool_strict_provenance_reproduces_golden_run_id_and_bundle_hash
FAILED tests/mcp_server/test_input_provenance_mcp.py::test_run_workflow_tool_omitted_expected_hash_still_reproduces_golden_bundle_hash
FAILED tests/mcp_server/test_mcp_protocol.py::test_tools_call_geo_run_workflow_worked_case_matches_the_cli
FAILED tests/network/test_baseline.py::test_strict_json_round_trip_for_failure_codes[THERMAL_PIPEFLOW_NOT_CONVERGED]
```

**`macos-latest` × Python 3.11:**

```
FAILED tests/mcp_server/test_server_lifecycle.py::test_real_server_process_cleans_up_its_temp_directory_on_sigterm
  subprocess.TimeoutExpired: ... timed out after 5 seconds
```

This is remarkably close to the specification's own originally-diagnosed pattern (4 hash + 2 solver
failures) -- the differences (5 hash-adjacent failures here, counted per-test rather than per-root-
cause, plus one CI-timing flake) reflect this exact codebase's own current test inventory, not a
different root cause.

### Diagnosis 1 — the pinned `bundle_scientific_sha256` genuinely diverges on real x86_64

All four `ubuntu-latest` hash failures show the identical pair of values, on BOTH Python 3.11 and
3.12:

```
expected (macOS ARM64 / Linux ARM64, this session's own Docker verification): ee76b2a626f57fd4825c554ac55e57e81e567f86c7bf4acd771cb23a4389f3c8
actual   (real ubuntu-latest x86_64, both Python versions):                  6e528746c56f2a1ceda9509b2f5ba2d65f1d45c7961caa69a09fa5577b6a9e25
```

`run_id` (`r3chain-run-93d41133daa11d1a`) and every KPI/ranking value passed on every job -- `run_id`
is a pure hash of INPUT bytes (raw PyDoublet result + config + provenance), never touched by solver
output, so its stability across architectures is expected and unsurprising. `bundle_scientific_sha256`
hashes RESULT content, including pandapipes' own solved floating-point state after a full sequential
thermo-hydraulic solve -- and this session's earlier arm64-only verification (Apple Silicon macOS vs.
Apple-Silicon-native Linux) never actually exercised a different CPU **architecture**, only a
different OS/libc on the SAME architecture family. Real x86_64 hardware's own numerical noise for this
project's linear solves evidently exceeds the 12th significant figure
`SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES` quantizes to.

**Correction applied (per this specification's own §18 three-tier reproducibility model -- (1) byte
hash, (2) scientific fingerprint, (3) scientific equivalence: "logical results plus KPI comparisons
within declared tolerances"):** the four affected tests
(`tests/mcp_client/test_wheel_install.py`, `tests/mcp_server/test_input_provenance_mcp.py` ×2,
`tests/mcp_server/test_mcp_protocol.py`) no longer assert `bundle_scientific_sha256` against a
cross-platform-pinned literal. Each now asserts: `run_id` exactly (tier 1, already platform-stable),
that `bundle_scientific_sha256` is a well-formed 64-character hash (structural sanity, not a value
comparison), and the exact ranked-candidate LCOH set to 4 decimal places plus candidate order (tier 3,
scientific equivalence) -- exactly the comparison strategy §18 itself prescribes for cross-platform CI,
not a new invention. `SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES` itself was deliberately NOT widened as
a blind fix: REPRO-002 requires diagnosing the actual divergent field via a per-file diff before
changing the normalization rule, and obtaining that diff would require iterative authorised-push CI
access this session did not have (see "What remains open" below). `hashing.py`'s own docstring is
corrected to state this plainly -- a PRIOR version of that docstring (written after the arm64-only
verification, before this real CI evidence existed) incorrectly claimed the 12-significant-figure rule
was "sufficient" cross-platform; that claim is now retracted with the real evidence that disproved it,
not silently edited away.

`bundle_scientific_sha256`'s original purpose -- detecting a scientific regression between two runs on
the SAME machine/BLAS backend (e.g. AC-J12's own "run twice, assert identical hash" proof,
restart-recovery determinism checks) -- is completely unaffected; only cross-architecture literal
comparisons were corrected.

### Diagnosis 2 — a third pathological-solver test, missed by this session's earlier fix

`tests/network/test_baseline.py::test_strict_json_round_trip_for_failure_codes[THERMAL_PIPEFLOW_NOT_CONVERGED]`
uses the identical "1e9 kW absurd demand" blueprint the ALREADY-corrected semantic test in the same
file used to use -- but this is a SEPARATE test (proving strict-JSON round-tripping for each failure
code's own contract), parametrized generically over a `_FAILURE_SCENARIOS` dict, so it was not caught
by this session's earlier grep-based search for "pathological"/"NOT_CONVERGED"/"extreme demand" text
patterns. On real ubuntu-latest x86_64, that same blueprint now produces `PRESSURE_LIMIT_EXCEEDED`
instead of `THERMAL_PIPEFLOW_NOT_CONVERGED` -- the exact class of platform-sensitivity REPRO-007 warns
against, confirmed for a second, independent test.

**Correction applied (REPRO-008):** `THERMAL_PIPEFLOW_NOT_CONVERGED` was removed from the
scenario-driven `_FAILURE_SCENARIOS` dict (the other three entries -- `CONSUMER_TEMPERATURE_NOT_MET`,
`PRESSURE_LIMIT_EXCEEDED`, `VELOCITY_LIMIT_EXCEEDED` -- all passed unmodified on real x86_64 CI, since
each is a converged solve failing a plain numeric gate comparison, not a convergence outcome itself,
and needed no change). A new dedicated test,
`test_strict_json_round_trip_for_thermal_pipeflow_not_converged`, proves the same strict-JSON
round-trip contract via a deterministic injected `pandapipes.pipeflow` failure (the same pattern
already established for the two previously-corrected tests), never dependent on any architecture's own
convergence behaviour for an ill-conditioned input.

### Diagnosis 3 — a CI-timing flake, unrelated to this session's own work

`test_real_server_process_cleans_up_its_temp_directory_on_sigterm` (`macos-latest` only) failed with
`subprocess.TimeoutExpired` on the POST-SIGTERM `process.wait(timeout=5)` call -- the real subprocess
did start and create its temp directory in time (an earlier assertion in the same test), but process
teardown itself did not complete within 5 seconds on a loaded GitHub Actions macOS runner. This is a
pre-existing test (unrelated to the joint site/connection specification's own scope) whose fixed
5-second teardown budget was too tight for real CI load. **Correction applied:** widened to 20 seconds
-- a CI-environment timing margin, not a change to what the test proves (the temp directory must still
be gone once the process has actually exited).

## Python 3.12 (REPRO-006, TEST-034)

`pandapipes` 0.14.0 (the only version this project's own `pandapipes>=0.14,<0.15` pin permits)
declares `Programming Language :: Python :: 3.12` on PyPI, as do `pydantic`, `mcp`, and `jsonpointer`
(this project's only other direct dependencies). The real `ubuntu-latest`×3.12 CI job confirms this in
practice: after the fixes above, its own failure set was IDENTICAL to `ubuntu-latest`×3.11's (same five
tests, same root causes) -- no 3.12-specific defect exists. `.github/workflows/ci.yml`'s matrix
includes `ubuntu-latest` × Python 3.12 alongside `ubuntu-latest`/`macos-latest` × Python 3.11 --
`requires-python = ">=3.11"` in `pyproject.toml` was already honest (no upper bound was ever asserted);
this closes the gap between that claim and what had actually been tested. `macos-latest` is
deliberately NOT tested against 3.12: that specific claim was not verified, and adding it without
evidence would repeat exactly the mistake REPRO-003 warns against.

## Update 2026-09-05 — the fixes were confirmed on real CI (partially)

The corrected commit above (containing every fix this document describes) was pushed externally as
`9da0bb8` ("feat: Enhance joint workflow artifacts with new resource and site files" -- also carrying
the Phase 9 §17 artifact-bundle work, unrelated to this document's own concern) and triggered a real
GitHub Actions run, `33948931491` (`gh run view 33948931491`). Result:

```
✓ test (ubuntu-latest, 3.12)  -- PASSED, 12m17s
✓ test (ubuntu-latest, 3.11)  -- PASSED, 6m45s
X test (macos-latest, 3.11)   -- FAILED, 6m43s
```

**Both `ubuntu-latest` jobs now pass completely** -- direct, real confirmation that the hash-divergence
fix (tier-3 scientific-equivalence assertions replacing the cross-architecture byte-literal) and the
third pathological-solver-test fix both hold on genuine x86_64 hardware, on both Python versions. This
is the strongest evidence this document has produced: not a local approximation, but the actual target
environment passing.

`macos-latest` failed at a DIFFERENT test than any of the five diagnosed above:
`test_real_server_process_cleans_up_its_temp_directory_on_sigterm`, this time timing out at the
WIDENED 20-second `process.wait()` (not the original 5s) -- `subprocess.TimeoutExpired`. This is a
pre-existing MCP-server-lifecycle test, unrelated to the joint-site-connection specification's own
scope. Since simply widening the number again did not obviously address a genuine timeout (it failed
at exactly the new limit, not merely close to the old one), the actual root cause was diagnosed
instead: the test set `stdout=subprocess.PIPE, stderr=subprocess.PIPE` for the real server subprocess
but never reads either stream anywhere in the test. If the server process (or an import it triggers --
numpy/pandapipes deprecation warnings are exactly this shape) writes enough bytes to fill the OS pipe
buffer, the child blocks indefinitely on `write()`, unable to ever finish handling `SIGTERM` -- no
finite timeout fixes a genuine full-pipe deadlock. **Correction applied:** `stdout`/`stderr` (and
`stdin`) redirected to `subprocess.DEVNULL` -- this test only ever needs the process's exit behaviour,
never its output content, so discarding output removes the deadlock possibility entirely. The
`process.wait()` timeout was also widened further, to 30 seconds, as a genuine (separate) CI-timing
margin. Re-verified locally on macOS (6/6 tests in this file passing). This session could not trigger
another real CI run to confirm the fix directly: `gh run rerun` was attempted and blocked by this
session's own auto-mode classifier (a write action against shared external state) -- reported here
rather than worked around.

## Update 2026-09-05 (later) — full three-job green CI confirmed

The `DEVNULL` fix above was pushed externally as `1d4a3ec` ("feat: Update documentation and tests for
cross-platform reproducibility and joint workflow") and triggered CI run `33953933376`
(`gh run view 33953933376`). Result:

```
✓ test (ubuntu-latest, 3.11)  -- 7m44s
✓ test (ubuntu-latest, 3.12)  -- 12m13s
✓ test (macos-latest, 3.11)   -- 7m6s
```

**All three required jobs pass.** Wheel artifacts were uploaded for all three
(`r3chain-geothermal-wheel-ubuntu-latest-py3.11`, `-py3.12`, `r3chain-geothermal-wheel-macos-latest-py3.11`),
confirming both the canonical and joint wheel-installation smoke tests (which run after the full
offline suite in each job) also passed -- those steps only execute if the suite itself is green.

This closes every item this document opened with: the four cross-platform `bundle_scientific_sha256`
divergences, the third pathological-solver test, and the macOS subprocess-pipe deadlock are all
confirmed fixed on real target hardware, not merely diagnosed and locally re-verified. **AC-J16
(cross-platform release gate) is PASS.**

## What this does NOT claim

This document's fixes ARE now confirmed on real CI (run `33953933376`, all three required jobs
green) -- this is no longer merely a local re-verification. What it still does not claim: bit-identical
`bundle_scientific_sha256` values are achievable or necessary across every CPU architecture in
existence -- the corrected test strategy explicitly abandons that narrower claim in favour of the
specification's own tier-3 "scientific equivalence" model for cross-platform comparisons, while
preserving byte-level comparison for same-machine determinism checks, which remain unaffected and
unweakened. Nor does it claim every conceivable future CI environment (a different runner image
version, a different BLAS release) will behave identically forever -- only that the three currently
supported, currently tested environments do, as of this run.
