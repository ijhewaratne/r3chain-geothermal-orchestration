# R3-CHAIN Final Research-Alignment Implementation Specification

## Complete implementation contract for Claude Code

## 1R3-CHAIN Final Research-Alignment Implementation Specification

Complete implementation contract for Claude CodeTarget repository: ijhewaratne/r3chain-geothermal-orchestrationTarget baseline: latest remote feature/complete-synthetic-prototypePrepared: 2026-09-05Status: normative implementation specification

### 1.10. Purpose and executive decision

The repository already contains a mature corrected synthetic joint site–connection workflow. This specification does not authorize another architecture redesign. Its purpose is to align the existing v2 software with the final six-week research methodology.

The implementation objective is:

Build a reproducible research experiment around the existing v2 workflow in which (1) geothermal-only, (2) network-only, and (3) integrated site–connection assessments are compared under the same declared assumptions; the integrated alternatives are evaluated across a small set of representative steady-state load conditions; technically infeasible alternatives are excluded before economics; feasible alternatives are ranked primarily by annualized system LCOH with materiality-aware ties; the existing Pareto analysis remains available as a secondary diagnostic; and a controlled sensitivity study reports whether the preferred configuration is stable over the tested assumption range.

The scientific question is:

Does the geothermal resource/site preferred by source-side analysis remain preferred once its actual district-heating integration is considered?

The implementation shall preserve the existing canonical C1–C4 workflow and the corrected v2 synthetic joint workflow. The new research-alignment layer shall sit above those workflows and reuse them rather than duplicating their physics.

### 1.21. Authority hierarchy

After this specification is added to the repository, ambiguity shall be resolved in this order:

docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md — authoritative for the final six-week research experiment and its completion criteria.

Executable code and tests — authoritative evidence of implemented behavior.

docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md — authoritative for the v2 joint site–connection architecture and contracts.

Current ADR/scope decisions — explain approved scope history and limitations.

README, acceptance criteria, traceability matrix and CLAUDE.md — user-facing current status.

Original six-week implementation plan — historical record only.

This specification supersedes only the research-completion/experimental-alignment layer. It does not invalidate the v2 architecture specification.

### 1.32. Repository facts that must be preserved

The implementation shall begin with a read-only audit and verify these facts against the current remote branch rather than assuming them.

At the inspected repository state:

feature/complete-synthetic-prototype contains the corrected v2 methodology.

workflow/joint_workflow_v2.py is the corrected joint site–connection workflow.

v2 represents explicit coordinate-bearing surface sites, site-linked geothermal scenarios, site-specific routes, compatible alternative enumeration, executable connection-pipe diameter, technical gates, economics, Pareto decision logic, deterministic artifacts, CLI/MCP dispatch and persistent-registry rehydration.

decision/joint_policy.py already supports both pareto_only and primary_objective_ranking, including materiality-aware rank groups and a preferred alternative only when rank 1 is unique.

the committed synthetic v2 study package currently uses mode: pareto_only, primary_objective: null, annual_operating_hours: 8000.0, 4% discount rate, 25-year analysis period, EUR 180/MWh electricity, EUR 90/MWh auxiliary heat, and synthetic cost provenance.

the existing v2 workflow and existing v2 study package are historical/scientific baselines and must not be silently mutated to create the new research experiment.

all real-location conclusions remain blocked because the current v2 study is synthetic.

The implementation must preserve the canonical fixed-source C1–C4 baseline and must not reinterpret it as a drilling-site result.

### 1.43. Final six-week research scope

#### 1.4.13.1 Included

The final synthetic research prototype shall contain:

a fixed four-consumer district-heating supply/return network;

explicit geothermal surface sites and site-linked resource scenarios;

explicit network attachments and site-specific connection routes;

PyDoublet-result validation and the existing heat-exchanger boundary;

pandapipes steady-state thermo-hydraulic evaluation;

ordered geothermal/HX/network feasibility gates before economics;

exhaustive evaluation of every compatible synthetic alternative;

three representative steady-state load conditions for annualization;

system-level annualized CAPEX/OPEX and useful-heat LCOH;

a primary materiality-aware LCOH ranking;

the existing Pareto shortlist as a secondary diagnostic;

a geothermal-only baseline;

a network-only baseline;

an integrated baseline;

explicit comparison of those three results;

a small, controlled ranking-robustness/sensitivity study;

deterministic CLI/Python/MCP orchestration;

complete provenance and hash-audited artifacts;

explicit synthetic/indicative caveats.

#### 1.4.23.2 Excluded from the six-week acceptance criteria

Do not implement these merely to make the prototype appear more sophisticated:

real Wuppertal drilling recommendations;

fabricated geology or land availability;

reservoir transient simulation;

full bidirectional annual PyDoublet–pandapipes co-simulation;

Drews-style Monte Carlo exploration-risk portfolios;

risk-adjusted LCOH unless approved probabilistic inputs are supplied;

simultaneous district-heating network topology redesign;

automatic pipe-diameter optimization across the complete network;

producer/injector underground trajectory optimization;

steam-network conversion;

multiple-doublet portfolio optimization;

opaque MILP/GA/LLM optimization;

LLM-generated feasibility decisions, costs or rankings;

a seventh MCP tool or a separate PyDoublet MCP server.

### 1.54. Correct decision entity and active dimensions

Retain the v2 definition:

x = (s, g, a, r, d, o)

where:

s = surface geothermal site / energy-centre location;

g = geothermal resource scenario linked to s;

a = district-heating network attachment;

