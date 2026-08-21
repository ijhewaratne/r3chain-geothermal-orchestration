"""Full test matrix for workflow/csv_export.py -- candidate_comparison.csv
(T2.4B2). Pure deterministic templating over an already-computed
WorkflowResult -- never re-derives a technical/economic value."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.network import CandidateEvaluationResult
from r3chain_geothermal.workflow import WorkflowResult, run_workflow
from r3chain_geothermal.workflow.csv_export import CSV_COLUMNS, render_candidate_comparison_csv

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _worked_result() -> WorkflowResult:
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    return result


def _mixed_result() -> WorkflowResult:
    """C4 fails PRESSURE_LIMIT_EXCEEDED; C1-C3 stay feasible -- a genuine
    per-candidate divergence (min_pressure_bar_abs differs by trunk
    position: C1=2.986/C2=2.978/C3=2.959/C4=2.917 bar abs for the golden
    fixture), unlike the earlier all-candidates-fail p_supply contrivance."""
    config = _config()
    config["gates"]["min_pressure_bar_abs"] = 2.95
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    return result


def _rows(csv_bytes: bytes) -> list[dict[str, str]]:
    text = csv_bytes.decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def test_header_matches_fixed_columns_exactly():
    csv_bytes = render_candidate_comparison_csv(_worked_result())
    header_line = csv_bytes.decode("utf-8").splitlines()[0]
    assert header_line == ",".join(CSV_COLUMNS)


def test_row_order_is_always_c1_through_c4_sorted_never_ranking_order():
    result = _mixed_result()
    rows = _rows(render_candidate_comparison_csv(result))
    assert [row["candidate_id"] for row in rows] == ["C1", "C2", "C3", "C4"]


def test_worked_case_reproduces_committed_lcoh_values():
    rows = _rows(render_candidate_comparison_csv(_worked_result()))
    lcoh_by_id = {row["candidate_id"]: row["indicative_lcoh_eur_per_mwh"] for row in rows}
    assert lcoh_by_id["C1"] == "52.1714"
    assert lcoh_by_id["C2"] == "52.2602"
    assert lcoh_by_id["C3"] == "52.3489"
    assert lcoh_by_id["C4"] == "52.4821"


def test_worked_case_rank_matches_ranking_order():
    rows = _rows(render_candidate_comparison_csv(_worked_result()))
    rank_by_id = {row["candidate_id"]: row["rank"] for row in rows}
    assert rank_by_id == {"C1": "1", "C2": "2", "C3": "3", "C4": "4"}
    assert all(row["feasible"] == "True" for row in rows)
    assert all(row["failure_code"] == "" for row in rows)


def test_infeasible_candidate_has_empty_technical_and_economic_columns():
    rows = _rows(render_candidate_comparison_csv(_mixed_result()))
    row = next(row for row in rows if row["candidate_id"] == "C4")
    assert row["feasible"] == "False"
    assert row["failure_code"] == "PRESSURE_LIMIT_EXCEEDED"
    assert row["failure_reason"] != ""
    always_populated = (
        "candidate_id", "label", "surface_connection_length_m", "converged", "feasible",
        "failure_code", "failure_reason",
    )
    for column in CSV_COLUMNS:
        if column in always_populated:
            continue
        assert row[column] == "", f"infeasible row must leave {column!r} empty, got {row[column]!r}"


def test_infeasible_candidate_still_reports_its_geometry():
    """surface_connection_length_m is pure geometry (BlueprintCandidate,
    embedded on CandidateEvaluationFailure too) -- it must NOT be gated
    behind feasibility the way every downstream physical/economic KPI is."""
    rows = _rows(render_candidate_comparison_csv(_mixed_result()))
    row = next(row for row in rows if row["candidate_id"] == "C4")
    assert row["surface_connection_length_m"] == "120.000000"


def test_worked_case_reports_surface_connection_length_per_candidate():
    rows = _rows(render_candidate_comparison_csv(_worked_result()))
    lengths = {row["candidate_id"]: row["surface_connection_length_m"] for row in rows}
    assert lengths == {"C1": "50.000000", "C2": "70.000000", "C3": "90.000000", "C4": "120.000000"}


def test_worked_case_reports_actual_geothermal_injection_temperatures():
    result = _worked_result()
    rows = _rows(render_candidate_comparison_csv(result))
    for row in rows:
        candidate_result = result.candidate_results[row["candidate_id"]]
        assert float(row["geothermal_injection_inlet_temperature_c"]) == pytest.approx(
            candidate_result.geothermal_injection_inlet_temperature_c
        )
        assert float(row["geothermal_injection_outlet_temperature_c"]) == pytest.approx(
            candidate_result.geothermal_injection_outlet_temperature_c
        )


def test_worked_case_reports_actual_consumer_supply_and_return_temperatures():
    result = _worked_result()
    rows = _rows(render_candidate_comparison_csv(result))
    for row in rows:
        candidate_result = result.candidate_results[row["candidate_id"]]
        assert float(row["min_consumer_supply_temperature_c"]) == pytest.approx(
            candidate_result.min_consumer_supply_temperature_c
        )
        assert float(row["mean_consumer_return_temperature_c"]) == pytest.approx(
            candidate_result.mean_consumer_return_temperature_c
        )


def test_worked_case_reports_pumping_power_kpis_matching_typed_fields():
    result = _worked_result()
    rows = _rows(render_candidate_comparison_csv(result))
    for row in rows:
        candidate_result = result.candidate_results[row["candidate_id"]]
        econ = next(e for e in result.ranking.ranked if e.candidate_id == row["candidate_id"]).economics
        assert float(row["connection_pump_hydraulic_power_kw"]) == pytest.approx(
            candidate_result.connection_pumping_power_kw
        )
        assert float(row["residual_main_pump_hydraulic_power_kw"]) == pytest.approx(
            candidate_result.circulation_pump.hydraulic_pumping_power_kw
        )
        assert float(row["doublet_pump_electric_power_kw"]) == pytest.approx(
            candidate_result.doublet_pump_electric_power_kw
        )
        assert float(row["total_dh_hydraulic_pumping_power_kw"]) == pytest.approx(
            econ.dh_hydraulic_pumping_power_kw
        )
        # The total must be at least each individual hydraulic-power component
        # (it is main-pump + connection-pump summed, an already-typed field --
        # never recomputed here, only cross-checked).
        assert float(row["total_dh_hydraulic_pumping_power_kw"]) >= float(row["connection_pump_hydraulic_power_kw"])
        assert float(row["total_dh_hydraulic_pumping_power_kw"]) >= float(row["residual_main_pump_hydraulic_power_kw"])


def test_worked_case_reports_annual_useful_heat_in_mwh_matching_typed_field():
    result = _worked_result()
    rows = _rows(render_candidate_comparison_csv(result))
    for row in rows:
        econ = next(e for e in result.ranking.ranked if e.candidate_id == row["candidate_id"]).economics
        assert float(row["annual_useful_heat_mwh"]) == pytest.approx(econ.annual_total_heat_delivered_kwh / 1000.0)
        assert float(row["annual_useful_heat_mwh"]) == pytest.approx(16000.0)


def test_infeasible_candidate_never_gets_a_fabricated_zero_or_na():
    rows = _rows(render_candidate_comparison_csv(_mixed_result()))
    row = next(row for row in rows if row["candidate_id"] == "C4")
    for column in ("annualised_cost_total_eur_per_a", "indicative_lcoh_eur_per_mwh", "rank"):
        assert row[column] not in ("0", "0.0", "0.00", "N/A", "NA", "null")
        assert row[column] == ""


def test_feasible_candidates_in_mixed_case_still_carry_full_economics():
    rows = _rows(render_candidate_comparison_csv(_mixed_result()))
    for candidate_id in ("C1", "C2", "C3"):
        row = next(row for row in rows if row["candidate_id"] == candidate_id)
        assert row["feasible"] == "True"
        assert row["rank"] != ""
        assert float(row["indicative_lcoh_eur_per_mwh"]) > 0


def test_converged_true_for_a_pressure_gate_failure_that_did_converge():
    rows = _rows(render_candidate_comparison_csv(_mixed_result()))
    row = next(row for row in rows if row["candidate_id"] == "C4")
    assert row["converged"] == "True"


def test_rendering_is_deterministic_across_repeated_calls():
    result = _worked_result()
    assert render_candidate_comparison_csv(result) == render_candidate_comparison_csv(result)


def test_rendering_is_deterministic_across_two_independent_runs():
    result_1 = _worked_result()
    result_2 = _worked_result()
    assert render_candidate_comparison_csv(result_1) == render_candidate_comparison_csv(result_2)


def test_every_column_present_for_every_candidate_row():
    rows = _rows(render_candidate_comparison_csv(_worked_result()))
    assert len(rows) == 4
    for row in rows:
        assert set(row.keys()) == set(CSV_COLUMNS)


def test_uses_lf_line_terminator_not_crlf():
    csv_bytes = render_candidate_comparison_csv(_worked_result())
    assert b"\r\n" not in csv_bytes
    assert b"\n" in csv_bytes
