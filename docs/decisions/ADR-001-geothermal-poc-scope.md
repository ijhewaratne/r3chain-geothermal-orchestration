# ADR-001 — Scope and governing decisions of the R3-CHAIN geothermal PoC

- **Status:** Accepted
- **Date:** 2026-08-19
- **Amended:** 2026-08-19 (D7: top-level orchestration repository added); 2026-09-04 (D9:
  synthetic joint site/connection extension); 2026-09-04 (D10: corrected joint
  site/connection specification adopted); 2026-09-05 (D11: research-alignment
  specification adopted)
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

**Implementation status (updated 2026-09-05):** Phases 1-9 of the specification's own
§21 phased plan are implemented -- corrected contracts/terminology and relationship
validation (Phase 1); site-linked resource scenarios and site-origin-aware route
generation, with only compatible combinations evaluated (Phase 2); connection-pipe
diameter threaded into the pandapipes evaluation itself (Phase 3); corrected
site/scenario-sourced economics and a materiality-aware Pareto decision policy with
optional primary-objective ranking (Phase 4); a committed, ready-to-run joint
configuration with the complete §17 audit bundle (16 hashed files + manifest.json),
reachable by CLI (Phase 5); the same corrected layer dispatched through the existing
six-tool MCP server, with persistent-registry rehydration distinguishing canonical and
joint run types (Phase 6); a diagnosed and corrected cross-platform reproducibility
claim, verified against BOTH local Docker (Linux/arm64) and a real `ubuntu-latest`
GitHub Actions run -- both `ubuntu-latest` jobs (Python 3.11 and 3.12) now pass
completely on real x86_64 hardware after the fixes; one macOS-specific CI-timing issue,
unrelated to the joint-site-connection methodology itself, remains open (Phase 7);
README/ADR/decision-register/traceability-matrix reconciled against actual current
behaviour, including a genuine README self-contradiction found and corrected (Phase 8);
and a full release-candidate verification checklist executed against the corrected code
(Phase 9). Every canonical C1-C4 golden value (`run_id`, LCOH set) is unchanged
throughout. **Not yet closed:** a fresh green three-job CI confirmation of the fully
corrected code (the macOS job's own remaining issue was diagnosed and fixed locally, not
yet re-confirmed on real CI). See
`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md`
§21, `docs/traceability-matrix.md`'s own Phase 9 section, and
`docs/decisions/decision-register.md` (IMPL-023, IMPL-024) for the phase-by-phase
evidence.

### D11 — Research-alignment specification adopted (decided 2026-09-05)

`docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md` (committed
verbatim from the externally supplied `.docx`, converted to Markdown for readability since
no docx-reading tool was available in this environment) is now the authoritative record for
a NEW research-experiment layer built ON TOP of the corrected v2 joint site/connection
workflow (D10) -- it does not reopen or redesign that layer's own architecture. It answers a
genuinely new scientific question the v2 layer alone cannot: does the site/resource that
source-side Pareto analysis prefers remain preferred once its actual district-heating
integration, evaluated at more than one representative load level, is priced in?

