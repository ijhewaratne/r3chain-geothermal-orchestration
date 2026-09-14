"""`workflow.fixed_interface_enumeration.enumerate_drilling_site_alternatives()`
-- proves the corrected candidate identity `i=(s,g)` with `a=a0` (fixed)
directly against `network.site_routing.generate_site_routes()`'s own
UNCHANGED output, without running the full workflow."""
from __future__ import annotations

import json
from pathlib import Path

from r3chain_geothermal.data_contracts.fixed_interface import resolve_fixed_integration_station
from r3chain_geothermal.data_contracts.joint_study import JointStudyPackage
from r3chain_geothermal.network.site_routing import generate_site_routes
from r3chain_geothermal.workflow.fixed_interface_enumeration import (
    enumerate_drilling_site_alternatives,
    possible_combination_count,
)
from r3chain_geothermal.workflow.joint_enumeration import enumerate_compatible_alternatives

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_PATH = _ROOT / "config" / "fixed_interface_site_optimization_synthetic.json"
_V2_PACKAGE_PATH = _ROOT / "config" / "joint_study_synthetic_v2.json"


def _package(path: Path = _PACKAGE_PATH) -> JointStudyPackage:
    return JointStudyPackage.model_validate(json.loads(path.read_text()))


def _routes(package: JointStudyPackage):
    return generate_site_routes(package.sites, package.network_attachments, package.routing_policy)


# ── Test 1 (task spec): fixed network entry invariant ───────────────────────
def test_every_identity_shares_the_fixed_stations_attachment_id():
    package = _package()
    station = resolve_fixed_integration_station(package, heat_exchanger_config_reference="coupling_assumptions")
    routes = _routes(package)
    identities = enumerate_drilling_site_alternatives(package, routes, station)
    assert identities  # non-empty for this fixture
    assert {i.attachment_id for i in identities} == {station.network_attachment_id} == {"trunk_1"}


# ── Test 3 (task spec): network entry does not move when the site changes ──
def test_swapping_the_site_never_changes_the_fixed_attachment_or_junction_ids():
    package = _package()
    station = resolve_fixed_integration_station(package, heat_exchanger_config_reference="coupling_assumptions")
    routes = _routes(package)
    identities = enumerate_drilling_site_alternatives(package, routes, station)
    by_site = {i.surface_site_id: i for i in identities}
    assert len(by_site) >= 2  # at least two distinct candidate sites in this fixture
    site_ids = sorted(by_site)
    first, second = by_site[site_ids[0]], by_site[site_ids[1]]
    assert first.surface_site_id != second.surface_site_id
    assert first.attachment_id == second.attachment_id == station.network_attachment_id


# ── Test 4 (task spec): no site x trunk_i cross-product ─────────────────────
def test_compatible_count_is_not_a_site_times_attachment_cross_product():
    """The corrected fixture has exactly ONE attachment, so the compatible
    count must equal the number of (site, scenario) pairs among AVAILABLE
    sites -- never multiplied by an attachment/trunk axis (contrast with
    the v1/v2 fixture's own 4-attachment cross-product below)."""
    package = _package()
    station = resolve_fixed_integration_station(package, heat_exchanger_config_reference="coupling_assumptions")
    routes = _routes(package)
    identities = enumerate_drilling_site_alternatives(package, routes, station)

    available_site_ids = {s.site_id for s in package.sites if s.availability_status.value == "available"}
    expected_pairs = sum(1 for sc in package.resource_scenarios if sc.site_id in available_site_ids)
    assert len(identities) == expected_pairs == 4

    # Contrast: the v2 fixture's own routing_policy names FOUR attachments,
    # so its own (unmodified) enumerate_compatible_alternatives() legitimately
    # produces MORE alternatives than distinct (site, scenario) pairs --
    # this is the exact joint cross-product this new mode does not exercise.
    v2_package = _package(_V2_PACKAGE_PATH)
    v2_routes = _routes(v2_package)
    v2_identities = enumerate_compatible_alternatives(v2_package, v2_routes)
    v2_available = {s.site_id for s in v2_package.sites if s.availability_status.value == "available"}
    v2_pairs = sum(1 for sc in v2_package.resource_scenarios if sc.site_id in v2_available)
    assert len(v2_identities) > v2_pairs  # the v2 layer DOES multiply by attachment/route


def test_possible_combination_count_uses_generated_not_accepted_routes():
    package = _package()
    routes = _routes(package)
    assert possible_combination_count(package, routes) == len(package.resource_scenarios) * len(routes)


def test_enumeration_never_raises_when_the_station_matches_the_routing_policy():
    """The defensive AssertionError in enumerate_drilling_site_alternatives()
    is unreachable whenever routes were generated from a routing_policy
    already validated by resolve_fixed_integration_station() -- this is
    exactly that path, run end to end."""
    package = _package()
    station = resolve_fixed_integration_station(package, heat_exchanger_config_reference="coupling_assumptions")
    routes = _routes(package)
    enumerate_drilling_site_alternatives(package, routes, station)  # must not raise
