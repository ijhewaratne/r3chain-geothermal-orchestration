# ADR-001 — Scope and governing decisions of the R3-CHAIN geothermal PoC

- **Status:** Accepted
- **Date:** 2026-08-19
- **Amended:** 2026-08-19 (D7: top-level orchestration repository added); 2026-09-04 (D9:
  synthetic joint site/connection extension); 2026-09-04 (D10: corrected joint
  site/connection specification adopted)
- **Decider:** Ishantha Hewaratne
- **Informed by:** `docs/R3_CHAIN_PyDoublet_pandapipes_Implementation_Plan.md`
  (18 Aug 2026); code study of the PyDoublet and pandapipesAI baselines
  (see `docs/provenance/upstream-imports.md`)

## Context

The R3-CHAIN geothermal integration workstream needs a six-week, reproducible,
auditable proof of concept in time for the Wuppertal kickoff on 15 September 2026.
The two upstream codebases are at opposite maturity levels: PyDoublet is a physics
prototype with broken packaging and no stable result contract; pandapipesAI is a
mature MCP tool platform with session, contract, ledger and validation
infrastructure. Without a recorded scope boundary, this project would drift toward
geological drilling-site optimisation, which it cannot honestly answer yet.

## Decision

### D1 — The one question this PoC answers

> Given **one** defined geothermal doublet result, at which candidate supply/return
> connection pair should the resulting surface heat source connect to a small
> district-heating network?

The PoC ranks **network connection options**. It does **not** determine where the
doublet should be drilled, and every report it produces must say so.

### D2 — Deferred (out of scope; reopening any of these requires a new ADR)

Real Wuppertal network or geological data; drilling-location determination;
geological grids / hexagonal spatial optimisation; annual or transient PyDoublet
output; fully dynamic hydraulic simulation; steam networks; mathematical
optimisation or ML; detailed heat-exchanger design; heat-pump design/optimisation;
a native geothermal component inside core pandapipes; a production Agent
Fred/conversational interface; a validated commercial cost database.

### D3 — Layer authority (separation is non-negotiable)

1. **PyDoublet** is authoritative for the subsurface/doublet calculation.
2. **The adapter** is authoritative for the coupling boundary and surface
   heat-exchanger assumptions.
3. **pandapipes** is authoritative for district-heating thermo-hydraulics.
4. **Deterministic code** is authoritative for feasibility, KPIs and ranking.
5. **The LLM/orchestrator** selects tools and explains structured results; it never
   invents, overrides or recalculates physical results.

### D4 — Ranking rule (version 1)

Two-stage, deterministic: (1) reject every candidate failing a hard technical gate;
(2) rank the remainder by lowest incremental annualised cost. Tie-breakers: lower DH
pumping electricity, then shorter connection length, then greater technical margin.
**No weighted multi-criteria score in version 1** — a weighted score can hide a
physical failure.

### D5 — Capacity policy (version 1)

Geothermal supplies as much feasible heat as possible; a documented auxiliary source
covers any shortfall for KPI/economic accounting (`auxiliary_policy:
"cost_shortfall"`). `strict_infeasible` (any shortfall is infeasible) is named in
`auxiliary_policy_options` as a planned second mode, but is **not yet implemented**:
`network/candidate.py`'s `GeothermalInjectionPolicy` currently raises `ValueError`
for any value other than `cost_shortfall`. Only rejection of the unbuilt mode is
tested (`tests/network/test_candidate.py::test_policy_rejects_strict_infeasible_auxiliary_policy`).
Building it, or removing it from the named vocabulary, is open Phase-1 work.

### D6 — Workshop adjustment (decided 2026-08-19)

The deterministic vertical slice remains the main Sprint-4 goal, **plus** a minimal
truthful MCP proof pulled into workshop scope. By 15 September the demonstrator
supports:

1. one Claude/scripted MCP request;
2. deterministic PyDoublet execution **or** loading of the approved golden scenario;
3. adapter validation and conversion;
4. pandapipes candidate evaluation;
5. feasibility-first ranking;
6. a machine-readable result and audit trace.

The full granular `geo_` MCP tool suite, registry integration and hardening remain
in Sprint 5. Sprint 4 delivers only the smallest truthful MCP wrapper around the
already-tested deterministic runner. During Sprint 1, an MCP entry-point/
configuration **spike only** (no wrapper implementation).

### D7 — Repository strategy (as executed in T1.1A, 2026-08-19)

- No `git init` inside the vendored reference folders; both remain untouched
  reference copies with frozen SHA-256 manifests.
- `repos/PyDoublet` — pristine fallback import, commit `4fb328d`, tag
  `upstream-import-2026-08-19`, work on `feature/pydoublet-integration`.
  Only integration-enabling changes (packaging, result contract); **no physics
  changes** in this phase.
- `repos/pandapipesAI` — pristine fallback import (project-supplied source
  snapshot, **not** a verified clone), commit `a1fe3c6`, same tag, work on
  `feature/r3chain-geothermal-poc`. New code goes into
  `pandapipesai/special_modules/geothermal/` with the `geo_` prefix, reusing the
  existing session/contract/ledger/annuity patterns.
- Official-repo access is being requested in parallel. When granted: **no overwrite**
  — a separate clean clone is compared against this baseline and a controlled
  migration/cherry-pick plan is proposed for approval.
