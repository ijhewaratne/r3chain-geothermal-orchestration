"""Full test matrix for network/candidate_generation.py -- CAN-001..007
deterministic candidate generation, and AC-08."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from r3chain_geothermal.adapter.heat_exchanger import HeatExchangerCouplingResult
from r3chain_geothermal.contracts import PyDoubletCouplingResult, SourceProvenance
from r3chain_geothermal.network import (
    CONSUMER_DECLARED_BASE_DISTANCE_M,
    GENERATION_EXCLUDED_ATTACHMENT_ID,
    GENERATION_MAX_ROUTE_LENGTH_M,
    GENERATION_STUDY_ID,
    BaselineNetworkResult,
    CandidateEvaluationFailure,
    CandidateEvaluationResult,
    CandidateFailureCode,
    CandidateGenerationFailureReason,
    DesignOption,
    EligibleAttachment,
    GateTolerances,
    GeneratedCandidateSpec,
    GeothermalInjectionPolicy,
    RouteOption,
    ScreenedCandidate,
    build_default_blueprint,
    eligible_attachments,
    evaluate_candidate,
    generate_candidates,
    run_baseline_evaluation,
)
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}
_CANONICAL_TRUNK_LENGTHS_M = {"trunk_1": 50.0, "trunk_2": 70.0, "trunk_3": 90.0, "trunk_4": 120.0}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _blueprint(**overrides):
    kwargs = dict(
        consumer_demands_kw=_DEMANDS, trunk_pipe_dn_mm=200.0, branch_pipe_dn_mm=100.0, design_delta_t_k=30.0,
        supply_temperature_c=70.0, return_temperature_c=40.0, ground_temperature_c=10.0,
        pipe_heat_transfer_coefficient_w_per_m2k=0.0, pipe_roughness_mm=0.1,
        p_supply_bar_abs=6.0, pump_pressure_lift_bar=3.0, created_at=datetime.now(timezone.utc),
    )
    kwargs.update(overrides)
    return build_default_blueprint(**kwargs)


def _golden_coupling_result() -> HeatExchangerCouplingResult:
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    coupling_input = parse_pydoublet_result(raw, source_provenance=provenance)
    assert isinstance(coupling_input, PyDoubletCouplingResult)
    assumptions = CouplingAssumptions.from_config_dict(_config())
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingResult)
    return result


# ── CAN-002: eligible attachments ───────────────────────────────────────────
def test_eligible_attachments_covers_all_trunk_and_consumer_junctions():
    attachments = eligible_attachments()
    ids = [a.attachment_id for a in attachments]
    assert ids == ["trunk_1", "trunk_2", "trunk_3", "trunk_4", "consumer_1", "consumer_2", "consumer_3", "consumer_4"]


def test_only_consumer_4_is_excluded():
    attachments = eligible_attachments()
    excluded_ids = {a.attachment_id for a in attachments if a.excluded}
    assert excluded_ids == {GENERATION_EXCLUDED_ATTACHMENT_ID}


def test_trunk_attachment_base_distances_match_the_canonical_c1_c4_lengths():
    """CAN-001's compatibility spirit: generated-mode trunk attachments
    reuse the EXACT SAME approved distances as the predefined C1-C4
    candidates, not a fresh invention."""
    attachments = {a.attachment_id: a for a in eligible_attachments()}
    for trunk_id, expected_length_m in _CANONICAL_TRUNK_LENGTHS_M.items():
        assert attachments[trunk_id].base_distance_m == expected_length_m


# ── CAN-007 synthetic demonstration ──────────────────────────────────────────
def test_generate_candidates_produces_the_documented_16_candidate_breakdown():
    bp = _blueprint()
    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    assert len(screened) == 16
    accepted = [s for s in screened if s.accepted]
    rejected = [s for s in screened if not s.accepted]
    assert len(accepted) == 11  # >= 4, CAN-007's own minimum, comfortably exceeded
    assert len(rejected) == 5   # >= 1, CAN-007's own minimum, comfortably exceeded
    reasons = {s.rejection_reason for s in rejected}
    assert reasons == {
        CandidateGenerationFailureReason.ROUTE_LENGTH_EXCEEDS_LIMIT,
        CandidateGenerationFailureReason.EXCLUDED_PROTECTED_GEOMETRY,
    }


def test_generate_candidates_is_deterministic_across_repeated_calls():
    bp = _blueprint()
    first = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    second = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


def test_generate_candidates_returns_candidates_sorted_by_id():
    bp = _blueprint()
    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    ids = [s.candidate_id for s in screened]
    assert ids == sorted(ids)


def test_excluded_attachment_carries_the_exact_reason_and_detail():
    bp = _blueprint()
    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    excluded = [s for s in screened if s.rejection_reason == CandidateGenerationFailureReason.EXCLUDED_PROTECTED_GEOMETRY]
    assert len(excluded) == 2  # consumer_4's two routes
    for s in excluded:
        assert GENERATION_EXCLUDED_ATTACHMENT_ID in s.candidate_id
        assert "GENERATION_EXCLUDED_ATTACHMENT_ID" in s.rejection_detail
        assert s.spec is None


def test_route_length_exceeds_limit_carries_the_measured_value_and_threshold():
    bp = _blueprint()
    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    over_limit = [s for s in screened if s.rejection_reason == CandidateGenerationFailureReason.ROUTE_LENGTH_EXCEEDS_LIMIT]
    assert len(over_limit) == 3  # consumer_1/2/3's own "diverted" route (consumer_4 already excluded)
    for s in over_limit:
        expected_length_m = CONSUMER_DECLARED_BASE_DISTANCE_M * 1.5
        assert f"{expected_length_m:.1f} m" in s.rejection_detail
        assert f"{GENERATION_MAX_ROUTE_LENGTH_M:.1f} m" in s.rejection_detail


def test_stable_candidate_id_scheme():
    bp = _blueprint()
    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    trunk_1_direct = next(s for s in screened if s.candidate_id == f"{GENERATION_STUDY_ID}-trunk_1-direct-standard")
    assert trunk_1_direct.accepted
    assert trunk_1_direct.spec.attachment_id == "trunk_1"
    assert trunk_1_direct.spec.route_id == "direct"
    assert trunk_1_direct.spec.design_option_id == "standard"
    assert trunk_1_direct.spec.study_id == GENERATION_STUDY_ID


# ── AC-08: every accepted candidate constructs and evaluates independently ──
def test_every_accepted_candidate_constructs_and_evaluates_independently():
    """Not every generated-and-screened-in candidate is TECHNICALLY
    feasible (CAN-005's pre-solve screening and CFG-004's post-solve gates
    are deliberately separate concerns) -- AC-08 only requires that each
    one CAN be constructed and evaluated without crashing. The three
    consumer-attached candidates here genuinely fail VELOCITY_LIMIT_EXCEEDED
    (their DN100 branch pipes, sized only for consumer demand, cannot also
    carry the injection flow) -- a real technical finding, not a defect in
    this test."""
    bp = _blueprint()
    baseline_result = run_baseline_evaluation(bp, tolerances=GateTolerances.from_config_dict(_config()))
    assert isinstance(baseline_result, BaselineNetworkResult)
    coupling_result = _golden_coupling_result()
    policy = GeothermalInjectionPolicy.from_config_dict(_config())
    tolerances = GateTolerances.from_config_dict(_config())

    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    accepted = [s for s in screened if s.accepted]
    assert len(accepted) == 11

    outcomes: dict[str, str] = {}
    for s in accepted:
        blueprint_candidate = s.spec.to_blueprint_candidate()
        result = evaluate_candidate(
            coupling_result, bp, blueprint_candidate, baseline_result,
            injection_policy=policy, tolerances=tolerances,
        )
        assert isinstance(result, (CandidateEvaluationResult, CandidateEvaluationFailure))
        outcomes[s.candidate_id] = (
            "feasible" if isinstance(result, CandidateEvaluationResult) else result.failure_code.value
        )

    trunk_ids = [cid for cid in outcomes if "-trunk_" in cid]
    consumer_ids = [cid for cid in outcomes if "-consumer_" in cid]
    assert len(trunk_ids) == 8
    assert len(consumer_ids) == 3
    assert all(outcomes[cid] == "feasible" for cid in trunk_ids)
    assert all(outcomes[cid] == CandidateFailureCode.VELOCITY_LIMIT_EXCEEDED.value for cid in consumer_ids)


def test_trunk_direct_candidate_matches_the_predefined_c1_result_exactly():
    """The strongest form of the CAN-001 compatibility claim: the
    generated "trunk_1-direct" candidate and the predefined C1 candidate
    are the SAME junction pair and length, so their evaluation results
    must be numerically identical."""
    import math
    from r3chain_geothermal.network import BlueprintCandidate

    bp = _blueprint()
    baseline_result = run_baseline_evaluation(bp, tolerances=GateTolerances.from_config_dict(_config()))
    assert isinstance(baseline_result, BaselineNetworkResult)
    coupling_result = _golden_coupling_result()
    policy = GeothermalInjectionPolicy.from_config_dict(_config())
    tolerances = GateTolerances.from_config_dict(_config())

    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    trunk_1_direct = next(s for s in screened if s.candidate_id == f"{GENERATION_STUDY_ID}-trunk_1-direct-standard")
    generated_result = evaluate_candidate(
        coupling_result, bp, trunk_1_direct.spec.to_blueprint_candidate(), baseline_result,
        injection_policy=policy, tolerances=tolerances,
    )
    c1 = BlueprintCandidate(id="C1", label="Near network head", supply_junction="trunk_1", return_junction="ret_trunk_1", surface_connection_length_m=50.0)
    predefined_result = evaluate_candidate(
        coupling_result, bp, c1, baseline_result, injection_policy=policy, tolerances=tolerances,
    )
    assert isinstance(generated_result, CandidateEvaluationResult) and isinstance(predefined_result, CandidateEvaluationResult)
    assert math.isclose(generated_result.total_heat_delivered_kw, predefined_result.total_heat_delivered_kw, rel_tol=1e-12)
    assert math.isclose(generated_result.min_pressure_bar_abs, predefined_result.min_pressure_bar_abs, rel_tol=1e-12)
    assert math.isclose(generated_result.max_velocity_m_s, predefined_result.max_velocity_m_s, rel_tol=1e-12)


# ── Contrived reachability for the remaining CAN-005 reason codes ──────────
def test_missing_supply_return_pair_reachable_via_a_broken_blueprint():
    bp = _blueprint()
    broken_junctions = {k: v for k, v in bp.junctions.items() if k != "ret_trunk_2"}
    broken_bp = bp.model_copy(update={"junctions": broken_junctions})
    screened = generate_candidates(broken_bp, connection_pipe_dn_mm=200.0)
    trunk_2_results = [s for s in screened if "trunk_2" in s.candidate_id]
    assert all(s.rejection_reason == CandidateGenerationFailureReason.MISSING_SUPPLY_RETURN_PAIR for s in trunk_2_results)
    assert all(not s.accepted for s in trunk_2_results)


def test_missing_pipe_or_design_data_reachable_via_a_non_positive_dn():
    bp = _blueprint()
    screened = generate_candidates(bp, connection_pipe_dn_mm=0.0)
    assert len(screened) > 0
    assert all(s.rejection_reason == CandidateGenerationFailureReason.MISSING_PIPE_OR_DESIGN_DATA for s in screened if not s.accepted)
    assert all(not s.accepted for s in screened)  # every candidate needs a design option; all screened out


def test_duplicate_topology_reachable_via_monkeypatched_route_multipliers(monkeypatch):
    import r3chain_geothermal.network.candidate_generation as gen_module
    monkeypatch.setattr(gen_module, "_ROUTE_MULTIPLIERS", {"direct": 1.0, "diverted": 1.0})
    bp = _blueprint()
    screened = generate_candidates(bp, connection_pipe_dn_mm=200.0)
    duplicates = [s for s in screened if s.rejection_reason == CandidateGenerationFailureReason.DUPLICATE_TOPOLOGY]
    assert len(duplicates) > 0
    for s in duplicates:
        assert "identical to" in s.rejection_detail


def test_invalid_pressure_zone_pairing_and_component_construction_conflict_are_constructible_reasons():
    """These two reasons never occur in generate_candidates()'s own
    output against any blueprint this generator can build (module
    docstring, "Screening") -- this test proves the TYPE itself accepts
    them as valid, well-formed rejections (the code path CAN-005 asks for
    exists and is exercised, even though this synthetic network's own
    single pressure zone and this generator's own uniqueness-by-
    construction loop never trigger them)."""
    for reason in (
        CandidateGenerationFailureReason.INVALID_PRESSURE_ZONE_PAIRING,
        CandidateGenerationFailureReason.COMPONENT_CONSTRUCTION_CONFLICT,
    ):
        screened = ScreenedCandidate(
            candidate_id="contrived", accepted=False, spec=None,
            rejection_reason=reason, rejection_detail="contrived for reachability testing",
        )
        assert screened.rejection_reason == reason
        restored = ScreenedCandidate.model_validate_json(screened.model_dump_json())
        assert restored == screened


def test_all_seven_failure_reasons_declared():
    assert len(CandidateGenerationFailureReason) == 7


# ── Model validation ─────────────────────────────────────────────────────────
def test_eligible_attachment_rejects_non_positive_base_distance():
    with pytest.raises(ValidationError):
        EligibleAttachment(attachment_id="x", supply_junction="a", return_junction="b", category="trunk", base_distance_m=0.0)


def test_eligible_attachment_rejects_excluded_without_reason():
    with pytest.raises(ValidationError):
        EligibleAttachment(
            attachment_id="x", supply_junction="a", return_junction="b", category="trunk",
            base_distance_m=10.0, excluded=True, exclusion_reason=None,
        )


def test_route_option_raises_for_unimplemented_kinds():
    for kind in ("network_graph", "external_gis"):
        route = RouteOption(route_id="direct", kind=kind, length_multiplier=1.0)
        with pytest.raises(NotImplementedError):
            route.resolve_length_m(100.0)


def test_route_option_synthetic_direct_is_a_pure_multiplication():
    route = RouteOption(route_id="diverted", length_multiplier=1.5)
    assert route.resolve_length_m(100.0) == 150.0


def test_design_option_rejects_non_positive_dn():
    with pytest.raises(ValidationError):
        DesignOption(connection_pipe_dn_mm=0.0)


def test_screened_candidate_requires_spec_when_accepted():
    with pytest.raises(ValidationError):
        ScreenedCandidate(candidate_id="x", accepted=True, spec=None, rejection_reason=None, rejection_detail="")


def test_screened_candidate_requires_reason_when_rejected():
    with pytest.raises(ValidationError):
        ScreenedCandidate(candidate_id="x", accepted=False, spec=None, rejection_reason=None, rejection_detail="")


def test_generated_candidate_spec_to_blueprint_candidate():
    spec = GeneratedCandidateSpec(
        candidate_id="gen-1", study_id=GENERATION_STUDY_ID, attachment_id="trunk_1", route_id="direct",
        design_option_id="standard", supply_junction="trunk_1", return_junction="ret_trunk_1",
        surface_connection_length_m=50.0, connection_pipe_dn_mm=200.0,
    )
    bc = spec.to_blueprint_candidate(label="custom label")
    assert bc.id == "gen-1"
    assert bc.label == "custom label"
    assert bc.supply_junction == "trunk_1"
    assert bc.surface_connection_length_m == 50.0
