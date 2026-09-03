# R3-CHAIN handover note

**Purpose:** a self-contained state summary for a new assistant/session
picking up this project. It complements, and never overrides,
`CLAUDE.md` and `docs/R3_CHAIN_PyDoublet_pandapipes_Implementation_Plan.md`
— read those two first; they hold the actual project rules and scope.
This file exists so continuity survives a tool/session switch without
re-deriving everything from git history.

**Last updated:** 2026-08-22, mid-way through task T5.1C.

## Non-negotiable rules (from `CLAUDE.md` — do not relax these)

- Work on one approved task at a time; start every implementation task
  in plan mode.
- Never invent simulation results, feasibility decisions, costs, or
  rankings — deterministic Python code is the only authority for those.
- Keep PyDoublet / adapter / pandapipes evaluation / economics / MCP
  wrappers / presentation as separate layers.
- Every physical field carries an explicit unit; brine flow and DH-water
  flow are never conflated; raw PyDoublet power is never treated as
  automatically DH-deliverable.
- No destructive git commands; never commit/push/PR without being
  explicitly asked; stop and ask when a requirement is ambiguous.
- Report before editing (existing implementation, files to touch,
  acceptance criteria, tests, assumptions/risks) and after editing
  (changed files, commands/tests run, results, remaining limitations,
  any deviation from plan).

## Where the project stands

Six-week PoC plan, phases roughly map to what's shipped:

| Phase | Status |
|---|---|
| PyDoublet repair + coupling contract | Done (pre-existing history) |
| Adapter, synthetic network, candidate evaluator, gates | Done |
| Economics, ranking, presentation artifacts, deterministic CLI | Done |
| T5.1A — interim standalone MCP server (`mcp_server/`) | Done, committed |
| T5.1B — scripted MCP client (`mcp_client/`), Claude Desktop template, workshop prompt | Done, committed |
| **T5.1C — real Claude Desktop demonstration** | **In progress — see below** |
| T5.2 — official two-server topology decision | Not started |

Branch: `feature/r3chain-orchestration-poc`. Latest commit:
`a070d413947b7ae7524a062f8781fc56cb2ee9df`
("feat: add Claude-ready scripted MCP demonstration client").
Full test suite at that commit: **838 tests, all passing**
(`python -m pytest tests/ -q` from the repo root with
`.venvs/orchestration` activated — see Environments below; the wheel-build
tests in `test_wheel_install.py` and `test_optional_dependency.py` take
several minutes each).

## Architecture (unchanged, still the layering to preserve)

```
hashing -> contracts/parsers (PyDoublet parsing) -> adapter (HX coupling)
  -> network (synthetic DH network + candidates) -> economics (annuity, LCOH, ranking)
  -> workflow (orchestration, audit artifacts, presentation, CLI)
  -> mcp_server (thin geo_ tool wrappers over workflow, T5.1A)
  -> mcp_client (real MCP client + CLI fallback + Claude Desktop template + prompt, T5.1B)
```

`mcp_server`'s six tools (`geo_get_capabilities`,
`geo_validate_pydoublet_result`, `geo_run_workflow`, `geo_get_run_summary`,
`geo_get_audit`, `geo_get_artifact`) are thin wrappers with zero physics/
economics/ranking logic of their own — every number comes from
`workflow.run_workflow()`. `mcp_server.tools.summarize_workflow_result()`
is the one public `WorkflowResult`/`WorkflowFailure` -> `RunSummary`
mapping, reused by both the server and the client's CLI fallback so they
cannot silently drift.

## Environments (four, not one)

| Venv | Purpose | Install mode |
|---|---|---|
| `.venvs/pandapipesai` | pandapipesAI reference baseline | see `docs/baselines/` |
| `.venvs/pydoublet` | PyDoublet reference baseline | see `docs/baselines/` |
| `.venvs/orchestration` | **This package's own dev/test environment** — run tests, build wheels, iterate on code | editable, `pip install -e ".[dev,mcp]"` |
| `/Users/ishanthahewaratne/.local/share/r3chain-geothermal-mcp/venv` | **Claude-Desktop-only runtime** (new, T5.1C) | **non-editable**, `pip install "<repo>[mcp]"` |

The fourth venv exists because macOS blocks Claude Desktop (a GUI app)
from *executing* binaries located under `~/Documents` even with Full
Disk Access granted — file read/write access and execute permission are
governed separately for that folder. Direct Terminal execution of the
same script works fine; only GUI-app-spawned execution was blocked. The
fix was relocating the MCP server's runtime venv outside Documents
entirely, not touching any repo file.

**Consequence to remember:** that fourth venv is a **non-editable
snapshot** of the package. Any change to `src/r3chain_geothermal/`
(especially `mcp_server/`) will NOT be visible to Claude Desktop until
you re-run
`/Users/ishanthahewaratne/.local/share/r3chain-geothermal-mcp/venv/bin/python -m pip install --force-reinstall --no-deps "<repo path>[mcp]"`
(or equivalent) and fully restart Claude Desktop. It's easy to edit code,
retest against `.venvs/orchestration`, and forget the Desktop-facing copy
is now stale.

## Claude Desktop config

`~/Library/Application Support/Claude/claude_desktop_config.json` now has
an `mcpServers.r3chain-geothermal` entry pointing at the fourth venv's
`bin/r3chain-geothermal-mcp-server` (absolute path — intentionally never
added to the repo). Two timestamped backups exist alongside it from this
session's two edits (`.bak-20260822T033129Z`,
`.bak-20260822T040529Z`) — every other key in that file (Cowork/UI
preferences, etc.) was preserved untouched both times.

