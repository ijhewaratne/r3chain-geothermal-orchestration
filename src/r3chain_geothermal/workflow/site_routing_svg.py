"""Deterministic `network_candidates.svg` rendering for the corrected joint
site/connection layer (v2) --
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
§17 (Phase 9: this file was added after Phase 5's own initial deferral of
this artifact was withdrawn).

Mirrors `workflow/svg_export.py`'s own established conventions exactly:
pure string templating (no matplotlib/folium/external renderer dependency
-- byte-identical output across machines), status communicated by BOTH a
distinct marker shape AND a text label (never colour alone), and the
EXACT required "Synthetic schematic" wording appearing verbatim.

Coordinates come from ONE already-established source of truth per
element: `SurfaceSite.coordinate` (a `SyntheticCoordinate`, the same
synthetic Cartesian system `JointStudyPackage.coordinate_reference`
itself declares) for every site marker, and
`network.site_routing._attachment_coordinate()` (the SAME function
`generate_site_routes()` itself already used to build every route's own
first/last geometry point) for every attachment marker -- never a newly
invented coordinate lookup.

This diagram is deliberately schematic, not a geographic/GIS map: it
represents the synthetic sites, attachments, and routes exactly as this
prototype's own invented Cartesian coordinates place them, and must never
be read as implying real-world geographic accuracy -- the same synthetic
disclaimer every other joint-workflow artifact already carries."""
from __future__ import annotations

import html

from ..data_contracts.joint_study import (
    JointStudyPackage,
    RouteScreeningStatus,
    SiteAvailabilityStatus,
    SiteConnectionRoute,
    SyntheticCoordinate,
)
from ..network.site_routing import _attachment_coordinate

SCHEMATIC_LABEL = "Synthetic schematic — not geographical"
"""Exact required wording (em dash, U+2014), matching svg_export.py's own
established convention -- must appear verbatim, prominently, in every
rendered SVG."""

_SCALE_PX_PER_M = 0.5
_MARGIN_X = 90
_MARGIN_Y = 70
_LEGEND_HEIGHT = 90
_LIST_ROW_HEIGHT = 16

