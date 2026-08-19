# Phase-0 clarification questions — R3-CHAIN geothermal PoC

**To:** Prof. Tanja Kneiske, Dr. Jan Niederau
**From:** Ishantha Hewaratne
**Date:** 2026-08-19
**Purpose:** These eleven questions materially change implementation details of the
six-week PoC. Coding continues meanwhile with provisional values labelled
`demo_assumption` in `config/demo_assumptions.json`; every provisional value is
replaceable without code changes once answered. Please answer what you can — a
one-line answer per question is enough.

| # | Owner | Question |
|---|-------|----------|
| Q1 | Jan | Is the separate PyDoublet-MCP repository available, and is it the interface the demonstration must use? |
| Q2 | Jan | Which explicit PyDoublet variable is the producer wellhead/surface temperature? |
| Q3 | Jan | Is `exit_temp_heat_exchanger` a fixed modelling input, a required reinjection limit, or a calculated result? |
| Q4 | Tanja | Which district-heating supply/return temperatures should the demonstration use? |
| Q5 | Tanja | What minimum heat-exchanger approach temperature should be assumed? |
| Q6 | Tanja | Should insufficient geothermal heat make a candidate infeasible, or should an auxiliary source cover the shortfall and be costed? |
| Q7 | Tanja | Which source should be used for doublet, heat-exchanger and O&M costs? |
| Q8 | Tanja | Should ranking be technical feasibility first, then lowest annualised cost? (recommended) |
| Q9 | Tanja + Jan | Is the six-week result expected to use PyDoublet-MCP as one server and pandapipesAI as another, with an external client connecting both? |
| Q10 | Jan | Where will the R3-CHAIN branch be hosted, and which licence governs PyDoublet? The repository currently contains conflicting Apache-2.0 and MIT declarations. |
| Q11 | Tanja | What minimum absolute network pressure should the feasibility gate use (1.0–1.5 bar abs), and is the project-wide absolute-pressure convention acceptable? |

## Details, evidence and adopted provisional values

### Q1 — PyDoublet-MCP availability (Jan)
- **Evidence:** No MCP code exists in the supplied PyDoublet snapshot. The supplied
  pandapipesAI URL (`github.com/Digital-Energy-Intelligence-Lab/pandapipesAI`) is not
  anonymously accessible; no PyDoublet remote is known at all.
- **Provisional:** the PoC plans a minimal fallback (`pydoublet_run`,
  `pydoublet_get_result`) for Sprint 5, per implementation plan §13.
- **Impact if different:** if PyDoublet-MCP exists, we extend its contract instead of
  building a duplicate server (plan §5), and Sprint-5 scope shrinks.

### Q2 — Producer wellhead temperature field (Jan)
- **Evidence:** The exported JSON has no named wellhead-temperature field. The value
  76.313 °C appears only as `temperature_profile_c[2]` (from
  `Doublet.temp_along_doublet`), whose node label is `"5&6, Prod_Top/Entry_HE"`
  (`pydoublet/doublet_config/doublet.py`, `node_names_along_doublet`;
  export in `pydoublet/scenario.py::_extract_simulation_results`). Position-based,
  undocumented, fragile.
- **Provisional:** `demo_assumption`: index 2 of `temperature_profile_c` is the
  producer wellhead temperature (config key `pydoublet.producer_wellhead_temperature_source`).
  The Sprint-1 PyDoublet repair adds an explicit named field pending your confirmation.
- **Impact if different:** adapter input mapping and the golden fixture change; all
  HX feasibility numbers shift.

### Q3 — Meaning of `exit_temp_heat_exchanger` (Jan)
- **Evidence:** `pydoublet/surface_installations/heat_exchanger.py` is a 6-line
  dataclass; the value (35 °C) is a **fixed user input**. In
  `doublet.py::calc_pressure_balance` the brine temperature after the HX node is simply
  set to it, and `calc_power_data` computes geothermal power as
  `qmass · cp · (T_prod − 35)`. No HX physics, no reinjection constraint enforced.
- **Provisional:** treated as a fixed modelling input, **not** a guaranteed reinjection
  limit; the adapter independently computes the allowable brine outlet as
  `max(T_reinj_min, T_DH_return + ΔT_min)` (plan §9.3).
- **Impact if different:** if 35 °C is a hard reinjection *requirement*, candidates
  that leave the brine warmer than 35 °C need an explicit note/penalty; if it is a
  *result* in a future PyDoublet version, the coupling contract gains a field.

