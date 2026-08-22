# R3-CHAIN PyDoublet–pandapipes proof of concept

Deterministic, auditable evaluation of candidate district-heating network
connection points for one already-computed geothermal doublet result. See
`docs/R3_CHAIN_PyDoublet_pandapipes_Implementation_Plan.md` for the full
scope, boundary, and six-week plan this package implements.

This package does **not** determine where to drill. It ranks network
**connection** locations for one fixed PyDoublet scenario.

## Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
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

## MCP server and scripted client (interim architecture)

> This demonstrates Claude/MCP orchestration of the deterministic
> R3-CHAIN workflow. It does not yet demonstrate communication between an
> official PyDoublet-MCP server and pandapipesAI's MCP server; that
> topology remains pending Q1 and Q9 (`docs/decisions/phase0-questions.md`).

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

## Layers

`hashing` → `contracts`/`parsers` (PyDoublet result parsing) →
`adapter` (heat-exchanger coupling) → `network` (synthetic district-heating
network and candidate evaluation) → `economics` (annuity, LCOH, ranking) →
`workflow` (orchestration, audit artifacts, presentation, CLI). Each layer
is independently tested; `workflow` sequences the others without
re-deriving or overriding any physical, technical, or economic result.
