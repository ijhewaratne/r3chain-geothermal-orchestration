# R3-CHAIN PyDoublet–pandapipes Proof of Concept

@docs/R3_CHAIN_PyDoublet_pandapipes_Implementation_Plan.md

## Objective

This project's scope has evolved through several layers. When scope is ambiguous, consult
them in this order (`docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md`'s
own §1.2 authority hierarchy, which now ranks above the corrected v2 spec's own §5.1 for the
research-experiment layer specifically — do not resolve ambiguity from the original plan alone):

1. **`docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md`**
   is authoritative for the research-experiment layer built on top of the corrected v2
   joint site/connection workflow: three representative steady-state load conditions per
   integrated alternative, annualized-system-LCOH primary-objective ranking (Pareto
   retained as a secondary diagnostic), three baselines (geothermal-only/network-only
   fixed-source/integrated) with a deterministic cross-baseline comparison, and a small
   deterministic sensitivity/robustness study. It does not authorize another architecture
   redesign — it aligns the existing v2 software with this research methodology, reusing
   `decision/joint_policy.py`'s existing decision machinery rather than duplicating it.
2. **`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md`**
   is authoritative for the v2 joint site/connection layer's own architecture and contracts
   (site-linked resource scenarios, site-specific routes, materiality-aware Pareto decision
   policy, corrected terminology) that item 1 builds on top of, unchanged. Implemented phase
   by phase (its own §21).
3. **Executable code and tests** are authoritative evidence of current behaviour.
4. **`docs/decisions/ADR-001-geothermal-poc-scope.md`** (D1-D11) explains the approved
   scope extensions and their limitations, most recently D9 (synthetic joint
   site/connection extension), D10 (adoption of the corrected v2 specification), and D11
   (adoption of the research-alignment specification in item 1).
5. **README, `docs/acceptance-criteria.md`, and the traceability matrix** describe
   user-facing current status.
6. This file (CLAUDE.md) directs future agents to the documents above.
7. **The original six-week implementation plan**
   (`docs/R3_CHAIN_PyDoublet_pandapipes_Implementation_Plan.md`) remains a historical
   record only — its own connection-only, single-fixed-PyDoublet-result scope is the
   **canonical baseline boundary** (still true and still enforced for the canonical
   C1-C4 workflow), not the current authority for either extended layer above.

Three concrete facts this hierarchy resolves: the canonical single-scenario C1-C4 workflow
(`workflow/core.py`) is complete and unchanged — evidence under `docs/evidence/`. The
corrected v2 joint site/connection layer (item 2) is complete, phases 1-9 all shipped. The
research-experiment layer (item 1) is implemented on top of it in `workflow/research_experiment.py`,
`workflow/load_state_evaluation.py`, `economics/annualized_system_costing.py`, and
`decision/research_comparison.py` — consult its own phase-by-phase status (and the code)
rather than assuming any phase not yet reported complete already exists. Real
drilling-location optimization against real data remains out of scope everywhere until
`data_contracts.readiness.drilling_location_optimization_permitted` can be satisfied —
never claimed or attempted in this prototype.

## Non-negotiable rules

- Work on only one approved task at a time.
- Start every implementation task in plan mode.
- Do not change scientific assumptions without explicit approval.
- Deterministic Python code is authoritative.
- Claude may orchestrate and explain results but must never invent simulation
  results, feasibility decisions, costs, or rankings.
- Keep PyDoublet, the adapter, pandapipes evaluation, economics, MCP wrappers,
  and presentation outputs as separate layers.
- Every physical field must have an explicit unit in its name or schema.
- Distinguish geothermal-brine flow from district-heating-water flow.
- Raw PyDoublet thermal power is not automatically DH-deliverable power.
- Candidate feasibility requires successful sequential thermo-hydraulic
  pandapipes convergence.
- Apply hard technical constraints before economic ranking.
- Store assumptions in configuration files, not scattered constants.
- Preserve raw inputs, converted inputs, warnings, tool calls, and results.
- Add or update tests with every behavioral change.
- Never remove or weaken a test merely to make the test suite pass.
- Do not use destructive Git commands.
- Do not commit, push, or open a pull request unless explicitly requested.
- Stop and ask if a requirement is ambiguous or contradicts the implementation
  plan.

## Required workflow

Before editing, report:

1. Existing implementation and relevant files.
2. Files proposed for modification.
3. Acceptance criteria.
4. Tests to add or execute.
5. Assumptions and risks.

After editing, report:

1. Changed files.
2. Commands and tests executed.
3. Test results.
4. Remaining limitations.
5. Any deviation from the approved plan.
