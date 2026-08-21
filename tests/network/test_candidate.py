"""Full test matrix for network/candidate.py -- the T2.3 independent
geothermal candidate evaluator."""
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
from r3chain_geothermal.contracts import PyDoubletCouplingResult, SourceProvenance
from r3chain_geothermal.network import (
    CONNECTION_PIPE_DN_MM,
    PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED,
    BaselineNetworkResult,
    BlueprintCandidate,
    CandidateEvaluationFailure,
    CandidateEvaluationResult,
    CandidateFailureCode,
    GateTolerances,
    GeothermalInjectionPolicy,
    build_default_blueprint,
    evaluate_candidate,
    parse_candidate_result_json,
    run_baseline_evaluation,
)
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_CANDIDATE_SRC_PATH = _ROOT / "src" / "r3chain_geothermal" / "network" / "candidate.py"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_DEMANDS = {"consumer_1": 650.0, "consumer_2": 750.0, "consumer_3": 850.0, "consumer_4": 950.0}


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _tolerances() -> GateTolerances:
    return GateTolerances.from_config_dict(_config())


def _policy(**overrides) -> GeothermalInjectionPolicy:
    base = dict(
        curtailment_allowed=True, auxiliary_policy="cost_shortfall",
        minimum_auxiliary_circulation_fraction=0.01,
    )
    base.update(overrides)
    return GeothermalInjectionPolicy(**base)


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
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired", calculation_mode="deterministic",
    )
    coupling_input = parse_pydoublet_result(raw, source_provenance=provenance)
    assert isinstance(coupling_input, PyDoubletCouplingResult)

    config = _config()
    assumptions = CouplingAssumptions.from_config_dict(config)
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


def _strict_json_loads(text: str):
    def _reject(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")
    return json.loads(text, parse_constant=_reject)


_CANDIDATES = {
    "C1": ("trunk_1", "ret_trunk_1", 50.0),
    "C2": ("trunk_2", "ret_trunk_2", 70.0),
    "C3": ("trunk_3", "ret_trunk_3", 90.0),
    "C4": ("trunk_4", "ret_trunk_4", 120.0),
}


def _candidate(candidate_id: str) -> BlueprintCandidate:
    supply, ret, length = _CANDIDATES[candidate_id]
    return BlueprintCandidate(
        id=candidate_id, label=candidate_id, supply_junction=supply, return_junction=ret,
        surface_connection_length_m=length,
    )


# ── The worked case: all four real candidates against the real 3.2277 MW
# geothermal result -- this evaluates network CONNECTION location, not
# drilling location (module docstring, plan "Executive decision"). ──
@pytest.mark.parametrize("candidate_id", list(_CANDIDATES))
def test_worked_case_all_candidates_converge_with_correct_kpis(candidate_id):
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate(candidate_id), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult), result

    # 99% curtailment ceiling binds (deliverable ~3227.7 kW > 99% of
    # 3200 kW demand) -- coverage is exactly the ceiling, not 1.0.
    assert math.isclose(result.geothermal_coverage_fraction, 0.99, rel_tol=1e-9)
    assert math.isclose(result.geothermal_injected_heat_kw, 3200.0 * 0.99, rel_tol=1e-9)
    assert result.geothermal_curtailed_heat_kw > 0
    assert math.isclose(
        result.geothermal_curtailed_heat_kw,
        coupling_result.deliverable_geothermal_heat_kw.value - 3200.0 * 0.99,
        rel_tol=1e-9,
    )
    assert result.connection_pipe_dn_mm == CONNECTION_PIPE_DN_MM
    assert result.connection_pumping_power_kw > 0
    assert result.connection_pressure_drop_bar >= 0

    # doublet pump electricity preserved unchanged, top-level and nested agree.
    expected_doublet_kw = coupling_result.coupling_input.doublet_pump_electric_power_kw.value
    assert result.doublet_pump_electric_power_kw == expected_doublet_kw
    assert result.coupling_input.coupling_input.doublet_pump_electric_power_kw.value == expected_doublet_kw

    # every consumer still receives full design demand.
    assert math.isclose(result.total_heat_delivered_kw, 3200.0, rel_tol=1e-9)
    for consumer_id, demand_kw in _DEMANDS.items():
        assert math.isclose(result.consumers[consumer_id].heat_delivered_kw, demand_kw, rel_tol=1e-9)


def test_worked_case_connection_pressure_drop_increases_with_connection_length():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    drops = {}
    for candidate_id in ("C1", "C2", "C3", "C4"):
        result = evaluate_candidate(
            coupling_result, bp, _candidate(candidate_id), baseline,
            injection_policy=_policy(), tolerances=_tolerances(),
        )
        assert isinstance(result, CandidateEvaluationResult)
        drops[candidate_id] = result.connection_pressure_drop_bar
    assert drops["C1"] < drops["C2"] < drops["C3"] < drops["C4"]


