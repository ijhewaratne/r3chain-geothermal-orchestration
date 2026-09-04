# R3-CHAIN Corrected Joint Geothermal Site–Connection Optimisation
## Complete Implementation Specification for Claude Code

**Document status:** Implementation contract  
**Prepared:** 2026-09-04  
**Repository:** https://github.com/ijhewaratne/r3chain-geothermal-orchestration  
**Inspected branch:** feature/complete-synthetic-prototype  
**Inspected commit:** 1fa8d39bb3d1e6db28ffefd790e6c844c968504e  
**Target:** A scientifically coherent, auditable synthetic joint site–connection research prototype

---

## 0. How to use this specification

1. Add this file to docs/specifications/ on a clean implementation branch without altering its requirement IDs.
2. Give Claude Code the exact prompt in Appendix A.
3. Claude performs Phase 0 as a read-only audit and reports before making any edit.
4. After the user authorizes continuation, Claude implements phases in order and verifies each exit gate.
5. A requirement is complete only when code, tests, artifacts and current documentation agree.

Normative words have these meanings:

- must and shall: mandatory for acceptance;
- should: recommended unless Claude documents a repository-specific reason and obtains approval;
- may: optional;
- do not and must not: prohibited.

This specification authorizes implementation edits after the Phase 0 checkpoint. It does not authorize commits, pushes, changes to historical evidence, real-world data claims or presentation editing.

---

## 1. Executive decision

The repository shall retain two methodological layers.

1. **Canonical controlled baseline — preserve unchanged.** One validated PyDoublet result is held fixed and evaluated against the predefined C1–C4 district-heating connection alternatives. This answers: “For this geothermal source, which network attachment is preferred?”
2. **Corrected synthetic joint layer — improve under this specification.** Multiple explicitly synthetic physical sites, site-linked geothermal resource scenarios, site-specific network routes, and configurable designs and policies are evaluated as compatible system alternatives. This answers: “How can candidate geothermal developments and their associated network integrations be compared?”

The corrected joint layer shall demonstrate the methodology needed for a future drilling-location study. It shall not claim to identify a real Wuppertal drilling location.

The approved deployment architecture remains one R3-CHAIN MCP server with an external Claude or scripted client. Do not add a separate PyDoublet MCP server.

### 1.1 Required claim

The finished prototype may state:

> The prototype jointly evaluates explicitly synthetic geothermal sites, site-linked resource scenarios and site-specific district-heating connection designs. It applies heat-exchanger and network feasibility gates before transparent economics, then returns a materiality-aware Pareto shortlist and, only when an approved decision rule is configured, a ranked recommendation.

It must not state:

> The system has determined where the geothermal doublet should be drilled in Wuppertal.

### 1.2 Correct decision entity

For a physical surface site \(s\), a resource scenario \(g\) belonging to that site, a district-heating network attachment \(a\), a compatible site-to-attachment route \(r\), design \(d\), and operating policy \(o\), one alternative is:

\[
x=(s,g,a,r,d,o)
\]

The feasible search set is not an unconstrained Cartesian product:

\[
X=\{(s,g,a,r,d,o)\mid g.site=s,\ r.site=s,\ r.attachment=a,\ d\text{ compatible},\ o\text{ compatible}\}
\]

Only compatible alternatives may reach the scientific evaluation pipeline.

---

## 2. Background and existing implementation

### 2.1 Tanja’s required prototype

The prototype must retain:

- a small synthetic district-heating network with approximately four consumers;
- explicit supply and return circuits;
- PyDoublet-to-heat-exchanger-to-pandapipes coupling;
- several alternative geothermal and network configurations;
- hydraulic and thermal feasibility checks before economics;
- transparent costs and Levelized Cost of Heat (LCOH);
- rejected alternatives with exact reason codes;
- first, second and third results only when a decision policy supports a total order;
- deterministic MCP orchestration and auditability.

### 2.2 Jan Niederau’s modelling boundary

Preserve the following:

- the current PyDoublet output represents a steady or lifetime-average operating point, not an annual time series;
- geothermal brine and district-heating water remain separate through a surface heat exchanger;
- producer and injector wells may be separated underground while their surface facilities form one energy centre;
- using one fixed PyDoublet result was acceptable for the first network-placement experiment;
- real site selection requires real geological inputs and multiple site-specific PyDoublet results.

### 2.3 Canonical result that must remain unchanged

| Rank | Candidate | Paired-trench length | Indicative LCOH | Feasibility |
|---:|---|---:|---:|---|
| 1 | C1 | 50 m | 52.1714 EUR/MWh | feasible |
| 2 | C2 | 70 m | 52.2602 EUR/MWh | feasible |
| 3 | C3 | 90 m | 52.3489 EUR/MWh | feasible |
| 4 | C4 | 120 m | 52.4821 EUR/MWh | feasible |

Expected canonical run ID:

~~~text
r3chain-run-93d41133daa11d1a
~~~

The C1–C4 result is a network-connection ranking for one fixed geothermal scenario. It is not a drilling-site ranking.

### 2.4 Current joint baseline

At the inspected commit, the full-product joint workflow evaluates:

~~~text
3 coupled synthetic site/scenario records
× 11 accepted global connection-route records
× 1 design option
× 1 operating policy
= 33 alternatives
~~~

Observed result:

- 17 feasible alternatives;
- Scenario A: 8 of 11 feasible;
- Scenario B: 0 of 11 feasible because of HX_SUPPLY_TEMPERATURE_INFEASIBLE;
- Scenario C: 9 of 11 feasible;
- five non-dominated alternatives in the full-product Pareto shortlist.

This is a useful synthetic interaction demonstration. It is not yet a coherent geographical siting model because route lengths are global connection attributes rather than distances from each physical site.

### 2.5 Known issues corrected by this specification

1. Six identity fields are described as “six axes,” although design and operating policy do not vary and scenario/site are paired one-to-one.
2. surface_site_id is a label without coordinates or physical constraints.
3. Resource scenarios are perturbations of one golden result, not independently loaded site-linked inputs.
4. Every scenario/site is combined with the same global network routes; route origin is not bound to the site.
5. Aggregate doublet CAPEX is changed with illustrative multipliers, not a depth- or geology-derived drilling-cost model.
6. Pump power is scaled linearly with flow while pressure drawdown and efficiency remain fixed.
7. Connection-pipe diameter is recorded by candidate generation but the evaluator uses a fixed module constant.
8. The Pareto objective set contains mathematically dependent and nested quantities.
9. Strict Pareto comparison treats negligible numerical differences as decision-relevant.
10. The curated six-alternative demonstration and the primary 33-alternative full product can be confused in documentation.
11. No committed ready-to-run joint configuration exists.
12. The joint workflow is available from Python and the CLI but not from geo_run_workflow; some code comments incorrectly imply MCP dispatch exists.
13. The clean-suite result is platform-sensitive. A fresh Linux inspection collected 1,063 tests: 1,054 passed, 6 failed and 3 skipped. Four failures concerned a pinned bundle scientific hash; two concerned a pathological solver failure code. The core joint tests passed.

### 2.6 Requirement traceability to the research conversations

| Research requirement | Implementation response | Primary verification |
|---|---|---|
| Four-consumer supply/return demonstration | Preserve the canonical synthetic network and C1–C4 baseline | GOV-007, TEST-017, AC-J01 |
| Compare potential geothermal placements | Add explicit synthetic surface sites and site-linked resource scenarios | DATA-001–DATA-019, AC-J03 |
| Couple PyDoublet to pandapipes | Preserve typed input, HX boundary, reusable doublet and fresh network evaluation | SCEN-001–SCEN-012, EVAL-001–EVAL-012 |
| Keep geothermal brine separate from DH water | Preserve the surface HX boundary | EVAL-002–EVAL-004 |
| Test technical possibility before cost | Apply ordered HX, solver and technical gates before economics | EVAL-006–EVAL-010, AC-J06–AC-J08 |
| Include connection and geothermal-development economics | Use site/scenario CAPEX, pumping and geometry-derived connection cost without double counting | ECON-001–ECON-015, AC-J09 |
| Return a shortlist or first/second/third | Use a material Pareto set; total order only under a declared policy | DEC-001–DEC-014, AC-J10–AC-J11 |
| Use an auditable orchestrator | Extend the existing six-tool R3-CHAIN MCP server and persistent registry | MCP-001–MCP-012, AC-J13–AC-J14 |
| Start with Jan’s steady/lifetime-average boundary | Carry temporal_basis and prohibit time-series claims | SCEN-011–SCEN-012 |
| Prepare for real Wuppertal data without inventing it | Add a strict real-readiness gate and retain synthetic classification | DATA-006, DATA-019, AC-J15 |

