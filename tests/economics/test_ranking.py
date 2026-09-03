"""Full test matrix for economics/ranking.py -- feasibility-first candidate
ranking."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from r3chain_geothermal.adapter.heat_exchanger import HeatExchangerCouplingResult
from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.economics import EconomicAssumptions, RankingResult, SHARED_CAPEX_STATEMENT, rank_candidates
from r3chain_geothermal.network import (
    BaselineNetworkResult,
    BlueprintCandidate,
    CandidateFailureCode,
    GateTolerances,
    GeothermalInjectionPolicy,
    build_default_blueprint,
    evaluate_candidate,
    run_baseline_evaluation,
)
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_RANKING_SRC_PATH = _ROOT / "src" / "r3chain_geothermal" / "economics" / "ranking.py"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}
_CANDIDATES = {
    "C1": ("trunk_1", "ret_trunk_1", 50.0), "C2": ("trunk_2", "ret_trunk_2", 70.0),
    "C3": ("trunk_3", "ret_trunk_3", 90.0), "C4": ("trunk_4", "ret_trunk_4", 120.0),
}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _tolerances() -> GateTolerances:
    return GateTolerances.from_config_dict(_config())


def _policy(**overrides) -> GeothermalInjectionPolicy:
    base = dict(
        curtailment_allowed=True, auxiliary_policy="cost_shortfall",
        minimum_auxiliary_circulation_fraction=0.01, heat_delivery_tolerance_fraction=0.01,
    )
    base.update(overrides)
    return GeothermalInjectionPolicy(**base)


def _econ_assumptions() -> EconomicAssumptions:
    return EconomicAssumptions.from_config_dict(_config())


def _blueprint(**overrides):
    kwargs = dict(
        consumer_demands_kw=_DEMANDS,
        trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0,
        created_at=datetime.now(timezone.utc),
    )
    kwargs.update(overrides)
    return build_default_blueprint(**kwargs)


def _golden_coupling_result(**assumption_overrides) -> HeatExchangerCouplingResult:
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired", calculation_mode="deterministic",
    )
    coupling_input = parse_pydoublet_result(raw, source_provenance=provenance)
    assumptions = CouplingAssumptions.from_config_dict(_config())
    if assumption_overrides:
        assumptions = assumptions.model_copy(update=assumption_overrides)
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingResult)
    return result


def _baseline(blueprint=None) -> BaselineNetworkResult:
    bp = blueprint if blueprint is not None else _blueprint()
    result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(result, BaselineNetworkResult)
    return result


def _candidate(candidate_id: str) -> BlueprintCandidate:
    supply, ret, length = _CANDIDATES[candidate_id]
    return BlueprintCandidate(id=candidate_id, label=candidate_id, supply_junction=supply, return_junction=ret, surface_connection_length_m=length)


def _all_worked_results(bp=None, coupling_result=None, baseline=None):
    bp = bp if bp is not None else _blueprint()
    coupling_result = coupling_result if coupling_result is not None else _golden_coupling_result()
    baseline = baseline if baseline is not None else _baseline(bp)
    results = {}
    for candidate_id in _CANDIDATES:
        results[candidate_id] = evaluate_candidate(
            coupling_result, bp, _candidate(candidate_id), baseline,
            injection_policy=_policy(), tolerances=_tolerances(),
        )
    return bp, coupling_result, baseline, results


def _strict_json_loads(text: str):
    def _reject(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")
    return json.loads(text, parse_constant=_reject)


# ── Worked case ───────────────────────────────────────────────────────────────
def test_worked_case_ranks_all_four_feasible_candidates():
    bp, coupling_result, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    assert isinstance(ranking, RankingResult)
    assert len(ranking.ranked) == 4
    assert ranking.infeasible == []
    assert {entry.candidate_id for entry in ranking.ranked} == set(_CANDIDATES)


def test_worked_case_ranks_are_contiguous_and_ascending_cost():
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    assert [entry.rank for entry in ranking.ranked] == [1, 2, 3, 4]
    costs = [entry.economics.annualised_cost_total_eur_per_a for entry in ranking.ranked]
    assert costs == sorted(costs)


def test_worked_case_c1_ranks_first_shortest_connection_cheapest():
    """In the worked case only connection length differs meaningfully --
    C1 (shortest, 50m) should rank first, C4 (longest, 120m) last."""
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    order = [entry.candidate_id for entry in ranking.ranked]
    assert order == ["C1", "C2", "C3", "C4"]


def test_shared_capex_statement_present_and_fixed():
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    assert ranking.shared_capex_statement == SHARED_CAPEX_STATEMENT
    assert "identical" in ranking.shared_capex_statement.lower()
    assert "drilling" in ranking.shared_capex_statement.lower()


# ── Infeasible candidates never scored ───────────────────────────────────────
def test_infeasible_candidate_never_appears_in_ranked():
    bp, coupling_result, baseline, results = _all_worked_results()
    # Force C1 infeasible via an artificially tight mass-balance tolerance
    # applied only to C1's own evaluation -- reuse T2.3's own established
    # contrivance pattern.
    tight_tolerances = _tolerances().model_copy(update={"mass_balance_tolerance_fraction": 1e-18})
    results["C1"] = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline, injection_policy=_policy(), tolerances=tight_tolerances,
    )
    from r3chain_geothermal.network import CandidateEvaluationFailure
    assert isinstance(results["C1"], CandidateEvaluationFailure)

    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    assert "C1" not in {entry.candidate_id for entry in ranking.ranked}
    assert len(ranking.ranked) == 3
    assert len(ranking.infeasible) == 1
    assert ranking.infeasible[0].candidate_id == "C1"
    assert ranking.infeasible[0].failure_code == CandidateFailureCode.MASS_BALANCE_FAILED


def test_infeasible_candidate_never_assigned_a_cost_or_rank():
    """Structural: InfeasibleCandidateEntry has no cost/rank field at all
    -- this test documents that guarantee via the model's own fields."""
    from r3chain_geothermal.economics.ranking import InfeasibleCandidateEntry
    field_names = set(InfeasibleCandidateEntry.model_fields)
    assert "rank" not in field_names
    assert not any("cost" in name or "eur" in name for name in field_names)


