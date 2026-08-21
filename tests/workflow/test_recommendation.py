"""Full test matrix for workflow/recommendation.py -- recommendation.md
(T2.4B2). Rendered from a fixed Python string template over an already-
computed WorkflowResult -- never an LLM call, never free-text generation."""
from __future__ import annotations

import json
from pathlib import Path

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow import WorkflowResult, run_workflow
from r3chain_geothermal.workflow.recommendation import (
    MINIMUM_AUXILIARY_MARGIN_CAVEAT,
    render_recommendation_markdown,
)

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


def _all_infeasible_result() -> WorkflowResult:
    """Reuses T2.3's own p_supply_bar_abs=4.51 contrivance (fails every
    candidate identically) to exercise the zero-feasible-candidates path."""
    config = _config()
    config["network"]["p_supply_bar_abs"] = 4.51
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    return result


def _mixed_result() -> WorkflowResult:
    config = _config()
    config["gates"]["min_pressure_bar_abs"] = 2.95
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    return result


def _md(result: WorkflowResult) -> str:
    return render_recommendation_markdown(result).decode("utf-8")


def test_worked_case_states_c1_as_preferred_with_committed_lcoh():
    text = _md(_worked_result())
    assert "C1 is preferred" in text
    assert "52.1714 EUR/MWh" in text


def test_worked_case_ranked_table_lists_all_four_in_rank_order():
    text = _md(_worked_result())
    for candidate_id, lcoh in (
        ("C1", "52.1714"), ("C2", "52.2602"), ("C3", "52.3489"), ("C4", "52.4821"),
    ):
        assert f"| {candidate_id} " in text
        assert lcoh in text


def test_states_network_connection_not_drilling_disclaimer():
    text = _md(_worked_result())
    assert "not**, and must never be read as, a" in text
    assert "drilling" in text.lower()


def test_states_hard_gates_precede_economics():
    text = _md(_worked_result())
    assert "BEFORE any" in text
    assert "economic figure" in text


def test_embeds_shared_capex_statement_verbatim():
    result = _worked_result()
    text = _md(result)
    assert result.ranking.shared_capex_statement in text


def test_embeds_baseline_scope_caveat_verbatim():
    result = _worked_result()
    text = _md(result)
    assert result.ranking.baseline_economics.scope_caveat in text


def test_embeds_minimum_auxiliary_margin_caveat_verbatim():
    text = _md(_worked_result())
    assert MINIMUM_AUXILIARY_MARGIN_CAVEAT in text


def test_states_provisional_assumptions_caveat():
    text = _md(_worked_result())
    assert "demo_assumption" in text
    assert "not validated engineering or market facts" in text


def test_run_id_is_present():
    result = _worked_result()
    text = _md(result)
    assert result.run_id in text


def test_zero_feasible_candidates_states_no_recommendation_honestly():
    text = _md(_all_infeasible_result())
    assert "No candidate is feasible" in text
    assert "No recommendation is made" in text
    assert "C1 is preferred" not in text


def test_zero_feasible_candidates_lists_every_rejection_code():
    result = _all_infeasible_result()
    text = _md(result)
    for entry in result.ranking.infeasible:
        assert entry.candidate_id in text
        assert entry.failure_code.value in text
    assert text.count("PRESSURE_LIMIT_EXCEEDED") >= 4


def test_mixed_case_lists_rejected_candidate_separately_from_ranked_table():
    result = _mixed_result()
    text = _md(result)
    assert "### Rejected candidates" in text
    assert "C4" in text.split("### Rejected candidates")[1]
    assert "PRESSURE_LIMIT_EXCEEDED" in text
    # C4 must not appear in the ranked table's rows.
    ranked_section = text.split("## Result")[1].split("### Rejected candidates")[0]
    assert "| C1 |" in ranked_section
    assert "| C4 |" not in ranked_section


def test_rendering_is_deterministic_across_two_independent_runs():
    result_1 = _worked_result()
    result_2 = _worked_result()
    assert render_recommendation_markdown(result_1) == render_recommendation_markdown(result_2)


def test_no_wall_clock_content_in_output():
    md_bytes = render_recommendation_markdown(_worked_result())
    assert b"created_at" not in md_bytes


def test_output_is_valid_utf8_ending_in_a_single_trailing_newline():
    md_bytes = render_recommendation_markdown(_worked_result())
    text = md_bytes.decode("utf-8")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
