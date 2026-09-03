# Geothermal doublet connection component guide (DLT-007)

`src/r3chain_geothermal/network/doublet_component.py`

## What this is, and what it is not

This is a **project composite** — a builder and result-extractor implemented in this orchestration
repository, on top of standard pandapipes primitives (`create_pipe_from_parameters`,
`create_pump_from_parameters`, `create_heat_consumer`). It is **not** a native upstream pandapipes
component, does not modify pandapipes internals, and does not touch the reference-only
`repos/pandapipesAI` checkout. A native upstream component may be considered later through a
separate ADR and upstream review — nothing here should be read as claiming that status today.

It exists to give `network/candidate.py::evaluate_candidate()`'s own already-validated geothermal
injection topology a reusable, independently typed, independently documented contract
(`R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md` Workstream G, DLT-001..007), for future
orchestration re-use — without touching `evaluate_candidate()`'s own code. See
`docs/issues/geothermal-doublet-component.md` for why the two are not (yet) merged into one code
path, and the parity evidence proving that decision doesn't cost any correctness today.

## Physical boundary

```
                    (network-wide return side, one candidate's own return_junction)
                                    │
                          return connection pipe
                          (length = candidate's surface_connection_length_m,
                           DN = CONNECTION_PIPE_DN_MM, both fixed per plan §10.1)
                                    │
                              geo_return junction
                                    │
                       circulation pump (flat lift curve,
                       lift = blueprint.circulation_pump.pressure_lift_bar)
                                    │
                               geo_mid junction
                                    │
                    controlled heat injection (heat_consumer,
                    qext_w = -accepted_heat_kw*1000, controlled_mdot_kg_per_s)
                                    │
                              geo_supply junction
                                    │
                          supply connection pipe
                          (same length/DN as the return connection pipe)
                                    │
                    (network-wide supply side, the SAME candidate's supply_junction)
```

