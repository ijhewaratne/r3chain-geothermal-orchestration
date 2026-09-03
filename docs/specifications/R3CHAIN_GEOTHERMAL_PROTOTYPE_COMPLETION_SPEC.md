# R3-CHAIN Geothermal Orchestration
## Prototype Completion Specification and Claude Code Execution Contract

**Document version:** 1.0  
**Date:** 2026-09-03  
**Canonical repository:** `https://github.com/ijhewaratne/r3chain-geothermal-orchestration`  
**Target branch family:** `feature/r3chain-orchestration-poc` followed by phase-specific feature branches  
**Intended executor:** Claude Code working inside the repository  
**Document status:** Implementation specification  

---

## 1. Executive directive to Claude Code

Complete the R3-CHAIN geothermal orchestration research prototype without overstating what the available data can support.

The completed prototype shall:

1. ingest and validate a provenance-controlled PyDoublet result;
2. convert the subsurface result into a defensible surface heat-exchanger boundary;
3. represent the geothermal connection as a reusable pandapipes-compatible composite component;
4. evaluate technically independent district-heating connection candidates;
5. generate candidate connection points deterministically rather than relying only on four hard-coded alternatives;
6. enforce every declared executable technical gate;
7. support auxiliary-supply and strict-infeasible shortfall policies;
8. include at least one deterministic, intentionally infeasible demonstration candidate;
9. persist run metadata and artifacts across MCP server restarts;
10. expose the deterministic workflow through the already selected one-server, six-tool MCP architecture;
11. provide schemas and validators for later real network, GIS and geological data;
12. demonstrate combined site/connection optimisation using explicitly synthetic spatial scenarios; and
13. refuse to claim a real Wuppertal drilling or connection recommendation until approved real data are supplied.

The language model is an orchestrator and reporter. It must never calculate, replace, estimate or “repair” scientific, hydraulic, thermal, economic or ranking results outside deterministic code.

---

## 2. Normative language

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT** and **MAY** are normative.

- **MUST/SHALL**: required for acceptance.
- **SHOULD**: expected unless a documented engineering reason is recorded.
- **MAY**: optional.
- **External decision**: requires approval from Tanja, Dr. Jan or another named domain owner; Claude must not decide it silently.
- **External data dependency**: cannot be completed by coding alone; Claude must implement the contract and report the dependency honestly.

---

## 3. Current verified baseline

The repository already contains a working deterministic vertical slice:

- strict PyDoublet JSON parsing with units and RFC 6901 source pointers;
- source-provenance contracts and whole-input hashing;
- heat-exchanger feasibility and deliverable-heat calculation;
- a four-consumer, 3.2 MW synthetic district-heating network;
- baseline and independent C1-C4 pandapipes evaluations;
- convergence, temperature, pressure, velocity, mass and energy checks;
- provisional CAPEX, OPEX, annuity and LCOH calculations;
- feasibility-first deterministic ranking;
- JSON, CSV, SVG, Markdown, audit and manifest artifacts;
- exactly six public `geo_` MCP tools;
- scripted MCP orchestration and Claude Desktop orchestration evidence;
- T5.1C PASS for Claude Desktop/MCP orchestration;
- a reconciled test baseline of 838 passing tests before the new work begins.

The present canonical synthetic comparison is:

| Candidate | Connection length | Indicative LCOH | Rank | Status |
|---|---:|---:|---:|---|
| C1 | 50 m | 52.1714 EUR/MWh | 1 | Feasible |
| C2 | 70 m | 52.2602 EUR/MWh | 2 | Feasible |
| C3 | 90 m | 52.3489 EUR/MWh | 3 | Feasible |
| C4 | 120 m | 52.4821 EUR/MWh | 4 | Feasible |

This comparison means only that C1 is preferred among four predefined **network connection pairs** for one fixed geothermal scenario and one synthetic network. It is not a drilling-site result.

### 3.1 Existing architectural decisions that shall not be reopened silently

1. The integration uses one R3-CHAIN MCP server with an external Claude/scripted client.
2. No separate PyDoublet-MCP server shall be created for this prototype.
3. PyDoublet remains authoritative for the doublet/subsurface result.
4. The adapter remains authoritative for the surface heat-exchanger boundary.
5. pandapipes remains authoritative for district-heating thermo-hydraulics.
6. Deterministic project code remains authoritative for gates, economics and ranking.
7. `repos/pandapipesAI` remains reference-only unless a separate, explicit upstream-integration decision is approved.
8. Existing T5.1C evidence is historical evidence and must not be rewritten to match later code.

---

## 4. Completion boundary

### 4.1 Prototype completion target

The prototype is complete when it can deterministically evaluate:

> one or more provenance-controlled geothermal scenarios against predefined or automatically generated district-heating connection candidates, apply transparent technical and economic screening, survive MCP server restarts, and return an audited ranked connection shortlist or Pareto set.

The completion demonstration MAY use synthetic network, GIS and geological scenarios, but every synthetic item must be explicitly labelled.

### 4.2 Real-study boundary

A real Wuppertal connection or drilling recommendation is **not** part of the software-only completion condition. It becomes eligible only when all of the following are supplied and approved:

- georeferenced real supply and return topology;
- pipe, pump, valve, substation, elevation and operating data;
- measured or approved demand profiles;
- calibrated baseline measurements;
- eligible connection locations and routing constraints;
- spatial geological/PyDoublet scenarios;
- land, planning, environmental and permitting constraints;
- approved cost sources, price year and decision policy.

If those data are absent, the system shall return `DATA_REQUIREMENTS_NOT_MET` or an equivalent typed pre-flight result. It shall not generate plausible-looking substitute data and shall not call a synthetic result “Wuppertal.”

### 4.3 Explicitly deferred features

The following are outside this completion release unless separately authorized:

- a Fred-style general conversational agent;
- a separate PyDoublet MCP server;
- production HTTP authentication and multi-tenant hosting;
- detailed equipment-manufacturer heat-exchanger design;
- full reservoir uncertainty calibration;
- steam-network conversion to approximately 80 °C;
- operational dispatch recommendations based on unapproved real data.

---

## 5. System architecture to preserve and extend

The implementation shall retain this authority chain:

```mermaid
flowchart TD
    Raw["PyDoublet raw result"] --> Provenance["Hash and provenance validation"]
    Provenance --> Parser["Typed PyDoublet parser"]
    Parser --> HX["Surface HX coupling"]
    HX --> Doublet["Reusable doublet component"]
    Data["Network/GIS data package"] --> Generator["Candidate generator"]
    Doublet --> Evaluation["Independent pandapipes evaluations"]
    Generator --> Evaluation
    Evaluation --> Gates["Technical gates"]
    Gates --> Economics["Economics and risk"]
    Economics --> Decision["Ranking or Pareto shortlist"]
    Decision --> Audit["Artifacts, manifest and audit"]
    MCP["Six-tool MCP server"] --> Provenance
    MCP --> Audit
```