def test_worked_case_exposes_the_discovered_temperature_anchoring_behaviour():
    """The ~36 degC actual return / ~66 degC actual supply behaviour
    (documented in docs/technical-observations/pandapipes-circulation-pump-direction-check.md
    and network/candidate.py's own module docstring) must be directly
    visible on the typed result, not only in prose -- this test locks in
    the exact measured values at C1, 1% margin, alongside the design
    targets and their deviations."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult)

    assert result.geothermal_injection_inlet_design_temperature_c == 40.0
    assert result.geothermal_injection_outlet_design_temperature_c == 70.0
    assert math.isclose(result.geothermal_injection_inlet_temperature_c, 36.002632892983115, rel_tol=1e-6)
    assert math.isclose(result.geothermal_injection_outlet_temperature_c, 65.97389649005743, rel_tol=1e-6)
    assert math.isclose(
        result.geothermal_injection_inlet_temperature_deviation_k,
        result.geothermal_injection_inlet_temperature_c - 40.0, rel_tol=1e-9,
    )
    assert math.isclose(
        result.geothermal_injection_outlet_temperature_deviation_k,
        result.geothermal_injection_outlet_temperature_c - 70.0, rel_tol=1e-9,
    )
    # Both deviations are negative -- the branch runs colder than design at
    # both ends, exactly the mechanism the stabilization warning describes.
    assert result.geothermal_injection_inlet_temperature_deviation_k < 0
    assert result.geothermal_injection_outlet_temperature_deviation_k < 0

    # The warning text must name BOTH mechanisms, not only the pandapipes
    # solver check.
    matching = [w for w in result.warnings if w.code == PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED]
    assert len(matching) == 1
    message_lower = matching[0].message.lower()
    assert "direction-change" in message_lower or "direction change" in message_lower
    assert "anchor" in message_lower


def test_worked_case_doublet_pump_electric_power_identical_across_candidates():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    values = set()
    for candidate_id in ("C1", "C2", "C3", "C4"):
        result = evaluate_candidate(
            coupling_result, bp, _candidate(candidate_id), baseline,
            injection_policy=_policy(), tolerances=_tolerances(),
        )
        assert isinstance(result, CandidateEvaluationResult)
        values.add(result.doublet_pump_electric_power_kw)
    assert len(values) == 1


# ── Solver-stability curtailment warning ─────────────────────────────────────
def test_stabilization_warning_present_in_worked_case():
    """The worked case's 99%-cap curtailment is entirely the solver-
    stability margin (deliverable ~3227.7 kW exceeds demand 3200.0 kW, so
    the margin -- not the raw deliverable value -- is what caps injection
    at exactly 99% of demand) -- the warning must be present, exactly
    once, and must name the two KPIs it affects."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult)
    matching = [w for w in result.warnings if w.code == PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED]
    assert len(matching) == 1
    assert set(matching[0].affects) == {"geothermal_injected_heat_kw", "geothermal_curtailed_heat_kw"}


def test_stabilization_warning_absent_when_fraction_is_zero():
    """With minimum_auxiliary_circulation_fraction=0.0, curtailment (if any)
    is driven entirely by the true deliverable-vs-demand relationship --
    no stability margin is applied, so the warning must not appear. (This
    scenario is expected to hit the exact-100%-coverage pandapipes
    direction-change failure -- see the dedicated hydraulic-conflict test
    -- so this test only checks the warning's ABSENCE on whichever
    failure/success outcome results, not that it succeeds.)"""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(minimum_auxiliary_circulation_fraction=0.0), tolerances=_tolerances(),
    )
    if isinstance(result, CandidateEvaluationResult):
        codes = {w.code for w in result.warnings}
        assert PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED not in codes


def test_stabilization_warning_absent_in_shortfall_case():
    bp = _blueprint()
    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result(hx_heat_delivery_factor=0.3)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult)
    codes = {w.code for w in result.warnings}
    assert PANDAPIPES_MINIMUM_AUXILIARY_FLOW_STABILIZATION_APPLIED not in codes


