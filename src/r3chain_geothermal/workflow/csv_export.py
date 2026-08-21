"""Deterministic `candidate_comparison.csv` rendering (T2.4B2).

Pure, deterministic string/bytes templating over an already-computed
`WorkflowResult` -- never re-derives a technical or economic value, never
calls an LLM, never touches pandapipes/PyDoublet. Fixed columns, fixed
row order (`sorted(candidate_results)` -- C1..C4 always, NOT ranking
order, so the file's row order never depends on which candidates happen
to be feasible this run).

Three tiers of column availability, in increasing order of what a
candidate must have achieved to populate them:

    1. ALWAYS populated, feasible or not -- pure geometry: `candidate_id`,
       `label`, `surface_connection_length_m` (from the blueprint's own
       candidate spec, `BlueprintCandidate`, embedded on BOTH
       `CandidateEvaluationResult` and `CandidateEvaluationFailure`).
    2. Populated once a candidate reaches a full, converged network
       solve -- i.e. `isinstance(candidate_result, CandidateEvaluationResult)`:
       every physical KPI (temperatures, pressures, velocities, mass/
       energy balance, connection-pump and residual main-pump hydraulic
       power, doublet-pump electrical power).
    3. Populated only for a RANKED (feasible + costed) candidate --
       `rank_by_id.get(candidate_id)` is not None: every economic figure,
       `total_dh_hydraulic_pumping_power_kw` and `annual_useful_heat_mwh`
       (both live on the per-candidate economics result, not the network
       result), and `rank` itself.

For an INFEASIBLE candidate, every column past tier 1 is left EMPTY
(never a fabricated 0 or "N/A" string that could be misread as a real
value) -- hard feasibility gates precede economics (CLAUDE.md), so an
infeasible row genuinely has no economics or downstream technical KPIs to
report.
"""
from __future__ import annotations

import csv
import io

from ..network import CandidateEvaluationFailure, CandidateEvaluationResult
from .core import WorkflowResult

CSV_COLUMNS = (
    "candidate_id", "label", "surface_connection_length_m",
    "converged", "feasible", "failure_code", "failure_reason",
    "geothermal_injected_heat_kw", "geothermal_curtailed_heat_kw", "auxiliary_heat_kw", "unmet_heat_kw",
    "geothermal_coverage_fraction",
    "geothermal_injection_inlet_temperature_c", "geothermal_injection_outlet_temperature_c",
    "min_consumer_supply_temperature_c", "mean_consumer_return_temperature_c",
    "min_pressure_bar_abs", "max_velocity_m_s",
    "worst_consumer_supply_temperature_drop_k", "consumer_temperature_result",
    "mass_balance_residual_fraction", "energy_balance_residual_fraction",
    "connection_pressure_drop_bar", "connection_pump_hydraulic_power_kw",
    "residual_main_pump_hydraulic_power_kw", "doublet_pump_electric_power_kw",
    "dh_pumping_electricity_eur_per_a", "doublet_pump_electricity_eur_per_a",
    "total_dh_hydraulic_pumping_power_kw", "annual_useful_heat_mwh",
    "connection_capex_eur", "annualised_cost_total_eur_per_a", "indicative_lcoh_eur_per_mwh", "rank",
)
"""Fixed, in this order, always -- never re-ordered/added-to silently; a
schema change here is a deliberate, reviewed decision, matching every
other typed contract in this project."""

_NOT_CONVERGENCE_RELATED_FAILURE_CODES = frozenset({
    "CONSUMER_TEMPERATURE_NOT_MET", "PRESSURE_LIMIT_EXCEEDED", "VELOCITY_LIMIT_EXCEEDED",
    "MASS_BALANCE_FAILED", "ENERGY_BALANCE_FAILED",
})
"""T2.3's own gate order (plan §11): THERMAL_PIPEFLOW_NOT_CONVERGED and
GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT are hydraulic-convergence
failures; every OTHER CandidateFailureCode is only reachable after
convergence already succeeded -- so a candidate failing for one of these
five reasons genuinely DID converge."""


def _converged(candidate_result) -> bool:
    if isinstance(candidate_result, CandidateEvaluationResult):
        return True
    return candidate_result.failure_code.value in _NOT_CONVERGENCE_RELATED_FAILURE_CODES


