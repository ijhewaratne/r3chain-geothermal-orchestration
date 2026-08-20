"""Tests for network/geometry.py -- the single coordinate source (T2.2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.network import geometry

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "demo_assumptions.json"


def test_trunk_pipe_pairs_are_the_four_consecutive_segments():
    assert geometry.trunk_pipe_pairs() == [
        ("trunk_0", "trunk_1"), ("trunk_1", "trunk_2"), ("trunk_2", "trunk_3"), ("trunk_3", "trunk_4"),
    ]


@pytest.mark.parametrize("from_id,to_id", [
    ("trunk_0", "trunk_1"), ("trunk_1", "trunk_2"), ("trunk_2", "trunk_3"), ("trunk_3", "trunk_4"),
])
def test_trunk_pipe_length_is_250m(from_id, to_id):
    assert geometry.trunk_pipe_length_m(from_id, to_id) == pytest.approx(250.0)


@pytest.mark.parametrize("consumer_id", ["consumer_1", "consumer_2", "consumer_3", "consumer_4"])
def test_consumer_branch_length_is_80m(consumer_id):
    assert geometry.consumer_branch_length_m(consumer_id) == pytest.approx(80.0)


@pytest.mark.parametrize("candidate_id,expected_length_m", [
    ("C1", 50.0), ("C2", 70.0), ("C3", 90.0), ("C4", 120.0),
])
def test_candidate_surface_connection_length_matches_hand_computed(candidate_id, expected_length_m):
    assert geometry.candidate_surface_connection_length_m(candidate_id) == pytest.approx(expected_length_m)


def test_candidate_labels_match_real_topological_positions():
    assert geometry.CANDIDATE_LABELS["C1"] == "Near network head"
    assert geometry.CANDIDATE_TRUNK_ATTACHMENT["C1"] == "trunk_1"
    assert geometry.CANDIDATE_LABELS["C4"] == "Near remote/end section"
    assert geometry.CANDIDATE_TRUNK_ATTACHMENT["C4"] == "trunk_4"
    # C3 = "Near branch intersection" -- trunk_3 IS a literal branch point (consumer_3 attaches there).
    assert geometry.CANDIDATE_LABELS["C3"] == "Near branch intersection"
    assert geometry.CONSUMER_TRUNK_ATTACHMENT["consumer_3"] == geometry.CANDIDATE_TRUNK_ATTACHMENT["C3"] == "trunk_3"


def test_euclidean_distance_helper():
    a = geometry.Coordinate(0.0, 0.0)
    b = geometry.Coordinate(3.0, 4.0)
    assert geometry.euclidean_distance_m(a, b) == pytest.approx(5.0)


def test_ret_junction_id_uses_ret_prefix_convention():
    assert geometry.ret_junction_id("trunk_1") == "ret_trunk_1"
    assert geometry.ret_junction_id("consumer_2") == "ret_consumer_2"


def test_ret_coordinate_is_offset_and_never_overlaps_supply_or_candidate_coordinates():
    supply_coords = list(geometry.TRUNK_JUNCTION_COORDINATES.values()) + list(geometry.CONSUMER_JUNCTION_COORDINATES.values())
    candidate_coords = list(geometry.CANDIDATE_SITE_COORDINATES.values())
    ret_coords = [geometry.ret_coordinate(c) for c in supply_coords]
    for ret in ret_coords:
        assert ret not in supply_coords
        assert ret not in candidate_coords


def test_geometry_matches_config_single_source_requirement():
    """The plan-approved geometry values must match config/demo_assumptions.json
    ::network.geometry exactly -- these are meant to be the SAME geometry
    source, one implemented as code, one as human-readable config."""
    config = json.loads(_CONFIG_PATH.read_text())
    net_geometry = config["network"]["geometry"]

    assert net_geometry["trunk_segment_length_m"] == geometry.TRUNK_SEGMENT_LENGTH_M
    assert net_geometry["trunk_segment_count"] == 4
    assert net_geometry["consumer_branch_offset_m"] == geometry.CONSUMER_BRANCH_OFFSET_M
    assert net_geometry["candidate_site_offsets_m"] == {
        cid: abs(geometry.CANDIDATE_SITE_COORDINATES[cid].y_m) for cid in geometry.CANDIDATE_SITE_COORDINATES
    }
    assert net_geometry["trunk_to_consumer_attachment"] == geometry.CONSUMER_TRUNK_ATTACHMENT
    assert net_geometry["trunk_to_candidate_attachment"] == geometry.CANDIDATE_TRUNK_ATTACHMENT

    for candidate in config["candidates"]["list"]:
        cid = candidate["id"]
        assert candidate["supply_junction"] == geometry.CANDIDATE_TRUNK_ATTACHMENT[cid]
        assert candidate["return_junction"] == geometry.ret_junction_id(geometry.CANDIDATE_TRUNK_ATTACHMENT[cid])
        assert candidate["surface_connection_length_m"] == pytest.approx(
            geometry.candidate_surface_connection_length_m(cid)
        )
        assert candidate["label"] == geometry.CANDIDATE_LABELS[cid]