---

## 3. Scope

### 3.1 Included

- preserve and regression-test the canonical C1–C4 workflow;
- correct joint-optimisation terminology and data contracts;
- create explicit synthetic physical surface sites in a local Cartesian coordinate system;
- link each geothermal resource scenario to exactly one site;
- permit multiple resource scenarios per site;
- generate routes separately for every site-to-network attachment combination;
- calculate route length from declared geometry;
- evaluate only compatible site/scenario/connection/route/design/policy combinations;
- make connection-pipe design data executable in pandapipes;
- use explicit, provenance-labelled site/scenario economic inputs;
- redesign the Pareto objectives to remove duplication;
- introduce materiality-aware Pareto comparison;
- optionally produce a total ranking only from a declared approved policy;
- provide a ready-to-run joint configuration;
- expose joint mode through the existing six-tool MCP architecture;
- persist and rehydrate both canonical and joint run types;
- produce deterministic, hash-audited artifacts;
- fix cross-platform reproducibility tests and CI claims;
- update current documentation without rewriting historical plans.

### 3.2 Excluded

- real Wuppertal conclusions;
- fabricated geology, coordinates, land constraints or cost sources;
- a real drilling recommendation;
- dynamic annual PyDoublet–pandapipes co-simulation;
- reservoir simulation inside this repository;
- probabilistic risk scores without sourced inputs;
- an opaque optimiser or LLM-generated ranking;
- a separate PyDoublet MCP server;
- retroactive rewriting of historical evidence bundles or the original six-week plan;
- presentation editing unless separately requested and the presentation is supplied.

### 3.3 Deferred real-study capabilities

Real mode remains gated until an approved study package contains:

- site coordinates and land or permission status;
- site-specific geological inputs;
- independently generated PyDoublet results;
- real network and GIS data with routing constraints;
- approved cost sources, price year and currency;
- uncertainty or success-probability inputs;
- domain-owner approval.

---

## 4. Normative terminology

| Term | Normative meaning |
|---|---|
| Geological/resource site | Subsurface location and geological conditions relevant to the reservoir and wells. |
| Surface site / energy centre | Surface location of wellheads, heat exchanger, pumps and optional heat-pump equipment. |
| Resource scenario | One explicitly sourced or synthetic set of geothermal conditions associated with one site. |
| Producer–injector geometry | Subsurface well trajectories and separation; not the district-heating route. |
| Network attachment | Eligible supply and return junction pair. |
| Route | Site-specific surface corridor from the surface site to the network attachment. |
| Design option | Physical connection or equipment design, including pipe diameter when implemented. |
| Operating policy | Dispatch and shortfall policy used to operate one design. |
| Alternative | One compatible site + resource scenario + network attachment + route + design + policy tuple. |
| Feasible | Passed all applicable input, HX, construction, convergence and technical gates. |
| Pareto shortlist | Feasible alternatives not materially dominated under configured independent objectives. |
| Preferred alternative | One alternative selected only by an explicit approved ranking policy. |
| Synthetic | Constructed solely to test methodology; not evidence about a real place. |

### TERM requirements

- **TERM-001:** Do not use “location” without qualifying geological site, surface site or network attachment.
- **TERM-002:** Do not call six stored identity fields “six active axes.”
- **TERM-003:** Report active_dimensions, their cardinalities and dependency relationships in every joint result.
- **TERM-004:** A dimension with one unique value is controlled, not optimised.
- **TERM-005:** Scenario and site are separate dimensions only when at least one site has multiple scenarios or another explicit many-to-one relationship exists.
- **TERM-006:** A route must reference its origin site and destination attachment; an attachment must not itself embed a route or design.
- **TERM-007:** Use “synthetic joint site–connection evaluation” until real-mode readiness passes.
- **TERM-008:** Use “drilling CAPEX” only for drilling-specific fields. An aggregate multiplier shall be named doublet_capex_multiplier.
- **TERM-009:** In synthetic v2, site_id identifies the candidate surface energy-centre/development location; resource conditions are represented by linked scenarios, not by pretending the surface point is a complete subsurface well model.
- **TERM-010:** Do not claim optimisation of producer/injector trajectories, underground separation or geological target coordinates unless those are explicit decision variables with approved data.

---

## 5. Governance and compatibility

- **GOV-001:** Start from the latest remote feature/complete-synthetic-prototype; record exact branch, commit and clean/dirty state.
- **GOV-002:** If remote HEAD differs from 1fa8d39, inspect and report the intervening diff before applying this specification.
- **GOV-003:** Do not discard, overwrite, stage or commit pre-existing user changes.
- **GOV-004:** Do not modify historical docs/evidence bundle content.
- **GOV-005:** Preserve the original six-week plan body as history; use amendments or status notes.
- **GOV-006:** Preserve config/demo_assumptions.json bytes unless a separately approved migration requires change.
- **GOV-007:** Preserve canonical C1–C4 feasibility, KPIs, ranking and run ID.
- **GOV-008:** Contract additions or semantic changes require appropriate schema-version changes and migration tests.
- **GOV-009:** A scientific-hash change requires causal diagnosis, payload comparison, versioning and explicit rebaseline approval.
- **GOV-010:** Keep calculations in deterministic Python. Claude and MCP may orchestrate and explain only.
- **GOV-011:** New assumptions must be config- or fixture-backed, labelled synthetic_assumption or approved_source, and carry provenance.
- **GOV-012:** Missing interpretation-critical input produces a typed failure; never silently substitute.
- **GOV-013:** Maintain one-server MCP architecture and six public tools.
- **GOV-014:** Do not commit or push without explicit user authorisation.

### 5.1 Documentation authority and historical traceability

Use this hierarchy:

1. this specification is authoritative for the target implementation;
2. executable code and tests are authoritative evidence of current behaviour;
3. a current ADR/scope amendment explains the approved extension and its limitations;
4. README, current acceptance criteria and the traceability matrix describe user-facing current status;
5. CLAUDE.md directs future agents to the current specification and ADR;
6. the original six-week implementation plan remains a historical record only.

- **GOV-015:** Add a short, dated status note above the original six-week plan body stating that the connection-only baseline was later extended by a synthetic joint methodology and linking to the current ADR/specification.
- **GOV-016:** Do not rewrite the original plan body or retroactively claim joint siting was part of its acceptance scope.
- **GOV-017:** Update CLAUDE.md so the historical connection-only restriction is not imported as the current authority; retain it only as the canonical-baseline boundary.
- **GOV-018:** Current documentation must label every material capability as implemented, planned or real-data-gated.
- **GOV-019:** Documentation must distinguish a synthetic candidate site from a geologically validated real drilling site.

---

## 6. Target architecture

~~~mermaid
flowchart TD
    A["Study package"] --> B["Sites and site-linked scenarios"]
    A --> C["Network and eligible attachments"]
    B --> D["Site-specific route generation"]
    C --> D
    D --> E["Compatible alternative enumeration"]
    E --> F["HX and pandapipes evaluation"]
    F --> G["Technical gates"]
    G --> H["Economics and decision policy"]
    H --> I["Audit, artifacts and MCP"]
~~~

### 6.1 Authority chain

1. Raw PyDoublet or declared synthetic resource input is authoritative for geothermal fields.
2. The typed parser and provenance validator are authoritative for input validity.
3. The HX adapter is authoritative for deliverable heat.
4. The reusable doublet component and pandapipes are authoritative for network thermo-hydraulics.
5. Gate code is authoritative for feasibility.
6. Economics code is authoritative for cost and LCOH.
7. Decision-policy code is authoritative for Pareto membership and optional ranking.
8. MCP and reports reproduce those results; they do not reinterpret them.

### 6.2 Implementation boundaries

Follow existing repository conventions, but separate these responsibilities rather than expanding one monolithic module:

| Responsibility | Suggested boundary |
|---|---|
| Joint study contracts and relationship validation | data_contracts/joint_study.py |
| Site-to-attachment route generation and screening | network/site_routing.py |
| Compatible alternative enumeration | workflow/joint_enumeration.py |
| Per-alternative scientific evaluation | workflow/joint_evaluation.py |
| Joint economic overrides and breakdown | economics/joint_costing.py |
| Materiality-aware Pareto and ranking policy | decision/joint_policy.py |
| Atomic run orchestration and publication | workflow/joint_workflow.py |
| Legacy API compatibility | workflow/joint_optimization.py |

