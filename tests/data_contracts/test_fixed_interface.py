"""Fixed-DH-interface drilling-site-optimization correction --
`data_contracts.fixed_interface.resolve_fixed_integration_station()`'s own
invariants: exactly one declared attachment, exactly one allowed
attachment id, they agree, and the attachment is eligible. These are the
structural checks that make "the DH network entry does not vary in this
methodology" a validated invariant rather than an incidental config
choice."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.data_contracts.fixed_interface import (
    FixedHeatIntegrationStation,
    FixedInterfaceErrorCode,
    FixedInterfaceValidationError,
    SiteCaseAssignment,
    resolve_fixed_integration_station,
    resolve_site_case_assignment,
)
from r3chain_geothermal.data_contracts.joint_study import JointStudyPackage

_ROOT = Path(__file__).resolve().parents[2]
_FIXED_INTERFACE_PACKAGE_PATH = _ROOT / "config" / "fixed_interface_site_optimization_synthetic.json"
_V2_PACKAGE_PATH = _ROOT / "config" / "joint_study_synthetic_v2.json"


def _fixed_interface_package() -> JointStudyPackage:
    return JointStudyPackage.model_validate(json.loads(_FIXED_INTERFACE_PACKAGE_PATH.read_text()))


def _v2_package() -> JointStudyPackage:
    return JointStudyPackage.model_validate(json.loads(_V2_PACKAGE_PATH.read_text()))


def test_committed_fixed_interface_package_resolves_to_exactly_one_station():
    station = resolve_fixed_integration_station(
        _fixed_interface_package(), heat_exchanger_config_reference="coupling_assumptions",
    )
    assert isinstance(station, FixedHeatIntegrationStation)
    assert station.network_attachment_id == "trunk_1"
    assert station.network_entry_supply_junction_id == "trunk_1"
    assert station.network_entry_return_junction_id == "ret_trunk_1"
    assert station.heat_pump_config_reference is None
    # station_id is a SEPARATE semantic display name (task's own
    # correction: never conflate the fixed station's identity with the
    # raw pandapipes junction it happens to be built from).
    assert station.station_id == "dh_integration_station_trunk_1"


def test_station_display_id_override_is_used_when_supplied():
    station = resolve_fixed_integration_station(
        _fixed_interface_package(), heat_exchanger_config_reference="coupling_assumptions",
        station_display_id="dh_integration_station_1",
    )
    assert isinstance(station, FixedHeatIntegrationStation)
    assert station.station_id == "dh_integration_station_1"
    assert station.network_attachment_id == "trunk_1"


def test_committed_v2_package_is_rejected_as_ambiguous():
    """The v2 joint-study package (trunk_1..trunk_4) belongs to the
    multi-attachment methodology -- it must never resolve to a single
    fixed station."""
    result = resolve_fixed_integration_station(_v2_package(), heat_exchanger_config_reference="coupling_assumptions")
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.STATION_AMBIGUOUS


def test_zero_attachments_is_rejected_as_missing():
    package = _fixed_interface_package()
    package = package.model_copy(update={
        "network_attachments": [],
        "routing_policy": package.routing_policy.model_copy(update={"allowed_attachment_ids": []}),
    })
    result = resolve_fixed_integration_station(package, heat_exchanger_config_reference="coupling_assumptions")
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.STATION_MISSING


def test_allowed_attachment_id_mismatch_is_rejected():
    package = _fixed_interface_package()
    package = package.model_copy(update={
        "routing_policy": package.routing_policy.model_copy(update={"allowed_attachment_ids": ["not_trunk_1"]}),
    })
    result = resolve_fixed_integration_station(package, heat_exchanger_config_reference="coupling_assumptions")
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.STATION_ALLOWED_ATTACHMENT_MISMATCH


def test_ineligible_attachment_is_rejected():
    from r3chain_geothermal.data_contracts.joint_study import AttachmentEligibilityStatus

    package = _fixed_interface_package()
    attachment = package.network_attachments[0].model_copy(update={
        "eligibility_status": AttachmentEligibilityStatus.EXCLUDED, "exclusion_reason": "test",
    })
    package = package.model_copy(update={"network_attachments": [attachment]})
    result = resolve_fixed_integration_station(package, heat_exchanger_config_reference="coupling_assumptions")
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.STATION_INELIGIBLE


def test_max_thermal_power_mw_is_passed_through_when_supplied():
    station = resolve_fixed_integration_station(
        _fixed_interface_package(), heat_exchanger_config_reference="coupling_assumptions", max_thermal_power_mw=5.0,
    )
    assert isinstance(station, FixedHeatIntegrationStation)
    assert station.max_thermal_power_mw == 5.0


# ── resolve_site_case_assignment(): the site-vs-scenario correction ─────────
_COMMITTED_REFERENCE_MAP = {
    "site_alpha": "scenario_alpha_golden",
    "site_beta": "scenario_beta_low_temperature",
    "site_gamma": "scenario_gamma_higher_flow",
}


# ── Test C (site/scenario spec): exactly one reference case per site ────────
def test_committed_reference_map_resolves_to_exactly_one_case_per_available_site():
    assignment = resolve_site_case_assignment(_fixed_interface_package(), _COMMITTED_REFERENCE_MAP)
    assert isinstance(assignment, SiteCaseAssignment)
    assert assignment.reference_scenario_id_by_site == _COMMITTED_REFERENCE_MAP
    for site_id, scenario_id in _COMMITTED_REFERENCE_MAP.items():
        assert assignment.is_reference_case(site_id, scenario_id)
    # site_alpha's OTHER scenario is correctly NOT the reference case:
    assert not assignment.is_reference_case("site_alpha", "scenario_alpha_reduced_flow")


def test_missing_reference_case_for_an_available_site_is_rejected():
    incomplete_map = dict(_COMMITTED_REFERENCE_MAP)
    del incomplete_map["site_beta"]
    result = resolve_site_case_assignment(_fixed_interface_package(), incomplete_map)
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.SITE_REFERENCE_CASE_MISSING


def test_reference_case_naming_an_unknown_site_is_rejected():
    bad_map = {**_COMMITTED_REFERENCE_MAP, "site_that_does_not_exist": "scenario_alpha_golden"}
    result = resolve_site_case_assignment(_fixed_interface_package(), bad_map)
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.SITE_REFERENCE_CASE_UNKNOWN_SITE


def test_reference_case_naming_a_scenario_from_a_different_site_is_rejected():
    """A site's own reference case must be one of ITS OWN linked
    scenarios -- borrowing another site's scenario id must fail loudly,
    never silently substitute the wrong site's physics."""
    bad_map = {**_COMMITTED_REFERENCE_MAP, "site_beta": "scenario_alpha_golden"}
    result = resolve_site_case_assignment(_fixed_interface_package(), bad_map)
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.SITE_REFERENCE_CASE_INVALID


def test_reference_case_naming_a_nonexistent_scenario_is_rejected():
    bad_map = {**_COMMITTED_REFERENCE_MAP, "site_gamma": "scenario_does_not_exist"}
    result = resolve_site_case_assignment(_fixed_interface_package(), bad_map)
    assert isinstance(result, FixedInterfaceValidationError)
    assert result.error_code == FixedInterfaceErrorCode.SITE_REFERENCE_CASE_INVALID


def test_excluded_site_needs_no_reference_case_entry():
    """site_delta is EXCLUDED in the committed fixture -- it must never be
    required to have a declared reference case (it will never be routed
    or evaluated at all)."""
    assert "site_delta" not in _COMMITTED_REFERENCE_MAP
    assignment = resolve_site_case_assignment(_fixed_interface_package(), _COMMITTED_REFERENCE_MAP)
    assert isinstance(assignment, SiteCaseAssignment)
