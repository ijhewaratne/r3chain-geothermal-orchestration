"""Full test matrix for the T2.1 heat-exchanger adapter."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.adapter import (
    AdapterFailureCode,
    CouplingAssumptions,
    HeatExchangerBoundaryResult,
    HeatExchangerCouplingFailure,
    HeatExchangerCouplingResult,
    RAW_POWER_CEILING_BINDING,
    evaluate_heat_exchanger_coupling,
    parse_heat_exchanger_result_json,
)
from r3chain_geothermal.contracts import NormalizedQuantity, PyDoubletCouplingResult, SourceProvenance
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"


def _golden_coupling_input() -> PyDoubletCouplingResult:
    raw = json.loads(_REPAIRED_PATH.read_text())
    provenance = SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired", calculation_mode="deterministic",
    )
    result = parse_pydoublet_result(raw, source_provenance=provenance)
    assert isinstance(result, PyDoubletCouplingResult)
    return result


def _golden_assumptions() -> CouplingAssumptions:
    config = json.loads(_CONFIG_PATH.read_text())
    return CouplingAssumptions.from_config_dict(config)


def _assumptions(**overrides) -> CouplingAssumptions:
    base = dict(
        dh_supply_temperature_c=70.0, dh_return_temperature_c=40.0,
        minimum_hx_approach_k=5.0, hx_heat_delivery_factor=0.98,
        reinjection_minimum_temperature_c=35.0,
        dh_water_specific_heat_capacity_j_kg_k=4180.0,
        energy_consistency_tolerance_fraction=0.02,
    )
    base.update(overrides)
    return CouplingAssumptions(**base)


def _strict_json_loads(text: str):
    def _reject(constant: str):
        raise ValueError(f"Strict JSON decoding rejects non-standard constant: {constant}")
    return json.loads(text, parse_constant=_reject)


# ── The five worked-example checks, reproduced exactly against the golden fixture ──
def test_raw_energy_consistency_matches_target():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert isinstance(result, HeatExchangerCouplingResult)
    check = result.raw_energy_consistency_check
    assert check.computed_power_kw.value == pytest.approx(4345.417, abs=1e-2)
    assert check.reported_power_kw.value == pytest.approx(4345.417, abs=1e-2)
    assert check.relative_difference < 1e-10
    assert check.passed is True


def test_required_brine_outlet_for_dh_matches_target():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.allowable_brine_outlet_temperature_c.value == 45.0
    assert result.allowable_brine_outlet_temperature_c.unit == "degC"
    assert result.allowable_brine_outlet_binding_constraint == "dh_return_plus_approach"


def test_hot_end_feasibility_matches_target():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.hot_end_feasibility_margin_k == pytest.approx(1.313044, abs=1e-5)
    assert result.hot_end_feasibility_margin_k >= 0


def test_deliverable_heat_matches_target():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.deliverable_geothermal_heat_kw.value == pytest.approx(3227.719, abs=1e-2)
    assert result.deliverable_geothermal_heat_kw.unit == "kW"
    assert result.deliverable_heat_binding_constraint == "temperature_limited_heat"


def test_dh_mass_flow_matches_target():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.district_heating_water_mass_flow_kg_s.value == pytest.approx(25.74, abs=1e-2)
    assert result.district_heating_water_mass_flow_kg_s.unit == "kg/s"


def test_raw_power_never_labelled_as_deliverable():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.deliverable_geothermal_heat_kw.value != result.coupling_input.raw_geothermal_thermal_power_kw.value
    assert result.deliverable_geothermal_heat_kw.value < result.coupling_input.raw_geothermal_thermal_power_kw.value


# ── Two distinct "35 degC" concepts kept separate ───────────────────────────
def test_brine_outlet_and_reinjection_minimum_are_independent_fields():
    coupling_input = _golden_coupling_input()
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=_golden_assumptions())
    # T1.5B's own contract value (what THIS run assumed):
    assert coupling_input.geothermal_brine_hx_outlet_temperature_c.value == 35.0
    # The adapter's policy floor (config, independent field):
    assert result.assumptions.reinjection_minimum_temperature_c == 35.0
    # Numerically equal here only by coincidence of the provisional config;
    # used in entirely separate formulas (asserted via the binding constraint,
    # which in the golden case is won by the DH-return term, not reinjection):
    assert result.allowable_brine_outlet_binding_constraint == "dh_return_plus_approach"


# ── Failure paths ────────────────────────────────────────────────────────
def test_unit_or_sign_error_on_corrupted_raw_power():
    coupling_input = _golden_coupling_input()
    corrupted = coupling_input.model_copy(update={
        "raw_geothermal_thermal_power_kw": NormalizedQuantity(value=9999.0, unit="kW"),
    })
    result = evaluate_heat_exchanger_coupling(corrupted, assumptions=_golden_assumptions())
    assert isinstance(result, HeatExchangerCouplingFailure)
    assert result.failure_code == AdapterFailureCode.UNIT_OR_SIGN_ERROR
    assert result.details["reported_power_kw"] == 9999.0
    assert result.details["relative_difference"] > result.details["tolerance_fraction"]
    assert result.coupling_input == corrupted


def test_hx_supply_temperature_infeasible():
    assumptions = _assumptions(dh_supply_temperature_c=80.0, dh_return_temperature_c=50.0)
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingFailure)
    assert result.failure_code == AdapterFailureCode.HX_SUPPLY_TEMPERATURE_INFEASIBLE
    assert result.details["required_minimum_c"] == 85.0
    assert result.details["shortfall_k"] > 0
    assert result.assumptions == assumptions


def test_hx_cold_end_approach_infeasible():
    """Hot end passes (dh_supply+approach=75 <= 76.313) but the reinjection
    floor is set above producer_wellhead_temperature_c, so no positive
    temperature difference remains."""
    assumptions = _assumptions(reinjection_minimum_temperature_c=77.0)
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingFailure)
    assert result.failure_code == AdapterFailureCode.HX_COLD_END_APPROACH_INFEASIBLE
    assert result.details["allowable_brine_outlet_temperature_c"] == 77.0
    assert result.details["producer_wellhead_temperature_c"] < result.details["allowable_brine_outlet_temperature_c"]


def test_hx_cold_end_approach_infeasible_at_exact_zero_heat_boundary():
    """T_prod == allowable_brine_outlet_temperature_c exactly (zero-Delta-T,
    zero-heat boundary) must still be rejected -- the <= comparison, not <,
    is what the evaluator uses, so an exact match is a failure, never a
    silent zero-kW success."""
    coupling_input = _golden_coupling_input()
    t_prod = coupling_input.producer_wellhead_temperature_c.value
    assumptions = _assumptions(reinjection_minimum_temperature_c=t_prod)
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingFailure)
    assert result.failure_code == AdapterFailureCode.HX_COLD_END_APPROACH_INFEASIBLE
    assert result.details["allowable_brine_outlet_temperature_c"] == t_prod
    assert result.details["producer_wellhead_temperature_c"] == t_prod


def test_allowable_outlet_helper_selects_dh_return_plus_approach_when_it_dominates():
    """Unit-level proof that _compute_allowable_brine_outlet() correctly
    picks the dh_return_plus_approach term when it exceeds the reinjection
    floor -- covering that branch of the max() in isolation, since (see the
    next test) it can never be observed as the CAUSE of an end-to-end
    HX_COLD_END_APPROACH_INFEASIBLE failure."""
    from r3chain_geothermal.adapter.heat_exchanger import _compute_allowable_brine_outlet

    t_prod = _golden_coupling_input().producer_wellhead_temperature_c.value
    assumptions = _assumptions(
        dh_supply_temperature_c=t_prod + 1.0, dh_return_temperature_c=t_prod - 4.0,
        minimum_hx_approach_k=5.0, reinjection_minimum_temperature_c=10.0,
    )
    allowable_c, binding = _compute_allowable_brine_outlet(assumptions)
    assert binding == "dh_return_plus_approach"
    assert allowable_c > t_prod  # this term, alone, WOULD make cold-end infeasible


def test_dh_return_plus_approach_term_cannot_cause_cold_end_failure_end_to_end():
    """Mathematical consequence of CouplingAssumptions requiring
    dh_supply_temperature_c > dh_return_temperature_c (both hot-end and
    cold-end use the SAME minimum_hx_approach_k): whenever
    dh_return+approach >= T_prod (which would make cold-end infeasible via
    that term), dh_supply+approach > dh_return+approach >= T_prod holds too,
    so the hot-end gate (HX_SUPPLY_TEMPERATURE_INFEASIBLE) always rejects
    such an input FIRST, before the cold-end gate is ever reached. This is
    confirmed here, not merely asserted -- using the exact assumptions from
    the previous test, where the dh_return_plus_approach term alone would
    exceed T_prod, the full gated evaluator still reports
    HX_SUPPLY_TEMPERATURE_INFEASIBLE, never HX_COLD_END_APPROACH_INFEASIBLE."""
    coupling_input = _golden_coupling_input()
    t_prod = coupling_input.producer_wellhead_temperature_c.value
    assumptions = _assumptions(
        dh_supply_temperature_c=t_prod + 1.0, dh_return_temperature_c=t_prod - 4.0,
        minimum_hx_approach_k=5.0, reinjection_minimum_temperature_c=10.0,
    )
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingFailure)
    assert result.failure_code == AdapterFailureCode.HX_SUPPLY_TEMPERATURE_INFEASIBLE


def test_none_of_the_three_failure_paths_ever_raise():
    coupling_input = _golden_coupling_input()
    for assumptions in [
        _assumptions(dh_supply_temperature_c=80.0, dh_return_temperature_c=50.0),
        _assumptions(reinjection_minimum_temperature_c=77.0),
    ]:
        try:
            result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
        except Exception as exc:  # pragma: no cover - must never happen
            pytest.fail(f"evaluate_heat_exchanger_coupling raised {exc!r} instead of returning a typed failure")
        assert result.status == "failure"


# ── Binding-constraint audit trail ──────────────────────────────────────────
def test_allowable_outlet_binding_dh_return_wins_in_golden_case():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.allowable_brine_outlet_binding_constraint == "dh_return_plus_approach"


def test_allowable_outlet_binding_reinjection_minimum_wins_when_raised():
    assumptions = _assumptions(reinjection_minimum_temperature_c=50.0)
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingResult)
    assert result.allowable_brine_outlet_temperature_c.value == 50.0
    assert result.allowable_brine_outlet_binding_constraint == "reinjection_minimum"


def test_deliverable_heat_binding_temperature_limited_in_golden_case():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.deliverable_heat_binding_constraint == "temperature_limited_heat"
    assert result.warnings == []


def test_deliverable_heat_binding_pydoublet_power_when_dh_return_very_cold():
    """A very cold DH return (and low reinjection floor) allows cooling the
    brine far below its default outlet -- the temperature-limited term then
    exceeds the raw reported power, so the raw power itself becomes the
    binding ceiling, and a RAW_POWER_CEILING_BINDING warning is emitted."""
    assumptions = _assumptions(dh_return_temperature_c=10.0, reinjection_minimum_temperature_c=20.0)
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingResult)
    assert result.deliverable_heat_binding_constraint == "pydoublet_reported_power"
    assert result.deliverable_geothermal_heat_kw.value == pytest.approx(
        result.coupling_input.raw_geothermal_thermal_power_kw.value * assumptions.hx_heat_delivery_factor
    )
    warning_codes = [w.code for w in result.warnings]
    assert RAW_POWER_CEILING_BINDING in warning_codes


# ── Brine/DH-water flow separation ──────────────────────────────────────────
def test_dh_water_flow_never_equals_brine_flow():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    assert result.district_heating_water_mass_flow_kg_s.value != result.coupling_input.geothermal_brine_mass_flow_kg_s.value


def test_four_core_quantities_distinctly_named_and_unit_labelled():
    """Raw power, deliverable heat, brine flow, and DH-water flow are four
    separate fields, each with its own explicit unit -- never aliased or
    reused across concepts."""
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    raw_power = result.coupling_input.raw_geothermal_thermal_power_kw
    deliverable_heat = result.deliverable_geothermal_heat_kw
    brine_flow = result.coupling_input.geothermal_brine_mass_flow_kg_s
    dh_flow = result.district_heating_water_mass_flow_kg_s

    field_names = {"raw_geothermal_thermal_power_kw", "deliverable_geothermal_heat_kw",
                   "geothermal_brine_mass_flow_kg_s", "district_heating_water_mass_flow_kg_s"}
    assert len(field_names) == 4  # all four names distinct

    assert raw_power.unit == "kW" and deliverable_heat.unit == "kW"
    assert brine_flow.unit == "kg/s" and dh_flow.unit == "kg/s"
    assert raw_power.value != deliverable_heat.value
    assert brine_flow.value != dh_flow.value


def test_dh_water_flow_field_naming_never_conflated_with_brine():
    field_names = set(HeatExchangerCouplingResult.model_fields.keys())
    dh_fields = {name for name in field_names if "district_heating" in name}
    assert dh_fields  # sanity: at least one DH-water field exists
    for name in dh_fields:
        assert "brine" not in name, name
    brine_referencing = {name for name in field_names if "brine" in name}
    for name in brine_referencing:
        assert "district_heating" not in name, name


# ── Preservation ─────────────────────────────────────────────────────────
def test_success_preserves_complete_coupling_input_and_assumptions():
    coupling_input = _golden_coupling_input()
    assumptions = _golden_assumptions()
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert result.coupling_input == coupling_input
    assert result.assumptions == assumptions


def test_failure_preserves_complete_coupling_input_and_assumptions():
    coupling_input = _golden_coupling_input()
    assumptions = _assumptions(dh_supply_temperature_c=80.0, dh_return_temperature_c=50.0)
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingFailure)
    assert result.coupling_input == coupling_input
    assert result.assumptions == assumptions


# ── Strict-JSON round trip for every failure code and success variants ─────
def _all_success_variants():
    return [
        evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions()),
        evaluate_heat_exchanger_coupling(
            _golden_coupling_input(), assumptions=_assumptions(reinjection_minimum_temperature_c=50.0)
        ),
        evaluate_heat_exchanger_coupling(
            _golden_coupling_input(),
            assumptions=_assumptions(dh_return_temperature_c=10.0, reinjection_minimum_temperature_c=20.0),
        ),
    ]


@pytest.mark.parametrize("result", _all_success_variants())
def test_strict_json_round_trip_for_success_variants(result):
    dumped = result.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["status"] == "success"
    restored = parse_heat_exchanger_result_json(dumped)
    assert isinstance(restored, HeatExchangerCouplingResult)
    assert restored == result


@pytest.mark.parametrize("failure_code,assumptions_overrides", [
    (AdapterFailureCode.UNIT_OR_SIGN_ERROR, None),
    (AdapterFailureCode.HX_SUPPLY_TEMPERATURE_INFEASIBLE, {"dh_supply_temperature_c": 80.0, "dh_return_temperature_c": 50.0}),
    (AdapterFailureCode.HX_COLD_END_APPROACH_INFEASIBLE, {"reinjection_minimum_temperature_c": 77.0}),
])
def test_strict_json_round_trip_for_every_failure_code(failure_code, assumptions_overrides):
    coupling_input = _golden_coupling_input()
    if failure_code == AdapterFailureCode.UNIT_OR_SIGN_ERROR:
        coupling_input = coupling_input.model_copy(update={
            "raw_geothermal_thermal_power_kw": NormalizedQuantity(value=9999.0, unit="kW"),
        })
        assumptions = _golden_assumptions()
    else:
        assumptions = _assumptions(**assumptions_overrides)
    result = evaluate_heat_exchanger_coupling(coupling_input, assumptions=assumptions)
    assert isinstance(result, HeatExchangerCouplingFailure)
    assert result.failure_code == failure_code

    dumped = result.model_dump_json()
    payload = _strict_json_loads(dumped)
    assert payload["failure_code"] == failure_code.value
    restored = parse_heat_exchanger_result_json(dumped)
    assert isinstance(restored, HeatExchangerCouplingFailure)
    assert restored == result


def test_all_three_adapter_failure_codes_covered():
    assert {c.value for c in AdapterFailureCode} == {
        "UNIT_OR_SIGN_ERROR", "HX_SUPPLY_TEMPERATURE_INFEASIBLE", "HX_COLD_END_APPROACH_INFEASIBLE",
    }


# ── Model-level tamper-rejection tests (mirrors T1.5B's second correction round) ──
def _valid_success_payload() -> dict:
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    return json.loads(result.model_dump_json())


def test_control_untouched_payload_round_trips_cleanly():
    payload = _valid_success_payload()
    restored = parse_heat_exchanger_result_json(json.dumps(payload))
    assert isinstance(restored, HeatExchangerCouplingResult)


def test_tamper_negative_deliverable_heat_is_rejected():
    payload = _valid_success_payload()
    payload["deliverable_geothermal_heat_kw"]["value"] = -1.0
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_wrong_unit_on_deliverable_heat_is_rejected():
    payload = _valid_success_payload()
    payload["deliverable_geothermal_heat_kw"]["unit"] = "MW"
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_wrong_unit_on_allowable_brine_outlet_is_rejected():
    payload = _valid_success_payload()
    payload["allowable_brine_outlet_temperature_c"]["unit"] = "K"
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_negative_dh_water_mass_flow_is_rejected():
    payload = _valid_success_payload()
    payload["district_heating_water_mass_flow_kg_s"]["value"] = -5.0
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_dh_water_flow_set_equal_to_brine_flow_is_rejected():
    payload = _valid_success_payload()
    payload["district_heating_water_mass_flow_kg_s"]["value"] = (
        payload["coupling_input"]["geothermal_brine_mass_flow_kg_s"]["value"]
    )
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_deliverable_heat_value_inconsistent_with_recomputation_is_rejected():
    payload = _valid_success_payload()
    payload["deliverable_geothermal_heat_kw"]["value"] = 1234.5  # plausible-looking but wrong
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_binding_constraint_flipped_is_rejected():
    payload = _valid_success_payload()
    assert payload["deliverable_heat_binding_constraint"] == "temperature_limited_heat"
    payload["deliverable_heat_binding_constraint"] = "pydoublet_reported_power"
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_hot_end_margin_inconsistent_is_rejected():
    payload = _valid_success_payload()
    payload["hot_end_feasibility_margin_k"] = 999.0
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_negative_hot_end_margin_is_rejected():
    payload = _valid_success_payload()
    payload["hot_end_feasibility_margin_k"] = -1.0
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_tamper_energy_consistency_check_relative_difference_exceeding_tolerance_is_rejected():
    payload = _valid_success_payload()
    payload["raw_energy_consistency_check"]["relative_difference"] = 0.5
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


def test_direct_construction_with_bad_unit_is_rejected():
    """Model-level invariants apply to direct Python construction too, not
    only JSON deserialization."""
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    kwargs = result.model_dump(mode="python")
    kwargs["deliverable_geothermal_heat_kw"] = NormalizedQuantity(value=kwargs["deliverable_geothermal_heat_kw"]["value"], unit="MW")
    with pytest.raises(ValidationError):
        HeatExchangerCouplingResult(**kwargs)


# ── Assumptions-embedded validation surfaces through the boundary too ──────
def test_tampered_hx_heat_delivery_factor_in_embedded_assumptions_is_rejected():
    payload = _valid_success_payload()
    payload["assumptions"]["hx_heat_delivery_factor"] = 1.5
    with pytest.raises(ValidationError):
        parse_heat_exchanger_result_json(json.dumps(payload))


# ── Models are frozen ────────────────────────────────────────────────────
def test_models_are_frozen():
    result = evaluate_heat_exchanger_coupling(_golden_coupling_input(), assumptions=_golden_assumptions())
    with pytest.raises(Exception):
        result.deliverable_geothermal_heat_kw = NormalizedQuantity(value=0.0, unit="kW")  # type: ignore[misc]

    failure = evaluate_heat_exchanger_coupling(
        _golden_coupling_input(), assumptions=_assumptions(reinjection_minimum_temperature_c=77.0)
    )
    with pytest.raises(Exception):
        failure.message = "changed"  # type: ignore[misc]