Exact filenames may follow established package layout; responsibility separation is mandatory.

- **ARCH-001:** Provide one authoritative run_joint_workflow entry point used by CLI and MCP.
- **ARCH-002:** Keep contracts, routing, scientific evaluation, economics and decision policy independently testable.
- **ARCH-003:** Keep canonical workflow code paths unchanged except for shared backward-compatible helpers.
- **ARCH-004:** Remove production dependence on hidden hard-coded scenarios, costs, routes, objectives or thresholds.
- **ARCH-005:** Keep legacy joint public imports working through documented adapters or publish a versioned migration.
- **ARCH-006:** Never parse semantic fields from a composite identifier.
- **ARCH-007:** Inject clocks or exclude timestamps from scientific identity; wall-clock time cannot change a scientific result.
- **ARCH-008:** CLI, MCP and Python API must consume the same normalized package and return the same scientific result contract.
- **ARCH-009:** Module docstrings and public API documentation must state implemented dispatch and persistence truthfully.

---

## 7. Corrected study-package data contract

Add a versioned joint-study contract, preferably under:

~~~text
src/r3chain_geothermal/data_contracts/joint_study.py
~~~

Exact class names may differ, but the following semantics are mandatory.

### 7.1 JointStudyPackage

Required fields:

~~~yaml
contract_schema_version: "2.0.0"
study_id: string
classification: synthetic | real
coordinate_reference: CoordinateReference
sites: list[SurfaceSite]
resource_inputs: list[ResourceInputReference]
resource_scenarios: list[GeothermalResourceScenario]
network_reference: NetworkReference
network_attachments: list[NetworkAttachment]
routing_policy: RoutingPolicy
design_options: list[ConnectionDesignOption]
operating_policies: list[OperatingPolicyReference]
economics: JointEconomicPolicy
decision_policy: DecisionPolicy
provenance: StudyProvenance
~~~

### 7.2 CoordinateReference

~~~yaml
kind: synthetic_cartesian | epsg
identifier: string
horizontal_unit: m | degree
axis_order: list[string]
epsg_code: integer | null
~~~

For the synthetic demonstration, use:

~~~yaml
kind: synthetic_cartesian
identifier: r3chain-synthetic-network-v1
horizontal_unit: m
axis_order: [x, y]
epsg_code: null
~~~

Coordinate is a discriminated union:

~~~yaml
SyntheticCoordinate: {kind: synthetic_cartesian, x_m: float, y_m: float}
ProjectedCoordinate: {kind: projected, easting_m: float, northing_m: float}
GeographicCoordinate: {kind: geographic, longitude_deg: float, latitude_deg: float}
~~~

All coordinates in one study and all points in one route must match the declared coordinate reference. Real mode requires an explicit EPSG code. Respect declared axis order; do not assume every EPSG CRS uses longitude then latitude.

### 7.3 SurfaceSite

Required fields:

~~~yaml
site_id: string
label: string
classification: synthetic | real
coordinate: Coordinate
elevation_m: float | null
availability_status: available | excluded | unknown
exclusion_reason: string | null
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

Rules:

- synthetic Cartesian sites use SyntheticCoordinate, never longitude/latitude;
- real sites use ProjectedCoordinate or GeographicCoordinate compatible with the declared CRS;
- excluded or unknown sites never reach route generation;
- no site may be represented solely by a label.

### 7.4 ResourceInputReference

~~~yaml
resource_input_id: string
source_kind: primary_runtime_input | package_relative_file
package_relative_path: string | null
expected_raw_sha256: string
expected_file_byte_sha256: string | null
provenance_reference: string
classification: synthetic | real
~~~

Rules:

- primary_runtime_input binds to the existing CLI --input and --provenance arguments or the existing MCP pydoublet_raw_result and source_provenance arguments;
- package_relative_file resolves beneath the validated study-package root and cannot escape it;
- expected_raw_sha256 retains the repository’s existing meaning: the canonical-JSON hash of the exact supplied raw structure, sensitive to numeric representation, key presence and array length;
- expected_raw_sha256 is checked after syntactic JSON loading but before scientific parsing or derivation;
- package_relative_file also requires expected_file_byte_sha256; primary_runtime_input may set it null because an MCP inline object has no original file bytes;
- the config stores references and expected hashes, not a second embedded copy of authoritative raw results.

### 7.5 GeothermalResourceScenario

Required fields:

~~~yaml
scenario_id: string
site_id: string
scenario_label: string
classification: synthetic | real
resource_input_id: string
temporal_basis: lifetime_average_steady | representative_steady_state
probability_label: string | null
probability: float | null
geological_metadata: GeologicalMetadata
economic_inputs: SiteEconomicInputs
derivation: SyntheticDerivation | null
~~~

Rules:

- every scenario references exactly one existing site_id;
- every scenario references exactly one existing resource_input_id;
- IDs are unique within a study;
- derivation null means use the independently validated raw PyDoublet input without transformation;
- a non-null synthetic derivation is allowed only in a synthetic study and requires a machine-readable transformation record;
- parsing or derivation produces the PyDoubletCouplingResult used downstream; it is a calculated result, not duplicated configuration input;
- the current PyDoublet-based demonstration uses lifetime_average_steady and must display that limitation in results;
- probability remains null without a sourced probabilistic interpretation;
- at least one demonstration site has two resource scenarios;
- raw power passes existing energy-consistency validation.

### 7.6 GeologicalMetadata

Support optional, source-labelled fields:

~~~yaml
target_depth_m: float | null
reservoir_temperature_c: float | null
transmissivity_m2_s: float | null
expected_mass_flow_kg_s: float | null
pressure_drawdown_bar: float | null
producer_injector_subsurface_separation_m: float | null
resource_location_reference: string | null
well_geometry_status: absent | synthetic_assumption | approved_source
data_status: absent | synthetic_assumption | approved_source
source_reference: string | null
~~~

Missing fields remain null. Do not fabricate values to populate the schema.

### 7.7 SiteEconomicInputs

~~~yaml
doublet_capex_eur: float | null
drilling_producer_well_capex_eur: float | null
drilling_injector_well_capex_eur: float | null
well_completion_capex_eur: float | null
surface_plant_capex_eur: float | null
contingency_capex_eur: float | null
price_year: int | null
currency: EUR
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

Rules:

- use either aggregate doublet CAPEX or a complete non-overlapping breakdown;
- never add aggregate and component totals together;
- depth-derived cost requires supplied coefficients and source;
- current 0.85, 1.00 and 1.15 compatibility multipliers must be named aggregate doublet multipliers and recorded in derivation metadata;
- doublet-pump electrical power has one authoritative source: coupling_result; do not duplicate it in SiteEconomicInputs;
- real mode rejects illustrative multipliers.

### 7.8 NetworkAttachment

~~~yaml
attachment_id: string
supply_junction_id: string
return_junction_id: string
pressure_zone_id: string
eligibility_status: eligible | excluded | unknown
exclusion_reason: string | null
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

An attachment is a network destination only. It must not embed a site, route, pipe design or operating policy.

### 7.9 SiteConnectionRoute

~~~yaml
route_id: string
site_id: string
attachment_id: string
route_kind: synthetic_polyline | network_graph | external_gis
route_geometry: list[Coordinate]
paired_trench_length_m: float
supply_pipe_length_m: float
return_pipe_length_m: float
screening_status: accepted | rejected
rejection_code: string | null
rejection_detail: string | null
~~~

The route is the explicit relationship between one surface site and one network attachment. Multiple route alternatives may connect the same pair.

### 7.10 ConnectionDesignOption

~~~yaml
design_option_id: string
connection_pipe_inner_diameter_mm: float
pipe_roughness_mm: float
heat_transfer_coefficient_w_m2_k: float | null
capex_eur_per_paired_trench_m: float
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

The selected diameter must control pandapipes construction. It must not remain presentation-only metadata.

### 7.11 AlternativeIdentity

~~~yaml
resource_scenario_id: string
surface_site_id: string
attachment_id: string
route_id: string
design_option_id: string
operating_policy_id: string
alternative_id: string
~~~

Rules:

- alternative_id is derived deterministically from the six typed references in a documented order;
- no code may recover route or design IDs by splitting a composite candidate string;
- the legacy connection_candidate_id may appear only in versioned v1 compatibility readers and historical artifacts;
- identity fields describe one tuple; only independently variable cardinalities may be reported as active dimensions.

### 7.12 DecisionPolicy

~~~yaml
mode: pareto_only | primary_objective_ranking
objectives: list[ObjectiveDefinition]
primary_objective: string | null
tie_breakers: list[string]
allow_shared_rank: boolean
display_order_key: alternative_id
~~~

