"""Fixed district-heating integration station (drilling-site-optimization
correction).

## The conceptual correction this module encodes

Every existing joint layer (`workflow/joint_optimization.py` v1,
`workflow/joint_workflow_v2.py` v2, `workflow/research_experiment.py`) treats
the DH network ATTACHMENT point as a free variable, jointly with the
geothermal site/scenario. The corrected research question fixes the
attachment: given ONE predefined district-heating integration point, which
geothermal drilling site should be selected? Candidate identity collapses
from `(site, scenario, attachment, route, design, policy)` to `(site,
scenario)` with `attachment = a0` (fixed).

## Reuse, not reinvention

This module does NOT introduce a new package schema, a new route generator,
or a new evaluator. `JointStudyPackage` (data_contracts.joint_study),
`generate_site_routes()` (network.site_routing), `enumerate_compatible_
alternatives()` / `evaluate_alternative()` (workflow.joint_enumeration /
joint_evaluation), and `decide()` (decision.joint_policy) are all reused
completely unchanged -- see workflow/fixed_interface_workflow.py.

What is missing from the existing contract, and what this module adds, is an
EXPLICIT, validated domain concept for "the one fixed DH integration point"
-- `FixedHeatIntegrationStation` -- plus the one function
(`resolve_fixed_integration_station`) that turns a `JointStudyPackage`
into that explicit station, enforcing (not merely assuming) that the
package actually declares exactly one attachment and that
`routing_policy.allowed_attachment_ids` names only that one. This makes "the
DH network entry does not vary in this methodology" a structural, tested
invariant rather than an incidental configuration choice."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator

from .joint_study import AttachmentEligibilityStatus, JointStudyPackage, NetworkAttachment

_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class FixedInterfaceErrorCode(str, Enum):
    """Stable, typed reason codes for why a `JointStudyPackage` cannot be
    resolved into exactly one `FixedHeatIntegrationStation` -- never a bare
    string or a generic exception message."""

    STATION_MISSING = "STATION_MISSING"
    """`network_attachments` is empty."""
    STATION_AMBIGUOUS = "STATION_AMBIGUOUS"
    """More than one `NetworkAttachment` is declared, or
    `routing_policy.allowed_attachment_ids` names more than one id -- this
    methodology requires exactly one, unlike v1/v2's own multi-attachment
    packages."""
    STATION_ALLOWED_ATTACHMENT_MISMATCH = "STATION_ALLOWED_ATTACHMENT_MISMATCH"
    """`routing_policy.allowed_attachment_ids`'s one entry does not match
    the package's own one `NetworkAttachment.attachment_id`."""
    STATION_INELIGIBLE = "STATION_INELIGIBLE"
    """The one declared attachment's `eligibility_status` is not
    `ELIGIBLE` -- a fixed integration point that cannot itself be used is
    not a valid experiment boundary."""
    STATION_COORDINATE_UNRESOLVED = "STATION_COORDINATE_UNRESOLVED"
    """The attachment's `supply_junction_id` has no known position in the
    synthetic network's own geometry tables (network.geometry) -- never a
    fabricated coordinate."""


class FixedInterfaceValidationError(BaseModel):
    """A `resolve_fixed_integration_station()` failure -- never raised,
    always returned, matching every other boundary in this codebase
    (contracts.PyDoubletCouplingFailure, adapter.errors, network.errors)."""

    model_config = _MODEL_CONFIG

    error_code: FixedInterfaceErrorCode
    message: str


class FixedHeatIntegrationStation(BaseModel):
    """The explicit, predefined geothermal/DH interface -- task's own
    conceptual model (`FixedHeatIntegrationStation`), adapted to this
    repository's Pydantic conventions and to the ONE `NetworkAttachment`
    this station is actually built from (data_contracts.joint_study.
    NetworkAttachment already carries `supply_junction_id`/
    `return_junction_id`; this model does not duplicate that data, it
    names/positions it as a fixed experiment boundary).

    Every candidate drilling site evaluated in this methodology connects to
    THIS station and only this station -- enforced by
    `workflow.fixed_interface_enumeration.enumerate_drilling_site_
    alternatives()`, not merely documented here."""

    model_config = _MODEL_CONFIG

    station_id: str
    """Equal to the underlying `NetworkAttachment.attachment_id` -- the
    same identifier every `AlternativeIdentity.attachment_id` produced by
    this methodology will carry (the invariant this whole module exists to
    make explicit and testable)."""
    name: str
    network_entry_supply_junction_id: str
    network_entry_return_junction_id: str
    x_m: float
    y_m: float
    heat_exchanger_config_reference: str
    """Points at the coupling-assumptions section actually used
    (`CouplingAssumptions.from_config_dict()`, adapter/assumptions.py) --
    this station does not itself carry HX physics, it only names where
    that configuration lives, matching this module's own reuse-not-
    reinvention rule."""
    heat_pump_config_reference: str | None = None
    """`None` in this branch: no heat-pump-assisted integration mode is
    implemented (task's own instruction -- do not add an unrealistic heat
    pump merely to make candidates feasible). Reserved for a future
    extension (docs/decisions/ADR-003)."""
    max_thermal_power_mw: float | None = None
    """Optional declared capacity ceiling for the station itself -- `None`
    means unconstrained-by-the-station (the existing geothermal-capacity/
    HX/network gates still apply per candidate, unchanged)."""
    source_reference: str


