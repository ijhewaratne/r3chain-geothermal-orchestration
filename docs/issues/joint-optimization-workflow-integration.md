# Issue: joint optimization exposed as a full-product primary workflow (Phase 4)

**Status**: **implemented for the Python entry point + CLI; MCP `geo_run_workflow` dispatch
explicitly deferred** (2026-09-03, `feature/complete-synthetic-prototype`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 4). See
`docs/decisions/decision-register.md` (IMPL-018) and `docs/issues/joint-location-optimization.md`
(the original OPT-001..007 implementation this phase builds on).

**Update (2026-09-04):** this remains accurate for `workflow/joint_workflow.py` (v1) specifically —
its own MCP `geo_run_workflow` dispatch is still genuinely deferred, unchanged. The corrected v2
layer (`workflow/joint_workflow_v2.py`,
`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md` Phase 6) DOES
now dispatch through `geo_run_workflow` (a discriminated `workflow_mode: joint_site_connection`
success shape, through the same six tools, no seventh tool added) — see
`docs/decisions/decision-register.md` (IMPL-023) for that implementation's own record. Nothing
below this note describes v2.

## What this closes

Phase 4's core instruction: "Do not limit the primary demonstration to a hand-selected list of six
alternatives unless that filtering is explicit, configured, audited and accompanied by the size of
the unfiltered search space" — `run_joint_optimization_full_product()`
(`workflow/joint_optimization.py`) evaluates the FULL deterministic product of every synthetic
geothermal scenario × every accepted `generate_candidates()` output, with zero curation:
`len(result.alternatives)` IS the unfiltered search-space size by construction (measured: 3
scenarios × 11 accepted candidates = 33). `workflow/joint_workflow.py` (new module) wraps this in
its own top-level, auditable workflow entry point
(`run_joint_optimization_workflow()`/`JointOptimizationWorkflowResult`/
`JointOptimizationWorkflowFailure`) with a dedicated hash-audited artifact bundle
(`write_joint_optimization_artifacts()`), reachable from the existing CLI
(`r3chain-geothermal-demo`) via the same config-driven mode-switch convention Phase 3.2 established
for `candidates.mode` — `config["joint_optimization"]["enabled"]`.

## Why a NEW top-level entry point, not a branch inside `run_workflow()`

`WorkflowResult`'s shape (`candidate_results: dict[str, CandidateEvaluationBoundaryResult]`,
`ranking: RankingResult`) describes ONE geothermal scenario evaluated against a flat candidate set
with a single lowest-cost ranking. A joint-optimization run's own result is a
`(scenario, candidate)` GRID with a Pareto shortlist (OPT-003: no approved multi-objective weighting
policy exists, so there is no single ranking to produce). Stretching `WorkflowResult`'s own frozen,
hash-pinned, heavily-tested contract to also hold this shape would either invent a fake per-scenario
rank or silently change what that contract means — exactly the kind of scientific-meaning drift
CLAUDE.md prohibits. `workflow/joint_workflow.py` therefore defines its own small, parallel
`JointOptimizationWorkflowResult`/`Failure` envelope, reusing `WorkflowAuditRecord`/
`SourceProvenance`/`compute_run_id()` UNCHANGED from `core.py` — the same content-addressed run
identity scheme, so a joint-optimization run sits in the SAME persistent registry as every other run
and is directly comparable/auditable alongside it.

## Design choices, each with a concrete reason

- **Candidate source**: always `generate_candidates()`'s accepted output (reusing
  `config["candidates"]["generated"]`'s own keys from Phase 3.2 unchanged — no new config surface
  for this), never only the four hand-picked C1-C4. A joint-optimization demonstration whose whole
  point is a broad connection search would be self-defeating if restricted to four fixed points.
