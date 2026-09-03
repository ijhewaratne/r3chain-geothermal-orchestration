# Configuration field classification (Phase 6)

`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 6: "classify every config field
executable/descriptive/deprecated/unsupported." This document does that for
`config/demo_assumptions.json` (and, by construction, every config forked from it —
`config/demo_assumptions_workshop_negative.json`, `config/demo_assumptions_generated_candidates.json`).

Every classification below was verified by tracing the actual `from_config_dict()`/config-reading
call sites in `src/`, not inferred from field names or the JSON file's own `_note` comments (though
those comments' own claims were cross-checked against the code and found accurate in every case
examined).

## How to read this

- **EXECUTABLE** — the exact literal key is read by name (`config["section"]["key"]` or
  `["nested"]["key"]`) by one of `adapter.CouplingAssumptions.from_config_dict()`,
  `network.baseline.GateTolerances.from_config_dict()`,
  `network.candidate.GeothermalInjectionPolicy.from_config_dict()`,
  `economics.EconomicAssumptions.from_config_dict()`, or
  `workflow.core._build_blueprint_kwargs()` — and its value participates in a scientific or
  technical-gate calculation, or in constructing the fixed synthetic network.
- **DESCRIPTIVE** — present in the JSON file, never read by any of the above (or by any other
  `config[...]` access anywhere in `src/`), and carries no runtime effect whatsoever. Verified
  by `grep -rn` for each key across `src/` and finding zero non-config, non-doc occurrences.
- **DEPRECATED** — none currently exist in this config (see "On deprecation" below).
- **UNSUPPORTED** — a key this config-loading approach has no way to reject: because every
  `from_config_dict()` reads specific, LITERAL keys via plain dict indexing (`config["gates"]`, not
  a Pydantic model validating the whole file with `extra="forbid"`), any misspelled, renamed, or
  genuinely novel key placed anywhere in the file is silently invisible — neither validated nor
  rejected, neither read nor warned about. This is a structural property of how config is loaded
  today, not a list of specific unsupported keys (none exist in the shipped, hand-authored configs).

## `_meta` — entirely DESCRIPTIVE

Every field under `_meta` (`schema_version`, `status`, `created`/`revised`, the full `changelog`
history, `description`, `questions_document`, `adr`/`adr_temperature_source`,
`source_plan_sections`, `pressure_convention`, `questions_without_config_impact`) is documentation
for a human reader. None of it is read by any code path.

## `coupling_assumptions` — mostly EXECUTABLE

EXECUTABLE (all read by `CouplingAssumptions.from_config_dict()` or
`GeothermalInjectionPolicy.from_config_dict()`): `dh_supply_temperature_c`,
`dh_return_temperature_c`, `minimum_hx_approach_k`, `hx_heat_delivery_factor`,
`reinjection_minimum_temperature_c`, `dh_water_specific_heat_capacity_j_kg_k`,
`curtailment_allowed`, `auxiliary_policy`, `minimum_auxiliary_circulation_fraction`,
`injection_sizing_policy` (optional, `.get()`-defaulted — DSP-005, absent from the canonical
config), and (via `GateTolerances.from_config_dict()` reading `config["gates"]` instead, listed
there) `velocity_limit_m_s`/`pump_dp_limit_bar`/`consumer_supply_drop_limit_k`/
`mass_balance_tolerance_fraction`/`energy_balance_tolerance_fraction` are declared HERE but the
values actually consumed for the technical gates come from the separate `gates` section below —
these `coupling_assumptions.*_limit_*`/`*_tolerance_*` copies are DESCRIPTIVE duplicates (see
"A concrete duplicate-value finding" below).

DESCRIPTIVE: `_status`, `_question_refs`, `dh_water_specific_heat_capacity_note`,
`reinjection_minimum_temperature_note`, `minimum_auxiliary_circulation_fraction_note`,
`auxiliary_policy_options` (a documentation list of the `Literal` values
`GeothermalInjectionPolicy.auxiliary_policy` actually accepts — the real constraint is enforced by
the Pydantic `Literal` type itself, not by reading this list).

## `pydoublet` — almost entirely DESCRIPTIVE (one concrete finding)

**Only `pydoublet.energy_consistency_tolerance_fraction` is EXECUTABLE** (read by
`CouplingAssumptions.from_config_dict()`).

Every other field — `example_config`, the entire `producer_wellhead_temperature` block (its own
`path_format`/`primary_field_path`/`legacy_fallback_field_path`/`mapping_status`/
`evidence_pydoublet_commit`/`fallback_policy`/`audit_warning_code`/tolerance fields/`note`), the
entire `scenario_identity` block, the entire `calculation_mode_policy` block, and the entire
`legacy_run_count_correction` block — is **DESCRIPTIVE ONLY**. Verified directly:
`parsers/pydoublet_parser.py` contains zero `config[...]` accesses of any kind. The actual JSON
pointer paths, fallback policy, calculation-mode gate, and legacy-run-count correction this section
describes are all **hardcoded Python logic** in `parsers/pydoublet_parser.py`, not data read from
this config section. This is a genuine, worth-stating-plainly finding: a reader changing, say,
`pydoublet.producer_wellhead_temperature.primary_field_path` in this file would have **zero effect**
on parsing behavior — the actual path is a Python string literal in the parser module. The config
section is accurate, current documentation of what the hardcoded logic does, not a lever that
controls it.

## `network` — a mix, with several DESCRIPTIVE fields that look configurable

EXECUTABLE (via `workflow.core._build_blueprint_kwargs()`): `consumers[].id`,
`consumers[].demand_kw`, `pipe_sizing.trunk_pipe_dn_mm`, `pipe_sizing.branch_pipe_dn_mm`,
`design_delta_t_k`, `ground_temperature_c`, `pipe_sizing.pipe_heat_transfer_coefficient_w_per_m2k`,
`pipe_roughness_mm`, `p_supply_bar_abs`, `circulation_pump.pressure_lift_bar`.

DESCRIPTIVE (verified: zero `config[...]` reads anywhere in `src/` for any of these):
`atmospheric_pressure_bar` (the actual value pandapipes uses is a Python constant,
`network/pressure.py::ATMOSPHERIC_PRESSURE_BAR = 1.01325`, matching pandapipes' own
`NORMAL_PRESSURE` — this config field documents that constant, does not set it), `fluid` (the
network is always built with water; nothing reads this key to select a fluid), `min_pressure_bar_abs`
and `min_pressure_note` at THIS `network.*` location (the value actually enforced as a gate comes
from `gates.min_pressure_bar_abs` instead — see "A concrete duplicate-value finding"),
`mirrored_return_network` (always true by construction; no code branches on this key),
`pressure_reference` (always "absolute" by the project's own fixed convention,
`_meta.pressure_convention`; nothing reads this key), `total_demand_kw` (a documentation sum of the
four `consumers[].demand_kw` values, never independently read or cross-checked against them by
code), and the entire `geometry` block (`trunk_segment_length_m`, `trunk_segment_count`,
`consumer_branch_offset_m`, `candidate_site_offsets_m`, `trunk_to_candidate_attachment`,
`trunk_to_consumer_attachment`) — the actual fixed synthetic-network coordinates are hardcoded in
`network/geometry.py`, cross-checked against this documentation by `tests/network/test_geometry.py`,
not read from it at runtime.

## `candidates` — the `list` array is entirely DESCRIPTIVE

**`candidates.list` and every field within each of its four entries
(`id`/`label`/`surface_connection_length_m`/`supply_junction`/`return_junction`/`connection_dn`/
`construction_multiplier`) are DESCRIPTIVE.** Verified: `_build_blueprint_kwargs()` never reads
`config["candidates"]` at all for the predefined C1-C4 case — the actual C1-C4 topology
(junction pairs, connection lengths) is hardcoded in `network/geometry.py`, matching this section's
own documented values exactly (cross-checked by test) but not driven by them. This is the single
most likely field to mislead a reader into believing it configures the demonstration's candidate
set — it does not, for the canonical `mode=="predefined"` case.

EXECUTABLE (added since — Phase 3.2/Phase 4, absent from the canonical config):
`include_workshop_negative_demo`/`workshop_negative_demo.*` (read by
`workflow/core.py::_apply_workshop_negative_demo()`), `mode`/`generated.connection_pipe_dn_mm`/
`generated.max_route_length_m`/`generated.max_candidates` (read by
`workflow/core.py::_apply_candidate_mode()` and `workflow/joint_workflow.py`'s own stage 2).

DESCRIPTIVE: `_status`, `_note`.

## `gates` — entirely EXECUTABLE (the actual gate thresholds)

Every field (`max_pipe_velocity_m_s`, `max_pump_dp_bar`, `min_pressure_bar_abs`,
`max_consumer_supply_drop_k`, `heat_delivery_tolerance_fraction`, `mass_balance_tolerance_fraction`,
`energy_balance_tolerance_fraction`) is read by `GateTolerances.from_config_dict()` and is the
value ACTUALLY compared against every technical-gate check in `network/candidate.py`/
`network/baseline.py`. DESCRIPTIVE: `_status`, `_note`, `pressure_reference` (documentation of the
project-wide absolute-pressure convention; not read),
`pydoublet_energy_consistency_tolerance_fraction` (a documentation duplicate of
`pydoublet.energy_consistency_tolerance_fraction`, the field actually read),
`require_sequential_thermal_convergence` (always enforced unconditionally by
`evaluate_candidate()`/`run_baseline_evaluation()`'s own hardcoded logic; not read as a toggle).

## `economics` — `.value` fields EXECUTABLE, everything else DESCRIPTIVE, plus one concrete finding

EXECUTABLE: every `.value` leaf under `interest_rate_real`, `lifetime_years.{doublet,
heat_exchanger, connection_pipes}`, `capex.{doublet_capex, heat_exchanger_capex,
connection_pipe_per_m}`, `opex.{fixed_om_fraction_of_capex_per_a, electricity_price,
auxiliary_heat_price}`, `annual_full_load_hours`, `dh_pump_efficiency` — all read by
`EconomicAssumptions.from_config_dict()`.

DESCRIPTIVE: `_status`, `_note`, every `.currency`/`.price_year`/`.source_status`/`.unit`/
`.source_note`/`*_note` sibling of the `.value` fields above.

**`economics.ranking_rule` and `economics.tie_breakers` are entirely DESCRIPTIVE.** Verified: zero
occurrences of either key anywhere in `src/`. The actual ranking rule
("feasibility_first_then_lowest_annualised_cost") and tie-breaker order (lower DH pumping
electricity, then shorter connection length, then greater technical margin) are **hardcoded directly
in `economics/ranking.py`**, exactly matching what these two config fields describe — but changing
either field's value in the JSON file would have zero effect on the actual ranking algorithm.

## A concrete duplicate-value finding

Three technical thresholds are declared TWICE in this config, under two different sections, with
only ONE of the two locations actually read:

| Value | Declared (descriptive) at | Actually enforced from |
|---|---|---|
| velocity limit | `coupling_assumptions.velocity_limit_m_s` | `gates.max_pipe_velocity_m_s` |
| pump differential-pressure limit | `coupling_assumptions.pump_dp_limit_bar` | `gates.max_pump_dp_bar` |
| minimum absolute pressure | `network.min_pressure_bar_abs` | `gates.min_pressure_bar_abs` |
| consumer supply-temperature-drop limit | `coupling_assumptions.consumer_supply_drop_limit_k` | `gates.max_consumer_supply_drop_k` |
| mass-balance tolerance | `coupling_assumptions.mass_balance_tolerance_fraction` | `gates.mass_balance_tolerance_fraction` |
| energy-balance tolerance | `coupling_assumptions.energy_balance_tolerance_fraction` | `gates.energy_balance_tolerance_fraction` |

In the shipped `config/demo_assumptions.json` (and every config forked from it) the two copies are
kept numerically IDENTICAL by convention, so this has never produced a discrepancy in practice --
but nothing in the code CHECKS that they agree, and only the `gates.*` copy has any effect. A future
edit that changes one copy without the other would silently do nothing (if the descriptive copy was
the one edited) rather than raise an error. Not fixed in this phase (fixing it would mean either
removing the descriptive duplicates -- a config-content change requiring the same approval as any
other assumption change -- or adding a new cross-check validator, itself new scope); reported here
as an honest finding per Phase 6's own instruction, not silently glossed over.

## On deprecation

No field in the current config is DEPRECATED in the sense of "still present, no longer read, kept
only for backward compatibility." The changelog documents fields that were RENAMED/RELOCATED across
schema versions (e.g. `pydoublet.reinjection_temperature_c` → `coupling_assumptions
.reinjection_minimum_temperature_c` at schema 0.6) — in every such case the OLD key was removed from
the file entirely at the time of the move, not left behind alongside the new one. There is
therefore nothing to classify as deprecated today.

## Resolved-executable-configuration hashing: explicitly not added in this phase

Phase 6 also asks to "produce and hash a resolved executable configuration." A function computing
exactly the EXECUTABLE-classified subset above (discarding every DESCRIPTIVE field) and hashing it
independently of `config_snapshot.json`'s existing full-raw-config hash would be straightforward to
add as a standalone utility. It was deliberately NOT wired into `WorkflowAuditRecord`/`ManifestRecord`
in this phase: doing so would add a new field to those already hash-pinned, heavily-tested contracts,
moving `bundle_scientific_sha256` for the canonical golden run a FOURTH time in this same session
(after IMPL-015 and IMPL-017's own rebaselines) for a purely additive audit-completeness field with
no scientific-value change — a real but avoidable cost given how much other genuine functionality
this session already delivered. Recorded here as a scope decision, not a silent gap: a future,
separately-scheduled change can add `resolved_config_sha256` to the audit record following the exact
same GOV-004 diagnose-then-rebaseline process already demonstrated twice in this session's own
commit history.
