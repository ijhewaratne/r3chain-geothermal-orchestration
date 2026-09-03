"""Deterministic `network_candidates.svg` rendering (T2.4B2).

Pure string templating -- no matplotlib/folium/external renderer
dependency (byte-identical output across machines, no rasterization
non-determinism). Coordinates come from TWO already-established, single
sources of truth: `result.blueprint.junctions[...].x_m/.y_m` (the SAME
coordinates the actual solved pandapipes network was built from --
network/builder.py) for every real junction, and
`network.geometry.CANDIDATE_SITE_COORDINATES` (T2.2A's own "map,
connection pipes and economics must all consume the SAME length" source)
for the four candidate MARKER positions, which have no corresponding
pandapipes junction of their own.

Status is communicated by BOTH a distinct marker shape/symbol AND a full
text label -- never by colour alone (a filled circle for a feasible
candidate, an X-marked hollow square for infeasible; the label text
always states "feasible"/"infeasible: <code>" explicitly).
"""
from __future__ import annotations

import html

from ..network import CandidateEvaluationFailure, CandidateEvaluationResult
from ..network.geometry import CANDIDATE_SITE_COORDINATES, Coordinate, ret_coordinate
from .core import WorkflowResult

SCHEMATIC_LABEL = "Synthetic schematic — not geographical"
"""Exact required wording (em dash, U+2014) -- must appear verbatim,
prominently, in every rendered SVG."""

_SCALE_PX_PER_M = 0.5
_MARGIN_X = 90
_MARGIN_Y = 70
_LEGEND_HEIGHT = 70
_LIST_ROW_HEIGHT = 16
"""Inline marker labels are kept to short IDs only (see the rendering
loops below) precisely so neighbouring markers -- spaced by the fixed
250 m candidate/consumer geometry, `network/geometry.py` -- never collide
regardless of scale; the full descriptive text (demand, feasibility,
rank, paired-trench length, LCOH) lives exclusively in the
vertically-stacked summary lists at the bottom, which cannot collide
horizontally with each other by construction."""

_SUPPLY_COLOR = "#1b4f8c"
_RETURN_COLOR = "#b3541e"
_FEASIBLE_COLOR = "#1a7a3c"
_INFEASIBLE_COLOR = "#a31515"
_CONSUMER_COLOR = "#333333"
_TEXT_COLOR = "#111111"


