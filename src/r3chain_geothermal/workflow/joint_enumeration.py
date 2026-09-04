"""Compatible alternative enumeration (S12, WF-004..006,
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 2).

## What this replaces

`workflow/joint_optimization.py`'s v1 curated/full-product functions pair
EVERY synthetic scenario against EVERY accepted candidate -- an
unconstrained scenario x candidate product, since v1 scenarios carry no
`site_id` a candidate could be filtered against. This module enumerates
only COMPATIBLE tuples: a scenario is only ever paired with routes that
belong to ITS OWN site (S1.2's own feasible-search-set definition,
`g.site=s`), never a global cross-product. `workflow/joint_optimization.py`
is not modified."""
from __future__ import annotations

from ..data_contracts.joint_study import (
    AlternativeIdentity,
    JointStudyPackage,
    RouteScreeningStatus,
    SiteAvailabilityStatus,
    SiteConnectionRoute,
)


def enumerate_compatible_alternatives(
    package: JointStudyPackage, routes: list[SiteConnectionRoute],
) -> list[AlternativeIdentity]:
    """S1.2: X = {(s,g,a,r,d,o) | g.site=s, r.site=s, r.attachment=a, ...}.
    Only ACCEPTED routes belonging to an AVAILABLE site are combined with
    that SAME site's own resource scenarios -- design and operating-
    policy dimensions are combined freely (S7's own contract has no
    per-route/per-scenario design or policy restriction to honour in
    this synthetic demonstration), but site<->scenario and site<->route
    are never decoupled. Deterministic order (WF-007): sorted by
    site_id, then scenario_id, then route_id, then design_option_id,
    then operating_policy_id."""
    available_site_ids = {s.site_id for s in package.sites if s.availability_status == SiteAvailabilityStatus.AVAILABLE}

    scenarios_by_site: dict[str, list[str]] = {}
    for scenario in package.resource_scenarios:
        scenarios_by_site.setdefault(scenario.site_id, []).append(scenario.scenario_id)

    routes_by_site: dict[str, list[SiteConnectionRoute]] = {}
    for route in routes:
        if route.screening_status == RouteScreeningStatus.ACCEPTED:
            routes_by_site.setdefault(route.site_id, []).append(route)

    identities: list[AlternativeIdentity] = []
    for site_id in sorted(available_site_ids):
        scenario_ids = sorted(scenarios_by_site.get(site_id, []))
        site_routes = sorted(routes_by_site.get(site_id, []), key=lambda r: r.route_id)
        if not scenario_ids or not site_routes:
            continue
        for scenario_id in scenario_ids:
            for route in site_routes:
                for design in sorted(package.design_options, key=lambda d: d.design_option_id):
                    for policy in sorted(package.operating_policies, key=lambda p: p.operating_policy_id):
                        identities.append(AlternativeIdentity(
                            resource_scenario_id=scenario_id, surface_site_id=site_id,
                            attachment_id=route.attachment_id, route_id=route.route_id,
                            design_option_id=design.design_option_id, operating_policy_id=policy.operating_policy_id,
                        ))
    return identities


def possible_combination_count(package: JointStudyPackage, routes: list[SiteConnectionRoute]) -> int:
    """WF-005: the unconstrained scenario x route x design x policy
    product size (across ALL sites, ALL routes regardless of
    screening/availability) -- reported alongside the compatible and
    evaluated counts so a reader can see exactly how much the
    compatibility constraint actually excluded, not just the final
    number (S1.2's own "not an unconstrained Cartesian product")."""
    return len(package.resource_scenarios) * len(routes) * len(package.design_options) * len(package.operating_policies)