## Golden / pinned reference values

For `fixtures/pydoublet/repaired_result.json` +
`config/demo_source_provenance.json`, against the committed
`config/demo_assumptions.json`:

```
run_id                     = r3chain-run-93d41133daa11d1a
bundle_scientific_sha256   = 90f52416785f0ea8f7f8dc33ede68c9b5529e6e9d51dd60e8d2e1df0389b8d2f
C1 = 52.1714 EUR/MWh  (preferred)
C2 = 52.2602 EUR/MWh
C3 = 52.3489 EUR/MWh
C4 = 52.4821 EUR/MWh
```

These are pinned in `tests/mcp_server/test_tools.py` and
`tests/mcp_client/test_wheel_install.py`, and were independently
reproduced this session via a direct tools-layer smoke test run from the
new Desktop-facing venv. Any future change to `config/demo_assumptions.json`,
the golden fixture, or upstream physics/economics code will legitimately
move these numbers — if that happens, update the pinned tests and this
file together, deliberately, never as a silent side effect.

## Authoritative decisions (session-level; not yet written into `docs/decisions/phase0-questions.md`)

The user made these decisions explicitly in-session for T5.1C, overriding
the "pending" status still recorded in `docs/decisions/phase0-questions.md`:

- **Q1:** No separate PyDoublet-MCP server exists or will be built.
- **Q9:** The R3-CHAIN MCP server (`mcp_server/`) is the selected
  integration architecture — not a two-server topology.
- **Q10:** MIT is the selected licensing position. Do **not** modify
  upstream PyDoublet license files without separate authorization.
- **Q2:** The existing producer-wellhead temperature mapping (as
  implemented in code) is accepted.
- **Q7/Q8:** Proceed with the existing economic assumptions as configured.
- **Q11:** Proceed with the existing pressure threshold as configured.

**`docs/decisions/phase0-questions.md` itself still shows these as open
or only "technically resolved pending domain-owner confirmation."**
Updating that file to reflect the session-level decisions above is a
reasonable follow-up, but has not been done — it wasn't in scope for the
work performed so far.

## Known stale text — RESOLVED 2026-08-30

`mcp_server.tools.INTERIM_ARCHITECTURE_DISCLAIMER` was stale given the
Q1/Q9 decisions above. Fixed 2026-08-30 (separate "fix doc/code
contradictions" task, plan-mode approved): the constant now reads "The
R3-CHAIN MCP server is the selected one-server integration architecture
(Q1/Q9, decided): no separate PyDoublet-MCP server exists or will be
built for this project." Propagated by hand to the two places that do
**not** import the constant (`mcp_server/server.py`'s module docstring
and `SERVER_INSTRUCTIONS`, `README.md`'s static Markdown copy); confirmed
`mcp_client/prompt.py` and `runner.py` pick it up automatically since
they import the constant. `docs/decisions/phase0-questions.md` Q1/Q9 were
updated in the same pass to record this as decided rather than pending.
`config/demo_assumptions.json` was deliberately left untouched (it feeds
`config_sha256`/`run_id`/`bundle_scientific_sha256` — editing it would
have silently moved every pinned golden value in this file).

## T5.1C exact current state

Plan approved and being executed
(`~/.claude/plans/typed-painting-lemur.md` holds the full plan text).
Completed so far:

1. Backed up and edited Claude Desktop's config (twice — once to add the
   server, once to fix its path after the Documents-execution issue).
2. Diagnosed and fixed the "Operation not permitted" failure (see
   Environments above) by creating the fourth venv outside Documents.
3. Verified the new venv's executable/interpreter/package/config all
   resolve outside Documents, and reproduced the golden values via a
   direct tools-layer call (not yet via a live stdio MCP round-trip from
   Claude Desktop itself).

**Not yet done / waiting on the user:**

- Confirmation that a full Claude Desktop quit+relaunch shows all six
  `geo_` tools connected (log check: Claude menu → View Logs, or
  `~/Library/Logs/Claude/mcp*.log`).
- The actual live Claude Desktop conversation (the ready-to-paste prompt
  and the two input files — `fixtures/pydoublet/repaired_result.json`,
  `config/demo_source_provenance.json` — were already handed to the
  user). No real Claude Desktop tool-call output has been reported back
  yet; nothing about it should be assumed or fabricated.
- The documentation staleness sync (previous section) — identify done,
  fix not yet applied.

**Explicitly out of scope for T5.1C** (per the approved plan — do not
drift into these without a fresh approved task): fixtures, assumption
values, physics, economics, either nested repository
(`repos/pandapipesAI`, `repos/PyDoublet`), any repository commit, and
T5.2 (official two-server topology).

## If you are Codex (or any other assistant) picking this up

1. Read `CLAUDE.md` and the implementation plan doc in full before doing
   anything.
2. Check `git log`, `git status`, and this file's "T5.1C exact current
   state" section to see what's actually still open versus what's
   already committed.
3. Do not assume the Desktop-facing venv is in sync with the repo — if
   you touch `mcp_server/`, remember to reinstall into the fourth venv
   (see Environments) before claiming a Desktop-facing fix works.
4. Do not re-litigate the Q1/Q9/Q10/Q2/Q7/Q8/Q11 decisions above; they
   are session-authoritative even though `phase0-questions.md` hasn't
   caught up yet.
5. Follow the same one-task-at-a-time, plan-mode-first, no-fabricated-
   results discipline `CLAUDE.md` requires — nothing about this project's
   process has changed with the tool/session switch.