- A top-level **orchestration repository** (`r3chain-poc`, branch `main`) tracks
  CLAUDE.md, `docs/`, `config/`, and later adapter/orchestration/reporting code and
  coupling-workflow tests. The nested PyDoublet and pandapipesAI repositories remain
  independent Git repositories — **not** submodules or embedded gitlinks at this
  stage — and are excluded via `.gitignore`, together with the original reference
  folders, uploaded source archives, virtual environments, caches, generated
  results/figures/logs, and secrets/local-environment files.
- No pushes; every commit requires explicit review and approval.

### D8 — Assumptions live in configuration

Every provisional value is stored in `config/demo_assumptions.json`, labelled
`demo_assumption`, cross-referenced to an open question in
`docs/decisions/phase0-questions.md`, and replaceable without code changes.
Changing a scientific assumption requires explicit approval (CLAUDE.md rule);
silently editing a value in code is forbidden.

### D9 — Synthetic joint site/connection extension (decided 2026-09-04)

`workflow/joint_optimization.py` EXTENDS D1, not replaces it: alongside the canonical
single-scenario C1-C4 comparison (unchanged, still available), it additionally varies a
synthetic geothermal scenario/site axis (`geothermal_scenario_id`/`surface_site_id`),
independent of the network-connection axis (`connection_candidate_id`/`route_id`/
`design_option_id`), via a six-component `AlternativeIdentity`. Every scenario is
`synthetic=True` and derived from the one golden, already-validated PyDoublet coupling
result by perturbing producer temperature and/or brine mass flow — never an
independent real drilling-site simulation or claim. Each scenario also carries a
declared, illustrative `drilling_capex_multiplier` and a doublet-pump power rescaled by
its own mass-flow ratio (reusing PyDoublet's own linear-in-flow pump formula), so a
scenario's economic consequence is not limited to deliverable heat alone. Since no
approved multi-objective weighting policy exists, feasible alternatives are compared via
a Pareto/non-dominated shortlist (OPT-003), never an invented single ranking.

Real drilling-location determination remains on D2's deferred list: `data_contracts
.readiness.drilling_location_optimization_permitted` is the enforced gate a future
real-data entry point must satisfy before any real (non-synthetic) drilling-location
optimization may run, and no code path in this repository currently supplies real data
to it. See `docs/issues/joint-location-optimization.md` for the full implementation
record.

### D10 — Corrected joint site/connection specification adopted (decided 2026-09-04)

A subsequent review of D9's own implementation found several genuine methodological
gaps: the six identity fields were loosely described as "axes" even where several never
independently vary; `surface_site_id` was a bare label with no coordinates; the three
synthetic resource scenarios were perturbations of one golden result rather than
independently site-linked inputs; every scenario shared the same global connection-route
distances instead of site-specific geometry; the declared CAPEX/pump-power multipliers
used the pre-correction field name `drilling_capex_multiplier`; and the Pareto objective
set mixed mathematically dependent quantities (e.g. LCOH alongside its own cost
denominator). `docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md`
is the authoritative correction for all of these, implemented phase by phase (its own
§21). D9's synthetic extension is understood as the corrected specification's own "v1"
baseline: still available, still accurately described where it is, now being extended
rather than replaced.

This specification is now the authoritative current-scope record for the joint
site/connection layer, ranking above the D9 text above for anything the two disagree
on (see `CLAUDE.md`'s authority hierarchy). It does not reopen D1's own boundary: the
canonical single-scenario C1-C4 workflow remains unchanged and is not affected by this
amendment. Real drilling-location determination remains exactly as constrained by D2
and the paragraph above -- this amendment corrects the SYNTHETIC methodology's
honesty and structure, it does not loosen the real-data gate.

**Implementation status (updated 2026-09-04):** Phases 1-7 of the specification's own
§21 phased plan are implemented -- corrected contracts/terminology and relationship
validation (Phase 1); site-linked resource scenarios and site-origin-aware route
generation, with only compatible combinations evaluated (Phase 2); connection-pipe
diameter threaded into the pandapipes evaluation itself (Phase 3); corrected
site/scenario-sourced economics and a materiality-aware Pareto decision policy with
optional primary-objective ranking (Phase 4); a committed, ready-to-run joint
configuration with a full audit bundle, reachable by CLI (Phase 5); the same corrected
layer dispatched through the existing six-tool MCP server, with persistent-registry
rehydration distinguishing canonical and joint run types (Phase 6); and a diagnosed,
corrected, empirically Linux-verified cross-platform reproducibility claim, including
two genuine defects this verification work found and fixed that the specification's own
diagnosis did not name -- a joint-CLI package-path resolution bug reachable only from an
external run directory, and two solver-non-convergence unit tests that depended on
BLAS-backend-specific behaviour rather than a deterministic injected failure (Phase 7).
Phase 8 (documentation reconciliation, this edit among others) and Phase 9
(release-candidate verification) remain. Every canonical C1-C4 golden value (`run_id`,
LCOH set) is unchanged throughout. See
`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md`
§21 and `docs/decisions/decision-register.md` for the phase-by-phase evidence.

## Consequences

- Scope creep toward geological placement, weighted scoring, or real Wuppertal data
  is blocked by this ADR; each would need a superseding ADR.
- The 4.345 MW raw PyDoublet power must never be presented as DH-deliverable power;
  the adapter exposes both raw and deliverable values (implementation plan §9.3).
- Brine mass flow and DH water mass flow are distinct, separately named quantities
  everywhere.
- A candidate without full sequential thermo-hydraulic pandapipes convergence is
  infeasible (`THERMAL_PIPEFLOW_NOT_CONVERGED`), regardless of hydraulic-only
  diagnostics.
- Economic outputs are labelled **indicative**; cost assumptions are visibly
  provisional until Phase-0 question 7 is answered.
