# T5.1C — clean Claude Desktop replay instructions

**How to use this document — read this first.** This file is instructions for *you*, not
something to attach anywhere. Two separate things happen with it:

1. **Attach as files** (drag/upload the actual files at the two paths below): the raw PyDoublet
   JSON and the provenance JSON. Never this `.md` file itself.
2. **Paste as chat text**: only the content inside the fenced ` ``` ` code block under "The exact
   prompt to paste" below — nothing above or below that fence.

(This distinction exists because an earlier attempt attached this document itself in place of
the JSON fixture — if you saved this file locally and dragged it in, that's exactly what
happened. Attach the two JSON files, paste only the fenced block.)

Status as of this evidence pass: the MCP server (Desktop-facing venv, reinstalled 2026-08-30)
exposes all six `geo_` tools with corrected disclaimer text — confirmed server-side via
`geo_get_capabilities`, re-verified directly against the running package code rather than by PID
(server process PIDs churn on every Claude.app restart and are not a meaningful freshness check
by themselves). **Whether the Claude Desktop *app* (not Claude Code) currently lists all six
tools in its own connector UI is something only you can confirm from inside that app** — open a
new chat there and check its tools/connectors list before pasting the prompt below. If it shows a
stale six-tool list or an error, quit and relaunch Claude.app again first.

## The two files to attach (unchanged, current canonical files)

- `<USER_HOME>/Documents/PhD/Aug 2026/r3chain-poc/fixtures/pydoublet/repaired_result.json`
- `<USER_HOME>/Documents/PhD/Aug 2026/r3chain-poc/config/demo_source_provenance.json`

## The exact prompt to paste (same vetted template, one addition)

```
You are connected to the r3chain-geothermal MCP server, which exposes six tools:

- geo_get_capabilities
- geo_validate_pydoublet_result
- geo_run_workflow
- geo_get_run_summary
- geo_get_audit
- geo_get_artifact

Use these tools for every step of evaluating a geothermal doublet result
against the candidate district-heating connection points. Call them in
this order: geo_get_capabilities first, then geo_validate_pydoublet_result
on the supplied raw PyDoublet result and its source provenance, then
geo_run_workflow, then geo_get_run_summary and geo_get_audit using the
run_id that geo_run_workflow returns, and finally geo_get_artifact
(paginated, using offset/limit) if you need to inspect a specific
artifact file such as candidate_comparison.csv or recommendation.md.

Hard rules -- do not deviate from these:

1. You MUST NEVER calculate, estimate, or approximate any physics,
   economics, feasibility, or ranking result yourself. Every technical
   or economic figure (temperatures, pressures, heat flows, LCOH,
   candidate ranking, feasibility) MUST come from a tool's own
   structured response. If a tool has not been called yet, do not guess
   its result -- call it.
2. You MUST preserve and report every warning a tool returns, verbatim.
   Never drop, summarize away, or silently ignore a warning.
3. You MUST state the following interim-architecture limitation exactly
   once, near the start of your response, before presenting any result:

   "This demonstrates Claude/MCP orchestration of the deterministic R3-CHAIN workflow. The R3-CHAIN MCP server is the selected one-server integration architecture (Q1/Q9, decided): no separate PyDoublet-MCP server exists or will be built for this project."

4. If a tool returns an error (a `status: "error"` response), report its
   exact `code`, `message`, and `stage` -- do not paraphrase it into a
   vaguer statement, and do not silently retry with different inputs
   unless the error is explicitly marked `recoverable`.
5. If geo_run_workflow completes with zero feasible candidates, or with
   `workflow_status: "stopped"`, state that plainly -- do not invent a
   recommendation. A completed evaluation with no feasible candidate, or
   a stopped workflow, is a valid, honest, fully audited result, not a
   failure to paper over.

When you are done, summarize: which candidate (if any) is preferred and
why (citing the tool's own ranking, never your own calculation), what
every rejected candidate's failure reason was, and any warnings that were
returned along the way.

For this acceptance run, geo_get_artifact is mandatory rather than
optional. Retrieve candidate_comparison.csv, recommendation.md,
workflow_result.json, and manifest.json, using pagination where
necessary. Finish with a chronological list of every MCP tool actually
called.
```

## Required clean sequence

1. `geo_get_capabilities`
2. **one complete** `geo_validate_pydoublet_result` (attach the two files directly; do not
   hand-retype their contents — the previous run's run-ID divergence from the golden reference
   traces exactly to hand-transcription of the JSON payload, see `hash-diagnosis.md` in this
   directory)
3. `geo_run_workflow`
4. `geo_get_run_summary`
5. `geo_get_audit`
6. `geo_get_artifact` for `candidate_comparison.csv`, `recommendation.md`, `manifest.json`, and
   `workflow_result.json` (with pagination)

## What NOT to do

Do not substitute another Claude Code session, the scripted MCP client, a direct Python import,
or a CLI run for this step — none of those satisfy the "real Claude Desktop chat" requirement.

## After you get a result

Give me the exact `run_id` Claude Desktop's response reports, before you close that chat/exit the
app — the server-side bundle is temporary and needs to be preserved while the server process is
still alive.
