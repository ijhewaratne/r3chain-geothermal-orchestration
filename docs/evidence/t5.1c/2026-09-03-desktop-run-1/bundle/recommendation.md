# R3-CHAIN geothermal candidate recommendation

This report evaluates network CONNECTION locations for one already-computed geothermal doublet result -- it is **not**, and must never be read as, a geological or drilling-location recommendation.

Run ID: `r3chain-run-efdb9cd8625c4b61`

## Result

**C1 is preferred** for this worked case -- rank 1 of 4 feasible candidate(s), lowest indicative LCOH at 52.1714 EUR/MWh.

| Rank | Candidate | Indicative LCOH | Total annualised cost |
|---:|---|---:|---:|
| 1 | C1 | 52.1714 EUR/MWh | 834,742.76 EUR/a |
| 2 | C2 | 52.2602 EUR/MWh | 836,162.42 EUR/a |
| 3 | C3 | 52.3489 EUR/MWh | 837,582.80 EUR/a |
| 4 | C4 | 52.4821 EUR/MWh | 839,713.38 EUR/a |

## Method and scope

Hard technical feasibility gates (convergence, consumer temperature delivery, absolute pressure, pipe velocity, mass balance, physical energy balance, and the geothermal-injection hydraulic check) were applied to every candidate BEFORE any economic figure was computed -- an infeasible candidate is never assigned a cost, an LCOH, or a rank (feasibility-first ranking, plan §12.3).

Every feasible candidate reuses the identical PyDoublet scenario and coupling result, so doublet and heat-exchanger CAPEX (and their annuities) are numerically identical across C1-C4 and do not drive this ranking. This ranking evaluates network-CONNECTION-location differences (connection length, DH pumping, technical margin) only -- it is not, and must never be read as, a geological or drilling-location recommendation.

## Provisional assumptions

The synthetic network geometry (trunk/branch layout, candidate connection lengths) and every economic value (CAPEX, O&M fraction, interest rate, electricity/auxiliary heat prices, DH pump efficiency) are documented `demo_assumption` placeholders (`config/demo_assumptions.json`), not validated engineering or market facts -- see that file's own `_status`/`source_status` fields for the exact provenance of each.

The geothermal-injection curtailment margin (`minimum_auxiliary_circulation_fraction`) is a documented numerical-stability assumption, not a physical operating choice -- it exists for two independently-discovered reasons: (1) it keeps the main plant pump's converged net mass flow clear of pandapipes 0.14.0's zero-tolerance circulation-pump direction-change check; (2) it keeps the network's thermal field sufficiently anchored by the main pump's own design-temperature flow that consumer_1 does not breach the consumer supply-temperature-drop gate (a temperature-anchoring effect). See `docs/technical-observations/pandapipes-circulation-pump-direction-check.md` for the full evidence and measured boundary.

This is a PROTOTYPE-BOUNDARY auxiliary-heat counterfactual, not a validated full-system baseline LCOH. auxiliary_heat_price_eur_per_kwh (config economics.opex.auxiliary_heat_price) is a per-kWh delivered-heat price assumption; it is NOT confirmed to be an all-inclusive price that already covers an auxiliary plant's own CAPEX and fixed O&M. Unless that price is explicitly defined as all-inclusive, indicative_lcoh_eur_per_kwh here EXCLUDES auxiliary-plant CAPEX and fixed O&M, and must not be read or compared as if computed on the same complete-system cost boundary as a candidate's own indicative_lcoh_eur_per_kwh (which DOES include doublet/HX/connection-pipe CAPEX and their fixed O&M).