r = site-specific route from s to a;

d = connection design option;

o = operating policy.

Only compatible alternatives may be evaluated:

g.site == s, r.site == s, r.attachment == a, with design and operating-policy compatibility satisfied.

Do not collapse geothermal site and network attachment into one “location”. Do not describe controlled one-value dimensions as optimized axes.

### 1.65. New implementation layer: research experiment workflow

#### 1.6.15.1 Architectural rule

Do not modify run_joint_workflow_v2() into a monolithic research function.

Add a higher-level deterministic experiment workflow that calls/reuses existing scientific components.

Preferred boundary:

data_contracts/research_experiment.py — research experiment contracts;

workflow/research_experiment.py — experiment orchestration;

workflow/research_baselines.py — geothermal-only and network-only baselines;

workflow/load_state_evaluation.py — per-load-state evaluation/aggregation;

economics/annualized_system_costing.py — annual aggregation without duplicating canonical cost formulas;

decision/research_comparison.py — baseline comparison and robustness classification;

workflow/research_experiment_export.py — artifacts;

Exact filenames may follow repository conventions, but responsibilities must remain separated and independently testable.

#### 1.6.25.2 Public entry point

Add one authoritative Python entry point, e.g.:

run_research_experiment(...) -> ResearchExperimentResult | ResearchExperimentFailure

The CLI and geo_run_workflow shall dispatch to this same entry point.

No physics or ranking logic may be implemented in CLI/MCP wrappers.

### 1.76. ResearchExperimentPackage contract

Add a versioned typed package. Suggested schema:

```

experiment_schema_version: "1.0.0"experiment_id: stringclassification: syntheticbase_joint_study_package_path: stringbase_joint_study_package_sha256: stringload_states: list[LoadState]baselines: BaselineExperimentPolicyannualization: AnnualizationPolicyprimary_decision: ResearchDecisionPolicysensitivity: SensitivityPolicyprovenance: ExperimentProvenance

```

#### 1.7.16.1 LoadState

```

load_state_id: stringhours_per_year: floatconsumer_demand_multiplier: floatrequired_for_feasibility: boolassumption_status: synthetic_assumption | approved_sourcesource_reference: string

```

Validation:

IDs unique;

hours_per_year > 0;

consumer_demand_multiplier > 0;

sum of all hours_per_year must equal the annualization horizon declared by policy;

no hidden default demand multipliers;

values must be config-backed and provenance-labelled.

The implementation shall support three representative states for the final experiment, but the contract may allow N >= 1.

The scientific publication/demo values are assumptions, not code constants. If Tanja/Jan have not approved exact values, commit a clearly labelled synthetic demonstration fixture and keep real-study values gated.

#### 1.7.26.2 BaselineExperimentPolicy

```

network_only:  enabled: true  reference_site_id: string  reference_resource_scenario_id: string  eligible_attachment_ids: list[string] | nullgeothermal_only:  enabled: true  resource_scenario_ids: list[string] | null  metric: indicative_geothermal_lcoh_at_hxintegrated:  enabled: true

```

#### 1.7.36.3 AnnualizationPolicy

```

horizon_hours_per_year: 8760.0useful_heat_boundary: consumer_deliveryinclude_dh_pumping_electricity_in_opex: trueinclude_geothermal_pumping_electricity_in_opex: trueinclude_auxiliary_heat_in_opex: truecapex_annualized_once: true

```

Do not subtract pumping electricity from the thermal-energy denominator.

#### 1.7.46.4 ResearchDecisionPolicy

Primary research decision:

```

mode: primary_objective_rankingprimary_objective: annualized_system_lcoh_eur_per_mwhallow_shared_rank: truetie_breakers: []

```

The Pareto shortlist shall still be calculated and published as a secondary diagnostic.

Do not add weights.

#### 1.7.56.5 SensitivityPolicy

Minimum accepted policy shall support:

connection-cost sensitivity, e.g. multiplicative factors around the base capex_eur_per_paired_trench_m;

geothermal deliverable-heat derating sensitivity, implemented as a clearly labelled post-validation availability/derating factor at the geothermal-to-HX availability boundary, not as a fabricated new PyDoublet result.

Suggested contract:

```

cases:  - sensitivity_case_id: base    connection_capex_multiplier: 1.0    geothermal_deliverable_heat_derating_fraction: 0.0  - sensitivity_case_id: connection_low    connection_capex_multiplier: 0.8    geothermal_deliverable_heat_derating_fraction: 0.0  - sensitivity_case_id: connection_high    connection_capex_multiplier: 1.2    geothermal_deliverable_heat_derating_fraction: 0.0  - sensitivity_case_id: geo_derate_10    connection_capex_multiplier: 1.0    geothermal_deliverable_heat_derating_fraction: 0.10

```

These are synthetic sensitivity cases. They are not probabilities and must never be described as exploration risk.

If different numeric factors are approved, use the approved values; do not bury them in code.

### 1.87. Three representative load-state evaluation

#### 1.8.17.1 Scientific intent

The current single steady-state result multiplied by one annual operating-hour value is acceptable for an indicative prototype but insufficient for the final research experiment.

The research layer shall evaluate each integrated alternative under multiple representative steady states while keeping PyDoublet at Jan’s current steady/lifetime-average boundary.

This is not transient simulation.

#### 1.8.27.2 Demand transformation

For each LoadState:

start from the same fixed network topology;

scale each consumer heat demand by consumer_demand_multiplier;

keep topology, geometry and base pipe data fixed;

