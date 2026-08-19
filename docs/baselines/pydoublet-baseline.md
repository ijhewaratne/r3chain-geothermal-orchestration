# PyDoublet baseline — T1.2 (2026-08-19)

Diagnostic record of the **unmodified** upstream import (`repos/PyDoublet`, HEAD
`4fb328dc4d7e035dad13ca60c43856072acedb8b`, clean before and after). Machine-readable
copy: `baseline-metadata.json`. Raw logs (hashed below): `artifacts/baseline/pydoublet/`
(git-ignored).

## Environment

| Item | Value |
|---|---|
| Platform | macOS 14.4.1 (23E224), arm64 (Apple Silicon) |
| Python | 3.11.16 (Homebrew `python@3.11`), venv `.venvs/pydoublet/` |
| pip / setuptools / wheel | 26.2.1 / 84.0.0 / 0.48.0 |

## Install

- Command: `pip install -e ".[dev]"` (per README/pyproject) — **exit 0**.
- `pip check`: clean. Full versions: `pydoublet-pip-freeze.txt`. Notable resolved
  versions far newer than the 2024-era code: numpy 2.4.6, pandas 3.0.5,
  matplotlib 3.11.1 (unpinned lower-bound-only requirements).
- The editable install *succeeds*, but the installed package is unusable (below).

## Behaviour probes (all from repo root unless noted)

| Probe | Exit | Result |
|---|---|---|
| `python -c "import pydoublet"` | 1 | `ModuleNotFoundError: No module named 'reservoir_config'` (`__init__` → `.scenario` → top-level internal import) |
| `python -c "from pydoublet import Scenario"` | 1 | same error |
| `python -m pydoublet.main --config examples/no_figures_config.json --no-figures` | 1 | same error (package `__init__` fails before `main.py` runs) |
| in-package: `cd pydoublet && python main.py --config ../examples/no_figures_config.json --no-figures` | 1 | `Error: No module named 'pydantic'` — **undeclared dependency** (`config_schema.py` imports pydantic; not in install requirements) |
| in-package, default params: `cd pydoublet && python main.py --no-figures` | 0 | **runs** (0.75 s); see below |

## Successful default-parameter run (finding: NOT the golden operating point)

Output: mass flow **41.002 kg/s**, geothermal power **7.694 MW**, COP **30.245**,
cp **3663.1 J/(kg·K)**, `temperature_profile_c[2]` **86.228 °C**.

The implementation plan's golden values (28.749 kg/s, 4.345 MW, COP 24.488, 76.313 °C)
belong to the `examples/no_figures_config.json` operating point (shallower 2200 m
reservoir, 200 mD), which is **currently unreachable** because every `--config` path
requires the undeclared pydantic. Golden-fixture capture (T1.3) therefore needs pydantic
available (venv-level) or the T1.4 repair first.

Also confirmed live: metadata bug — `actual_runs_completed: 1000` reported for one
deterministic run; `log.txt` created empty.

### Side effects of the successful run

| File | SHA-256 |
|---|---|
| `pydoublet/results/pydoublet_results_20260819_170539.json` | `d146332452524478f3ab8316715764e9fa78e820f4935a2af6e7251fc566a352` |
| `pydoublet/log.txt` (empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Preserved under `artifacts/baseline/pydoublet/side_effects/`, then removed from the
repo; `git status` clean afterwards.

## Tests

- Command: `python -m pytest tests/ -v --tb=short` — **exit 2**, elapsed 10.9 s.
- Collected 0 / passed 0 / failed 0 / skipped 0 / **errors 6** (collection interrupted).
- All six files (`test_doublet, test_fluid, test_pipe, test_reservoir, test_scenario,
  test_well`) error at collection: ImportError chains through the package's top-level
  internal imports (e.g. `from pydoublet.well import Well`, `from pydoublet.reservoir
  import Reservoir` — paths that don't exist) → all **pre-existing**.
- `tests_io.py` is never collected (filename matches neither `test_*.py` nor
  `*_test.py`).

## Classification summary (all pre-existing, none introduced by R3-CHAIN)

1. Top-level internal imports break every package-level import path (known defect,
   plan §7.3).
2. `pydantic` used but undeclared → the entire JSON-config path is dead (known).
3. `pyproject [tool.setuptools] packages=["pydoublet"]` omits subpackages (install
   nonetheless "succeeds" in editable mode; irrelevant while imports fail anyway).
4. Deterministic run reports 1000 completed runs (known metadata defect).
5. Test suite non-functional at collection (stale import paths).
6. No named producer-wellhead temperature field; only `temperature_profile_c[2]`.

## Raw-log hashes (SHA-256)

| Log | Hash |
|---|---|
| 00-pip-upgrade.log | `50d85d4457a5310f402c5af03e7a9418c3aeac900338744bbf3cfd8f99b2a4ed` |
| 01-install.log | `8472f884a1e2e732788763ed4bcca8288a7915d69cd5d58d49dd05ea2c7bfe50` |
| 02-pip-check.log | `9261363b733079a641c2e4cc9bc46ffa1d8336945a87f807b6cf68847dbc9b09` |
| 03-import-pkg.log | `8e59bda4136c8bdbba89a6551194174e6c4afcd1ec3ae54b2f75683087d115a1` |
| 04-import-scenario.log | `8e59bda4136c8bdbba89a6551194174e6c4afcd1ec3ae54b2f75683087d115a1` |
| 05-module-run.log | `a964b2ebc32de814fdb54453438c310807e9ae35ffa9b0658b0348e3d2ddbfaa` |
| 06-inpackage-run.log | `3ded12a5f590c9ee13fb2476c5326f3a11f89a903289d6e371332e090fb118de` |
| 07-inpackage-default-run.log | `8b4003759f22e27040163b73e1b2739d03b2c04dbe7f0e26eb56edd2fb770983` |
| 08-side-effects.sha256 | `adc98b7bb917ad1770d6f41dbc62a5b0a46046d6f9de12587fb2ed2b64c201ef` |
| 09-pytest.log | `5cab1acaf5ba243969cc4eec517c061339de0c275693bd47d50c7437e24a3037` |
