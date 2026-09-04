"""Site-origin-aware connection-route generation (S9, ROUTE-001..012,
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 2).

## What this replaces

The v1 joint layer (`workflow/joint_optimization.py`) and the v1 generated-
candidate mechanism (`network/candidate_generation.py`) both compute a
connection length from ONE GLOBAL table (`network/geometry.py`'s own
`CANDIDATE_SITE_COORDINATES`/`CONSUMER_DECLARED_BASE_DISTANCE_M`) shared by
every scenario -- the exact issue S2.5 item 4 names ("every scenario/site is
combined with the same global network routes; route origin is not bound to
the site"). This module computes route length from the ACTUAL geometry
between a specific `SurfaceSite`'s own coordinate and a specific
`NetworkAttachment`'s real position, per site, per attachment -- ROUTE-005:
"do not reuse C1-C4 global distances for all sites." Neither v1 module is
modified; this is purely additive (ARCH-003).

## Where an attachment's own coordinate comes from

S7.8's `NetworkAttachment` contract has no coordinate field of its own
(it names `supply_junction_id`/`return_junction_id`, not a position) --
deliberately not amended here to add one, since this synthetic network
already has exactly one authoritative geometry source
(`network/geometry.py`'s own module docstring: "the SAME geometry
source"). `_attachment_coordinate()` below resolves an attachment's
position by looking its `supply_junction_id` up in that EXISTING table
(`TRUNK_JUNCTION_COORDINATES`/`CONSUMER_JUNCTION_COORDINATES`) rather
than introducing a second, competing geometry table. A real (non-
synthetic) network would need its own `NetworkReference`-carried
position data -- out of scope, real-mode-gated, not attempted here.

## Scope of this Phase-2 implementation

Only `route_kind="synthetic_polyline"` is implemented (S9's own formula:
sum of consecutive Euclidean distances). `network_graph` and
`external_gis` are declared in `RouteKind` (data_contracts.joint_study)
but return a typed `ROUTE_KIND_UNSUPPORTED` rejection here, never a
silent straight-line fallback (ROUTE-010). Exclusion-polygon conflicts
(S7.14) are checked by SITE-endpoint containment only (a full route-
segment/polygon intersection test is not implemented) -- stated as a
limitation, not silently claimed as complete."""
from __future__ import annotations

from .geometry import CONSUMER_JUNCTION_COORDINATES, TRUNK_JUNCTION_COORDINATES
from ..data_contracts.joint_study import (
    Coordinate,
    DetourDefinition,
    NetworkAttachment,
    RouteKind,
    RouteRejectionCode,
    RouteScreeningStatus,
    RoutingPolicy,
    SiteAvailabilityStatus,
    SiteConnectionRoute,
    SurfaceSite,
    SyntheticCoordinate,
    compute_polyline_length_m,
)


def _route_id(site_id: str, attachment_id: str, route_kind: RouteKind) -> str:
    """ROUTE-002: derived from site_id, attachment_id, and route-kind
    inputs only -- never design identity, never iteration order."""
    return f"route-{site_id}-{attachment_id}-{route_kind.value}"


def _attachment_coordinate(attachment: NetworkAttachment) -> SyntheticCoordinate | None:
    """Resolves an attachment's position from the existing synthetic-
    network geometry tables by its own supply_junction_id -- returns
    None (never a guessed/fabricated position) if the junction id is
    not one this synthetic network's geometry module actually knows."""
    coordinate = (
        TRUNK_JUNCTION_COORDINATES.get(attachment.supply_junction_id)
        or CONSUMER_JUNCTION_COORDINATES.get(attachment.supply_junction_id)
    )
    if coordinate is None:
        return None
    return SyntheticCoordinate(x_m=coordinate.x_m, y_m=coordinate.y_m)


def _rejected_route(
    route_id: str, site: SurfaceSite, attachment_id: str, route_kind: RouteKind,
    code: RouteRejectionCode, detail: str, geometry: list[Coordinate] | None = None,
) -> SiteConnectionRoute:
    return SiteConnectionRoute(
        route_id=route_id, site_id=site.site_id, attachment_id=attachment_id, route_kind=route_kind,
        route_geometry=geometry or [site.coordinate, site.coordinate],
        paired_trench_length_m=0.0, supply_pipe_length_m=0.0, return_pipe_length_m=0.0,
        screening_status=RouteScreeningStatus.REJECTED, rejection_code=code, rejection_detail=detail,
    )


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Standard ray-casting point-in-polygon test."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            inside = not inside
    return inside


def _exclusion_conflict(site: SurfaceSite, policy: RoutingPolicy) -> str | None:
    if not isinstance(site.coordinate, SyntheticCoordinate):
        return None
    for exclusion in policy.exclusion_definitions:
        if exclusion.applies_to.value not in ("sites", "both"):
            continue
        if not all(isinstance(c, SyntheticCoordinate) for c in exclusion.geometry):
            continue
        polygon = [(c.x_m, c.y_m) for c in exclusion.geometry]  # type: ignore[union-attr]
        if _point_in_polygon((site.coordinate.x_m, site.coordinate.y_m), polygon):
            return exclusion.exclusion_id
    return None