preserve the alternative’s site, route, design and operating policy;

use the same validated geothermal resource scenario, subject only to an explicitly configured sensitivity derating when running sensitivity cases;

evaluate through the existing HX/network pipeline.

Do not mutate shared network objects across alternatives or states. Build fresh deterministic network evaluation state as the existing v2 workflow does.

#### 1.8.37.3 Curtailment and shortfall

Before implementation, audit how the current evaluator behaves when geothermal available heat exceeds reduced network demand.

Required behavior:

geothermal supply may be curtailed to the useful demand/operating-policy requirement;

excess source availability must not be forced into the network merely because the PyDoublet result is fixed;

if the configured operating policy permits auxiliary heat, capacity shortfall may be met by auxiliary heat and recorded explicitly;

an HX temperature infeasibility is not silently repaired by auxiliary heat unless the operating policy explicitly models such temperature boosting;

no negative shortfall, negative auxiliary heat or over-delivery may be hidden by clipping without an audit record.

If the current code cannot represent curtailment cleanly, add one explicit deterministic dispatch helper and tests. Do not introduce an optimizer.

#### 1.8.47.4 Feasibility across load states

An integrated alternative is research-feasible only if every load state marked required_for_feasibility=true:

parses and couples successfully;

converges in pandapipes;

satisfies all configured hard technical constraints.

If one required state fails, the annual alternative is infeasible and excluded from the primary LCOH ranking.

Store exact state-level failure codes.

### 1.98. Annualized useful heat and cost

#### 1.9.18.1 Useful heat denominator

Use thermal heat delivered to consumers:

E_useful = Σ_r(Q_delivered,r × h_r)

where r is load state and h_r is state hours/year.

Do not use raw reservoir heat, raw PyDoublet thermal power or heat before network losses as the system-LCOH denominator.

Do not subtract electrical pumping energy from E_useful.

#### 1.9.28.2 Pumping and auxiliary-energy OPEX

Aggregate electricity/auxiliary terms by state:

DH pumping: Σ_r(P_DH_pump,r × h_r);

geothermal/doublet pumping: use the physically appropriate existing scenario pump-power quantity and dispatched operating hours; do not multiply the same annual energy three times;

auxiliary heat: Σ_r(Q_aux,r × h_r).

Apply configured energy prices once.

#### 1.9.38.3 CAPEX

Annualize CAPEX once per alternative using the existing annuity logic:

declared geothermal/doublet CAPEX;

HX/plant CAPEX where already part of the declared boundary;

site-to-network route/connection CAPEX;

explicitly declared network modification CAPEX.

Do not annualize CAPEX separately for each load state.

#### 1.9.48.4 Final annualized system LCOH

annualized_system_lcoh_eur_per_mwh = annualized_total_system_cost_eur_per_a / annual_useful_heat_mwh_per_a

The result remains indicative/synthetic because the cost assumptions and geothermal scenarios are synthetic.

#### 1.9.58.5 Cost breakdown

Every feasible annualized alternative shall expose at least:

annualized geothermal CAPEX component;

annualized connection CAPEX component;

other annualized CAPEX component if present;

geothermal pumping electricity MWh/a and EUR/a;

DH pumping electricity MWh/a and EUR/a;

auxiliary heat MWh/a and EUR/a;

fixed O&M EUR/a if present;

annual useful heat MWh/a;

annual geothermal heat delivered MWh/a;

geothermal coverage fraction;

annualized system LCOH EUR/MWh.

### 1.109. Primary LCOH ranking and secondary Pareto analysis

#### 1.10.19.1 Reuse existing decision engine

decision/joint_policy.py already supports primary_objective_ranking. Reuse it; do not create a second ranking implementation unless the annualized field requires a small extractor extension.

#### 1.10.29.2 Ranking semantics

For feasible integrated alternatives:

primary objective = minimize annualized_system_lcoh_eur_per_mwh;

materiality thresholds must be declared in config;

alternatives within materiality remain in the same rank group;

no hidden tie-breaker;

alternative_id may order display only, never science;

preferred_alternative_id exists only when rank 1 contains exactly one alternative.

#### 1.10.39.3 Pareto diagnostic

Retain the independent Pareto objectives, preferably:

minimize annualized system LCOH;

maximize geothermal coverage fraction;

minimize annual total pumping electricity.

The report shall distinguish:

primary research ranking from LCOH;

secondary Pareto shortlist from multi-objective diagnostics.

Do not describe the Pareto set itself as a total ranking.

### 1.1110. Geothermal-only baseline

#### 1.11.110.1 Purpose

Answer:

Which declared geothermal resource scenario looks best before district-heating routing and network thermo-hydraulics are considered?

#### 1.11.210.2 Unit of comparison

Rank resource scenarios, each carrying its linked site. Do not silently collapse multiple scenarios at one site into one best-site value.

#### 1.11.310.3 Metric

Add a clearly named source-side metric:

indicative_geothermal_lcoh_at_hx_eur_per_mwh

Boundary:

geothermal/doublet CAPEX and declared source-side plant/HX costs already present in scenario economics;

geothermal pumping OPEX;

no site-to-DH connection CAPEX;

no DH-network pumping;

no DH-network heat loss;

no network-modification CAPEX.

Energy denominator:

deliverable geothermal heat at the HX boundary under the declared steady/lifetime-average assumption and declared annual operating basis;

if an annual load-state policy is used, source-side useful heat may be capped by the reference heat-demand envelope, but this rule must be explicit and identical for all scenarios.

