# PyDoublet repaired-result fixture — provenance (T1.5A, 2026-08-20)

## What this is

The output of the **repaired** PyDoublet (post T1.4A–T1.4C2), run on the same
unchanged `examples/no_figures_config.json` used for the T1.3 pristine
fixture, captured for T1.5's `PyDoubletCouplingResult` parser development.
Companion to `fixtures/pydoublet/raw_result.json` (pristine, untouched) —
together the two files exercise both the "current" and "recognized legacy"
paths of the ADR-002 fallback policy.

- `repaired_result.json` — verbatim output, no manual field insertion.
- This file — full execution record.

## Execution record

| Item | Value |
|---|---|
| PyDoublet commit | `0d649c3e6930d342dac03654d57776e134c2d0b9` (throwaway clone under `artifacts/t1.5a/pydoublet-clone`; `repos/PyDoublet` itself never executed in, confirmed clean before and after) |
| Config | `examples/no_figures_config.json`, **unchanged**, SHA-256 `d847fa16e2ca17184693cdd5d802d01f39bfb81fab0e8b92ad835c7b1821543b` (identical to the T1.3 capture's config hash — re-verified) |
| Command | `PYTHONPATH=<clone> python -m pydoublet.main --config <clone>/examples/no_figures_config.json --no-figures --result-file <run-dir>/repaired_result.json` (the T1.4B `--result-file` explicit-path flag; the T1.3-era `cd pydoublet && python main.py` invocation **no longer works** post-T1.4A's import repair — direct-file execution fails with `ImportError: attempted relative import with no known parent package`, confirmed live during this capture, corrected to the supported `-m` invocation) |
| Exit code / elapsed | 0 / 0.75 s |
| Python | 3.11.16 (Homebrew `python@3.11`), macOS 14.4.1 arm64, venv `.venvs/pydoublet` |
| Dependencies | pydantic 2.13.4, pydantic_core 2.46.4, numpy 2.4.6, scipy 1.17.1, pandas 3.0.5, matplotlib 3.11.1 (same environment as the T1.4 series; no new install needed — pydantic already present from T1.3) |
| Repo integrity | `repos/PyDoublet` at `0d649c3e`, status clean before and after; throwaway clone also ended clean |

## Verification results

- **All seven golden scientific fields bit-identical** to
  `fixtures/pydoublet/golden_fixture.json` (relative difference `0.0` for
  every field: brine mass flow, producer wellhead temperature, reinjection
  temperature, geothermal thermal power, doublet pump power, COP, brine heat
  capacity).
- **Structural diff against the pristine fixture — exactly three
  differences, nothing else** (full recursive key/value walk, 74 pristine
  leaves vs. 75 repaired leaves):
  1. `/metadata/timestamp` — nondeterministic (expected).
  2. `/simulation_parameters/actual_runs_completed`: `1000` → `1` (T1.4C1
     correction, `afdb036f`).
  3. `/simulation_results/producer_wellhead_temperature_c` — new, additive
     (T1.4C2, `4b29d1a0`); absent in pristine, present here, value
     `76.31304410943065` — bit-identical to the pristine's
     `/simulation_results/temperature_profile_c/2`.
- **Pristine fixture confirmed untouched**: `fixtures/pydoublet/raw_result.json`
  hash `ed73b0eba885670d46a5e7871d3d3f4c12b8fedf15a9a9fb5b134586aa5bafbe`,
  identical before and after this capture.

## Ignored evidence under `artifacts/t1.5a/` — SHA-256

| File | Hash |
|---|---|
| `run1/repaired_result.json` (= `fixtures/pydoublet/repaired_result.json`) | `b70bd85a95f49c552733ada4eb656b6c551ba2ab61027d8f9c915d3e26fdc7e8` |
| `run1/run.log` | `40f273b0010efdbbfe423903c2ed29acd5b724181704a165df702ff78845cb5d` |