def _row_for_candidate(
    candidate_id: str, candidate_result, rank_by_id: dict, max_supply_drop_k: float,
) -> dict[str, str]:
    row: dict[str, str] = {column: "" for column in CSV_COLUMNS}
    row["candidate_id"] = candidate_id
    row["label"] = candidate_result.candidate.label
    # Tier 1: pure geometry, present on both CandidateEvaluationResult and
    # CandidateEvaluationFailure (BlueprintCandidate embedded on both).
    row["surface_connection_length_m"] = f"{candidate_result.candidate.surface_connection_length_m:.6f}"
    row["converged"] = str(_converged(candidate_result))
    row["feasible"] = str(isinstance(candidate_result, CandidateEvaluationResult))

    if isinstance(candidate_result, CandidateEvaluationFailure):
        row["failure_code"] = candidate_result.failure_code.value
        row["failure_reason"] = candidate_result.message
        return row

    # Tier 2: a full, converged network solve exists -- every field below
    # is an already-typed, already-validated KPI read straight off
    # CandidateEvaluationResult, never recomputed here.
    result: CandidateEvaluationResult = candidate_result
    worst_drop_k = max(c.supply_temperature_drop_k for c in result.consumers.values())
    row.update({
        "geothermal_injected_heat_kw": f"{result.geothermal_injected_heat_kw:.6f}",
        "geothermal_curtailed_heat_kw": f"{result.geothermal_curtailed_heat_kw:.6f}",
        "auxiliary_heat_kw": f"{result.auxiliary_heat_kw:.6f}",
        "unmet_heat_kw": f"{result.unmet_heat_kw:.6f}",
        "geothermal_coverage_fraction": f"{result.geothermal_coverage_fraction:.9f}",
        "geothermal_injection_inlet_temperature_c": f"{result.geothermal_injection_inlet_temperature_c:.6f}",
        "geothermal_injection_outlet_temperature_c": f"{result.geothermal_injection_outlet_temperature_c:.6f}",
        "min_consumer_supply_temperature_c": f"{result.min_consumer_supply_temperature_c:.6f}",
        "mean_consumer_return_temperature_c": f"{result.mean_consumer_return_temperature_c:.6f}",
        "min_pressure_bar_abs": f"{result.min_pressure_bar_abs:.6f}",
        "max_velocity_m_s": f"{result.max_velocity_m_s:.6f}",
        "worst_consumer_supply_temperature_drop_k": f"{worst_drop_k:.6f}",
        "consumer_temperature_result": "within_limit" if worst_drop_k <= max_supply_drop_k else "exceeded",
        "mass_balance_residual_fraction": f"{result.mass_balance.residual_fraction:.3e}",
        "energy_balance_residual_fraction": f"{result.energy_balance.residual_fraction:.3e}",
        "connection_pressure_drop_bar": f"{result.connection_pressure_drop_bar:.6f}",
        "connection_pump_hydraulic_power_kw": f"{result.connection_pumping_power_kw:.6f}",
        "residual_main_pump_hydraulic_power_kw": f"{result.circulation_pump.hydraulic_pumping_power_kw:.6f}",
        "doublet_pump_electric_power_kw": f"{result.doublet_pump_electric_power_kw:.6f}",
    })

    entry = rank_by_id.get(candidate_id)
    if entry is not None:
        # Tier 3: only a RANKED (feasible + costed) candidate has an
        # economics result -- dh_hydraulic_pumping_power_kw and
        # annual_total_heat_delivered_kwh live there, not on the network
        # result above.
        econ = entry.economics
        row.update({
            "dh_pumping_electricity_eur_per_a": f"{econ.opex_electricity_dh_pumping_eur_per_a:.2f}",
            "doublet_pump_electricity_eur_per_a": f"{econ.opex_electricity_doublet_pump_eur_per_a:.2f}",
            "total_dh_hydraulic_pumping_power_kw": f"{econ.dh_hydraulic_pumping_power_kw:.6f}",
            "annual_useful_heat_mwh": f"{econ.annual_total_heat_delivered_kwh / 1000.0:.6f}",
            "connection_capex_eur": f"{econ.capex_connection_pipes_eur:.2f}",
            "annualised_cost_total_eur_per_a": f"{econ.annualised_cost_total_eur_per_a:.2f}",
            "indicative_lcoh_eur_per_mwh": f"{econ.indicative_lcoh_eur_per_kwh * 1000.0:.4f}",
            "rank": str(entry.rank),
        })
    return row


def render_candidate_comparison_csv(result: WorkflowResult) -> bytes:
    """Renders `candidate_comparison.csv`'s exact bytes -- deterministic:
    the same WorkflowResult content always produces the same bytes (no
    created_at anywhere in this file at all, so byte_sha256 ==
    scientific_sha256 for it -- artifacts.py's own convention)."""
    rank_by_id = {entry.candidate_id: entry for entry in result.ranking.ranked}
    max_supply_drop_k = result.audit.gate_tolerances.max_consumer_supply_drop_k

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for candidate_id in sorted(result.candidate_results):
        row = _row_for_candidate(
            candidate_id, result.candidate_results[candidate_id], rank_by_id, max_supply_drop_k,
        )
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")