### 5.1 Required separation of concerns

- Raw evidence identity must remain separate from normalized scientific identity.
- Brine-side quantities must remain separate from district-heating-side quantities.
- Network-connection location must remain separate from geological drilling location.
- Technical feasibility must be evaluated before economics.
- Deterministic computation must remain separate from LLM explanation.
- Exact evidence artifacts must remain separate from redacted publication copies.
- Real data must remain separate from synthetic demonstration fixtures.

---

## 6. Workstream A — repository baseline and governance

### GOV-001 Clean implementation baseline

Before feature work, Claude MUST:

1. verify the current branch, HEAD, remotes and nested repositories;
2. resolve or preserve all pre-existing dirty-worktree changes;
3. verify that T5.1C evidence commits are present;
4. ensure no evidence bundle is modified;
5. create a clean feature branch or isolated Git worktree;
6. record the starting commit in the implementation report.

### GOV-002 Branching and commits

Each workstream shall be implemented in a reviewable branch or series of small commits. Suggested branches:

- `feature/mcp-input-provenance-enforcement`
- `feature/persistent-run-registry`
- `feature/config-gates-shortfall`
- `feature/geothermal-doublet-component`
- `feature/candidate-generation`
- `feature/real-data-contracts`
- `feature/joint-location-optimization`

Claude MUST NOT force-push, rewrite published evidence history, stage unrelated files or modify nested repositories without explicit authorization.

### GOV-003 Decision register

Create or update a decision register containing:

- decision identifier;
- owner;
- status: `provisional`, `approved`, `rejected` or `superseded`;
- chosen value/policy;
- source and date;
- affected code/config fields;
- rerun implications.

At minimum, track Q4, Q5, Q6, Q7, Q8, Q9 and Q11 plus Dr. Jan’s outstanding PyDoublet semantic confirmations. Q9 is already decided as one-server integration.

### GOV-004 No silent scientific change

If an implementation changes any existing canonical technical/economic value, run ID, artifact hash or ranking, Claude MUST:

1. stop treating it as a refactor;
2. produce a before/after numerical diff;
3. identify the precise causal code/config change;
4. classify the change as intended, defect correction or unexplained;
5. obtain approval before rebaselining golden expectations.

---

## 7. Workstream B — exact input-provenance enforcement

### 7.1 Goal

Prevent a valid but unintended, truncated, retyped or previously preserved PyDoublet object from being presented as the canonical source fixture.

### IP-001 Expected hash field

Add an optional field named `expected_raw_sha256` to the appropriate provenance or validation contract.

- It must be a lowercase 64-character hexadecimal SHA-256 value.
- Its definition must explicitly state that it refers to `canonical_raw_result_sha256(raw_object)`, not necessarily the byte hash of the original JSON file.
- Existing callers that omit it must remain backward compatible.
- Strict acceptance configurations must supply it.

### IP-002 Authoritative calculation

The server shall independently compute the actual canonical raw-result hash from the complete received object before extracting fields. The server must not trust a client-supplied actual hash.

### IP-003 Mismatch behavior

When expected and calculated hashes differ, validation and workflow execution must stop before scientific parsing or network calculation and return a structured error:

- `status: "error"`
- `code: "PYDOUBLET_RAW_HASH_MISMATCH"`
- `stage: "input_provenance_validation"`
- `recoverable: true`
- message containing expected and calculated hashes;
- no silent normalization, substitution, fallback or retry.

If the existing repository error taxonomy requires another stable code, document the decision and use one code consistently across CLI, MCP, tests and documentation.

### IP-004 Audit record

Record:

- whether an expected hash was supplied;
- expected raw hash;
- calculated raw hash;
- verification result;
- canonicalization algorithm/version.

Do not record the same value as both a byte hash and scientific-equivalence hash unless that is demonstrably true.

### IP-005 Strict demonstration provenance

Provide a strict demonstration provenance input that pins the canonical repaired fixture hash:

`6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762`

Do not overwrite historical evidence or silently rebaseline the existing golden run. If adding the field to the existing demo provenance changes the provenance hash and run ID, either:

1. create a separately versioned strict provenance fixture; or
2. document and explicitly approve a golden-baseline migration.

The default choice should preserve the historical baseline and introduce a separately named strict provenance fixture.

### IP-006 Tests

Tests must cover:

- correct fixture plus correct expected hash succeeds;
- correct fixture plus wrong expected hash fails;
- previously hand-transcribed Run 1/Run 2 input plus canonical expected hash fails;
- malformed, uppercase, shortened and non-hex hash values fail schema validation;
- omitted expected hash preserves backward-compatible behavior;
- CLI and MCP return equivalent typed results;
- no workflow artifact directory is created after a mismatch;
- mismatch is present in the external/tool audit without exposing the entire raw input.

### IP-007 Security boundary

Do not add unrestricted arbitrary-file-path access to the MCP tool. If future file-based ingestion is introduced, it must use a configured allow-listed root, reject symlinks/path traversal and verify a caller-supplied expected hash.

---

## 8. Workstream C — persistent, restart-safe run registry

### 8.1 Goal

Allow `geo_get_run_summary`, `geo_get_audit` and `geo_get_artifact` to find a completed run after a normal MCP server restart.

### RR-001 Stable storage root

Replace the mandatory process-created temporary root with a configurable run root.

- Tests must inject temporary directories.
- Installed local use should default to an OS-appropriate application-data/state directory.
- `R3CHAIN_RUN_ROOT` or an equivalently documented setting may override the default.
- The resolved root must appear in server diagnostics without exposing it in public/redacted evidence unnecessarily.
- Normal server shutdown must not automatically delete completed runs.

### RR-002 Atomic publication

A completed run must be published by writing to a staging directory on the same filesystem, validating required files and hashes, then atomically renaming it to the final run directory.

Incomplete staging directories must never be returned as completed runs.

### RR-003 Startup rehydration

On startup, scan only direct child directories matching the run-ID pattern. For each candidate:

1. validate directory name and manifest schema;
2. ensure manifest run ID matches the directory;
3. check the required artifact inventory for its workflow status;
4. verify member hashes before registering it;
5. classify corrupt or incomplete bundles without crashing the server;
6. expose a warning/diagnostic count for skipped bundles.

### RR-004 Registry state model

Persist or reconstruct at least:

- run ID;
- workflow status;
- creation/completion timestamp;
- bundle directory;
- summary fields required by `geo_get_run_summary`;
- artifact inventory;
- last-access metadata if used for retention.

In-progress computations need not survive a process crash, but abandoned staging directories must be identifiable and safely cleanable.

### RR-005 Concurrency and deduplication

Retain same-run deduplication. Concurrent requests for the same run ID must not execute duplicate workflows or corrupt a completed bundle. Use process-safe locking if multiple server processes can share the root.

### RR-006 Retention

Retention must be explicit and configurable:

- maximum completed runs;
- maximum age, if enabled;
- deterministic eviction order;
- pinned/active-read protection;
- safe deletion limited to validated child run directories.

The default policy must be documented. A clean restart alone must not cause data loss.

### RR-007 Artifact safety

Artifact retrieval must retain its allow-list, offset/limit validation and path-traversal protection. It must never accept arbitrary paths relative to the run root.

### RR-008 Restart acceptance test

An automated integration test must:

1. start a server with a temporary persistent root;
2. run a complete workflow;
3. terminate the server cleanly;
4. start a new server process against the same root;
5. retrieve the summary and audit;
6. retrieve all pages of `workflow_result.json`;
7. reconstruct the bytes and verify the manifest hash;
8. confirm no new workflow computation occurred.

### RR-009 Error behavior

Use typed errors for:

- unknown run ID;
- corrupt manifest;
- missing artifact;
- unapproved artifact name;
- invalid pagination;
- temporarily locked/in-progress run.

Never silently regenerate a missing run when a read-only retrieval tool is called.

---

## 9. Workstream D — authoritative configuration and technical gates

### CFG-001 Configuration classification

Every configuration field must be classified as:

- executable and consumed;
- descriptive/audit-only;
- deprecated;
- unsupported.

An executable field must affect code through one typed resolved-config path. A descriptive field must not be presented as controlling behavior.

### CFG-002 Hash boundaries

Preserve both:

1. exact source-config identity; and
2. resolved executable-config identity.

Documentation-only text should not silently alter the scientific run identity unless the project deliberately retains that policy. Document the chosen boundary and schema version.

### CFG-003 Currently ignored gates

At minimum, resolve these known mismatches:

- `max_pump_dp_bar` must either be enforced or removed from executable configuration;
- heat-delivery tolerance must be enforced at the correct boundary or reclassified;
- configured geometry and candidate lists must become authoritative in configuration-driven mode or be clearly labelled descriptive;
- configured ranking and tie-break rules must drive the implementation or be removed from executable config.

### CFG-004 Gate order

The deterministic evaluation order shall be:

1. input/provenance validation;
2. PyDoublet semantic validation;
3. heat-exchanger feasibility;
4. blueprint/data validation;
5. baseline convergence and calibration gates;
6. candidate construction;
7. candidate convergence;
8. delivered-heat/capacity gate;
9. consumer-temperature gate;
10. pressure gate;
11. pump differential-pressure gate;
12. velocity gate;
13. mass-balance gate;
14. physical-energy-balance gate;
15. economics eligibility;
16. ranking or Pareto classification.

Each rejected candidate must retain the first primary failure plus optional secondary diagnostics. It must never receive a normal economic rank.

### CFG-005 Pressure semantics

Continue using explicit gauge-to-absolute conversion. Every threshold and output must carry its reference (`bar_g` or `bar_abs`). No bare `bar` field is acceptable at a public contract boundary.

### CFG-006 Backward-compatible synthetic mode

With the existing canonical configuration and current default policies, C1-C4 outputs must remain unchanged unless an approved defect correction intentionally changes them. Preserve a compatibility/golden test.

---

## 10. Workstream E — dispatch, shortfall and self-consistent flow

### DSP-001 Explicit shortfall policy

Implement a typed policy enum with at least:

- `auxiliary_supply`
- `strict_infeasible`

Unknown policy values must fail configuration validation.

### DSP-002 Auxiliary policy

Under `auxiliary_supply`:

- calculate geothermal heat accepted by the network;
- calculate the remaining thermal shortfall;
- supply only the allowed shortfall from the auxiliary source;
- include auxiliary energy and cost in candidate economics;
- expose geothermal available, delivered, curtailed and auxiliary heat separately;
- issue typed warnings when a numerical-stability reserve changes dispatch.

### DSP-003 Strict policy

Under `strict_infeasible`, a candidate is infeasible when geothermal/network-deliverable heat falls below required demand by more than the configured tolerance. Use a stable failure code such as `GEOTHERMAL_HEAT_SHORTFALL`.

Do not cost or rank a strict-mode infeasible candidate as though auxiliary supply were available.

### DSP-004 Numerical stabilization separation

Do not label the existing 1% main-plant circulation reserve as resource shortfall. Track separately:

- resource-limited shortfall;
- network-acceptance curtailment;
- deliberately retained auxiliary/stabilization heat;
- true surplus geothermal heat.

### DSP-005 Self-consistent district-heating flow

Replace the fixed design-return-temperature approximation with a bounded deterministic iteration or root solve:

1. initialize district-heating flow from the design temperature pair;
2. run the candidate network;
3. obtain the solved return temperature/enthalpy at the geothermal interface;
4. update flow so accepted heat equals the enthalpy rise to the supply target;
5. apply relaxation if required;
6. stop when heat and flow residual tolerances are met;
7. fail with a typed convergence code after the configured maximum iterations.

Record iteration count, initial/final flow, heat residual and convergence status. The algorithm must be deterministic.

### DSP-006 Stabilization sensitivity

Retain the existing 1% policy only as an explicit, configurable fallback until the self-consistent method proves that it can safely reach higher geothermal fractions. Compare at least 0%, 0.5%, 1% and 2% in a documented sensitivity test. Do not silently select a new physical policy from numerical convenience.

---

## 11. Workstream F — intentionally infeasible demonstration

### FAIL-001 Separate scenario

Add a clearly named workshop/negative-test configuration. Do not modify the canonical successful C1-C4 comparison merely to force a failure.

### FAIL-002 Deterministic failure

Include at least one candidate designed to fail exactly one primary gate under documented inputs. Suitable examples include:

- excessive connection pressure drop;
- undersized pipe causing excessive velocity;
- inadequate geothermal deliverable heat in strict mode;
- consumer temperature below threshold.

The chosen case must not depend on random solver behavior.

### FAIL-003 Evidence

The result, audit, CSV and recommendation must show:

- candidate ID and label;
- `feasible: false`;
- exact stable failure code;
- measured value, threshold, unit and pressure reference where applicable;
- exclusion from ranking;
- no invented LCOH recommendation.