Each objective contains:

~~~yaml
name: string
direction: minimize | maximize
absolute_materiality: float
relative_materiality_fraction: float
unit: string
rationale: string
source_reference: string
~~~

No weights or thresholds may be invented inside code. alternative_id may stabilize display order but may not decide scientific preference.

### 7.13 NetworkReference

~~~yaml
network_id: string
network_schema_version: string
source_kind: committed_blueprint | approved_dataset
package_relative_path: string
source_sha256: string
topology_scientific_fingerprint: string
classification: synthetic | real
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

The referenced network must resolve beneath the validated study-package root through the existing validated loader. source_reference is evidence metadata, not permission to fetch arbitrary content at runtime.

### 7.14 RoutingPolicy

~~~yaml
route_kind: synthetic_polyline | network_graph | external_gis
maximum_paired_trench_length_m: float
allowed_attachment_ids: list[string]
detour_definitions: list[DetourDefinition]
exclusion_definitions: list[ExclusionDefinition]
shared_trench: boolean
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

Every exclusion, detour and maximum-distance rule must be declared. Unimplemented route kinds fail readiness rather than falling back to straight-line distance.

For the synthetic route kind, use these supporting records:

~~~yaml
DetourDefinition:
  detour_id: string
  site_id: string
  attachment_id: string
  via_coordinates: list[Coordinate]
  reason: string

ExclusionDefinition:
  exclusion_id: string
  geometry: list[Coordinate]
  applies_to: sites | routes | both
  reason: string
  assumption_status: synthetic_assumption | approved_source
  source_reference: string
~~~

An exclusion geometry must form a valid non-self-intersecting polygon with at least three distinct vertices. The synthetic routing algorithm may create only declared straight or via-point polylines; it must not claim shortest-path or GIS routing.

### 7.15 OperatingPolicyReference

~~~yaml
operating_policy_id: string
policy_schema_version: string
package_relative_path: string
source_sha256: string
shortfall_mode: auxiliary | strict
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

The referenced policy is validated by the existing operating-policy contract. Do not duplicate or override policy fields in joint-optimization code.

### 7.16 JointEconomicPolicy

~~~yaml
economic_policy_id: string
economic_schema_version: string
base_assumptions_package_relative_path: string
base_assumptions_sha256: string
annual_operating_hours: float
discount_rate_fraction: float
analysis_period_years: integer
electricity_price_eur_per_mwh: float
auxiliary_heat_price_eur_per_mwh: float
price_year: integer
currency: EUR
assumption_status: synthetic_assumption | approved_source
source_reference: string
~~~

The full existing economic-assumption schema remains authoritative. This joint wrapper identifies and hashes it and exposes the fields required to interpret annualisation. Any site/scenario override must be explicit, typed and non-overlapping.

### 7.17 StudyProvenance

~~~yaml
created_at_utc: datetime
created_by: string
repository_commit: string
software_version: string
parent_input_sha256: list[string]
classification: synthetic | real
approval_status: synthetic_demo_approved | real_study_approved | not_approved
approval_reference: string | null
notes: list[string]
~~~

Real mode requires real_study_approved and a non-null approval reference. A synthetic package can never be promoted to real by changing only classification.

### DATA requirements

- **DATA-001:** Validate all foreign-key relationships before simulation.
- **DATA-002:** Reject duplicate IDs.
- **DATA-003:** Reject scenario-to-site mismatches.
- **DATA-004:** Reject connection routes whose origin does not match site_id.
- **DATA-005:** Reject route endpoints that do not match the declared attachment.
- **DATA-006:** Reject real mode without real-ready provenance and approvals.
- **DATA-007:** Preserve every rejected site, route and alternative with a typed reason.
- **DATA-008:** Store units in field names or typed metadata.
- **DATA-009:** Forbid non-finite numeric values.
- **DATA-010:** Record contract and normalisation versions.
- **DATA-011:** Never infer real coordinates from names or diagrams.
- **DATA-012:** Never convert synthetic Cartesian coordinates into latitude/longitude.
- **DATA-013:** Every site, scenario, cost and route input carries status and source.
- **DATA-014:** A synthetic study package must be self-contained and offline runnable.
- **DATA-015:** Network attachment, route and design are separate entities and foreign keys.
- **DATA-016:** A versioned migration reader may consume legacy composite connection_candidate_id values, but all new v2 results use typed attachment_id, route_id and design_option_id fields.
- **DATA-017:** All coordinate variants must match the declared coordinate reference and axis order.
- **DATA-018:** Runtime input loading is restricted to validated package-relative paths or the explicit primary runtime input; provenance references are not arbitrary network-fetch authority.
- **DATA-019:** Real-mode approval cannot be inferred from classification, filenames or environment variables.
- **DATA-020:** Study, site, resource-input, scenario, network and cost classifications must be mutually compatible.
- **DATA-021:** Every present SHA-256 value is validated as a 64-character lowercase hexadecimal digest before comparison; package-relative files require both byte and canonical raw-result hashes.
- **DATA-022:** Resolve and validate every package-relative path against the package root before opening it; reject absolute paths and traversal.

---

## 8. Synthetic demonstration dataset

Create a committed, ready-to-run package, for example:

