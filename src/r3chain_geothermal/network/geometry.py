"""The single geometry source for the T2.2 synthetic four-consumer network:
one coordinate table, from which every supply pipe length, every consumer
branch length, and every candidate surface-connection length is derived by
Euclidean distance. The pandapipes network builder (builder.py), a later
map, and later economics must all consume these SAME derived lengths --
never a separately re-measured value (plan §10.2's "the map, the pandapipes
connection pipes and the economic calculation must all consume the SAME
single length value per candidate").

Topology (plan-approved, config/demo_assumptions.json schema 0.7):

              consumer_1(+80m)   consumer_2(+80m)   consumer_3(+80m)   consumer_4(+80m)
                    |                  |                  |                  |
trunk_0 --250m-- trunk_1 --250m-- trunk_2 --250m-- trunk_3 --250m-- trunk_4
(plant)             |                  |                  |                  |
                 C1(-50m)          C2(-70m)           C3(-90m)          C4(-120m)

trunk_1..4 double as the candidate connection points: C1="Near network
head" (trunk_1), C2="Near central trunk" (trunk_2), C3="Near branch
intersection" (trunk_3, a literal consumer-branch junction), C4="Near
remote/end section" (trunk_4, the literal end of the trunk) -- the labels
match real topological positions, not decoration.

Return-side coordinates exist ONLY for future map legibility (a large,
non-overlapping y-offset) -- they are NOT used to compute return pipe
lengths. A mirrored return pipe's length is, by definition, identical to
its corresponding supply pipe's length (see RETURN_PIPE_LENGTHS_MIRROR_SUPPLY
below) -- independently re-measuring it from separate return coordinates
would risk exactly the kind of silent-drift this project's config
repeatedly warns against.
"""
from __future__ import annotations

import math
from typing import NamedTuple


class Coordinate(NamedTuple):
    x_m: float
    y_m: float


def euclidean_distance_m(a: Coordinate, b: Coordinate) -> float:
    return math.hypot(a.x_m - b.x_m, a.y_m - b.y_m)


TRUNK_SEGMENT_LENGTH_M = 250.0
CONSUMER_BRANCH_OFFSET_M = 80.0
RETURN_Y_OFFSET_M = -300.0  # map-legibility only, not used for any length

# ── Supply-side junction coordinates (the single geometry source) ──────────
TRUNK_JUNCTION_COORDINATES: dict[str, Coordinate] = {
    "trunk_0": Coordinate(0.0, 0.0),
    "trunk_1": Coordinate(250.0, 0.0),
    "trunk_2": Coordinate(500.0, 0.0),
    "trunk_3": Coordinate(750.0, 0.0),
    "trunk_4": Coordinate(1000.0, 0.0),
}

CONSUMER_JUNCTION_COORDINATES: dict[str, Coordinate] = {
    "consumer_1": Coordinate(250.0, CONSUMER_BRANCH_OFFSET_M),
    "consumer_2": Coordinate(500.0, CONSUMER_BRANCH_OFFSET_M),
    "consumer_3": Coordinate(750.0, CONSUMER_BRANCH_OFFSET_M),
    "consumer_4": Coordinate(1000.0, CONSUMER_BRANCH_OFFSET_M),
}

# consumer id -> the trunk junction id its branch pipe connects to
CONSUMER_TRUNK_ATTACHMENT: dict[str, str] = {
    "consumer_1": "trunk_1",
    "consumer_2": "trunk_2",
    "consumer_3": "trunk_3",
    "consumer_4": "trunk_4",
}

# Candidate site coordinates -- NOT part of the pandapipes network itself
# (plan: "create valid candidate supply/return junction pairs, without
# evaluating geothermal connections yet"). Only used to derive
# surface_connection_length_m; the candidate's supply_junction/
# return_junction ARE the existing trunk_N/ret_trunk_N junctions.
CANDIDATE_SITE_COORDINATES: dict[str, Coordinate] = {
    "C1": Coordinate(250.0, -50.0),
    "C2": Coordinate(500.0, -70.0),
    "C3": Coordinate(750.0, -90.0),
    "C4": Coordinate(1000.0, -120.0),
}

CANDIDATE_TRUNK_ATTACHMENT: dict[str, str] = {
    "C1": "trunk_1",
    "C2": "trunk_2",
    "C3": "trunk_3",
    "C4": "trunk_4",
}

CANDIDATE_LABELS: dict[str, str] = {
    "C1": "Near network head",
    "C2": "Near central trunk",
    "C3": "Near branch intersection",
    "C4": "Near remote/end section",
}

TRUNK_ORDER = ["trunk_0", "trunk_1", "trunk_2", "trunk_3", "trunk_4"]


def trunk_pipe_pairs() -> list[tuple[str, str]]:
    """The four consecutive trunk segments, in order."""
    return list(zip(TRUNK_ORDER[:-1], TRUNK_ORDER[1:]))


def trunk_pipe_length_m(from_junction: str, to_junction: str) -> float:
    return euclidean_distance_m(
        TRUNK_JUNCTION_COORDINATES[from_junction], TRUNK_JUNCTION_COORDINATES[to_junction],
    )


def consumer_branch_length_m(consumer_id: str) -> float:
    trunk_id = CONSUMER_TRUNK_ATTACHMENT[consumer_id]
    return euclidean_distance_m(
        CONSUMER_JUNCTION_COORDINATES[consumer_id], TRUNK_JUNCTION_COORDINATES[trunk_id],
    )


def candidate_surface_connection_length_m(candidate_id: str) -> float:
    trunk_id = CANDIDATE_TRUNK_ATTACHMENT[candidate_id]
    return euclidean_distance_m(
        CANDIDATE_SITE_COORDINATES[candidate_id], TRUNK_JUNCTION_COORDINATES[trunk_id],
    )


def ret_junction_id(supply_junction_id: str) -> str:
    """Mirrored return-junction naming convention (`ret_` prefix), adopted
    from pandapipesAI's own established net_builder.py pattern
    (add_return_network=True mode) for consistency."""
    return f"ret_{supply_junction_id}"


def ret_coordinate(supply_coordinate: Coordinate) -> Coordinate:
    """Map-legibility-only return-side coordinate -- NOT used for any pipe
    length. See module docstring."""
    return Coordinate(supply_coordinate.x_m, supply_coordinate.y_m + RETURN_Y_OFFSET_M)