Publish component values so the baseline is auditable.

#### 1.11.410.4 Ties

Use materiality-aware ranking. If source-side economics are equal within materiality, report a tie.

### 1.1211. Network-only baseline

#### 1.12.111.1 Purpose

Answer:

For one fixed geothermal source at one fixed reference surface site, which eligible DH attachment/route performs best?

This isolates network integration effects.

#### 1.12.211.2 Fixed source

The policy must name one existing validated synthetic resource scenario and its site. Its geothermal physical/economic inputs remain identical for every network-only alternative.

#### 1.12.311.3 Varying dimensions

Vary only:

eligible network attachment;

site-specific route to that attachment;

approved connection design if more than one is explicitly included.

Keep geothermal scenario and site fixed.

#### 1.12.411.4 Metric

Use the same annualized system-cost boundary as the integrated analysis. Since geothermal cost is constant, ranking differences arise from route, network thermo-hydraulics, losses, pumping and auxiliary behavior.

Publish both absolute LCOH and network-incremental cost terms so the isolation is visible.

### 1.1312. Integrated baseline

Run the complete compatible v2 search space under the annualized load-state methodology.

The integrated result shall include:

every compatible alternative;

state-by-state technical outcomes;

exact rejection codes;

annualized feasible-alternative economics;

materiality-aware LCOH rank groups;

Pareto shortlist;

preferred alternative only if unique.

No pre-filtering based on observed economics is allowed.

### 1.1413. Cross-baseline research comparison

Add a deterministic comparison result that directly answers the research question.

Suggested fields:

```

geothermal_only_rank_groups: ...network_only_rank_groups: ...integrated_rank_groups: ...geothermal_only_best_scenario_ids: ...network_only_best_attachment_ids: ...integrated_best_alternative_ids: ...integrated_best_site_ids: ...integrated_best_attachment_ids: ...site_decision_changed_after_integration: true|false|nullattachment_decision_changed_after_integration: true|false|nullcomparison_interpretation_code: string

```

Semantics:

compare sets, not arbitrary first elements of tied groups;

site_decision_changed_after_integration=true only when the integrated rank-1 site set is disjoint from the geothermal-only rank-1 site set;

false when there is overlap and no stronger conclusion is justified;

use null/typed indeterminate code when either baseline has no feasible/rankable result;

similar rules for network attachments.

Mandatory interpretation codes should include at least:

INTEGRATED_MATCHES_BOTH_BASELINES;

INTEGRATED_SITE_DIFFERS_FROM_GEO_ONLY;

INTEGRATED_ATTACHMENT_DIFFERS_FROM_NETWORK_ONLY;

INTEGRATED_DIFFERS_FROM_BOTH;

MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON;

NO_FEASIBLE_INTEGRATED_ALTERNATIVE;

BASELINE_NOT_RANKABLE.

Do not force a “coupling changes the answer” conclusion. Matching rankings are scientifically valid.

### 1.1514. Sensitivity and robustness analysis

#### 1.15.114.1 Required cases

Run the integrated experiment for the configured sensitivity cases.

Minimum categories:

connection-cost perturbation;

geothermal deliverable-heat downside/derating perturbation.

#### 1.15.214.2 No probabilistic claims

Sensitivity cases are deterministic what-if scenarios. They are not P10/P50/P90, not probability of success and not exploration risk.

#### 1.15.314.3 Robustness classification

Publish:

base rank-1 group;

rank-1 group for every sensitivity case;

whether base rank-1 set remains unchanged;

whether any candidate becomes infeasible;

maximum observed rank change for each base candidate;

winning-site/attachment changes.

Use one of these classifications:

ROBUST_OVER_TESTED_RANGE — same unique rank-1 alternative in all mandatory cases;

ROBUST_SITE_BUT_CONNECTION_SENSITIVE;

ROBUST_CONNECTION_BUT_SITE_SENSITIVE;

ASSUMPTION_SENSITIVE;

NO_UNIQUE_BASE_WINNER;

INSUFFICIENT_FEASIBLE_CASES.

Never shorten ROBUST_OVER_TESTED_RANGE to “robust” without the tested-range qualifier.

### 1.1615. Failure ordering and gates

Retain the existing principle: physics before economics.

For each alternative/load state, use an ordered pipeline:

input/provenance validation;

site/scenario/route/design compatibility;

geothermal/HX coupling;

pandapipes build and convergence;

hydraulic/thermal technical limits;

annual aggregation eligibility;

economics;

decision policy.

Infeasible alternatives must have blank/null economic decision fields where economics are not meaningful.

No failure may be converted to a poor score.

### 1.1716. MCP and CLI behavior

#### 1.17.116.1 One server, same six tools

Do not add a seventh public MCP tool.

Extend the existing geo_run_workflow discriminated input with one research mode, e.g.:

```

{  "workflow_mode": "research_experiment",  "experiment_package_path": "config/research_experiment_synthetic.json"}

```

The exact field names may follow current conventions.

#### 1.17.216.2 Equality across interfaces

For identical normalized inputs:

Python API;

CLI;

MCP

must produce the same scientific result ID/hash and the same normalized artifacts.

#### 1.17.316.3 LLM boundary

Claude may:

select the requested workflow mode;

call the deterministic tools;

retrieve artifacts;

summarize already-computed results.

Claude must not:

invent missing inputs;

modify thresholds after seeing results;

calculate hydraulic/thermal results itself;

fabricate LCOH;

decide feasibility;

override rank groups;

claim real drilling recommendations.