- **Design-option axis**: currently contributes exactly ONE value ("standard",
  `network.candidate_generation.DesignOption`'s only implemented variant) for every accepted
  candidate — stated plainly in the function's own docstring rather than silently multiplied by a
  design-option count that does not yet vary (see `docs/issues/candidate-generation.md`).
- **Site/route screening stays separate from the product**: `generate_candidates()`'s own CAN-005
  screening (rejecting e.g. excessive route length or protected geometry) happens BEFORE the
  product, with its own stable reason codes, preserved verbatim in
  `JointOptimizationWorkflowResult.screened_candidates`. This is not hidden filtering — it is a
  separately-audited upstream step, unaffected by which scenario is later paired with each accepted
  candidate.
- **Failure codes reused, not invented**: `PYDOUBLET_PARSE_FAILED`/`BLUEPRINT_CONSTRUCTION_FAILED`/
  `BASELINE_EVALUATION_FAILED` (`workflow/errors.py::WorkflowFailureCode`) cover this entry point's
  three stopping conditions exactly as they do `run_workflow()`'s own. `HEAT_EXCHANGER_COUPLING_FAILED`
  does not apply at this top level — HX coupling is evaluated per-(scenario, candidate) alternative
  inside the product, never as one shared stage.
- **A dedicated manifest model**: `workflow/artifacts.py::ManifestRecord`'s own model-level
  invariant hardcodes the single-scenario workflow's four core filenames (including
  `workflow_result.json`, which does not exist in this bundle). Rather than stretching that
  validator to accept two incompatible filename sets, `joint_workflow.py` defines its own small
  `JointOptimizationManifestRecord` with the SAME hashing/invariant pattern
  (byte SHA-256 always; scientific SHA-256 additionally normalized for JSON files; bundle hash
  recomputation-checked) but its own core-filename set. `write_workflow_artifacts()` itself is
  untouched — the already-hash-pinned single-scenario workflow's own artifact path carries zero
  risk from this addition.

## Deliberately deferred: `geo_run_workflow`'s own response mapping

`mcp_server/schemas.py::RunSummary` (the fixed success shape `geo_run_workflow` returns) requires
`ranked: list[RankedCandidateSummary]`, each carrying an integer `rank`. A Pareto shortlist has NO
total order by definition (OPT-003) — assigning arbitrary rank numbers to non-dominated alternatives
to fit that shape would misrepresent the result exactly as CLAUDE.md prohibits ("Claude... must
never invent... rankings"). Extending `RunWorkflowResult`'s discriminated union with a genuinely new
success variant (e.g. a `JointOptimizationRunSummary`, discriminated by a new field alongside
`status`) is a real, reviewable API-contract decision — not a routine wiring task — and is left
unimplemented here, an explicit deferral in the same spirit as OPT-006's own documented real-mode
safeguard deferral. Consequences, stated plainly:

- `run_joint_optimization_workflow()`/`write_joint_optimization_artifacts()` are fully implemented,
  tested, and reachable from the primary Python API and the CLI (`r3chain-geothermal-demo`) TODAY.
- `geo_get_capabilities` does NOT claim joint-optimization is reachable through `geo_run_workflow` —
  checked directly: `mcp_server/tools.py`/`mcp_server/server.py` contain no reference to
  `joint_optimization`/`joint_workflow` at all, so no capability field asserts something this
  session did not implement.
- `mcp_server/tools.py::run_workflow_tool()` is completely unmodified; the six `geo_` tools remain
  exactly as documented (rule 7: no seventh tool).

## Tests

`tests/workflow/test_joint_workflow.py` (15 tests): the config switch itself (absent from canonical,
`is_joint_optimization_enabled()`'s own three cases); the full product's exact measured shape (33
alternatives, 8/0/9 feasible per scenario, scenario_B universally `HX_SUPPLY_TEMPERATURE_INFEASIBLE`
regardless of candidate); determinism (`run_id` and alternative ordering both bit-identical across
two runs); `max_candidates` capping the grid deterministically; the honest "zero feasible ->
empty Pareto shortlist, never an invented recommendation" case (an unreachably tight
`max_consumer_supply_drop_k`, verified empirically to fail every alternative while still letting the
baseline itself converge — a velocity-gate override was tried first and found to fail the BASELINE,
not the candidates, for this topology, so a different, verified lever was used instead); both
stopping failures (`PYDOUBLET_PARSE_FAILED`, `BLUEPRINT_CONSTRUCTION_FAILED` when
`candidates.generated` is missing); the artifact bundle (every expected file + a valid, hash-checked
manifest, deterministic across two separate write targets, a failure bundle correctly limited to the
four core files); the CLI dispatch itself (exit code 0 for a completed run, exit code 2 for a
stopping failure, both publishing their artifact bundle). Full offline suite passes unchanged
(verified alongside this issue's own commit).
