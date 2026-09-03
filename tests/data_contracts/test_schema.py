"""Full test matrix for data_contracts/schema.py -- DATA-001..006's typed
study-package contracts."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r3chain_geothermal.data_contracts import (
    ApprovalStatus,
    DataOwnerReference,
    DatasetClassification,
    DemandProfileDeclaration,
    EconomicLineItem,
    GeothermalScenarioRecord,
    JunctionRecord,
    LicenceReference,
    NetworkDataPackage,
    NetworkSide,
    OperatingLimits,
    PipeRecord,
    SpatialLayerReference,
    StudyPackageManifest,
)

_TS = datetime(2026, 9, 3, tzinfo=timezone.utc)
_HASH = "0" * 64


def _manifest(**overrides) -> StudyPackageManifest:
    kwargs = dict(
        study_id="test-study", title="Test", classification=DatasetClassification.SYNTHETIC,
        created_at=_TS, updated_at=_TS,
        data_owners=[DataOwnerReference(name="a", organization="b")],
        licence=LicenceReference(licence_name="CC0", use_restrictions="none"),
        unit_conventions={"length": "m"}, approval_status=ApprovalStatus.PROVISIONAL,
        file_inventory={},
    )
    kwargs.update(overrides)
    return StudyPackageManifest(**kwargs)


# ── SpatialLayerReference ────────────────────────────────────────────────────
def test_spatial_layer_reference_accepts_a_missing_crs():
    """CRS absence is semantically caught by validate_study_package(), not
    rejected at this type's own boundary -- see that module's own test
    file for the AC-09 reachability proof."""
    layer = SpatialLayerReference(file_path="x.geojson", crs=None, byte_sha256=_HASH, feature_count=0, geometry_validated=False)
    assert layer.crs is None


def test_spatial_layer_reference_rejects_a_malformed_hash():
    with pytest.raises(ValidationError):
        SpatialLayerReference(file_path="x.geojson", crs="EPSG:4326", byte_sha256="not-a-hash", feature_count=0, geometry_validated=True)


def test_spatial_layer_reference_rejects_negative_feature_count():
    with pytest.raises(ValidationError):
        SpatialLayerReference(file_path="x.geojson", crs="EPSG:4326", byte_sha256=_HASH, feature_count=-1, geometry_validated=True)


# ── StudyPackageManifest ─────────────────────────────────────────────────────
def test_manifest_requires_data_owners():
    with pytest.raises(ValidationError):
        _manifest(data_owners=[])


def test_manifest_rejects_updated_before_created():
    from datetime import timedelta
    with pytest.raises(ValidationError):
        _manifest(created_at=_TS, updated_at=_TS - timedelta(days=1))


def test_manifest_rejects_a_spatial_layer_hash_disagreeing_with_file_inventory():
    with pytest.raises(ValidationError):
        _manifest(
            file_inventory={"x.geojson": _HASH},
            spatial_layers=[SpatialLayerReference(
                file_path="x.geojson", crs="EPSG:4326", byte_sha256="1" * 64, feature_count=1, geometry_validated=True,
            )],
        )


def test_manifest_rejects_a_spatial_layer_not_in_file_inventory():
    with pytest.raises(ValidationError):
        _manifest(
            file_inventory={},
            spatial_layers=[SpatialLayerReference(
                file_path="x.geojson", crs="EPSG:4326", byte_sha256=_HASH, feature_count=1, geometry_validated=True,
            )],
        )


def test_manifest_accepts_a_consistent_spatial_layer():
    manifest = _manifest(
        file_inventory={"x.geojson": _HASH},
        spatial_layers=[SpatialLayerReference(
            file_path="x.geojson", crs="EPSG:4326", byte_sha256=_HASH, feature_count=1, geometry_validated=True,
        )],
    )
    assert len(manifest.spatial_layers) == 1


# ── NetworkDataPackage / OperatingLimits / DemandProfileDeclaration ─────────
def test_operating_limits_rejects_inverted_pressure_bounds():
    with pytest.raises(ValidationError):
        OperatingLimits(min_pressure_bar_abs=6.0, max_pressure_bar_abs=1.0, min_temperature_c=0.0, max_temperature_c=100.0)


def test_operating_limits_rejects_inverted_temperature_bounds():
    with pytest.raises(ValidationError):
        OperatingLimits(min_pressure_bar_abs=1.0, max_pressure_bar_abs=6.0, min_temperature_c=100.0, max_temperature_c=0.0)


def test_demand_profile_declaration_requires_a_reference_for_time_series_mode():
    with pytest.raises(ValidationError):
        DemandProfileDeclaration(mode="time_series_reference", time_series_reference=None)


def test_demand_profile_declaration_requires_a_note_for_static_mode():
    with pytest.raises(ValidationError):
        DemandProfileDeclaration(mode="static_demo", static_demo_note=None)


def test_demand_profile_declaration_accepts_a_valid_static_declaration():
    declaration = DemandProfileDeclaration(mode="static_demo", static_demo_note="single fixed point")
    assert declaration.mode == "static_demo"


def test_network_data_package_rejects_empty_junctions():
    with pytest.raises(ValidationError):
        NetworkDataPackage(
            junctions=[], pipes=[PipeRecord(pipe_id="p", from_junction="a", to_junction="b", length_m=1.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active")],
            consumers=[], operating_limits=OperatingLimits(min_pressure_bar_abs=1.0, max_pressure_bar_abs=6.0, min_temperature_c=0.0, max_temperature_c=100.0),
            demand_profile=DemandProfileDeclaration(mode="static_demo", static_demo_note="x"),
        )


# ── GeothermalScenarioRecord ─────────────────────────────────────────────────
def _scenario(**overrides) -> GeothermalScenarioRecord:
    kwargs = dict(
        scenario_id="s1", site_id="site1", geometry_or_parcel_reference="ref",
        pydoublet_input_reference="ref", pydoublet_input_sha256=_HASH,
        pydoublet_result_reference="ref", pydoublet_result_sha256=_HASH,
        depth_m=3000.0, temperature_assumption_c=76.0, mass_flow_or_transmissivity_basis="basis",
        reinjection_constraint_c=35.0, well_spacing_m=1000.0, well_trajectory_note="note",
        production_pump_requirement_kw=177.0, injection_pump_requirement_kw=0.0,
        uncertainty_or_risk_note="note", calculation_mode="deterministic", upstream_commit_or_model_version="abc",
    )
    kwargs.update(overrides)
    return GeothermalScenarioRecord(**kwargs)


def test_geothermal_scenario_accepts_missing_provenance_hashes():
    scenario = _scenario(pydoublet_input_sha256=None, pydoublet_result_sha256=None)
    assert scenario.pydoublet_input_sha256 is None


def test_geothermal_scenario_rejects_temperature_at_or_below_reinjection_constraint():
    with pytest.raises(ValidationError):
        _scenario(temperature_assumption_c=35.0, reinjection_constraint_c=35.0)


def test_geothermal_scenario_rejects_non_positive_depth():
    with pytest.raises(ValidationError):
        _scenario(depth_m=0.0)


# ── EconomicLineItem ─────────────────────────────────────────────────────────
def _line_item(**overrides) -> EconomicLineItem:
    kwargs = dict(
        line_item_id="l1", category="drilling", value=1000.0, currency="EUR", price_year=2026,
        unit_basis="per unit", source="demo", approval_status=ApprovalStatus.PROVISIONAL,
        uncertainty_range=None, inclusion_note="note",
    )
    kwargs.update(overrides)
    return EconomicLineItem(**kwargs)


def test_economic_line_item_rejects_implausible_price_year():
    with pytest.raises(ValidationError):
        _line_item(price_year=1500)


def test_economic_line_item_rejects_inverted_uncertainty_range():
    with pytest.raises(ValidationError):
        _line_item(uncertainty_range=(100.0, 50.0))


def test_economic_line_item_accepts_a_valid_range():
    item = _line_item(uncertainty_range=(50.0, 100.0))
    assert item.uncertainty_range == (50.0, 100.0)
