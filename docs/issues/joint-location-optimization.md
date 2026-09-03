# Issue: synthetic joint site/connection optimisation demonstration (OPT-001..007)

**Status**: **implemented** (2026-09-03, `feature/joint-location-optimization`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 7 / Workstream J, AC-10 — the final Phase
before Phase 8 (real Wuppertal, external-data gated) and Phase 9 (release acceptance)). See
`docs/decisions/decision-register.md` (IMPL-013).

## What this closes

OPT-001 (six-component decision identity), OPT-002 (evaluation stages), OPT-003 (Pareto shortlist,
no invented weights), OPT-004 (per-scenario reporting), OPT-005 (synthetic demonstration), OPT-006
(real-mode safeguard, documented as an explicit deferral), OPT-007 (extended-mode outputs), AC-10.

## Design: an outer layer over already-existing, already-tested physics

`workflow/joint_optimization.py` adds NO new physics or economics formulas. It reuses, in sequence:
`adapter.evaluate_heat_exchanger_coupling()` (OPT-002 stage 3), `network.evaluate_candidate()`
(stages 4-6, already covering construction, the independent solve, and every technical gate in one
call), and `economics.compute_candidate_economics()` (stage 7) — exactly the same functions
`workflow/core.py::run_workflow()` itself calls for the single-scenario C1-C4 case. This module's
only new logic is the OPT-001 identity, OPT-002's stage bookkeeping, and OPT-003's Pareto filter.

## Synthetic geothermal scenarios: derived, not invented from nothing

Real PyDoublet cannot be run in this prototype. `build_synthetic_geothermal_scenarios()` derives
THREE variants from the one golden, already-validated coupling result by adjusting
`producer_wellhead_temperature_c` and/or `geothermal_brine_mass_flow_kg_s`, and RECOMPUTING
`raw_geothermal_thermal_power_kw` via the exact same formula T1.5B's own energy-consistency check
uses — so every variant satisfies that check by construction, isolating the deliberate failure mode
(scenario B) to the HX hot-end check specifically, not an incidental energy-balance rejection.
`scenario_B` sets `producer_wellhead_temperature_c=60.0` (below `dh_supply_temperature_c=70.0 +
minimum_hx_approach_k=5.0=75.0`), giving a deterministic `HX_SUPPLY_TEMPERATURE_INFEASIBLE`
geological/site screening failure. `scenario_C` scales brine mass flow to 70% of the golden value —
a genuinely different, still-feasible scenario. Every scenario is `synthetic=True`.

## The curated demonstration (OPT-005), not a full cross-product

`run_joint_optimization_demo()` evaluates a CURATED list of six (scenario, candidate) pairs, not a
full cross-product of every scenario against every Workstream-H-generated candidate (11 accepted ×
3 scenarios = 33 would be disproportionate to a demonstration and harder to reason about). The
curated set still satisfies every OPT-005 minimum, measured directly:

| # | Scenario | Candidate | Outcome |
|---|---|---|---|
| 1 | scenario_A (golden, feasible) | trunk_1-direct | feasible |
| 2 | scenario_A | trunk_2-diverted | feasible |
| 3 | scenario_A | consumer_1-direct | **hydraulic/thermal failure** — `VELOCITY_LIMIT_EXCEEDED` (network-connection stage) |
| 4 | scenario_B (HX-infeasible) | trunk_1-direct | **geological/site screening failure** — `HX_SUPPLY_TEMPERATURE_INFEASIBLE` (site stage, never reaches the network solve) |
| 5 | scenario_C (reduced flow, feasible) | trunk_3-direct | feasible |
| 6 | scenario_C | trunk_4-diverted | feasible |

3 scenarios ✓ (≥3); 5 distinct candidates referenced ✓ (≥4); both "direct" and "diverted" routes
appear ✓ (≥2); one geological/site failure (#4) ✓ (≥1); one hydraulic/thermal failure (#3) ✓ (≥1),
kept structurally distinct from #4 by `stage_reached` (`CALCULATE_HX_COUPLING_BOUNDARY` vs.
`APPLY_TECHNICAL_GATES`) — the demonstration's explicit separation of drilling/surface-site
suitability from network-connection suitability; four feasible alternatives ✓ (≥2). Deterministic
on every call (verified directly, not merely asserted).