### 1.1817. Required artifact bundle

A successful research experiment shall publish at least:

experiment_input.json — normalized experiment package;

joint_study_snapshot.json — exact referenced v2 study package;

load_states.json;

load_state_results.json — one result per integrated alternative × load state;

annualized_alternative_comparison.csv;

annualized_integrated_result.json;

geothermal_only_result.json;

geothermal_only_comparison.csv;

network_only_result.json;

network_only_comparison.csv;

research_comparison.json;

research_comparison.csv;

sensitivity_results.json;

sensitivity_comparison.csv;

objective_policy.json;

pareto_or_ranking.json;

research_findings.md;

audit.json;

manifest.json.

The existing v2 route/site artifacts may be copied or referenced by hash rather than redundantly recomputed if the scientific identity is unchanged.

#### 1.18.117.1 research_findings.md

Must state, deterministically:

this is a synthetic methodology demonstration;

the best geothermal-only scenario/rank group;

the best network-only attachment/rank group;

the integrated rank-1 group;

whether integration changed the site and/or attachment conclusion;

Pareto shortlist;

robustness classification;

exact caveats: synthetic geology/costs, steady-state PyDoublet boundary, representative load states, no exploration risk, no real Wuppertal recommendation.

Do not write a natural-language claim that is not derivable from fields in research_comparison.json and sensitivity_results.json.

### 1.1918. Scientific identity and reproducibility

#### 1.19.118.1 Run identity

Scientific identity shall include:

experiment package normalized content;

referenced joint study package hash;

load states;

baseline policy;

annualization policy;

decision policy;

sensitivity cases;

relevant code/schema version.

Wall-clock timestamps must not affect scientific hashes.

#### 1.19.218.2 Determinism

Two independent runs with identical scientific inputs must produce:

identical scientific run ID;

identical normalized scientific bundle hash;

identical CSV row ordering;

identical rank groups;

identical interpretation and robustness codes.

Byte hashes may differ only for files explicitly containing real invocation timestamps, following existing repository conventions.

### 1.2019. Data/provenance rules

Every non-derived numeric assumption must be classified as:

approved_source, or

synthetic_assumption.

Every sensitivity perturbation must record:

base field/path;

base value;

multiplier/derating;

resulting value;

reason;

source/approval reference.

Do not replace missing site-specific PyDoublet data with guessed geology.

The current synthetic scenarios remain a methodology demonstration only.

### 1.2120. Testing specification

#### 1.21.120.1 Regression tests — must remain green

Preserve and execute all existing tests, including:

canonical C1–C4 run ID/KPIs/ranking;

v2 site/scenario/route compatibility;

route geometry and cost;

connection-DN execution;

HX and pandapipes failure codes;

Pareto materiality behavior;

CLI/MCP/persistence;

scientific hashing;

wheel install and CI platform tests.

Existing canonical and existing v2 fixtures must remain scientifically unchanged unless a separately approved migration is required.

#### 1.21.220.2 New contract tests

Add tests for:

unique load-state IDs;

positive demand multipliers;

valid hour sum;

classification/provenance;

baseline reference IDs exist in joint study package;

sensitivity factors valid and finite;

no real-mode use without readiness.

#### 1.21.320.3 Load-state tests

Add tests that prove:

demand scaling affects only intended consumer loads;

topology and route identity stay fixed;

fresh network state per run;

curtailment does not over-inject heat;

auxiliary heat is never negative;

required-state failure makes annual alternative infeasible;

optional-state failure behavior is explicit if optional states are supported.

#### 1.21.420.4 Annualization tests

Prove numerically:

E_useful = Σ Q_delivered × hours;

pumping electricity = Σ P_pump × hours;

auxiliary energy = Σ Q_aux × hours;

CAPEX annualized exactly once;

pumping electricity is a cost-numerator term, never subtracted from useful thermal heat;

zero useful heat cannot produce finite LCOH;

cost components sum exactly to total annual cost within declared tolerance.

#### 1.21.520.5 Decision tests

Prove:

primary-objective ranking uses annualized system LCOH;

materiality creates shared rank groups;

no ID-based scientific tie-break;

preferred ID only for a unique first rank;

Pareto shortlist still computed independently;

infeasible alternatives never enter ranking.

#### 1.21.620.6 Baseline-isolation tests

Geothermal-only:

network route/pressure/velocity changes cannot affect geothermal-only rank;

source-side metric excludes connection and DH-network cost terms.

Network-only:

source scenario/site are identical across all candidates;

changing geothermal CAPEX by the same constant for all network-only candidates does not change their order;

attachment/route/network differences can change the order.

Integrated:

all compatible alternatives evaluated;

no economics-based pre-curation.

#### 1.21.720.7 Cross-baseline comparison tests

Test every interpretation code, including ties and no-feasible cases.

#### 1.21.820.8 Sensitivity tests

Prove:

perturbations do not mutate base fixture objects;

base case exactly reproduces base research run;

each case has a distinct scientific identity;

robustness classification follows set-based rank-1 comparison;

no probabilistic wording is emitted.

#### 1.21.920.9 Interface parity tests

Python, CLI and MCP must produce the same scientific result contract and bundle hash.

#### 1.21.1020.10 Reproducibility tests

Two independent research runs must match scientifically on Linux and macOS under supported Python versions.

### 1.2221. Documentation updates

After code and tests pass:

Add this specification to docs/specifications/.

Add a new scope ADR amendment (e.g. D11) stating that v2 is retained and a research-experiment layer now adds annualized load-state evaluation, three baselines, primary LCOH ranking and sensitivity analysis.