### FAIL-004 Tests

Provide unit and end-to-end tests proving the failure remains stable and that successful candidates are unaffected.

---

## 12. Workstream G — reusable geothermal-doublet component

### 12.1 Design decision

For this prototype, implement a reusable **composite builder and result extractor** in the top-level orchestration repository. Do not modify pandapipes internals or the reference-only `pandapipesAI` checkout.

An upstream custom pandapipes component may be considered later through a separate ADR and upstream review.

### DLT-001 Component contract

Define immutable, extra-forbid models for at least:

- `GeothermalDoubletSpec`
- `HeatExchangerBoundary`
- `DistrictHeatingConnectionSpec`
- `DoubletOperatingPolicy`
- `GeothermalDoubletHandles`
- `GeothermalDoubletResult`

Names may follow repository conventions, but responsibilities must remain separated.

### DLT-002 Inputs

The component must receive explicit typed inputs for:

- producer wellhead temperature;
- brine mass flow;
- brine heat capacity or enthalpy method;
- raw geothermal thermal power;
- minimum reinjection temperature;
- HX minimum approach;
- delivery factor;
- production/doublet pump electricity from PyDoublet;
- district-heating supply target;
- return/supply connection nodes;
- connection pipe specifications;
- circulation-pump specification;
- accepted-heat/shortfall policy;
- flow-solver tolerances.

Every public quantity must carry a unit or unit-bearing field name.

### DLT-003 Network topology

The component shall construct the DH-side path using supported pandapipes primitives:

> return attachment → return connection → circulation pump → controlled heat injection → supply connection → supply attachment

The component must not pretend to model the underground brine loop inside the district-heating water network. Brine-side results enter through the coupling boundary.

### DLT-004 Isolation and idempotence

- Every candidate evaluation must build a fresh network or a demonstrably deep-isolated copy.
- Adding one doublet component must not mutate the reusable blueprint.
- Component names/IDs must be deterministic and collision-safe.
- Repeated evaluation with identical inputs must produce identical scientific outputs.

### DLT-005 Result extraction

Return at least:

- available geothermal heat;
- accepted/injected heat;
- curtailed heat, separated by cause;
- auxiliary heat;
- brine and DH mass flows;
- interface temperatures;
- connection differential pressure;
- circulation-pump hydraulic and electrical power;
- component convergence/iteration diagnostics;
- warnings and failure codes;
- pandapipes element handles for audit/debugging.

### DLT-006 Parity

When configured to match the existing synthetic implementation, the new component must reproduce C1-C4 results within declared numerical tolerances. Any deviation requires the GOV-004 process.

### DLT-007 Documentation

Provide a concise component guide with:

- physical boundary diagram;
- inputs and units;
- equations/algorithm references;
- limitations;
- one construction example;
- one result-extraction example;
- statement that it is a project composite, not necessarily an upstream pandapipes element.

---

## 13. Workstream H — automatic network-connection candidate generation

### CAN-001 Modes

Support both:

- `predefined`: backward-compatible explicit candidates;
- `generated`: deterministic candidates derived from the network/data package.

### CAN-002 Eligible attachments

Candidate generation must use explicit eligibility rules. It may consider:

- paired supply/return junctions;
- paired supply/return pipe tap points;
- allowed plant/connection parcels;
- exclusion zones;
- maximum route length;
- minimum pipe capacity or diameter;
- pressure-zone compatibility;
- construction/routing availability.

It must not connect arbitrary supply and return points merely because they are geometrically close.

### CAN-003 Stable identity

Generate stable candidate IDs from normalized study ID, supply attachment, return attachment, route ID and design-option ID. Stable IDs must not depend on iteration order or wall-clock time.

### CAN-004 Deterministic routing abstraction

Provide an interface with at least:

- declared/direct route length for synthetic mode;
- network-graph route length when a routing graph exists;
- external GIS route reference when an approved route is supplied.

Straight-line distance must never be labelled routed construction length.

### CAN-005 Screening

Before pandapipes solving, reject candidates with typed reasons for:

- missing supply/return pair;
- invalid pressure-zone pairing;
- route exceeding limit;
- excluded/protected geometry;
- missing pipe/design data;
- duplicate topology;
- component-construction conflict.

Preserve screened-out candidates in the audit.

### CAN-006 Design options

The generator should allow multiple connection diameters and pump options without conflating them with geographic locations. A candidate identity must distinguish location, route and design.

### CAN-007 Synthetic demonstration

Add a generated-mode synthetic example that:

- deterministically produces at least four valid candidates;
- includes or pairs with at least one screened/infeasible candidate;
- produces the same ordered set on repeated runs;
- clearly labels coordinates and routes as synthetic;
- does not replace the canonical predefined C1-C4 regression case.

---

## 14. Workstream I — real network, GIS and geological data contracts

### 14.1 Principle

Claude shall implement data contracts, validation and example packages. Claude shall not fabricate a real Wuppertal dataset. Actual data ingestion remains blocked until datasets and licences are supplied.

### DATA-001 Study package

Define a versioned study package with a manifest similar to:

```text
study-package/
  manifest.json
  provenance.json
  network/
    junctions.geojson
    pipes.geojson
    consumers.csv
    plants.json
    controls.json
    measurements.csv
  geography/
    candidate_sites.geojson
    routing_graph.geojson
    exclusion_zones.geojson
  geothermal/
    scenarios.json
  economics/
    assumptions.json
  decisions/
    policy.json
```

Equivalent names are allowed if documented and schema-versioned.

### DATA-002 Manifest

The manifest must contain:

- study ID and schema version;
- title and explicit `synthetic` or `real` classification;
- CRS identifier for every spatial layer;
- file inventory and SHA-256 hashes;
- data owners/sources;
- licence/use restrictions;
- creation and update dates;
- unit conventions;
- approval status;
- optional expected scenario hashes.

### DATA-003 Network requirements

Require, with typed validation:

- separate or explicitly typed supply/return topology;
- junction IDs, coordinates and elevations;
- pipe endpoints, lengths, internal diameters, material/roughness, insulation/U-value and status;
- pumps, valves, heat sources and pressure controls;
- consumer/substation IDs, design loads and return-temperature behavior;
- operating pressure and temperature limits;
- demand profile or explicit static-demo declaration;
- candidate tie-in eligibility.

### DATA-004 GIS requirements

- Spatial files must declare CRS; silent CRS guessing is prohibited.
- Geometry validity must be checked.
- Distances must be computed in a suitable projected CRS.
- Routes must distinguish straight-line, graph-routed and approved-engineering lengths.
- Land, roads, rail, waterways, utilities, protected areas and easements must be modelled as supplied constraints, not inferred by the LLM.