## Objective policy (OPT-003): Pareto, not invented weights

No approved multi-objective weighting policy exists for this prototype (only Q8's single-scenario
feasibility-first-then-lowest-cost rule was approved). `pareto_shortlist()` returns the non-dominated
subset of feasible alternatives across six objectives that this prototype actually computes data
for (annualised cost, indicative LCOH, geothermal heat delivered, auxiliary heat, total pumping
electricity, connection length) — drilling/site cost (not yet differentiated per scenario in this
economics module), risk/success-probability, and emissions are excluded, since no data/source for
them exists (OPT-003's explicit instruction). Measured: of the four feasible alternatives, only the
two `scenario_A` ones are non-dominated — `scenario_C`'s reduced brine flow makes its alternatives
strictly worse on every considered objective, an interesting, real, unplanned finding kept and
reported rather than adjusted away.

## Real-mode safeguard (OPT-006): documented deferral, not implemented

This module operates in synthetic mode only. `data_contracts.readiness.generate_readiness_report()`
(Workstream I) already computes the exact `connection_optimization_permitted`/
`drilling_location_optimization_permitted` flags OPT-006 requires — wiring THIS module to consult
that report before evaluating a `classification="real"` study package is a real-mode integration
step explicitly deferred alongside Phase 8's own external-data gate, not attempted here.

## Extended outputs (OPT-007): a lighter-weight export than the main pipeline

`workflow/joint_optimization_export.py` writes `generated_candidates.json`,
`screened_alternatives.json`, `alternative_comparison.csv`, `pareto_or_ranking.json`, and
`recommendation.md` (plus `study_readiness.json` when a readiness report is supplied) as plain,
deterministic files — WITHOUT `workflow/artifacts.py`'s own full byte/scientific-hash manifest
infrastructure. `location_shortlist.geojson` is never produced: this demonstration has no real
spatial coordinate data (OPT-007's own "when spatial inputs exist" qualifier). Extending the
existing manifest system to also audit this extended mode is a reasonable next step, reported here
as a scope decision, not attempted in this phase.

## Tests

`tests/workflow/test_joint_optimization.py` (14 tests): the OPT-001 identity; scenario derivation
(≥3, all synthetic, distinct scenario/site IDs); scenario B's HX-infeasibility and every scenario's
energy-consistency-by-construction; the full OPT-005 minimum-satisfaction proof measured directly
against the curated demonstration; AC-10's technical/economic separation (no infeasible alternative
ever carries economics) and Pareto-not-ranking proof; determinism; Pareto-dominance logic in
isolation (including a synthetic strictly-worse clone proven excluded); every OPT-007 file written,
non-empty, and byte-identical across repeated exports; the recommendation text's explicit
"SYNTHETIC" language. Full offline suite: 1009 passed, 0 failed (a fully clean run — the
previously-noted, pre-existing subprocess-timing flake did not recur this time).

## Update (2026-09-03, `feature/complete-synthetic-prototype`, Phase 4): the full product, wired in

The three items below, each flagged "not covered" at the time this issue was first closed, are now
addressed by `workflow/joint_optimization.py::run_joint_optimization_full_product()` and
`workflow/joint_workflow.py` (new file) — see `docs/issues/joint-optimization-workflow-integration.md`
for the full account. Summary: a genuine full scenario × accepted-generated-candidate product (no
curation, no undisclosed filtering — 3 scenarios × 11 accepted candidates = 33 alternatives,
measured, `len(result.alternatives)` equals the search-space size by construction) is now exposed
as its own top-level workflow entry point with a hash-audited artifact bundle, reachable from the
CLI via the same `config`-driven mode-switch convention as `candidates.mode` (Phase 3.2) and, for
MCP, by pointing the server's fixed config at such a config (`geo_run_workflow`'s own response
mapping is a documented, deliberate scope boundary — see that new issue document). The curated
six-alternative `run_joint_optimization_demo()` above is UNCHANGED and still available as a
lighter-weight, hand-picked illustration; it is not replaced.

## Not covered by this issue (remaining, unaffected by the update above)

- No wiring of OPT-006's real-mode readiness check into this module (Phase 8, external-data-gated,
  still not attempted).
- No `location_shortlist.geojson` (no real spatial data exists to populate one).
