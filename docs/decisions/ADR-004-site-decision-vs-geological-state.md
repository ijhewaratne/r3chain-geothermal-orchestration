# ADR-004 — Drilling site is the decision; geothermal scenario is a state of nature

- **Status:** Accepted, implemented.
- **Date:** 2026-09-14
- **Decider:** Ishantha Hewaratne
- **Branch:** `feature/fixed-dh-interface-drilling-site-optimization`
- **Builds on:** `docs/decisions/ADR-003-fixed-interface-drilling-site-optimization.md`
  (the fixed-DH-interface correction, preserved unchanged by this ADR).

## Context

ADR-003 correctly fixed the DH network-attachment axis. But the resulting
implementation still ranked every `(site, scenario)` pair as an
independently competing "alternative." Site alpha carries two linked
resource scenarios (`scenario_alpha_golden`, `scenario_alpha_reduced_flow`);
both appeared as separate rows in `drilling_site_ranking.csv` and both
competed in the primary decision. That implies the optimizer chose the
golden geological outcome over the reduced-flow one for site alpha — but a
planner chooses WHERE to drill, never WHICH geological outcome occurs
there. Nature determines the geological realization after drilling.

## Decision

$$
s_i = \text{decision variable (drilling site)}, \qquad
g_{ik} = \text{uncertain geological state/outcome at site } s_i.
$$

For the deterministic workshop prototype, exactly ONE declared reference
case `g_{i,\text{ref}}` is designated per available site `s_i`, used for
the PRIMARY site-level ranking. Every other scenario linked to that site is
a SENSITIVITY case: evaluated through the identical physics/economics
pipeline, reported separately (`site_sensitivity_results.csv`/`.json`), and
never fed into the primary decision.

### Where the assignment lives

The reference/sensitivity designation is declared in this mode's OWN
configuration (`fixed_interface_site_optimization.reference_scenario_by_site`,
a `{site_id: scenario_id}` mapping) — never inferred from scenario naming
("golden"/"best"/"winning") and never added as a field on the shared,
UNTOUCHED `GeothermalResourceScenario`/`JointStudyPackage` contract
(`data_contracts/joint_study.py`) that v1, v2, and `research_experiment`
also depend on. `data_contracts/fixed_interface.py::resolve_site_case_
assignment()` validates the mapping (every available site has exactly one
entry, naming one of its OWN linked scenarios) before any simulation runs,
returning a typed `FixedInterfaceValidationError` otherwise.

### What changed vs. ADR-003's own implementation

- `FixedInterfaceSiteOptimizationResult` gained `case_assignment:
  SiteCaseAssignment`; its own model-level invariant now additionally
  asserts no sensitivity-case alternative ever appears in
  `decision.pareto_shortlist_alternative_ids`/`ranked_alternative_groups`/
  `preferred_alternative_id`.
- `run_fixed_interface_site_optimization()`'s `decide()` call is now fed
  ONLY the reference-case subset of evaluated alternatives — `decide()`
  itself (`decision/joint_policy.py`) is completely unchanged; only the
  input list is filtered.
- `FixedHeatIntegrationStation` gained `network_attachment_id` (the raw
  pandapipes attachment id, e.g. `"trunk_1"`), separated from `station_id`
  (a semantic display id, e.g. `"dh_integration_station_1"`, configurable
  via `station_display_id`) -- preventing the misreading "trunk_1 was
  selected by the optimization." It was not selected; it is the fixed
  station's own underlying attachment.
- `drilling_site_ranking.csv`/`.json` now have exactly ONE row per
  DECLARED site (never per site×scenario), built from each site's own
  reference case, with static fields (distance, declared depth, declared
  geothermal inputs) read from sources that survive a downstream technical
  rejection (routes, scenario metadata) rather than from the
  (possibly-absent) computed result.
- New artifacts: `site_sensitivity_results.csv`/`.json` (sensitivity cases,
  with `difference_from_site_reference_eur_per_mwh`), `cost_breakdown.csv`
  (full component decomposition, `pump_capex_eur` explicitly
  `not_modelled` — this prototype has no pump capital-cost term at all,
  only pump OPEX/electricity).

Nothing about the underlying physics, HX/network gates, or economics
formulas changed — see the module-level "reuse, not reinvention" docstrings
in `workflow/fixed_interface_workflow.py`.

## Answers to the specific audit questions this correction required

- **Drilling depth → cost:** `target_depth_m` is metadata only. No cost
  function in this repository consumes it (grepped `src/`); drilling CAPEX
  is a declared, per-scenario input
  (`SiteEconomicInputs.doublet_capex_eur`). A deeper site does not cost
  more for that reason alone under this prototype.
- **The 0.99 geothermal-coverage figure:** `coupling_assumptions
  .minimum_auxiliary_circulation_fraction = 0.01`
  (`config/demo_assumptions.json`), an existing, already-documented
  numerical-stability margin protecting a pandapipes solver zero-tolerance
  check (`network/candidate.py`'s own "Curtailment" section) — not an
  economic policy, not accidental.
- **Load cases:** this mode currently evaluates one prescribed design
  operating condition. `workflow/load_state_evaluation.py` exists (reused
  by `research_experiment.py`) but is not yet wired into this mode;
  `site_load_case_feasibility.csv` is deliberately not produced.
- **Cost decomposition:** already fully available on
  `economics.costing.CandidateEconomicResult` (per-component CAPEX/OPEX
  fields) — exposed via `cost_breakdown.csv`, not newly computed.

## Future work (documented, not implemented here)

$$
E[V(s_i)] = \sum_k P(g_{ik} \mid s_i)\, E[V(s_i, g_{ik})].
$$

`GeothermalResourceScenario` (the untouched shared contract) already
carries `probability: float | None` and `probability_label: str | None` —
sufficient structure for a future probabilistic ranking extension without
further schema changes. No probability value is assigned anywhere in this
branch (no `20%`/`60%`/`80%` or any other invented figure); Fündigkeitsrisiko
quantification remains explicitly future work.