### DATA-005 Geological scenarios

Each scenario must include:

- scenario/site ID and geometry or parcel reference;
- PyDoublet input/result reference and hash;
- depth and temperature assumptions;
- mass-flow/transmissivity basis;
- fluid properties and salinity when relevant;
- reinjection constraints;
- well spacing/trajectory assumptions;
- production and injection pump requirements;
- uncertainty/risk metadata;
- calculation mode and upstream commit/model version.

### DATA-006 Economics and planning data

Every economic value must include:

- currency;
- price year;
- unit basis;
- source;
- approval status;
- uncertainty/range where available;
- inclusion/exclusion boundary.

Land, drilling, connection routing, road crossing, grid connection, permitting, exploration, workover, decommissioning and risk costs must remain separate line items.

### DATA-007 Validation policy

- Missing required data must fail with exact field/location information.
- No silent imputation is allowed in real mode.
- Explicit configured defaults may be used only when labelled and audited.
- Duplicate IDs, disconnected topology, impossible temperatures, invalid dimensions and inconsistent units must fail pre-flight.
- All transformations must be recorded with source and output hashes.

### DATA-008 Synthetic sample package

Provide a small fully licensed synthetic package exercising every schema. It must be unmistakably labelled `synthetic: true` and must not use real-place labels suggesting operational validity.

### DATA-009 Real-data readiness report

Generate a machine-readable and human-readable readiness report listing:

- supplied datasets;
- missing datasets;
- validation errors;
- provisional assumptions;
- unresolved approvals;
- whether connection optimisation is permitted;
- whether drilling-location optimisation is permitted.

---

## 15. Workstream J — combined site and connection optimisation

### 15.1 Goal

Create a transparent outer evaluation loop over geological/surface-site scenarios, network connection candidates, routes and design options. This is a bounded enumerative/filtered optimisation prototype, not an opaque AI-generated location decision.

### OPT-001 Decision entity

An alternative must be uniquely represented as:

`(geothermal_scenario_id, surface_site_id, connection_candidate_id, route_id, design_option_id, operating_policy_id)`

Never use one generic “location” field for all of these concepts.

### OPT-002 Evaluation stages

For every alternative:

1. validate data and provenance;
2. screen geological/site/route constraints;
3. calculate the PyDoublet/HX coupling boundary;
4. construct the reusable doublet connection;
5. run an independent network solve;
6. apply technical gates;
7. compute location-specific CAPEX/OPEX only if technically feasible;
8. attach risk/uncertainty metadata;
9. add the feasible result to the decision set;
10. retain all rejected alternatives and exact reasons.

### OPT-003 Objective policy

Technical feasibility is always first.

If approved weights and tie-breakers exist, deterministic ranking may be returned. If they do not exist, return a Pareto/non-dominated shortlist across explicitly configured objectives rather than inventing weights.

Supported objective fields should include, when data exist:

- annualized cost;
- indicative LCOH;
- geothermal heat delivered;
- auxiliary heat;
- pumping electricity;
- connection length/civil cost;
- drilling/site cost;
- technical margin;
- risk or success-probability metric;
- emissions metric.

Do not include an objective whose data/source are absent.

### OPT-004 Uncertainty

The prototype must accept deterministic scenarios. It should also support multiple named scenarios or samples without embedding uncertainty calculations in the LLM.

At minimum, report:

- result per scenario;
- feasibility frequency when comparable samples exist;
- range/quantiles only when calculated by deterministic code;
- sensitivity of the preferred/Pareto set to configured scenarios.

### OPT-005 Synthetic joint demonstration

Provide a deterministic demonstration containing:

- at least three explicitly synthetic geothermal/site scenarios;
- at least four generated network connection candidates;
- at least two design options or routes where practical;
- at least one geological/site screening failure;
- at least one hydraulic/thermal failure;
- at least two feasible alternatives;
- a deterministic ranked result if the synthetic policy defines weights, otherwise a Pareto shortlist.

The demonstration must clearly separate drilling/surface-site suitability from network connection suitability.

### OPT-006 Real-mode safeguard

Real mode must not run to a recommendation unless the readiness report permits it. If critical data or approvals are missing, return a stopped workflow with exact missing requirements.

### OPT-007 Outputs

Extended-mode artifacts shall include:

- `study_readiness.json`
- `generated_candidates.json`
- `screened_alternatives.json`
- `alternative_comparison.csv`
- `pareto_or_ranking.json`
- `location_shortlist.geojson` when spatial inputs exist;
- `recommendation.md` using decision-safe language;
- audit and manifest coverage for all files.

The existing synthetic connection-only bundle must remain backward compatible. Extended artifacts should be mode-specific.

---

## 16. MCP and orchestration requirements

### MCP-001 Preserve the six-tool public architecture

Keep these public tools unless an ADR explicitly approves a versioned change:

1. `geo_get_capabilities`
2. `geo_validate_pydoublet_result`
3. `geo_run_workflow`
4. `geo_get_run_summary`
5. `geo_get_audit`
6. `geo_get_artifact`

New functionality should normally be selected through typed optional workflow inputs/configuration and advertised through capabilities, rather than casually adding tools and breaking T5.1C clients.

### MCP-002 Capabilities

Advertise:

- server/tool contract version;
- supported workflow modes;
- supported data-package schema versions;
- provenance-hash enforcement support;
- persistent-registry support;
- available shortfall policies;
- candidate-generation modes;
- maximum artifact page size;
- exact architecture disclaimer.

### MCP-003 Tool behavior

- Tool outputs must remain structured and bounded.
- Long artifacts must remain paginated.
- Read-only retrieval tools must never trigger workflow computation.
- Validation must not publish a successful run bundle.
- `geo_run_workflow` must be deterministic for identical inputs/configuration.
- Every error must carry code, message, stage and recoverability.
- Warnings must never be silently dropped.

### MCP-004 External orchestration transcript

Provide an optional client-side session record containing:

- timestamp;
- tool name;
- sanitized arguments or argument hashes;
- run ID;
- status/error code;
- pagination offsets;
- response hash where practical.

This external transcript complements but does not replace the internal workflow audit.

### MCP-005 Installed-client acceptance

After relevant MCP changes, repeat a clean installed-package smoke test and a live Claude Desktop test. Do not repeat the 17-page demonstration after every internal refactor; require it at the final release candidate.

---

## 17. Audit, artifacts and reproducibility

### AUD-001 Identity layers

Maintain distinct identifiers for:

- original file bytes, when available;
- canonical raw JSON object;
- normalized scientific input;
- resolved executable configuration;
- source provenance;
- workflow/run contract version;
- artifact bytes;
- scientific artifact content.