Implemented in full: `data_contracts/research_experiment.py` (typed contracts --
`LoadStateDefinition`, `ResearchExperimentConfig`, `AnnualizedAlternativeEconomicResult`,
`BaselineComparisonResult`/`ComparisonInterpretationCode`, `SensitivityCaseDefinition`/
`SensitivityCaseResult`, `RobustnessClassification`/`ResearchExperimentDecisionSummary`);
`workflow/load_state_evaluation.py` (per-alternative, per-load-state evaluation, reusing
`workflow/joint_evaluation.py::evaluate_alternative()` unchanged against a scaled-demand
baseline built per state); `economics/annualized_system_costing.py` (CAPEX/annuity computed
ONCE per alternative, OPEX/auxiliary/pumping summed across load states, each weighted by its
own duration); `decision/research_comparison.py` (the three baselines -- geothermal-only, a
NEW narrowly-scoped source-side-only LCOH formula since no existing function omits network
costs; network-only, a deterministic filter of the same integrated results to one fixed
reference scenario; integrated, reusing `decision/joint_policy.py::decide()`/
`pareto_shortlist()` completely unchanged -- plus the deterministic cross-baseline
comparison and the small deterministic sensitivity/robustness study);
`workflow/research_experiment.py` (the orchestrator, calling `run_joint_workflow_v2()`
wholesale rather than re-deriving package loading/route generation/enumeration);
`workflow/research_experiment_export.py` (the artifact bundle); CLI wiring
(`is_research_experiment_enabled`, checked before `joint_study_v2` in `run_cli()`, mirroring
the existing "most specific layer first" convention); and MCP dispatch (a third
`workflow_mode: "research_experiment"` value added to the EXISTING `geo_run_workflow`
discriminated-union response and the registry's `run_type` string dispatch -- no seventh
tool, matching how the v2 layer was added to the same six tools in D10's own Phase 6). A
committed, ready-to-run configuration (`config/research_experiment_synthetic.json`, a copy
of the v2 config plus one new `research_experiment` section) exercises the full layer
end-to-end against the same already-committed `config/joint_study_synthetic_v2.json`
package.

A genuine, evidenced risk area was audited before implementation, not assumed solved:
`network/candidate.py`'s `GeothermalInjectionPolicy` curtailment-stability margin
(`minimum_auxiliary_circulation_fraction`) was empirically tuned only at the golden case's
near-100%-coverage surplus; a load state with much-reduced demand produces a materially
larger surplus ratio than anything previously verified. `workflow/load_state_evaluation.py`
treats a resulting `THERMAL_PIPEFLOW_NOT_CONVERGED`/`CONSUMER_TEMPERATURE_NOT_MET` outcome
at such a state as an ordinary, honestly reported infeasible result -- never masked, never
retried with a widened margin -- and an alternative with any infeasible load state is
reported `computable=False` with a typed reason, never estimated or interpolated.

Every new numeric value this layer introduces (three synthetic load-state demand
multipliers/durations, two sensitivity-case multipliers, and the reused v2 materiality
thresholds for the new `annualized_system_lcoh_eur_per_mwh` objective) is a labelled
`synthetic_assumption` in `config/research_experiment_synthetic.json`, following D8's own
established convention -- none is presented as validated engineering guidance. This
amendment does not reopen D1's own canonical boundary or D2's real-data deferral list: the
canonical C1-C4 workflow and the v2 layer's own golden values are unchanged throughout,
verified by the full offline test suite passing after every phase. **Not yet closed:** a
fresh green CI confirmation of this new layer on real GitHub Actions runners (verified only
against this session's local `.venvs/orchestration` environment) -- the same open item D10
already recorded for the v2 layer's own macOS job remains open here too.

**Conformance round (2026-09-05, after this layer was first pushed):** a closer, commit-pinned
re-read of the specification against the actual code found three genuine literal gaps —
an explicit `AnnualizationPolicy`/duration-equality rule (§1.7.3), the optional
`LoadState.required_for_feasibility` field, and the full §17 "shall publish at least" 19-file
artifact list (published as a smaller 8-file bundle). All three resolved without touching any
scientific calculation — see `docs/decisions/decision-register.md` IMPL-028 for the full record.

**Decision-layer correction (2026-09-05, a second, deeper review):** a second review against the
committed v2 fixture and the spec's own §10-14 text found the geothermal-only baseline silently
collapsed multiple resource scenarios sharing one site into a single best-site value — directly
contradicting the spec's own explicit instruction — plus a non-declared network-only reference, a
comparison that was not actually set-based, and an unreachable `INTEGRATED_DIFFERS_FROM_BOTH` code.
All independently re-verified against the spec text before any fix; `decision/research_comparison.py`
was substantially rewritten to rank scenarios via the existing materiality-aware `decide()` (reused
unchanged) and derive rank-1 SETS directly. See `docs/decisions/decision-register.md` IMPL-029.

**Final scientific-conformance round (2026-09-05, a third, letter-by-letter review):** a third
review, structured against explicit lettered requirements A-O, found the prior two rounds had
already correctly implemented most items (verified by direct re-inspection before any further
edit, not assumed) but two genuine gaps remained: `network_only.eligible_attachment_ids` was
declared in configuration but never actually referenced by any code (a documentation-only
field), and the spec's own §14.3 "maximum observed rank change for each base candidate" metric,
previously descoped in IMPL-029 as disproportionate, was implemented as requested rather than
left descoped. Both fixed without any new simulation or re-derived ranking — see
`docs/decisions/decision-register.md` IMPL-030 for the full record. This round also strengthens,
rather than changes, prior disclosures already made in IMPL-029/IMPL-028:
`MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON` is **RESERVED/DEPRECATED under set-based comparison
semantics** — rank-1 ties no longer prevent baseline comparison, since disjointness between two
rank-1 SETS is always computable once both are non-empty; the enum member is retained (the spec
requires the full code set to exist) but no runtime path in `compare_baselines()` reaches it, and
no test claims to exercise it. The declared 5000 h/a annualization horizon (D9/IMPL-028) is
reaffirmed as this experiment's own REPRESENTED operating regime, never a claim of a full
8760-hour chronological calendar-year simulation. The geothermal-derating sensitivity case is
reaffirmed as a deterministic economic what-if that never re-runs pandapipes or the HX evaluator
and therefore cannot discover new technical infeasibility on its own — a documented boundary, not
a silent one (`decision/research_comparison.py::_apply_sensitivity_case()`).

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
