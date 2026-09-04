"""Full test matrix for data_contracts/joint_study.py -- Phase 1 of
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md:
typed contracts (S7), relationship validation (DATA-001..022, so far as
checkable at the schema level), and active-dimension reporting
(TERM-003..005, AC-J02/AC-J03)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r3chain_geothermal.data_contracts import DatasetClassification
from r3chain_geothermal.data_contracts.joint_study import (
    AssumptionStatus,
    AttachmentEligibilityStatus,
    ConnectionDesignOption,
    Coordinate,
    CoordinateReference,
    DecisionPolicy,
    DecisionPolicyMode,
    GeographicCoordinate,
    GeologicalMetadata,
    GeothermalResourceScenario,
    AlternativeIdentity as JointAlternativeIdentity,
    JointEconomicPolicy,
    JointStudyPackage,
    NetworkAttachment,
    NetworkReference,
    NetworkSourceKind,
    ObjectiveDefinition,
    ObjectiveDirection,
    OperatingPolicyReference,
    ProjectedCoordinate,
    ResourceInputReference,
    ResourceInputSourceKind,
    RouteKind,
    RouteRejectionCode,
    RouteScreeningStatus,
    RoutingPolicy,
    ShortfallMode,
    SiteAvailabilityStatus,
    SiteConnectionRoute,
    SiteEconomicInputs,
    StudyApprovalStatus,
    StudyProvenance,
    SurfaceSite,
    SyntheticCoordinate,
    SyntheticDerivation,
    SyntheticDerivationFieldChange,
    TemporalBasis,
    compute_active_dimensions,
    compute_polyline_length_m,
    validate_joint_study_package,
    validate_route_against_site_and_attachment,
)

_TS = datetime(2026, 9, 4, tzinfo=timezone.utc)
_HASH = "0" * 64
_HASH2 = "1" * 64


def _synthetic_coord(x: float, y: float) -> SyntheticCoordinate:
    return SyntheticCoordinate(x_m=x, y_m=y)


def _site(**overrides) -> SurfaceSite:
    kwargs = dict(
        site_id="site_A", label="Site A", classification=DatasetClassification.SYNTHETIC,
        coordinate=_synthetic_coord(0.0, 0.0), availability_status=SiteAvailabilityStatus.AVAILABLE,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
    )
    kwargs.update(overrides)
    return SurfaceSite(**kwargs)


def _resource_input(**overrides) -> ResourceInputReference:
    kwargs = dict(
        resource_input_id="input_A", source_kind=ResourceInputSourceKind.PRIMARY_RUNTIME_INPUT,
        expected_raw_sha256=_HASH, provenance_reference="fixtures/pydoublet/repaired_result.json",
        classification=DatasetClassification.SYNTHETIC,
    )
    kwargs.update(overrides)
    return ResourceInputReference(**kwargs)


def _geological_metadata(**overrides) -> GeologicalMetadata:
    kwargs: dict = {}
    kwargs.update(overrides)
    return GeologicalMetadata(**kwargs)


def _economic_inputs(**overrides) -> SiteEconomicInputs:
    kwargs = dict(
        doublet_capex_eur=8_000_000.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="demo",
    )
    kwargs.update(overrides)
    return SiteEconomicInputs(**kwargs)


def _scenario(**overrides) -> GeothermalResourceScenario:
    kwargs = dict(
        scenario_id="scenario_A", site_id="site_A", scenario_label="Golden", classification=DatasetClassification.SYNTHETIC,
        resource_input_id="input_A", temporal_basis=TemporalBasis.LIFETIME_AVERAGE_STEADY,
        geological_metadata=_geological_metadata(), economic_inputs=_economic_inputs(),
    )
    kwargs.update(overrides)
    return GeothermalResourceScenario(**kwargs)


def _attachment(**overrides) -> NetworkAttachment:
    kwargs = dict(
        attachment_id="trunk_1", supply_junction_id="trunk_1", return_junction_id="ret_trunk_1",
        pressure_zone_id="zone_1", eligibility_status=AttachmentEligibilityStatus.ELIGIBLE,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
    )
    kwargs.update(overrides)
    return NetworkAttachment(**kwargs)


def _design_option(**overrides) -> ConnectionDesignOption:
    kwargs = dict(
        design_option_id="standard", connection_pipe_inner_diameter_mm=200.0, pipe_roughness_mm=0.1,
        capex_eur_per_paired_trench_m=1000.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="demo",
    )
    kwargs.update(overrides)
    return ConnectionDesignOption(**kwargs)


def _operating_policy(**overrides) -> OperatingPolicyReference:
    kwargs = dict(
        operating_policy_id="standard", policy_schema_version="1.0.0",
        package_relative_path="config/operating_policy.json", source_sha256=_HASH,
        shortfall_mode=ShortfallMode.AUXILIARY, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="demo",
    )
    kwargs.update(overrides)
    return OperatingPolicyReference(**kwargs)


def _network_reference(**overrides) -> NetworkReference:
    kwargs = dict(
        network_id="r3chain-synthetic-network-v1", network_schema_version="1.0.0",
        source_kind=NetworkSourceKind.COMMITTED_BLUEPRINT, package_relative_path="network/geometry.py",
        source_sha256=_HASH, topology_scientific_fingerprint=_HASH2,
        classification=DatasetClassification.SYNTHETIC, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="demo",
    )
    kwargs.update(overrides)
    return NetworkReference(**kwargs)


def _routing_policy(**overrides) -> RoutingPolicy:
    kwargs = dict(
        route_kind=RouteKind.SYNTHETIC_POLYLINE, maximum_paired_trench_length_m=250.0,
        allowed_attachment_ids=["trunk_1"], shared_trench=True,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
    )
    kwargs.update(overrides)
    return RoutingPolicy(**kwargs)


def _decision_policy(**overrides) -> DecisionPolicy:
    objective = ObjectiveDefinition(
        name="indicative_system_lcoh_eur_per_mwh", direction=ObjectiveDirection.MINIMIZE,
        absolute_materiality=0.5, relative_materiality_fraction=0.01, unit="EUR/MWh",
        rationale="primary cost signal", source_reference="demo",
    )
    kwargs = dict(mode=DecisionPolicyMode.PARETO_ONLY, objectives=[objective], allow_shared_rank=True)
    kwargs.update(overrides)
    return DecisionPolicy(**kwargs)


def _economics(**overrides) -> JointEconomicPolicy:
    kwargs = dict(
        economic_policy_id="demo-econ", economic_schema_version="1.0.0",
        base_assumptions_package_relative_path="config/demo_assumptions.json", base_assumptions_sha256=_HASH,
        annual_operating_hours=8000.0, discount_rate_fraction=0.04, analysis_period_years=25,
        electricity_price_eur_per_mwh=180.0, auxiliary_heat_price_eur_per_mwh=90.0, price_year=2026,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
    )
    kwargs.update(overrides)
    return JointEconomicPolicy(**kwargs)


def _provenance(**overrides) -> StudyProvenance:
    kwargs = dict(
        created_at_utc=_TS, created_by="test-suite", repository_commit="1fa8d39",
        software_version="0.1.0", parent_input_sha256=[_HASH], classification=DatasetClassification.SYNTHETIC,
        approval_status=StudyApprovalStatus.SYNTHETIC_DEMO_APPROVED,
    )
    kwargs.update(overrides)
    return StudyProvenance(**kwargs)


def _package(**overrides) -> JointStudyPackage:
    kwargs = dict(
        study_id="joint-study-v2-demo", classification=DatasetClassification.SYNTHETIC,
        coordinate_reference=CoordinateReference(
            kind="synthetic_cartesian", identifier="r3chain-synthetic-network-v1", horizontal_unit="m", axis_order=["x", "y"],
        ),
        sites=[_site()], resource_inputs=[_resource_input()], resource_scenarios=[_scenario()],
        network_reference=_network_reference(), network_attachments=[_attachment()],
        routing_policy=_routing_policy(), design_options=[_design_option()],
        operating_policies=[_operating_policy()], economics=_economics(),
        decision_policy=_decision_policy(), provenance=_provenance(),
    )
    kwargs.update(overrides)
    return JointStudyPackage(**kwargs)


# ── TEST-001: deterministic ID validation/serialization ─────────────────────
def test_valid_package_constructs_and_round_trips_through_json():
    package = _package()
    reloaded = JointStudyPackage.model_validate_json(package.model_dump_json())
    assert reloaded == package
    assert package.contract_schema_version == "2.0.0"


def test_alternative_identity_is_deterministic_and_never_needs_parsing():
    identity = JointAlternativeIdentity(
        resource_scenario_id="scenario_A", surface_site_id="site_A", attachment_id="trunk_1",
        route_id="route_1", design_option_id="standard", operating_policy_id="standard",
    )
    assert identity.alternative_id == "scenario_A|site_A|trunk_1|route_1|standard|standard"
    # Same six fields -> same id, constructed independently (no shared state).
    identity_2 = JointAlternativeIdentity(
        resource_scenario_id="scenario_A", surface_site_id="site_A", attachment_id="trunk_1",
        route_id="route_1", design_option_id="standard", operating_policy_id="standard",
    )
    assert identity.alternative_id == identity_2.alternative_id


def test_alternative_identity_rejects_an_empty_field():
    with pytest.raises(ValidationError):
        JointAlternativeIdentity(
            resource_scenario_id="", surface_site_id="site_A", attachment_id="trunk_1",
            route_id="route_1", design_option_id="standard", operating_policy_id="standard",
        )


# ── TEST-002: missing site reference is rejected ─────────────────────────────
def test_scenario_referencing_unknown_site_is_rejected():
    package = _package(resource_scenarios=[_scenario(site_id="nonexistent_site")])
    result = validate_joint_study_package(package)
    assert not result.valid
    codes = {e.error_code.value for e in result.errors}
    assert "SCENARIO_SITE_MISMATCH" in codes


def test_scenario_referencing_unknown_resource_input_is_rejected():
    package = _package(resource_scenarios=[_scenario(resource_input_id="nonexistent_input")])
    result = validate_joint_study_package(package)
    assert not result.valid
    codes = {e.error_code.value for e in result.errors}
    assert "SCENARIO_RESOURCE_INPUT_MISMATCH" in codes


def test_valid_package_passes_relationship_validation():
    result = validate_joint_study_package(_package())
    assert result.valid
    assert result.errors == []


def test_duplicate_site_id_is_rejected():
    package = _package(sites=[_site(), _site()])
    result = validate_joint_study_package(package)
    assert not result.valid
    assert any(e.error_code.value == "DUPLICATE_ID" for e in result.errors)


# ── TEST-003/004: route origin/endpoint mismatch rejected ────────────────────
def _route(**overrides) -> SiteConnectionRoute:
    kwargs = dict(
        route_id="route_1", site_id="site_A", attachment_id="trunk_1", route_kind=RouteKind.SYNTHETIC_POLYLINE,
        route_geometry=[_synthetic_coord(0.0, 0.0), _synthetic_coord(50.0, 0.0)],
        paired_trench_length_m=50.0, supply_pipe_length_m=50.0, return_pipe_length_m=50.0,
        screening_status=RouteScreeningStatus.ACCEPTED,
    )
    kwargs.update(overrides)
    return SiteConnectionRoute(**kwargs)


def test_route_matching_its_declared_site_and_attachment_has_no_errors():
    route = _route()
    site = _site()
    attachment = _attachment()
    assert validate_route_against_site_and_attachment(route, site, attachment) == []


def test_route_with_mismatched_site_id_is_rejected():
    route = _route(site_id="other_site")
    errors = validate_route_against_site_and_attachment(route, _site(), _attachment())
    assert any(e.error_code.value == "ROUTE_SITE_MISMATCH" for e in errors)


def test_route_with_mismatched_attachment_id_is_rejected():
    route = _route(attachment_id="other_attachment")
    errors = validate_route_against_site_and_attachment(route, _site(), _attachment())
    assert any(e.error_code.value == "ROUTE_ATTACHMENT_MISMATCH" for e in errors)


def test_route_geometry_not_starting_at_site_coordinate_is_rejected():
    wrong_start = _synthetic_coord(999.0, 999.0)
    end = _synthetic_coord(50.0, 0.0)
    geometry = [wrong_start, end]
    route = _route(route_geometry=geometry, paired_trench_length_m=compute_polyline_length_m(geometry))
    errors = validate_route_against_site_and_attachment(route, _site(), _attachment())
    assert any(e.error_code.value == "ROUTE_SITE_MISMATCH" for e in errors)


# ── TEST-005: polyline length calculated correctly ───────────────────────────
def test_polyline_length_is_the_sum_of_consecutive_euclidean_distances():
    geometry = [_synthetic_coord(0.0, 0.0), _synthetic_coord(3.0, 4.0), _synthetic_coord(3.0, 10.0)]
    assert compute_polyline_length_m(geometry) == pytest.approx(5.0 + 6.0)


def test_projected_coordinate_polyline_length_also_computed():
    geometry = [ProjectedCoordinate(easting_m=0.0, northing_m=0.0), ProjectedCoordinate(easting_m=6.0, northing_m=8.0)]
    assert compute_polyline_length_m(geometry) == pytest.approx(10.0)


def test_geographic_coordinate_polyline_length_is_not_silently_computed():
    """GOV-012: a lon/lat polyline has no Euclidean length in metres --
    this must raise, never silently return a wrong number."""
    geometry = [GeographicCoordinate(longitude_deg=7.0, latitude_deg=51.0), GeographicCoordinate(longitude_deg=7.1, latitude_deg=51.1)]
    with pytest.raises(ValueError, match="geodesic"):
        compute_polyline_length_m(geometry)


def test_route_rejects_a_declared_length_disagreeing_with_geometry():
    with pytest.raises(ValidationError):
        _route(paired_trench_length_m=999.0)  # geometry-derived length is 50.0


def test_route_with_geographic_geometry_cannot_be_accepted():
    with pytest.raises(ValidationError):
        _route(
            route_geometry=[GeographicCoordinate(longitude_deg=7.0, latitude_deg=51.0), GeographicCoordinate(longitude_deg=7.1, latitude_deg=51.1)],
            paired_trench_length_m=50.0,
        )


# ── TEST-006: excluded site/route retained with reason ───────────────────────
def test_excluded_site_is_retained_with_its_reason_not_dropped():
    site = _site(availability_status=SiteAvailabilityStatus.EXCLUDED, exclusion_reason="protected geometry demonstration")
    assert site.availability_status == SiteAvailabilityStatus.EXCLUDED
    assert site.exclusion_reason


def test_excluded_site_without_a_reason_is_rejected():
    with pytest.raises(ValidationError):
        _site(availability_status=SiteAvailabilityStatus.EXCLUDED, exclusion_reason=None)


def test_rejected_route_is_retained_with_its_reason_not_dropped():
    route = _route(
        screening_status=RouteScreeningStatus.REJECTED, rejection_code=RouteRejectionCode.LENGTH_EXCEEDS_LIMIT,
        rejection_detail="declared route exceeds the maximum paired-trench length",
    )
    assert route.screening_status == RouteScreeningStatus.REJECTED
    assert route.rejection_code == RouteRejectionCode.LENGTH_EXCEEDS_LIMIT
    assert route.rejection_detail


def test_rejected_route_without_a_reason_code_is_rejected_at_construction():
    with pytest.raises(ValidationError):
        _route(screening_status=RouteScreeningStatus.REJECTED, rejection_code=None, rejection_detail="too long")


def test_accepted_route_must_not_carry_a_rejection_code():
    with pytest.raises(ValidationError):
        _route(rejection_code=RouteRejectionCode.LENGTH_EXCEEDS_LIMIT)


# ── TEST-007: synthetic derivation recorded and physically valid ─────────────
def test_synthetic_derivation_records_the_real_v1_perturbations():
    """Mirrors the actual perturbations workflow/joint_optimization.py's
    v1 build_synthetic_geothermal_scenarios() applies for its scenario_C
    (mass-flow scaled to 70% of golden, doublet_capex_multiplier=1.15,
    pump power and raw power recomputed as a consequence) -- proving the
    v2 derivation record can faithfully describe them."""
    derivation = SyntheticDerivation(
        source_fixture_sha256=_HASH,
        field_changes=[
            SyntheticDerivationFieldChange(
                field_name="geothermal_brine_mass_flow_kg_s", original_value=28.749278, transformed_value=28.749278 * 0.7,
                transformation_formula="mass_flow * 0.7",
            ),
            SyntheticDerivationFieldChange(
                field_name="raw_geothermal_thermal_power_kw", original_value=4345.417312, transformed_value=3041.8,
                transformation_formula="mass_flow * cp * (T_prod - T_brine_outlet) / 1000", is_recomputed_consequence=True,
            ),
            SyntheticDerivationFieldChange(
                field_name="doublet_pump_electric_power_kw", original_value=177.449827, transformed_value=124.21,
                transformation_formula="golden_pump_power_kw * (mass_flow_kg_s / golden_mass_flow_kg_s)", is_recomputed_consequence=True,
            ),
        ],
        doublet_capex_multiplier=1.15,
        rationale="declared, illustrative 'deeper/more difficult reservoir' assumption chosen before evaluation",
        author_or_decision_reference="IMPL-021",
    )
    scenario = _scenario(derivation=derivation)
    assert scenario.derivation is not None
    assert scenario.derivation.doublet_capex_multiplier == pytest.approx(1.15)
    assert len(scenario.derivation.field_changes) == 3
    assert sum(1 for c in scenario.derivation.field_changes if c.is_recomputed_consequence) == 2


def test_synthetic_derivation_field_name_is_the_corrected_doublet_capex_multiplier():
    """TERM-008/ECON-001: the v2 field is named doublet_capex_multiplier
    -- the v1 name (drilling_capex_multiplier) is not reused here."""
    assert "doublet_capex_multiplier" in SyntheticDerivation.model_fields
    assert "drilling_capex_multiplier" not in SyntheticDerivation.model_fields


def test_real_scenario_cannot_carry_a_synthetic_derivation():
    """TEST-008: a real scenario cannot use a synthetic multiplier."""
    derivation = SyntheticDerivation(
        source_fixture_sha256=_HASH,
        field_changes=[SyntheticDerivationFieldChange(
            field_name="x", original_value=1.0, transformed_value=2.0, transformation_formula="x*2",
        )],
        doublet_capex_multiplier=1.0, rationale="r", author_or_decision_reference="ref",
    )
    with pytest.raises(ValidationError):
        _scenario(classification=DatasetClassification.REAL, derivation=derivation)


# ── SiteEconomicInputs: aggregate vs. component CAPEX (ECON-002/014) ────────
def test_aggregate_and_component_capex_cannot_both_be_set():
    with pytest.raises(ValidationError):
        _economic_inputs(doublet_capex_eur=8_000_000.0, drilling_producer_well_capex_eur=3_000_000.0)


def test_partial_component_breakdown_is_rejected():
    with pytest.raises(ValidationError):
        _economic_inputs(doublet_capex_eur=None, drilling_producer_well_capex_eur=3_000_000.0)


def test_complete_component_breakdown_is_accepted():
    inputs = _economic_inputs(
        doublet_capex_eur=None, drilling_producer_well_capex_eur=1.0, drilling_injector_well_capex_eur=1.0,
        well_completion_capex_eur=1.0, surface_plant_capex_eur=1.0, contingency_capex_eur=1.0,
    )
    assert inputs.doublet_capex_eur is None


# ── AC-J02/AC-J03/TERM-003..005: active-dimension reporting ─────────────────
def test_single_site_single_scenario_package_reports_every_dimension_controlled():
    report = compute_active_dimensions(_package())
    assert report.active_dimensions == []
    assert set(report.controlled_dimensions) == {
        "surface_site_id", "resource_scenario_id", "attachment_id", "design_option_id", "operating_policy_id",
    }
    assert all(count <= 1 for count in report.cardinalities.values())


def test_two_scenarios_on_one_site_makes_scenario_dimension_active():
    """AC-J03: every scenario belongs to one site, and at least one site
    has multiple scenarios -- that scenario dimension must then report
    as active, nested under a still-controlled site dimension (TERM-005)."""
    package = _package(resource_scenarios=[
        _scenario(scenario_id="scenario_A"),
        _scenario(scenario_id="scenario_B"),
    ])
    report = compute_active_dimensions(package)
    assert "resource_scenario_id" in report.active_dimensions
    assert "surface_site_id" in report.controlled_dimensions  # still one site
    assert any("depends on surface_site_id" in note for note in report.dependency_notes)


def test_two_sites_makes_site_dimension_active():
    package = _package(
        sites=[_site(site_id="site_A"), _site(site_id="site_B")],
        resource_scenarios=[_scenario(site_id="site_A"), _scenario(scenario_id="scenario_B", site_id="site_B")],
    )
    report = compute_active_dimensions(package)
    assert "surface_site_id" in report.active_dimensions
    assert "resource_scenario_id" in report.active_dimensions


# ── DecisionPolicy (DEC-003/008/009) ─────────────────────────────────────────
def test_pareto_only_policy_forbids_a_primary_objective():
    with pytest.raises(ValidationError):
        _decision_policy(mode=DecisionPolicyMode.PARETO_ONLY, primary_objective="indicative_system_lcoh_eur_per_mwh")


def test_primary_objective_ranking_requires_a_declared_primary_objective():
    with pytest.raises(ValidationError):
        _decision_policy(mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, primary_objective=None)


def test_primary_objective_ranking_with_a_declared_objective_is_accepted():
    policy = _decision_policy(mode=DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING, primary_objective="indicative_system_lcoh_eur_per_mwh")
    assert policy.primary_objective == "indicative_system_lcoh_eur_per_mwh"


def test_duplicate_objective_names_are_rejected():
    objective = ObjectiveDefinition(
        name="dup", direction=ObjectiveDirection.MINIMIZE, absolute_materiality=0.1,
        relative_materiality_fraction=0.01, unit="EUR", rationale="r", source_reference="s",
    )
    with pytest.raises(ValidationError):
        DecisionPolicy(mode=DecisionPolicyMode.PARETO_ONLY, objectives=[objective, objective], allow_shared_rank=True)


# ── Coordinate discriminated union / classification-coordinate pairing ──────
def test_synthetic_site_cannot_use_a_projected_coordinate():
    with pytest.raises(ValidationError):
        _site(coordinate=ProjectedCoordinate(easting_m=1.0, northing_m=1.0))


def test_real_site_cannot_use_a_synthetic_coordinate():
    with pytest.raises(ValidationError):
        _site(classification=DatasetClassification.REAL, coordinate=_synthetic_coord(0.0, 0.0))


def test_package_classification_must_match_provenance_classification():
    with pytest.raises(ValidationError):
        _package(provenance=_provenance(classification=DatasetClassification.REAL, approval_status=StudyApprovalStatus.REAL_STUDY_APPROVED, approval_reference="ref"))
