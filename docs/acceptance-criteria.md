# Acceptance criteria — R3-CHAIN geothermal PoC

Two gates. Every item is phrased so it can be checked by running a command or opening
an artifact — not by judgement. Provisional values are governed by
`config/demo_assumptions.json` and ADR-001.

## Gate 1 — Workshop vertical slice (due 2026-09-15)

Deterministic slice (implementation plan, Week-4 exit gate):

- [ ] One Python command runs the full deterministic chain end-to-end:
      PyDoublet (or approved golden scenario) → adapter → baseline → candidates →
      gates → ranking → output package.
- [ ] The output shows, side by side, the **raw** PyDoublet thermal power and the
      **adapter-corrected deliverable** heat (both values present in
      `pydoublet_coupling_result.json` / report).
- [ ] The synthetic four-consumer network with mirrored supply/return converges in
      sequential (thermo-hydraulic) pandapipes pipeflow for the baseline case.
- [ ] At least three candidates evaluate independently on copied networks; at least
      one intentionally failing case is rejected with its exact failure code.
- [ ] Ranking includes only gate-passing candidates; rejected candidates carry
      machine-readable reason codes.
- [ ] Every cost figure is visibly marked provisional/indicative (report text +
      `demo_assumption` labels).
- [ ] Every connection length appearing in workshop results equals the simulated
      pipe geometry length — map, pandapipes pipes and economics consume one single
      length value per candidate (no separate economic length).
- [ ] All pressure limits and reported pressures carry an explicit pressure
      reference (absolute, `*_bar_abs`), and a test pins the pressure-reference
      semantics of pandapipes results before any pressure gate is applied.
- [ ] Absolute cost and LCOH outputs are labelled **illustrative** in every report
      and cannot be read as validated project costs.

Minimal MCP proof (ADR-001 D6, decided 2026-08-19):

- [ ] One Claude/scripted MCP request triggers the demonstrator.
- [ ] Deterministic PyDoublet execution **or** loading of the approved golden
      scenario works through that request.
- [ ] Adapter validation and conversion run through that request.
- [ ] pandapipes candidate evaluation runs through that request.
- [ ] Feasibility-first ranking is returned through that request.
- [ ] The request produces a machine-readable result and an audit trace
      (`manifest.json` + `audit.jsonl` or equivalent).
- [ ] The MCP path and the deterministic runner produce the same ranking within
      numeric tolerances.

## Gate 2 — Final acceptance (end of Sprint 6)

Definition of done (implementation plan §2):

- [ ] 1. A clean Python 3.11 environment installs and runs the selected PyDoublet
      example (`pip install -e .` + example run succeed from scratch).
- [ ] 2. PyDoublet returns a stable, versioned coupling result (no timestamped-file
      searching, no undocumented array positions).
- [ ] 3. The deterministic adapter validates units/physics and calculates
      HX-deliverable heat.
- [ ] 4. The fixed synthetic DH network has supply + mirrored return + four consumers.
- [ ] 5. Baseline plus ≥3 candidate pairs run independently on copied networks.
- [ ] 6. Full sequential thermo-hydraulic convergence is required for feasibility.
- [ ] 7. Hard gates check temperature compatibility, geothermal capacity, delivered
      heat, pressure, velocity, mass balance and energy balance.
- [ ] 8. Indicative economics declare the cost boundary and all assumptions/sources.
- [ ] 9. Only technically feasible candidates enter the economic ranking.
- [ ] 10. The deterministic workflow is callable through MCP tools and one external
      orchestrator.
- [ ] 11. One command produces raw results, converted results, candidate results,
      ranking, figures and an audit manifest (plan §15 output package, complete).
- [ ] 12. Unit, integration, contract and end-to-end tests pass **without network
      access** and without real Wuppertal data.

Week-6 exit gate (plan §17):

- [ ] One-command clean run succeeds on a fresh clone/checkout.
- [ ] All Gate-1 and Gate-2 boxes above are checked.
- [ ] Results are reproducible (same ranking within tolerances on re-run) and
      auditable (manifest contains commits, hashes, tool calls, assumptions,
      warnings, output-file hashes).
- [ ] A colleague can run the demonstration from the README alone.

## Producer wellhead temperature contract (ADR-002)

- [ ] The adapter prefers the primary JSON Pointer
      `/simulation_results/producer_wellhead_temperature_c` (the named field)
      over the legacy pointer `/simulation_results/temperature_profile_c/2`
      whenever the primary pointer resolves.
- [ ] Any use of the legacy fallback is traceable and emits the
      `LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK` audit warning.
- [ ] The original raw PyDoublet result and the field's source path are
      preserved alongside every extracted value, primary or fallback.
- [ ] A post-repair PyDoublet result missing the named field is rejected
      (validation failure), never silently patched via the legacy fallback.
- [ ] When both the named field and the legacy index are present, their
      values must agree; disagreement is itself a validation failure.
- [ ] The temperature unit is explicitly °C wherever this value is reported
      or logged.
- [ ] No unlabelled index-based extraction of this value is permitted
      anywhere in adapter or reporting code.

Standing constraints verified at both gates:

- [ ] Every physical field carries an explicit unit in its name or schema.
- [ ] Brine flow and DH water flow are separate, separately named quantities.
- [ ] Reports state explicitly that the PoC ranks network connection options, not
      drilling locations.
- [ ] No scientific assumption changed without approval (config + ADR trail).
- [ ] All project-level documents and configuration (CLAUDE.md, docs/, config/,
      orchestration code and coupling tests) are version-controlled in the
      top-level orchestration repository.
