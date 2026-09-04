"""Focused unit tests for workflow/joint_enumeration.py in isolation --
S1.2's compatible-search-set definition, proven with a small hand-built
two-site package (not the full committed fixture; see
tests/workflow/test_joint_phase2.py for the end-to-end integration
proof)."""
from __future__ import annotations

from datetime import datetime, timezone

from r3chain_geothermal.data_contracts.joint_study import (
    AssumptionStatus,
    AttachmentEligibilityStatus,
    ConnectionDesignOption,
    CoordinateReference,
    DecisionPolicy,
    DecisionPolicyMode,
    GeologicalMetadata,
    GeothermalResourceScenario,
    JointEconomicPolicy,
    JointStudyPackage,
    NetworkAttachment,
    NetworkReference,
    NetworkSourceKind,
    ObjectiveDefinition,
    ObjectiveDirection,
    OperatingPolicyReference,
    ResourceInputReference,
    ResourceInputSourceKind,
    RouteKind,
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
    TemporalBasis,
)
from r3chain_geothermal.data_contracts.schema import DatasetClassification
from r3chain_geothermal.workflow.joint_enumeration import enumerate_compatible_alternatives, possible_combination_count

_HASH = "0" * 64
_TS = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _minimal_package(*, two_scenarios_on_site_a: bool = False) -> JointStudyPackage:
    scenarios = [
        GeothermalResourceScenario(
            scenario_id="scenario_a1", site_id="site_a", scenario_label="a1", classification=DatasetClassification.SYNTHETIC,
            resource_input_id="input_1", temporal_basis=TemporalBasis.LIFETIME_AVERAGE_STEADY,
            geological_metadata=GeologicalMetadata(),
            economic_inputs=SiteEconomicInputs(doublet_capex_eur=1.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t"),
        ),
        GeothermalResourceScenario(
            scenario_id="scenario_b1", site_id="site_b", scenario_label="b1", classification=DatasetClassification.SYNTHETIC,
            resource_input_id="input_1", temporal_basis=TemporalBasis.LIFETIME_AVERAGE_STEADY,
            geological_metadata=GeologicalMetadata(),
            economic_inputs=SiteEconomicInputs(doublet_capex_eur=1.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t"),
        ),
    ]
    if two_scenarios_on_site_a:
        scenarios.append(GeothermalResourceScenario(
            scenario_id="scenario_a2", site_id="site_a", scenario_label="a2", classification=DatasetClassification.SYNTHETIC,
            resource_input_id="input_1", temporal_basis=TemporalBasis.LIFETIME_AVERAGE_STEADY,
            geological_metadata=GeologicalMetadata(),
            economic_inputs=SiteEconomicInputs(doublet_capex_eur=1.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t"),
        ))

    return JointStudyPackage(
        study_id="unit-test-package", classification=DatasetClassification.SYNTHETIC,
        coordinate_reference=CoordinateReference(kind="synthetic_cartesian", identifier="test", horizontal_unit="m", axis_order=["x", "y"]),
        sites=[
            SurfaceSite(
                site_id="site_a", label="A", classification=DatasetClassification.SYNTHETIC, coordinate=SyntheticCoordinate(x_m=0.0, y_m=0.0),
                availability_status=SiteAvailabilityStatus.AVAILABLE, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
            ),
            SurfaceSite(
                site_id="site_b", label="B", classification=DatasetClassification.SYNTHETIC, coordinate=SyntheticCoordinate(x_m=100.0, y_m=0.0),
                availability_status=SiteAvailabilityStatus.AVAILABLE, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
            ),
        ],
        resource_inputs=[ResourceInputReference(
            resource_input_id="input_1", source_kind=ResourceInputSourceKind.PRIMARY_RUNTIME_INPUT,
            expected_raw_sha256=_HASH, provenance_reference="t", classification=DatasetClassification.SYNTHETIC,
        )],
        resource_scenarios=scenarios,
        network_reference=NetworkReference(
            network_id="n", network_schema_version="1.0.0", source_kind=NetworkSourceKind.COMMITTED_BLUEPRINT,
            package_relative_path="x", source_sha256=_HASH, topology_scientific_fingerprint=_HASH,
            classification=DatasetClassification.SYNTHETIC, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        ),
        network_attachments=[NetworkAttachment(
            attachment_id="att_1", supply_junction_id="j1", return_junction_id="ret_j1", pressure_zone_id="z1",
            eligibility_status=AttachmentEligibilityStatus.ELIGIBLE, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        )],
        routing_policy=RoutingPolicy(
            route_kind=RouteKind.SYNTHETIC_POLYLINE, maximum_paired_trench_length_m=1000.0, allowed_attachment_ids=["att_1"],
            shared_trench=True, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        ),
        design_options=[ConnectionDesignOption(
            design_option_id="d1", connection_pipe_inner_diameter_mm=200.0, pipe_roughness_mm=0.1,
            capex_eur_per_paired_trench_m=1.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        )],
        operating_policies=[OperatingPolicyReference(
            operating_policy_id="p1", policy_schema_version="1.0.0", package_relative_path="x", source_sha256=_HASH,
            shortfall_mode=ShortfallMode.AUXILIARY, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        )],
        economics=JointEconomicPolicy(
            economic_policy_id="e1", economic_schema_version="1.0.0", base_assumptions_package_relative_path="x",
            base_assumptions_sha256=_HASH, annual_operating_hours=8000.0, discount_rate_fraction=0.04,
            analysis_period_years=25, electricity_price_eur_per_mwh=1.0, auxiliary_heat_price_eur_per_mwh=1.0,
            price_year=2026, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="t",
        ),
        decision_policy=DecisionPolicy(
            mode=DecisionPolicyMode.PARETO_ONLY,
            objectives=[ObjectiveDefinition(
                name="obj", direction=ObjectiveDirection.MINIMIZE, absolute_materiality=0.1,
                relative_materiality_fraction=0.01, unit="x", rationale="t", source_reference="t",
            )],
            allow_shared_rank=True,
        ),
        provenance=StudyProvenance(
            created_at_utc=_TS, created_by="t", repository_commit="deadbeef", software_version="0.1.0",
            parent_input_sha256=[_HASH], classification=DatasetClassification.SYNTHETIC,
            approval_status=StudyApprovalStatus.SYNTHETIC_DEMO_APPROVED,
        ),
    )


def _route(route_id: str, site_id: str, status: RouteScreeningStatus = RouteScreeningStatus.ACCEPTED, **overrides) -> SiteConnectionRoute:
    kwargs = dict(
        route_id=route_id, site_id=site_id, attachment_id="att_1", route_kind=RouteKind.SYNTHETIC_POLYLINE,
        route_geometry=[SyntheticCoordinate(x_m=0.0, y_m=0.0), SyntheticCoordinate(x_m=10.0, y_m=0.0)],
        paired_trench_length_m=10.0, supply_pipe_length_m=10.0, return_pipe_length_m=10.0, screening_status=status,
    )
    kwargs.update(overrides)
    return SiteConnectionRoute(**kwargs)


def test_scenario_is_never_paired_with_a_route_from_a_different_site():
    package = _minimal_package()
    routes = [_route("r_a", "site_a"), _route("r_b", "site_b")]
    identities = enumerate_compatible_alternatives(package, routes)
    ids = {(i.resource_scenario_id, i.route_id) for i in identities}
    assert ("scenario_a1", "r_b") not in ids
    assert ("scenario_b1", "r_a") not in ids
    assert ("scenario_a1", "r_a") in ids
    assert ("scenario_b1", "r_b") in ids


def test_rejected_routes_never_enter_the_compatible_set():
    from r3chain_geothermal.data_contracts.joint_study import RouteRejectionCode

    package = _minimal_package()
    routes = [
        _route("r_a", "site_a"),
        _route(
            "r_a_rejected", "site_a", status=RouteScreeningStatus.REJECTED,
            rejection_code=RouteRejectionCode.LENGTH_EXCEEDS_LIMIT, rejection_detail="too long",
        ),
    ]
    identities = enumerate_compatible_alternatives(package, routes)
    route_ids_used = {i.route_id for i in identities}
    assert "r_a_rejected" not in route_ids_used
    assert "r_a" in route_ids_used


def test_two_scenarios_on_one_site_both_enumerate_against_that_sites_own_routes():
    """AC-J03's own consequence for enumeration: a second scenario on
    site_a must be paired with site_a's own routes too, not skipped."""
    package = _minimal_package(two_scenarios_on_site_a=True)
    routes = [_route("r_a", "site_a")]
    identities = enumerate_compatible_alternatives(package, routes)
    scenario_ids = {i.resource_scenario_id for i in identities if i.route_id == "r_a"}
    assert scenario_ids == {"scenario_a1", "scenario_a2"}


def test_possible_combination_count_exceeds_compatible_when_multiple_sites_exist():
    package = _minimal_package()
    routes = [_route("r_a", "site_a"), _route("r_b", "site_b")]
    possible = possible_combination_count(package, routes)
    compatible = len(enumerate_compatible_alternatives(package, routes))
    # possible = 2 scenarios x 2 routes x 1 design x 1 policy = 4 (an
    # unconstrained product would include scenario_a1 x r_b, which is
    # NOT physically meaningful); compatible = 2 (only same-site pairs).
    assert possible == 4
    assert compatible == 2
    assert compatible < possible


def test_enumeration_is_deterministically_ordered():
    package = _minimal_package(two_scenarios_on_site_a=True)
    routes = [_route("r_a", "site_a"), _route("r_b", "site_b")]
    ids_1 = [i.alternative_id for i in enumerate_compatible_alternatives(package, routes)]
    ids_2 = [i.alternative_id for i in enumerate_compatible_alternatives(package, routes)]
    assert ids_1 == ids_2
    assert ids_1 == sorted(ids_1, key=lambda x: (x.split("|")[1], x.split("|")[0], x.split("|")[2]))