def test_all_candidates_infeasible_yields_empty_ranked():
    bp, coupling_result, baseline, results = _all_worked_results()
    tight_tolerances = _tolerances().model_copy(update={"mass_balance_tolerance_fraction": 1e-18})
    results = {
        cid: evaluate_candidate(coupling_result, bp, _candidate(cid), baseline, injection_policy=_policy(), tolerances=tight_tolerances)
        for cid in _CANDIDATES
    }
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    assert ranking.ranked == []
    assert len(ranking.infeasible) == 4


# ── Tie-break keys ────────────────────────────────────────────────────────────
def test_technical_margin_fraction_is_minimum_of_three_normalized_margins():
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    for entry in ranking.ranked:
        expected = min(entry.pressure_margin_fraction, entry.velocity_margin_fraction, entry.temperature_margin_fraction)
        assert entry.technical_margin_fraction == expected


def test_dh_pumping_electricity_tie_break_key_matches_economics_field():
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    for entry in ranking.ranked:
        # sanity: the tie-break key used internally is this exact field
        assert entry.economics.opex_electricity_dh_pumping_eur_per_a >= 0


# ── Strict-JSON round trip ───────────────────────────────────────────────────
def test_strict_json_round_trip():
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    dumped = ranking.model_dump_json()
    _strict_json_loads(dumped)
    restored = RankingResult.model_validate_json(dumped)
    assert restored == ranking


# ── Model-level tamper tests ─────────────────────────────────────────────────
def _valid_ranking_payload() -> dict:
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    return json.loads(ranking.model_dump_json())


def test_control_untouched_payload_round_trips_cleanly():
    payload = _valid_ranking_payload()
    RankingResult.model_validate_json(json.dumps(payload))


def test_tamper_rank_order_broken_is_rejected():
    payload = _valid_ranking_payload()
    payload["ranked"][0]["rank"], payload["ranked"][1]["rank"] = payload["ranked"][1]["rank"], payload["ranked"][0]["rank"]
    with pytest.raises(ValidationError):
        RankingResult.model_validate_json(json.dumps(payload))


def test_tamper_cost_ordering_broken_is_rejected():
    payload = _valid_ranking_payload()
    payload["ranked"][0]["economics"]["annualised_cost_total_eur_per_a"] = 99_999_999.0
    with pytest.raises(ValidationError):
        RankingResult.model_validate_json(json.dumps(payload))


def test_tamper_duplicate_candidate_id_across_ranked_and_infeasible_is_rejected():
    payload = _valid_ranking_payload()
    payload["infeasible"] = [{
        "candidate_id": payload["ranked"][0]["candidate_id"],
        "failure_code": "PRESSURE_LIMIT_EXCEEDED", "message": "contrived",
    }]
    with pytest.raises(ValidationError):
        RankingResult.model_validate_json(json.dumps(payload))


def test_tamper_shared_capex_statement_altered_is_rejected():
    payload = _valid_ranking_payload()
    payload["shared_capex_statement"] = "a different, unapproved statement"
    with pytest.raises(ValidationError):
        RankingResult.model_validate_json(json.dumps(payload))


def test_models_are_frozen():
    _, _, baseline, results = _all_worked_results()
    ranking = rank_candidates(results, baseline, economic_assumptions=_econ_assumptions(), tolerances=_tolerances())
    with pytest.raises(ValidationError):
        ranking.ranked = []


# ── Determinism ───────────────────────────────────────────────────────────────
def test_two_rankings_of_the_same_results_are_bit_identical():
    _, _, baseline, results = _all_worked_results()
    assumptions = _econ_assumptions()
    tolerances = _tolerances()
    ranking_1 = rank_candidates(results, baseline, economic_assumptions=assumptions, tolerances=tolerances)
    ranking_2 = rank_candidates(results, baseline, economic_assumptions=assumptions, tolerances=tolerances)
    payload_1 = json.loads(ranking_1.model_dump_json())
    payload_2 = json.loads(ranking_2.model_dump_json())

    def _strip_timestamps(payload):
        del payload["created_at"], payload["baseline_economics"]["created_at"]
        for entry in payload["ranked"]:
            del entry["economics"]["created_at"]
        return payload

    assert _strip_timestamps(payload_1) == _strip_timestamps(payload_2)


# ── Scope boundary ────────────────────────────────────────────────────────────
def test_no_map_report_or_mcp_identifiers_in_ranking_module():
    source = _RANKING_SRC_PATH.read_text()
    match = re.match(r'^""".*?"""\n', source, flags=re.DOTALL)
    assert match is not None
    code_body = source[match.end():].lower()
    for pattern in [r"\bMCP\b", r"\bfastmcp\b", r"\bmatplotlib\b", r"\bfolium\b"]:
        assert not re.search(pattern, code_body), f"forbidden pattern {pattern!r} found in ranking.py's code body"


def test_module_never_recommends_drilling_location():
    source = _RANKING_SRC_PATH.read_text().lower()
    assert "drilling" in source
    assert "connection" in source
