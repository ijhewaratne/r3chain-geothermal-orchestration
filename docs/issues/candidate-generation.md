# Issue: deterministic network-connection candidate generation (CAN-001..007)

**Status**: **implemented** (2026-09-03, `feature/candidate-generation`,
`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Phase 5 / Workstream H, AC-08). See
`docs/decisions/decision-register.md` (IMPL-011).

## What this closes

CAN-001 (predefined/generated modes), CAN-002 (explicit eligibility rules), CAN-003 (stable
identity), CAN-004 (routing abstraction), CAN-005 (typed screening, audited), CAN-006 (design axis
distinct from location/route), CAN-007 (synthetic demonstration), AC-08.

## Design

`network/candidate_generation.py::generate_candidates()` is entirely additive — `config/
demo_assumptions.json`'s own four predefined C1-C4 candidates and `run_workflow()`'s existing
orchestration are completely untouched. Eligible attachments (CAN-002) are the four trunk junctions
(`trunk_1`..`trunk_4`, C1-C4's own attachment points — reusing their exact approved distances) and
the four consumer junctions (a NEW, explicitly synthetic attachment class this generator adds).
Two route options ("direct" ×1.0, "diverted" ×1.5) and one design option ("standard", the project's
existing fixed connection DN) give each attachment multiple candidate identities, distinguishing
location/route/design per CAN-006.

## Deterministic demonstration (CAN-007), measured

Against the canonical `build_default_blueprint()`: **16 candidates generated, 11 accepted, 5
rejected**, identical on every call:

- 4 trunk attachments × 2 routes = 8 accepted (all pass the FULL technical gate suite when
  evaluated — one, `trunk_1-direct`, is numerically IDENTICAL to the predefined `C1` candidate,
  verified directly).
- 3 consumer attachments (`consumer_1/2/3`) × "direct" route = 3 accepted, but **fail
  `VELOCITY_LIMIT_EXCEEDED` when evaluated** — a genuine technical finding, not a test defect: their
  DN100 branch pipes are sized only for consumer demand and cannot also carry the injection flow.
  This cleanly demonstrates CAN-005's pre-solve screening and CFG-004's post-solve gates as
  deliberately separate concerns (AC-08 requires only that every accepted candidate CAN be
  constructed and evaluated, not that it is technically feasible).
- 3 consumer attachments × "diverted" route = 3 rejected, `ROUTE_LENGTH_EXCEEDS_LIMIT` (300 m > the
  250 m `GENERATION_MAX_ROUTE_LENGTH_M` limit).
- 1 excluded consumer (`consumer_4`, `GENERATION_EXCLUDED_ATTACHMENT_ID`) × 2 routes = 2 rejected,
  `EXCLUDED_PROTECTED_GEOMETRY` — a synthetic protected-zone example.

## CAN-005's seven reason codes: which ones this generator's own output reaches

`ROUTE_LENGTH_EXCEEDS_LIMIT` and `EXCLUDED_PROTECTED_GEOMETRY` occur naturally on the canonical
demonstration (above). The other five are implemented and directly tested but do not occur on the
canonical blueprint/default arguments — this synthetic network has exactly one pressure zone and
one fixed pipe DN throughout, so pressure-zone and pipe-data checks have nothing to reject in
practice:

- `MISSING_SUPPLY_RETURN_PAIR` — reachable through `generate_candidates()` itself, given a
  deliberately broken blueprint (a junction removed).
- `MISSING_PIPE_OR_DESIGN_DATA` — reachable through `generate_candidates()` itself, given
  `connection_pipe_dn_mm<=0`.
- `DUPLICATE_TOPOLOGY` — reachable through `generate_candidates()` itself, given a monkeypatched
  route-multiplier table that collapses two distinct routes to the same resolved length.
- `INVALID_PRESSURE_ZONE_PAIRING`, `COMPONENT_CONSTRUCTION_CONFLICT` — genuinely unreachable by
  this generator's own loop structure (attachment × route enumeration structurally guarantees
  unique candidate IDs; there is no pressure-zone concept in this synthetic network at all) — proven
  only at the type level (`ScreenedCandidate` accepts and round-trips them correctly), documented
  as such rather than silently left untested.

## Routing abstraction (CAN-004)

Only `RouteOption.kind == "synthetic_direct"` is implemented. `"network_graph"` and `"external_gis"`
are declared enum members (the interface CAN-004 asks for) but `resolve_length_m()` raises
`NotImplementedError` for either — a straight-line distance is never silently mislabelled as a
routed construction length, and a routing graph or an approved external route reference is
Workstream I's own concern, not fabricated here.

## Update (2026-09-03, `feature/complete-synthetic-prototype`, Phase 3.2): wired into `run_workflow()`

`workflow/core.py::_apply_candidate_mode()` now reads `config["candidates"]["mode"]` (default
`"predefined"`, absent from the canonical config so its behavior/hashes are completely unaffected —
same established pattern as the workshop-negative-demo feature) and, when set to `"generated"`,
REPLACES `blueprint.candidates` with this module's own `generate_candidates()` ACCEPTED output,
each converted via `GeneratedCandidateSpec.to_blueprint_candidate()`. Evaluated through the exact
same `evaluate_candidate()` pathway as every predefined candidate — no new evaluation code. Reachable
through `geo_run_workflow` by pointing the (one-server-architecture) MCP server's fixed config at a
config file with `candidates.mode=="generated"` (`R3CHAIN_MCP_CONFIG_PATH`), exactly how the existing
workshop-negative-demo config is exercised via MCP — no seventh tool, no new tool parameter.
`config/demo_assumptions_generated_candidates.json` demonstrates this, reproducing the exact
measured 11-accepted/8-feasible/3-`VELOCITY_LIMIT_EXCEEDED` breakdown above through the full
workflow (`tests/workflow/test_generated_candidates.py`, 14 tests). Also adds
`candidates.generated.max_candidates` (optional cap, deterministic — takes the first N by the
already-sorted candidate-id order `generate_candidates()` itself returns) and a loud
`ValueError`/`WorkflowConfigurationError` when generation accepts zero candidates, rather than
silently producing an empty ranking.

## Not covered by this issue

- A second, differently-sized `DesignOption` is not constructable — `network/candidate.py`'s own
  evaluator reads the project-wide `CONNECTION_PIPE_DN_MM` constant, not a per-candidate DN; a
  generated candidate's own `connection_pipe_dn_mm` is recorded but not yet consumed by the physics
  evaluator (documented explicitly in `_apply_candidate_mode`'s own docstring and in
  `config/demo_assumptions_generated_candidates.json`'s own note). Extending that is a
  scientific-assumption change (plan §10.1, "fixed pipe diameters across candidate evaluations")
  requiring separate approval, out of proportion to this workstream.
- Workstream I (DATA-001..009, real-data contracts and readiness) is not part of this issue.

## Tests

`tests/network/test_candidate_generation.py` (24 tests): eligible-attachment coverage and
exclusion; the exact 16/11/5 breakdown; determinism; sorted, stable IDs; exact rejection
detail/reason for both naturally-occurring reasons; AC-08's full independent-evaluation proof
(including the `trunk_1-direct` == `C1` numerical-identity check); reachability for the three
generator-triggerable-but-not-naturally-occurring reasons; type-level proof for the two genuinely
unreachable reasons; model validation. Full offline suite: 962 passed (was 938), 0 failed.