# ── Injected+curtailed must equal deliverable_geothermal_heat_kw exactly --
# NEVER an inequality claim against raw PyDoublet power (a prior version of
# this evaluator's own model invariant wrongly rejected the legitimate case
# where deliverable_geothermal_heat_kw == raw_geothermal_thermal_power_kw;
# see adapter/heat_exchanger.py's own precedent,
# test_deliverable_heat_may_equal_raw_power_when_factor_is_one_and_raw_power_binds,
# commit 81319978 "fix: allow coincidentally equal coupling quantities"). ──
def test_golden_case_injected_plus_curtailed_differs_from_raw_power():
    """A numeric fact of the GOLDEN worked example specifically (temperature-
    limited binding + a 0.98 delivery factor) -- NOT a general contract
    rule. See test_injected_plus_curtailed_may_equal_raw_power_when_binding_matches
    for the equality-acceptance case, which is equally valid."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    raw_power_kw = coupling_result.coupling_input.raw_geothermal_thermal_power_kw.value
    deliverable_kw = coupling_result.deliverable_geothermal_heat_kw.value
    assert not math.isclose(raw_power_kw, deliverable_kw, rel_tol=0.05)  # sanity: golden fixture really does differ

    baseline = _baseline(bp)
    for candidate_id in ("C1", "C2", "C3", "C4"):
        result = evaluate_candidate(
            coupling_result, bp, _candidate(candidate_id), baseline,
            injection_policy=_policy(), tolerances=_tolerances(),
        )
        assert isinstance(result, CandidateEvaluationResult)
        total = result.geothermal_injected_heat_kw + result.geothermal_curtailed_heat_kw
        # The one universally-true rule: total == deliverable, always.
        assert math.isclose(total, deliverable_kw, rel_tol=1e-9)


def test_injected_plus_curtailed_may_equal_raw_power_when_binding_matches():
    """Equality-acceptance test, mirroring T2.1's own precedent exactly
    (adapter/heat_exchanger.py::test_deliverable_heat_may_equal_raw_power_when_factor_is_one_and_raw_power_binds,
    commit 81319978): with hx_heat_delivery_factor=1.0 and assumptions that
    make the raw-power term bind (dh_return_temperature_c=10.0,
    reinjection_minimum_temperature_c=20.0), T2.1 legitimately produces
    deliverable_geothermal_heat_kw == raw_geothermal_thermal_power_kw
    exactly. evaluate_candidate() must ACCEPT this and succeed -- the rule
    is "the chain feeds from deliverable_geothermal_heat_kw", not "raw and
    deliverable must differ"."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result(
        dh_return_temperature_c=10.0, reinjection_minimum_temperature_c=20.0, hx_heat_delivery_factor=1.0,
    )
    assert coupling_result.deliverable_heat_binding_constraint == "pydoublet_reported_power"
    raw_power_kw = coupling_result.coupling_input.raw_geothermal_thermal_power_kw.value
    deliverable_kw = coupling_result.deliverable_geothermal_heat_kw.value
    assert deliverable_kw == raw_power_kw  # exact equality, the legitimate case

    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult), result
    total = result.geothermal_injected_heat_kw + result.geothermal_curtailed_heat_kw
    assert math.isclose(total, deliverable_kw, rel_tol=1e-9)
    assert math.isclose(total, raw_power_kw, rel_tol=1e-9)  # equality is fine here -- not rejected

    # Round-trips and re-validates cleanly -- equality is not rejected
    # anywhere in the boundary, including on reparse.
    restored = parse_candidate_result_json(result.model_dump_json())
    assert restored == result


