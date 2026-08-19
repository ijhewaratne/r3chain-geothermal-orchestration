# MCP entry-point spike — findings (Sprint 1, 2026-08-19)

Diagnostic only: no source, packaging or test file changed; nested repos clean before
and after. Raw outputs (git-ignored, SHA-256 below): `artifacts/spike/`. Verified
against `repos/pandapipesAI` HEAD `a1fe3c6`, `.venvs/pandapipesai` (Python 3.11.16,
mcp 1.29.0 venv-only override — see `docs/baselines/pandapipesai-baseline.md`).

## 1. Does this PyDoublet snapshot contain an MCP server? — **No.**

`grep -ril "mcp|fastmcp|model context"` over every `*.py/*.toml/*.md/*.json` in
`repos/PyDoublet`: **0 hits**. There is no server, no client, no MCP dependency, and no
mention in docs. Statically conclusive for this snapshot.

## 2. Is PyDoublet-MCP a separate, unavailable repository? — **Unknown; only Dr. Jan can answer.**

Evidence trail: not in the workspace, not in the supplied archives/folders, no remote
recorded anywhere in the snapshot (pyproject URLs are `your-org` placeholders), nothing
publicly discoverable. This is exactly Phase-0 **Q1**; until answered, the fallback
plan (implementation plan §13: `pydoublet_run` / `pydoublet_get_result`) stands.

## 3. pandapipesAI MCP entry point and transport — **verified live.**

- Entry point: `pyproject.toml [project.scripts]` →
  `pandapipesai-server = pandapipesai.core.server:main` (equivalently
  `python -m pandapipesai.core.server`).
- Transports: `stdio` (default; wrapped in an instrumented stdout logger for the
  documented ~4-min-hang diagnosis), `sse`, `streamable-http` — selected by argv[1]
  (`core/server.py::main`, lines 1711-1728).
- Startup behaviour: fires a background daemon-thread warmup (`_start_background_warmup`)
  so the stdio handshake is reached immediately.
- **Live check (first attempt, no hang):** `initialize` → server `pandapipesAI`,
  reported version 1.29.0, protocol `2025-11-25`, instructions present →
  `tools/list` → **41 tools** → clean shutdown. Client: throwaway stdio script
  (`artifacts/spike/list_tools_client.py`), 120 s guard — not needed.

## 4. Startup command and environment variables

```bash
.venvs/pandapipesai/bin/pandapipesai-server            # stdio (default)
.venvs/pandapipesai/bin/pandapipesai-server sse        # HTTP-based clients
```

| Env var | Purpose | Required? |
|---|---|---|
| `PANDAPIPESAI_SESSION_DIR` | session snapshots directory | optional (default `<repo>/sessions`) |
| `PANDAPIPESAI_OUTPUT_DIR` | plot/export outputs | optional (default `<repo>/output`) |
| `PANDAPIPESAI_CACHE_DIR` | OSM disk cache base | optional (default `<repo>`) |
| `ASSETS_DB_PATH` | assets.duckdb for `nb_load_place` | required only for the nb_ pipeline's step 1 |
| `PANDAPIPESAI_DISABLE_ISOLATION` | test-suite bypass of the OS-subprocess isolation used for stuck-prone native calls (`core/isolation.py`) | leave unset in normal operation |

For the R3-CHAIN demo the three path vars should always be set explicitly (Claude
Desktop spawns servers with an arbitrary CWD — a documented upstream failure mode).

## 5. Registered tools — registry import vs. live `tools/list`: **exact match, 41/41**

Counts by layer: core 8, nb 8, tb 9, viz 3, ext 5, cm 5, en 3. Full sorted list in
`artifacts/spike/tools-list.json` / `registry-import.json`.

Demonstrator-relevant today: `core_session_status`/`core_list_sessions`/
`core_load_session` (session pattern to reuse), `cm_*` (ledger/annuity patterns the
`geo.*` economics will follow), `viz_plot_network*` (map output pattern).
**No `geo_` or PyDoublet-related tool exists yet** — confirmed gap, to be added as
`GEO_REGISTRY` + explicit `core/server.py` registration in Sprint 5 (plan §13).

## 6. mcp version requirement — **v1 API required today; 2.0.0 is a breaking release.**

- **pandapipesAI currently uses the MCP Python SDK v1 API** (`from mcp.server.fastmcp
  import FastMCP`, `core/server.py:39`, plus the v1 stdio server internals in
  `_run_stdio_instrumented`).
