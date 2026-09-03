"""Real-data readiness reporting (DATA-009, OPT-006's real-mode safeguard).

`generate_readiness_report()` is the single source of truth for whether
connection-optimisation or drilling-location-optimisation may proceed
against a given study package. Both permission flags default to `False`
and are set `True` only under conditions checked explicitly below --
never inferred from the mere presence of data.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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
