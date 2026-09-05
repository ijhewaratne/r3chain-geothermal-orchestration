# R3-CHAIN PyDoublet–pandapipes proof of concept

Deterministic, auditable evaluation of a geothermal doublet's connection to a
district-heating network. Three modes exist, kept clearly distinct throughout every
artifact this package produces:

- **Canonical single-scenario mode** (`workflow/core.py`): ranks candidate DH
  network-**connection** points for **one** already-computed, fixed geothermal
  doublet result. Does **not** determine where to drill.
- **Synthetic joint site/connection-optimization mode, v1** (`workflow/joint_optimization.py`,
  see "A joint-optimization run" below): additionally varies a synthetic
  geothermal scenario/site axis, independently of the connection axis, and returns
  a Pareto shortlist rather than a single ranking. Every scenario is explicitly
  `synthetic=True` — it demonstrates the *methodology* for comparing candidate
  drilling sites, not a real drilling-site recommendation (no real geological/GIS
  data exists in this prototype; see "Limitations and the real-data boundary" below).
  Still available, unchanged, throughout the v2 correction below.
- **Corrected synthetic joint site/connection-optimization mode, v2**
  (`workflow/joint_workflow_v2.py`, see "A corrected joint site/connection run (v2)"
  below): the same synthetic-methodology demonstration as v1, corrected to link each
  resource scenario to an explicit, coordinate-bearing site, generate site-specific
  route geometry per site/attachment pair, and compare feasible alternatives with a
  materiality-aware Pareto policy. Same real-data boundary as v1 — still entirely
  synthetic, still never a drilling-site recommendation.

See `docs/R3_CHAIN_PyDoublet_pandapipes_Implementation_Plan.md` for the original
six-week plan, `docs/decisions/ADR-001-geothermal-poc-scope.md` (D9/D10 amendments) for
the scope history of both joint-optimization modes, and
`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md` for
v2's own authoritative, phase-by-phase target and current status.

## Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,mcp]"
python -m pytest -q
```

`dev` includes `build` (needed by `tests/mcp_client/test_wheel_install.py`, which builds and
installs a real wheel into a separate fresh venv as part of the suite) alongside `pytest`; `mcp`
is required for the MCP server/client console scripts and their own tests (both are skipped, not
failed, if omitted — `pytest.importorskip("mcp")`). `.github/workflows/ci.yml` runs this exact
sequence, plus a wheel build and a fresh-venv wheel-install smoke test, on both Ubuntu and macOS.

To build and smoke-test a wheel yourself, outside CI:

```bash
python -m build --wheel --outdir dist/
python -m venv /tmp/r3chain-wheel-smoke && source /tmp/r3chain-wheel-smoke/bin/activate
python -m pip install "$(ls dist/*.whl)[mcp]"
```

## One-command reproducible run

```bash
r3chain-geothermal-demo \
  --input fixtures/pydoublet/repaired_result.json \
  --config config/demo_assumptions.json \
  --provenance config/demo_source_provenance.json \
  --output-dir artifacts/demo