Update CLAUDE.md authority hierarchy so this specification is above the corrected v2 architecture spec for final research-completion questions.

Update README with a concise “Final six-week research experiment” section.

Correct any stale README CI text only after verifying current real CI status.

Extend the traceability matrix; do not rewrite or erase historical rows.

Update acceptance criteria with the new requirement IDs below.

Clearly label old joint v1 as legacy/superseded and v2 as the physical joint baseline.

Keep all real-study limitations visible.

Do not rewrite historical evidence bundles.

### 1.2322. Required new requirement IDs

#### 1.23.1Governance

RA-GOV-001 — work from latest remote v2 baseline; record branch/commit/tree state.

RA-GOV-002 — do not alter canonical C1–C4 scientific result.

RA-GOV-003 — do not alter existing v2 scientific baseline merely to create research experiment.

RA-GOV-004 — no commits/pushes without explicit authorization.

RA-GOV-005 — no real-location claim.

#### 1.23.2Contracts

RA-DATA-001 — versioned ResearchExperimentPackage.

RA-DATA-002 — typed load states and annual horizon validation.

RA-DATA-003 — typed baseline policy.

RA-DATA-004 — typed sensitivity cases and provenance.

RA-DATA-005 — config-backed materiality and ranking policy.

#### 1.23.3Load-state evaluation

RA-LOAD-001 — N representative steady-state evaluations per integrated alternative.

RA-LOAD-002 — fresh network state per alternative/state.

RA-LOAD-003 — demand scaling only through declared multipliers.

RA-LOAD-004 — explicit curtailment/shortfall behavior.

RA-LOAD-005 — required-state feasibility aggregation.

#### 1.23.4Economics

RA-ECON-001 — consumer-delivered useful-heat denominator.

RA-ECON-002 — state-weighted pumping and auxiliary OPEX.

RA-ECON-003 — CAPEX annualized once.

RA-ECON-004 — annualized system LCOH.

RA-ECON-005 — auditable cost breakdown.

RA-ECON-006 — no subtraction of pumping electricity from thermal heat.

#### 1.23.5Decision

RA-DEC-001 — primary ranking = annualized system LCOH.

RA-DEC-002 — materiality-aware shared ranks.

RA-DEC-003 — Pareto remains secondary.

RA-DEC-004 — unique preferred alternative only when rank 1 unique.

#### 1.23.6Baselines

RA-BASE-001 — geothermal-only source-side ranking.

RA-BASE-002 — fixed-source network-only ranking.

RA-BASE-003 — integrated ranking.

RA-BASE-004 — set-based cross-baseline comparison.

RA-BASE-005 — deterministic interpretation code.

#### 1.23.7Sensitivity

RA-SENS-001 — connection-cost sensitivity.

RA-SENS-002 — geothermal deliverable-heat derating sensitivity.

RA-SENS-003 — tested-range robustness classification.

RA-SENS-004 — no probability/exploration-risk claim.

#### 1.23.8Interfaces/artifacts

RA-API-001 — one Python entry point.

RA-API-002 — CLI dispatch.

RA-API-003 — existing six-tool MCP dispatch.

RA-ART-001 — complete research artifact bundle.

RA-ART-002 — deterministic findings report.

RA-ART-003 — manifest/scientific hash.

#### 1.23.9Verification

RA-TEST-001 — all existing tests green.

RA-TEST-002 — new contract/load/economics/decision/baseline/sensitivity tests green.

RA-TEST-003 — two-run scientific reproducibility.

RA-TEST-004 — CLI/MCP/API parity.

RA-TEST-005 — supported CI matrix green.

### 1.2423. Acceptance criteria

The implementation is accepted only when all of the following are true.

#### 1.24.1AC-RA01 — Historical baseline preserved

Canonical C1–C4 output remains unchanged and its existing regression evidence passes.

#### 1.24.2AC-RA02 — Existing v2 preserved

The committed v2 synthetic joint study still runs and retains its scientific result identity unless an explicitly approved, causally explained schema migration is necessary.

#### 1.24.3AC-RA03 — Research package runs in one command

A committed synthetic research experiment package can be executed from the installed CLI with one command.

#### 1.24.4AC-RA04 — Three load states actually execute

The final research fixture evaluates three declared steady-state load conditions per integrated alternative, not merely three labels around one result.

#### 1.24.5AC-RA05 — Annualization is correct

Useful heat, pumping energy, auxiliary energy and annual cost equal independently recomputed reference values for test fixtures.

#### 1.24.6AC-RA06 — Physics gates precede economics

An alternative failing a required load state never receives a decision rank and carries exact failure evidence.

#### 1.24.7AC-RA07 — Primary LCOH ranking exists

Feasible integrated alternatives have materiality-aware rank groups based on annualized system LCOH.

#### 1.24.8AC-RA08 — Pareto remains available

The same run publishes the secondary materiality-aware Pareto shortlist.

#### 1.24.9AC-RA09 — Three research baselines exist

Geothermal-only, network-only and integrated results are all produced from one research run.

#### 1.24.10AC-RA10 — Research question is answered mechanically

The result/artifacts state whether the integrated rank-1 site/attachment set matches or differs from each baseline using deterministic interpretation codes.

#### 1.24.11AC-RA11 — Sensitivity exists

At least one connection-cost and one geothermal-deliverable-heat downside case are executed and compared with base.

#### 1.24.12AC-RA12 — Robustness wording is bounded