Document which identifiers are representation-sensitive.

### AUD-002 Scientific-equivalence policy

Do not simply change existing hashes so `35` and `35.0` collide. Define a versioned normalization policy with explicit scope. At minimum:

- preserve an immutable exact raw evidence hash;
- define whether numeric normalization is allowed for the scientific hash;
- never delete or ignore structurally different arrays merely because the current parser does not consume them;
- record normalization version in the audit;
- provide collision and regression tests.

### AUD-003 Manifest

The manifest must list every published member with byte hash, scientific hash where applicable, size and media type. The bundle digest must avoid self-reference and use a documented deterministic order.

### AUD-004 Recommendation safety

Every recommendation must state:

- study mode and synthetic/real classification;
- exact scenario and candidate scope;
- feasibility basis;
- provisional assumptions and warnings;
- whether the output ranks connection points, surface sites or drilling alternatives;
- that no excluded dimension was optimized.

### AUD-005 Historical evidence

Do not rewrite old manifests, bundles or transcripts after implementation changes. New runs receive new evidence directories and refer back to the software commit used.

---

## 18. Non-functional requirements

### NFR-001 Determinism

Identical validated inputs, configuration, provenance and contract version must produce identical scientific results and deterministic ordering. Wall-clock timestamps may differ but must be excluded only through an explicit scientific-hash policy.

### NFR-002 Offline testability

All unit, integration, contract and end-to-end tests must pass without network access and without real Wuppertal data.

### NFR-003 Type safety

Public and inter-layer contracts must use immutable, extra-forbid typed models. Units must appear in field names or dedicated quantity types.

### NFR-004 Failure transparency

No broad exception may be converted into a generic success or empty recommendation. Candidate failures and workflow-stopping failures must remain distinguishable.

### NFR-005 Security

- no arbitrary MCP filesystem reads;
- no path traversal;
- no secret/token logging;
- no dynamic code execution from study packages;
- bounded file sizes and candidate counts;
- safe archive extraction if archives are supported;
- explicit allow-list for artifact retrieval;
- no use of untrusted pickle or executable serialization.

### NFR-006 Performance and resource bounds

Expose configured bounds for:

- maximum candidates;
- maximum scenario combinations;
- maximum iterations;
- artifact size/page size;
- run retention;
- concurrent workflows.

When a bound is exceeded, return a typed error. Do not silently sample or drop alternatives.

### NFR-007 Compatibility

The canonical predefined C1-C4 CLI and MCP workflow must remain available. Any public schema change requires a contract-version increment and migration notes.

### NFR-008 Documentation

A colleague must be able to install and reproduce the synthetic prototype from the README alone, including MCP configuration, exact input files, expected warnings and acceptance commands.

### NFR-009 Licensing and provenance

Record the origin/licence of all imported data and code. Do not commit restricted real datasets or modify reference repositories in a way that obscures upstream provenance.

---

## 19. Required test strategy

### 19.1 Test layers

Every workstream must add tests at the appropriate levels:

1. **Unit:** contracts, validators, hash checks, gates, routing and objective logic.
2. **Property/invariant:** stable IDs, non-negative energy partitions, conservation, deterministic ordering and no feasible candidate with a failed hard gate.
3. **Integration:** parser → HX → component → network → economics.
4. **Contract:** CLI/MCP equivalence, typed errors, warnings and schema versions.
5. **Restart:** persisted registry and paginated artifact retrieval after a new process starts.
6. **End-to-end:** canonical C1-C4, negative workshop case, generated candidates and synthetic joint optimisation.
7. **Packaging:** clean wheel/install, no repository-relative hidden dependency.

### 19.2 Mandatory invariants

- `available_heat >= accepted_heat >= 0`
- `curtailed_heat >= 0`
- `auxiliary_heat >= 0`
- heat-partition residual is within configured tolerance;
- infeasible candidates are excluded from ranking;
- exact same alternative is not evaluated twice;
- candidate results do not depend on evaluation order;
- pressure reference is explicit;
- no real-mode recommendation when readiness is false;
- every artifact listed in the manifest exists and hashes correctly;
- complete pagination reconstructs the exact artifact bytes.

### 19.3 Regression baseline

The starting baseline is 838 passing tests. New tests should increase the collected count. A reduction or skipped/xfailed test requires explicit justification. No test may be weakened merely to preserve a desired result.

### 19.4 Numerical tolerances

Every approximate comparison must document:

- absolute and/or relative tolerance;
- physical rationale;
- units;
- whether it applies to solver convergence, gate acceptance or regression reporting.

Do not use one global tolerance for unrelated physical quantities.

---

## 20. Acceptance scenarios

### AC-01 Canonical backward-compatible run

Given the existing canonical repaired PyDoublet fixture and canonical synthetic configuration:

- validation succeeds;
- C1-C4 are evaluated independently;
- existing expected ranking remains C1, C2, C3, C4 unless an approved correction changes it;
- audit and manifest verify;
- CLI and MCP scientific results agree.

### AC-02 Exact provenance mismatch

Given a hand-transcribed/reused raw result and the canonical expected raw hash:

- validation stops with `PYDOUBLET_RAW_HASH_MISMATCH` or the approved equivalent;
- expected and actual hashes are reported;
- no workflow solve or successful bundle occurs.

### AC-03 Restart recovery

Given a completed run and a clean MCP server restart:

- summary, audit and all artifacts remain retrievable by the same run ID;
- full pagination terminates with `next_offset: null`;
- the reconstructed file matches the manifest;
- no recomputation occurs.

### AC-04 Auxiliary shortfall

Given a deliberately reduced geothermal resource and `auxiliary_supply`:

- shortfall is supplied and costed;
- energy partitions reconcile;
- the candidate may remain feasible if all other gates pass;
- the recommendation reports the dependency on auxiliary heat.

### AC-05 Strict shortfall

With the same reduced resource and `strict_infeasible`:

- the candidate fails with the stable shortfall code;
- it receives no normal rank;
- no auxiliary heat is silently introduced.

### AC-06 Intentionally infeasible network candidate

Given the negative workshop candidate:

- it fails the designed primary gate deterministically;
- value, threshold, unit and failure code are recorded;
- other candidates remain independently evaluable.

### AC-07 Reusable component parity

Given C1-C4 represented using the reusable component:

- results match the approved legacy implementation within declared tolerances;
- no cross-candidate network mutation occurs.

### AC-08 Generated candidates

Given the synthetic network and generation rules:

- the generator returns the same stable candidate set and IDs on every run;
- invalid/duplicate options are screened with reasons;
- every accepted candidate can be constructed and evaluated independently.