```

Installing the package (`pip install .` or `pip install -e .`) registers
`r3chain-geothermal-demo` as a console script; it can be run from any
directory, against any three matching JSON files.

Three different things are checked or handled, in this order, before a
bundle is written:

- **CLI-level validation, before `run_workflow()` is called at all**: each
  input file exists, is readable, is well-formed finite JSON (no
  NaN/Infinity), and is a JSON object; the provenance file additionally
  validates against the typed `SourceProvenance` schema; `--config`'s
  STRUCTURAL shape is checked by constructing every config-derived object
  `run_workflow()` itself builds, without running the workflow (a missing
  section or wrong field type raises the dedicated `WorkflowConfigurationError`);
  `--output-dir` is either absent, empty, or `--overwrite` was given. Any
  failure here maps to exit code 1 and writes nothing.
- **`run_workflow()`'s own typed outcome**: everything about the raw
  PyDoublet result's content (units, physics, energy consistency) and the
  network/candidate/ranking outcome — these produce a typed
  `WorkflowFailure`, never an exception, and map to exit code 2.
- **Anything else that still escapes `run_workflow()`**, now that `--config`
  has already been proven structurally valid: a solver defect or a
  genuine programming bug, kept distinguishable from a config/input
  problem as its own exit code (4), never silently folded into exit
  code 1.

If `--output-dir` already exists and is non-empty, the command refuses to
proceed unless `--overwrite` is given. The complete bundle is built in a
temporary sibling directory and published via a **staged, rollback-safe
replacement using same-filesystem renames** (not strictly crash-atomic:
the process could in principle be killed between the two renames): if
`--output-dir` already holds a previous bundle, that bundle is renamed
aside (never deleted) before the new one is swapped into place, and is
only removed once the swap succeeds — a publication failure this process
can catch, at any point, including one injected mid-swap, restores the
previous bundle unchanged and exits 3.

### Exit codes

| Code | Meaning |
|---:|---|
| 0 | The workflow completed and its bundle was published. This includes a completed evaluation with zero feasible candidates — a valid, honest result, never treated as an error. |
| 1 | A usage or input problem: bad/missing CLI arguments, a missing/unreadable file, non-finite or otherwise invalid JSON, a provenance file that fails schema validation, a structurally malformed `--config` file, or a non-empty `--output-dir` without `--overwrite`. Nothing is written. `--help`/`-h` also exits 0, not this code. |
| 2 | The workflow itself stopped (PyDoublet parsing, heat-exchanger coupling, blueprint construction, or baseline network evaluation failed). The failure's audit trail — the 4 core files plus `manifest.json` — is still published; there is no candidate/ranking data for the 3 presentation files to describe, so they are not written for this outcome. |
| 3 | Artifact publication failed after a result was already produced (e.g. disk full, permission denied, or a failure injected mid-swap). Any bundle previously published at `--output-dir` is left exactly as it was. |
| 4 | An unexpected internal failure inside `run_workflow()` itself, after `--config` was already proven structurally valid — a solver defect or a genuine programming bug, never conflated with exit code 1. |

## The published bundle

A **completed** workflow (exit 0, whether or not a candidate turned out
feasible) publishes all eight files below. A **stopped** workflow (exit 2)
publishes only the first five — `pydoublet_input.json`, `config_snapshot.json`,
`workflow_result.json`, `audit.json`, and `manifest.json` — since a
`WorkflowFailure` has no candidate or ranking data for the three
presentation files to describe.

| File | Contents |
|---|---|
| `pydoublet_input.json` | The raw PyDoublet result passed in, unchanged, canonically re-encoded. |
| `config_snapshot.json` | The assumptions config actually consumed by this run, unchanged. |
| `workflow_result.json` | The complete typed result: parsed PyDoublet result, heat-exchanger coupling, network blueprint, baseline evaluation, every candidate's outcome, and the final ranking. |
| `audit.json` | The same run's provenance and process trail: input/config/provenance hashes, ordered stage calls, every assumption set actually used, and collected warnings — also embedded verbatim inside `workflow_result.json`. |
| `candidate_comparison.csv` | One row per candidate (C1–C4, fixed order), every technical and economic KPI; an infeasible candidate's economic columns are left empty, never a fabricated value. |
| `network_candidates.svg` | A synthetic, non-geographical network schematic — supply/return trunks, consumers, and candidate connection points, each candidate's feasibility shown by marker shape (not colour alone) and detailed in an accompanying summary list. |
| `recommendation.md` | A deterministically templated summary: the preferred candidate (or an explicit "no candidate is feasible" statement), the ranked/rejected tables, and every scientific and economic caveat that applies to this run. |
| `manifest.json` | For every file above: its exact on-disk byte hash (`byte_sha256`, which legitimately varies run-to-run for `workflow_result.json`/`audit.json` because they embed wall-clock timestamps) and its normalized scientific-content hash (`scientific_sha256`, stable across independent runs of identical input). `bundle_scientific_sha256` summarizes the whole bundle's scientific content in one hash. |

Two independent runs against identical `--input`/`--config`/`--provenance`
always produce the same `run_id` and the same `bundle_scientific_sha256`,
even though `workflow_result.json`/`audit.json`'s own on-disk bytes are not
claimed to be byte-identical (they carry a real invocation timestamp).

## Alternative demonstrations

The canonical `config/demo_assumptions.json` above always evaluates the four hand-picked C1-C4
candidates. Three other configs, each a genuinely separate file (never a modification of the
canonical one — a different config produces a different `run_id`/`config_sha256` by design, never
a silent change to the canonical golden result), exercise different parts of the deterministic
workflow through the *same* CLI:

- **`config/demo_assumptions_workshop_negative.json`** — adds one deliberately infeasible fifth
  candidate (`C5_negative`, an excessive connection length) to the canonical C1-C4 set via
  `candidates.include_workshop_negative_demo`/`candidates.workshop_negative_demo`. Demonstrates the
  full failure-reporting path: an exact `PRESSURE_LIMIT_EXCEEDED` failure code, excluded from
  ranking, no invented economics — while C1-C4 remain numerically identical to the canonical run.
- **`config/demo_assumptions_generated_candidates.json`** — sets `candidates.mode="generated"`, replacing
  the candidate set entirely with `network.candidate_generation.generate_candidates()`'s own
  deterministic attachment × route search (every eligible trunk/consumer junction × direct/diverted
  route, screened with an exact, stable reason code for anything rejected — excessive route length,
  a protected zone, a missing junction) instead of the four hand-picked points. For this fixed
  synthetic topology: 16 combinations screened, 11 accepted, 8 feasible, 3 correctly rejected
  (`VELOCITY_LIMIT_EXCEEDED` at three consumer-adjacent attachments whose branch pipes are sized
  only for consumer demand). Optional `candidates.generated.max_candidates` caps the accepted set
  deterministically (first N by candidate ID). Known limitation, stated plainly rather than
  silently glossed over: a generated candidate's own connection-pipe-DN design axis is recorded but
  not yet consumed by the physics evaluator, which still uses one fixed DN for every candidate
  (`docs/issues/candidate-generation.md`).
- **A joint-optimization run (v1)** — **status: implemented, superseded for new work by v2 below,
  still available unchanged.** What's described below is what actually runs today
  (`workflow/joint_optimization.py`). A corrected v2 methodology (site-linked resource scenarios with
  real coordinates, site-specific route geometry, corrected `doublet_capex_multiplier` naming,
  materiality-aware non-duplicative Pareto objectives) is described in "A corrected joint
  site/connection run (v2)" below — consult
  `docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md` and
  `docs/decisions/ADR-001-geothermal-poc-scope.md` (D10) for that layer's own phase-by-phase status.
  Any config with
  `joint_optimization.enabled=true` (in addition to a `candidates.generated` block) dispatches the CLI
  to a genuinely different, full-product evaluation answering: *"Among the candidate geothermal
  doublet locations and associated network connections, which candidate provides the technically
  feasible minimum-cost/LCOH solution for supplying the four-consumer DH network?"* Every one of
  three synthetic geothermal scenarios
  (derived from the one golden PyDoublet result — this prototype cannot run real PyDoublet
  scenarios — by adjusting producer temperature, brine mass flow, doublet-pump power, and a
  declared drilling-CAPEX multiplier, one deliberately made heat-exchanger-infeasible) is paired
  with *every* accepted generated candidate — 3 × 11 = 33 alternatives for this topology, with **no
  curation**: the evaluated set size always equals the true, unfiltered search space, never a
  hand-picked subset presented without disclosing how large the full space actually is. Since no
  approved multi-objective weighting policy exists, the result is a **Pareto shortlist** of
  non-dominated alternatives, never an invented single ranking. Publishes its own,
  separately-hash-audited artifact bundle (`joint_optimization_result.json`,
  `generated_candidates.json`, `screened_alternatives.json`, `alternative_comparison.csv`,
  `pareto_or_ranking.json`, `joint_recommendation.md`, `manifest.json`) at the same `--output-dir`.
  This is a **synthetic scenario/connection/design comparison**, explicitly labelled as such in
  every artifact — never a geological drilling-site recommendation, and never confused with the
  canonical single-scenario C1-C4 comparison, which a joint-optimization config never touches.
  `docs/issues/joint-optimization-workflow-integration.md` has the full design rationale, including
  why this is a separate top-level entry point rather than a mode inside the single-scenario
  workflow (a Pareto shortlist cannot honestly be forced into a single-ranking result shape).

- **A corrected joint site/connection run (v2)** — **status: Phases 1–9 of
  `docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md` implemented
  (contracts/terminology, site-linked scenarios and routes, executable per-design connection
  diameters, corrected economics/materiality-aware Pareto decision policy, the primary
  CLI/audit-bundle workflow with the complete §17 artifact set, MCP dispatch and persistent-registry
  rehydration, cross-platform reproducibility diagnosis and correction against real CI evidence, and
  documentation reconciliation); the one remaining item is a fresh green three-job GitHub Actions run
  confirming the corrected code on real `ubuntu-latest`/`macos-latest` hardware — see
  `docs/traceability-matrix.md`'s own "Phase 9 release-candidate verification" section and
  `docs/issues/cross-platform-reproducibility.md` for the exact current status.** Corrects the
  specific methodological gaps `workflow/joint_optimization.py` (v1)
  never addressed (spec §2.5): `surface_site_id` is now an explicit, coordinate-bearing
  `SurfaceSite`, not a bare label; each `GeothermalResourceScenario` links to exactly one site (one
  site may carry several scenarios); routes are generated per site/network-attachment pair from
  actual site coordinates, so the SAME attachment reached from two different sites has two different,
  independently-measured route lengths and costs — never one global route reused regardless of
  origin; only *compatible* (same-site) scenario/route combinations are ever evaluated, never a blind
  Cartesian product; connection-pipe diameter is threaded all the way into the pandapipes evaluation
  (not recorded-but-ignored); and the Pareto objective set was corrected to remove mathematically
  dependent quantities, with materiality thresholds so a below-threshold numerical difference no
  longer creates false dominance. Reachable identically from the CLI
  (`joint_study_v2.enabled=true` + `joint_study_v2.package_path` pointing at a committed
  `JointStudyPackage` JSON file — see `config/demo_assumptions_joint_study_v2.json` and
  `config/joint_study_synthetic_v2.json`) and from `geo_run_workflow` (the SAME six-tool MCP server,
  a discriminated `workflow_mode: joint_site_connection` success shape, no seventh tool). Publishes
  its own, separately-hash-audited artifact bundle -- the complete
  specification §17 set (`resource_input_index.json`, `sites.json`, `resource_scenarios.json`,
  `joint_study_snapshot.json`, `screened_site_connection_routes.json`, `site_route_geometry.json`
  (declares the synthetic Cartesian coordinate basis explicitly), `compatible_alternatives.json`,
  `joint_optimization_result.json`, `alternative_comparison.csv`, `objective_policy.json`,
  `pareto_or_ranking.json`, `network_candidates.svg` (a synthetic-labelled schematic diagram, never
  implying real geographic/GIS accuracy), `joint_recommendation.md`, `audit.json`, `manifest.json`,
  `pydoublet_input.json` and `config_snapshot.json`) at the same `--output-dir`, and survives
  an MCP server restart via the same persistent-registry rehydration path the canonical workflow
  already uses. Every artifact carries the same synthetic disclaimer v1's own artifacts do — this
  remains a **synthetic scenario/site/connection/design comparison**, never a geological
  drilling-site recommendation, and the canonical single-scenario C1-C4 comparison is untouched by
  any `joint_study_v2` config.

Try it directly:

```bash
r3chain-geothermal-demo \
  --input fixtures/pydoublet/repaired_result.json \
  --config config/demo_assumptions_workshop_negative.json \
  --provenance config/demo_source_provenance.json \
  --output-dir artifacts/workshop-negative-demo

