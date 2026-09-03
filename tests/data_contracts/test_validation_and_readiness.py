"""DATA-007/DATA-009/AC-09: pre-flight validation and readiness reporting."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from r3chain_geothermal.data_contracts import (
    ApprovalStatus,
    ConsumerRecord,
    DataOwnerReference,
    DatasetClassification,
    DemandProfileDeclaration,
    JunctionRecord,
    LicenceReference,
    NetworkDataPackage,
    NetworkSide,
    OperatingLimits,
    PipeRecord,
    StudyPackage,
    StudyPackageErrorCode,
    StudyPackageManifest,
    generate_readiness_report,
    validate_study_package,
)
from r3chain_geothermal.data_contracts.sample_packages import (
    build_intentionally_incomplete_real_package,
    build_synthetic_sample_package,
)

_TS = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _minimal_manifest(**overrides) -> StudyPackageManifest:
    kwargs = dict(
        study_id="test-study", title="Test", classification=DatasetClassification.SYNTHETIC,
        created_at=_TS, updated_at=_TS,
        data_owners=[DataOwnerReference(name="a", organization="b")],
        licence=LicenceReference(licence_name="CC0", use_restrictions="none"),
        unit_conventions={"length": "m"}, approval_status=ApprovalStatus.APPROVED, file_inventory={},
    )
    kwargs.update(overrides)
    return StudyPackageManifest(**kwargs)


def _network_with_pipes(pipes: list[PipeRecord], junctions: list[JunctionRecord] | None = None) -> NetworkDataPackage:
    return NetworkDataPackage(
        junctions=junctions or [
            JunctionRecord(junction_id="a", x_m=0.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
            JunctionRecord(junction_id="b", x_m=10.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
        ],
        pipes=pipes, consumers=[],
        operating_limits=OperatingLimits(min_pressure_bar_abs=1.0, max_pressure_bar_abs=6.0, min_temperature_c=0.0, max_temperature_c=100.0),
        demand_profile=DemandProfileDeclaration(mode="static_demo", static_demo_note="x"),
    )


# ── AC-09: the exact three named cases ──────────────────────────────────────
def test_ac09_incomplete_package_fails_pre_flight_with_all_three_exact_errors():
    package = build_intentionally_incomplete_real_package()
    result = validate_study_package(package)
    assert result.valid is False
    codes = {e.error_code for e in result.errors}
    assert codes == {
        StudyPackageErrorCode.MISSING_CRS,
        StudyPackageErrorCode.INVALID_DIMENSION,
        StudyPackageErrorCode.MISSING_PROVENANCE,
    }


def test_ac09_readiness_report_lists_the_validation_errors_and_denies_optimization():
    package = build_intentionally_incomplete_real_package()
    report = generate_readiness_report(package)
    assert len(report.validation_errors) == 3
    assert report.connection_optimization_permitted is False
    assert report.drilling_location_optimization_permitted is False
    assert "economics" in report.missing_datasets
    assert "decisions" in report.missing_datasets


def test_validate_study_package_never_raises_for_the_incomplete_package():
    package = build_intentionally_incomplete_real_package()
    validate_study_package(package)  # must not raise


# ── DATA-008: the synthetic sample package ──────────────────────────────────
def test_synthetic_sample_package_is_fully_valid():
    package = build_synthetic_sample_package()
    result = validate_study_package(package)
    assert result.valid is True
    assert result.errors == []


def test_synthetic_sample_package_is_explicitly_classified_synthetic():
    package = build_synthetic_sample_package()
    assert package.manifest.classification == DatasetClassification.SYNTHETIC
    assert "riverbend" in package.manifest.study_id.lower()  # an invented, not-real place name


def test_synthetic_sample_package_readiness_permits_connection_optimization():
    package = build_synthetic_sample_package()
    report = generate_readiness_report(package)
    assert report.connection_optimization_permitted is True
    assert report.drilling_location_optimization_permitted is True
    assert report.missing_datasets == []


# ── Duplicate/topology/temperature checks, isolated from the fixtures ──────
def test_duplicate_pipe_id_detected():
    pipes = [
        PipeRecord(pipe_id="p1", from_junction="a", to_junction="b", length_m=10.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active"),
        PipeRecord(pipe_id="p1", from_junction="a", to_junction="b", length_m=10.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active"),
    ]
    package = StudyPackage(manifest=_minimal_manifest(), network=_network_with_pipes(pipes))
    result = validate_study_package(package)
    assert StudyPackageErrorCode.DUPLICATE_ID in {e.error_code for e in result.errors}


def test_disconnected_supply_side_topology_detected():
    junctions = [
        JunctionRecord(junction_id="a", x_m=0.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
        JunctionRecord(junction_id="b", x_m=10.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
        JunctionRecord(junction_id="c", x_m=20.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
    ]
    # "c" has no pipe connecting it to a/b -- disconnected.
    pipes = [PipeRecord(pipe_id="p1", from_junction="a", to_junction="b", length_m=10.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active")]
    package = StudyPackage(manifest=_minimal_manifest(), network=_network_with_pipes(pipes, junctions=junctions))
    result = validate_study_package(package)
    assert StudyPackageErrorCode.DISCONNECTED_TOPOLOGY in {e.error_code for e in result.errors}


def test_two_sided_network_with_separate_supply_and_return_graphs_is_not_falsely_flagged():
    """Regression guard: a real two-sided DH network's supply and return
    junctions are legitimately separate pipe graphs (joined only through
    non-pipe components this schema doesn't model) -- this must NOT be
    reported as DISCONNECTED_TOPOLOGY."""
    junctions = [
        JunctionRecord(junction_id="s1", x_m=0.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
        JunctionRecord(junction_id="s2", x_m=10.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
        JunctionRecord(junction_id="r1", x_m=0.0, y_m=5.0, elevation_m=0.0, side=NetworkSide.RETURN),
        JunctionRecord(junction_id="r2", x_m=10.0, y_m=5.0, elevation_m=0.0, side=NetworkSide.RETURN),
    ]
    pipes = [
        PipeRecord(pipe_id="ps", from_junction="s1", to_junction="s2", length_m=10.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active"),
        PipeRecord(pipe_id="pr", from_junction="r2", to_junction="r1", length_m=10.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active"),
    ]
    package = StudyPackage(manifest=_minimal_manifest(), network=_network_with_pipes(pipes, junctions=junctions))
    result = validate_study_package(package)
    assert StudyPackageErrorCode.DISCONNECTED_TOPOLOGY not in {e.error_code for e in result.errors}


def test_pipe_referencing_unknown_junction_detected():
    pipes = [PipeRecord(pipe_id="p1", from_junction="a", to_junction="does_not_exist", length_m=10.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active")]
    package = StudyPackage(manifest=_minimal_manifest(), network=_network_with_pipes(pipes))
    result = validate_study_package(package)
    assert StudyPackageErrorCode.DISCONNECTED_TOPOLOGY in {e.error_code for e in result.errors}


def test_duplicate_consumer_id_detected():
    network = _network_with_pipes([
        PipeRecord(pipe_id="p1", from_junction="a", to_junction="b", length_m=10.0, internal_diameter_mm=100.0, material="steel", roughness_mm=0.1, status="active"),
    ])
    network = network.model_copy(update={"consumers": [
        ConsumerRecord(consumer_id="c1", substation_id="s1", design_load_kw=100.0, return_temperature_behavior="fixed"),
        ConsumerRecord(consumer_id="c1", substation_id="s2", design_load_kw=100.0, return_temperature_behavior="fixed"),
    ]})
    package = StudyPackage(manifest=_minimal_manifest(), network=network)
    result = validate_study_package(package)
    assert StudyPackageErrorCode.DUPLICATE_ID in {e.error_code for e in result.errors}


def test_inconsistent_unit_convention_detected():
    package = StudyPackage(manifest=_minimal_manifest(unit_conventions={"length": "feet"}))
    result = validate_study_package(package)
    assert StudyPackageErrorCode.INCONSISTENT_UNITS in {e.error_code for e in result.errors}


def test_no_network_section_is_not_itself_a_validation_error():
    """A completely absent network section is reported via the readiness
    report's missing_datasets (DATA-009), not as a validate_study_package()
    error -- the two concerns are deliberately separate."""
    package = StudyPackage(manifest=_minimal_manifest())
    result = validate_study_package(package)
    assert result.valid is True
    report = generate_readiness_report(package)
    assert "network" in report.missing_datasets