def _svg_xy(x_m: float, y_m: float, y_origin_px: float) -> tuple[float, float]:
    return _MARGIN_X + x_m * _SCALE_PX_PER_M, y_origin_px - y_m * _SCALE_PX_PER_M


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_network_candidates_svg(result: WorkflowResult) -> bytes:
    """Renders the SVG's exact bytes -- deterministic: driven entirely by
    already-computed, deterministic typed data (blueprint coordinates,
    candidate results, ranking), no randomness, no wall-clock content, no
    created_at anywhere in this file (byte_sha256 == scientific_sha256
    for it, artifacts.py's own convention)."""
    blueprint = result.blueprint
    junctions_by_id = blueprint.junctions

    all_y = [j.y_m for j in junctions_by_id.values()] + [c.y_m for c in CANDIDATE_SITE_COORDINATES.values()]
    all_x = [j.x_m for j in junctions_by_id.values()] + [c.x_m for c in CANDIDATE_SITE_COORDINATES.values()]
    max_y_m, min_y_m = max(all_y), min(all_y)
    max_x_m = max(all_x)

    y_origin_px = _MARGIN_Y + max_y_m * _SCALE_PX_PER_M
    width_px = _MARGIN_X * 2 + max_x_m * _SCALE_PX_PER_M + 260  # extra room for summary list text
    height_px = (
        _MARGIN_Y * 2 + (max_y_m - min_y_m) * _SCALE_PX_PER_M + _LEGEND_HEIGHT
        + _LIST_ROW_HEIGHT * (len(blueprint.candidates) + len(blueprint.consumers) + 2)  # +2 for the two list titles
        + 8  # gap between the Consumers and Candidates list blocks
    )

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_px:.1f} {height_px:.1f}" '
        f'font-family="monospace" font-size="12">'
    )
    parts.append(f'<rect x="0" y="0" width="{width_px:.1f}" height="{height_px:.1f}" fill="#ffffff"/>')

    # ── Title / mandatory disclaimer ──
    parts.append(
        f'<text x="{_MARGIN_X:.1f}" y="24" font-size="16" font-weight="bold" fill="{_TEXT_COLOR}">'
        f'{_esc(SCHEMATIC_LABEL)}</text>'
    )

    # ── Supply trunk (solid) ──
    trunk_ids = sorted((jid for jid, j in junctions_by_id.items() if j.kind == "trunk" and j.side == "supply"), key=lambda jid: junctions_by_id[jid].x_m)
    for a, b in zip(trunk_ids, trunk_ids[1:]):
        xa, ya = _svg_xy(junctions_by_id[a].x_m, junctions_by_id[a].y_m, y_origin_px)
        xb, yb = _svg_xy(junctions_by_id[b].x_m, junctions_by_id[b].y_m, y_origin_px)
        parts.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" stroke="{_SUPPLY_COLOR}" stroke-width="3"/>')

    # ── Return trunk (dashed) ──
    return_trunk_ids = sorted((jid for jid, j in junctions_by_id.items() if j.kind == "trunk" and j.side == "return"), key=lambda jid: junctions_by_id[jid].x_m)
    for a, b in zip(return_trunk_ids, return_trunk_ids[1:]):
        xa, ya = _svg_xy(junctions_by_id[a].x_m, junctions_by_id[a].y_m, y_origin_px)
        xb, yb = _svg_xy(junctions_by_id[b].x_m, junctions_by_id[b].y_m, y_origin_px)
        parts.append(
            f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" '
            f'stroke="{_RETURN_COLOR}" stroke-width="3" stroke-dasharray="8,5"/>'
        )

    # ── Consumers: supply + return branch lines, one marker + short ID label each
    #    (full demand figure lives in the "Consumers" summary list below --
    #    inline labels are kept short so neighbouring 250 m-spaced markers
    #    never collide, see _SCALE_PX_PER_M's docstring) ──
    for index, consumer_id in enumerate(sorted(blueprint.consumers)):
        consumer = blueprint.consumers[consumer_id]
        supply_j = junctions_by_id[consumer.supply_junction]
        return_j = junctions_by_id[consumer.return_junction]
        trunk_supply_j = next(j for jid, j in junctions_by_id.items() if j.kind == "trunk" and j.side == "supply" and abs(j.x_m - supply_j.x_m) < 1e-6)
        trunk_return_j = next(j for jid, j in junctions_by_id.items() if j.kind == "trunk" and j.side == "return" and abs(j.x_m - return_j.x_m) < 1e-6)

        xs, ys = _svg_xy(supply_j.x_m, supply_j.y_m, y_origin_px)
        xts, yts = _svg_xy(trunk_supply_j.x_m, trunk_supply_j.y_m, y_origin_px)
        parts.append(f'<line x1="{xs:.1f}" y1="{ys:.1f}" x2="{xts:.1f}" y2="{yts:.1f}" stroke="{_SUPPLY_COLOR}" stroke-width="1.5"/>')

        xr, yr = _svg_xy(return_j.x_m, return_j.y_m, y_origin_px)
        xtr, ytr = _svg_xy(trunk_return_j.x_m, trunk_return_j.y_m, y_origin_px)
        parts.append(
            f'<line x1="{xr:.1f}" y1="{yr:.1f}" x2="{xtr:.1f}" y2="{ytr:.1f}" '
            f'stroke="{_RETURN_COLOR}" stroke-width="1.5" stroke-dasharray="6,4"/>'
        )

        label_y_offset = -10 if index % 2 == 0 else -22
        parts.append(f'<circle cx="{xs:.1f}" cy="{ys:.1f}" r="5" fill="{_CONSUMER_COLOR}"/>')
        parts.append(
            f'<text x="{xs:.1f}" y="{ys + label_y_offset:.1f}" text-anchor="middle" fill="{_TEXT_COLOR}">'
            f'{_esc(consumer_id)}</text>'
        )

    # ── Candidates: marker (shape encodes feasibility, not colour alone) + short
    #    ID label + connection line. Full status/rank/length/LCOH lives in the
    #    "Candidates" summary list below (see _SCALE_PX_PER_M's docstring). ──
    ranked_by_id = {entry.candidate_id: entry for entry in result.ranking.ranked}
    for candidate_id in sorted(blueprint.candidates):
        candidate = blueprint.candidates[candidate_id]
        candidate_result = result.candidate_results[candidate_id]
        trunk_j = junctions_by_id[candidate.supply_junction]
        site = CANDIDATE_SITE_COORDINATES.get(candidate_id)
        if site is None:
            # FAIL-001 (workshop/negative-demo candidates, e.g. C5_negative):
            # not part of the mapped C1-C4 site set in geometry.py -- render
            # its marker at a small fixed offset from its own trunk junction
            # rather than crashing. A presentation-layer fallback only,
            # never a scientific value.
            site = Coordinate(x_m=trunk_j.x_m + 15.0, y_m=trunk_j.y_m - 15.0)

        xc, yc = _svg_xy(site.x_m, site.y_m, y_origin_px)
        xt, yt = _svg_xy(trunk_j.x_m, trunk_j.y_m, y_origin_px)
        parts.append(f'<line x1="{xc:.1f}" y1="{yc:.1f}" x2="{xt:.1f}" y2="{yt:.1f}" stroke="#888888" stroke-width="1.5" stroke-dasharray="2,3"/>')

        is_feasible = isinstance(candidate_result, CandidateEvaluationResult)
        marker_color = _FEASIBLE_COLOR if is_feasible else _INFEASIBLE_COLOR
        if is_feasible:
            parts.append(f'<circle cx="{xc:.1f}" cy="{yc:.1f}" r="7" fill="{marker_color}"/>')
        else:
            assert isinstance(candidate_result, CandidateEvaluationFailure)
            parts.append(
                f'<rect x="{xc - 6:.1f}" y="{yc - 6:.1f}" width="12" height="12" '
                f'fill="none" stroke="{marker_color}" stroke-width="2"/>'
            )
            parts.append(
                f'<line x1="{xc - 6:.1f}" y1="{yc - 6:.1f}" x2="{xc + 6:.1f}" y2="{yc + 6:.1f}" stroke="{marker_color}" stroke-width="2"/>'
            )
            parts.append(
                f'<line x1="{xc - 6:.1f}" y1="{yc + 6:.1f}" x2="{xc + 6:.1f}" y2="{yc - 6:.1f}" stroke="{marker_color}" stroke-width="2"/>'
            )

        parts.append(
            f'<text x="{xc:.1f}" y="{yc + 20:.1f}" text-anchor="middle" fill="{_TEXT_COLOR}">'
            f'{_esc(candidate_id)}</text>'
        )

    # ── Legend + consumer/candidate summary lists (detail text lives here,
    #    one entry per line, so it can never collide horizontally -- see
    #    _SCALE_PX_PER_M's docstring) ──
    list_row_count = len(blueprint.candidates) + len(blueprint.consumers) + 2
    legend_y = height_px - _LEGEND_HEIGHT - _LIST_ROW_HEIGHT * list_row_count + 16
    parts.append(f'<line x1="{_MARGIN_X:.1f}" y1="{legend_y:.1f}" x2="{_MARGIN_X + 30:.1f}" y2="{legend_y:.1f}" stroke="{_SUPPLY_COLOR}" stroke-width="3"/>')
    parts.append(f'<text x="{_MARGIN_X + 36:.1f}" y="{legend_y + 4:.1f}" fill="{_TEXT_COLOR}">supply network</text>')
    parts.append(
        f'<line x1="{_MARGIN_X + 180:.1f}" y1="{legend_y:.1f}" x2="{_MARGIN_X + 210:.1f}" y2="{legend_y:.1f}" '
        f'stroke="{_RETURN_COLOR}" stroke-width="3" stroke-dasharray="8,5"/>'
    )
    parts.append(f'<text x="{_MARGIN_X + 216:.1f}" y="{legend_y + 4:.1f}" fill="{_TEXT_COLOR}">return network (dashed)</text>')

    list_y = legend_y + 24
    parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" font-weight="bold" fill="{_TEXT_COLOR}">Consumers</text>')
    list_y += _LIST_ROW_HEIGHT
    for consumer_id in sorted(blueprint.consumers):
        consumer = blueprint.consumers[consumer_id]
        line = f"{consumer_id}: {consumer.demand_kw:.0f} kW demand"
        parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" fill="{_TEXT_COLOR}">{_esc(line)}</text>')
        list_y += _LIST_ROW_HEIGHT

    list_y += 8
    parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" font-weight="bold" fill="{_TEXT_COLOR}">Candidates</text>')
    list_y += _LIST_ROW_HEIGHT
    for candidate_id in sorted(blueprint.candidates):
        candidate = blueprint.candidates[candidate_id]
        candidate_result = result.candidate_results[candidate_id]
        if isinstance(candidate_result, CandidateEvaluationResult):
            entry = ranked_by_id[candidate_id]
            line = (
                f"{candidate_id}: feasible, rank {entry.rank}, "
                f"{candidate.surface_connection_length_m:.0f} m paired-trench, "
                f"LCOH {entry.economics.indicative_lcoh_eur_per_kwh * 1000.0:.2f} EUR/MWh"
            )
        else:
            line = (
                f"{candidate_id}: infeasible ({candidate_result.failure_code.value}), "
                f"{candidate.surface_connection_length_m:.0f} m paired-trench"
            )
        parts.append(f'<text x="{_MARGIN_X:.1f}" y="{list_y:.1f}" fill="{_TEXT_COLOR}">{_esc(line)}</text>')
        list_y += _LIST_ROW_HEIGHT

    parts.append('</svg>')
    return ("\n".join(parts) + "\n").encode("utf-8")