# ── Sensitivity: nearby minimum_auxiliary_circulation_fraction values do
# not change any candidate's feasibility conclusion, ABOVE a second,
# separately-discovered boundary ────────────────────────────────────────────
#
# Investigation (not assumed): sweeping the fraction below the chosen 1%
# reveals a SECOND, distinct failure mechanism -- not the pandapipes
# direction-change check (that is a hydraulic/pressure-solve issue), but a
# genuine CONSUMER_TEMPERATURE_NOT_MET failure. Root cause, traced directly
# (not guessed): as the fraction shrinks, the main plant pump's own share
# of total network flow shrinks toward zero, so the network's thermal
# field is increasingly dominated by the geothermal injection branch's own
# OUTPUT temperature -- which is NOT exactly the design 70 degC supply
# temperature, because _compute_injected_mass_flow_kg_s sizes the
# injection's mass flow assuming a fixed 30 K rise from the DESIGN return
# temperature (40 degC), while the branch's ACTUAL inlet temperature
# (ret_trunk_N, a real mixed-flow result) is measurably colder once the
# main pump's anchoring flow shrinks (verified directly: at
# fraction=0.01, ret_trunk_1 solves to 36.00 degC, not 40.00 degC; the
# resulting geo_supply_C1 output is 65.97 degC, not 70.00 degC). This
# under-temperature then propagates through the trunk to EVERY consumer
# (verified: the failure is always at consumer_1, the plant-nearest
# consumer, for ALL FOUR candidates, with IDENTICAL drop_k magnitudes per
# fraction across candidates -- because the injected kW/mass-flow amount
# itself does not depend on which candidate is being evaluated, only on
# the fraction). This is DISTINCT from, and in addition to, the pandapipes
# direction-change reason documented in
# docs/technical-observations/pandapipes-circulation-pump-direction-check.md
# -- both independently justify keeping minimum_auxiliary_circulation_fraction
# no smaller than the chosen 0.01.
#
# Precisely characterized boundary (all four candidates, consumer_1 in every
# failing case): 0.003 -> drop_k=19.54, 0.005 -> drop_k=9.27,
# 0.0075 -> drop_k=5.58 (still just over the 5.0 K gate), 0.01 -> feasible
# (drop_k=3.99 for C1, 4.17 for C2/C3/C4 -- the chosen value's own margin
# is real but thin, ~0.8-1.0 K of the 5.0 K budget, ~17-20% headroom, not
# a large safety margin).
@pytest.mark.parametrize("fraction", [0.01, 0.02, 0.05])
def test_sensitivity_nearby_fractions_at_or_above_chosen_value_preserve_feasibility(fraction):
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    connection_pressure_drops = {}
    for candidate_id in ("C1", "C2", "C3", "C4"):
        result = evaluate_candidate(
            coupling_result, bp, _candidate(candidate_id), baseline,
            injection_policy=_policy(minimum_auxiliary_circulation_fraction=fraction),
            tolerances=_tolerances(),
        )
        assert isinstance(result, CandidateEvaluationResult), (
            f"candidate {candidate_id!r} became infeasible at "
            f"minimum_auxiliary_circulation_fraction={fraction!r} (result: {result!r})"
        )
        # Coverage should track (1 - fraction) exactly, since the golden
        # deliverable always exceeds demand -- confirms the sensitivity
        # sweep is actually exercising the stabilization ceiling, not
        # silently no-op'ing.
        assert math.isclose(result.geothermal_coverage_fraction, 1.0 - fraction, rel_tol=1e-9)
        connection_pressure_drops[candidate_id] = result.connection_pressure_drop_bar

    # The physically expected connection_pressure_drop_bar ordering (C1's
    # 50 m connection < C2's 70 m < C3's 90 m < C4's 120 m) must hold at
    # every tested margin, not just the chosen 1% -- the ranking a later
    # (out-of-scope) economics/ranking layer would consume must not be an
    # artifact of one specific fraction.
    assert (
        connection_pressure_drops["C1"] < connection_pressure_drops["C2"]
        < connection_pressure_drops["C3"] < connection_pressure_drops["C4"]
    ), connection_pressure_drops


@pytest.mark.parametrize("fraction,expected_drop_k", [(0.003, 19.54), (0.005, 9.27), (0.0075, 5.58)])
def test_sensitivity_below_chosen_value_fails_consumer_temperature_not_pressure(fraction, expected_drop_k):
    """Below the chosen 1% margin, ALL FOUR candidates fail --
    CONSUMER_TEMPERATURE_NOT_MET at consumer_1, never
    GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT -- confirming this is the
    SEPARATE temperature-anchoring mechanism (module comment above), not
    the pandapipes direction-change failure the margin was originally
    chosen to avoid. Locks in the precisely-measured boundary so a future
    change to the topology/formula that shifts this boundary is caught."""
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    for candidate_id in ("C1", "C2", "C3", "C4"):
        result = evaluate_candidate(
            coupling_result, bp, _candidate(candidate_id), baseline,
            injection_policy=_policy(minimum_auxiliary_circulation_fraction=fraction),
            tolerances=_tolerances(),
        )
        assert isinstance(result, CandidateEvaluationFailure)
        assert result.failure_code == CandidateFailureCode.CONSUMER_TEMPERATURE_NOT_MET
        assert result.details["consumer_id"] == "consumer_1"
        assert math.isclose(result.details["supply_temperature_drop_k"], expected_drop_k, rel_tol=1e-3)


