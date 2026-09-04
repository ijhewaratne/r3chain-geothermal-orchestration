"""Full test matrix for network/site_routing.py -- Phase 2 of
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md:
site-origin-aware route generation and screening (S9, ROUTE-001..012)."""
from __future__ import annotations

import pytest

from r3chain_geothermal.data_contracts.joint_study import (
    AssumptionStatus,
    AttachmentEligibilityStatus,
    DetourDefinition,
    ExclusionAppliesTo,
    ExclusionDefinition,
    NetworkAttachment,
    RouteKind,
    RouteRejectionCode,
    RouteScreeningStatus,
    RoutingPolicy,
    SiteAvailabilityStatus,
    SurfaceSite,
    SyntheticCoordinate,
)
from r3chain_geothermal.data_contracts.schema import DatasetClassification
from r3chain_geothermal.network.site_routing import generate_site_routes


def _site(site_id: str, x: float, y: float, **overrides) -> SurfaceSite:
    kwargs = dict(
        site_id=site_id, label=site_id, classification=DatasetClassification.SYNTHETIC,
        coordinate=SyntheticCoordinate(x_m=x, y_m=y), availability_status=SiteAvailabilityStatus.AVAILABLE,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="test",
    )
    kwargs.update(overrides)
    return SurfaceSite(**kwargs)


def _attachment(attachment_id: str, supply_junction_id: str, **overrides) -> NetworkAttachment:
    kwargs = dict(
        attachment_id=attachment_id, supply_junction_id=supply_junction_id, return_junction_id=f"ret_{supply_junction_id}",
        pressure_zone_id="zone_1", eligibility_status=AttachmentEligibilityStatus.ELIGIBLE,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="test",
    )
    kwargs.update(overrides)
    return NetworkAttachment(**kwargs)


def _policy(**overrides) -> RoutingPolicy:
    kwargs = dict(
        route_kind=RouteKind.SYNTHETIC_POLYLINE, maximum_paired_trench_length_m=300.0,
        allowed_attachment_ids=["trunk_1", "trunk_2"], shared_trench=True,
        assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="test",
    )
    kwargs.update(overrides)
    return RoutingPolicy(**kwargs)


_TRUNK_1 = _attachment("trunk_1", "trunk_1")
_TRUNK_2 = _attachment("trunk_2", "trunk_2")


# ── ROUTE-005/AC-J04: geometry-derived length, never a global table ─────────
def test_route_length_is_geometry_derived_not_a_global_table():
    site = _site("site_A", 250.0, -60.0)  # 60 m straight from trunk_1 at (250, 0)
    routes = generate_site_routes([site], [_TRUNK_1], _policy(allowed_attachment_ids=["trunk_1"]))
    accepted = [r for r in routes if r.screening_status == RouteScreeningStatus.ACCEPTED]
    assert len(accepted) == 1
    assert accepted[0].paired_trench_length_m == pytest.approx(60.0)
    assert accepted[0].supply_pipe_length_m == pytest.approx(60.0)
    assert accepted[0].return_pipe_length_m == pytest.approx(60.0)


def test_ac_j04_same_attachment_two_sites_two_different_lengths():
    """AC-J04: the SAME attachment evaluated from two different sites has
    two different geometry-derived route lengths -- proof this is a real
    per-site geometry calculation, not one shared distance re-labelled."""
    site_near = _site("site_near", 500.0, -50.0)   # 50 m from trunk_2 at (500, 0)
    site_far = _site("site_far", 500.0, -200.0)     # 200 m from trunk_2
    routes = generate_site_routes(
        [site_near, site_far], [_TRUNK_2], _policy(allowed_attachment_ids=["trunk_2"], maximum_paired_trench_length_m=300.0),
    )
    by_site = {r.site_id: r for r in routes}
    assert by_site["site_near"].screening_status == RouteScreeningStatus.ACCEPTED
    assert by_site["site_far"].screening_status == RouteScreeningStatus.ACCEPTED
    assert by_site["site_near"].paired_trench_length_m == pytest.approx(50.0)
    assert by_site["site_far"].paired_trench_length_m == pytest.approx(200.0)
    assert by_site["site_near"].paired_trench_length_m != by_site["site_far"].paired_trench_length_m


# ── ROUTE-008/009: screening, retained with exact reason codes ──────────────
def test_excluded_site_route_is_retained_as_site_unavailable():
    site = _site("site_A", 250.0, -60.0, availability_status=SiteAvailabilityStatus.EXCLUDED, exclusion_reason="protected")
    routes = generate_site_routes([site], [_TRUNK_1], _policy(allowed_attachment_ids=["trunk_1"]))
    assert len(routes) == 1
    assert routes[0].screening_status == RouteScreeningStatus.REJECTED
    assert routes[0].rejection_code == RouteRejectionCode.SITE_UNAVAILABLE


def test_route_exceeding_max_length_is_retained_as_length_exceeds_limit():
    site = _site("site_A", 250.0, -1000.0)  # 1000 m from trunk_1
    routes = generate_site_routes([site], [_TRUNK_1], _policy(allowed_attachment_ids=["trunk_1"], maximum_paired_trench_length_m=300.0))
    assert routes[0].screening_status == RouteScreeningStatus.REJECTED
    assert routes[0].rejection_code == RouteRejectionCode.LENGTH_EXCEEDS_LIMIT


