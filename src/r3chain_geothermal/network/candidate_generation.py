"""Deterministic network-connection candidate generation (CAN-001..007,
R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Workstream H).

## Modes (CAN-001)

`config/demo_assumptions.json`'s own four predefined candidates (C1-C4,
`network/geometry.py::CANDIDATE_TRUNK_ATTACHMENT`) remain the backward-
compatible default and are UNCHANGED and UNTOUCHED by this module. This
module adds the OTHER mode: `generate_candidates()` deterministically
derives a larger candidate set from the synthetic blueprint's own
junctions -- entirely additive, never wired into `run_workflow()`'s
existing predefined path (that would be a much larger, separately-
reviewable change; see `docs/issues/candidate-generation.md`).

## Eligible attachments (CAN-002)

Every trunk junction (`trunk_1`..`trunk_4`, `network/geometry.py`) and
every consumer junction (`consumer_1`..`consumer_4`) that has a `ret_`
counterpart already present in the blueprint is ELIGIBLE -- this
generator never connects two junctions merely because they are
geometrically close; eligibility is the explicit trunk/consumer
membership test in `eligible_attachments()`, not a distance threshold.
One junction (`GENERATION_EXCLUDED_ATTACHMENT_ID`, `consumer_4`) is
marked EXCLUDED as a synthetic protected-zone example (CAN-002's
"exclusion zones"). A maximum route length
(`GENERATION_MAX_ROUTE_LENGTH_M`) is enforced as an eligibility limit
(CAN-002's "maximum route length"). Pressure-zone compatibility and
pipe-capacity checks are DECLARED as typed screening reasons (CAN-005)
but never fire in this synthetic network, which has exactly one pressure
zone and one fixed pipe DN throughout -- see
`CandidateGenerationFailureReason`'s own docstring for which reasons are
exercised by this generator's normal output versus only by a dedicated,
contrived test.

## Stable identity (CAN-003)

`candidate_id = f"{study_id}-{attachment_id}-{route_id}-{design_option_id}"`
-- a pure function of these four normalized components, never of
iteration order or wall-clock time. `generate_candidates()` always
returns candidates in a fixed, sorted order (by candidate_id).

## Routing abstraction (CAN-004)

`RouteOption.kind` is currently always `"synthetic_direct"` in this
generator -- a declared, straight-line-style distance from
`network/geometry.py`'s own coordinate table (trunk attachments reuse
the ALREADY-APPROVED C1-C4 site distances exactly;
`CONSUMER_DECLARED_BASE_DISTANCE_M` is a NEW, explicitly synthetic
declared distance for consumer attachments, since geometry.py has no
existing site-distance table for them). `"network_graph"` and
`"external_gis"` are declared enum members (the interface CAN-004 asks
for) but have no implementation in this synthetic demonstration --
selecting either raises `NotImplementedError` rather than silently
falling back to the synthetic distance, so a straight-line distance is
never mislabelled as a routed construction length (CAN-004's explicit
requirement).

## Design options (CAN-006)

Two declared route multipliers ("direct" x1.0, "diverted" x1.5) per
attachment give each location TWO route-length variants, and ONE design
option ("standard", the project's existing fixed
`CONNECTION_PIPE_DN_MM`) -- candidate identity therefore already
distinguishes location (attachment) and route from design, even though
this generation's own output only ever varies the first two axes in
practice: a second, differently-sized design option is not yet
constructable by `network/candidate.py`'s own evaluator (which reads the
project-wide `CONNECTION_PIPE_DN_MM` constant, not a per-candidate DN --
see `docs/issues/candidate-generation.md` for why extending that was
judged out of proportion to this workstream).

## Screening (CAN-005)

`generate_candidates()` NEVER raises for a screened-out attachment/route
combination -- every one is returned as a `ScreenedCandidate`
(`accepted=False`, an exact `CandidateGenerationFailureReason`, and a
human-readable detail), preserved for audit, exactly like every other
layer's boundary-result convention in this project.

## Synthetic demonstration (CAN-007)

`generate_candidates()` on the canonical `build_default_blueprint()`
topology deterministically returns: 4 trunk attachments x 2 routes = 8
accepted candidates; 3 non-excluded consumer attachments x "direct"
route = 3 accepted; 3 non-excluded consumer attachments x "diverted"
route = 3 rejected (`ROUTE_LENGTH_EXCEEDS_LIMIT`, 300 m > the 250 m
limit); 1 excluded consumer (`consumer_4`) x 2 routes = 2 rejected
(`EXCLUDED_PROTECTED_GEOMETRY`) -- 11 accepted, 5 rejected, 16 total,
identical on every call (`tests/network/test_candidate_generation.py`).
Every accepted candidate constructs and evaluates independently through
the EXISTING, unmodified `network/candidate.py::evaluate_candidate()`
(no new physics). All coordinates/routes are explicitly synthetic (module
docstring, this section) -- this generator makes no claim about a real
network. This demonstration does not replace, and is never substituted
for, the canonical predefined C1-C4 regression case.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .blueprint import BlueprintCandidate, NetworkBlueprint
from .geometry import (
    CANDIDATE_TRUNK_ATTACHMENT,
    CONSUMER_TRUNK_ATTACHMENT,
    candidate_surface_connection_length_m,
    ret_junction_id,
)

CANDIDATE_GENERATION_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""Versioned independently of every other layer's own contract schema."""

