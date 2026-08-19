# PyDoublet golden fixture — provenance (T1.3, 2026-08-19)

## What this is

The frozen behaviour of the **pristine** PyDoublet baseline (commit
`4fb328dc4d7e035dad13ca60c43856072acedb8b`, before the T1.4 packaging/contract
repair), run on `examples/no_figures_config.json`, captured as:

- `raw_result.json` — verbatim run-1 output (original keys, values, metadata; nothing
  renamed, nothing corrected).
- `golden_fixture.json` — canonical mapping to named quantities with units, source-key
  provenance, derived tolerances, and reproduced-defect flags.
- `comparison_report.json` — machine-readable 3-run comparison, anchor verification,
  derived tolerances, energy-consistency diagnostic.

It is a regression reference, not a universal project design point.

## Execution record

| Item | Value |
|---|---|
| PyDoublet commit | `4fb328dc4d7e035dad13ca60c43856072acedb8b` (throwaway clone under `artifacts/t1.3/pydoublet-clone`; clean repo never executed in) |
| Config | `examples/no_figures_config.json`, **unchanged**, SHA-256 `d847fa16e2ca17184693cdd5d802d01f39bfb81fab0e8b92ad835c7b1821543b` |
| Command (per run) | `.venvs/pydoublet/bin/python <clone>/pydoublet/main.py --config <clone>/examples/no_figures_config.json --no-figures`, CWD = `artifacts/t1.3/run{1,2,3}/` (three separate clean output dirs; `sys.path[0]` = script dir resolves the in-package imports) |
| Exit codes / durations | run1: 0 / 0.94 s · run2: 0 / ~0.9 s · run3: 0 / ~0.9 s (exact values in `comparison_report.json`) |
| Python | 3.11.16 (Homebrew `python@3.11`), macOS 14.4.1 arm64, venv `.venvs/pydoublet` |
| Base dependencies | `docs/baselines/pydoublet-pip-freeze.txt` (numpy 2.4.6, scipy 1.17.1, pandas 3.0.5, matplotlib 3.11.1) |
| Dependency delta for this task | `pydantic==2.13.4`, `pydantic_core==2.46.4`, `annotated-types==0.8.0`, `typing-inspection==0.4.4` |
| Repo integrity | `repos/PyDoublet` at `4fb328d`, status clean before and after; throwaway clone also ended status-clean (all outputs landed in run CWDs) |

## Pydantic environment-only override — rationale

PyDoublet's `--config` path requires pydantic via `config_schema.py`, but pydantic is
**not declared** in its dependencies (reproduced baseline defect, see
`docs/baselines/pydoublet-baseline.md`). Per decision (2026-08-19): pinned
**`pydantic==2.13.4`** installed into `.venvs/pydoublet` only — chosen because the code
uses the pydantic-v2 API (`model_dump`, `ConfigDict`) with deprecated V1-style
`@validator`s, 2.13.4 was verified compatible (deprecation warnings only), and it
matches the pandapipesai venv exactly (no cross-environment drift). **No PyDoublet
packaging or source file was modified**; declaring the dependency properly is T1.4
scope.

## Reproducibility result

- **All scientific fields bit-identical across the three runs** — observed
  scientific-field variation: **zero** (`abs_spread = 0.0` for every field).
- **Tolerance scope:** the derived per-field relative tolerance of `1e-11`
  (numerical floor × safety 10; no observed spread to widen it) is a
  **same-platform, fully pinned-environment regression tolerance** (macOS 14.4.1
  arm64, Python 3.11.16, dependency set above). It is **not yet claimed as a
  cross-platform tolerance**; a portable tolerance must be confirmed on another
  clean machine during Sprint 6.
- Timestamps, file paths and other transport metadata are excluded from scientific
  equality comparisons but remain untouched in `raw_result.json`.
- Raw JSON files differ across runs **only** in nondeterministic transport metadata:
  `metadata.timestamp` and the timestamped results filename (hence differing file
  hashes below). These fields are listed in `comparison_report.json →
  nondeterministic_fields` and excluded from scientific comparison; they are **not**
  stripped from `raw_result.json` (verbatim preservation).
- **Anchor verification passed** — all seven anchors within 1e-5 relative (threshold
  0.1 %): 28.749278 kg/s, 76.313044 °C, 35.0 °C, 4345.417312 kW, 177.449827 kW,
  COP 24.488146, cp 3658.620334 J/(kg·K). No stop condition triggered; no tuning done.
- **Energy-consistency diagnostic:** reported power equals ṁ·cp·(T_prod − T_reinj) to
  machine precision (relative residual 2.1e-16) — expected, since
  `calc_power_data()` computes it from exactly these quantities. Diagnostic only;
  reported value untouched.
- **Reproduced defect (not corrected):** `simulation_parameters.actual_runs_completed
  = 1000` for a single deterministic run — present verbatim in `raw_result.json`,
  flagged in `golden_fixture.json → reproduced_defects`. Correction is T1.4 scope.
- Known caveat: `producer_wellhead_temperature_c` is extracted from
  `temperature_profile_c[2]` (node `"5&6, Prod_Top/Entry_HE"`) — provisional pending
  Phase-0 Q2.

## Ignored evidence under `artifacts/t1.3/` — SHA-256

| File | Hash |
|---|---|
| run1/results/pydoublet_results_20260819_213215.json (= raw_result.json) | `ed73b0eba885670d46a5e7871d3d3f4c12b8fedf15a9a9fb5b134586aa5bafbe` |
| run2/results/pydoublet_results_20260819_213216.json | `51a1bd5c56c36a308049993b226790f9d6c0f2a1f25a8e4192e65f9e9d088e80` |
| run3/results/pydoublet_results_20260819_213217.json | `4fd0d573d84b815847ac8b55b9fc213525d46c28fd9284f48f214ce69f0f9e87` |
| run1/run.log | `f89ddc8885f332eee9d1434aa8169c92281910d2983574f4cb74a6cd731168d1` |
| run2/run.log | `456c73c08f1f8416760c4d14d4ee4faab3a54d66f95d9c127723b7f029f5f3a6` |
| run3/run.log | `41a9e96ef9b53f6ccbff443a07662f0f1fe519c1e4906fe46090ebbe240dc22c` |
| pydantic-install.log | `294e690e9b8cc2485393729fc140d94affc9603d749c7cd19805d22cc4bfe841` |
| freeze-before.txt | `d2f2510cb37c6c1fef8ae9dd6a8563df5b402e7bfe526c208ccb228ec8165779` |
| freeze-after.txt | `8196696aa6504e4abe35fcf5b7390a4c85e5202939e1db9beacb2c8ab9594a76` |

(Each run dir also contains an empty `log.txt` created by PyDoublet's logger — the
empty-file hash `e3b0c442…`, already documented in the T1.2 baseline.)
