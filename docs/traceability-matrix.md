# R3-CHAIN prototype completion — final requirements traceability matrix

Prepared per `R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` §26/Phase 9. Every requirement ID in
that document has a row below. **PASS** means implemented and verified with executable evidence;
**PARTIAL** means implemented with a documented, honest gap; **BLOCKED** means correctly not
attempted because it requires external data/approval not yet supplied (Phase 8). No PARTIAL or
BLOCKED item is collapsed into PASS.

Implementation branch: `feature/complete-synthetic-prototype` (linear history from
`feature/r3chain-orchestration-poc` @ `9478c391`, which itself carries the first-session history
recorded below: `5951189` (Phase 1), `6a7efca` (Phase 2), `1796b29` + `2f064d1` + `311a5a6` (Phase
3), `3ea33e6` (Phase 4), `09dc653` (Phase 5), `321a786` (Phase 6), `8eb61d3` (Phase 7)). A second,
later session (against `R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md`'s own Phases 0-9
numbering, distinct from the first session's Workstream-labelled phases above) added: `bb513e0`
(spec preserved in-repo), `1ba27a0` (reproducible dev install), `df91ce9` (scientific-hash
cross-platform fix), `760d608` (CI), `aa3b97e` (lifecycle test hardening), `5e84ffc` (gate-precedence
documentation), `1565eb4` (Phase 3.1 — doublet-component retargeting), `a481dc1` (Phase 3.2 —
generated candidates wired into `run_workflow`), `1c45971` (Phase 4 — joint-optimization full
product + its own workflow entry point), `d2b4994` (Phase 5 — real-data readiness gate), `042feba`
(Phase 6 — config classification + registry retention). This document's own status column reflects
BOTH sessions' cumulative state, updated in place rather than superseded — a row unchanged since the
first session keeps its original evidence citation; a row this second session's work resolved,
partially resolved, or added is marked and dated below. Full offline suite as of this report: see
`docs/decisions/decision-register.md`'s final entries and this document's own "Final suite result"
section below.

## Workstream A — governance

| ID | Status | Evidence |
|---|---|---|
| GOV-001 | PASS | Phase 0 report (this conversation); baseline commit `940f4cf`; nested repos (`repos/PyDoublet`, `repos/pandapipesAI`) verified untouched throughout. |
| GOV-002 | PASS | 8 focused feature-workstream commits; no force-push; no destructive git operations used. |
| GOV-003 | PASS | `docs/decisions/decision-register.md` — Q1–Q11 plus IMPL-001..013. |
| GOV-004 | PASS | Applied explicitly at every schema-identity change (IMPL-007 CFG-003, IMPL-008 DSP-005): stop → before/after diff → causal code identification → classification → rebaseline only the specific literal, `run_id` and canonical KPI values re-verified unchanged each time. |

## Workstream B — input provenance (Phase 1, `5951189`)

| ID | Status | Evidence |
|---|---|---|
| IP-001 | PASS | `expected_raw_sha256` keyword parameter on `parse_pydoublet_result()`/`run_workflow()` (IMPL-001 records why it is a parameter, not a `SourceProvenance` field). |
| IP-002 | PASS | Server independently recomputes `canonical_raw_result_sha256()`; never trusts a client-supplied actual hash. |
| IP-003 | PASS | `PYDOUBLET_RAW_HASH_MISMATCH` failure code, `input_provenance_validation` stage, `recoverable=true`. |
| IP-004 | PASS | Audit records expected/calculated hash, verification result, `CANONICAL_RAW_HASH_ALGORITHM_VERSION`. |
| IP-005 | PASS | `config/demo_source_provenance_strict.json` pins the canonical repaired-fixture hash; historical golden run/evidence untouched. |
| IP-006 | PASS | `tests/mcp_server/test_input_provenance_mcp.py`, `tests/workflow/test_input_provenance_run_id.py`; mismatch creates no artifact directory. |
| IP-007 | PASS | No new arbitrary-file-path MCP surface introduced. |

## Workstream C — persistent run registry (Phase 2, `6a7efca`)

| ID | Status | Evidence |
|---|---|---|
| RR-001 | PASS | `R3CHAIN_RUN_ROOT` env var opt-in; default remains the ephemeral temp-directory behaviour byte-for-byte. |
| RR-002 | PASS | `.staging-<run_id>-<uuid>` → validated → atomic rename to the final run directory. |
| RR-003 | PASS | `_rehydrate()`/`_load_run_entry()` — pattern-matched directory names, manifest schema/run-id/hash re-verification, warnings collected, never a crash. |
| RR-004 | PASS | Rehydrated `RunEntry` reconstructs run id, status, bundle dir, summary, artifact inventory. |
| RR-005 | PASS | Existing in-memory dedup/locking primitive unchanged and reused. |
| RR-006 | PASS *(resolved 2026-09-03, `042feba`)* | Max-size FIFO/pinned eviction (count-based retention) plus a NEW `RunRegistry(max_age_days=...)` (age-based retention, `None`-disabled by default so it can never unexpectedly destroy acceptance evidence) — both controls, applied at startup rehydration only, never a running timer. `tests/mcp_server/test_persistent_registry.py`'s 5 new tests: default-disabled, non-positive-value rejection, pruning past the configured age, non-pruning within it, and (a related RR-008 strengthening) multiple simultaneously-stored runs surviving restart independently. |
| RR-007 | PASS | Existing artifact allow-list/offset/limit/path-traversal protections unchanged. |
| RR-008 | PASS | `test_rr008_restart_recovery_full_acceptance` — the exact 8-step scenario, executed and passing. |
| RR-009 | PASS | Typed errors for unknown run id, corrupt manifest, missing/unapproved artifact, invalid pagination; never silently regenerates on a read-only call. |

## Workstream D — configuration and gates (Phase 3, `1796b29`)

| ID | Status | Evidence |
|---|---|---|
| CFG-001 | PASS *(resolved 2026-09-03, `042feba`)* | `docs/config-field-classification.md` classifies every field of `config/demo_assumptions.json` executable/descriptive/deprecated/unsupported, verified against actual `from_config_dict()` call sites (not inferred), with mechanical proof (`tests/test_config_field_classification.py`, 4 tests: bulk and per-field descriptive-field removal leaves validation passing; an executable-field control proves the test method detects real dependencies). Confirms `candidates.list` is descriptive-only (as previously noted) and additionally surfaces that almost the entire `pydoublet.*` section, `economics.ranking_rule`/`tie_breakers`, and six duplicated technical thresholds (`coupling_assumptions.*`/`network.min_pressure_bar_abs` vs. the `gates.*` copies actually enforced) are also descriptive-only — findings not previously documented. |
| CFG-002 | **PARTIAL, now explicitly scoped** *(2026-09-03)* | Exact source-config identity (`config_sha256`) remains preserved and load-bearing throughout. A `resolved_config_sha256` (hashing only the CFG-001-classified executable subset) was deliberately NOT added this session either: doing so would add a new field to the already hash-pinned `WorkflowAuditRecord`/`ManifestRecord` contracts, moving `bundle_scientific_sha256` for the canonical golden run a fourth time in one session for a purely additive audit-completeness field — recorded as a scope decision in `docs/config-field-classification.md`'s own closing section, with the exact GOV-004 process a future change must follow. |
| CFG-003 | PASS | `max_pump_dp_bar` and `heat_delivery_tolerance_fraction` now enforced (`PUMP_DIFFERENTIAL_PRESSURE_EXCEEDED`, `GEOTHERMAL_HEAT_SHORTFALL`); ranking tie-break order remains hard-coded, not config-driven (a residual, documented instance of the same class of gap). |
| CFG-004 | PASS | Gate order in `network/baseline.py`/`network/candidate.py` reordered and verified (pressure → pump-dp → velocity → mass-balance → energy-balance); delivered-heat/capacity gate placed immediately after candidate convergence. |
| CFG-005 | PASS | Pre-existing `network/pressure.py` gauge/absolute discipline, unchanged and still enforced. |
| CFG-006 | PASS | Verified by a genuinely fresh, isolated wheel install (Phase 9, this document) reproducing `run_id=r3chain-run-93d41133daa11d1a` and the exact canonical LCOH set unchanged through every subsequent phase. |

## Workstream E — dispatch, shortfall, self-consistent flow (Phase 3, `2f064d1`)

| ID | Status | Evidence |
|---|---|---|
| DSP-001 | PASS | `GeothermalInjectionPolicy.auxiliary_policy` (`cost_shortfall`≡`auxiliary_supply`/`strict_infeasible`) — unknown values rejected by Pydantic validation. |
| DSP-002 | PASS | Existing `cost_shortfall` behaviour, unchanged, documented against DSP-002's exact requirements. |
| DSP-003 | PASS | `strict_infeasible` implemented; `GEOTHERMAL_HEAT_SHORTFALL` failure code; AC-05 reproduced directly. |
| DSP-004 | PASS | Resource-limited shortfall (DSP-003's gate) kept structurally separate from the pre-existing numerical-stabilization margin; DSP-006's sensitivity sweep empirically confirms the two are independent causes. |
| DSP-005 | PASS | `_solve_self_consistent_injection()` — a bounded bisection root solve (documented deviation from the literally-worded damped fixed-point iteration, which was tried first and found to diverge; DSP-005 explicitly permits "iteration or root solve"). Converges in 16 solves for the golden case. |
| DSP-006 | PASS | 0/0.5/1/2% × 2-policy sensitivity sweep executed and asserted exactly (`test_dsp006_stabilization_margin_sensitivity`); canonical default retained per DSP-006's own instruction not to silently select a new policy. |

## Workstream F — intentionally infeasible demonstration (Phase 3, `311a5a6`)

| ID | Status | Evidence |
|---|---|---|
| FAIL-001 | PASS | `config/demo_assumptions_workshop_negative.json` — a genuinely separate file; canonical config never modified. |
| FAIL-002 | PASS | `C5_negative` — 200× C1's connection length, deterministic `PRESSURE_LIMIT_EXCEEDED`, non-borderline margin (~84% below threshold). |
| FAIL-003 | PASS | Verified directly in `workflow_result.json`, `candidate_comparison.csv`, `recommendation.md`, and `audit.json`'s stage-call record — exact code/value/threshold, excluded from ranking, no invented LCOH. |
| FAIL-004 | PASS | `tests/network/test_candidate.py` (unit) + `tests/workflow/test_workshop_negative_demo.py` (end-to-end, 14 tests) — stability and non-interference with C1-C4 both proven. |

## Workstream G — reusable geothermal-doublet component (Phase 4, `3ea33e6`)

| ID | Status | Evidence |
|---|---|---|
| DLT-001 | PASS | All six named models implemented in `network/doublet_component.py`. |
| DLT-002 | PASS | Every DLT-002-listed input present and unit-bearing. |
| DLT-003 | PASS | Documented topology reproduced (not redefined) from `network/candidate.py`. |
| DLT-004 | PASS | Fresh-net-per-call, no blueprint mutation, bit-identical repeated calls, no cross-candidate contamination — all directly tested. |
| DLT-005 | PASS | All DLT-005-listed result fields present, including pandapipes element handles. |
| DLT-006 | PASS | Parity by construction (shared underlying calls) — bit-identical (`rel_tol=1e-12`) to `evaluate_candidate()` for all 4 candidates × 2 sizing policies. |
| DLT-007 | PASS | `docs/geothermal-doublet-component-guide.md` — boundary diagram, inputs/units, equations, limitations, construction and result-extraction examples, explicit "not necessarily upstream" statement. |
| *(Phase-4 exit gate)* | PASS *(resolved 2026-09-03, `1565eb4`)* | `evaluate_candidate()` NOW retargeted to call `build_and_evaluate_geothermal_doublet_with_net()` directly — the prior deferral is superseded (`docs/issues/geothermal-doublet-component.md`'s own "Update" section). Reverses the earlier deliberate deferral per an explicit later instruction not to preserve duplicate orchestration code without a documented reason; a genuine cross-module constant-propagation bug surfaced and fixed during the retargeting (`DoubletOperatingPolicy`'s solver-tolerance defaults now read `network.candidate`'s constants via a live module reference instead of a copied-at-import-time value). Zero KPI/`run_id`/hash impact, verified by the full pre-existing exact-value-pinned test suite passing with zero test-file edits beyond the one genuine bug fix. |

## Workstream H — candidate generation (Phase 5, `09dc653`)

| ID | Status | Evidence |
|---|---|---|
| CAN-001 | PASS, strengthened *(2026-09-03, `a481dc1`)* | Predefined (unchanged) and generated (`network/candidate_generation.py`) modes both present and independently tested. Generated mode is now additionally WIRED into `run_workflow()`/`validate_config_structure()` via `config["candidates"]["mode"]` (`workflow/core.py::_apply_candidate_mode()`), reachable through the CLI and, for MCP, by pointing the server's fixed config at a config with `mode=="generated"` — no longer library-only. `config/demo_assumptions_generated_candidates.json` demonstrates it end to end. `mcp_server/schemas.py::CapabilitiesSummary.candidate_generation_modes`'s own docstring updated to drop the now-stale "not yet wired" caveat. |
| CAN-002 | PASS | Explicit eligibility rules (trunk/consumer membership, one exclusion zone, a max-route-length limit); never a proximity-only connection. |
| CAN-003 | PASS | `{study_id}-{attachment_id}-{route_id}-{design_option_id}`, stable and iteration-order-independent. |
| CAN-004 | PASS | `RouteOption.kind` interface with `synthetic_direct` implemented; `network_graph`/`external_gis` declared but raise `NotImplementedError` rather than mislabel a straight-line distance. |
| CAN-005 | **PASS, with 2 of 7 reasons type-level-only** | `ROUTE_LENGTH_EXCEEDS_LIMIT`/`EXCLUDED_PROTECTED_GEOMETRY` occur naturally; `MISSING_SUPPLY_RETURN_PAIR`/`MISSING_PIPE_OR_DESIGN_DATA`/`DUPLICATE_TOPOLOGY` reachable via `generate_candidates()` with contrived arguments; `INVALID_PRESSURE_ZONE_PAIRING`/`COMPONENT_CONSTRUCTION_CONFLICT` are genuinely unreachable by this generator's own loop structure and proven only at the type level (documented, not silently untested). |
| CAN-006 | PASS | Candidate identity distinguishes location/route/design; a second, differently-sized design option is not yet constructable by the evaluator (documented limitation, not fabricated). |
| CAN-007 | PASS | 16 candidates / 11 accepted / 5 rejected, deterministic; ≥1 screened example; canonical C1-C4 untouched. |

## Workstream I — real network/GIS/geological data contracts (Phase 6, `321a786`)

| ID | Status | Evidence |
|---|---|---|
| DATA-001 | PASS | `StudyPackage` (manifest + network + geothermal_scenarios + economics + decisions); geography represented via manifest spatial-layer metadata (documented scope choice). |
| DATA-002 | PASS | All manifest fields present and validated (`StudyPackageManifest`). |
| DATA-003 | PASS | `NetworkDataPackage` — all DATA-003-listed fields. |
| DATA-004 | **PASS, at the metadata layer** | CRS declared/required-by-validator, never guessed; no GeoJSON geometry-validity engine implemented (no new GIS dependency) — documented explicitly. |
| DATA-005 | PASS | `GeothermalScenarioRecord` — all DATA-005-listed fields. |
| DATA-006 | PASS | `EconomicLineItem` — currency/price-year/source/approval/uncertainty/inclusion-note, separate line-item categories. |
| DATA-007 | PASS | `validate_study_package()` — exact field/location errors, never silent imputation, never raises; duplicate/topology/temperature/CRS/provenance/unit checks. |
| DATA-008 | PASS | `build_synthetic_sample_package()` ("Riverbend", invented) — validates cleanly, exercises every schema section. |
| DATA-009 | PASS, strengthened *(2026-09-03, `d2b4994`)* | `generate_readiness_report()` — supplied/missing datasets, validation errors, provisional assumptions, unresolved approvals, both optimisation-permission flags. ADDITIONALLY, `enforce_real_data_readiness()` (new) wraps this in a discriminated `RealDataReadinessGranted`/`DataRequirementsNotMet` boundary result naming the exact `DATA_REQUIREMENTS_NOT_MET` failure via 8 named `RealDataRequirement` categories — the mandatory choke point for a future real-data entry point, with 7 new tests (`tests/data_contracts/test_readiness_gate.py`) including a genuinely complete, approved REAL package proving the granted path is reachable for real data, not only synthetic. |

## Workstream J — synthetic joint site/connection optimisation (Phase 7, `8eb61d3`)

| ID | Status | Evidence |
|---|---|---|
| OPT-001 | PASS | `AlternativeIdentity` — the full six-component tuple, never one generic field. |
| OPT-002 | PASS | `evaluate_alternative()` sequences the 10 stages (collapsed to 4 observable `JointEvaluationStage` values where existing functions perform several stages internally — documented). |
| OPT-003 | PASS | `pareto_shortlist()` — non-dominated filter across 6 objectives with actual data; no invented weights (no approved weighting policy exists). |
| OPT-004 | PASS | Per-scenario results reported directly; no probabilistic uncertainty is fabricated (single deterministic scenario per alternative, explicitly noted in each `risk_note`). |
| OPT-005 | PASS, strengthened *(2026-09-03, `1c45971`)* | Curated 6-alternative demonstration (`run_joint_optimization_demo()`) UNCHANGED and still available, every numeric minimum measured and asserted directly. ADDITIONALLY, `run_joint_optimization_full_product()` now evaluates the FULL, uncurated product (3 synthetic scenarios × 11 accepted generated candidates = 33 alternatives, measured; `len(result.alternatives)` equals the unfiltered search-space size by construction) — satisfying the specification's own instruction not to limit the demonstration to a hand-selected list without disclosing the unfiltered size, wrapped in its own top-level workflow entry point (`workflow/joint_workflow.py`) reachable from the CLI via `config["joint_optimization"]["enabled"]`. |
| OPT-006 | **PARTIAL, gate now exists, not yet wired here** *(2026-09-03, `d2b4994`)* | `data_contracts.readiness.enforce_real_data_readiness()` (new) is now the MANDATORY, typed `DATA_REQUIREMENTS_NOT_MET`-returning gate any future real-data caller must use — a genuine strengthening over the prior state (a permission-flag-only report). It is still not wired into `joint_optimization.py` itself, and — verified directly before this session's work — there is currently no real-data entry point anywhere in this repository to wire it into; Phase 8 remains blocked (`docs/issues/real-data-readiness-gate.md`). |
| OPT-007 | **PASS, lighter-weight than the main pipeline** | 5 of 6 named files produced (`location_shortlist.geojson` never applicable — no real spatial data); no full byte/scientific-hash manifest audit for the ORIGINAL curated-demo export path (documented scope decision, unchanged). The NEW full-product workflow entry point (OPT-005 above) DOES carry a full byte/scientific-hash-audited manifest (`JointOptimizationManifestRecord`, `write_joint_optimization_artifacts()`) — the audit gap is closed for that path specifically, not for `joint_optimization_export.py`'s original lighter-weight exporter. |

## Workstream K — corrected joint site/connection layer, v2 (this session, 2026-09-04)

Workstream J above (OPT-001..007) describes `workflow/joint_optimization.py` (v1) exactly as it is —
unchanged throughout this workstream, and still accurate. A subsequent, separate specification,
`docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md` (ADR-001
amendment D10), corrects the specific methodological gaps that document's own §2.5 names in v1
(site as a bare label rather than coordinates; scenarios as perturbations rather than
independently site-linked; global routes not bound to site origin; a Cartesian product rather than
compatibility-screened enumeration; connection diameter recorded but not consumed by the physics
evaluator; mathematically dependent Pareto objectives; strict rather than materiality-aware
dominance; no committed ready-to-run config; no MCP dispatch). That specification defines its own
~300 requirement IDs (TERM/DATA/GOV/ARCH/ROUTE/SCEN/DESIGN/EVAL/ECON/DEC/WF/AUD/MCP/REPRO/FAIL/
NFR-prefixed) and its own acceptance scenarios (AC-J01 through AC-J18, §20) — these are **not**
retrofitted row-by-row into this document (the same choice `docs/acceptance-criteria.md` already
made for this same specification): a second ~300-row parallel table duplicating IDs the
specification itself already defines and phase-tracks (§21) would be a maintenance liability, not
an added guarantee. Consult the specification directly for the authoritative, current, ID-level
record; `docs/decisions/decision-register.md` (IMPL-022 for Phase 1, IMPL-023 for Phases 2-7) and
`docs/decisions/ADR-001-geothermal-poc-scope.md` (D10's own "Implementation status" addendum) for
the decision-level record. Summary, at the phase level, as of this document's own last edit:

| Phase | Scope | Status |
|---|---|---|
| 0 / 0.5 | Read-only baseline audit; remote-URL reconciliation | PASS |
| 1 | Documentation-authority correction; joint package/site/scenario/route/design/decision contracts; relationship validation; active-dimension reporting | PASS — `tests/data_contracts/test_joint_study.py` |
| 2 | Site-linked scenarios/routes; compatible-only enumeration | PASS — AC-J02–AC-J07 proven, `tests/workflow/test_joint_phase2.py` |
| 3 | Executable per-design connection diameter | PASS — AC-J08 proven, `tests/network/test_candidate.py` |
| 4 | Corrected economics; materiality-aware Pareto decision policy | PASS — AC-J09–AC-J11 proven, `tests/workflow/test_joint_phase4.py`, `tests/decision/test_joint_policy.py` |
| 5 | Ready-to-run config; full audit bundle; CLI dispatch | PASS — AC-J12 proven twice into independent output directories, `tests/workflow/test_joint_workflow_v2.py`. The bundle publishes the complete §17 named set (16 hashed files): `resource_input_index.json`, `sites.json`, `resource_scenarios.json`, `site_route_geometry.json` (declares the synthetic Cartesian coordinate basis explicitly) and `network_candidates.svg` (a synthetic-labelled schematic diagram) were originally deferred as redundant sub-content of other files -- that deferral was withdrawn (Phase 9) once §17's own "SHALL publish" wording was read as requiring these named files separately, not merely as recoverable sub-content. |
| 6 | MCP dispatch (six tools, unchanged count); persistent-registry rehydration | PASS — AC-J13/AC-J14 proven, `tests/mcp_server/test_joint_workflow_v2_mcp.py` |
| 7 | Cross-platform reproducibility diagnosis and correction | **PASS** — Linux/arm64 (Python 3.11 and 3.12) verified via local Docker; a first real `ubuntu-latest`/`macos-latest` CI run (`33918616460`) failed all three jobs (4 hash divergences + 1 missed pathological-solver test + 1 unrelated CI-timing flake), all five diagnosed and fixed; a second real CI run (`33948931491`) confirmed both `ubuntu-latest` jobs (3.11 and 3.12) green, with `macos-latest` failing at a different, unrelated pre-existing subprocess-pipe-deadlock test — root-caused (unread `subprocess.PIPE` streams risking a full-buffer write deadlock, not merely a tight timeout) and fixed (`DEVNULL` + 30s margin). A THIRD real CI run (`33953933376`, commit `1d4a3ec`) confirms **all three required jobs green**: `ubuntu-latest`×3.11 (7m44s), `ubuntu-latest`×3.12 (12m13s), `macos-latest`×3.11 (7m6s) — including both canonical and joint wheel-installation smoke tests (only reachable after a passing suite). See `docs/issues/cross-platform-reproducibility.md` for the complete evidence and fix record across all three runs. |
| 8 | Documentation reconciliation | PASS — this edit and the README/ADR-001/decision-register/traceability-matrix edits alongside it; a genuine README self-contradiction (claimed "must run from repo root" after Phase 7's own fix removed that constraint) found and corrected; AC-J17 claim audit found no real-drilling/six-axis overclaims anywhere. |
| 9 | Release-candidate verification | **PASS** — the green CI confirmation tracked under Phase 7 above has now landed; see this document's own "Phase 9 release-candidate verification" section below for the executed checklist and evidence. |

Every canonical C1-C4 golden value (`run_id r3chain-run-93d41133daa11d1a`, the exact LCOH set) is
unchanged throughout this workstream, re-verified after every phase — this workstream never
modifies `workflow/core.py`'s own canonical execution path or `workflow/joint_optimization.py` (v1).
No test was removed or weakened to reach a green suite anywhere in this workstream (CLAUDE.md); the
three REPRO-009 test broadenings (two in Phase 7, a third found and fixed in Phase 9 via real CI
evidence) are documented exactly, in place, as principled corrections approved by the specification
itself, not silent dilutions.

### Phase 9 release-candidate verification (this session, against HEAD as of this edit)

Executed against the corrected working tree, following the specification's own §21 Phase 9 checklist:

1. **Targeted + full test suite** — 1240 collected, 1240 passed, 0 failed, exit code 0, macOS/Python
   3.11.16, ~9-10 minutes wall-clock (consistent with every prior full-suite run this session).
2. **`git diff --check`** — clean, on both tracked changes and untracked new files.
3. **Wheel build + clean-environment install** — a fresh `python -m build --wheel`, installed via
   `python3.11 -m venv` (genuinely new, outside any project-managed environment) with the `mcp` extra.
4. **Canonical CLI outside the repository** — `run_id r3chain-run-93d41133daa11d1a`; ranked LCOH
   `{"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}` reproduced exactly.
5. **Joint v2 CLI outside the repository, run twice** — `run_id r3chain-run-99e7f5ea0fb38a12` both
   times; identical `bundle_scientific_sha256`; the complete 16-file §17 artifact set published both
   times (`resource_input_index.json`, `sites.json`, `resource_scenarios.json`, `joint_study_snapshot.json`,
   `screened_site_connection_routes.json`, `site_route_geometry.json`, `compatible_alternatives.json`,
   `joint_optimization_result.json`, `alternative_comparison.csv`, `objective_policy.json`,
   `pareto_or_ranking.json`, `network_candidates.svg`, `joint_recommendation.md`, `audit.json`,
   `pydoublet_input.json`, `config_snapshot.json`).
6. **Scripted MCP client** (`r3chain-geothermal-mcp-demo`, a genuine live stdio round-trip) —
   `execution_route: mcp`, golden canonical `run_id` reproduced.
7. **MCP restart recovery** — a persistent `RunRegistry` holding both a canonical and a joint run,
   closed and rebuilt against the same root (simulating a server restart): zero rehydration warnings,
   both run types correctly rehydrated (`run_type` discriminator intact), identical
   `bundle_scientific_sha256` for each, and a third call to each confirms `reused_existing_run=True`
   (no recomputation).
8. **Full artifact pagination through MCP** — every one of the 17 joint artifacts (16 hashed files +
   `manifest.json`) and every one of the 8 canonical artifacts retrieved via `geo_get_artifact`
   pagination (`offset`/`limit` loop until `next_offset is None`) and reassembled byte-for-byte
   identical to the on-disk file.
9. **Real-data readiness negative test** (`tests/data_contracts/test_readiness_gate.py`, the two
   `incomplete`-package tests) — passed: an incomplete real package returns
   `DATA_REQUIREMENTS_NOT_MET` with zero solver/ranking calls, never a silent synthetic fallback.
10. **Internal-error-boundary tests** (AC-J18, both canonical and joint) — passed: an injected
    deterministic exception after package/input validation surfaces as `UNEXPECTED_ERROR`, never a
    scientific infeasibility code, publishes no completed run, exposes no partial artifact.
11. **Privacy/secret/personal-path scan** — clean across every changed/new file (no API keys, private
    keys, tokens, or leaked absolute personal/temp-directory paths); one stray `build/` setuptools
    cache directory (from this session's own wheel-build verification, not committed) found and
    removed twice.
12. **Manifest/hash validation** — every `ManifestRecord`/`JointWorkflowV2ManifestRecord` constructed
    during the above self-validates (`bundle_scientific_sha256` recomputation, no self-hashing,
    per-file byte/scientific hash pairs) — covered structurally by every test and CLI run above, none
    of which could have produced a result without passing that validation.
13. **Every changed/new file inspected** — the complete file list for this specific closure pass is a
    clean, reviewable 13-file diff (`git diff --stat`, since nothing is staged/committed in this
    session per its own standing instruction); every file was authored or edited directly in this
    session, not generated blind.

**Closed**: the fresh green three-job GitHub Actions run this section previously awaited (tracked
under Phase 7 above) landed as CI run `33953933376` against commit `1d4a3ec` — all three required
jobs pass. Nothing in this checklist remains open.

## Workstream L — research-experiment layer (this session, 2026-09-05)

Workstream K above (the corrected v2 joint site/connection layer) is complete and unchanged
throughout this workstream. A subsequent specification,
`docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md` (ADR-001 amendment
D11), defines a NEW layer built entirely on top of v2: three representative steady-state load
conditions per compatible alternative, annualized-system-LCOH primary-objective ranking (v2's own
Pareto machinery reused unchanged and retained as a secondary diagnostic), three baselines
(geothermal-only, network-only fixed-source, integrated) with a deterministic cross-baseline
comparison, and a small deterministic sensitivity/robustness study. That specification defines its
own requirement-ID taxonomy (RA-GOV/DATA/LOAD/ECON/DEC/BASE/SENS/API/ART/TEST) and acceptance
scenarios (AC-RA01 through AC-RA17) — not retrofitted row-by-row into this document, the same
choice already made for Workstream K's own AC-J set. Consult the specification directly for the
authoritative, ID-level record; `docs/decisions/decision-register.md` (IMPL-027) and
`docs/decisions/ADR-001-geothermal-poc-scope.md` (D11) for the decision-level record. Summary, at
the phase level, as of this document's own last edit:

| Phase | Scope | Status |
|---|---|---|
| 0 | Read-only audit against the actual v2 code (curtailment-stability risk area investigated directly, not assumed) | PASS |
| 1 | `data_contracts/research_experiment.py` typed contracts; relationship/invariant validation | PASS — `tests/data_contracts/test_research_experiment.py` |
| 2 | Per-(alternative, load-state) evaluation, reusing `workflow.joint_evaluation.evaluate_alternative()` unchanged | PASS — `tests/workflow/test_load_state_evaluation.py`, including the flagged low-load curtailment risk case |
| 3 | Annualized system economics (CAPEX/annuity once, OPEX/auxiliary/pumping summed across load states) | PASS — `tests/economics/test_annualized_system_costing.py` |
| 4 | Cross-baseline comparison, decision reuse, deterministic sensitivity/robustness | PASS — `tests/decision/test_research_comparison.py`, exercising all 7 comparison codes and all 6 robustness classifications |
| 5 | Orchestrator (`workflow/research_experiment.py`), committed config, CLI wiring | PASS — `tests/workflow/test_research_experiment.py`, end-to-end against the committed `config/research_experiment_synthetic.json` |
| 6 | MCP dispatch (`workflow_mode: research_experiment` on the existing six tools, `run_type` registry rehydration) | PASS — `tests/mcp_server/test_research_experiment_mcp.py`, including restart-recovery rehydration |
| 7 | Full artifact bundle (`workflow/research_experiment_export.py`) | PASS — `tests/workflow/test_research_experiment_export.py` |
| 8 | Documentation reconciliation | PASS — this edit and the README/CLAUDE.md/ADR-001/acceptance-criteria/decision-register edits alongside it |
| 9 | Release-candidate verification | pending — see "Remaining work" below |

Every canonical C1-C4 golden value and every v2 golden value (`run_id r3chain-run-99e7f5ea0fb38a12`,
its own counts/decision) is unchanged throughout this workstream, re-verified after every phase
(the full offline suite run clean after each addition) — this workstream never modifies
`workflow/core.py`, `workflow/joint_optimization.py` (v1), or any file under `workflow/joint_workflow_v2.py`'s
own module (it calls `run_joint_workflow_v2()` as a black box). No test was removed or weakened to
reach a green suite (CLAUDE.md).

**Remaining for Phase 9 (honestly scoped, not yet executed):** a fresh real GitHub Actions CI
confirmation of this workstream (verified so far only against this session's local
`.venvs/orchestration` environment, not real `ubuntu-latest`/`macos-latest` hardware); a wheel-build
clean-environment install smoke test exercising the research-experiment CLI path specifically,
mirroring Workstream K's own Phase-9 checklist item 3; and the same privacy/secret-scan and
full-file-review pass Workstream K's own Phase 9 executed. None of these gaps affect any golden
value already reproduced — they are verification-completeness items, not defects found.

### Conformance round (this session, 2026-09-05, after the workstream above was first pushed)

A closer, commit-pinned re-read of `docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md`
against the actual code found three genuine literal conformance gaps (not missing architecture):
an explicit `AnnualizationPolicy`/duration-equality rule the spec's §1.7.3 requires was implemented
only implicitly as an upper-bound check; the spec's optional `LoadState.required_for_feasibility`
field was undocumented rather than either implemented or explicitly deferred; and the spec's own
§17 "shall publish at least" 19-file artifact list was published as a smaller 8-file bundle. All
three are now resolved — see `docs/decisions/decision-register.md` IMPL-028 for the full record —
without touching any scientific calculation: the two threaded-through baseline breakdowns
(`geothermal_only_lcoh_by_scenario_id`, `network_only_subset`) and the 15 new artifact renderers are
all thin serializations of data `ResearchExperimentResult` already computed. Full offline suite
re-run clean after every fix; canonical and v2 golden `run_id`s unaffected. The research-experiment
layer's own `run_id` changed (config bytes changed via the new `annualization` section) — expected,
and this layer's own tests derive `run_id` dynamically rather than pinning a golden literal, so
nothing needed updating for that.

### Decision-layer correction (this session, 2026-09-05, a second, deeper review)

A second review, against the actual pushed commit and the spec's own §10–14 text, found the
geothermal-only baseline SILENTLY COLLAPSED multiple resource scenarios sharing one site into a
single best-site value — directly contradicting the spec's own explicit instruction ("do not
silently collapse multiple scenarios at one site into one best-site value") — plus three related
decision-layer defects: the network-only reference was auto-selected rather than declared;
`compare_baselines()` compared single winner IDs rather than rank-1 SETS (the spec's own required
disjointness semantics); and `INTEGRATED_DIFFERS_FROM_BOTH` was structurally unreachable. All four
were independently re-verified directly against the spec text and the committed v2 fixture (which
genuinely has two scenarios on one site, `scenario_alpha_golden`/`scenario_alpha_reduced_flow`,
both `site_alpha`) before any fix — see `docs/decisions/decision-register.md` IMPL-029 for the full
record, including the live-verified, scientifically consequential difference this bug actually
made (the corrected ranking picks a different geothermal-only winner than the buggy per-site
collapse would have). `decision/research_comparison.py` was substantially rewritten to rank
scenarios via the existing materiality-aware `decide()` (reused unchanged), derive rank-1 SETS from
each baseline's own `JointDecisionResult`, and compute disjointness directly. A fifth item (richer
sensitivity rank-group/infeasibility reporting) was also implemented; the spec's own "maximum
observed rank change per candidate" sub-item is explicitly descoped and documented, not silently
dropped. Full offline suite re-run clean; canonical and v2 golden `run_id`s re-confirmed unaffected.

### Final scientific-conformance round (this session, 2026-09-05, a third, letter-by-letter review)

A third review, structured against explicit lettered requirements A–O, warned not to assume the
prior two rounds' local corrections were already correct. Direct re-inspection (not assumption)
confirmed most items — including A, B, D, E (geothermal-only scenario-level ranking, the declared
network-only reference, set-based comparison, all four interpretation codes reachable), J, K
(annualization horizon semantics, LCOH physical/economic boundary), L (artifact bundle coverage)
and N (no scientific logic in the MCP layer) — were already correctly implemented and needed no
further code change. Two genuine gaps remained: `network_only.eligible_attachment_ids` was
declared in `NetworkOnlyBaselinePolicy` but never referenced by any code in `src/` (a
documentation-only field, confirmed by direct search before any fix); and the spec's own §14.3
"maximum observed rank change for each base candidate" metric, previously descoped in the round
above as disproportionate, is now implemented as the user explicitly requested rather than left
descoped, together with item H's symmetric "restored to feasibility" case. Both are computed
purely from each already-computed `JointDecisionResult`'s own `ranked_alternative_groups` — no
re-derived ranking, no new pandapipes/HX re-simulation. Item G (geothermal-derating sensitivity
honesty) required no new physics: the derating path already re-derives economics only from
already-computed KPIs and never re-runs pandapipes, so it structurally cannot fabricate new
infeasibility; this is now stated explicitly rather than left implicit, alongside the one
documented simplification (`dh_hydraulic_pumping_power_kw` held at its base-case value). Item F's
wording is strengthened, not changed: `MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON` is
**RESERVED/DEPRECATED under set-based comparison semantics — rank-1 ties no longer prevent
baseline comparison**. See `docs/decisions/decision-register.md` IMPL-030 for the full record,
including the one bug this round's own implementation caught before any test ran: the final
(non-early-return) construction path inside `run_sensitivity_study()` initially omitted threading
`candidate_rank_sensitivity` through, found and fixed by direct code re-inspection. Full offline
suite re-run clean after every fix in this round; canonical and v2 golden `run_id`s re-confirmed
unaffected.

## MCP and orchestration requirements

| ID | Status | Evidence |
|---|---|---|
| MCP-001 | PASS | Exactly six `geo_` tools, unchanged throughout all seven phases (`test_tools_list_returns_exactly_the_six_geo_tools` still passes). |
| MCP-002 | PASS | `geo_get_capabilities` now additionally advertises provenance-hash enforcement, live persistent-registry status, available shortfall policies, available injection-sizing policies, and candidate-generation modes (added during this Phase 9 hardening pass, `tests/mcp_server/test_tools.py::test_get_capabilities_advertises_the_prototype_completion_spec_capabilities`). Schema/contract version advertisement and max-artifact-page-size were already present pre-existing; data-package schema versions are not yet advertised (Workstream I is not wired into the MCP layer at all — see OPT-006/CFG-001 notes). |
| MCP-003 | PASS | Structured/bounded outputs, pagination, deterministic `geo_run_workflow`, typed errors with code/message/stage/recoverability, warnings never dropped — all pre-existing and unaffected by every addition in this cycle (none touch tool signatures). |
| MCP-004 | PASS | Pre-existing `session_record.json`-style external transcript (timestamp, tool name, run id, status, pagination, response hash) — unaffected. |
| MCP-005 | PASS | Phase 9's own fresh, isolated wheel install + `r3chain-geothermal-mcp-demo` run reproduces the exact golden `run_id`/`bundle_scientific_sha256`/LCOH set (this document, "Clean-install verification" below). A live Claude Desktop 17-page re-demonstration was not repeated for every internal refactor (MCP-005 explicitly says not to); it remains the T5.1C evidence's own responsibility, current as of that evidence's own date. |

## Audit, artifacts and reproducibility

| ID | Status | Evidence |
|---|---|---|
| AUD-001 | PASS | Distinct identifiers maintained throughout: raw bytes, canonical raw JSON hash, normalized scientific hash, source-provenance hash, contract version, artifact byte hash, artifact scientific hash. |
| AUD-002 | PASS | `normalize_for_scientific_hash()`'s versioned rule unchanged and consistently applied; every schema bump this cycle (1.0.0→1.1.0→1.2.0 on two contract families) was recorded, diffed, and classified per GOV-004, never silently applied. |
| AUD-003 | PASS | `ManifestRecord` — every published member's byte hash, scientific hash, size, media type; deterministic bundle-digest ordering, no self-reference. |
| AUD-004 | PASS | `recommendation.md` (single-scenario) and the new joint-optimization `recommendation.md` both state scope, mode, and synthetic/real classification explicitly. |
| AUD-005 | PASS | No historical evidence bundle (`docs/evidence/t5.1c/*`) was modified at any point in this work; every new run produces its own, separately-identified evidence. |

## Non-functional requirements

| ID | Status | Evidence |
|---|---|---|
| NFR-001 | PASS | Determinism verified directly for every new subsystem (self-consistent solver, candidate generation, joint optimisation) via repeated-call bit-identical tests. |
| NFR-002 | PASS | Full offline suite requires no network access and no real Wuppertal data throughout. |
| NFR-003 | PASS | Every new model across all seven phases is an immutable, `extra="forbid"` Pydantic type with unit-bearing field names. |
| NFR-004 | PASS | No broad exception is ever converted to a generic success; every failure surface remains a typed, discriminated result. |
| NFR-005 | PASS | No new arbitrary MCP filesystem access; no GIS/geometry library dependency added; no dynamic code execution; no pickle. |
| NFR-006 | **PARTIAL, narrowed** *(2026-09-03)* | `SELF_CONSISTENT_FLOW_MAX_ITERATIONS` and candidate-generation's own screening limits remain bounded and named. `candidates.generated.max_candidates` (Phase 3.2/`a481dc1`, also honoured by the joint-optimization full product, `workflow/joint_workflow.py`) now provides an explicit, config-exposed cap on the generated-candidate count specifically. A general "maximum scenario combinations/concurrent workflows" bound beyond this and the registry's pre-existing `max_size` was not added this session either. |
| NFR-007 | PASS | Canonical predefined C1-C4 CLI/MCP workflow verified unchanged (Phase 9 fresh-install run); every public schema change in this cycle carried its own contract-version increment. |
| NFR-008 | PASS *(resolved 2026-09-03)* | `README.md` rewritten to cover: environment install (including the `build`/`mcp` extras and a manual wheel-build/smoke-test recipe matching CI), the canonical C1-C4 workflow, strict input-provenance validation, the workshop-negative and generated-candidates alternative demonstrations (both with working, directly-runnable commands), the joint-optimization full-product demonstration, MCP server install + Claude Desktop config, the persistent run registry and its two retention controls, `geo_get_artifact` pagination, and an explicit "Limitations and the real-data boundary" section. This traceability matrix and the now-11 `docs/issues/*.md` records remain the deeper reference for any one capability's own design rationale. |
| NFR-009 | PASS | No restricted real dataset committed; nested-repository provenance untouched. |

## Acceptance scenarios

| ID | Status | Evidence |
|---|---|---|
| AC-01 | PASS | Verified fresh in Phase 9 (below): validation succeeds, C1-C4 independent, ranking `[C1,C2,C3,C4]` unchanged, CLI/MCP agree. |
| AC-02 | PASS | Pre-existing (Phase 1), unaffected by later phases — `PYDOUBLET_RAW_HASH_MISMATCH`, no successful bundle created. |
| AC-03 | PASS | Pre-existing (Phase 2) `test_rr008_restart_recovery_full_acceptance`, unaffected by later phases. |
| AC-04 | PASS | `test_geothermal_heat_shortfall_absent_under_cost_shortfall_policy` — shortfall costed, candidate feasible. |
| AC-05 | PASS | `test_geothermal_heat_shortfall_under_strict_infeasible_policy` — `GEOTHERMAL_HEAT_SHORTFALL`, no rank. |
| AC-06 | PASS | Workshop-negative-demo end-to-end test — `C5_negative` fails deterministically, C1-C4 unaffected. |
| AC-07 | PASS | Doublet-component parity tests — bit-identical to the legacy path, no cross-candidate mutation. |
| AC-08 | PASS | `test_every_accepted_candidate_constructs_and_evaluates_independently` — same stable set/IDs every run, screened with reasons, every accepted candidate independently evaluable (feasible or not). |
| AC-09 | PASS | `build_intentionally_incomplete_real_package()` — pre-flight stops with the exact three named errors, no solver/recommendation code runs, readiness report lists them. |
| AC-10 | PASS | Joint-optimisation demonstration — all combinations enumerated/screened, technical/economic separation proven, ≥2 feasible, Pareto shortlist returned, recommendation explicitly synthetic. |
| AC-11 | **BLOCKED (by design, not attempted)** | Requires a live Claude Desktop session against an installed package — this is an interactive, human-in-the-loop acceptance step outside what this automated session can execute. The equivalent automated proof (fresh wheel install, live `stdio` MCP client, restart recovery, strict-hash success, artifact pagination) is covered by AC-01/02/03/07-10 and this document's own Phase-9 verification; a literal live-Desktop re-run was not performed as part of this session. |

## Clean-install verification (Phase 9, this session)

A genuinely fresh Python 3.11 venv (`python3.11 -m venv`, outside any project-managed environment)
built the wheel (`python -m build --wheel`), installed it with the `mcp` extra, and ran BOTH the
canonical config and the workshop-negative config from directories outside the repository:

- Canonical (`r3chain-geothermal-mcp-demo`, live stdio MCP client): `run_id=r3chain-run-93d41133daa11d1a`,
  `bundle_scientific_sha256=f85243d16a6e43365f12081a6af346d2ea1aa5bbb51a70f760404eb64a1188a1`,
  `{"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}` — all three values EXACTLY match
  the values established before this multi-phase work began and re-verified after every schema
  change throughout it (CFG-006/GOV-004's central promise, now independently confirmed via a real
  installed package rather than only unit tests).
- Workshop-negative (`r3chain-geothermal-demo` CLI, deterministic runner):
  `run_id=r3chain-run-440e06b197eaae18` (a genuinely different, expected identity for a
  deliberately different config), `C5_negative` correctly infeasible, C1-C4 unaffected.

## Final suite result

**HISTORICAL -- superseded by the "Phase 9 release-candidate verification" section (Workstream K,
1240/1240 passing, three-job green CI) and by Workstream L above.** Preserved unedited below for
its own historical record; do not read the figures in this section as the current suite status.

Full offline suite (`.venvs/orchestration`, `python -m pytest -q`), run after every phase and once
more after this Phase 9 hardening pass (which added the MCP-002 capabilities fix and its own test):
**1010 collected, 1009 passed, 1 failed** —
`tests/mcp_server/test_server_lifecycle.py::test_real_server_process_cleans_up_its_temp_directory_on_sigterm`,
a real-subprocess SIGTERM-timing test that is flaky under concurrent system load (this session ran
many parallel pytest/pandapipes invocations); confirmed to pass in isolation both in this run and
every prior phase's run. The starting baseline (Phase 0) was 838 passing tests; the collected count
has only ever increased across every phase, per NFR-007/19.3's own requirement — no test was ever
weakened or removed to make the suite pass. The suite requires no network access and no real
Wuppertal data at any point.

## Second-session update (2026-09-03, `feature/complete-synthetic-prototype`)

A later session, working from `R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md`'s own Phase 0-9
numbering (an independent, more skeptical audit that explicitly re-verified every prior claim in
this document against the actual code before accepting it), resolved five of the seven "Remaining
work" items the first session left open — see the row-level updates above (each carrying its own
resolution date/commit) and the commit list in this document's own header. In order of the original
list below: item 2 (README) — resolved. Item 3 (CFG-001) — resolved; CFG-002 remains an explicit,
now more narrowly documented deferral. Item 4 (OPT-006) — the gate now exists
(`enforce_real_data_readiness()`) but remains unwired into `joint_optimization.py` specifically,
since no real-data entry point exists anywhere to wire it into. Item 5 (NFR-006) — narrowed, not
fully closed (`candidates.generated.max_candidates` added). Item 6 (doublet-component retargeting)
— resolved. Items 1 (Phase 8) and 7 (AC-11) remain exactly as before: correctly not attempted, and
correctly deferred to a genuine, human-performed Claude Desktop session respectively. Two genuinely
NEW capabilities this second session added were not contemplated by the first session's own
requirement list at all and so have no ID above: candidate-generation wired into `run_workflow()`
(CAN-001's own row, updated) and the full-product joint-optimization workflow entry point (OPT-005's
own row, updated) — both fully tested and documented in their own `docs/issues/*.md` files.

Full offline suite as of this second session's own final commit (`042feba`): **1060 collected, 1060
passed, 0 failed** — a fully clean run, re-verified after every commit in this session (`1565eb4`,
`a481dc1`, `1c45971`, `d2b4994`, `042feba`, plus the six hardening commits preceding them). One
scientific-hash rebaseline occurred and was handled per GOV-004 (`df91ce9`, a cross-platform
floating-point-noise fix, diagnosed via `git stash`-isolated causal identification before
rebaselining, documented in `decision-register.md` IMPL-015); a second, smaller rebaseline occurred
during the generated-candidates work when a presentation-text honesty fix
(`economics/ranking.py::SHARED_CAPEX_STATEMENT`, no longer hardcoding "C1-C4" for a run whose
candidates are not C1-C4) incidentally changed `bundle_scientific_sha256` for the canonical run too,
since that text is part of every bundle — also diagnosed via `git stash` isolation before
rebaselining (IMPL-017). Neither rebaseline changed the canonical `run_id` or any KPI/ranking value.

## Remaining work (honestly scoped, not hidden)

1. **Phase 8 (real Wuppertal application)** — correctly not started. Requires the Appendix B data
   request to be fulfilled and domain-owner approvals (Tanja, Dr. Jan) before any of Phase 8's own
   activities may begin.
2. ~~**README.md**~~ — resolved, second session (above).
3. ~~**CFG-001**~~ — resolved, second session (above). **CFG-002** remains open: a
   `resolved_config_sha256` was deliberately not added, to avoid a fourth same-session hash
   rebaseline for a purely additive audit field — see CFG-002's own row.
4. **OPT-006** — `enforce_real_data_readiness()` (the gate itself) now exists and is tested, but
   remains unwired into `joint_optimization.py` specifically; no real-data entry point exists
   anywhere in this repository today for it to gate.
5. **NFR-006** — narrowed (`candidates.generated.max_candidates` added, second session) but not
   fully closed: no general "maximum scenario combinations/concurrent workflows" bound exists
   beyond that and the registry's pre-existing `max_size`.
6. ~~**`evaluate_candidate()` → doublet-component retargeting**~~ — resolved, second session
   (above, `1565eb4`).
7. **AC-11** — the literal live-Claude-Desktop session step was not re-executed in either session;
   its automatable components are covered elsewhere in this matrix. This remains the one item this
   document cannot resolve on its own — it requires a genuine, human-performed Claude Desktop
   replay, prepared for but not substitutable by any amount of further automated work.

None of the above affects the canonical C1-C4 golden result, `run_id`, or any previously-approved
scientific/economic value — every item is either a genuinely new-workstream refinement opportunity
or a documentation/wiring completeness gap, not a defect in what has been built and tested.