r3chain-geothermal-demo \
  --input fixtures/pydoublet/repaired_result.json \
  --config config/demo_assumptions_generated_candidates.json \
  --provenance config/demo_source_provenance.json \
  --output-dir artifacts/generated-candidates-demo

# Corrected joint site/connection run (v2) -- can be run from ANY working
# directory: joint_study_v2.package_path is resolved relative to --config's
# own file location (config_path.resolve().parent.parent), never the
# process's cwd, so this works identically from the repository root (as
# below) or from a completely external run directory, e.g.
# --config "$(pwd)/config/demo_assumptions_joint_study_v2.json".
r3chain-geothermal-demo \
  --input fixtures/pydoublet/repaired_result.json \
  --config config/demo_assumptions_joint_study_v2.json \
  --provenance config/demo_source_provenance.json \
  --output-dir artifacts/joint-study-v2-demo
```

## Strict input-provenance validation

By default, the raw PyDoublet result's own content is trusted as given (its physics/units are still
independently validated — that never changes). To additionally pin the EXACT raw bytes a caller
expects, pass `expected_raw_sha256` (a lowercase 64-hex-character SHA-256, matching
`canonical_raw_result_sha256()`'s own canonical-JSON encoding) via `SourceProvenance` (library/MCP
level) or `SourceProvenanceInput` (the `geo_validate_pydoublet_result`/`geo_run_workflow` MCP tool
argument) — `contracts.SourceProvenance.expected_raw_sha256` and
`mcp_server.schemas.SourceProvenanceInput.expected_raw_sha256`. Omitted (the default) is
byte-for-byte behaviorally identical to this feature not existing at all. When supplied and it does
not match the actual computed hash, the server returns `PYDOUBLET_RAW_HASH_MISMATCH` and — for
`geo_run_workflow` specifically — creates NO artifact directory at all: a provenance mismatch means
the caller did not send the input they believed they were sending, so nothing about that attempt is
persisted as an audited scientific result. This is a library/MCP-level feature only — the CLI above
does not expose an `--expected-hash` flag (`tests/mcp_server/test_input_provenance_mcp.py`,
`tests/parsers/test_input_provenance_enforcement.py`).

## MCP server and scripted client (interim architecture)

> This demonstrates Claude/MCP orchestration of the deterministic
> R3-CHAIN workflow. The R3-CHAIN MCP server is the selected one-server
> integration architecture (Q1/Q9, decided): no separate PyDoublet-MCP
> server exists or will be built for this project
> (`docs/decisions/phase0-questions.md`).

Installing with the optional `mcp` extra (`pip install -e ".[dev,mcp]"`)
registers two more console scripts:

- **`r3chain-geothermal-mcp-server`** — a standalone stdio MCP server
  exposing six `geo_` tools (`geo_get_capabilities`,
  `geo_validate_pydoublet_result`, `geo_run_workflow`,
  `geo_get_run_summary`, `geo_get_audit`, `geo_get_artifact`), each a
  thin wrapper over the same `run_workflow()`/`write_workflow_artifacts()`
  functions the CLI above calls — no physics/economics/ranking logic of
  its own.
- **`r3chain-geothermal-mcp-demo`** — a scripted MCP client that launches
  the server over stdio and runs the exact eight-step demonstration
  sequence (`initialize` → `tools/list` → the six tools in order, with
  `geo_get_artifact` paginated), publishing a compact
  `session_record.json` (tool order, compact inputs/outputs, warnings,
  `execution_route`, and a deterministic recommendation — never the raw
  PyDoublet result, an absolute path, or environment data):

  ```bash
  r3chain-geothermal-mcp-demo \
    --input fixtures/pydoublet/repaired_result.json \
    --provenance config/demo_source_provenance.json \
    --output-dir artifacts/mcp-demo \
    [--enable-cli-fallback]
  ```

  `--enable-cli-fallback` opts in to a deterministic, non-MCP fallback
  path (the same `run_workflow()`/`write_workflow_artifacts()` functions,
  called directly) used ONLY when the MCP transport itself fails to
  start or breaks mid-session — never for a typed workflow/domain
  outcome (a stopped workflow, or zero feasible candidates, is always a
  valid, fully audited `execution_route: "mcp"` result) and never for a
  malformed/unexpected server response (the wrong tool set, a payload
  that fails schema validation, or a paginated artifact whose content
  does not match its own recorded hash — a client-side or server-side
  bug, never silently masked by a fallback run). There is no
  `--server-command` flag; the launch command is fixed internally.

  `R3CHAIN_MCP_CONFIG_PATH` is a **server-operator/test launch setting
  only** — read once, by `r3chain-geothermal-mcp-server` itself, at
  process startup. It is never a `geo_` tool argument and never a
  scripted-client (`r3chain-geothermal-mcp-demo`) argument; a client can
  observe which config a running server actually loaded via
  `geo_get_capabilities`'s `demo_assumptions_config_sha256`, which always
  reflects that server process's own active configuration.

### Claude Desktop

Add this to your own `claude_desktop_config.json` (uses the installed
command name — no machine-specific path to edit):

```json
{
  "mcpServers": {
    "r3chain-geothermal": {
      "command": "r3chain-geothermal-mcp-server",
      "args": []
    }
  }
}
```

`r3chain_geothermal.mcp_client.claude_desktop.render_claude_desktop_config_json()`
renders this same template programmatically.
`r3chain_geothermal.mcp_client.prompt.render_workshop_prompt()` renders a
ready-to-paste prompt instructing Claude to use the six tools for every
technical/economic/ranking decision, never to compute one itself, to
preserve every warning verbatim, and to state the interim-architecture
limitation above. This is a **Claude-ready scripted MCP demonstration**
— the scripted client (`r3chain-geothermal-mcp-demo`) is what has
actually been run and verified end-to-end; the config/prompt are
ready-to-use artifacts for a live Claude Desktop session, which is a
separate, human-driven step.

### Persistent run registry (restart recovery)

By default (`R3CHAIN_RUN_ROOT` unset), a server's run registry is ephemeral: every run lives only
for that process's lifetime, in a temporary directory deleted on shutdown — identical behavior to
every earlier version of this project. Setting `R3CHAIN_RUN_ROOT=/some/stable/path` before starting
`r3chain-geothermal-mcp-server` makes the registry **persistent**: completed runs survive a server
restart. On startup, the server scans that directory's immediate children and rehydrates any that
validate as complete, correctly-named, hash-consistent run bundles — anything corrupt, incomplete,
or tampered with is skipped (never crashes startup) and recorded in a diagnostic warning list, never
silently re-run. A rehydrated run is served from disk on the next `geo_run_workflow` call for the
same input (`reused_existing_run: true` in the response) rather than recomputed, and every artifact
— including full pagination through a multi-page file — works identically to a freshly computed run.

Two independent, ORTHOGONAL retention controls bound how many runs a persistent registry keeps:
`max_size` (an LRU count bound — the oldest unpinned run is evicted, from memory AND disk, once the
bound is exceeded) and the newer `max_age_days` (age-based, applied only at startup rehydration,
`None`/disabled by default so it can never unexpectedly discard evidence unless a caller explicitly
opts in with a positive value — a pruned run is recorded in the same startup warning list, never
silently deleted with no trace).

### Artifact retrieval and pagination

`geo_get_artifact(run_id, filename, offset=0, limit=<default>)` returns one slice of a named
artifact file's text content, plus `total_length` and `next_offset` (`null` once the end of the file
has been reached). To retrieve a large file in full, loop: pass the previous response's
`next_offset` as the next call's `offset` until `next_offset` comes back `null`, then concatenate
every `content` chunk in order. `limit` is bounded (`1..16384` characters per call); `filename` must
be one of the fixed, allowed artifact names for that run (never an arbitrary path) —
`geo_get_capabilities`'s own `allowed_artifact_filenames` lists them.

## Limitations and the real-data boundary

This is a **synthetic proof of concept**. Every network, every geothermal scenario besides the one
golden PyDoublet result, and every generated/screened candidate is deliberately invented for this
demonstration. Concretely, this project does **not**:

- Use, reference, or fabricate any real Wuppertal (or any other real place's) network, geological,
  or economic data. `data_contracts/` defines the TYPED CONTRACTS a real study package would need
  to satisfy (network topology, pipe attributes, CRS-declared spatial layers, geothermal scenarios,
  economic line items, provenance/licensing, approval status) and a mandatory readiness gate
  (`enforce_real_data_readiness()`) that any future real-data caller must pass before proceeding —
  but no code path anywhere in this repository actually ingests real data today. Verified directly:
  no reference to `DatasetClassification.REAL` exists in `network/blueprint.py`, `workflow/core.py`,
  or `workflow/joint_workflow.py`.
- Make a real geological drilling-site recommendation. The **canonical mode** ranks/Pareto-compares
  network connection points for one already-computed, already-fixed doublet result only. The
  **joint-optimization mode** additionally varies a synthetic geothermal scenario/site axis
  (`workflow/joint_optimization.py`) — demonstrating the methodology for comparing candidate
  drilling sites against real data, once real data exists — but every scenario it evaluates is
  explicitly `synthetic=True`, derived from the one golden PyDoublet result, never an independent
  real drilling-site simulation. Real drilling-location optimization stays gated behind
  `data_contracts.readiness.drilling_location_optimization_permitted`, never satisfied by any code
  path in this repository today. Both facts are stated explicitly in every `recommendation.md`/
  `joint_recommendation.md` this project produces.
- Claim a validated commercial cost basis. Every economic figure (CAPEX, O&M, interest rate,
  electricity/auxiliary-heat prices) is a labelled `demo_assumption` placeholder in
  `config/demo_assumptions.json`, not a researched market value — see that file's own
  `docs/config-field-classification.md` for exactly which of its fields are actually consumed by
  the economics calculation versus purely descriptive.
- Vary a generated candidate's connection-pipe diameter in the actual physics evaluation (recorded
  as metadata, not yet consumed — a documented, deliberate limitation, not silently absent).

## Layers

`hashing` → `contracts`/`parsers` (PyDoublet result parsing) →
`adapter` (heat-exchanger coupling) → `network` (synthetic district-heating
network and candidate evaluation) → `economics` (annuity, LCOH, ranking) →
`workflow` (orchestration, audit artifacts, presentation, CLI). Each layer
is independently tested; `workflow` sequences the others without
re-deriving or overriding any physical, technical, or economic result.