# ── Shortfall path (cost_shortfall auxiliary policy) ────────────────────────
def test_shortfall_path_auxiliary_covers_the_gap():
    bp = _blueprint()
    baseline = _baseline(bp)
    # Shrink the heat-exchanger delivery factor so deliverable heat drops
    # well below the 3200 kW baseline demand -- a genuine, independently
    # re-evaluated shortfall, not a hand-tampered value.
    coupling_result = _golden_coupling_result(hx_heat_delivery_factor=0.3)
    assert coupling_result.deliverable_geothermal_heat_kw.value < baseline.total_heat_delivered_kw

    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult), result
    assert result.geothermal_curtailed_heat_kw == 0.0
    assert result.geothermal_coverage_fraction < 1.0
    assert result.auxiliary_heat_kw > 0.0
    assert result.unmet_heat_kw == 0.0
    assert math.isclose(
        result.auxiliary_heat_kw, result.total_heat_delivered_kw - result.geothermal_injected_heat_kw,
        rel_tol=1e-9,
    )
    # main pump now covers less than the baseline's own full demand.
    assert result.circulation_pump.mass_flow_kg_s < baseline.circulation_pump.mass_flow_kg_s
    assert result.kpi_deltas.main_pump_mass_flow_delta_kg_s < 0


# ── GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT -- the exact pandapipes
# limitation the curtailment ceiling is designed to avoid (module
# docstring, "Curtailment"), reachable via an insufficient margin. ──
def test_geothermal_injection_hydraulic_conflict_via_insufficient_margin():
    bp = _blueprint()
    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result()
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(minimum_auxiliary_circulation_fraction=1e-9),
        tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationFailure), result
    assert result.failure_code == CandidateFailureCode.GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT


# ── Inherited gate failures (reusing CandidateFailureCode's shared codes) ──
def test_thermal_pipeflow_not_converged_via_undersized_connection_pipe(monkeypatch):
    """Distinct from GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT (a UserWarning
    the main pump's own direction check raises on an otherwise-converged
    solution) -- this is a genuine pandapipes.PipeflowNotConverged from the
    hydraulic solve itself, forced by an absurdly undersized connection
    pipe (1.0 mm, vs. the real 200.0 mm) at the candidate's own injection
    branch, with a baseline that converges normally."""
    import r3chain_geothermal.network.candidate as candidate_module
    monkeypatch.setattr(candidate_module, "CONNECTION_PIPE_DN_MM", 1.0)

    bp = _blueprint()
    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result()
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationFailure)
    assert result.failure_code == CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED


def test_velocity_limit_exceeded_via_undersized_connection_pipe(monkeypatch):
    """A smaller (but not solver-breaking) connection DN pushes the two
    connection pipes' own velocity over gates.max_pipe_velocity_m_s while
    the rest of the (baseline-identical) network stays fine -- a genuine
    candidate-specific velocity failure, distinct from T2.2B's own
    trunk/branch-pipe velocity tests."""
    # 140.0 mm: chosen so the pressure gate (checked first, in plan §11
    # order) still passes (min_pressure_bar_abs=2.938 >= 1.5) while the
    # connection pipes' own velocity crosses 1.5 m/s -- an undersized DN
    # of 50.0 mm was tried first and instead tripped PRESSURE_LIMIT_EXCEEDED
    # before velocity was ever reached, which would have tested the wrong
    # gate.
    import r3chain_geothermal.network.candidate as candidate_module
    monkeypatch.setattr(candidate_module, "CONNECTION_PIPE_DN_MM", 140.0)

    bp = _blueprint()
    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result()
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationFailure)
    assert result.failure_code == CandidateFailureCode.VELOCITY_LIMIT_EXCEEDED
    assert result.details["pipe"] == "geo_supply_connection_C1"


def test_all_seven_failure_codes_reachable():
    """Enumerates CandidateFailureCode and cross-checks it against the
    dedicated failure-path tests above -- if a new code is ever added to
    the enum without a corresponding reachability test, this test's own
    membership assertion documents the gap explicitly rather than passing
    silently."""
    covered = {
        CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED,
        CandidateFailureCode.CONSUMER_TEMPERATURE_NOT_MET,
        CandidateFailureCode.PRESSURE_LIMIT_EXCEEDED,
        CandidateFailureCode.VELOCITY_LIMIT_EXCEEDED,
        CandidateFailureCode.MASS_BALANCE_FAILED,
        CandidateFailureCode.ENERGY_BALANCE_FAILED,
        CandidateFailureCode.GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT,
    }
    assert covered == set(CandidateFailureCode)
    assert len(covered) == 7


def test_consumer_temperature_not_met():
    bp = _blueprint(pipe_heat_transfer_coefficient_w_per_m2k=10.0)
    baseline_bp_result = run_baseline_evaluation(bp, tolerances=_tolerances())
    # A non-adiabatic baseline may itself fail CONSUMER_TEMPERATURE_NOT_MET;
    # if so the candidate evaluator is exercised with a genuinely different,
    # still-converging baseline built at a smaller heat-loss coefficient
    # so the baseline itself succeeds and the candidate net is what fails.
    if not isinstance(baseline_bp_result, BaselineNetworkResult):
        bp = _blueprint(pipe_heat_transfer_coefficient_w_per_m2k=2.0)
    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result()
    tight = _tolerances().model_copy(update={"max_consumer_supply_drop_k": 1e-9})
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=tight,
    )
    assert isinstance(result, CandidateEvaluationFailure)
    assert result.failure_code == CandidateFailureCode.CONSUMER_TEMPERATURE_NOT_MET


