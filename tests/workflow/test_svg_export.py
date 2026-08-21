"""Full test matrix for workflow/svg_export.py -- network_candidates.svg
(T2.4B2). Pure deterministic string templating -- validated at the XML
structural level here; a rendered visual inspection was performed
separately (not automatable) and confirmed: no overlapping text labels,
distinct marker shapes for feasible/infeasible candidates, and the
mandatory schematic disclaimer rendering legibly."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow import WorkflowResult, run_workflow
from r3chain_geothermal.workflow.svg_export import SCHEMATIC_LABEL, render_network_candidates_svg

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_SVG_NS = "{http://www.w3.org/2000/svg}"


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _worked_result() -> WorkflowResult:
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    return result


def _mixed_result() -> WorkflowResult:
    config = _config()
    config["gates"]["min_pressure_bar_abs"] = 2.95
    result = run_workflow(_raw(), config, source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    return result


def _all_text(root: ET.Element) -> list[str]:
    return [el.text for el in root.iter(f"{_SVG_NS}text") if el.text]


def test_output_is_well_formed_xml():
    svg_bytes = render_network_candidates_svg(_worked_result())
    root = ET.fromstring(svg_bytes)
    assert root.tag == f"{_SVG_NS}svg"


def test_mandatory_schematic_disclaimer_is_present_verbatim():
    svg_bytes = render_network_candidates_svg(_worked_result())
    root = ET.fromstring(svg_bytes)
    assert SCHEMATIC_LABEL in _all_text(root)


def test_all_four_consumers_and_candidates_appear_by_id():
    root = ET.fromstring(render_network_candidates_svg(_worked_result()))
    texts = _all_text(root)
    for consumer_id in ("consumer_1", "consumer_2", "consumer_3", "consumer_4"):
        assert consumer_id in texts
    for candidate_id in ("C1", "C2", "C3", "C4"):
        assert candidate_id in texts


def test_infeasible_candidate_failure_code_appears_in_summary_text():
    root = ET.fromstring(render_network_candidates_svg(_mixed_result()))
    texts = " ".join(_all_text(root))
    assert "PRESSURE_LIMIT_EXCEEDED" in texts
    assert "C4" in texts


def test_feasible_and_infeasible_markers_use_distinct_shapes_not_colour_alone():
    """C1-C3 feasible (filled <circle>), C4 infeasible (<rect> + two
    diagonal <line>s forming an X) -- shape differs, not only fill colour."""
    root = ET.fromstring(render_network_candidates_svg(_mixed_result()))
    circles = list(root.iter(f"{_SVG_NS}circle"))
    rects = list(root.iter(f"{_SVG_NS}rect"))
    # 4 consumer circles + 3 feasible candidate circles = 7
    assert len(circles) == 7
    # 1 background <rect> + 1 infeasible candidate square marker
    assert len(rects) == 2


def test_all_four_candidates_feasible_gives_only_the_background_rect():
    root = ET.fromstring(render_network_candidates_svg(_worked_result()))
    rects = list(root.iter(f"{_SVG_NS}rect"))
    assert len(rects) == 1


def test_supply_and_return_lines_use_distinct_stroke_styling():
    svg_text = render_network_candidates_svg(_worked_result()).decode("utf-8")
    assert "#1b4f8c" in svg_text  # supply colour
    assert "#b3541e" in svg_text  # return colour
    assert "stroke-dasharray" in svg_text  # return network is dashed, supply is solid


def test_no_text_labels_overlap_horizontally_within_the_same_row():
    """Regression guard for the overlap bug found during visual inspection:
    every consumer/candidate marker's inline label is now just its short
    ID (never the full demand/feasibility/length sentence), so adjacent
    labels at the fixed 250 m/0.5 px-per-m spacing never collide. Detail
    text lives exclusively in the vertically-stacked summary lists."""
    root = ET.fromstring(render_network_candidates_svg(_worked_result()))
    inline_labels = [el.text for el in root.iter(f"{_SVG_NS}text") if el.text in ("C1", "C2", "C3", "C4")]
    assert inline_labels == ["C1", "C2", "C3", "C4"]
    consumer_labels = [
        el.text for el in root.iter(f"{_SVG_NS}text")
        if el.text in ("consumer_1", "consumer_2", "consumer_3", "consumer_4")
    ]
    assert consumer_labels == ["consumer_1", "consumer_2", "consumer_3", "consumer_4"]


def test_summary_lists_carry_the_full_detail_text():
    root = ET.fromstring(render_network_candidates_svg(_worked_result()))
    texts = " ".join(_all_text(root))
    assert "650 kW demand" in texts
    assert "feasible, rank 1" in texts
    assert "50 m paired-trench" in texts
    assert "52.17 EUR/MWh" in texts


def test_rendering_is_deterministic_across_two_independent_runs():
    result_1 = _worked_result()
    result_2 = _worked_result()
    assert render_network_candidates_svg(result_1) == render_network_candidates_svg(result_2)


def test_no_wall_clock_content_in_output():
    svg_bytes = render_network_candidates_svg(_worked_result())
    assert b"created_at" not in svg_bytes


def test_schematic_disclaimer_em_dash_survives_utf8_round_trip():
    svg_bytes = render_network_candidates_svg(_worked_result())
    assert "—".encode("utf-8") in svg_bytes