The report uses “robust over tested range” only when the configured cases support it.

#### 1.24.13AC-RA13 — Synthetic caveats are unavoidable

Every user-facing research artifact states that the result is synthetic/indicative and not a real Wuppertal drilling recommendation.

#### 1.24.14AC-RA14 — API parity

Python, CLI and MCP give the same scientific result/hash for the same package.

#### 1.24.15AC-RA15 — Reproducible bundle

Two independent runs produce the same normalized scientific bundle hash.

#### 1.24.16AC-RA16 — Full test and CI gates

Offline suite, wheel-install smoke test and required GitHub Actions matrix are green.

#### 1.24.17AC-RA17 — Documentation reconciled

README, CLAUDE.md, current ADR, acceptance criteria and traceability matrix describe the same implemented status.

### 1.2524. Implementation phases and exit gates

#### 1.25.1Phase 0 — Read-only audit

Claude must first report, before editing:

remote branch and exact HEAD;

clean/dirty status;

diff since the commit cited in prior specifications;

relevant modules/contracts/tests;

existing v2 run and test status;

proposed files to modify/add;

any contradiction between this spec and current code.

Exit gate: user authorizes implementation after audit.

#### 1.25.2Phase 1 — Preserve specification and governance

add this spec;

add new ADR amendment placeholder/decision entry;

do not yet claim implementation complete.

Exit gate: no scientific code changes; existing suite unchanged.

#### 1.25.3Phase 2 — Research contracts

Implement ResearchExperimentPackage, load states, baseline policy, annualization policy and sensitivity policy.

Exit gate: contract tests green; invalid packages fail with typed errors.

#### 1.25.4Phase 3 — Multi-load-state evaluation

Implement deterministic demand scaling, per-state evaluation, curtailment/shortfall audit and annual feasibility aggregation.

Exit gate: state-level tests and deliberate failure cases green.

#### 1.25.5Phase 4 — Annualized economics

Implement state-weighted useful heat and variable OPEX while reusing existing annuity/cost formulas. Ensure CAPEX counted once.

Exit gate: independent numeric reference tests green.

#### 1.25.6Phase 5 — Primary research decision

Wire annualized LCOH into existing primary-objective ranking while retaining Pareto.

Exit gate: materiality/tie/preferred-ID tests green.

#### 1.25.7Phase 6 — Three baselines and research comparison

Implement geothermal-only, network-only, integrated results and deterministic comparison codes.

Exit gate: isolation and comparison tests green.

#### 1.25.8Phase 7 — Sensitivity and robustness

Implement configured cases, immutable base inputs and bounded robustness classification.

Exit gate: sensitivity tests and findings fields green.

#### 1.25.9Phase 8 — CLI/MCP/artifacts

Add workflow dispatch without new MCP tools; publish required artifact bundle and manifests.

Exit gate: API/CLI/MCP parity and two-run hash reproducibility green.

#### 1.25.10Phase 9 — Documentation reconciliation and release verification

update README/CLAUDE/ADR/acceptance/traceability;

run complete offline test suite;

build/install wheel smoke test;

run real CI matrix;

verify artifacts from a clean install.

Exit gate: AC-RA01 through AC-RA17 all PASS; no hidden PARTIAL collapsed into PASS.

### 1.2625. Files expected to change or be added

Claude must audit current names first, but the expected surface is:

#### 1.26.1New

docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md

src/r3chain_geothermal/data_contracts/research_experiment.py

src/r3chain_geothermal/workflow/research_experiment.py

src/r3chain_geothermal/workflow/research_baselines.py

src/r3chain_geothermal/workflow/load_state_evaluation.py

src/r3chain_geothermal/economics/annualized_system_costing.py

src/r3chain_geothermal/decision/research_comparison.py

src/r3chain_geothermal/workflow/research_experiment_export.py

config/research_experiment_synthetic.json

focused tests matching each module.

#### 1.26.2Likely extensions

workflow CLI dispatch;

MCP workflow-mode union/response contract;

persistent run registry type union;

objective extractor registry if annualized LCOH uses a new field name;

README;

CLAUDE.md;

ADR-001 scope decision or a new ADR;

acceptance criteria;

traceability matrix.

#### 1.26.3Must remain unchanged unless strictly required

canonical config/demo_assumptions.json bytes;

canonical C1–C4 expected run identity/KPIs;

historical evidence bundles;

v1 behavior except documentation labels;

v2 joint_study_synthetic_v2.json scientific content (prefer a new research wrapper/package rather than mutating it).

### 1.2726. Design decisions that require no further user clarification

Claude shall proceed with these decisions unless current code makes them impossible:

keep existing v2 as authoritative physical joint evaluation;

add a higher research-experiment layer instead of redesigning v2;

use exhaustive compatible enumeration for the synthetic search space;

use three representative steady states, not transient simulation;

rank integrated feasible alternatives primarily by annualized system LCOH;

preserve Pareto analysis as secondary;

allow shared rank within materiality;

use no scientific tie-breakers unless later approved;

compare rank-1 sets when ties exist;

use useful thermal heat delivered to consumers as system-LCOH denominator;

include pumping electricity in OPEX, not in the heat denominator;

sensitivity is deterministic, not probabilistic;

MCP/LLM orchestration remains non-authoritative for physics and decisions;

no real-location claim.

### 1.2827. Items that must be surfaced if not already approved

Claude shall not invent values for these if the repository/final research specification does not already contain approved values:

exact three load-state demand multipliers;

exact hours/year for each load state;