def test_pressure_limit_exceeded():
    # p_supply_bar_abs=4.51: chosen so the BASELINE itself still passes its
    # own pressure gate (min_pressure_bar_abs=1.51 >= gates.min_pressure_bar_abs=1.5)
    # while the CANDIDATE's extra injection-branch connection-pipe friction
    # loss pushes its own minimum below the same gate -- a genuine
    # candidate-specific failure, not a baseline failure reused. The exact
    # failing junction/value are asserted below (not just the failure code)
    # -- a prior report of this test mistakenly quoted a PASSING candidate's
    # value (1.506 bar abs, from p_supply_bar_abs=4.52) as if it were this
    # scenario's failing value; this assertion pins the real number down so
    # that mistake cannot recur silently.
    bp = _blueprint(p_supply_bar_abs=4.51)
    baseline_bp_result = run_baseline_evaluation(bp, tolerances=_tolerances())
    assert isinstance(baseline_bp_result, BaselineNetworkResult)
    baseline = baseline_bp_result
    assert baseline.min_pressure_bar_abs >= _tolerances().min_pressure_bar_abs
    coupling_result = _golden_coupling_result()
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationFailure)
    assert result.failure_code == CandidateFailureCode.PRESSURE_LIMIT_EXCEEDED
    assert result.details["junction"] == "geo_return_C1"
    assert result.details["min_pressure_bar_abs"] == _tolerances().min_pressure_bar_abs == 1.5
    assert result.details["pressure_bar_abs"] < 1.5
    assert math.isclose(result.details["pressure_bar_abs"], 1.4962070042036113, rel_tol=1e-9)


def test_mass_balance_failed_via_artificially_tight_tolerance():
    bp = _blueprint()
    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result()
    tight = _tolerances().model_copy(update={"mass_balance_tolerance_fraction": 1e-18})
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=tight,
    )
    assert isinstance(result, CandidateEvaluationFailure)
    assert result.failure_code == CandidateFailureCode.MASS_BALANCE_FAILED


def test_energy_balance_failed_via_artificially_tight_tolerance():
    bp = _blueprint()
    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result()
    tight = _tolerances().model_copy(update={"energy_balance_tolerance_fraction": 1e-18})
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=tight,
    )
    assert isinstance(result, CandidateEvaluationFailure)
    assert result.failure_code == CandidateFailureCode.ENERGY_BALANCE_FAILED


def test_evaluation_never_raises_for_any_contrived_input():
    scenarios = [
        _blueprint(consumer_demands_kw={**_DEMANDS, "consumer_1": 1e9}),
        _blueprint(p_supply_bar_abs=4.4),
        _blueprint(p_supply_bar_abs=10.0, trunk_pipe_dn_mm=100.0),
    ]
    for bp in scenarios:
        baseline_bp_result = run_baseline_evaluation(bp, tolerances=_tolerances())
        if not isinstance(baseline_bp_result, BaselineNetworkResult):
            continue  # a candidate needs a converging baseline as its own input
        coupling_result = _golden_coupling_result()
        result = evaluate_candidate(
            coupling_result, bp, _candidate("C1"), baseline_bp_result,
            injection_policy=_policy(), tolerances=_tolerances(),
        )
        assert isinstance(result, (CandidateEvaluationResult, CandidateEvaluationFailure))


# ── GeothermalInjectionPolicy validation ────────────────────────────────────
def test_policy_from_config_dict_reads_real_config():
    policy = GeothermalInjectionPolicy.from_config_dict(_config())
    assert policy.curtailment_allowed is True
    assert policy.auxiliary_policy == "cost_shortfall"
    assert math.isclose(policy.minimum_auxiliary_circulation_fraction, 0.01)


def test_policy_rejects_curtailment_disabled():
    with pytest.raises(ValidationError):
        _policy(curtailment_allowed=False)


def test_policy_rejects_strict_infeasible_auxiliary_policy():
    with pytest.raises(ValidationError):
        _policy(auxiliary_policy="strict_infeasible")


@pytest.mark.parametrize("bad_value", [-0.1, 1.0, 1.5])
def test_policy_rejects_out_of_range_minimum_auxiliary_circulation_fraction(bad_value):
    with pytest.raises(ValidationError):
        _policy(minimum_auxiliary_circulation_fraction=bad_value)