### AC-09 Invalid real-data package

Given a package missing CRS, pipe diameter or provenance:

- pre-flight stops with exact typed errors;
- no solver or recommendation runs;
- missing items appear in the readiness report.

### AC-10 Synthetic joint optimisation

Given the complete synthetic spatial study package:

- all combinations are enumerated or transparently screened;
- technical failures remain separate from economic results;
- at least two alternatives are feasible;
- the system returns the configured deterministic ranking or Pareto shortlist;
- the report explicitly says the result is synthetic.

### AC-11 Live MCP release candidate

From an installed package and live Claude Desktop session:

- all six tools are available;
- strict hash verification succeeds with the intended input;
- the workflow completes;
- summary and audit are retrieved;
- mandatory artifacts are paginated completely;
- the transcript and server log agree;
- a restart then demonstrates retrieval of the same run.

---

## 21. Implementation phases and exit gates

### Phase 0 — clean baseline

Deliverables:

- reconciled dirty worktree;
- pushed/available evidence commits if authorized;
- clean feature-work base;
- baseline test report.

Exit gate: no unexplained overlapping change remains.

### Phase 1 — input provenance

Implement Workstream B and AC-02.

Exit gate: intended canonical object succeeds; known drifted objects fail when strict expected hash is supplied; backward compatibility remains tested.

### Phase 2 — persistent registry

Implement Workstream C and AC-03.

Exit gate: a new server process retrieves the original run without recomputation.

### Phase 3 — configuration, gates, shortfall and failure demo

Implement Workstreams D-F and AC-04 through AC-06.

Exit gate: every executable gate is wired, strict/auxiliary behavior differs correctly, and the negative demonstration is stable.

### Phase 4 — reusable doublet component

Implement Workstream G and AC-07.

Exit gate: component parity and isolation pass; legacy duplicate construction logic is removed only after parity is proven.

### Phase 5 — automatic candidate generation

Implement Workstream H and AC-08.

Exit gate: deterministic generated-mode demonstration passes while predefined mode remains compatible.

### Phase 6 — real-data contracts and readiness

Implement Workstream I and AC-09.

Exit gate: complete synthetic package validates; intentionally incomplete real package fails safely; no real data are fabricated.

### Phase 7 — synthetic joint optimisation

Implement Workstream J and AC-10.

Exit gate: audited synthetic site/connection/design shortlist is produced with explicit failures and no unsupported real-world claim.

### Phase 8 — real Wuppertal application (external-data gated)

Do not start until real data and approvals are supplied. Activities then include:

- data licensing/provenance review;
- import and QA;
- baseline calibration;
- candidate-generation review with network/domain owners;
- geological scenario review with PyDoublet/domain owners;
- approved economics and ranking policy;
- sensitivity/uncertainty analysis;
- decision workshop and qualified shortlist.

Exit gate: domain owners sign off data, assumptions, calibration and decision wording.

### Phase 9 — release acceptance

- run the entire offline suite;
- build/install the package in a clean Python 3.11 environment;
- execute all acceptance scenarios;
- complete AC-11;
- generate a final traceability matrix;
- archive logs, transcripts, bundle hashes and commit IDs;
- update README and architecture diagrams.

---

## 22. Required deliverables

### 22.1 Source and tests

- provenance enforcement;
- persistent registry/rehydration;
- resolved configuration models;
- complete gates and dispatch policies;
- self-consistent flow solver;
- negative demonstration;
- reusable doublet component;
- candidate generator;
- study-package schemas and validators;
- joint alternative evaluator;
- unit/integration/contract/restart/end-to-end tests.

### 22.2 Configuration and fixtures

- backward-compatible canonical synthetic configuration;
- strict hash-pinned provenance fixture;
- negative workshop configuration;
- generated-candidate synthetic configuration;
- fully synthetic spatial study package;
- deliberately invalid packages for validation tests.

### 22.3 Documentation

- updated README reproduction path;
- configuration reference distinguishing executable/descriptive fields;
- doublet component guide;
- study-package schema guide;
- candidate-generation rules;
- registry retention/recovery guide;
- decision register;
- updated ADRs where architecture changes;
- data requirements/readiness checklist;
- final requirements traceability matrix;
- explicit prototype-versus-real-study statement.

### 22.4 Evidence

- exact commands and environment;
- Git commit IDs and dirty-state records;
- test counts and durations;
- golden/scientific diffs for approved changes;
- restart-recovery evidence;
- final live MCP transcript;
- complete paginated artifact ledger;
- manifest and bundle hashes;
- warnings and known limitations.

---

## 23. Stop conditions and escalation rules

Claude MUST stop and request direction when:

1. the worktree contains unexplained overlapping user changes;
2. a scientific result changes without an identified approved cause;
3. implementation requires changing PyDoublet physics;
4. implementation requires modifying `pandapipesAI` or another nested repository;
5. a real dataset is unavailable, unlicensed or lacks provenance;
6. a required Tanja/Dr. Jan policy decision materially changes behavior;
7. ranking requires weights that have not been approved;
8. a full test run fails or loses tests unexpectedly;
9. a migration would invalidate historical evidence;
10. security would require unrestricted filesystem or network access;
11. solver convergence can only be obtained by hiding or relaxing a gate;
12. real-mode readiness is false.

Claude may continue independently when the change is covered by this specification, backward compatible, deterministic, tested and does not cross one of these boundaries.

---

## 24. Definition of done

### 24.1 Completed research prototype

The prototype may be declared complete when Phases 0-7 and 9 pass and all of the following are true:

- strict input provenance is available;
- runs survive server restarts;
- every executable gate is real;
- auxiliary and strict shortfall modes work;
- an intentionally infeasible candidate is demonstrated;
- the reusable doublet component has parity evidence;
- candidates can be generated deterministically;
- the real-data contract and readiness checks exist;
- a synthetic joint site/connection optimisation demonstration passes;
- the six-tool MCP interface and CLI remain operational;
- all tests pass offline;
- documentation accurately limits the claims.

### 24.2 Completed real Wuppertal study

The real study is complete only after Phase 8 also passes with approved real data. Code completion alone cannot satisfy this definition.

### 24.3 Prohibited completion claims

Do not state any of the following unless Phase 8 has passed:

- “the best geothermal location in Wuppertal”;
- “the recommended drilling site”;
- “the real network is feasible”;
- “the economics are validated”;
- “C1 is the best real-world location.”

Permitted prototype wording:

> The system demonstrates a deterministic, auditable method for validating geothermal scenarios, generating and evaluating district-heating connection alternatives, and producing a technically screened ranking or Pareto shortlist. Its current demonstrations use synthetic network and spatial data; real location conclusions require approved real datasets and domain-owner decisions.