GENERATION_STUDY_ID = "r3chain-synthetic-network-v1"
"""CAN-003's "normalized study id" component -- a fixed, named constant
for this synthetic demonstration (not yet study-package-driven; that is
Workstream I's own concern)."""

GENERATION_MAX_ROUTE_LENGTH_M = 250.0
"""CAN-002's "maximum route length" eligibility limit. A named constant,
not a config value -- this is a candidate-GENERATION policy parameter for
a not-yet-config-driven demonstration mode, the same category as
network/candidate.py's own SELF_CONSISTENT_FLOW_* solver constants."""

GENERATION_EXCLUDED_ATTACHMENT_ID = "consumer_4"
"""CAN-002's "exclusion zones" -- one synthetic protected-geometry example
in this demonstration. Not a claim about any real constraint."""

CONSUMER_DECLARED_BASE_DISTANCE_M = 200.0
"""A NEW, explicitly synthetic declared/direct distance for consumer
attachments (module docstring, "Routing abstraction") -- geometry.py has
no existing site-distance table for consumer junctions (only for
trunk-attached C1-C4); this is judged a reasonable synthetic value under
the SAME "direct offset from the network junction" convention C1-C4
already use, not derived from any real measurement."""

_ROUTE_MULTIPLIERS: dict[str, float] = {"direct": 1.0, "diverted": 1.5}


class CandidateGenerationFailureReason(str, Enum):
    """CAN-005's typed screening-rejection vocabulary. Reasons marked
    "(demo-reachable)" occur in generate_candidates()'s own normal output
    on the canonical blueprint; reasons marked "(contrived-only)" are
    implemented and unit-tested but do not occur naturally in this
    synthetic network (documented, not silently unimplemented) -- e.g.
    there is exactly one pressure zone and one fixed pipe DN throughout,
    so pressure-zone and pipe-data checks never actually reject anything
    here."""

    MISSING_SUPPLY_RETURN_PAIR = "MISSING_SUPPLY_RETURN_PAIR"
    """(contrived-only) An attachment's declared return junction does not
    exist in the blueprint."""
    INVALID_PRESSURE_ZONE_PAIRING = "INVALID_PRESSURE_ZONE_PAIRING"
    """(contrived-only) This synthetic network has exactly one pressure
    zone; never fires on real generator output."""
    ROUTE_LENGTH_EXCEEDS_LIMIT = "ROUTE_LENGTH_EXCEEDS_LIMIT"
    """(demo-reachable) declared route length > GENERATION_MAX_ROUTE_LENGTH_M."""
    EXCLUDED_PROTECTED_GEOMETRY = "EXCLUDED_PROTECTED_GEOMETRY"
    """(demo-reachable) the attachment is GENERATION_EXCLUDED_ATTACHMENT_ID."""
    MISSING_PIPE_OR_DESIGN_DATA = "MISSING_PIPE_OR_DESIGN_DATA"
    """(contrived-only) a design option with a non-positive connection DN."""
    DUPLICATE_TOPOLOGY = "DUPLICATE_TOPOLOGY"
    """(contrived-only) two candidates resolving to the identical
    (supply_junction, return_junction, surface_connection_length_m,
    connection_pipe_dn_mm) tuple."""
    COMPONENT_CONSTRUCTION_CONFLICT = "COMPONENT_CONSTRUCTION_CONFLICT"
    """(contrived-only) two candidates sharing the same candidate_id."""