# ── Determinism and independence across C1-C4 ───────────────────────────────
def test_evaluation_does_not_mutate_blueprint_or_coupling_result():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    bp_snapshot = bp.model_dump_json()
    coupling_snapshot = coupling_result.model_dump_json()
    for candidate_id in ("C1", "C2", "C3", "C4"):
        evaluate_candidate(
            coupling_result, bp, _candidate(candidate_id), baseline,
            injection_policy=_policy(), tolerances=_tolerances(),
        )
    assert bp.model_dump_json() == bp_snapshot
    assert coupling_result.model_dump_json() == coupling_snapshot


def test_two_evaluations_of_the_same_candidate_are_bit_identical():
    fixed_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bp = _blueprint(created_at=fixed_created_at)
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)

    result_1 = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    result_2 = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result_1, CandidateEvaluationResult) and isinstance(result_2, CandidateEvaluationResult)
    payload_1 = json.loads(result_1.model_dump_json())
    payload_2 = json.loads(result_2.model_dump_json())
    del payload_1["created_at"], payload_2["created_at"]
    del payload_1["coupling_input"]["created_at"], payload_2["coupling_input"]["created_at"]
    del payload_1["coupling_input"]["coupling_input"]["created_at"], payload_2["coupling_input"]["coupling_input"]["created_at"]
    assert payload_1 == payload_2


def test_candidates_evaluated_in_reverse_order_are_bit_identical_to_forward_order():
    fixed_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bp = _blueprint(created_at=fixed_created_at)
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)

    def _run(order):
        results = {}
        for candidate_id in order:
            r = evaluate_candidate(
                coupling_result, bp, _candidate(candidate_id), baseline,
                injection_policy=_policy(), tolerances=_tolerances(),
            )
            assert isinstance(r, CandidateEvaluationResult)
            payload = json.loads(r.model_dump_json())
            del payload["created_at"]
            del payload["coupling_input"]["created_at"]
            del payload["coupling_input"]["coupling_input"]["created_at"]
            results[candidate_id] = payload
        return results

    forward = _run(["C1", "C2", "C3", "C4"])
    reverse = _run(["C4", "C3", "C2", "C1"])
    assert forward == reverse


# ── Strict-JSON round trip ───────────────────────────────────────────────────
def test_strict_json_round_trip_for_success():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult)
    dumped = result.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["status"] == "success"
    restored = parse_candidate_result_json(dumped)
    assert isinstance(restored, CandidateEvaluationResult)
    assert restored == result


@pytest.mark.parametrize("failure_code", list(CandidateFailureCode))
def test_strict_json_round_trip_for_failure_codes(failure_code, monkeypatch):
    """Covers all seven CandidateFailureCode values -- one dedicated,
    independently-verified scenario per code, matching the scenario used
    in that code's own dedicated failure test above."""
    import r3chain_geothermal.network.candidate as candidate_module

    bp = _blueprint()
    tolerances = _tolerances()
    policy = _policy()

    if failure_code == CandidateFailureCode.MASS_BALANCE_FAILED:
        tolerances = tolerances.model_copy(update={"mass_balance_tolerance_fraction": 1e-18})
    elif failure_code == CandidateFailureCode.ENERGY_BALANCE_FAILED:
        tolerances = tolerances.model_copy(update={"energy_balance_tolerance_fraction": 1e-18})
    elif failure_code == CandidateFailureCode.GEOTHERMAL_INJECTION_HYDRAULIC_CONFLICT:
        policy = _policy(minimum_auxiliary_circulation_fraction=1e-9)
    elif failure_code == CandidateFailureCode.THERMAL_PIPEFLOW_NOT_CONVERGED:
        monkeypatch.setattr(candidate_module, "CONNECTION_PIPE_DN_MM", 1.0)
    elif failure_code == CandidateFailureCode.VELOCITY_LIMIT_EXCEEDED:
        monkeypatch.setattr(candidate_module, "CONNECTION_PIPE_DN_MM", 140.0)
    elif failure_code == CandidateFailureCode.CONSUMER_TEMPERATURE_NOT_MET:
        tolerances = tolerances.model_copy(update={"max_consumer_supply_drop_k": 1e-9})
    elif failure_code == CandidateFailureCode.PRESSURE_LIMIT_EXCEEDED:
        bp = _blueprint(p_supply_bar_abs=4.51)

    baseline = _baseline(bp)
    coupling_result = _golden_coupling_result()
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=policy, tolerances=tolerances,
    )
    assert isinstance(result, CandidateEvaluationFailure)
    assert result.failure_code == failure_code

    dumped = result.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["failure_code"] == failure_code.value
    restored = parse_candidate_result_json(dumped)
    assert isinstance(restored, CandidateEvaluationFailure)
    assert restored == result