def _resolve_attachment_coordinate_or_none(attachment: NetworkAttachment) -> tuple[float, float] | None:
    from ..network.site_routing import resolve_attachment_coordinate

    coordinate = resolve_attachment_coordinate(attachment)
    if coordinate is None:
        return None
    return coordinate.x_m, coordinate.y_m


def resolve_fixed_integration_station(
    package: JointStudyPackage,
    *,
    heat_exchanger_config_reference: str,
    max_thermal_power_mw: float | None = None,
) -> FixedHeatIntegrationStation | FixedInterfaceValidationError:
    """The one function that turns a `JointStudyPackage` into an explicit
    `FixedHeatIntegrationStation`, enforcing every invariant this
    methodology requires:

    - exactly one `NetworkAttachment` is declared on the package,
    - `routing_policy.allowed_attachment_ids` names exactly that one id
      (never more), and
    - that attachment is `ELIGIBLE`.

    Never raises -- every failure is a typed `FixedInterfaceValidationError`.
    A package that declares MULTIPLE attachments (e.g. the existing
    `config/joint_study_synthetic_v2.json`, with `trunk_1..trunk_4`) is
    correctly REJECTED here: it belongs to the v2 joint methodology, not
    this one -- the two are deliberately never interchangeable."""
    if not package.network_attachments:
        return FixedInterfaceValidationError(
            error_code=FixedInterfaceErrorCode.STATION_MISSING,
            message="package.network_attachments is empty -- a fixed-interface study must declare exactly one",
        )
    if len(package.network_attachments) > 1 or len(package.routing_policy.allowed_attachment_ids) > 1:
        return FixedInterfaceValidationError(
            error_code=FixedInterfaceErrorCode.STATION_AMBIGUOUS,
            message=(
                f"a fixed-interface study must declare exactly one NetworkAttachment and exactly one "
                f"routing_policy.allowed_attachment_ids entry -- got "
                f"{len(package.network_attachments)} attachment(s) and "
                f"{len(package.routing_policy.allowed_attachment_ids)} allowed id(s)"
            ),
        )
    attachment = package.network_attachments[0]
    allowed_id = package.routing_policy.allowed_attachment_ids[0]
    if allowed_id != attachment.attachment_id:
        return FixedInterfaceValidationError(
            error_code=FixedInterfaceErrorCode.STATION_ALLOWED_ATTACHMENT_MISMATCH,
            message=(
                f"routing_policy.allowed_attachment_ids[0]={allowed_id!r} does not match the package's "
                f"one declared NetworkAttachment.attachment_id={attachment.attachment_id!r}"
            ),
        )
    if attachment.eligibility_status != AttachmentEligibilityStatus.ELIGIBLE:
        return FixedInterfaceValidationError(
            error_code=FixedInterfaceErrorCode.STATION_INELIGIBLE,
            message=(
                f"the fixed integration station {attachment.attachment_id!r} has "
                f"eligibility_status={attachment.eligibility_status.value!r}, not 'eligible'"
            ),
        )
    resolved = _resolve_attachment_coordinate_or_none(attachment)
    if resolved is None:
        return FixedInterfaceValidationError(
            error_code=FixedInterfaceErrorCode.STATION_COORDINATE_UNRESOLVED,
            message=(
                f"attachment {attachment.attachment_id!r}'s supply_junction_id "
                f"{attachment.supply_junction_id!r} has no known position in the synthetic network's "
                "own geometry tables (network/geometry.py)"
            ),
        )
    x_m, y_m = resolved
    return FixedHeatIntegrationStation(
        station_id=attachment.attachment_id,
        name=f"Fixed DH integration station ({attachment.attachment_id})",
        network_entry_supply_junction_id=attachment.supply_junction_id,
        network_entry_return_junction_id=attachment.return_junction_id,
        x_m=x_m, y_m=y_m,
        heat_exchanger_config_reference=heat_exchanger_config_reference,
        heat_pump_config_reference=None,
        max_thermal_power_mw=max_thermal_power_mw,
        source_reference=attachment.source_reference,
    )
