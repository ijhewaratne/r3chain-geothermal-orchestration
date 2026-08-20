# Technical observation — injector-side aquifer temperature reuse (index 5)

- **Status:** Open observation, not yet classified as a defect.
- **Found during:** the T1.4C2 producer-wellhead-temperature investigation
  (unrelated to that finding — see "Confirmation" below).
- **Repository/commit:** `repos/PyDoublet`, `pydoublet/doublet_config/doublet.py`,
  unchanged since commit `6ae5f60f...` (the T1.4A packaging repair); current
  HEAD `0d649c3e6930d342dac03654d57776e134c2d0b9` on
  `feature/pydoublet-integration`.

## Source expression and location

`pydoublet/doublet_config/doublet.py:253`, inside `Doublet.calc_pressure_balance`,
in the block computing node index 5 of `temp_along_doublet`
(`node_names_along_doublet[5] == "11, Aquifer_Inj"`):

```python
# add pressure and temperature difference injector-->aquifer
density = fluid.density_fluid(p=pres_at_node, T=temp_at_node, S=self.reservoir.aquifer_water_salinity)
viscosity = fluid.viscosity_fluid(T=temp_at_node, S=self.reservoir.aquifer_water_salinity)
dp = -self.injector.dp_well_aquifer(rate_vol=rate_mass / density, kh_net=self.reservoir.get_aquifer_kh_net(),
                                    distance_wells=self.distance_between_wells, viscosity=viscosity,
                                    skin=self.skin_injector)
dT = self.temp_mid_production_aquifer - temp_at_node
```

## Why this appears to reuse a producer-side reference for the injector side

`self.temp_mid_production_aquifer` is computed once, in `Doublet.build()`
(`doublet.py:51`), from `self.reservoir.aquifer_top_at_producer +
0.5 * self.reservoir.aquifer_gross_thickness` — a producer-side depth. It is
used correctly at node index 0 (`"1, Aquifer_Prod"`), which is explicitly the
producer-side aquifer reference.

At node index 5 (`"11, Aquifer_Inj"`), the **injector**-side aquifer
reference, the code resets `temp_at_node` to this **same**
`temp_mid_production_aquifer` variable, rather than a separately computed
value using `self.reservoir.aquifer_top_at_injector` (a distinct config field
that the reservoir schema explicitly allows to differ from
`aquifer_top_at_producer` — see `config_schema.py`'s `ReservoirParams`, both
fields required and independently specified). No `temp_mid_injection_aquifer`
variable exists anywhere in the file.

## Potential impact

If `aquifer_top_at_injector` differs materially from `aquifer_top_at_producer`
in a given scenario (the golden config uses 2468 m vs. 2505 m — a small but
non-zero difference), the injector-side aquifer reference temperature used at
node index 5 would not reflect the injector's own aquifer depth, and would be
systematically offset by whatever temperature difference the geothermal
gradient implies over that depth difference. This node is a pressure/
temperature-balance intermediate value (feeding into the residual/closure
node 6), not a value currently exposed in any adapter-facing field — so the
immediate, observable impact on `producer_wellhead_temperature_c` or any
other exported quantity is believed to be none, but the underlying
mass-flow/pressure-balance Newton–Raphson solve (`calc_mass_rate`) does use
`calc_pressure_balance`'s full node-by-node trace, so a downstream numerical
effect on the converged mass flow itself cannot be ruled out without further
analysis.

## Confirmation: independent of the producer-wellhead (index 2) finding

This observation does **not** weaken the ADR-002 determination for
`producer_wellhead_temperature_c` (index 2). The two are different code
paths: index 2 is computed via the producer well's own implicit thermal
solve (`well_tubing.calc_pressures_along_pipe`) integrating up from the
index-1 value to the well's own node 0, proven by the independent
`depth_profile_m[0] == 0.0` fact. Index 5 is a direct variable reassignment,
unrelated to any well-tubing computation. The index-2 evidence chain does not
rely on `temp_mid_production_aquifer` being correct for the injector side.

## Question for Dr. Jan

Is the injector-side aquifer reference temperature at node index 5 intended
to reuse the producer-side `temp_mid_production_aquifer`, or should it be a
separately computed value based on `aquifer_top_at_injector`? If the latter,
this is a defect requiring a physics-adjacent fix — out of scope for the
current packaging/contract work and not addressed by this observation.

## Status

Open observation. Not yet classified as a defect. No PyDoublet source change
has been made or is proposed here.
