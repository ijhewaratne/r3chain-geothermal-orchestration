"""Real-data readiness reporting (DATA-009, OPT-006's real-mode safeguard).

`generate_readiness_report()` is the single source of truth for whether
connection-optimisation or drilling-location-optimisation may proceed
against a given study package. Both permission flags default to `False`
and are set `True` only under conditions checked explicitly below --
never inferred from the mere presence of data.

## `enforce_real_data_readiness()` (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase 5)

The MANDATORY gate any future real-data entry point must call before
proceeding to connection- or drilling-location optimisation against a
`classification=="real"` `StudyPackage` -- returns a structured
`DATA_REQUIREMENTS_NOT_MET` failure enumerating every missing/invalid
dataset when the package is not ready, never a silent pass. As of this
phase, NO code path anywhere in this repository actually calls it with a
real package: `network/blueprint.py`, `workflow/core.py`, and
`workflow/joint_workflow.py` only ever construct or consume SYNTHETIC
data (verified directly, `grep -rn "DatasetClassification.REAL" src/`
outside this module and its tests returns nothing) -- real-data
ingestion itself remains Phase 8's own external-data-gated concern,
explicitly not attempted here (CLAUDE.md, this specification's own
non-negotiable rules). This function exists so that WHENEVER a future,
separately-approved real-data entry point is added, it has no honest way
to skip this check -- it is the enforced choke point, not a demonstration
of one."""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .schema import ApprovalStatus, DatasetClassification, StudyPackage
from .validation import StudyPackageFieldError, validate_study_package


class StudyReadinessReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    classification: DatasetClassification
    supplied_datasets: list[str]
    missing_datasets: list[str]
    validation_errors: list[StudyPackageFieldError]
    provisional_assumptions: list[str]
    unresolved_approvals: list[str]
    connection_optimization_permitted: bool
    drilling_location_optimization_permitted: bool


_ALL_DATASET_SECTIONS = ("network", "geothermal_scenarios", "economics", "decisions")


def generate_readiness_report(package: StudyPackage) -> StudyReadinessReport:
    validation = validate_study_package(package)

    supplied: list[str] = []
    missing: list[str] = []
    if package.network is not None:
        supplied.append("network")
    else:
        missing.append("network")
    if package.geothermal_scenarios:
        supplied.append("geothermal_scenarios")
    else:
        missing.append("geothermal_scenarios")
    if package.economics:
        supplied.append("economics")
    else:
        missing.append("economics")
    if package.decisions is not None:
        supplied.append("decisions")
    else:
        missing.append("decisions")

    provisional_assumptions: list[str] = []
    if package.manifest.approval_status == ApprovalStatus.PROVISIONAL:
        provisional_assumptions.append(f"manifest.approval_status is {ApprovalStatus.PROVISIONAL.value!r}")

    unresolved_approvals: list[str] = []
    if package.manifest.approval_status != ApprovalStatus.APPROVED:
        unresolved_approvals.append(f"study {package.manifest.study_id!r} manifest is not approved")

    is_synthetic = package.manifest.classification == DatasetClassification.SYNTHETIC
    is_fully_supplied_and_valid_and_approved = (
        validation.valid
        and not missing
        and package.manifest.approval_status == ApprovalStatus.APPROVED
    )

    # OPT-006: real mode must not run to a recommendation unless the
    # readiness report permits it -- a synthetic package is always
    # permitted for its OWN explicitly-synthetic demonstration purpose
    # (Workstream J), but a REAL package is permitted only when fully
    # supplied, valid, and approved. Neither path ever infers permission
    # from data merely being present.
    connection_optimization_permitted = is_synthetic or is_fully_supplied_and_valid_and_approved

    drilling_location_optimization_permitted = (
        connection_optimization_permitted and bool(package.geothermal_scenarios)
    )

    return StudyReadinessReport(
        study_id=package.manifest.study_id, classification=package.manifest.classification,
        supplied_datasets=supplied, missing_datasets=missing, validation_errors=validation.errors,
        provisional_assumptions=provisional_assumptions, unresolved_approvals=unresolved_approvals,
        connection_optimization_permitted=connection_optimization_permitted,
        drilling_location_optimization_permitted=drilling_location_optimization_permitted,
    )


class RealDataRequirement(str, Enum):
    """Which named requirement a real study package is missing/invalid
    for -- deliberately named after the SPEC's own vocabulary (topology,
    pipe attributes, demands, temperatures, CRS, candidate constraints,
    geological scenarios, economics, provenance/approval), each mapped
    onto the existing `StudyPackageErrorCode`/missing-dataset/approval
    checks `generate_readiness_report()` already computes -- no new
    validation logic, only a stable, spec-aligned name for each one."""

    NETWORK_TOPOLOGY = "NETWORK_TOPOLOGY"
    PIPE_ATTRIBUTES = "PIPE_ATTRIBUTES"
    DEMANDS_AND_TEMPERATURES = "DEMANDS_AND_TEMPERATURES"
    SPATIAL_CRS = "SPATIAL_CRS"
    GEOTHERMAL_SCENARIOS = "GEOTHERMAL_SCENARIOS"
    ECONOMICS_AND_PLANNING = "ECONOMICS_AND_PLANNING"
    PROVENANCE_OR_LICENSING = "PROVENANCE_OR_LICENSING"
    APPROVAL_STATUS = "APPROVAL_STATUS"