class EligibleAttachment(BaseModel):
    """One candidate connection point BEFORE routing/design are applied
    (CAN-002)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: str
    supply_junction: str
    return_junction: str
    category: Literal["trunk", "consumer"]
    base_distance_m: float
    """A declared, direct distance (module docstring, "Routing
    abstraction") -- never a routed construction length."""
    excluded: bool = False
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "EligibleAttachment":
        if self.base_distance_m <= 0:
            raise ValueError("base_distance_m must be > 0")
        if self.excluded and not self.exclusion_reason:
            raise ValueError("excluded=True requires a non-empty exclusion_reason")
        return self


class RouteOption(BaseModel):
    """CAN-004's routing abstraction, one concrete option."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    route_id: Literal["direct", "diverted"]
    kind: Literal["synthetic_direct", "network_graph", "external_gis"] = "synthetic_direct"
    length_multiplier: float

    def resolve_length_m(self, base_distance_m: float) -> float:
        """CAN-004: "straight-line distance must never be labelled routed
        construction length" -- only "synthetic_direct" is implemented;
        the other two kinds raise rather than silently reusing the
        synthetic distance under a different label."""
        if self.kind != "synthetic_direct":
            raise NotImplementedError(
                f"RouteOption.kind={self.kind!r} has no implementation in this synthetic "
                "generator -- a network-graph or external-GIS route length requires an actual "
                "routing graph or an approved external route reference, neither of which this "
                "demonstration has (Workstream I's own concern, not fabricated here)."
            )
        return base_distance_m * self.length_multiplier


class DesignOption(BaseModel):
    """CAN-006: a candidate's design axis, kept distinct from its
    location (EligibleAttachment) and route (RouteOption)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_option_id: Literal["standard"] = "standard"
    connection_pipe_dn_mm: float

    @model_validator(mode="after")
    def _validate(self) -> "DesignOption":
        if self.connection_pipe_dn_mm <= 0:
            raise ValueError("connection_pipe_dn_mm must be > 0")
        return self


class GeneratedCandidateSpec(BaseModel):
    """A fully-resolved, accepted candidate -- constructable via
    `to_blueprint_candidate()` and evaluable through the EXISTING,
    unmodified `network/candidate.py::evaluate_candidate()`."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    study_id: str
    attachment_id: str
    route_id: str
    design_option_id: str
    supply_junction: str
    return_junction: str
    surface_connection_length_m: float
    connection_pipe_dn_mm: float

    def to_blueprint_candidate(self, label: str | None = None) -> BlueprintCandidate:
        return BlueprintCandidate(
            id=self.candidate_id, label=label or self.candidate_id,
            supply_junction=self.supply_junction, return_junction=self.return_junction,
            surface_connection_length_m=self.surface_connection_length_m,
        )


class ScreenedCandidate(BaseModel):
    """CAN-005: every attachment/route/design combination this generator
    considered, accepted or not -- preserved for audit, never silently
    dropped."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    accepted: bool
    spec: GeneratedCandidateSpec | None
    rejection_reason: CandidateGenerationFailureReason | None
    rejection_detail: str

    @model_validator(mode="after")
    def _validate(self) -> "ScreenedCandidate":
        if self.accepted:
            if self.spec is None:
                raise ValueError("accepted=True requires spec")
            if self.rejection_reason is not None:
                raise ValueError("accepted=True must not carry a rejection_reason")
        else:
            if self.rejection_reason is None:
                raise ValueError("accepted=False requires an exact rejection_reason")
        return self


def eligible_attachments() -> list[EligibleAttachment]:
    """CAN-002: every trunk (C1-C4's own attachment points) and consumer
    junction this generator nominally knows about, from
    network/geometry.py's own tables -- independent of any specific
    `NetworkBlueprint` instance (whether each one's junction pair actually
    EXISTS in a given blueprint is `generate_candidates()`'s own check,
    yielding a typed MISSING_SUPPLY_RETURN_PAIR screening result rather
    than a silent omission here -- CAN-005: "preserve screened-out
    candidates in the audit"). Deterministic order: trunk attachments (by
    CANDIDATE_TRUNK_ATTACHMENT's own C1-C4 order) then consumer
    attachments (sorted by id)."""
    attachments: list[EligibleAttachment] = []
    for candidate_id, trunk_id in CANDIDATE_TRUNK_ATTACHMENT.items():
        attachments.append(EligibleAttachment(
            attachment_id=trunk_id, supply_junction=trunk_id, return_junction=ret_junction_id(trunk_id),
            category="trunk", base_distance_m=candidate_surface_connection_length_m(candidate_id),
        ))
    for consumer_id in sorted(CONSUMER_TRUNK_ATTACHMENT):
        excluded = consumer_id == GENERATION_EXCLUDED_ATTACHMENT_ID
        attachments.append(EligibleAttachment(
            attachment_id=consumer_id, supply_junction=consumer_id, return_junction=ret_junction_id(consumer_id),
            category="consumer", base_distance_m=CONSUMER_DECLARED_BASE_DISTANCE_M,
            excluded=excluded,
            exclusion_reason=(
                f"{consumer_id} is a synthetic protected-geometry demonstration example "
                "(GENERATION_EXCLUDED_ATTACHMENT_ID)" if excluded else None
            ),
        ))
    return attachments


def generate_candidates(
    blueprint: NetworkBlueprint,
    *,
    study_id: str = GENERATION_STUDY_ID,
    connection_pipe_dn_mm: float,
    max_route_length_m: float = GENERATION_MAX_ROUTE_LENGTH_M,
) -> list[ScreenedCandidate]:
    """CAN-001/007: the deterministic generated-mode candidate set.
    `connection_pipe_dn_mm` must be supplied by the caller (this module
    never reads network/candidate.py's own CONNECTION_PIPE_DN_MM directly,
    keeping this generator's design axis genuinely independent of that
    evaluator's own fixed value -- see module docstring, "Design
    options")."""
    screened: list[ScreenedCandidate] = []
    seen_topology: dict[tuple[str, str, float, float], str] = {}
    seen_candidate_ids: set[str] = set()

    for attachment in eligible_attachments():
        for route_id, multiplier in sorted(_ROUTE_MULTIPLIERS.items()):
            route = RouteOption(route_id=route_id, length_multiplier=multiplier)
            try:
                design = DesignOption(connection_pipe_dn_mm=connection_pipe_dn_mm)
            except ValidationError as exc:
                candidate_id = f"{study_id}-{attachment.attachment_id}-{route.route_id}-standard"
                screened.append(ScreenedCandidate(
                    candidate_id=candidate_id, accepted=False, spec=None,
                    rejection_reason=CandidateGenerationFailureReason.MISSING_PIPE_OR_DESIGN_DATA,
                    rejection_detail=f"invalid connection_pipe_dn_mm={connection_pipe_dn_mm!r}: {exc}",
                ))
                continue
            candidate_id = f"{study_id}-{attachment.attachment_id}-{route.route_id}-{design.design_option_id}"

            if attachment.supply_junction not in blueprint.junctions or attachment.return_junction not in blueprint.junctions:
                screened.append(ScreenedCandidate(
                    candidate_id=candidate_id, accepted=False, spec=None,
                    rejection_reason=CandidateGenerationFailureReason.MISSING_SUPPLY_RETURN_PAIR,
                    rejection_detail=(
                        f"supply_junction={attachment.supply_junction!r} or "
                        f"return_junction={attachment.return_junction!r} not present in blueprint.junctions"
                    ),
                ))
                continue

            if attachment.excluded:
                screened.append(ScreenedCandidate(
                    candidate_id=candidate_id, accepted=False, spec=None,
                    rejection_reason=CandidateGenerationFailureReason.EXCLUDED_PROTECTED_GEOMETRY,
                    rejection_detail=attachment.exclusion_reason or "excluded",
                ))
                continue

            length_m = route.resolve_length_m(attachment.base_distance_m)
            if length_m > max_route_length_m:
                screened.append(ScreenedCandidate(
                    candidate_id=candidate_id, accepted=False, spec=None,
                    rejection_reason=CandidateGenerationFailureReason.ROUTE_LENGTH_EXCEEDS_LIMIT,
                    rejection_detail=f"{length_m:.1f} m exceeds max_route_length_m={max_route_length_m:.1f} m",
                ))
                continue

            topology_key = (attachment.supply_junction, attachment.return_junction, length_m, design.connection_pipe_dn_mm)
            if topology_key in seen_topology:
                screened.append(ScreenedCandidate(
                    candidate_id=candidate_id, accepted=False, spec=None,
                    rejection_reason=CandidateGenerationFailureReason.DUPLICATE_TOPOLOGY,
                    rejection_detail=f"identical to {seen_topology[topology_key]!r}",
                ))
                continue
            if candidate_id in seen_candidate_ids:
                screened.append(ScreenedCandidate(
                    candidate_id=candidate_id, accepted=False, spec=None,
                    rejection_reason=CandidateGenerationFailureReason.COMPONENT_CONSTRUCTION_CONFLICT,
                    rejection_detail=f"candidate_id {candidate_id!r} already assigned",
                ))
                continue

            spec = GeneratedCandidateSpec(
                candidate_id=candidate_id, study_id=study_id, attachment_id=attachment.attachment_id,
                route_id=route.route_id, design_option_id=design.design_option_id,
                supply_junction=attachment.supply_junction, return_junction=attachment.return_junction,
                surface_connection_length_m=length_m, connection_pipe_dn_mm=design.connection_pipe_dn_mm,
            )
            seen_topology[topology_key] = candidate_id
            seen_candidate_ids.add(candidate_id)
            screened.append(ScreenedCandidate(
                candidate_id=candidate_id, accepted=True, spec=spec, rejection_reason=None, rejection_detail="",
            ))

    return sorted(screened, key=lambda sc: sc.candidate_id)