def _matching_detour(site_id: str, attachment_id: str, policy: RoutingPolicy) -> DetourDefinition | None:
    return next(
        (d for d in policy.detour_definitions if d.site_id == site_id and d.attachment_id == attachment_id),
        None,
    )


def generate_site_routes(
    sites: list[SurfaceSite], attachments: list[NetworkAttachment], routing_policy: RoutingPolicy,
) -> list[SiteConnectionRoute]:
    """ROUTE-001: generate routes SEPARATELY for each site and each
    eligible attachment named in `routing_policy.allowed_attachment_ids`
    -- an explicit allow-list (ROUTE-008), never every attachment in the
    network implicitly. ROUTE-009: every screened-out combination is
    RETAINED with an exact `RouteRejectionCode`, never dropped. ROUTE-011:
    deterministic order (sorted by route_id)."""
    attachments_by_id = {a.attachment_id: a for a in attachments}
    routes: list[SiteConnectionRoute] = []

    for site in sorted(sites, key=lambda s: s.site_id):
        for attachment_id in sorted(routing_policy.allowed_attachment_ids):
            route_id = _route_id(site.site_id, attachment_id, routing_policy.route_kind)
            attachment = attachments_by_id.get(attachment_id)

            if attachment is None:
                routes.append(_rejected_route(
                    route_id, site, attachment_id, routing_policy.route_kind,
                    RouteRejectionCode.ATTACHMENT_INELIGIBLE,
                    f"attachment_id {attachment_id!r} is not a known NetworkAttachment",
                ))
                continue
            if site.availability_status != SiteAvailabilityStatus.AVAILABLE:
                routes.append(_rejected_route(
                    route_id, site, attachment_id, routing_policy.route_kind,
                    RouteRejectionCode.SITE_UNAVAILABLE,
                    f"site {site.site_id!r} availability_status={site.availability_status.value!r}",
                ))
                continue
            if attachment.eligibility_status.value != "eligible":
                routes.append(_rejected_route(
                    route_id, site, attachment_id, routing_policy.route_kind,
                    RouteRejectionCode.ATTACHMENT_INELIGIBLE,
                    f"attachment {attachment_id!r} eligibility_status={attachment.eligibility_status.value!r}",
                ))
                continue
            if routing_policy.route_kind != RouteKind.SYNTHETIC_POLYLINE:
                routes.append(_rejected_route(
                    route_id, site, attachment_id, routing_policy.route_kind,
                    RouteRejectionCode.ROUTE_KIND_UNSUPPORTED,
                    f"route_kind={routing_policy.route_kind.value!r} is not implemented (ROUTE-010)",
                ))
                continue

            attachment_coordinate = _attachment_coordinate(attachment)
            if attachment_coordinate is None:
                routes.append(_rejected_route(
                    route_id, site, attachment_id, routing_policy.route_kind,
                    RouteRejectionCode.GEOMETRY_INVALID,
                    f"attachment {attachment_id!r} supply_junction_id {attachment.supply_junction_id!r} "
                    "has no known position in this synthetic network's geometry",
                ))
                continue

            exclusion_id = _exclusion_conflict(site, routing_policy)
            if exclusion_id is not None:
                routes.append(_rejected_route(
                    route_id, site, attachment_id, routing_policy.route_kind,
                    RouteRejectionCode.EXCLUSION_CONFLICT,
                    f"site {site.site_id!r} falls inside exclusion {exclusion_id!r}",
                    geometry=[site.coordinate, attachment_coordinate],
                ))
                continue

            # ROUTE-003/004: geometry starts at the site, terminates at the
            # attachment; a matching DetourDefinition inserts its
            # via_coordinates between them (S7.14).
            detour = _matching_detour(site.site_id, attachment_id, routing_policy)
            geometry: list[Coordinate] = [site.coordinate]
            if detour is not None:
                geometry.extend(detour.via_coordinates)
            geometry.append(attachment_coordinate)

            length_m = compute_polyline_length_m(geometry)
            if length_m > routing_policy.maximum_paired_trench_length_m:
                routes.append(_rejected_route(
                    route_id, site, attachment_id, routing_policy.route_kind,
                    RouteRejectionCode.LENGTH_EXCEEDS_LIMIT,
                    f"geometry-derived length {length_m:.3f} m exceeds "
                    f"maximum_paired_trench_length_m={routing_policy.maximum_paired_trench_length_m!r}",
                    geometry=geometry,
                ))
                continue

            routes.append(SiteConnectionRoute(
                route_id=route_id, site_id=site.site_id, attachment_id=attachment_id,
                route_kind=routing_policy.route_kind, route_geometry=geometry,
                paired_trench_length_m=length_m, supply_pipe_length_m=length_m, return_pipe_length_m=length_m,
                screening_status=RouteScreeningStatus.ACCEPTED,
            ))

    return sorted(routes, key=lambda r: r.route_id)
