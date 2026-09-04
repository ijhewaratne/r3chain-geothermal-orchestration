# Issue: cross-platform reproducibility verification and correction (REPRO-001..010, AC-J16)

**Status**: **verified on Linux/arm64 (Python 3.11 and 3.12); local Linux/amd64 verification was
abandoned as impractical on this host (see "Remaining verification" below) — the real ubuntu-latest
GitHub Actions runner, not local emulation, is the correct mechanism to close that specific
architecture gap** (2026-09-04,
`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md` Phase 7).

## Problem (spec §2.5 point 13, §18)

The corrected specification records a prior, real Linux CI observation against this project's own
pre-Phase-1 baseline (1,063 tests): "1,054 passed, 6 failed and 3 skipped. Four failures concerned a
pinned bundle scientific hash; two concerned a pathological solver failure code." REPRO-001 requires
reproducing these before changing any test; REPRO-002/003 require diagnosing the actual divergent
field(s) rather than replacing one platform's hardcoded hash with another's; REPRO-007/008/009
require not relying on genuinely ill-conditioned solver behaviour as a test's sole proof, and adding
a deterministic, platform-independent proof instead; REPRO-006 requires actually testing declared
Python support (3.11 and 3.12) rather than an untested `requires-python` claim.

This session could not run a real `ubuntu-latest` GitHub Actions job directly (no push was
authorised for this purpose). Docker Desktop was available locally, however, and was used to build
and test the project fresh, from this exact working tree, inside genuine Linux containers — this is
qualitatively different from (and more direct than) re-reasoning about the problem from macOS alone,
and is the evidence this document records.

## What was actually run

Three fresh containers, each: `cp` the repository into the container, `pip install -e ".[dev,mcp]"`,
then `python -m pytest -q` (the exact commands `ci.yml` itself runs):

| Container | Base image | Platform | Python | numpy | scipy | pandapipes | BLAS/LAPACK |
|---|---|---|---|---|---|---|---|
| A | `python:3.11-slim` | `linux/arm64` (native on this Apple Silicon host) | 3.11.14 | 2.4.6 | 1.16.3 | 0.14.0 | OpenBLAS 0.3.31.188.0 (scipy-openblas, `neoversev2`) |
| B | `python:3.12-slim` | `linux/arm64` | 3.12.x | 2.4.6 | 1.16.3 | 0.14.0 | OpenBLAS 0.3.31.188.0 |
| C | `python:3.11-slim` | `linux/amd64` (emulated on this host via Docker Desktop's Rosetta translation — the architecture GitHub Actions' `ubuntu-latest` runners actually use) | 3.11.x | — | — | — | abandoned, see below |

Compared against this project's own native macOS ARM64 development environment: Python 3.11.16,
numpy 2.4.6, scipy 1.16.3, pandapipes 0.14.0, **Apple Accelerate** (not OpenBLAS) as the BLAS/LAPACK
backend. Package *versions* are identical across every environment — only the BLAS/LAPACK backend
and OS differ, which isolates the comparison to exactly the variable REPRO-002 asks about.

## Result

Containers A and B: **1231/1232 collected tests passed** (1 skipped set of 3, unrelated —
`ps -e -o pid=,ppid=,command=` not available in a minimal container, the SAME reason this already
skips in some sandboxed macOS CI contexts). The single reported failure in both containers,
`test_no_changes_to_either_nested_repository`, is a **verification-harness artifact, not a real
issue**: this ad-hoc verification used `cp -r` (not `git clone`) to get the repository into the
container, and macOS's own filesystem stores the `repos/pandapipesAI` submodule's two accented
German filenames in Unicode NFD form while the submodule's own git index recorded them in NFC form —
a mismatch `cp -r` reproduces and a real `git clone`/`actions/checkout@v4` (as `ci.yml` actually
uses) does not. This is not one of the six originally-diagnosed failures and required no code change.

**All four previously-flagged `bundle_scientific_sha256`-pinning tests passed, unmodified, in both
containers**, reproducing the exact same golden hash the macOS suite already asserts:

```
ee76b2a626f57fd4825c554ac55e57e81e567f86c7bf4acd771cb23a4389f3c8
```

This is the direct, now-empirically-confirmed answer to the "honesty boundary" `hashing.py`'s own
`SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES` docstring left open (added under a prior spec's Phase 2,
explicitly noting it had only ever been tested on macOS ARM64): the 12-significant-figure scientific
fingerprint **is sufficient** for this project's own canonical golden run across Apple Accelerate and
OpenBLAS. No further normalization-rule change was needed for these four tests, and none was made —
consistent with REPRO-003's instruction not to replace one platform's hash with another's: the SAME
hash, unchanged, is correct on both.

**Both non-convergence ("pathological solver failure code") tests were already corrected in this
session, before these containers were built** (REPRO-007/008/009):
`tests/network/test_baseline.py::test_absurd_demand_produces_thermal_pipeflow_not_converged` and
`tests/network/test_candidate.py::test_thermal_pipeflow_not_converged_via_undersized_connection_pipe`
each now have (a) their own single hardcoded `failure_code` assertion widened to a documented,
complete set of every hard-gate code reachable from that test's own configuration (never widened to
"any code" — CONNECTION_DESIGN_INVALID/GEOTHERMAL_HEAT_SHORTFALL/SELF_CONSISTENT_FLOW_NOT_CONVERGED
remain excluded, since they are structurally unreachable from these tests' own setup regardless of
platform) and (b) a new companion test
(`test_thermal_pipeflow_not_converged_via_injected_solver_failure`, one per file) that monkeypatches
`pandapipes.pipeflow` to raise `PipeflowNotConverged` directly — a deterministic, platform-independent
unit proof of the exact `PipeflowNotConverged -> THERMAL_PIPEFLOW_NOT_CONVERGED` mapping, never
dependent on any BLAS/LAPACK backend's own numerical behaviour for a genuinely ill-conditioned input.
All four tests (2 originals, now broadened; 2 new deterministic companions) pass on macOS, and on
both Linux containers.