~~~text
config/joint_study_synthetic_v2.json
fixtures/joint_study/sites.json
fixtures/joint_study/resource_scenarios/*.json
fixtures/joint_study/routes.json
~~~

### 8.1 Demonstration composition

The dataset shall contain:

- the four-consumer 3.2 MW synthetic DH network;
- at least three available synthetic surface sites with Cartesian coordinates;
- at least one excluded site or site-route combination;
- at least two resource scenarios for one site;
- at least one low-temperature scenario that fails at the HX stage;
- at least two HX-feasible scenarios with different heat, pump and cost characteristics;
- at least two site-specific attachments for one site;
- direct and detoured route geometry where applicable;
- existing DN200 as the default compatibility design;
- optional additional designs only when explicitly configured;
- existing auxiliary/shortfall policy as the compatibility operating policy;
- a declared synthetic demonstration decision policy that preserves the Pareto set and ranks feasible alternatives primarily by indicative LCOH; material ties share a rank unless declared scientific tie-breakers separate them.

### 8.2 Synthetic derivation records

If Scenarios A, B and C are retained, move transformations out of hidden hard-coded logic and record:

- source fixture hash;
- changed field;
- original and transformed values;
- transformation formula;
- rationale;
- assumption status;
- author/date or decision reference.

The transformed coupling result must pass existing typed validation.

### 8.3 Demonstration intent

Without tuning results after execution, prove:

1. the shortest route is not automatically selected only because it is shortest;
2. a low-temperature scenario can fail before network simulation;
3. resource flow can change network feasibility;
4. connection design changes hydraulics when design variation is enabled;
5. site-specific geometry changes length and cost;
6. infeasible alternatives never receive economics;
7. the decision result is reproducible and explained.

---

## 9. Site-specific route generation

Replace global candidate distances with site-origin-aware route generation in joint mode. Preserve the old generator for canonical compatibility where required.

For synthetic_polyline:

\[
L=\sum_{k=1}^{n}\sqrt{(x_k-x_{k-1})^2+(y_k-y_{k-1})^2}
\]

Never accept a separate economic length that differs from the simulated route length.

### ROUTE requirements

- **ROUTE-001:** Generate routes separately for each site and eligible attachment.
- **ROUTE-002:** Derive a stable route ID from site_id, attachment_id, route-kind inputs and geometry identity; do not embed design identity in it.
- **ROUTE-003:** Route geometry starts at the site coordinate.
- **ROUTE-004:** Route geometry terminates at the declared attachment.
- **ROUTE-005:** Compute route length from geometry; do not reuse C1–C4 global distances for all sites.
- **ROUTE-006:** Preserve supply and return pipe lengths separately for hydraulics.
- **ROUTE-007:** If pipes share a trench, charge civil cost once per paired-trench metre and document it.
- **ROUTE-008:** Screen route length, exclusions, endpoints and geometry before pandapipes.
- **ROUTE-009:** Preserve screened routes with exact reason codes.
- **ROUTE-010:** Unimplemented network_graph or external_gis returns a typed unsupported/readiness failure.
- **ROUTE-011:** Ordering and identifiers are deterministic.
- **ROUTE-012:** Export site-specific connection geometry.

---

## 10. Executable connection design

- **DESIGN-001:** Remove unconditional dependence on module-level CONNECTION_PIPE_DN_MM for joint candidates.
- **DESIGN-002:** Pass selected inner diameter into both supply and return connection pipes.
- **DESIGN-003:** Preserve DN200 as canonical default.
- **DESIGN-004:** Validate diameter, roughness and thermal parameters before construction.
- **DESIGN-005:** Include design values in scientific identity and audit.
- **DESIGN-006:** Construction failure returns a typed failure.
- **DESIGN-007:** Do not advertise design as active when one design exists.
- **DESIGN-008:** Add a controlled test proving two diameters change a hydraulic KPI.


---

## 11. Resource-scenario evaluation

- **SCEN-001:** Load resource scenarios from the study package instead of implicitly generating all scenarios inside joint_optimization.py.
- **SCEN-002:** Keep build_synthetic_geothermal_scenarios as a compatibility adapter or deprecate it with migration tests.
- **SCEN-003:** Validate every raw or derived scenario independently.
- **SCEN-004:** Record raw-source and derivation hashes.
- **SCEN-005:** Use each scenario’s own producer temperature, brine flow, raw power and doublet-pump electrical power.
- **SCEN-006:** Never rescale a real PyDoublet pump result downstream.
- **SCEN-007:** Synthetic pump scaling is permitted only with recorded held-constant pressure and efficiency assumptions.
- **SCEN-008:** A low-temperature HX failure is “surface energy-delivery incompatibility under configured supply/HX assumptions,” not proof that the geology is infeasible.
- **SCEN-009:** Multiple scenarios at one site may represent sensitivity cases without invented probabilities.
- **SCEN-010:** Site/scenario provenance survives into every result and artifact.
- **SCEN-011:** Preserve and expose temporal_basis in the alternative result, audit and user-facing report.
- **SCEN-012:** Annual heat and cost values may annualise the declared steady operating point using configured operating hours, but must not be described as an hourly, seasonal or lifetime time-series simulation.

---

## 12. Per-alternative evaluation pipeline

Every compatible alternative runs independently on a fresh network copy.

~~~mermaid
flowchart TD
    A["Validate site, scenario and route"] --> B["Calculate HX boundary"]
    B --> C["Construct doublet and connection"]
    C --> D["Run sequential pandapipes"]
    D --> E["Apply technical gates"]
    E --> F["Calculate economics"]
    F --> G["Decision set"]
~~~

Normative enumeration pseudocode:

~~~text
package = validate_joint_study(raw_package)
baseline = run_or_load_validated_baseline(package.network_reference)
routes = generate_and_screen_routes(package.sites, package.network_attachments,
                                    package.routing_policy)

for site in sort_by_id(available_sites):
    for scenario in sort_by_id(scenarios_where_site_id_equals(site.site_id)):
        for attachment in sort_by_id(eligible_attachments):
            for route in sort_by_id(routes_where_site_and_attachment_match(site, attachment)):
                for design in sort_by_id(compatible_designs(route, attachment)):
                    for policy in sort_by_id(compatible_operating_policies(design)):
                        identity = make_typed_identity(site, scenario, attachment,
                                                       route, design, policy)
                        result = evaluate_fresh_alternative(identity, baseline)
                        retain(result)

feasible = alternatives_where_all_gates_pass()
pareto = materiality_aware_pareto(feasible, declared_objectives)
ranking = optional_declared_primary_objective_ranking(feasible)
publish_atomic_audited_bundle(all_inputs, all_screening, all_results,
                              pareto, ranking)
~~~

Invalid study-package structure fails the run before scientific evaluation and creates no completed run. A valid package may contain screened or infeasible alternatives; those are normal evaluated outcomes and must not abort remaining alternatives. An unexpected internal exception fails the run and must not be converted into a scientific failure code.

### 12.1 Failure taxonomy

Reuse canonical HX, solver and technical-gate codes unchanged. Add or map the following joint semantics without creating duplicate synonyms:

| Code | Stage | Meaning | Scope |
|---|---|---|---|
| JOINT_STUDY_PACKAGE_INVALID | package_validation | Structural, schema or relationship validation failed | whole run |
| JOINT_RESOURCE_INPUT_MISSING | input_resolution | A declared input could not be resolved safely | whole run |
| PYDOUBLET_RAW_HASH_MISMATCH | provenance_check | Existing canonical raw-result hash check failed | whole run |
| JOINT_REAL_STUDY_NOT_READY | readiness | Required real-data approval or source is absent | whole run |
| JOINT_SITE_UNAVAILABLE | site_screening | Site is excluded or not confirmed available | site and descendants |
| JOINT_ROUTE_SITE_MISMATCH | route_validation | Route origin and site foreign key disagree | route |
| JOINT_ROUTE_ATTACHMENT_MISMATCH | route_validation | Route terminus and attachment disagree | route |
| JOINT_ROUTE_EXCLUSION_CONFLICT | route_screening | Route intersects a declared exclusion | route |
| JOINT_ROUTE_TOO_LONG | route_screening | Geometry-derived paired-trench length exceeds policy | route |
| JOINT_ROUTE_KIND_UNSUPPORTED | readiness | Configured route engine is not implemented | whole run or route kind |
| JOINT_DESIGN_INVALID | design_validation | Design values are physically or structurally invalid | design and descendants |
| JOINT_DESIGN_INCOMPATIBLE | compatibility | Valid design is incompatible with route or attachment | alternative |

Every expected failure record includes code, stage, message, affected entity IDs, recoverable flag and deterministic detail. “No feasible alternatives” is a valid completed study result, not one of these failure codes. Unexpected exceptions use the project’s software-error boundary and never a code from this scientific taxonomy.

- **FAIL-001:** Preserve existing canonical failure-code meanings and precedence.
- **FAIL-002:** Whole-run validation, provenance or readiness failures occur before solver calls and completed-run publication.
- **FAIL-003:** Entity-level screening failures are retained and do not abort unrelated compatible alternatives.
- **FAIL-004:** Every failure identifies the most specific affected site, scenario, attachment, route, design or policy IDs available.
- **FAIL-005:** Reuse existing HX and network gate codes rather than wrapping them in a generic joint failure.
- **FAIL-006:** Zero feasible alternatives returns a completed result with an empty decision set.
- **FAIL-007:** Unexpected exceptions remain software errors and never masquerade as scientific infeasibility.
- **FAIL-008:** Where several gates could fail, use documented deterministic stage precedence.
- **FAIL-009:** Failure messages state what failed without claiming a broader geological conclusion.
- **FAIL-010:** Contract and test exhaustiveness checks prevent undocumented failure-code drift.

### EVAL requirements

- **EVAL-001:** Provenance and compatibility validation precede calculations.
- **EVAL-002:** HX coupling is evaluated per resource scenario.
- **EVAL-003:** Geothermal brine and DH water flows remain separate.
- **EVAL-004:** Use one authoritative reusable doublet-component path.
- **EVAL-005:** Use a fresh network for each alternative; no mutation leakage.
- **EVAL-006:** Full sequential thermo-hydraulic convergence is mandatory.
- **EVAL-007:** Preserve configured gate order and exact reason codes.
- **EVAL-008:** Apply temperature, pressure, pump differential, velocity, shortfall, mass and energy gates as applicable.
- **EVAL-009:** Never calculate economics for an infeasible alternative.
- **EVAL-010:** Retain incompatible, screened and simulated alternatives separately.
- **EVAL-011:** Record final reached stage and failure stage.
- **EVAL-012:** The LLM cannot repair failures or insert missing values.
- **EVAL-013:** One expected alternative failure does not abort evaluation of other compatible alternatives.
- **EVAL-014:** Unexpected software exceptions remain software errors and are never relabelled as physical infeasibility.

---

## 13. Corrected economics

For feasible alternative \(i\):

\[
C_{annual,i}=A_{doublet,i}+A_{HX,i}+A_{connection,i}+O\&M_i+E_{geo\ pump,i}+E_{DH\ pump,i}+C_{aux,i}
\]

\[
LCOH_i=\frac{C_{annual,i}}{Q_{delivered,i,annual}}
\]

Every term must be present, explicitly zero with a reason, or marked absent.

### ECON requirements

- **ECON-001:** Rename aggregate drilling_capex_multiplier to doublet_capex_multiplier unless a drilling-only breakdown is implemented.
- **ECON-002:** Accept explicit site/scenario aggregate CAPEX or a non-overlapping component breakdown.
- **ECON-003:** Do not infer drilling cost from depth without approved coefficients and source.
- **ECON-004:** Use each scenario’s declared or PyDoublet-reported doublet-pump electrical power.
- **ECON-005:** Audit any synthetic pump formula and held-constant assumptions.
- **ECON-006:** Connection CAPEX uses site-specific paired-trench length and selected design cost per metre.
- **ECON-007:** Pandapipes and economics consume the same route-length record.
- **ECON-008:** HX CAPEX remains fixed only when explicitly declared; support a versioned duty-dependent strategy when sourced data exist.
- **ECON-009:** Fixed O&M states which CAPEX components it covers.
- **ECON-010:** Electricity and auxiliary prices carry currency, price year, source and status.
- **ECON-011:** Label outputs indicative until costs are approved.
- **ECON-012:** Preserve the caveat that auxiliary-heat price may exclude auxiliary-plant CAPEX and fixed O&M.
- **ECON-013:** Do not count curtailed heat in useful heat.
- **ECON-014:** Do not double-count aggregate and component CAPEX.
- **ECON-015:** Export a per-alternative breakdown and difference explanation.

---

## 14. Corrected Pareto and ranking policy

### 14.1 Remove dependent objectives

The existing default set is unsuitable as six equal dimensions because:

\[
LCOH=\frac{annualised\ cost}{fixed\ annual\ delivered\ heat}
\]

and:

\[
Q_{geo}+Q_{aux}=Q_{demand}
\]

Pumping cost and connection CAPEX are also already inside annualised cost.

### 14.2 Default non-duplicative objectives

Use these for the synthetic demonstration:

1. indicative_system_lcoh_eur_per_mwh — minimise;
2. geothermal_coverage_fraction — maximise;
3. total_pumping_electric_energy_mwh_per_a — minimise.

Connection length remains a planning KPI and becomes an objective only when the policy justifies value beyond captured cost and energy.

Annualised cost remains reported but is not a second Pareto objective when all alternatives share the same LCOH denominator. Auxiliary heat remains reported but is not a second objective when it exactly complements coverage.

These objectives are not statistically independent: coverage and pumping energy can affect LCOH. They are retained because they expose distinct physical decision consequences and are not exact monotonic transformations of LCOH. The objective registry must disclose such dependencies. If the required decision is purely minimum cost, use primary-objective ranking and present the other metrics as explanatory KPIs rather than claiming a multi-objective optimum.

### 14.3 Materiality-aware dominance

For objective \(j\), values \(a_j\) and \(b_j\) are practically equivalent when:

\[
|a_j-b_j|\leq\max(\epsilon_{abs,j},\epsilon_{rel,j}\max(|a_j|,|b_j|))
\]

A materially dominates B only when A is no worse outside those tolerances on every objective and materially better on at least one.

### DEC requirements

- **DEC-001:** Objectives and materiality thresholds live in configuration.
- **DEC-002:** Every objective has unit, direction, rationale and decision/source reference.
- **DEC-003:** Reject duplicate or algebraically dependent default objectives.
- **DEC-004:** Use electrical energy, not electricity cost, as a pumping objective when cost is already in LCOH.
- **DEC-005:** Pareto logic uses configured absolute and relative materiality.
- **DEC-006:** Explain why each shortlisted alternative is non-dominated.
- **DEC-007:** Report trade-offs at user-facing precision.
- **DEC-008:** pareto_only returns no preferred ID or arbitrary rank.
- **DEC-009:** primary_objective_ranking requires an explicit primary objective and deterministic tie-breakers.
- **DEC-010:** Feasibility always precedes decision logic.
- **DEC-011:** Minimum-LCOH mode groups materially equivalent LCOH values before applying declared scientific tie-breakers; unresolved material ties share a rank.
- **DEC-012:** Run sensitivity analysis before presenting one preferred result when synthetic cost assumptions can change order.
- **DEC-013:** Preserve the Pareto set when a secondary total ranking is produced.
- **DEC-014:** Never call a Pareto member “optimal” without naming its objective or trade-off.
- **DEC-015:** alternative_id may order equal records for serialization or display but may not break a scientific decision tie.

---

## 15. Workflow integration

Preserve the existing CLI shape:

~~~text
r3chain-geothermal-demo \
  --input fixtures/pydoublet/repaired_result.json \
  --provenance config/demo_source_provenance.json \
  --config config/joint_study_synthetic_v2.json \
  --output-dir artifacts/joint-study-v2
~~~

In joint mode, the ResourceInputReference whose source_kind is primary_runtime_input binds to --input and --provenance. Synthetic variants are derived from that validated input only through declared transformation records. Additional package-relative inputs are allowed by the v2 contract but are not required for the single-fixture synthetic demonstration. The canonical non-joint invocation and exit-code meanings remain backward compatible.

- **WF-001:** Add a committed joint configuration accepted by r3chain-geothermal-demo.
- **WF-002:** Absence of joint mode remains canonical single-scenario behaviour.
- **WF-003:** Validate the joint package before baseline or candidate simulation.
- **WF-004:** Replace blind scenario × global-candidate enumeration with compatible site-linked enumeration.
- **WF-005:** Report counts for sites, scenarios, attachments, routes, designs, policies, possible combinations, screened combinations, compatible alternatives, evaluated alternatives and feasible alternatives.
- **WF-006:** evaluated_count equals the compatible post-screening set.
- **WF-007:** Preserve deterministic ordering and IDs.
- **WF-008:** Keep the curated six-alternative function only as a named test/example helper.
- **WF-009:** The primary demonstration uses the full compatible set.
- **WF-010:** Zero feasible alternatives is a completed evaluation with an empty shortlist, not a software error.
- **WF-011:** Real mode invokes readiness before alternative generation.
- **WF-012:** Correct documentation that currently implies unimplemented MCP or registry integration.

---

## 16. MCP and persistent registry

Keep exactly these six public tools:

1. geo_get_capabilities
2. geo_validate_pydoublet_result
3. geo_run_workflow
4. geo_get_run_summary
5. geo_get_audit
6. geo_get_artifact

Do not add a seventh tool.

### 16.1 Joint summary

Extend geo_run_workflow with a genuinely distinct discriminated success type:

~~~yaml
status: success
workflow_mode: joint_site_connection
run_id: string
study_classification: synthetic
site_count: integer
resource_scenario_count: integer
network_attachment_count: integer
route_count: integer
design_option_count: integer
operating_policy_count: integer
compatible_alternative_count: integer
evaluated_alternative_count: integer
feasible_alternative_count: integer
active_dimensions: list[string]
controlled_dimensions: list[string]
pareto_shortlist_alternative_ids: list[string]
ranked_alternative_groups: list[list[string]]
preferred_alternative_id: string | null
decision_policy_mode: pareto_only | primary_objective_ranking
artifact_filenames: list[string]
bundle_scientific_sha256: string
reused_existing_run: boolean
~~~

### MCP requirements

- **MCP-001:** geo_get_capabilities truthfully advertises canonical and joint modes.
- **MCP-002:** geo_run_workflow dispatches from validated fixed configuration.
- **MCP-003:** Use a discriminated union; never force Pareto results into canonical integer ranks.
- **MCP-004:** preferred_alternative_id is null under pareto_only and whenever the first ranked group contains more than one materially tied alternative.
- **MCP-005:** Joint artifacts use existing allow-list and pagination protections.
- **MCP-006:** Registry stores a run-type discriminator.
- **MCP-007:** Rehydration validates the correct manifest and result contract.
- **MCP-008:** Canonical MCP responses remain backward compatible.
- **MCP-009:** Strict provenance mismatch still creates no run directory.
- **MCP-010:** Prevent path traversal and arbitrary artifact access.
- **MCP-011:** Scripted MCP and CLI produce equivalent joint scientific results.
- **MCP-012:** Documentation matches the implemented interface exactly.

---

## 17. Artifacts and audit

The primary joint run shall publish:

~~~text
resource_input_index.json
joint_study_snapshot.json
sites.json
resource_scenarios.json
screened_site_connection_routes.json
compatible_alternatives.json
joint_optimization_result.json
alternative_comparison.csv
objective_policy.json
pareto_or_ranking.json
site_route_geometry.json
network_candidates.svg
joint_recommendation.md
audit.json
manifest.json
~~~

site_route_geometry.json shall declare synthetic_cartesian_m. Produce location_shortlist.geojson only with genuine compatible geospatial coordinates.

### AUD requirements

- **AUD-001:** Preserve declared inputs and calculated results separately.
- **AUD-002:** Record source, config and contract hashes.
- **AUD-003:** Record active and controlled dimensions.
- **AUD-004:** Record compatibility and screening counts.
- **AUD-005:** Record every failure code and stage.
- **AUD-006:** Record economic boundary and assumption sources.
- **AUD-007:** Record objectives and materiality thresholds.
- **AUD-008:** Record Pareto explanations and optional ranking tie-breaks.
- **AUD-009:** Create and validate manifest last.
- **AUD-010:** No personal path, token, secret or temporary-directory name in committed artifacts.
- **AUD-011:** Every user-facing joint output carries a visible synthetic disclaimer.
- **AUD-012:** Historical evidence remains immutable.

---

## 18. Reproducibility and scientific fingerprints

Separate:

1. **Byte hash:** exact artifact bytes.
2. **Scientific fingerprint:** field-aware normalized scientific content at declared meaningful precision.
3. **Scientific equivalence:** logical results plus KPI comparisons within declared tolerances.

Required correction:

- Do not treat one macOS solver-output bundle hash as universal proof across BLAS/LAPACK implementations.
- Either pin a containerized numerical environment for bit-identical hashes or implement a versioned field-aware fingerprint.
- Continue exact hashes for raw inputs and configuration.
- Cross-platform CI compares logical identities and numeric KPIs within scientific tolerances.

### REPRO requirements

- **REPRO-001:** Reproduce the known Linux failures before changing tests.
- **REPRO-002:** Diff per-file scientific hashes and normalized payloads to locate divergent fields.
- **REPRO-003:** Do not merely replace the expected macOS hash with a Linux hash.
- **REPRO-004:** Version fingerprint-rule changes.
- **REPRO-005:** Produce macOS/Linux comparison evidence in CI.
- **REPRO-006:** Test declared Python support; include 3.11 and 3.12 or narrow metadata honestly.
- **REPRO-007:** Do not use pathological solver behaviour as the sole unit proof of a precise non-convergence code.
- **REPRO-008:** Test non-convergence via deterministic injected solver failure.
- **REPRO-009:** Keep an integration test requiring extreme demand to be rejected by an applicable technical failure without assuming every backend chooses the same first failure.
- **REPRO-010:** Never weaken a physical gate to achieve parity.

---

## 19. Required tests

### 19.1 Unit tests

- **TEST-001:** Site/scenario IDs validate and serialize deterministically.
- **TEST-002:** Missing site reference is rejected.
- **TEST-003:** Route-origin mismatch is rejected.
- **TEST-004:** Route-endpoint mismatch is rejected.
- **TEST-005:** Polyline length is calculated correctly.
- **TEST-006:** Excluded site/route is retained with reason.
- **TEST-007:** Synthetic derivation is recorded and physically valid.
- **TEST-008:** Real scenario cannot use a synthetic multiplier.
- **TEST-009:** Aggregate and component CAPEX cannot be double-counted.
- **TEST-010:** Per-design diameter reaches pandapipes.
- **TEST-011:** Different diameters change a controlled hydraulic KPI.
- **TEST-012:** Objective validation detects dependent defaults.
- **TEST-013:** Materiality-aware dominance ignores sub-threshold differences.
- **TEST-014:** Material differences change Pareto membership.
- **TEST-015:** pareto_only cannot create a preferred ID or rank.
- **TEST-016:** Primary-objective ranking is deterministic.

### 19.2 Integration tests

- **TEST-017:** Canonical C1–C4 regression remains unchanged.
- **TEST-018:** Full joint run enumerates only compatible alternatives.
- **TEST-019:** The same attachment has different routes and costs from different sites.
- **TEST-020:** At least one site has multiple scenarios.
- **TEST-021:** Low-temperature scenario fails before network construction.
- **TEST-022:** Resource flow can change a network gate outcome.
- **TEST-023:** Infeasible alternatives have no economics.
- **TEST-024:** Every accepted alternative uses a fresh network.
- **TEST-025:** Repeated runs preserve ordering, logic and scientific fingerprint.
- **TEST-026:** Joint CLI publishes the complete bundle.
- **TEST-027:** MCP joint result equals CLI result.
- **TEST-028:** Joint run survives registry restart.
- **TEST-029:** Artifact pagination reaches next_offset null.
- **TEST-030:** Incomplete real mode calls no solver or ranking code.
- **TEST-031:** An expected infeasible alternative does not abort remaining compatible alternatives.
- **TEST-032:** An injected internal exception fails the run as a software error and is not emitted as a scientific failure code.

### 19.3 Cross-platform tests

- **TEST-033:** Ubuntu/Python 3.11 full suite.
- **TEST-034:** Ubuntu/Python 3.12 full suite if metadata supports it.
- **TEST-035:** macOS/Python 3.11 full suite.
- **TEST-036:** Canonical wheel smoke test on each supported environment.
- **TEST-037:** Joint wheel smoke test on each supported environment.
- **TEST-038:** Cross-platform scientific-equivalence comparison.

No test may be removed or weakened merely to obtain a green suite.

---

## 20. Executable acceptance scenarios

### AC-J01 — Canonical preservation

Run the original configuration. Require the established run ID, C1–C4 feasibility, LCOH values and ranking.

### AC-J02 — Honest dimension report

Verify the result distinguishes six identity fields from dimensions with more than one independent value.

### AC-J03 — Site/scenario relationship

Every scenario belongs to one site, and at least one site has multiple scenarios.

### AC-J04 — Site-specific routing

The same attachment evaluated from two different sites produces geometry-derived site-specific lengths.

### AC-J05 — Compatibility-constrained enumeration

An intentionally mismatched route is rejected before HX or pandapipes. Evaluated count equals the compatible set.

### AC-J06 — HX failure

The low-temperature scenario returns HX_SUPPLY_TEMPERATURE_INFEASIBLE with no network or economic result.

### AC-J07 — Network interaction

At the same attachment and design, changing resource flow changes at least one network gate outcome.

### AC-J08 — Executable design

Two configured pipe diameters produce different hydraulic results in a controlled case.

### AC-J09 — Economic traceability

Independently recompute every cost term and LCOH for one feasible alternative from artifacts.

### AC-J10 — Material Pareto logic

Two alternatives differing only below thresholds are not separated because of that insignificant difference.

### AC-J11 — Decision mode

pareto_only returns no preferred ID. Explicit minimum-LCOH mode returns a deterministic ranked feasible list, preserves the Pareto set, and assigns the same rank to alternatives that remain materially tied after scientific tie-breakers. A unique preferred ID is present only when rank 1 contains one alternative.

### AC-J12 — Complete primary demonstration

Run the committed joint config by CLI and verify all counts, artifacts and manifest.

### AC-J13 — MCP parity

Run the same config through geo_run_workflow and retrieve summary, audit and every artifact page. Require CLI parity.

### AC-J14 — Restart recovery

Restart the MCP server and retrieve the same joint run without recomputation.

### AC-J15 — Real-data gate

An incomplete real package returns readiness failure with zero solver calls and no recommendation.

### AC-J16 — Cross-platform release gate

Complete suite and both wheel smoke tests pass on every supported CI environment.

### AC-J17 — Claim audit

README, ADRs, current specifications, module documentation, templates and capabilities contain no real-drilling or six-active-axis overclaim.

### AC-J18 — Internal-error boundary

Inject a deterministic internal exception after package validation. Require a software-error result, no scientific infeasibility code, no completed run publication and no partial artifact exposed through MCP.

---

## 21. Phased implementation plan

### Phase 0 — Read-only baseline audit

1. Fetch remote branches and record branch, HEAD, status and remotes.
2. Read CLAUDE.md, README, ADR-001, decision register, joint issue documents and this specification completely.
3. Run canonical, joint, MCP and registry targeted tests.
4. Run the full suite in the existing environment.
5. Reproduce or classify Linux failures.
6. Report a file-by-file implementation map.

**Exit gate:** No file changed; baseline reported.

### Phase 1 — Current-scope correction, contracts and terminology

First add the dated historical-plan status note, current ADR/scope amendment and corrected CLAUDE.md authority hierarchy. Describe the current code exactly, including its limitations, without claiming the target improvements already exist. Then implement joint package, site, scenario, route, design and decision schemas. Add relationship validation and active-dimension reporting.

**Exit gate:** Schema tests pass; canonical path unchanged.

### Phase 2 — Site-linked scenarios and routes

Move synthetic scenarios into committed fixtures/config with derivation records. Add sites and site-origin-aware routes. Enumerate compatible alternatives only.

**Exit gate:** AC-J02 through AC-J07 pass.

### Phase 3 — Executable designs

Thread connection diameter and supported design fields into reusable doublet/network construction, retaining canonical DN200.

**Exit gate:** AC-J08 passes; canonical values unchanged.

### Phase 4 — Economics and decision policy

Correct CAPEX terminology, consume site/scenario costs, remove duplicated objectives, implement materiality-aware Pareto logic and optional primary-objective ranking.

**Exit gate:** AC-J09 through AC-J11 pass.

### Phase 5 — Primary workflow and artifacts

Add ready-to-run joint configuration, full compatible enumeration and required audit bundle. Keep curated demo secondary.

**Exit gate:** AC-J12 passes twice in independent output directories.

### Phase 6 — MCP and persistent registry

Add a discriminated joint summary, config dispatch, artifact retrieval and joint rehydration through the existing six tools.

**Exit gate:** AC-J13 and AC-J14 pass.

### Phase 7 — Cross-platform reproducibility

Diagnose hash and pathological-solver failures. Add field-aware equivalence or pin the numerical environment. Align CI and Python metadata.

**Exit gate:** AC-J16 passes everywhere supported.

### Phase 8 — Final documentation and traceability reconciliation

Reconcile README, current ADR amendment, decision register, current acceptance criteria, traceability matrix and issue files against the completed behaviour. Preserve historical bodies and evidence. Clearly mark remaining work and real-data gates.

**Exit gate:** AC-J17 passes; no stale interface or scope statements.

### Phase 9 — Release-candidate verification

1. Run targeted and full tests with counts, duration and exit code.
2. Build/install wheel in clean supported environments.
3. Run canonical and joint CLI outside the repository.
4. Run scripted MCP parity and restart recovery.
5. Run privacy, secret and personal-path scans.
6. Run git diff --check.
7. Inspect every staged file explicitly.

**Exit gate:** All acceptance scenarios pass and limitations are documented.

---

## 22. Suggested commit strategy

Only commit after explicit user authorisation.

1. feat(joint): add site-linked study contracts
2. feat(routing): generate site-specific connection routes
3. feat(network): consume candidate connection designs
4. feat(economics): correct joint site cost boundaries
5. feat(decision): add materiality-aware Pareto policy
6. feat(workflow): publish full compatible joint runs
7. feat(mcp): expose joint workflow through existing tools
8. test(ci): enforce supported-platform equivalence
9. docs: align current joint-optimization methodology

Use explicit paths when staging. Never use git add dot or git add -A. Do not amend historical T5.1C evidence commits. Do not push without permission.

---

## 23. Stop and escalation conditions

Stop and report when:

- the working tree contains overlapping unexplained changes;
- the advanced branch moved and conflicts with this specification;
- canonical C1–C4 results change unexpectedly;
- a scientific or economic value lacks an approved or explicitly synthetic source;
- real coordinates or geology are required but unavailable;
- contract meaning changes without a version decision;
- objectives require unapproved weights or thresholds;
- tests fail for an unexplained reason;
- a bundle hash changes without isolated causal explanation;
- MCP compatibility would silently change canonical response meaning;
- implementation would rewrite historical evidence;
- licence or data-use restrictions block redistribution.

Do not resolve these by guessing.

---

## 24. Definition of done

The corrected synthetic joint prototype is complete only when:

1. Canonical C1–C4 remains unchanged.
2. Physical sites have explicit synthetic coordinates.
3. Every resource scenario links to a site with provenance.
4. Every route starts at its site and ends at its attachment.
5. Only compatible alternatives are enumerated.
6. Pipe design affects pandapipes when varied.
7. Technical feasibility precedes economics.
8. Economics is explicit and non-double-counted.
9. Pareto objectives are non-duplicative and materiality-aware.
10. A preferred result appears only under an approved ranking policy.
11. The full compatible search is the primary demonstration.
12. CLI, MCP and persistent retrieval agree.
13. Audit and manifest cover the complete joint bundle.
14. All supported-platform tests and clean installs pass.
15. Documentation says synthetic methodology, not real drilling recommendation.

A real Wuppertal result requires approved geology, coordinates, PyDoublet results, GIS routes, costs, uncertainty inputs and domain-owner review. It is not part of this implementation.

---

## Appendix A — Exact master prompt for Claude Code

> Implement R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md against https://github.com/ijhewaratne/r3chain-geothermal-orchestration.
>
> Treat the specification as the implementation contract. Begin with Phase 0 only. Do not edit code, documentation or tests until you have completed and reported the read-only baseline audit.
>
> Start from the latest remote feature/complete-synthetic-prototype. Verify whether HEAD still matches inspected commit 1fa8d39bb3d1e6db28ffefd790e6c844c968504e. If it differs, inspect and report intervening changes. Preserve all pre-existing user changes.
>
> Preserve the canonical C1–C4 workflow, run ID, feasibility, KPIs and ranking. This is an additive correction to the synthetic joint layer, not a rewrite of the accepted baseline.
>
> The essential correction is compatibility-constrained enumeration: every resource scenario references a contract-level site; every route originates at that site and terminates at its declared DH supply/return attachment; evaluate only compatible tuples. Do not reuse one global connection distance unchanged across sites.
>
> Do not call the current six-field identity six active optimisation axes. Report which dimensions vary and which are controlled.
>
> Move synthetic assumptions into explicit provenance-labelled configuration or fixtures. Do not fabricate geology, coordinates, costs, probabilities or real Wuppertal inputs.
>
> Remove algebraically duplicated default objectives, implement configured materiality-aware Pareto dominance, and produce a preferred result only under an explicit approved primary-objective policy. Feasibility always precedes economics and ranking.
>
> Thread connection design values, especially pipe diameter, into pandapipes while preserving DN200 and canonical results by default.
>
> Integrate joint mode through the existing six MCP tools using a distinct discriminated summary. Do not add a seventh tool or separate PyDoublet MCP server.
>
> Diagnose known Linux reproducibility failures. Do not update golden hashes or weaken physical gates without identifying causes and documenting a versioned equivalence policy.
>
> Work phase by phase. Before each phase, report intended files, tests, assumptions and risks. After each phase, run targeted tests and report exact results. Stop on unexplained scientific change, missing assumption, dirty overlap, contract ambiguity or test failure.
>
> Do not rewrite historical evidence or the original six-week plan body. Do not edit the presentation. Do not commit or push unless explicitly authorised.
>
> At completion, report requirements implemented by ID, files changed, exact tests, canonical regression evidence, joint acceptance results, CLI/MCP parity, cross-platform status, authorised commits, remaining limitations and the precise defensible claim.

---

## Appendix B — Abbreviations

| Abbreviation | Meaning |
|---|---|
| ADR | Architectural Decision Record |
| API | Application Programming Interface |
| BLAS | Basic Linear Algebra Subprograms |
| CAPEX | Capital Expenditure |
| CI | Continuous Integration |
| CLI | Command-Line Interface |
| CRS | Coordinate Reference System |
| CSV | Comma-Separated Values |
| DH | District Heating |
| DN | Nominal Diameter; a standardized pipe-size designation |
| EPSG | European Petroleum Survey Group; commonly used name for its coordinate-reference-system code registry |
| EUR | Euro |
| GIS | Geographic Information System |
| HX | Heat Exchanger |
| ID | Identifier |
| JSON | JavaScript Object Notation |
| KPI | Key Performance Indicator |
| LAPACK | Linear Algebra PACKage |
| LCOH | Levelized Cost of Heat |
| MCP | Model Context Protocol |
| O&M | Operations and Maintenance |
| OPEX | Operating Expenditure |
| PoC | Proof of Concept |
| QA | Quality Assurance |
| SHA-256 | Secure Hash Algorithm producing a 256-bit digest |
| SVG | Scalable Vector Graphics |
| URI | Uniform Resource Identifier |

## Appendix C — Units and symbols

| Symbol | Meaning |
|---|---|
| °C | Degree Celsius, used for temperature |
| bar | Bar, a pressure unit equal to 100,000 pascals |
| EUR | Euro, the configured currency |
| EUR/MWh | Euro per megawatt-hour of useful delivered heat |
| kg/s | Kilograms per second, used for mass flow |
| kW | Kilowatt, a unit of power |
| m | Metre, used for distance and route length |
| m²/s | Square metres per second, used here for transmissivity |
| mm | Millimetre, used for pipe diameter or roughness |
| MW | Megawatt, a unit of power |
| MWh | Megawatt-hour, a unit of energy |
| W/(m²·K) | Watt per square metre-kelvin, used for heat-transfer coefficients |
| \(\epsilon_{abs}\) | Configured absolute materiality tolerance for an objective |
| \(\epsilon_{rel}\) | Configured relative materiality tolerance for an objective |