def test_ineligible_attachment_is_rejected():
    site = _site("site_A", 250.0, -60.0)
    ineligible = _attachment("trunk_1", "trunk_1", eligibility_status=AttachmentEligibilityStatus.EXCLUDED, exclusion_reason="closed")
    routes = generate_site_routes([site], [ineligible], _policy(allowed_attachment_ids=["trunk_1"]))
    assert routes[0].screening_status == RouteScreeningStatus.REJECTED
    assert routes[0].rejection_code == RouteRejectionCode.ATTACHMENT_INELIGIBLE


def test_unknown_attachment_id_in_policy_is_rejected():
    site = _site("site_A", 250.0, -60.0)
    routes = generate_site_routes([site], [_TRUNK_1], _policy(allowed_attachment_ids=["trunk_99"]))
    assert routes[0].screening_status == RouteScreeningStatus.REJECTED
    assert routes[0].rejection_code == RouteRejectionCode.ATTACHMENT_INELIGIBLE


def test_unsupported_route_kind_is_rejected_not_silently_fallen_back():
    """ROUTE-010: never a silent straight-line fallback for an
    unimplemented route engine."""
    site = _site("site_A", 250.0, -60.0)
    policy = _policy(allowed_attachment_ids=["trunk_1"], route_kind=RouteKind.NETWORK_GRAPH)
    routes = generate_site_routes([site], [_TRUNK_1], policy)
    assert routes[0].screening_status == RouteScreeningStatus.REJECTED
    assert routes[0].rejection_code == RouteRejectionCode.ROUTE_KIND_UNSUPPORTED


def test_nothing_is_silently_dropped_every_combination_appears():
    """ROUTE-009: every (site, attachment) combination is retained,
    accepted or rejected -- never silently absent from the output."""
    sites = [_site("site_A", 250.0, -60.0), _site("site_B", 500.0, -9999.0)]
    routes = generate_site_routes(sites, [_TRUNK_1, _TRUNK_2], _policy())
    assert len(routes) == 4  # 2 sites x 2 attachments


# ── S7.14: exclusion polygon and detour ──────────────────────────────────────
def test_site_inside_an_exclusion_polygon_is_rejected():
    exclusion = ExclusionDefinition(
        exclusion_id="zone_1", geometry=[
            SyntheticCoordinate(x_m=200.0, y_m=-100.0), SyntheticCoordinate(x_m=300.0, y_m=-100.0),
            SyntheticCoordinate(x_m=300.0, y_m=-20.0), SyntheticCoordinate(x_m=200.0, y_m=-20.0),
        ],
        applies_to=ExclusionAppliesTo.SITES, reason="protected", assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="test",
    )
    site = _site("site_A", 250.0, -60.0)  # inside the polygon above
    policy = _policy(allowed_attachment_ids=["trunk_1"], exclusion_definitions=[exclusion])
    routes = generate_site_routes([site], [_TRUNK_1], policy)
    assert routes[0].screening_status == RouteScreeningStatus.REJECTED
    assert routes[0].rejection_code == RouteRejectionCode.EXCLUSION_CONFLICT


def test_detour_route_inserts_via_coordinates_and_lengthens_the_route():
    site = _site("site_A", 250.0, -60.0)
    direct_routes = generate_site_routes([site], [_TRUNK_1], _policy(allowed_attachment_ids=["trunk_1"]))
    direct_length = direct_routes[0].paired_trench_length_m

    detour = DetourDefinition(
        detour_id="d1", site_id="site_A", attachment_id="trunk_1",
        via_coordinates=[SyntheticCoordinate(x_m=100.0, y_m=-60.0)], reason="avoid a synthetic obstacle",
    )
    detoured_routes = generate_site_routes(
        [site], [_TRUNK_1],
        _policy(allowed_attachment_ids=["trunk_1"], detour_definitions=[detour], maximum_paired_trench_length_m=500.0),
    )
    assert len(detoured_routes[0].route_geometry) == 3
    assert detoured_routes[0].paired_trench_length_m > direct_length


# ── ROUTE-002/011: deterministic identity and ordering ───────────────────────
def test_route_id_is_deterministic_and_never_embeds_design_identity():
    site = _site("site_A", 250.0, -60.0)
    routes_1 = generate_site_routes([site], [_TRUNK_1], _policy(allowed_attachment_ids=["trunk_1"]))
    routes_2 = generate_site_routes([site], [_TRUNK_1], _policy(allowed_attachment_ids=["trunk_1"]))
    assert routes_1[0].route_id == routes_2[0].route_id
    assert "standard" not in routes_1[0].route_id  # no design identity embedded


def test_routes_are_returned_in_sorted_deterministic_order():
    sites = [_site("site_z", 250.0, -60.0), _site("site_a", 500.0, -60.0)]
    routes = generate_site_routes(sites, [_TRUNK_1, _TRUNK_2], _policy())
    ids = [r.route_id for r in routes]
    assert ids == sorted(ids)
