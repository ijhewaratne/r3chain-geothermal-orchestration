# R3-CHAIN PyDoublet–pandapipes Proof of Concept

@docs/R3_CHAIN_PyDoublet_pandapipes_Implementation_Plan.md

## Objective

Implement the six-week deterministic proof of concept described in the imported
implementation plan.

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