Both wheel-installation smoke tests (canonical, and the new joint site/connection one — see below)
were also run directly against a freshly built wheel in a Linux container, from an external run
directory with absolute `--config`/`--input`/`--provenance` paths (the exact shape `ci.yml`'s own
wheel-smoke-test step uses) and reproduced the exact golden `run_id` for each:
`r3chain-run-93d41133daa11d1a` (canonical) and `r3chain-run-99e7f5ea0fb38a12` (joint).

## A genuine bug found and fixed by this verification (not one of the six originally diagnosed)

Running the joint wheel smoke test for the first time (this phase's own new addition, TEST-037)
surfaced a real defect this specification's own diagnosis did not name:
`workflow/cli.py::_run_joint_study_v2_cli()` resolved `joint_study_v2.package_path` (and, downstream,
`economics.base_assumptions_package_relative_path`) against `Path.cwd()`. That default only ever
worked because every existing test and every documented local-dev invocation happens to run with
`cwd` already at the repository root — it silently breaks the moment the CLI is invoked from an
external run directory with an absolute `--config` path, which is exactly `ci.yml`'s own
wheel-smoke-test pattern. Reproduced directly (`JOINT_STUDY_PACKAGE_INVALID`, file-not-found, in a
throwaway Linux container) before being fixed: `package_root` is now derived from `--config`'s own
resolved path (`config_path.resolve().parent.parent` — every committed package-relative path is
written as `"config/<name>.json"`, i.e. relative to whatever directory contains that file's own
`config/` folder), never from the process's working directory. The identical fix was applied to
`mcp_server/server.py::build_server()`'s own `package_root` resolution for MCP-launched joint runs,
for the same reason. Re-verified fixed in the same Linux container before this document was written.

## Python 3.12 (REPRO-006, TEST-034)

`pandapipes` 0.14.0 (the only version this project's own `pandapipes>=0.14,<0.15` pin permits)
declares `Programming Language :: Python :: 3.12` on PyPI, as do `pydantic`, `mcp`, and `jsonpointer`
(this project's only other direct dependencies). Container B (Python 3.12, Linux/arm64) confirms this
in practice: the identical clean result as container A (1231/1232, the same single harness artifact,
all four hash tests passing). `.github/workflows/ci.yml`'s matrix now includes `ubuntu-latest` ×
Python 3.12 alongside `ubuntu-latest`/`macos-latest` × Python 3.11 — `requires-python = ">=3.11"` in
`pyproject.toml` was already honest (no upper bound was ever asserted); this closes the gap between
that claim and what had actually been tested. `macos-latest` is deliberately NOT tested against 3.12
in this change: that specific claim was not verified here, and adding it without evidence would
repeat exactly the mistake REPRO-003 warns against.

## Remaining verification

A third container (Linux/**amd64**, `--platform linux/amd64`, matching GitHub Actions'
`ubuntu-latest` runner architecture exactly rather than this host's native arm64) was started to
close the one remaining architecture gap. Docker Desktop on this Apple Silicon host translated it via
Rosetta (confirmed via `docker top`: the `python -m pytest -q` process ran under
`/run/rosetta/rosetta`, not QEMU). After **5 hours wall-clock / 4 hours 43 minutes of continuous CPU
time at 100% utilisation**, the test run had still not completed and had produced zero output --
roughly a 15-20x slowdown versus container A/B's own ~15-20 minute completion time for the identical
suite. This is disproportionate to the value of the data point (containers A/B already exercise a
genuinely different OS, libc, and BLAS/LAPACK backend than macOS -- the actual variable REPRO-002 is
concerned with; only the CPU instruction-set architecture itself remained untested, a narrower
question than the BLAS-backend one this document is otherwise built around). The container was
stopped rather than left running indefinitely on an unbounded timeline with no interim evidence to
show for it -- continuing to wait would not have been a genuine verification effort, only an
increasingly expensive guess that it would eventually finish and pass.

**Conclusion:** local amd64 emulation on this specific Apple Silicon host is impractical for this
project's own numerically-heavy test suite (regardless of whether the emulation layer is Rosetta or
QEMU) and is not a reliable path to the amd64 evidence this document set out to gather. The correct
mechanism for that specific, remaining architecture gap is a REAL `ubuntu-latest` GitHub Actions
runner (genuine x86_64 hardware, not emulated) -- exactly the job `.github/workflows/ci.yml`'s own
updated matrix will run once pushed. This session did not trigger that job (a push requires
authorisation separate from ordinary repository edits). Until it runs, the amd64-specific claim in
AC-J16 remains genuinely open, not assumed passing and not silently dropped -- recorded here, in
`docs/traceability-matrix.md`'s own Workstream K table, and in
`docs/decisions/decision-register.md` (IMPL-023) as PARTIAL for exactly this reason.

## What this does NOT claim

This is local Docker verification against this exact working tree, not a GitHub Actions run. It
substitutes genuine cross-platform execution (a different OS, libc, and BLAS/LAPACK backend, not
merely a different machine) for a claim that would otherwise remain untested-but-documented, exactly
as `hashing.py`'s own prior "honesty boundary" note distinguished. It does not claim bit-identical
byte hashes across every possible BLAS/LAPACK/compiler combination in existence — only that the
declared reproducibility boundary (`SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES`, 12 significant
figures) holds for the specific, real environments tested here.