---

## 25. Claude Code operating procedure

For every phase, Claude shall:

1. read this specification, applicable issue document, ADRs and current code;
2. report the exact baseline and affected modules;
3. identify assumptions and potential golden-output impact;
4. create or use a clean isolated branch/worktree;
5. implement the smallest coherent vertical slice;
6. add failing tests first where practical;
7. run targeted tests;
8. run the complete offline suite;
9. inspect `git diff --check` and staged files;
10. commit only the phase’s files with a focused message;
11. update traceability and documentation;
12. report results, deviations, warnings and next phase;
13. stop before pushing unless the user explicitly authorizes a push.

Claude must not mark a phase complete from code inspection alone. Each exit gate requires executable evidence.

---

## 26. Required final report format

At the end of each phase, report:

1. **Phase and verdict:** PASS, PARTIAL, FAIL or BLOCKED.
2. **Implemented requirements:** IDs and files.
3. **Tests:** exact commands, counts, failures/skips and duration.
4. **Scientific impact:** unchanged or exact before/after diff.
5. **Artifacts/evidence:** paths and hashes.
6. **Git:** branch, starting/ending commit, commits created and remaining dirty files.
7. **Warnings and limitations:** verbatim codes and concise meaning.
8. **External decisions/data:** resolved and still required.
9. **Next phase:** recommended action only; do not begin unless within the same authorized scope.

The final release report must contain a row for every requirement in this document and must not collapse PARTIAL/BLOCKED items into PASS.

---

## Appendix A — provisional scientific and policy values

These values describe the current demonstration and are not automatically approved design values:

| Assumption | Current value | Status |
|---|---:|---|
| DH supply/return | 70/40 °C | Provisional Q4 |
| Minimum HX approach | 5 K | Provisional Q5 |
| Reinjection minimum | 35 °C | Pending PyDoublet/domain confirmation |
| HX delivery factor | 0.98 | Demo assumption |
| Auxiliary/stabilization reserve | 1% demand | Numerical policy, not validated plant requirement |
| Minimum network pressure | 1.5 bar absolute | Provisional Q11 |
| Maximum velocity | 1.5 m/s | Demo gate |
| Mass-balance tolerance | 0.5% | Demo gate |
| Energy-balance tolerance | 2% | Demo gate |
| Maximum pump differential pressure | 6 bar | Configured but previously unenforced |
| Full-load hours | 5,000 h/a | Static simplification |
| DH pump efficiency | 70% | Placeholder |
| Doublet CAPEX | EUR 8.0 million | Placeholder Q7 |
| HX CAPEX | EUR 150,000 | Placeholder Q7 |
| Connection CAPEX | EUR 1,000/m paired trench | Placeholder Q7 |
| Fixed O&M | 2% CAPEX/a | Placeholder Q7 |
| Electricity | EUR 0.25/kWh | Placeholder Q7 |
| Auxiliary heat | EUR 0.09/kWh | Placeholder Q7 |

Changing one of these values requires a new configuration identity and sensitivity/result comparison.

---

## Appendix B — minimum real-data request to project partners

Request from the district-heating/network owner:

- georeferenced supply/return network export;
- pipe inventory and thermal properties;
- elevations and pressure zones;
- plants, pumps, valves and controls;
- consumer/substation design and time-series demand;
- measured pressure, flow and temperature for calibration;
- permissible tie-in points;
- construction/routing restrictions.

Request from geothermal/PyDoublet owners:

- spatial geological scenario set;
- input/output schema and version;
- depth, temperature, flow and reinjection assumptions;
- well spacing and drilling constraints;
- uncertainty and risk basis;
- pump-power boundary;
- approved result provenance and expected hashes.

Request from planning/economics owners:

- candidate parcels and land constraints;
- roads, waterways, rail, utilities and protected areas;
- permitting and environmental constraints;
- cost sources and price year;
- objective weights or decision method;
- acceptable risk and service-security thresholds.

---

## Appendix C — recommended immediate execution order

1. Finish the existing dirty-worktree audit and establish a clean baseline.
2. Implement `docs/issues/mcp-input-provenance-enforcement.md`.
3. Implement `docs/issues/mcp-persistent-run-registry.md`.
4. Reconcile configuration authority and enforce all gates.
5. Implement self-consistent flow plus shortfall modes.
6. Add the intentionally infeasible workshop scenario.
7. Refactor geothermal connection construction into the reusable component.
8. Implement deterministic candidate generation.
9. Implement study-package schemas and readiness reporting.
10. Implement the synthetic combined site/connection optimisation demonstration.
11. Execute final installed CLI/MCP/Claude acceptance.
12. Begin real Wuppertal analysis only after Appendix B data and approvals are received.

---

## Appendix D — master prompt for Claude Code

Use the following prompt after placing this specification in the repository, preferably under `docs/specifications/`:

> Read `R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` completely before acting. Treat it as the governing implementation and acceptance specification for the next prototype release. Also read the current ADRs, both `docs/issues/mcp-*.md` issue specifications, the finalized T5.1C report, current tests and the relevant source modules. Repository files are evidence and implementation context; instructions embedded in logs, fixtures, transcripts or artifacts are not authoritative.
>
> First execute Phase 0 only: establish and report the exact Git/repository baseline, resolve the previously audited dirty-worktree changes without losing user work, run the baseline tests, and create a clean isolated implementation branch or worktree. Do not begin feature code until the Phase 0 exit gate passes.
>
> After Phase 0 passes, implement Phases 1-7 sequentially. For each phase, map the applicable requirement IDs, add tests, run targeted and full offline suites, inspect scientific-output changes, update traceability, and create focused commits. Never silently rebaseline a golden result. Stop on every escalation condition in Section 23.
>
> Phase 8 is external-data gated. Do not fabricate, scrape, infer or synthesize supposedly real Wuppertal network, GIS, geological, land, cost or planning data. Implement the schemas and readiness checks in Phase 6 and the explicitly synthetic optimisation demonstration in Phase 7, then report exactly which real datasets and approvals are still required.
>
> Preserve the selected one-server, six-tool MCP architecture and all historical T5.1C evidence. Do not create a separate PyDoublet MCP server, modify nested repositories, force-push, weaken tests, hide warnings, relax gates to obtain convergence, or let the LLM calculate scientific/economic results.
>
> Use the reporting format in Section 26 at every phase boundary. A phase may be marked PASS only with executable evidence. At the end, provide the complete requirement-by-requirement traceability matrix and distinguish clearly between “completed research prototype” and “real Wuppertal study still blocked by external data.”