### Q4 — DH supply/return temperatures (Tanja)
- **Provisional:** 70 °C / 40 °C (`coupling_assumptions.dh_supply_temperature_c` /
  `dh_return_temperature_c`), per plan §8.2. Note: pandapipesAI's own defaults are
  80/50 °C — with 80 °C supply and a 5 K approach, the 76.3 °C brine could not heat
  the network at all, which is why 70/40 matters.
- **Impact if different:** changes deliverable heat, DH mass flow, and possibly makes
  every candidate infeasible (hot-end gate `T_prod ≥ T_supply + ΔT_min`).

### Q5 — Minimum HX approach temperature (Tanja)
- **Provisional:** 5 K (`coupling_assumptions.minimum_hx_approach_k`), plan §8.2.
- **Impact if different:** directly moves the allowable brine outlet (45 °C with
  40 °C return + 5 K) and therefore the deliverable-heat ceiling
  (~3.3 MW vs. raw 4.35 MW at the golden operating point).

### Q6 — Shortfall policy (Tanja)
- **Provisional:** `auxiliary_policy: "cost_shortfall"` — geothermal supplies what it
  feasibly can; a documented auxiliary source covers the remainder and is costed.
  A strict mode (any shortfall ⇒ infeasible) is implemented and configurable
  (plan §9.5; ADR-001 D5).
- **Impact if different:** strict mode likely rejects all candidates at 3.2 MW demand
  if deliverable heat lands below demand, changing the whole demo narrative.

### Q7 — Cost data source (Tanja)
- **Evidence:** pandapipesAI's costing module is KWW-Technikkatalog-based with a
  session ledger designed for extension (`ledger.py` explicitly anticipates
  `module="geo"`). It contains no geothermal doublet/HX cost data.
- **Provisional:** placeholder unit costs marked `"source": "placeholder pending Q7"`
  in `config/demo_assumptions.json::economics`; ledger keys under `geo.*` from
  Sprint 4. Doublet CAPEX identical across candidates, so it cannot drive ranking.
- **Impact if different:** absolute LCOH changes; relative candidate ranking is
  driven only by connection-length/DN CAPEX, pumping electricity and auxiliary cost.

### Q8 — Ranking rule (Tanja)
- **Provisional:** feasibility-first, then lowest annualised incremental cost;
  tie-breakers per plan §12.3. Recorded as ADR-001 D4.
- **Impact if different:** a weighted multi-criteria score would require a new ADR
  and is recommended against in version 1.

### Q9 — Two-server MCP topology (Tanja + Jan)
- **Provisional:** target picture is two servers (PyDoublet[-MCP] + pandapipesAI)
  joined by one external scripted client (plan §14); the 15-Sep workshop shows the
  minimal wrapper only (ADR-001 D6).
- **Impact if different:** a one-server decision moves the PyDoublet tools into
  pandapipesAI's server and removes the fallback server from Sprint 5.

### Q10 — Hosting and PyDoublet licence (Jan)
- **Evidence:** `PyDoublet/LICENSE` is Apache-2.0, while `pyproject.toml`
  (`license = {text = "MIT"}`, MIT classifier) and `setup.py` declare MIT.
  pandapipesAI is BSD-3-Clause (consistent).
- **Provisional:** no PyDoublet code is copied or redistributed outside the local
  workspace until resolved; work stays on the local integration branch.
- **Impact if different:** affects where the R3-CHAIN branches can be hosted and
  whether demo code may vendor PyDoublet snippets.

### Q11 — Minimum absolute network pressure and pressure convention (Tanja)
- **Evidence:** the implementation plan's gate table (§11) lists "Minimum absolute
  network pressure: 1.0–1.5 bar, confirm". The project has adopted a single
  convention: all pressure fields are absolute (`*_bar_abs`), matching how
  pandapipes pressure output is treated; gauge pressures are never compared with
  pandapipes output directly.
- **Provisional:** `min_pressure_bar_abs = 1.5` (the stricter bound), config keys
  `network.min_pressure_bar_abs` / `gates.min_pressure_bar_abs`,
  `pressure_reference: "absolute"`. A Sprint-2 unit test pins the pressure-reference
  semantics of pandapipes results before the gate is applied.
- **Impact if different:** 1.0 bar abs loosens the feasibility margin at the network's
  low-pressure points; candidates near the remote section are most affected.
