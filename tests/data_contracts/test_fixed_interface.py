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
    resolve_fixed_integration_station,
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
    assert station.station_id == "trunk_1"
    assert station.network_entry_supply_junction_id == "trunk_1"
    assert station.network_entry_return_junction_id == "ret_trunk_1"
    assert station.heat_pump_config_reference is None


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
