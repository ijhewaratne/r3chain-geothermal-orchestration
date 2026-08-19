# pandapipesAI baseline — T1.2 (2026-08-19)

Diagnostic record of the **unmodified** upstream import (`repos/pandapipesAI`, HEAD
`a1fe3c6f6a73155f9ee50546b8af713014bfa695`, clean before and after). Machine-readable
copy: `baseline-metadata.json`. Raw logs (hashed below):
`artifacts/baseline/pandapipesai/` (git-ignored). Nothing in this baseline was
introduced by R3-CHAIN; every non-pass below is pre-existing repo/environment
behaviour on a fresh macOS machine.

## Environment

| Item | Value |
|---|---|
| Platform | macOS 14.4.1 (23E224), arm64 (Apple Silicon) |
| Python | 3.11.16 (Homebrew `python@3.11`), venv `.venvs/pandapipesai/` |
| pip / setuptools / wheel | 26.2.1 / 84.0.0 / 0.48.0 |

## Install

- Command: `pip install -e ".[dev,viz,costing]"` (repo pyproject extras; implementation
  plan §7.1) — **exit 0**; `pip check` clean.
- Key resolved versions: pandapipes **0.14.0**, pandapower **3.3.3** (the combination
  upstream CLAUDE.md documents as verified), osmnx 2.1.1, geopandas 1.1.4,
  networkx 3.6.1, duckdb 1.5.5, pydantic 2.13.4. Full list:
  `pandapipesai-pip-freeze.txt`.

## Environment/setup findings (classified, with remediation)

1. **`mcp` 2.0.0 breaks import** — the unbounded pin `mcp>=1.0.0` resolves to 2.0.0,
   which removed `mcp.server.fastmcp`; `tests/test_startup_warmup.py` then errors at
   collection and interrupts the whole run (first attempt: exit 2, log
   `03-pytest-no-network.log`). Classification: **pre-existing dependency-resolution
   failure** (missing upper bound), not a code/test defect. Remediation applied:
   venv-only `pip install "mcp>=1.0,<2"` → mcp **1.29.0**; **no repository file
   changed**. Both dependency states are part of this baseline: (a) the declared
   install resolved mcp 2.0.0 and broke collection; (b) the venv-only mcp 1.29.0
   compatibility override is what enabled the recorded test results. The override is
   a diagnostic enabler only, **not** the permanent dependency fix — that decision
   belongs to a later packaging/compatibility task.
2. **Test runs mutate a tracked file** — every pytest invocation regenerates
   `pandapipesai/special_modules/costing/data/_kww_flatdata_cache.json` (1-line diff).
   Classification: pre-existing repo behaviour (generated cache under version
   control). Handling: mutated copy + diff preserved
   (`mutated_kww_cache.json`, `04-kww-cache-mutation.diff`), file restored via
   `git checkout` after each run; repo ends clean.

## Primary baseline — no-network suite (repo's own documented run)

- Command: `python -m pytest tests/ -m "not integration" -v --tb=short`, with
  `PANDAPIPESAI_SESSION_DIR/OUTPUT_DIR/CACHE_DIR` redirected into artifacts (repo's
  own env-var mechanism; keeps the work tree clean).
- Result (with mcp 1.29.0): **exit 0 — 1152 passed, 0 failed, 0 skipped, 0 errors**,
  303 deselected (integration), 141.2 s.
- Reference: upstream CLAUDE.md records 821 passed / 4 failed on its Windows/conda
  environment — this macOS/venv baseline is strictly cleaner.

## Informational — integration suite (real OSM/Overpass network access)

- Command: same env, `-m integration` — exit 1, **272 passed, 2 failed, 29 errors**,
  1152 deselected, 140.7 s. Live Lohme OSM downloads succeeded.
- **All 31 non-passes share one root cause:** `RuntimeError: cache key
  '412112d820324909' not found under cache/osm/ … for Arnis` — costing tests
  (`test_sensitivity.py`, `test_explain.py`, `test_reference_tech*.py`) require a
  **pre-warmed OSM cache for "Arnis"** that ships with the developers' machines, not
  with the repo. Classification: **environment/setup dependency (missing prewarmed
  cache), pre-existing**; not code failures, not R3-CHAIN-introduced.
  (One additional failure, `test_missing_network_opex_defaults_raises_actionable_error`,
  is downstream of the same missing-cache fixture.)
- Caveat: integration results depend on Overpass availability and are not part of the
  PoC's no-network acceptance target.

## Raw-log hashes (SHA-256)

| Log | Hash |
|---|---|
| 00-pip-upgrade.log | `49c1438e1128a5bf71474d204bc8f96d714f371f28bd2f3fdb186f3269f68f94` |
| 01-install.log | `1dae59aa3c14321c6460efd15296cc6d5c397e13fc8d501723f5e49244bb41d2` |
| 02-pip-check.log | `9261363b733079a641c2e4cc9bc46ffa1d8336945a87f807b6cf68847dbc9b09` |
| 03-pytest-no-network.log (mcp 2.0.0 attempt) | `ce6b239187f98c72c198aee88f4533c30f56a37d06dde8b13714ead250886c56` |
| 04-kww-cache-mutation.diff | `46f8655332e4d09b71dd9467f1126599f55617b77be04a2fa3579b20e9d9d1cc` |
| 05-mcp-downgrade.log | `2877bc6de5f5db5637638fe14394a21623fd87f035a133f36cd9168c0e8f56b2` |
| 06-pip-check-after-mcp.log | `9261363b733079a641c2e4cc9bc46ffa1d8336945a87f807b6cf68847dbc9b09` |
| 07-pytest-no-network-mcp1.log | `6c793712f1ecd20a925a45867397d6906ab8745154d45f4d83597b4f03340909` |
| 08-pytest-integration.log | `a9732c1f045e934a8ecb04bd2d921b1e515688ac31875ec914b2947769f59cbf` |
