# T5.1C preliminary run — factual record

Status: **preliminary evidence of functional Claude/MCP orchestration** — accepted as such, not
the final Claude Desktop acceptance run. See `hash-diagnosis.md` for why this run's identifiers
diverge from the previously-pinned golden reference despite matching results.

## Provenance

- **Execution surface**: this Claude Code CLI session (not a separate Claude Desktop chat window)
  — see `mcp-log-excerpt.txt` and the note below.
- **Server**: `<USER_HOME>/.local/share/r3chain-geothermal-mcp/venv/bin/r3chain-geothermal-mcp-server`
  (the Desktop-facing venv, reinstalled 2026-08-30 from the working tree including that day's
  uncommitted doc-fix changes).
- **Server process PIDs**: 31473, 31474 (Python), plus wrapper PIDs 31470, 31472
  (`/Applications/Claude.app/Contents/Helpers/disclaimer --pgroup`) — all started 2026-08-30
  18:24:22 UTC (20:24 CEST), immediately after the user's full Claude.app quit+relaunch. Same
  process pair still running at time of writing.
- **Run created_at**: `2026-08-31T07:51:38.522077Z` (per `audit.json`).

## Source → destination

- **Source**: `<TEMP_RUN_ROOT>/r3chain-run-160ff2195378cdc4/` (server-side
  temporary registry root; not durable, would be deleted on clean server shutdown).
- **Destination**: `docs/evidence/t5.1c/2026-08-31-preliminary-code-run/bundle/` (this directory,
  untracked in git).
- **Copy integrity**: every file's SHA-256 verified identical between source and destination
  after copying (`diff` of sorted `shasum -a 256` output for both directories was empty).

## File inventory and hashes (SHA-256, as independently recomputed from the copied files)

| File | SHA-256 |
|---|---|
| `audit.json` | `2bdfa8b0b8eddd10862dd575147498fb44f80bfda192cfd5ca2e53b49dd0cbe1` |
| `candidate_comparison.csv` | `5a7e501b309e85c0c07c1ed194947ae6fe83acbc72aa54c7b3cc2b00153ef377` |
| `config_snapshot.json` | `2bdfd11dc901c6bdaf68f3d23516d85919ffa3f7d440ddcec46d6918b3d6e0c1` |
| `manifest.json` | `e3ab17d22981440d8ca0662e50158611099e709f95ca82a71303422f52c4860d` |
| `network_candidates.svg` | `6f43c948cc871679f1d7e26bbc065f4ba2cbe6b280ac66b2e547629e308513f3` |
| `pydoublet_input.json` | `34deec7c58480d59346adecfc15e17fd564c6648f6990843ebb6d5590caa11cf` |
| `recommendation.md` | `fca5f78619877720144e509146a77c71bf807fe0f6d56af1a3dacc28966a5774` |
| `workflow_result.json` | `9ca35362128de05832b0c447f8e59a0832a6660a14323064dc805b3b5d40e220` |

Every hash above matches what `manifest.json`'s own `files` section claims for that file
(cross-checked; `manifest.json` does not hash itself, by design — its own hash above is the
directory-listing hash I computed independently, not a self-referential claim).

`bundle_scientific_sha256` (from `manifest.json`): `e2f7ec8fa773d2f9bc14c58ec8d337b8dc793e2847d622f1b3a955a77c366f07`

**Cross-validation**: `candidate_comparison.csv`'s hash (`5a7e501b...`) is byte-identical to the
same file found in an unrelated, independently-discovered prior bundle
(`<TEMP_RUN_ROOT>/r3chain-run-487d97ddd667c3f0/`, created 2026-08-30T14:43:15Z,
predating this session) — confirming the candidate KPI output is a stable function of the
consumed scientific inputs, unaffected by the input-representation differences described in
`hash-diagnosis.md`.

## Tool-call chronology (11 calls, all successful)

1. `geo_get_capabilities`
2. `geo_validate_pydoublet_result` (trimmed payload — superseded by #3, kept for the record)
3. `geo_validate_pydoublet_result` (complete payload — authoritative)
4. `geo_run_workflow` → `run_id = r3chain-run-160ff2195378cdc4`
5. `geo_get_run_summary`
6. `geo_get_audit`
7. `geo_get_artifact` — `candidate_comparison.csv`
8. `geo_get_artifact` — `recommendation.md`
9. `geo_get_artifact` — `manifest.json`
10. `geo_get_artifact` — `workflow_result.json` (offset 0, page 1 of 2)
11. `geo_get_artifact` — `workflow_result.json` (offset 261045, final page, `next_offset: null`)

## Result summary (from the tool's own responses, not recalculated here)

- `workflow_status`: `completed`
- `preferred_candidate_id`: `C1`
- Ranking: C1 = 52.1714 EUR/MWh (rank 1), C2 = 52.2602 (rank 2), C3 = 52.3489 (rank 3),
  C4 = 52.4821 (rank 4) — all four feasible, `infeasible: []`
- Warnings: `PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED` on each of C1–C4 (verbatim
  text preserved in `bundle/audit.json` and `bundle/workflow_result.json`)
- Audit: 13/13 stage calls `status: "success"`

## Log evidence

`mcp-log-excerpt.txt` in this directory reproduces
`~/Library/Logs/Claude/mcp-server-r3chain-geothermal.log` lines 280–327: the post-restart clean
`initialize` → `notifications/initialized` → `tools/list`/`prompts/list`/`resources/list`
handshake, followed by exactly 11 `CallToolRequest` log lines (4, then 4 pandapipes
solve-warning pairs for candidates C1–C4, then 7 more) — matching the 11 calls above one-for-one.