_ERROR_CODE_TO_REQUIREMENT: dict[str, RealDataRequirement] = {
    "MISSING_CRS": RealDataRequirement.SPATIAL_CRS,
    "MISSING_PROVENANCE": RealDataRequirement.PROVENANCE_OR_LICENSING,
    "DUPLICATE_ID": RealDataRequirement.NETWORK_TOPOLOGY,
    "DISCONNECTED_TOPOLOGY": RealDataRequirement.NETWORK_TOPOLOGY,
    "IMPOSSIBLE_TEMPERATURE": RealDataRequirement.DEMANDS_AND_TEMPERATURES,
    "INVALID_DIMENSION": RealDataRequirement.PIPE_ATTRIBUTES,
    "INCONSISTENT_UNITS": RealDataRequirement.PIPE_ATTRIBUTES,
    "MISSING_REQUIRED_FIELD": RealDataRequirement.NETWORK_TOPOLOGY,
}


class RealDataReadinessGranted(BaseModel):
    """The real study package satisfies every requirement Phase 5 names
    for the requested optimisation kind -- returned ONLY when
    `readiness.connection_optimization_permitted` (or, for a drilling-
    relevant request, `drilling_location_optimization_permitted`) is
    `True`."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ready"] = "ready"
    study_id: str
    requested_optimization: Literal["connection", "drilling_location"]
    readiness: StudyReadinessReport


class DataRequirementsNotMet(BaseModel):
    """R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase 5's own
    named failure: enumerates every missing/invalid requirement rather
    than a single boolean -- never a silent fallback to synthetic data
    while still being labelled real (the caller's `package.manifest
    .classification` is echoed back unchanged, never overridden)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["failure"] = "failure"
    failure_code: Literal["DATA_REQUIREMENTS_NOT_MET"] = "DATA_REQUIREMENTS_NOT_MET"
    study_id: str
    requested_optimization: Literal["connection", "drilling_location"]
    missing_requirements: list[RealDataRequirement]
    """Deduplicated, sorted by enum value -- one entry per distinct
    `RealDataRequirement` category with at least one contributing gap,
    never one entry per individual field error (see `readiness.validation_errors`
    for that level of detail)."""
    message: str
    readiness: StudyReadinessReport


RealDataReadinessBoundaryResult = Annotated[
    Union[RealDataReadinessGranted, DataRequirementsNotMet], Field(discriminator="status"),
]
_boundary_result_adapter: TypeAdapter = TypeAdapter(RealDataReadinessBoundaryResult)


def parse_real_data_readiness_result_json(json_str: str) -> RealDataReadinessBoundaryResult:
    return _boundary_result_adapter.validate_json(json_str)


def enforce_real_data_readiness(
    package: StudyPackage, *, requested_optimization: Literal["connection", "drilling_location"],
) -> RealDataReadinessBoundaryResult:
    """The Phase 5 gate. Builds on `generate_readiness_report()`
    unchanged (no new validation logic) -- adds only the named-
    requirement enumeration and the discriminated `ready`/
    `DATA_REQUIREMENTS_NOT_MET` boundary result a real-data caller can
    act on directly, instead of re-deriving "is this actually ready" from
    the report's own boolean fields and error list itself.

    A SYNTHETIC package is always granted, matching
    `generate_readiness_report()`'s own OPT-006 policy (Workstream J's
    explicitly-synthetic demonstration purpose) -- this function does not
    change that policy, only exposes it through the same named-result
    shape a real package uses."""
    readiness = generate_readiness_report(package)
    permitted = (
        readiness.connection_optimization_permitted if requested_optimization == "connection"
        else readiness.drilling_location_optimization_permitted
    )
    if permitted:
        return RealDataReadinessGranted(
            study_id=package.manifest.study_id, requested_optimization=requested_optimization, readiness=readiness,
        )

    missing_requirements: set[RealDataRequirement] = set()
    for dataset in readiness.missing_datasets:
        if dataset == "network":
            missing_requirements.add(RealDataRequirement.NETWORK_TOPOLOGY)
        elif dataset == "geothermal_scenarios":
            missing_requirements.add(RealDataRequirement.GEOTHERMAL_SCENARIOS)
        elif dataset == "economics":
            missing_requirements.add(RealDataRequirement.ECONOMICS_AND_PLANNING)
    for error in readiness.validation_errors:
        requirement = _ERROR_CODE_TO_REQUIREMENT.get(error.error_code.value)
        if requirement is not None:
            missing_requirements.add(requirement)
    if readiness.unresolved_approvals or readiness.provisional_assumptions:
        missing_requirements.add(RealDataRequirement.APPROVAL_STATUS)
    if (
        requested_optimization == "drilling_location"
        and readiness.connection_optimization_permitted
        and not missing_requirements
    ):
        # connection-level requirements are all met but the package still
        # lacks any geothermal scenario -- the one drilling-specific gap.
        missing_requirements.add(RealDataRequirement.GEOTHERMAL_SCENARIOS)

    return DataRequirementsNotMet(
        study_id=package.manifest.study_id, requested_optimization=requested_optimization,
        missing_requirements=sorted(missing_requirements, key=lambda r: r.value),
        message=(
            f"study {package.manifest.study_id!r} does not meet the data requirements for "
            f"{requested_optimization!r} optimisation: {sorted(r.value for r in missing_requirements)}"
        ),
        readiness=readiness,
    )