final materiality thresholds for the new annualized LCOH field if different from current v2 values;

exact sensitivity factor ranges if not explicitly approved;

any new engineering pressure/velocity/temperature thresholds;

any new cost source, price year or currency;

any claim that a synthetic scenario corresponds to a real geological site.

Implementation may support/configure these fields and use clearly labelled synthetic test fixtures, but the final stakeholder run must expose their assumption status.

### 1.2928. Phase-II extension points — design for, do not implement

The new contracts should leave clean extension points for:

independent site-specific real PyDoublet result files;

real EPSG/GIS sites and routes;

approved Wuppertal network data;

depth-dependent geothermal cost model;

bidirectional DH-return/HX/PyDoublet operating-point iteration if PyDoublet supports it;

probabilistic resource scenarios;

exploration probability of success;

Drews-style risk-adjusted LCOH;

coarse screening before detailed simulation at city scale;

multiple geothermal doublets and storage/heat-pump coupling.

Do not implement placeholders that silently return fake values.

### 1.3029. Required final implementation report from Claude

After Phase 9, Claude must report:

exact branch and HEAD;

changed files by phase;

all commands executed;

offline test counts;

wheel/install smoke-test result;

CI run IDs and job statuses;

canonical baseline regression result;

existing v2 baseline regression result;

research experiment run ID and bundle scientific hash;

geothermal-only rank-1 group;

network-only rank-1 group;

integrated rank-1 group;

whether integration changes site and/or attachment conclusion;

Pareto shortlist;

sensitivity robustness classification;

remaining limitations;

any deviation from this specification;

no commit/push unless separately authorized.

## 2Appendix A — Exact Claude Code master prompt

Use the following prompt with Claude Code after this specification has been placed in the repository.

You are implementing the final research-alignment layer of the R3-CHAIN geothermal orchestration prototype.

Repository: ijhewaratne/r3chain-geothermal-orchestrationBaseline branch: latest remote feature/complete-synthetic-prototypeGoverning specification: docs/specifications/R3CHAIN_FINAL_RESEARCH_ALIGNMENT_IMPLEMENTATION_SPEC.md

The corrected v2 joint site–connection architecture already exists. Do not redesign it. Your task is to build the final controlled research experiment above it: three representative steady-state load conditions with correct annualization; primary materiality-aware system-LCOH ranking with Pareto retained as a secondary diagnostic; geothermal-only, network-only and integrated baselines; deterministic comparison of those baselines; controlled sensitivity/robustness analysis; complete provenance/artifacts; and API/CLI/MCP parity through the existing six-tool server.

Non-negotiable boundaries:

preserve the canonical C1–C4 scientific baseline;

preserve the existing v2 scientific baseline and use a wrapper/research package rather than mutating it where possible;

do not fabricate geology, real coordinates, land constraints, costs or PyDoublet outputs;

do not implement transient reservoir simulation or Drews-style exploration risk in this phase;

do not let an LLM calculate physics, feasibility, economics or ranking;

do not add a seventh MCP tool or a separate PyDoublet MCP server;

do not commit, push or open a PR without explicit user authorization;

never weaken/delete a test merely to make the suite pass.

Phase 0 first: read-only audit. Do not edit anything yet.

Report:

exact remote HEAD, branch, clean/dirty state and any divergence;

current implementations of v2 workflow, data contracts, annual economics, decision policy, CLI, MCP, registry, artifacts and tests;

which parts of the new specification are already supported (especially primary_objective_ranking) and therefore require configuration/wiring rather than new duplicate code;

exact files you propose to add/change;

exact tests you will add/run;

risks/ambiguities, especially current low-load curtailment behavior and the treatment of geothermal pump power across load states;

whether any existing scientific hash would change and why.

Stop after the Phase 0 report and wait for authorization.

Once authorized, implement Phases 1–9 in order. At each phase, run focused tests and report the exit gate. Reuse existing deterministic physics/economics/decision helpers; keep new responsibilities modular. The final run must mechanically answer whether the integrated rank-1 site/attachment set matches or differs from the geothermal-only and network-only rank-1 sets, and must report robustness only as “over the tested range.”

## 3Appendix B — Research result interpretation template

The final findings artifact should be structurally capable of producing a statement like this, using only deterministic result fields:

Under the declared synthetic assumptions, the geothermal-only assessment preferred [scenario/site rank group], while the fixed-source network-only assessment preferred [attachment rank group]. The integrated annualized assessment preferred [alternative rank group] at [annualized LCOH or tied range] EUR/MWh. Therefore, integration [did/did not/could not uniquely be shown to] change the preferred geothermal site and [did/did not/could not uniquely be shown to] change the preferred network attachment. The preferred configuration was [robust over the tested sensitivity range / assumption-sensitive / not uniquely ranked]. These results demonstrate the methodology only; they are not a Wuppertal drilling recommendation and do not include exploration-risk probability.

## 4Appendix C — Implementation completion definition

The final six-week synthetic prototype is scientifically complete when it can reproducibly answer:

For this fixed four-consumer district-heating network, these explicitly synthetic geothermal sites/resource scenarios, these network attachments/routes, these declared representative load states and these declared cost assumptions: which compatible alternatives are technically feasible, which feasible alternatives have the lowest annualized system LCOH within materiality, how does that result compare with geothermal-only and network-only assessments, and does the preferred alternative remain stable over the tested assumption range?

Anything beyond that — real Wuppertal siting, probabilistic exploration risk, transient reservoir/network co-simulation or city-scale search acceleration — is Phase II.
