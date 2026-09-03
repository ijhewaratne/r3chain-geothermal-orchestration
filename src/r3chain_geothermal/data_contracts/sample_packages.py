"""DATA-008/AC-09 example study packages.

`build_synthetic_sample_package()`: a small, fully valid, explicitly
`classification="synthetic"` package exercising every schema section
(DATA-008). Uses invented placeholder names ("Riverbend", a fictional
place) -- never a real place label that could suggest operational
validity, and never real Wuppertal data (14.1's own principle).

`build_intentionally_incomplete_real_package()`: a deliberately incomplete
`classification="real"` package, missing exactly the three items AC-09
names -- a spatial layer's CRS, one pipe's diameter, and one geothermal
scenario's PyDoublet provenance hashes -- for the acceptance test proving
pre-flight validation stops before any solver or recommendation runs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .schema import (
    ApprovalStatus,
    ConsumerRecord,
    ControlComponentRecord,
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
    StudyDecisionPolicy,
    StudyPackage,
    StudyPackageManifest,
)

_FIXED_TIMESTAMP = datetime(2026, 9, 3, tzinfo=timezone.utc)
_PLACEHOLDER_HASH = "0" * 64
"""A deliberately obviously-synthetic all-zero placeholder hash for the
sample package's file_inventory/spatial_layers -- not a real file's hash,
matching this project's own established "demo_assumption"-style labelling
discipline for provisional values."""


def build_synthetic_sample_package() -> StudyPackage:
    """DATA-008: exercises every StudyPackage section. "Riverbend" is an
    invented placeholder network name -- not a real place."""
    manifest = StudyPackageManifest(
        study_id="riverbend-synthetic-demo-v1",
        title="Riverbend synthetic district-heating study package (fully invented example)",
        classification=DatasetClassification.SYNTHETIC,
        created_at=_FIXED_TIMESTAMP, updated_at=_FIXED_TIMESTAMP,
        data_owners=[DataOwnerReference(name="R3-CHAIN prototype", organization="internal", contact=None)],
        licence=LicenceReference(licence_name="CC0-1.0 (synthetic, invented data)", use_restrictions="none"),
        unit_conventions={"length": "m", "temperature": "degC", "power": "kW", "pressure": "bar_abs"},
        approval_status=ApprovalStatus.APPROVED,
        file_inventory={
            "network/junctions.geojson": _PLACEHOLDER_HASH, "network/pipes.geojson": _PLACEHOLDER_HASH,
            "geography/candidate_sites.geojson": _PLACEHOLDER_HASH,
        },
        spatial_layers=[
            SpatialLayerReference(
                file_path="network/junctions.geojson", crs="EPSG:25832", byte_sha256=_PLACEHOLDER_HASH,
                feature_count=6, geometry_validated=True,
            ),
            SpatialLayerReference(
                file_path="network/pipes.geojson", crs="EPSG:25832", byte_sha256=_PLACEHOLDER_HASH,
                feature_count=5, geometry_validated=True,
            ),
            SpatialLayerReference(
                file_path="geography/candidate_sites.geojson", crs="EPSG:25832", byte_sha256=_PLACEHOLDER_HASH,
                feature_count=2, geometry_validated=True,
            ),
        ],
    )

    network = NetworkDataPackage(
        junctions=[
            JunctionRecord(junction_id="rb_supply_1", x_m=0.0, y_m=0.0, elevation_m=100.0, side=NetworkSide.SUPPLY),
            JunctionRecord(junction_id="rb_supply_2", x_m=300.0, y_m=0.0, elevation_m=98.0, side=NetworkSide.SUPPLY),
            JunctionRecord(junction_id="rb_return_1", x_m=0.0, y_m=10.0, elevation_m=100.0, side=NetworkSide.RETURN),
            JunctionRecord(junction_id="rb_return_2", x_m=300.0, y_m=10.0, elevation_m=98.0, side=NetworkSide.RETURN),
        ],
        pipes=[
            PipeRecord(
                pipe_id="rb_pipe_supply_1", from_junction="rb_supply_1", to_junction="rb_supply_2",
                length_m=300.0, internal_diameter_mm=200.0, material="steel", roughness_mm=0.1,
                insulation_u_value_w_per_m2k=0.2, status="active",
            ),
            PipeRecord(
                pipe_id="rb_pipe_return_1", from_junction="rb_return_2", to_junction="rb_return_1",
                length_m=300.0, internal_diameter_mm=200.0, material="steel", roughness_mm=0.1,
                insulation_u_value_w_per_m2k=0.2, status="active",
            ),
        ],
        consumers=[
            ConsumerRecord(
                consumer_id="rb_consumer_1", substation_id="rb_substation_1", design_load_kw=500.0,
                return_temperature_behavior="fixed 30 K design delta-T",
            ),
        ],
        controls=[
            ControlComponentRecord(
                component_id="rb_pump_1", kind="pump", junction_id="rb_supply_1",
                parameters={"pressure_lift_bar": 3.0},
            ),
        ],
        operating_limits=OperatingLimits(
            min_pressure_bar_abs=1.5, max_pressure_bar_abs=10.0, min_temperature_c=20.0, max_temperature_c=90.0,
        ),
        demand_profile=DemandProfileDeclaration(mode="static_demo", static_demo_note="single fixed operating point, no time series"),
        candidate_tie_in_eligible_junction_ids=["rb_supply_1", "rb_supply_2"],
    )

    geothermal_scenarios = [
        GeothermalScenarioRecord(
            scenario_id="rb_scenario_1", site_id="rb_site_1",
            geometry_or_parcel_reference="invented parcel RB-001",
            pydoublet_input_reference="fixtures/pydoublet/repaired_result.json",
            pydoublet_input_sha256="6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762"[:64],
            pydoublet_result_reference="fixtures/pydoublet/repaired_result.json",
            pydoublet_result_sha256="6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762"[:64],
            depth_m=3000.0, temperature_assumption_c=76.3, mass_flow_or_transmissivity_basis="PyDoublet reservoir model",
            fluid_salinity_note="not modelled in this synthetic example", reinjection_constraint_c=35.0,
            well_spacing_m=1000.0, well_trajectory_note="vertical doublet, invented example",
            production_pump_requirement_kw=177.4, injection_pump_requirement_kw=0.0,
            uncertainty_or_risk_note="none quantified -- synthetic example", calculation_mode="deterministic",
            upstream_commit_or_model_version="0d649c3e6930d342dac03654d57776e134c2d0b9",
        ),
    ]

    economics = [
        EconomicLineItem(
            line_item_id="rb_econ_drilling", category="drilling", value=8_000_000.0, currency="EUR",
            price_year=2026, unit_basis="per doublet", source="demo_assumption", approval_status=ApprovalStatus.PROVISIONAL,
            uncertainty_range=(6_000_000.0, 10_000_000.0), inclusion_note="doublet CAPEX only",
        ),
    ]

    decisions = StudyDecisionPolicy(ranking_policy="feasibility_first_then_lowest_annualised_cost", objective_weights=None)

    return StudyPackage(
        manifest=manifest, network=network, geothermal_scenarios=geothermal_scenarios,
        economics=economics, decisions=decisions,
    )


def build_intentionally_incomplete_real_package() -> StudyPackage:
    """AC-09: missing exactly a spatial layer's CRS, one pipe's diameter,
    and one geothermal scenario's PyDoublet provenance -- constructible
    (structurally valid Pydantic objects) but semantically incomplete,
    for validate_study_package()/generate_readiness_report() to catch."""
    manifest = StudyPackageManifest(
        study_id="incomplete-real-example-v1",
        title="Intentionally incomplete real-mode example (AC-09) -- not a real study",
        classification=DatasetClassification.REAL,
        created_at=_FIXED_TIMESTAMP, updated_at=_FIXED_TIMESTAMP,
        data_owners=[DataOwnerReference(name="AC-09 test fixture", organization="internal", contact=None)],
        licence=LicenceReference(licence_name="not applicable -- test fixture", use_restrictions="internal test use only"),
        unit_conventions={"length": "m"},
        approval_status=ApprovalStatus.PROVISIONAL,
        file_inventory={"network/junctions.geojson": _PLACEHOLDER_HASH},
        spatial_layers=[
            SpatialLayerReference(
                file_path="network/junctions.geojson", crs="",  # MISSING CRS (AC-09)
                byte_sha256=_PLACEHOLDER_HASH, feature_count=2, geometry_validated=False,
            ),
        ],
    )

    network = NetworkDataPackage(
        junctions=[
            JunctionRecord(junction_id="j1", x_m=0.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
            JunctionRecord(junction_id="j2", x_m=100.0, y_m=0.0, elevation_m=0.0, side=NetworkSide.SUPPLY),
        ],
        pipes=[
            PipeRecord(
                pipe_id="p1", from_junction="j1", to_junction="j2", length_m=100.0,
                internal_diameter_mm=0.0,  # MISSING PIPE DIAMETER (AC-09)
                material="unknown", roughness_mm=0.1, status="active",
            ),
        ],
        consumers=[],
        operating_limits=OperatingLimits(min_pressure_bar_abs=1.0, max_pressure_bar_abs=6.0, min_temperature_c=0.0, max_temperature_c=100.0),
        demand_profile=DemandProfileDeclaration(mode="static_demo", static_demo_note="fixture only"),
    )

    geothermal_scenarios = [
        GeothermalScenarioRecord(
            scenario_id="s1", site_id="site1", geometry_or_parcel_reference="unknown",
            pydoublet_input_reference="unknown",
            pydoublet_input_sha256=None,  # MISSING PROVENANCE (AC-09)
            pydoublet_result_reference="unknown",
            pydoublet_result_sha256=None,  # MISSING PROVENANCE (AC-09)
            depth_m=2000.0, temperature_assumption_c=70.0, mass_flow_or_transmissivity_basis="unknown",
            reinjection_constraint_c=35.0, well_spacing_m=500.0, well_trajectory_note="unknown",
            production_pump_requirement_kw=0.0, injection_pump_requirement_kw=0.0,
            uncertainty_or_risk_note="unknown", calculation_mode="unknown",
            upstream_commit_or_model_version="unknown",
        ),
    ]

    return StudyPackage(manifest=manifest, network=network, geothermal_scenarios=geothermal_scenarios, economics=[], decisions=None)