This is the district-heating WATER side only. The underground brine loop is never modelled inside
this network — brine-side facts (`GeothermalDoubletSpec`) enter only through the already-computed
heat-exchanger coupling boundary (`HeatExchangerBoundary`, T2.1's `HeatExchangerCouplingResult`).
Brine mass flow and DH-water mass flow are always independently derived quantities (CLAUDE.md);
this component never uses one to compute the other.

## Inputs and units (DLT-002)

| Model | Field | Unit |
|---|---|---|
| `GeothermalDoubletSpec` | `producer_wellhead_temperature_c` | °C |
| | `brine_mass_flow_kg_s` | kg/s |
| | `brine_specific_heat_capacity_j_kg_k` | J/(kg·K) |
| | `raw_geothermal_thermal_power_kw` | kW |
| | `minimum_reinjection_temperature_c` | °C |
| | `doublet_pump_electric_power_kw` | kW (electrical, PyDoublet's own figure) |
| `HeatExchangerBoundary` | `minimum_hx_approach_k` | K |
| | `hx_heat_delivery_factor` | dimensionless fraction, (0, 1] |
| | `deliverable_geothermal_heat_kw` | kW |
| `DistrictHeatingConnectionSpec` | `candidate` | (`BlueprintCandidate` — junctions + m) |
| | `dh_supply_temperature_c` / `dh_return_temperature_c` | °C |
| | `dh_water_specific_heat_capacity_j_kg_k` | J/(kg·K) |
| `DoubletOperatingPolicy` | `accepted_heat_kw` | kW — the DECIDED injection amount |
| | `injection_sizing_policy` | `"fixed_design_temperature"` \| `"self_consistent"` |
| | `outlet_temperature_tolerance_k`, `mass_flow_residual_tolerance_fraction`, `max_iterations` | solver tolerances (must equal `network.candidate`'s own named constants in this version) |

## Equations / algorithm references

- Injection mass flow (`"fixed_design_temperature"`): `m = Q / (cp * (T_supply - T_return))` using
  the DESIGN return temperature — `network/candidate.py::_compute_injected_mass_flow_kg_s()`.
- Injection mass flow (`"self_consistent"`, DSP-005): a bounded bisection root solve against the
  branch's own SOLVED return temperature — `network/candidate.py::_solve_self_consistent_injection()`.
  See `docs/issues/self-consistent-flow-solver.md` for why bisection was chosen over the literally-
  worded damped fixed-point iteration.
- Connection differential pressure: sum of the two connection pipes' own absolute-pressure drops
  (`network/pressure.py::to_absolute_bar()` throughout — gauge/absolute conversion is never done
  inline).

## Isolation and idempotence (DLT-004)

Every call builds a fresh `pandapipesNet` from the supplied `NetworkBlueprint` (never a shared or
cached net) and never mutates the blueprint itself (a frozen Pydantic model in any case). Repeated
calls with identical inputs produce identical scientific outputs — see
`tests/network/test_doublet_component.py::test_repeated_calls_are_bit_identical` and
`test_evaluating_multiple_candidates_does_not_cross_contaminate`.

## Limitations

- This component's own failure surface covers only what is intrinsic to ONE connection's own
  construction and flow-sizing (pandapipes non-convergence, its own hydraulic conflict, and
  self-consistent-solve non-convergence). Network-wide gates — consumer temperature, absolute
  pressure, pipe velocity, mass balance, physical energy balance — are NOT evaluated here; they
  remain `network/candidate.py::evaluate_candidate()`'s own responsibility, applied after this
  component's own construction succeeds (CFG-004's gate order).
- `accepted_heat_kw` is a DECIDED input, not computed by this component — the curtailment/shortfall
  decision (true surplus vs. resource-limited shortfall vs. numerical-stabilization margin) is
  network-wide policy that stays one layer above this component.
- Auxiliary/unmet heat is not computed here (it requires total consumer demand, which this
  component never sees) — see the module's own "Scope boundary" docstring section.
- `DoubletOperatingPolicy`'s solver-tolerance fields must currently equal
  `network.candidate`'s own named constants exactly — overriding them independently is not yet
  supported.
- Not (yet) called by `evaluate_candidate()` itself — see the parity note above.

## Construction example

```python
from r3chain_geothermal.network import (
    BlueprintCandidate, DistrictHeatingConnectionSpec, DoubletOperatingPolicy,
    GeothermalDoubletSpec, HeatExchangerBoundary, build_and_evaluate_geothermal_doublet,
)

spec = GeothermalDoubletSpec(
    producer_wellhead_temperature_c=76.313044, brine_mass_flow_kg_s=28.749278,
    brine_specific_heat_capacity_j_kg_k=3658.620334, raw_geothermal_thermal_power_kw=4345.417312,
    minimum_reinjection_temperature_c=35.0, doublet_pump_electric_power_kw=177.449827,
)
boundary = HeatExchangerBoundary(
    minimum_hx_approach_k=5.0, hx_heat_delivery_factor=0.98, deliverable_geothermal_heat_kw=3227.7186,
)
connection = DistrictHeatingConnectionSpec(
    candidate=BlueprintCandidate(
        id="C1", label="Near network head", supply_junction="trunk_1",
        return_junction="ret_trunk_1", surface_connection_length_m=50.0,
    ),
    dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0, dh_water_specific_heat_capacity_j_kg_k=4180.0,
)
policy = DoubletOperatingPolicy(accepted_heat_kw=3168.0, injection_sizing_policy="fixed_design_temperature")

result = build_and_evaluate_geothermal_doublet(blueprint, spec, boundary, connection, policy)
```

## Result-extraction example

```python
from r3chain_geothermal.network import GeothermalDoubletResult

if isinstance(result, GeothermalDoubletResult):
    print(result.district_heating_water_mass_flow_kg_s)   # solved injection-branch mass flow, kg/s
    print(result.outlet_temperature_c, result.outlet_design_temperature_c)  # actual vs. design, degC
    print(result.connection_differential_pressure_bar)     # bar_abs, friction-only
    print(result.circulation_pump_hydraulic_power_kw)       # this connection's own injection pump, kW
    print(result.flow_solver.iteration_count, result.flow_solver.converged)
else:
    print(result.failure_code, result.message, result.details)
```