# ── Model-level tamper tests ────────────────────────────────────────────────
def _valid_success_payload() -> dict:
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult)
    return json.loads(result.model_dump_json())


def test_control_untouched_payload_round_trips_cleanly():
    payload = _valid_success_payload()
    restored = parse_candidate_result_json(json.dumps(payload))
    assert isinstance(restored, CandidateEvaluationResult)


def test_tamper_negative_geothermal_injected_heat_is_rejected():
    payload = _valid_success_payload()
    payload["geothermal_injected_heat_kw"] = -1.0
    with pytest.raises(ValidationError):
        parse_candidate_result_json(json.dumps(payload))


def test_tamper_coverage_fraction_above_one_is_rejected():
    payload = _valid_success_payload()
    payload["geothermal_coverage_fraction"] = 1.5
    with pytest.raises(ValidationError):
        parse_candidate_result_json(json.dumps(payload))


def test_tamper_unmet_heat_nonzero_is_rejected():
    payload = _valid_success_payload()
    payload["unmet_heat_kw"] = 5.0
    with pytest.raises(ValidationError):
        parse_candidate_result_json(json.dumps(payload))


def test_tamper_doublet_pump_electric_power_mismatch_is_rejected():
    payload = _valid_success_payload()
    payload["doublet_pump_electric_power_kw"] = payload["doublet_pump_electric_power_kw"] + 1.0
    with pytest.raises(ValidationError):
        parse_candidate_result_json(json.dumps(payload))


def test_tamper_connection_pipe_dn_mismatch_is_rejected():
    payload = _valid_success_payload()
    payload["connection_pipe_dn_mm"] = 999.0
    with pytest.raises(ValidationError):
        parse_candidate_result_json(json.dumps(payload))


def test_tamper_kpi_delta_inconsistent_with_baseline_reference_is_rejected():
    payload = _valid_success_payload()
    payload["kpi_deltas"]["total_heat_delivered_delta_kw"] += 100.0
    with pytest.raises(ValidationError):
        parse_candidate_result_json(json.dumps(payload))


def test_tamper_non_finite_geothermal_coverage_fraction_is_rejected():
    payload = _valid_success_payload()
    payload["geothermal_coverage_fraction"] = float("nan")
    with pytest.raises(ValueError):
        parse_candidate_result_json(json.dumps(payload))


def test_models_are_frozen():
    bp = _blueprint()
    coupling_result = _golden_coupling_result()
    baseline = _baseline(bp)
    result = evaluate_candidate(
        coupling_result, bp, _candidate("C1"), baseline,
        injection_policy=_policy(), tolerances=_tolerances(),
    )
    assert isinstance(result, CandidateEvaluationResult)
    with pytest.raises(ValidationError):
        result.geothermal_injected_heat_kw = 0.0


# ── Scope-boundary discipline ────────────────────────────────────────────────
def test_no_economics_ranking_or_mcp_identifiers_in_module():
    """T2.3 excludes economics, ranking, MCP, and maps (plan, "Scope
    exclusions") -- mirrors T2.2B's own to_absolute_bar()-only-discipline
    structural test pattern. The module's own LEADING DOCSTRING explicitly
    DISCLAIMS these in prose (e.g. "does not rank candidates, compute
    economics", "no economic calculation, no ranking, no MCP tools, no
    maps") -- that whole leading docstring is exempted from the scan; any
    occurrence in the actual CODE BODY (imports, functions, class fields)
    fails the test."""
    source = _CANDIDATE_SRC_PATH.read_text()
    match = re.match(r'^""".*?"""\n', source, flags=re.DOTALL)
    assert match is not None, "expected a leading module docstring"
    code_body = source[match.end():]

    forbidden_patterns = [
        r"\beconomic", r"\bcapex\b", r"\bopex\b", r"\blcoh\b", r"\bannuit",
        r"\branking\b", r"\brank\b(?!ed_)", r"\bMCP\b", r"\bfastmcp\b",
        r"\bmatplotlib\b", r"\bfolium\b",
    ]
    lowered = code_body.lower()
    for pattern in forbidden_patterns:
        assert not re.search(pattern, lowered), f"forbidden pattern {pattern!r} found in candidate.py's code body"


def test_module_explicitly_disclaims_drilling_location():
    """This evaluates network CONNECTION location only -- the module must
    say so explicitly, not merely avoid the word "drilling" by omission."""
    source = _CANDIDATE_SRC_PATH.read_text().lower()
    assert "drilling" in source
    assert "connection location" in source