- **Primary evidence (local reproduction):** the unbounded pin `mcp>=1.0.0` resolved
  mcp 2.0.0 during the T1.2 install → `ModuleNotFoundError: No module named
  'mcp.server.fastmcp'` at test collection (recorded in
  `docs/baselines/pandapipesai-baseline.md`, log `03-pytest-no-network.log`).
- **Primary evidence (official release):** MCP Python SDK **v2.0.0**
  (github.com/modelcontextprotocol/python-sdk, releases/tag/v2.0.0, 2026-07-28) is a
  breaking API release: "`FastMCP` is now `MCPServer`", the underlying architecture was
  rebuilt, and v1.x enters maintenance mode. The official migration guidance for
  projects not yet migrated: "keep a `<2` upper bound on your requirement (for example
  `mcp>=1.28,<2`)".
- **mcp==1.29.0 is the verified temporary compatibility version** — it enabled all
  recorded T1.2 test results and this spike's live server run (venv-only; no repository
  file changed).
- **The permanent choice — pinning v1 (`mcp>=1.28,<2`) versus migrating to the v2
  `MCPServer` API — remains open** and belongs to a later packaging/compatibility task
  requiring Tanja's upstream coordination.
- (Secondary reference only, non-authoritative: third-party error write-ups such as
  Zuplo's describe the same failure mode.)

## 7. Smallest MCP path for the 15-September demonstration — recommendation (interim workshop architecture)

**Recommended: a minimal standalone FastMCP server in the orchestration repo** (working
name `r3chain-demo-server`), stdio transport, mcp 1.x — explicitly an **interim
workshop architecture**, exposing at most:
1. `geo_run_demo(config_path)` — runs the already-tested deterministic runner
   (PyDoublet or approved golden scenario → adapter → candidates → gates → ranking →
   output package) and returns the machine-readable summary + output paths;
2. `geo_get_result(run_id)` — returns a stored result;
3. (optional) `geo_get_audit(run_id)` — returns the audit trace path/summary.

Why this beats early `geo_` registration inside pandapipesAI's server: zero
pandapipesAI source changes before Sprint 5 (ADR-001 D7), a truthful thin wrapper over
tested deterministic code (D6: "smallest truthful MCP wrapper"), no exposure to the
documented transport-hang/registry-test surface, and the scripted client
(`run_mcp_demo.py`) plus Claude Desktop can both drive it. The full granular `geo_`
suite inside pandapipesAI (plan §13) remains the Sprint-5 target unchanged; this
wrapper is discarded or demoted to a fallback then.

**Scope of the claim:** this interim server can satisfy the 15-September requirement
for one external MCP invocation, deterministic execution, candidate evaluation, result
retrieval and audit retrieval. It must **not** be described as satisfying the final
PyDoublet-MCP ↔ pandapipesAI MCP-coupling objective.

> The standalone geo demonstration server is an interim workshop adapter around the
> deterministic runner. It does not by itself demonstrate coupling between the official
> PyDoublet-MCP and pandapipesAI MCP servers. The final topology remains pending Q1
> and Q9.

**Decision remains with Ishantha — this is a recommendation.**

## 8. Access/clarification needed from Dr. Jan (and Tanja)

1. **Q1 (Jan):** Does PyDoublet-MCP exist as a separate repo, and can we get access?
   If yes, its contract replaces the fallback `pydoublet_run`/`pydoublet_get_result`.
2. **Repo access (pending since T1.1A):** official pandapipesAI repository
   (`Digital-Energy-Intelligence-Lab/pandapipesAI` — private/unreachable anonymously).
3. **Q10 (Jan):** PyDoublet licence conflict (Apache-2.0 LICENSE vs. MIT metadata) —
   blocks any redistribution of wrapper code that vendors PyDoublet snippets.
4. **Q9 (Tanja+Jan):** confirm the intended final topology (two servers + external
   client); affects whether the workshop wrapper is one server or a client of two.

## Raw outputs (git-ignored), SHA-256

| File | Hash |
|---|---|
| `artifacts/spike/tools-list.json` | `33d042aee3e84f06cd16c024493adea9a058f51350186a8c33ad0541053a4f8d` |
| `artifacts/spike/server-stderr.log` | `5464541e457ea71476a5f0b55f81b53ca49cd34e28901652a3bdc2c42188407c` |
| `artifacts/spike/registry-import.json` | `101e3a6028178af7d7cae58f2a3c3ca01d0032a98ce484e2ba15f46cc3fc7bad` |
| `artifacts/spike/list_tools_client.py` | `a6adff881677bb8c46ca54ac8dc91d90a3dd1e2021b3c98a71d9c465bd7db543` |