_SITE_AVAILABLE_COLOR = "#1a7a3c"
_SITE_EXCLUDED_COLOR = "#666666"
_ATTACHMENT_COLOR = "#1b4f8c"
_ROUTE_ACCEPTED_COLOR = "#1b4f8c"
_ROUTE_REJECTED_COLOR = "#a31515"
_TEXT_COLOR = "#111111"


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_network_candidates_svg(
    package: JointStudyPackage, routes: list[SiteConnectionRoute], compatible_alternative_ids: frozenset[str],
) -> bytes:
    sites = sorted(package.sites, key=lambda s: s.site_id)
    attachments = sorted(package.network_attachments, key=lambda a: a.attachment_id)
    sorted_routes = sorted(routes, key=lambda r: r.route_id)

    site_coords: dict[str, SyntheticCoordinate] = {}
    for site in sites:
        if not isinstance(site.coordinate, SyntheticCoordinate):
            raise ValueError(
                f"site {site.site_id!r} does not use a SyntheticCoordinate -- this renderer is for "
                "synthetic packages only (a real package must never reach this diagram unlabelled)"
            )
        site_coords[site.site_id] = site.coordinate

    attachment_coords: dict[str, SyntheticCoordinate] = {}
    for attachment in attachments:
        coord = _attachment_coordinate(attachment)
        if coord is not None:
            attachment_coords[attachment.attachment_id] = coord

    all_x = [c.x_m for c in site_coords.values()] + [c.x_m for c in attachment_coords.values()]
    all_y = [c.y_m for c in site_coords.values()] + [c.y_m for c in attachment_coords.values()]
    if not all_x:
        all_x, all_y = [0.0], [0.0]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    width_px = _MARGIN_X * 2 + max(1.0, (max_x - min_x)) * _SCALE_PX_PER_M
    height_px = _MARGIN_Y * 2 + max(1.0, (max_y - min_y)) * _SCALE_PX_PER_M
    list_rows = len(sites) + len(attachments) + len(sorted_routes) + 3  # +3 section headers
    total_height_px = height_px + _LEGEND_HEIGHT + list_rows * _LIST_ROW_HEIGHT + 40

    def _xy(coord: SyntheticCoordinate) -> tuple[float, float]:
        return (_MARGIN_X + (coord.x_m - min_x) * _SCALE_PX_PER_M, _MARGIN_Y + (coord.y_m - min_y) * _SCALE_PX_PER_M)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_px:.1f} {total_height_px:.1f}" '
        f'font-family="sans-serif" font-size="11">'
    )
    parts.append(f'<rect x="0" y="0" width="{width_px:.1f}" height="{total_height_px:.1f}" fill="#ffffff"/>')
    parts.append(
        f'<text x="{width_px / 2:.1f}" y="24" text-anchor="middle" font-size="16" font-weight="bold" '
        f'fill="{_TEXT_COLOR}">Joint site/connection candidates (v2)</text>'
    )
    parts.append(
        f'<text x="{width_px / 2:.1f}" y="42" text-anchor="middle" font-size="13" font-weight="bold" '
        f'fill="#a31515">{_esc(SCHEMATIC_LABEL)}</text>'
    )
    parts.append(
        f'<text x="{width_px / 2:.1f}" y="58" text-anchor="middle" font-size="10" fill="{_TEXT_COLOR}">'
        "Every site, attachment and route below is invented for this synthetic demonstration -- "
        "never a real geological drilling-site or network-connection recommendation.</text>"
    )

    y_origin = _MARGIN_Y + 60

    # ── routes (drawn first, so site/attachment markers sit on top) ──
    for route in sorted_routes:
        site_coord = site_coords.get(route.site_id)
        attachment_coord = attachment_coords.get(route.attachment_id)
        if site_coord is None or attachment_coord is None:
            continue
        x1, y1 = _xy(site_coord)
        x2, y2 = _xy(attachment_coord)
        accepted = route.screening_status == RouteScreeningStatus.ACCEPTED
        color = _ROUTE_ACCEPTED_COLOR if accepted else _ROUTE_REJECTED_COLOR
        dash = "" if accepted else ' stroke-dasharray="4,3"'
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1 + 60:.1f}" x2="{x2:.1f}" y2="{y2 + 60:.1f}" '
            f'stroke="{color}" stroke-width="1.5"{dash}/>'
        )

    # ── surface sites ──
    for site in sites:
        coord = site_coords[site.site_id]
        x, y = _xy(coord)
        y += 60
        available = site.availability_status == SiteAvailabilityStatus.AVAILABLE
        color = _SITE_AVAILABLE_COLOR if available else _SITE_EXCLUDED_COLOR
        fill = color if available else "none"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{fill}" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<text x="{x + 10:.1f}" y="{y + 4:.1f}" fill="{_TEXT_COLOR}">{_esc(site.site_id)}</text>')

    # ── network attachments ──
    for attachment in attachments:
        coord = attachment_coords.get(attachment.attachment_id)
        if coord is None:
            continue
        x, y = _xy(coord)
        y += 60
        parts.append(
            f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" fill="{_ATTACHMENT_COLOR}" '
            f'stroke="{_ATTACHMENT_COLOR}"/>'
        )
        parts.append(f'<text x="{x + 10:.1f}" y="{y + 4:.1f}" fill="{_TEXT_COLOR}">{_esc(attachment.attachment_id)}</text>')

    # ── legend ──
    legend_y = height_px + 20
    parts.append(f'<circle cx="{_MARGIN_X:.1f}" cy="{legend_y:.1f}" r="7" fill="{_SITE_AVAILABLE_COLOR}"/>')
    parts.append(f'<text x="{_MARGIN_X + 14:.1f}" y="{legend_y + 4:.1f}" fill="{_TEXT_COLOR}">Available surface site</text>')
    parts.append(f'<circle cx="{_MARGIN_X + 220:.1f}" cy="{legend_y:.1f}" r="7" fill="none" stroke="{_SITE_EXCLUDED_COLOR}" stroke-width="2"/>')
    parts.append(f'<text x="{_MARGIN_X + 234:.1f}" y="{legend_y + 4:.1f}" fill="{_TEXT_COLOR}">Excluded surface site</text>')
    parts.append(f'<rect x="{_MARGIN_X + 440 - 6:.1f}" y="{legend_y - 6:.1f}" width="12" height="12" fill="{_ATTACHMENT_COLOR}"/>')
    parts.append(f'<text x="{_MARGIN_X + 460:.1f}" y="{legend_y + 4:.1f}" fill="{_TEXT_COLOR}">Network attachment</text>')
    legend_y2 = legend_y + 22
    parts.append(f'<line x1="{_MARGIN_X:.1f}" y1="{legend_y2:.1f}" x2="{_MARGIN_X + 30:.1f}" y2="{legend_y2:.1f}" stroke="{_ROUTE_ACCEPTED_COLOR}" stroke-width="1.5"/>')
    parts.append(f'<text x="{_MARGIN_X + 36:.1f}" y="{legend_y2 + 4:.1f}" fill="{_TEXT_COLOR}">Accepted route</text>')
    parts.append(f'<line x1="{_MARGIN_X + 220:.1f}" y1="{legend_y2:.1f}" x2="{_MARGIN_X + 250:.1f}" y2="{legend_y2:.1f}" stroke="{_ROUTE_REJECTED_COLOR}" stroke-width="1.5" stroke-dasharray="4,3"/>')
    parts.append(f'<text x="{_MARGIN_X + 256:.1f}" y="{legend_y2 + 4:.1f}" fill="{_TEXT_COLOR}">Rejected route</text>')

    # ── summary lists ──
    list_y = legend_y2 + 30
    parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" font-weight="bold" fill="{_TEXT_COLOR}">Sites</text>')
    list_y += _LIST_ROW_HEIGHT
    for site in sites:
        status = "available" if site.availability_status == SiteAvailabilityStatus.AVAILABLE else f"excluded: {site.exclusion_reason or ''}"
        parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" fill="{_TEXT_COLOR}">{_esc(site.site_id)} -- {_esc(status)}</text>')
        list_y += _LIST_ROW_HEIGHT

    parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" font-weight="bold" fill="{_TEXT_COLOR}">Attachments</text>')
    list_y += _LIST_ROW_HEIGHT
    for attachment in attachments:
        parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" fill="{_TEXT_COLOR}">{_esc(attachment.attachment_id)}</text>')
        list_y += _LIST_ROW_HEIGHT

    parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" font-weight="bold" fill="{_TEXT_COLOR}">Routes</text>')
    list_y += _LIST_ROW_HEIGHT
    for route in sorted_routes:
        status = route.screening_status.value
        length = f"{route.paired_trench_length_m:.1f} m" if route.paired_trench_length_m is not None else ""
        parts.append(
            f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" fill="{_TEXT_COLOR}">{_esc(route.route_id)} '
            f"({_esc(route.site_id)} -&gt; {_esc(route.attachment_id)}): {_esc(status)} {_esc(length)}</text>"
        )
        list_y += _LIST_ROW_HEIGHT

    parts.append("</svg>")
    return ("\n".join(parts) + "\n").encode("utf-8")
