"""Fixed-DH-interface drilling-site optimization workflow.

## The corrected research question

"Given one predefined, fixed district-heating integration point, which
geothermal drilling site should be selected?" -- NOT "which network
attachment point should geothermal connect to?" (the question v1
`workflow/joint_optimization.py` and v2 `workflow/joint_workflow_v2.py` both
answer instead). `docs/decisions/ADR-003-fixed-interface-drilling-site-
optimization.md` records the full conceptual correction.

## Not workflow/joint_workflow_v2.py

That module (and the v1 layer it does not touch) remain completely
untouched -- this is an ADDITIVE, separately-named mode, never a
replacement. `README.md`'s "Alternative demonstrations" section documents
all four modes (v1, v2, research_experiment, this one) side by side.

## What this orchestrates (reuse only, module docstring precedent from
joint_workflow_v2.py)

`run_fixed_interface_site_optimization()` sequences: load + validate the
study package (data_contracts.joint_study.validate_joint_study_package(),
UNCHANGED) -> resolve the ONE fixed integration station from it
(data_contracts.fixed_interface.resolve_fixed_integration_station(), NEW,
the one validation this mode adds) -> verify the resource input's own
raw-hash binding (UNCHANGED) -> parse the primary PyDoublet input
(UNCHANGED) -> build the fixed synthetic blueprint and run its baseline
(UNCHANGED) -> generate site-origin-aware routes (network.site_routing,
UNCHANGED) -> enumerate ONLY drilling-site alternatives against the fixed
station (workflow.fixed_interface_enumeration, a thin wrapper around the
UNCHANGED workflow.joint_enumeration) -> evaluate each one, economics on
every feasible result (workflow.joint_evaluation, UNCHANGED) -> compute a
decision (decision.joint_policy, UNCHANGED). No new scientific computation
exists anywhere in this module -- it is sequencing, the one new station
validation, and audit/artifact bookkeeping only."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ..adapter import CouplingAssumptions
from ..contracts import PyDoubletCouplingFailure, PyDoubletCouplingResult, SourceProvenance
from ..data_contracts.fixed_interface import (
    FixedHeatIntegrationStation,
    FixedInterfaceValidationError,
    SiteCaseAssignment,
    resolve_fixed_integration_station,
    resolve_site_case_assignment,
)
from ..data_contracts.joint_study import (
    ActiveDimensionReport,
    JointStudyPackage,
    ResourceInputSourceKind,
    RouteScreeningStatus,
    SiteConnectionRoute,
    compute_active_dimensions,
    validate_joint_study_package,
)
from ..decision.joint_policy import JointDecisionResult, compute_alternative_objective_values, decide
from ..economics import EconomicAssumptions
from ..economics.costing import compute_baseline_economics
from ..economics.joint_costing import load_base_assumptions
from ..hashing import (
    SCIENTIFIC_NORMALIZATION_RULE_VERSION,
    canonical_raw_result_json_bytes,
    canonical_raw_result_sha256,
    normalize_for_scientific_hash,
)
from ..network import GateTolerances, GeothermalInjectionPolicy, build_default_blueprint, run_baseline_evaluation
from ..network.baseline import BaselineNetworkFailure, BaselineNetworkResult
from ..network.site_routing import generate_site_routes
from ..parsers.pydoublet_parser import parse_pydoublet_result
from .artifacts import ArtifactHashRecord
from .core import (
    WORKFLOW_CONTRACT_SCHEMA_VERSION,
    StageCallRecord,
    WorkflowAuditRecord,
    WorkflowWarningRecord,
    _build_blueprint_kwargs,
    _default_now,
    compute_run_id,
    compute_source_provenance_sha256,
)
from .fixed_interface_enumeration import enumerate_drilling_site_alternatives, possible_combination_count
from .joint_evaluation import JointAlternativeEvaluation, evaluate_compatible_alternatives

FIXED_INTERFACE_WORKFLOW_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

# ── artifact filenames (task's own §19 naming, adapted to this repo's
# established file-per-artifact convention) ─────────────────────────────────
PYDOUBLET_INPUT_FILENAME = "pydoublet_input.json"
CONFIG_SNAPSHOT_FILENAME = "config_snapshot.json"
JOINT_STUDY_SNAPSHOT_FILENAME = "joint_study_snapshot.json"
FIXED_INTERFACE_RESULT_FILENAME = "fixed_interface_result.json"
FIXED_STATION_FILENAME = "fixed_integration_station.json"
CANDIDATE_SITES_JSON_FILENAME = "candidate_sites.json"
CANDIDATE_SITES_CSV_FILENAME = "candidate_sites.csv"
GEOTHERMAL_RESULTS_FILENAME = "geothermal_results.json"
CANDIDATE_NETWORK_FEASIBILITY_FILENAME = "candidate_network_feasibility.json"
CANDIDATE_ECONOMICS_FILENAME = "candidate_economics.json"
DRILLING_SITE_RANKING_CSV_FILENAME = "drilling_site_ranking.csv"
DRILLING_SITE_RANKING_JSON_FILENAME = "drilling_site_ranking.json"
SITE_SENSITIVITY_RESULTS_CSV_FILENAME = "site_sensitivity_results.csv"
SITE_SENSITIVITY_RESULTS_JSON_FILENAME = "site_sensitivity_results.json"
COST_BREAKDOWN_CSV_FILENAME = "cost_breakdown.csv"
RESEARCH_FINDINGS_FILENAME = "research_findings.md"
AUDIT_FILENAME = "audit.json"
MANIFEST_FILENAME = "manifest.json"

_JSON_FILENAMES = frozenset((
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, JOINT_STUDY_SNAPSHOT_FILENAME, FIXED_INTERFACE_RESULT_FILENAME,
    FIXED_STATION_FILENAME, CANDIDATE_SITES_JSON_FILENAME, GEOTHERMAL_RESULTS_FILENAME,
    CANDIDATE_NETWORK_FEASIBILITY_FILENAME, CANDIDATE_ECONOMICS_FILENAME, DRILLING_SITE_RANKING_JSON_FILENAME,
    SITE_SENSITIVITY_RESULTS_JSON_FILENAME, AUDIT_FILENAME,
))
_CORE_SCIENTIFIC_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, JOINT_STUDY_SNAPSHOT_FILENAME, FIXED_INTERFACE_RESULT_FILENAME,
    AUDIT_FILENAME,
)
"""The minimum every bundle this module writes must contain -- declared
inputs, the calculated result (present for BOTH a completed run and a
stopped one, since `model_dump_json()` works on the whole discriminated
boundary type -- mirrors JointWorkflowV2's own JOINT_RESULT_FILENAME
precedent exactly), and the audit trail. `FIXED_STATION_FILENAME` is
deliberately NOT in this core set: a run that fails before station
resolution (e.g. JOINT_STUDY_PACKAGE_INVALID) never produces one, and that
is a normal, honest early-failure bundle, not a missing-file defect. A
completed run additionally publishes the full candidate/ranking/findings
set (write_fixed_interface_site_optimization_artifacts())."""


class FixedInterfaceWorkflowCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_count: int
    resource_scenario_count: int
    generated_route_count: int
    accepted_route_count: int
    possible_alternative_count: int
    compatible_alternative_count: int
    evaluated_alternative_count: int
    feasible_alternative_count: int
    reference_case_count: int
    """Exactly one per AVAILABLE site (task's own correction: the primary
    ranking has one row per drilling site, never per site×scenario)."""
    sensitivity_case_count: int
    """Every other scenario linked to a site -- evaluated through the
    identical pipeline but reported separately, never fed into `decide()`."""

    @model_validator(mode="after")
    def _validate(self) -> "FixedInterfaceWorkflowCounts":
        if self.evaluated_alternative_count != self.compatible_alternative_count:
            raise ValueError("evaluated_alternative_count must equal compatible_alternative_count")
        if self.feasible_alternative_count > self.evaluated_alternative_count:
            raise ValueError("feasible_alternative_count cannot exceed evaluated_alternative_count")
        if self.reference_case_count + self.sensitivity_case_count != self.evaluated_alternative_count:
            raise ValueError("reference_case_count + sensitivity_case_count must equal evaluated_alternative_count")
        return self


class FixedInterfaceSiteOptimizationResult(BaseModel):
    """A completed fixed-interface drilling-site-optimization run --
    meaning the fixed sequence finished, not that any site was
    recommended (zero feasible candidates is a valid, completed result,
    never a software error -- same rule as every other workflow layer)."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = FIXED_INTERFACE_WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    run_id: str
    package: JointStudyPackage
    fixed_integration_station: FixedHeatIntegrationStation
    case_assignment: SiteCaseAssignment
    """Which scenario is the declared deterministic reference case for
    each available site -- everything else linked to that site is a
    sensitivity case (data_contracts.fixed_interface.SiteCaseAssignment's
    own docstring). The decision below is computed ONLY over the
    reference-case subset of `alternatives`."""
    pydoublet_result: PyDoubletCouplingResult
    routes: list[SiteConnectionRoute]
    alternatives: list[JointAlternativeEvaluation]
    """BOTH reference-case and sensitivity-case evaluations, in one list
    (every downstream consumer that needs only one group filters via
    `case_assignment.is_reference_case()`) -- physics/economics evaluation
    itself never distinguishes the two (module docstring: reuse only)."""
    active_dimensions: ActiveDimensionReport
    decision: JointDecisionResult
    """Computed over REFERENCE-CASE alternatives only -- a sensitivity
    scenario can never appear in `pareto_shortlist_alternative_ids`/
    `ranked_alternative_groups`/`preferred_alternative_id` (task's own
    correction: the geological outcome is not a decision)."""
    counts: FixedInterfaceWorkflowCounts
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "FixedInterfaceSiteOptimizationResult":
        errors: list[str] = []
        if self.run_id != self.audit.run_id:
            errors.append("run_id does not match audit.run_id")
        offending = {a.identity.attachment_id for a in self.alternatives} - {self.fixed_integration_station.network_attachment_id}
        if offending:
            errors.append(
                f"every alternative must share the fixed station's own network_attachment_id "
                f"({self.fixed_integration_station.network_attachment_id!r}) -- found {sorted(offending)!r}"
            )
        decided_ids = set(self.decision.pareto_shortlist_alternative_ids) | {
            aid for group in self.decision.ranked_alternative_groups for aid in group
        }
        if self.decision.preferred_alternative_id:
            decided_ids.add(self.decision.preferred_alternative_id)
        non_reference_decided = {
            aid for aid in decided_ids
            if not self.case_assignment.is_reference_case(
                next(a.identity.surface_site_id for a in self.alternatives if a.identity.alternative_id == aid),
                next(a.identity.resource_scenario_id for a in self.alternatives if a.identity.alternative_id == aid),
            )
        }
        if non_reference_decided:
            errors.append(
                f"decision must never include a sensitivity-case alternative -- found {sorted(non_reference_decided)!r}"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self


class FixedInterfaceSiteOptimizationFailure(BaseModel):
    """A run that stopped before (or during) evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = FIXED_INTERFACE_WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"

    run_id: str
    failure_code: str
    stage: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "FixedInterfaceSiteOptimizationFailure":
        if self.run_id != self.audit.run_id:
            raise ValueError("run_id does not match audit.run_id")
        return self


FixedInterfaceWorkflowBoundaryResult = Annotated[
    Union[FixedInterfaceSiteOptimizationResult, FixedInterfaceSiteOptimizationFailure],
    Field(discriminator="status"),
]
_boundary_result_adapter: TypeAdapter = TypeAdapter(FixedInterfaceWorkflowBoundaryResult)


def parse_fixed_interface_workflow_result_json(json_str: str) -> FixedInterfaceWorkflowBoundaryResult:
    return _boundary_result_adapter.validate_json(json_str)


def is_fixed_interface_site_optimization_enabled(config: dict[str, Any]) -> bool:
    """The single, explicit config switch this module keys off -- absent
    from every other mode's own config, so canonical/v1/v2/research_
    experiment configs are completely unaffected."""
    return bool(config.get("fixed_interface_site_optimization", {}).get("enabled", False))


def _resolve_package_path(config: dict[str, Any], package_root: Path) -> Path:
    relative_path = config["fixed_interface_site_optimization"]["package_path"]
    resolved = (package_root / relative_path).resolve()
    root = package_root.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"fixed_interface_site_optimization.package_path escapes the package root: {resolved}")
    return resolved


@dataclass(frozen=True)
class _PackageLoadOutcome:
    run_id: str
    config_sha256_for_audit: str
    package_raw: dict[str, Any] | None
    package: "JointStudyPackage | None"
    error: Exception | None


def _load_and_hash_package(
    pydoublet_raw_result: dict[str, Any], config: dict[str, Any], *,
    source_provenance: SourceProvenance, package_root: Path,
) -> _PackageLoadOutcome:
    input_sha256 = canonical_raw_result_sha256(pydoublet_raw_result)
    config_sha256 = canonical_raw_result_sha256(config)
    source_provenance_sha256 = compute_source_provenance_sha256(source_provenance)
    try:
        package_path = _resolve_package_path(config, package_root)
        package_raw = json.loads(package_path.read_text())
        package = JointStudyPackage.model_validate(package_raw)
    except (KeyError, OSError, ValueError, ValidationError) as exc:
        run_id = compute_run_id(input_sha256, config_sha256, source_provenance_sha256, WORKFLOW_CONTRACT_SCHEMA_VERSION)
        return _PackageLoadOutcome(
            run_id=run_id, config_sha256_for_audit=config_sha256, package_raw=None, package=None, error=exc,
        )
    combined_config_sha256 = canonical_raw_result_sha256({"config": config, "joint_study_package": package_raw})
    run_id = compute_run_id(input_sha256, combined_config_sha256, source_provenance_sha256, WORKFLOW_CONTRACT_SCHEMA_VERSION)
    return _PackageLoadOutcome(
        run_id=run_id, config_sha256_for_audit=combined_config_sha256, package_raw=package_raw, package=package, error=None,
    )


def resolve_fixed_interface_workflow_run_id(
    pydoublet_raw_result: dict[str, Any], config: dict[str, Any], *,
    source_provenance: SourceProvenance, package_root: Path,
) -> tuple[str, dict[str, Any] | None]:
    """Public, cheap (no simulation) helper mirroring
    joint_workflow_v2.resolve_joint_workflow_v2_run_id() exactly, for the
    MCP tool layer's own pre-registry-lookup step."""
    outcome = _load_and_hash_package(
        pydoublet_raw_result, config, source_provenance=source_provenance, package_root=package_root,
    )
    return outcome.run_id, outcome.package_raw


def run_fixed_interface_site_optimization(
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    *,
    source_provenance: SourceProvenance,
    package_root: Path,
    expected_raw_sha256: str | None = None,
    now: Callable[[], datetime] = _default_now,
) -> FixedInterfaceWorkflowBoundaryResult:
    """The corrected sequence: package validation and fixed-station
    resolution BOTH happen before any simulation. Never raises for any of
    its named stopping conditions."""
    workflow_created_at = now()
    input_sha256 = canonical_raw_result_sha256(pydoublet_raw_result)
    source_provenance_sha256 = compute_source_provenance_sha256(source_provenance)

    stage_calls: list[StageCallRecord] = []
    warnings: list[WorkflowWarningRecord] = []

    # ── Stage 0: load + validate the study package ──
    outcome = _load_and_hash_package(
        pydoublet_raw_result, config, source_provenance=source_provenance, package_root=package_root,
    )
    run_id = outcome.run_id
    if outcome.error is not None:
        stage_calls.append(StageCallRecord(
            order=1, stage_name="load_and_validate_joint_study_package", status="failure",
            failure_code="JOINT_STUDY_PACKAGE_INVALID", message=str(outcome.error),
        ))
        return FixedInterfaceSiteOptimizationFailure(
            run_id=run_id, failure_code="JOINT_STUDY_PACKAGE_INVALID", stage="load_and_validate_joint_study_package",
            message=f"study package could not be loaded/parsed: {outcome.error}",
            details={"exception_message": str(outcome.error)},
            audit=_audit_stub(run_id, workflow_created_at, input_sha256, outcome.config_sha256_for_audit,
                               source_provenance, source_provenance_sha256, stage_calls, warnings, config),
            created_at=workflow_created_at,
        )
    package_raw = outcome.package_raw
    package = outcome.package
    combined_config_sha256 = outcome.config_sha256_for_audit

    def _audit() -> WorkflowAuditRecord:
        return _audit_stub(run_id, workflow_created_at, input_sha256, combined_config_sha256, source_provenance,
                            source_provenance_sha256, stage_calls, warnings, config)

    relationship_result = validate_joint_study_package(package)
    stage_calls.append(StageCallRecord(
        order=len(stage_calls) + 1, stage_name="validate_joint_study_package",
        status="success" if relationship_result.valid else "failure",
        failure_code=None if relationship_result.valid else "JOINT_STUDY_PACKAGE_INVALID",
        message=None if relationship_result.valid else "; ".join(
            f"{e.field_path}: {e.error_code.value}: {e.message}" for e in relationship_result.errors
        ),
    ))
    if not relationship_result.valid:
        return FixedInterfaceSiteOptimizationFailure(
            run_id=run_id, failure_code="JOINT_STUDY_PACKAGE_INVALID", stage="validate_joint_study_package",
            message=f"study package failed relationship validation ({len(relationship_result.errors)} error(s))",
            details={"errors": [json.loads(e.model_dump_json()) for e in relationship_result.errors]},
            audit=_audit(), created_at=workflow_created_at,
        )

    # ── Stage 0.5: resolve the ONE fixed DH integration station (the one
    # new validation this mode adds -- everything else below is reuse) ──
    fixed_interface_cfg = config.get("fixed_interface_site_optimization", {})
    station_or_error = resolve_fixed_integration_station(
        package,
        heat_exchanger_config_reference=fixed_interface_cfg.get("heat_exchanger_config_reference", "coupling_assumptions"),
        max_thermal_power_mw=fixed_interface_cfg.get("max_thermal_power_mw"),
        station_display_id=fixed_interface_cfg.get("station_display_id"),
    )
    if isinstance(station_or_error, FixedInterfaceValidationError):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="resolve_fixed_integration_station", status="failure",
            failure_code=station_or_error.error_code.value, message=station_or_error.message,
        ))
        return FixedInterfaceSiteOptimizationFailure(
            run_id=run_id, failure_code=station_or_error.error_code.value, stage="resolve_fixed_integration_station",
            message=station_or_error.message, audit=_audit(), created_at=workflow_created_at,
        )
    station: FixedHeatIntegrationStation = station_or_error
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="resolve_fixed_integration_station", status="success"))

    # ── Stage 0.6: resolve which scenario is the declared deterministic
    # reference case per site (the site/scenario correction) -- everything
    # else linked to a site is a sensitivity case, never a competing
    # drilling-site decision. ──
    case_assignment_or_error = resolve_site_case_assignment(
        package, fixed_interface_cfg.get("reference_scenario_by_site", {}),
    )
    if isinstance(case_assignment_or_error, FixedInterfaceValidationError):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="resolve_site_case_assignment", status="failure",
            failure_code=case_assignment_or_error.error_code.value, message=case_assignment_or_error.message,
        ))
        return FixedInterfaceSiteOptimizationFailure(
            run_id=run_id, failure_code=case_assignment_or_error.error_code.value, stage="resolve_site_case_assignment",
            message=case_assignment_or_error.message, audit=_audit(), created_at=workflow_created_at,
        )
    case_assignment: SiteCaseAssignment = case_assignment_or_error
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="resolve_site_case_assignment", status="success"))

    # ── Stage 1: resource-input hash binding + parse PyDoublet ──
    primary_inputs = [
        ri for ri in package.resource_inputs if ri.source_kind == ResourceInputSourceKind.PRIMARY_RUNTIME_INPUT
    ]
    if primary_inputs:
        primary_input = primary_inputs[0]
        if input_sha256 != primary_input.expected_raw_sha256:
            stage_calls.append(StageCallRecord(
                order=len(stage_calls) + 1, stage_name="verify_resource_input_hash", status="failure",
                failure_code="PYDOUBLET_RAW_HASH_MISMATCH",
                message=f"supplied input hash {input_sha256!r} != declared {primary_input.expected_raw_sha256!r}",
            ))
            return FixedInterfaceSiteOptimizationFailure(
                run_id=run_id, failure_code="PYDOUBLET_RAW_HASH_MISMATCH", stage="verify_resource_input_hash",
                message="the supplied --input does not match this study package's declared expected_raw_sha256",
                details={"expected": primary_input.expected_raw_sha256, "actual": input_sha256},
                audit=_audit(), created_at=workflow_created_at,
            )
        stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="verify_resource_input_hash", status="success"))

    pydoublet_boundary = parse_pydoublet_result(
        pydoublet_raw_result, source_provenance=source_provenance, expected_raw_sha256=expected_raw_sha256,
    )
    if isinstance(pydoublet_boundary, PyDoubletCouplingFailure):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="parse_pydoublet_result", status="failure",
            failure_code=pydoublet_boundary.failure_code.value, message=pydoublet_boundary.message,
        ))
        return FixedInterfaceSiteOptimizationFailure(
            run_id=run_id, failure_code=pydoublet_boundary.failure_code.value, stage="parse_pydoublet_result",
            message=f"parse_pydoublet_result failed: {pydoublet_boundary.message}",
            details={"upstream_details": pydoublet_boundary.details},
            audit=_audit(), created_at=workflow_created_at,
        )
    golden: PyDoubletCouplingResult = pydoublet_boundary
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="parse_pydoublet_result", status="success"))

    # ── Stage 2: blueprint + baseline (unchanged canonical construction) ──
    try:
        blueprint = build_default_blueprint(created_at=workflow_created_at, **_build_blueprint_kwargs(config))
    except (KeyError, ValueError, ValidationError) as exc:
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="build_blueprint", status="failure",
            failure_code="BLUEPRINT_CONSTRUCTION_FAILED", message=str(exc),
        ))
        return FixedInterfaceSiteOptimizationFailure(
            run_id=run_id, failure_code="BLUEPRINT_CONSTRUCTION_FAILED", stage="build_blueprint",
            message=f"blueprint construction raised {type(exc).__name__}: {exc}", details={"exception_message": str(exc)},
            audit=_audit(), created_at=workflow_created_at,
        )
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="build_blueprint", status="success"))

    tolerances = GateTolerances.from_config_dict(config)
    baseline_boundary = run_baseline_evaluation(blueprint, tolerances=tolerances)
    if isinstance(baseline_boundary, BaselineNetworkFailure):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="run_baseline_evaluation", status="failure",
            failure_code=baseline_boundary.failure_code.value, message=baseline_boundary.message,
        ))
        return FixedInterfaceSiteOptimizationFailure(
            run_id=run_id, failure_code="BASELINE_EVALUATION_FAILED", stage="run_baseline_evaluation",
            message=f"run_baseline_evaluation failed: {baseline_boundary.message}",
            details={"upstream_details": baseline_boundary.details},
            audit=_audit(), created_at=workflow_created_at,
        )
    baseline: BaselineNetworkResult = baseline_boundary
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="run_baseline_evaluation", status="success"))

    # ── Stage 3: economics base assumptions ──
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    base_assumptions = load_base_assumptions(package.economics, package_root)
    baseline_economics = compute_baseline_economics(baseline, assumptions=base_assumptions)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="load_base_assumptions", status="success"))

    # ── Stage 4: site-origin-aware routes (UNCHANGED -- routing_policy
    # already names only the fixed station's one attachment_id, enforced
    # by resolve_fixed_integration_station() above) ──
    routes = generate_site_routes(package.sites, package.network_attachments, package.routing_policy)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="generate_site_routes", status="success"))

    # ── Stage 5: drilling-site-only enumeration (fixed a=a0) ──
    identities = enumerate_drilling_site_alternatives(package, routes, station)
    possible_count = possible_combination_count(package, routes)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="enumerate_drilling_site_alternatives", status="success"))

    # ── Stage 6: evaluate every candidate drilling site (UNCHANGED evaluator) ──
    attachments_by_id = {a.attachment_id: a for a in package.network_attachments}
    routes_by_id = {r.route_id: r for r in routes}
    alternatives = evaluate_compatible_alternatives(
        identities, package, routes_by_id, attachments_by_id, golden, blueprint, baseline,
        baseline_economics, base_assumptions,
        coupling_assumptions=coupling_assumptions, injection_policy=injection_policy, tolerances=tolerances,
    )
    for alt in alternatives:
        if alt.feasible:
            stage_calls.append(StageCallRecord(
                order=len(stage_calls) + 1, stage_name=f"evaluate_alternative:{alt.identity.alternative_id}",
                status="success",
            ))
        else:
            stage_calls.append(StageCallRecord(
                order=len(stage_calls) + 1, stage_name=f"evaluate_alternative:{alt.identity.alternative_id}",
                status="failure", failure_code=alt.failure_code, message=alt.message,
            ))

    # ── Stage 7: decision -- REFERENCE-CASE alternatives only (task's own
    # correction: `decide()` itself is UNCHANGED, decision/joint_policy.py;
    # only the input list fed to it is now filtered). A sensitivity
    # scenario is evaluated (Stage 6, above) but can never enter the
    # primary ranking -- excluded here structurally, not by convention. ──
    is_reference = {
        a.identity.alternative_id: case_assignment.is_reference_case(
            a.identity.surface_site_id, a.identity.resource_scenario_id,
        )
        for a in alternatives
    }
    reference_alternatives = [a for a in alternatives if is_reference[a.identity.alternative_id]]
    sensitivity_alternatives = [a for a in alternatives if not is_reference[a.identity.alternative_id]]
    feasible = [a for a in alternatives if a.feasible]
    feasible_reference = [a for a in reference_alternatives if a.feasible]
    alt_values = [
        compute_alternative_objective_values(a.identity.alternative_id, a.candidate_result, a.economics, package.decision_policy.objectives)
        for a in feasible_reference
    ]
    decision = decide(alt_values, package.decision_policy)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="decide", status="success"))

    active_dimensions = compute_active_dimensions(package, routes)

    counts = FixedInterfaceWorkflowCounts(
        site_count=len(package.sites), resource_scenario_count=len(package.resource_scenarios),
        generated_route_count=len(routes),
        accepted_route_count=sum(1 for r in routes if r.screening_status == RouteScreeningStatus.ACCEPTED),
        possible_alternative_count=possible_count, compatible_alternative_count=len(identities),
        evaluated_alternative_count=len(alternatives), feasible_alternative_count=len(feasible),
        reference_case_count=len(reference_alternatives), sensitivity_case_count=len(sensitivity_alternatives),
    )

    return FixedInterfaceSiteOptimizationResult(
        run_id=run_id, package=package, fixed_integration_station=station, case_assignment=case_assignment,
        pydoublet_result=golden, routes=routes,
        alternatives=alternatives, active_dimensions=active_dimensions, decision=decision, counts=counts,
        audit=_audit(), created_at=workflow_created_at,
    )


def _audit_stub(
    run_id: str, created_at: datetime, input_sha256: str, config_sha256: str, source_provenance: SourceProvenance,
    source_provenance_sha256: str, stage_calls: list[StageCallRecord], warnings: list[WorkflowWarningRecord],
    config: dict[str, Any],
) -> WorkflowAuditRecord:
    return WorkflowAuditRecord(
        run_id=run_id, contract_schema_version=WORKFLOW_CONTRACT_SCHEMA_VERSION, created_at=created_at,
        input_sha256=input_sha256, config_sha256=config_sha256, source_provenance=source_provenance,
        source_provenance_sha256=source_provenance_sha256, stage_calls=list(stage_calls),
        coupling_assumptions=CouplingAssumptions.from_config_dict(config), gate_tolerances=GateTolerances.from_config_dict(config),
        injection_policy=GeothermalInjectionPolicy.from_config_dict(config),
        economic_assumptions=EconomicAssumptions.from_config_dict(config), warnings=list(warnings),
    )


# ── S17-style artifacts (task's own §19 named outputs) ──────────────────────

RESEARCH_FINDINGS_SYNTHETIC_DISCLAIMER = (
    "This is a SYNTHETIC demonstration: every candidate drilling site, geothermal scenario, and cost "
    "assumption here is explicitly invented for this prototype. It contains no real Wuppertal (or any "
    "other real place's) geological or network data, and must never be read as a real drilling-site "
    "recommendation, a validated economic result, or a statement of geological probability of success."
)


def render_candidate_sites_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = [
        {
            "site_id": site.site_id,
            "label": site.label,
            "availability_status": site.availability_status.value,
            "coordinate": json.loads(site.coordinate.model_dump_json()),
            "scenarios": sorted(
                scenario.scenario_id for scenario in result.package.resource_scenarios if scenario.site_id == site.site_id
            ),
            "distance_to_fixed_station_m": next(
                (r.paired_trench_length_m for r in result.routes
                 if r.site_id == site.site_id and r.screening_status.value == "accepted"),
                None,
            ),
        }
        for site in sorted(result.package.sites, key=lambda s: s.site_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def render_candidate_sites_csv(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=["site_id", "label", "availability_status", "target_depth_m", "distance_to_fixed_station_m"],
        lineterminator="\n",
    )
    writer.writeheader()
    scenarios_by_site: dict[str, list] = {}
    for scenario in result.package.resource_scenarios:
        scenarios_by_site.setdefault(scenario.site_id, []).append(scenario)
    routes_by_site = {r.site_id: r for r in result.routes if r.screening_status.value == "accepted"}
    for site in sorted(result.package.sites, key=lambda s: s.site_id):
        depths = [
            s.geological_metadata.target_depth_m for s in scenarios_by_site.get(site.site_id, [])
            if s.geological_metadata.target_depth_m is not None
        ]
        route = routes_by_site.get(site.site_id)
        writer.writerow({
            "site_id": site.site_id,
            "label": site.label,
            "availability_status": site.availability_status.value,
            "target_depth_m": f"{depths[0]:.2f}" if depths else "",
            "distance_to_fixed_station_m": f"{route.paired_trench_length_m:.3f}" if route else "",
        })
    return buffer.getvalue().encode("utf-8")


def _case_type(result: FixedInterfaceSiteOptimizationResult, alt: JointAlternativeEvaluation) -> str:
    return "reference" if result.case_assignment.is_reference_case(
        alt.identity.surface_site_id, alt.identity.resource_scenario_id,
    ) else "sensitivity"


def render_geothermal_results_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = [
        {
            "alternative_id": alt.identity.alternative_id,
            "surface_site_id": alt.identity.surface_site_id,
            "resource_scenario_id": alt.identity.resource_scenario_id,
            "case_type": _case_type(result, alt),
            "stage_reached": alt.stage_reached.value,
            "feasible": alt.feasible,
            "geothermal_coverage_fraction": (
                alt.candidate_result.geothermal_coverage_fraction if alt.candidate_result else None
            ),
        }
        for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def render_candidate_network_feasibility_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = [
        {
            "alternative_id": alt.identity.alternative_id,
            "surface_site_id": alt.identity.surface_site_id,
            "case_type": _case_type(result, alt),
            "feasible": alt.feasible,
            "stage_reached": alt.stage_reached.value,
            "failure_code": alt.failure_code,
            "message": alt.message,
            "network_entry_attachment_id": alt.identity.attachment_id,
        }
        for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def render_candidate_economics_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = [
        {
            "alternative_id": alt.identity.alternative_id,
            "surface_site_id": alt.identity.surface_site_id,
            "case_type": _case_type(result, alt),
            "feasible": alt.feasible,
            "annualised_cost_total_eur_per_a": (
                alt.economics.annualised_cost_total_eur_per_a if alt.economics else None
            ),
            "indicative_lcoh_eur_per_mwh": (
                alt.economics.indicative_lcoh_eur_per_kwh * 1000.0 if alt.economics else None
            ),
        }
        for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def _declared_geothermal_inputs(result: FixedInterfaceSiteOptimizationResult, scenario_id: str) -> dict[str, float]:
    """Reads the scenario's own DECLARED (input) geothermal figures --
    never a computed/simulated result -- so they remain available even
    for a site whose evaluation stopped before any physics ran (e.g. an
    unavailable site with no scenario evaluated at all). Reuses the SAME
    pure, already-published `apply_synthetic_derivation()` function
    `workflow.joint_evaluation.evaluate_alternative()` itself calls
    internally -- no new physics, just re-reading a declared input."""
    from ..data_contracts.joint_study_synthetic_v2 import apply_synthetic_derivation

    scenario = next(s for s in result.package.resource_scenarios if s.scenario_id == scenario_id)
    coupling_input = apply_synthetic_derivation(result.pydoublet_result, scenario.derivation)
    return {
        "producer_wellhead_temperature_c": coupling_input.producer_wellhead_temperature_c.value,
        "geothermal_brine_mass_flow_kg_s": coupling_input.geothermal_brine_mass_flow_kg_s.value,
        "raw_geothermal_thermal_power_mw": coupling_input.raw_geothermal_thermal_power_kw.value / 1000.0,
    }


def _rank_by_alternative_id(result: FixedInterfaceSiteOptimizationResult) -> dict[str, int]:
    """1-based rank per alternative_id, only under
    `primary_objective_ranking` (`ranked_alternative_groups` is empty
    under `pareto_only` -- DecisionPolicy's own documented distinction,
    decision/joint_policy.py). Ties within one group share the same rank
    number (DEC-011's own established convention)."""
    ranks: dict[str, int] = {}
    for index, group in enumerate(result.decision.ranked_alternative_groups):
        for alternative_id in group:
            ranks[alternative_id] = index + 1
    return ranks


def _drilling_site_ranking_rows(result: FixedInterfaceSiteOptimizationResult) -> list[dict]:
    """One row per DECLARED site (`result.package.sites`, sorted) -- never
    per site x scenario. An unavailable site's row is built from its own
    (rejected) route, never from a nonexistent alternative. An available
    site's row is built from its ONE reference-case alternative
    (`case_assignment.reference_scenario_id_by_site`), whatever its
    feasibility -- distance/depth/declared geothermal inputs are read from
    STATIC sources (routes, scenario metadata) that survive a downstream
    rejection, never from the (possibly-absent) `candidate_result`/
    `economics` fields (task's own §11 correction)."""
    ranks = _rank_by_alternative_id(result)
    routes_by_site = {r.site_id: r for r in result.routes}
    alternatives_by_key = {(a.identity.surface_site_id, a.identity.resource_scenario_id): a for a in result.alternatives}

    rows: list[dict] = []
    for site in sorted(result.package.sites, key=lambda s: s.site_id):
        route = routes_by_site.get(site.site_id)
        reference_scenario_id = result.case_assignment.reference_scenario_id_by_site.get(site.site_id)

        if reference_scenario_id is None:
            # Site not AVAILABLE (never entered case-assignment resolution
            # at all) -- report its own route-rejection reason, no
            # alternative was ever enumerated for it.
            rows.append({
                "rank": None, "site_id": site.site_id, "site_name": site.label, "reference_case_id": None,
                "target_depth_m": None, "distance_to_fixed_station_m": None,
                "geothermal_wellhead_temperature_c": None, "geothermal_mass_flow_kg_s": None,
                "geothermal_thermal_power_mw": None, "hx_feasible": None, "network_feasible": None,
                "overall_feasible": False, "drilling_capex_eur": None, "surface_connection_capex_eur": None,
                "hx_capex_eur": None, "pump_capex_eur": "not_modelled", "auxiliary_heat_cost_eur_per_a": None,
                "pumping_cost_eur_per_a": None, "annualised_total_cost_eur_per_a": None,
                "indicative_lcoh_eur_per_mwh": None, "in_pareto_shortlist": False,
                "failure_stage": "generate_site_routes",
                "failure_code": (route.rejection_code.value if route and route.rejection_code else "SITE_UNAVAILABLE"),
                "failure_message": (route.rejection_detail if route and route.rejection_detail
                                     else f"site {site.site_id!r} availability_status={site.availability_status.value!r}"),
            })
            continue

        alt = alternatives_by_key[(site.site_id, reference_scenario_id)]
        scenario = next(s for s in result.package.resource_scenarios if s.scenario_id == reference_scenario_id)
        declared = _declared_geothermal_inputs(result, reference_scenario_id)
        hx_feasible = alt.stage_reached.value != "CALCULATE_HX_COUPLING_BOUNDARY"
        network_feasible: bool | None
        if alt.stage_reached.value == "CALCULATE_HX_COUPLING_BOUNDARY":
            network_feasible = None  # network simulation never ran (physics before economics/network)
        else:
            network_feasible = alt.stage_reached.value == "ADDED_TO_DECISION_SET"
        econ = alt.economics

        rows.append({
            "rank": ranks.get(alt.identity.alternative_id),
            "site_id": site.site_id, "site_name": site.label, "reference_case_id": reference_scenario_id,
            "target_depth_m": scenario.geological_metadata.target_depth_m,
            "distance_to_fixed_station_m": route.paired_trench_length_m if route else None,
            "geothermal_wellhead_temperature_c": declared["producer_wellhead_temperature_c"],
            "geothermal_mass_flow_kg_s": declared["geothermal_brine_mass_flow_kg_s"],
            "geothermal_thermal_power_mw": declared["raw_geothermal_thermal_power_mw"],
            "hx_feasible": hx_feasible, "network_feasible": network_feasible, "overall_feasible": alt.feasible,
            "drilling_capex_eur": econ.capex_doublet_eur if econ else None,
            "surface_connection_capex_eur": econ.capex_connection_pipes_eur if econ else None,
            "hx_capex_eur": econ.capex_heat_exchanger_eur if econ else None,
            "pump_capex_eur": "not_modelled",
            "auxiliary_heat_cost_eur_per_a": econ.opex_auxiliary_heat_eur_per_a if econ else None,
            "pumping_cost_eur_per_a": (
                econ.opex_electricity_doublet_pump_eur_per_a + econ.opex_electricity_dh_pumping_eur_per_a
                if econ else None
            ),
            "annualised_total_cost_eur_per_a": econ.annualised_cost_total_eur_per_a if econ else None,
            "indicative_lcoh_eur_per_mwh": econ.indicative_lcoh_eur_per_kwh * 1000.0 if econ else None,
            "in_pareto_shortlist": alt.identity.alternative_id in result.decision.pareto_shortlist_alternative_ids,
            "failure_stage": None if alt.feasible else alt.stage_reached.value,
            "failure_code": alt.failure_code,
            "failure_message": None if alt.feasible else alt.message,
        })
    return rows


def render_drilling_site_ranking_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = {
        "fixed_dh_integration_station_id": result.fixed_integration_station.station_id,
        "network_attachment_id": result.fixed_integration_station.network_attachment_id,
        "sites": _drilling_site_ranking_rows(result),
        "decision_policy_mode": result.decision.mode.value,
    }
    return (json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n").encode("utf-8")


def render_drilling_site_ranking_csv(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    """Strict acceptance criterion (task §27): one row corresponds to ONE
    DRILLING SITE, never one site-scenario combination."""
    import csv
    import io

    fieldnames = [
        "rank", "site_id", "site_name", "reference_case_id", "target_depth_m", "distance_to_fixed_station_m",
        "geothermal_wellhead_temperature_c", "geothermal_mass_flow_kg_s", "geothermal_thermal_power_mw",
        "hx_feasible", "network_feasible", "overall_feasible", "drilling_capex_eur", "surface_connection_capex_eur",
        "hx_capex_eur", "pump_capex_eur", "auxiliary_heat_cost_eur_per_a", "pumping_cost_eur_per_a",
        "annualised_total_cost_eur_per_a", "indicative_lcoh_eur_per_mwh", "in_pareto_shortlist",
        "failure_stage", "failure_code", "failure_message",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in _drilling_site_ranking_rows(result):
        formatted = {}
        for key in fieldnames:
            value = row.get(key)
            if value is None:
                formatted[key] = ""
            elif isinstance(value, float):
                formatted[key] = f"{value:.6f}"
            else:
                formatted[key] = value
        writer.writerow(formatted)
    return buffer.getvalue().encode("utf-8")


def render_site_sensitivity_results_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = _site_sensitivity_rows(result)
    return (json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n").encode("utf-8")


def _site_sensitivity_rows(result: FixedInterfaceSiteOptimizationResult) -> list[dict]:
    reference_by_site = result.case_assignment.reference_scenario_id_by_site
    alternatives_by_key = {(a.identity.surface_site_id, a.identity.resource_scenario_id): a for a in result.alternatives}
    rows: list[dict] = []
    for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id):
        if result.case_assignment.is_reference_case(alt.identity.surface_site_id, alt.identity.resource_scenario_id):
            continue
        declared = _declared_geothermal_inputs(result, alt.identity.resource_scenario_id)
        reference_alt = alternatives_by_key.get((alt.identity.surface_site_id, reference_by_site.get(alt.identity.surface_site_id)))
        difference: float | str | None = None
        if alt.economics is not None and reference_alt is not None and reference_alt.economics is not None:
            difference = alt.economics.indicative_lcoh_eur_per_kwh * 1000.0 - reference_alt.economics.indicative_lcoh_eur_per_kwh * 1000.0
        elif alt.economics is not None or (reference_alt is not None and reference_alt.economics is not None):
            difference = "not_comparable"
        rows.append({
            "site_id": alt.identity.surface_site_id,
            "scenario_id": alt.identity.resource_scenario_id,
            "scenario_type": "sensitivity",
            "reference_or_sensitivity": "sensitivity",
            "temperature_c": declared["producer_wellhead_temperature_c"],
            "flow_kg_s": declared["geothermal_brine_mass_flow_kg_s"],
            "thermal_power_mw": declared["raw_geothermal_thermal_power_mw"],
            "hx_feasible": alt.stage_reached.value != "CALCULATE_HX_COUPLING_BOUNDARY",
            "network_feasible": (
                None if alt.stage_reached.value == "CALCULATE_HX_COUPLING_BOUNDARY"
                else alt.stage_reached.value == "ADDED_TO_DECISION_SET"
            ),
            "annualised_total_cost_eur_per_a": alt.economics.annualised_cost_total_eur_per_a if alt.economics else None,
            "indicative_lcoh_eur_per_mwh": alt.economics.indicative_lcoh_eur_per_kwh * 1000.0 if alt.economics else None,
            "difference_from_site_reference_eur_per_mwh": difference,
        })
    return rows


def render_site_sensitivity_results_csv(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    import csv
    import io

    fieldnames = [
        "site_id", "scenario_id", "scenario_type", "reference_or_sensitivity", "temperature_c", "flow_kg_s",
        "thermal_power_mw", "hx_feasible", "network_feasible", "annualised_total_cost_eur_per_a",
        "indicative_lcoh_eur_per_mwh", "difference_from_site_reference_eur_per_mwh",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in _site_sensitivity_rows(result):
        formatted = {}
        for key in fieldnames:
            value = row.get(key)
            if value is None:
                formatted[key] = ""
            elif isinstance(value, float):
                formatted[key] = f"{value:.6f}"
            else:
                formatted[key] = value
        writer.writerow(formatted)
    return buffer.getvalue().encode("utf-8")


def render_cost_breakdown_csv(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    """One row per site's own REFERENCE case, breaking out every already-
    computed `CandidateEconomicResult` component (economics/costing.py) --
    no new cost formula. `pump_capex_eur`/`station_thermal_power_capacity_mw`
    are explicitly `not_modelled`/absent rather than fabricated (task §10:
    'do not fabricate cost components that do not exist')."""
    import csv
    import io

    fieldnames = [
        "site_id", "reference_case_id", "overall_feasible", "capex_doublet_eur", "capex_heat_exchanger_eur",
        "capex_connection_pipes_eur", "pump_capex_eur", "annuity_doublet_eur_per_a",
        "annuity_heat_exchanger_eur_per_a", "annuity_connection_pipes_eur_per_a", "annuity_capital_eur_per_a",
        "opex_fixed_eur_per_a", "opex_electricity_doublet_pump_eur_per_a", "opex_electricity_dh_pumping_eur_per_a",
        "opex_auxiliary_heat_eur_per_a", "annualised_cost_total_eur_per_a", "indicative_lcoh_eur_per_mwh",
        "station_thermal_power_capacity_mw",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    alternatives_by_key = {(a.identity.surface_site_id, a.identity.resource_scenario_id): a for a in result.alternatives}
    for site_id in sorted(result.case_assignment.reference_scenario_id_by_site):
        scenario_id = result.case_assignment.reference_scenario_id_by_site[site_id]
        alt = alternatives_by_key[(site_id, scenario_id)]
        econ = alt.economics
        row = {
            "site_id": site_id, "reference_case_id": scenario_id, "overall_feasible": alt.feasible,
            "pump_capex_eur": "not_modelled",
            "station_thermal_power_capacity_mw": (
                result.fixed_integration_station.max_thermal_power_mw
                if result.fixed_integration_station.max_thermal_power_mw is not None else "not_modelled"
            ),
        }
        for key in (
            "capex_doublet_eur", "capex_heat_exchanger_eur", "capex_connection_pipes_eur",
            "annuity_doublet_eur_per_a", "annuity_heat_exchanger_eur_per_a", "annuity_connection_pipes_eur_per_a",
            "annuity_capital_eur_per_a", "opex_fixed_eur_per_a", "opex_electricity_doublet_pump_eur_per_a",
            "opex_electricity_dh_pumping_eur_per_a", "opex_auxiliary_heat_eur_per_a",
            "annualised_cost_total_eur_per_a",
        ):
            value = getattr(econ, key) if econ else None
            row[key] = f"{value:.6f}" if value is not None else "not_evaluated"
        row["indicative_lcoh_eur_per_mwh"] = (
            f"{econ.indicative_lcoh_eur_per_kwh * 1000.0:.6f}" if econ else "not_evaluated"
        )
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def render_fixed_integration_station_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    return (result.fixed_integration_station.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_research_findings_markdown(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    """Task §21's own 9-section structure: Experiment boundary / Fixed DH
    integration station / Drilling sites evaluated / Reference case per
    site / Technical feasibility / Economic comparison / Preferred
    drilling site / Sensitivity scenarios / Limitations. Primary ranking
    and sensitivity cases are NEVER mixed into the same table (task §21's
    own explicit instruction)."""
    station = result.fixed_integration_station
    rows = _drilling_site_ranking_rows(result)
    sensitivity_rows = _site_sensitivity_rows(result)
    lines: list[str] = []

    lines.append("# R3-CHAIN fixed-DH-interface drilling-site optimization")
    lines.append("")
    lines.append(RESEARCH_FINDINGS_SYNTHETIC_DISCLAIMER)
    lines.append("")

    lines.append("## 1. Experiment boundary")
    lines.append("")
    lines.append(
        "We choose the drilling site, not the geological outcome. For each candidate drilling site, this "
        "deterministic prototype evaluates one declared reference geothermal case, transfers the resulting "
        "geothermal heat to the same fixed district-heating integration station, checks heat-exchanger and "
        "network feasibility, and compares system-level economics. Additional geothermal scenarios are "
        "retained as sensitivity cases rather than competing drilling decisions."
    )
    lines.append("")

    lines.append("## 2. Fixed DH integration station")
    lines.append("")
    lines.append(
        f"The heat-integration station is a predefined boundary condition of this experiment, identified "
        f"here as `{station.station_id}`. Its pandapipes supply junction is `{station.network_entry_supply_junction_id}` "
        f"and its return junction is `{station.network_entry_return_junction_id}`. These junctions are not "
        "optimized. Only the geothermal drilling-site location varies."
    )
    lines.append(f"Declared thermal-power capacity ceiling: "
                  f"{station.max_thermal_power_mw if station.max_thermal_power_mw is not None else 'not modelled (unconstrained beyond the per-candidate HX/network gates)'}.")
    lines.append(f"Heat-pump-assisted integration: {'configured' if station.heat_pump_config_reference else 'not modelled -- direct heat exchange only'}.")
    lines.append("")

    lines.append("## 3. Drilling sites evaluated")
    lines.append("")
    c = result.counts
    lines.append(
        f"Candidate drilling sites declared: {c.site_count} &middot; resource scenarios declared: "
        f"{c.resource_scenario_count} &middot; reference cases (one per available site): {c.reference_case_count} "
        f"&middot; sensitivity cases: {c.sensitivity_case_count}."
    )
    lines.append("")
    lines.append("| Site | Availability | Target depth (m, synthetic) | Distance to fixed station (m) |")
    lines.append("|---|---|---:|---:|")
    for row in rows:
        depth = f"{row['target_depth_m']:.0f}" if row["target_depth_m"] is not None else "n/a"
        distance = f"{row['distance_to_fixed_station_m']:.1f}" if row["distance_to_fixed_station_m"] is not None else "n/a"
        availability = "excluded" if row["reference_case_id"] is None else "available"
        lines.append(f"| `{row['site_id']}` | {availability} | {depth} | {distance} |")
    lines.append("")
    lines.append(
        "Target depth is currently METADATA ONLY: no cost function in this prototype consumes "
        "`target_depth_m` -- drilling CAPEX is a declared, per-scenario input "
        "(`SiteEconomicInputs.doublet_capex_eur`), not derived from depth. A deeper site does not "
        "currently cost more for this reason alone."
    )
    lines.append("")

    lines.append("## 4. Declared reference case per site")
    lines.append("")
    lines.append(
        "Exactly one declared deterministic reference case is used per available site for the primary "
        "ranking below -- never the site's own \"best\" or \"golden\" scenario by convention, but an "
        "explicitly configured mapping (`fixed_interface_site_optimization.reference_scenario_by_site`)."
    )
    lines.append("")
    lines.append("| Site | Reference case |")
    lines.append("|---|---|")
    for row in rows:
        if row["reference_case_id"] is not None:
            lines.append(f"| `{row['site_id']}` | `{row['reference_case_id']}` |")
    lines.append("")

    lines.append("## 5. Technical feasibility")
    lines.append("")
    lines.append("| Site | HX feasible | Network feasible | Overall feasible | Failure stage | Failure code |")
    lines.append("|---|:---:|:---:|:---:|---|---|")
    for row in rows:
        def _fmt_bool(v: object) -> str:
            return "n/a" if v is None else ("yes" if v else "no")
        lines.append(
            f"| `{row['site_id']}` | {_fmt_bool(row['hx_feasible'])} | {_fmt_bool(row['network_feasible'])} "
            f"| {_fmt_bool(row['overall_feasible'])} | {row['failure_stage'] or ''} | {row['failure_code'] or ''} |"
        )
    lines.append("")
    lines.append(
        "Physics precedes economics throughout: an HX-infeasible site is never simulated in pandapipes, "
        "and a network-infeasible site never has its system economics computed -- both remain marked "
        "`overall_feasible: false` with a stage-tagged reason code, never converted into an expensive "
        "candidate (this project's own long-standing rule)."
    )
    lines.append("")
    lines.append(
        "Load cases: this fixed-interface mode currently evaluates ONE prescribed design operating "
        "condition (the configured DH supply/return temperatures and consumer demand) -- it does NOT yet "
        "evaluate peak/shoulder/base load states. `workflow/load_state_evaluation.py` exists and is reused "
        "by the separate research-experiment layer, but is not yet connected to this mode; "
        "`site_load_case_feasibility.csv` is therefore not produced here."
    )
    lines.append("")
    lines.append(
        "Geothermal coverage occasionally caps at 0.99 (99%) rather than 1.00 for a supply-surplus site: "
        "this is `coupling_assumptions.minimum_auxiliary_circulation_fraction=0.01`, an existing, documented "
        "numerical-stability margin (config/demo_assumptions.json's own note; network/candidate.py's module "
        "docstring, section \"Curtailment\") that keeps the main circulation pump's solved flow clear of a "
        "pandapipes solver zero-tolerance check -- not an economic policy and not accidental."
    )
    lines.append("")

    lines.append("## 6. Economic comparison")
    lines.append("")
    lines.append(
        "| Site | Annualised total cost (EUR/a) | Indicative LCOH (EUR/MWh) | Rank | In Pareto shortlist |"
    )
    lines.append("|---|---:|---:|:---:|:---:|")
    for row in rows:
        cost = f"{row['annualised_total_cost_eur_per_a']:,.2f}" if row["annualised_total_cost_eur_per_a"] is not None else "not_evaluated"
        lcoh = f"{row['indicative_lcoh_eur_per_mwh']:.4f}" if row["indicative_lcoh_eur_per_mwh"] is not None else "not_evaluated"
        rank = str(row["rank"]) if row["rank"] is not None else ""
        shortlist = "yes" if row["in_pareto_shortlist"] else "no"
        lines.append(f"| `{row['site_id']}` | {cost} | {lcoh} | {rank} | {shortlist} |")
    lines.append("")
    lines.append(
        "Full component-level cost decomposition (doublet, heat-exchanger, connection-pipe CAPEX; fixed "
        "and electricity OPEX; auxiliary heat cost) is published separately in `cost_breakdown.csv` -- "
        "`pump_capex_eur` is reported as `not_modelled` there (this prototype models pump OPEX/electricity "
        "only, never a pump capital cost)."
    )
    lines.append("")

    lines.append("## 7. Preferred drilling site")
    lines.append("")
    if result.decision.mode.value == "pareto_only":
        lines.append(
            f"Decision policy mode: `pareto_only` -- {len(result.decision.pareto_shortlist_alternative_ids)} "
            "non-dominated candidate drilling site(s) among the reference cases, no single preferred site "
            "under this policy."
        )
        for alt_id in result.decision.pareto_shortlist_alternative_ids:
            site_id = next(a.identity.surface_site_id for a in result.alternatives if a.identity.alternative_id == alt_id)
            lines.append(f"- `{site_id}`: {result.decision.pareto_explanations.get(alt_id, '')}")
    else:
        if result.decision.preferred_alternative_id:
            preferred = next(
                a for a in result.alternatives if a.identity.alternative_id == result.decision.preferred_alternative_id
            )
            preferred_row = next(r for r in rows if r["site_id"] == preferred.identity.surface_site_id)
            lines.append(f"**Preferred drilling site: `{preferred.identity.surface_site_id}`**")
            lines.append("")
            lines.append("Reason:")
            lines.append(f"- evaluated using its own declared reference case `{preferred.identity.resource_scenario_id}`,")
            lines.append("- the geothermal source passes direct heat-exchanger compatibility,")
            lines.append(f"- heat is delivered through the fixed integration station `{station.station_id}`,")
            lines.append("- required district-heating network feasibility checks pass,")
            lines.append(f"- surface transmission distance to the station is {preferred_row['distance_to_fixed_station_m']:.1f} m,")
            lines.append(
                f"- annualised system cost ({preferred_row['annualised_total_cost_eur_per_a']:,.2f} EUR/a) is lower "
                "than other technically feasible reference-case sites,"
            )
            lines.append("- therefore it ranks first under the current synthetic deterministic assumptions.")
            lines.append(f"\n{result.decision.synthetic_cost_sensitivity_caveat}")
            lines.append(
                "\nNote: the caveat above concerns COST-ASSUMPTION sensitivity (a different synthetic price "
                "set could change the ranking) -- it is distinct from the GEOLOGICAL-SCENARIO sensitivity "
                "cases in section 8 below, which test whether the same site's ranking is robust to a "
                "different geological outcome at that same site."
            )
        else:
            lines.append("No unique preferred drilling site -- rank 1 contains more than one materially tied "
                          "candidate among the reference cases.")
    lines.append("")

    lines.append("## 8. Sensitivity scenarios")
    lines.append("")
    if sensitivity_rows:
        lines.append("| Site | Scenario | LCOH (EUR/MWh) | Difference from site reference (EUR/MWh) |")
        lines.append("|---|---|---:|---:|")
        for row in sensitivity_rows:
            lcoh = f"{row['indicative_lcoh_eur_per_mwh']:.4f}" if row["indicative_lcoh_eur_per_mwh"] is not None else "not_evaluated"
            diff = row["difference_from_site_reference_eur_per_mwh"]
            diff_text = f"{diff:.4f}" if isinstance(diff, float) else (diff or "")
            lines.append(f"| `{row['site_id']}` | `{row['scenario_id']}` | {lcoh} | {diff_text} |")
        lines.append("")
        lines.append(
            "These sensitivity cases demonstrate that a site's ranking may not be robust to geological "
            "uncertainty at that same site -- they are never fed into the primary ranking or decision above "
            "(see `site_sensitivity_results.csv`/`.json` for the full detail)."
        )
    else:
        lines.append("No sensitivity scenarios are declared beyond each site's own reference case in this fixture.")
    lines.append("")

    lines.append("## 9. Limitations")
    lines.append("")
    lines.append("- No real Wuppertal (or any other real place's) drilling-site recommendation.")
    lines.append("- No Fündigkeitsrisiko / geological probability-of-success model. `GeothermalResourceScenario` "
                  "already carries an unused `probability: float | None` field for future work -- see "
                  "`docs/decisions/ADR-004-site-decision-vs-geological-state.md`.")
    lines.append("- No full network operating-envelope optimization -- prescribed DH supply/return "
                  "temperatures remain fixed inputs.")
    lines.append("- No heat-pump-assisted or hybrid integration mode is evaluated -- only direct heat "
                  "exchange, per the fixed station's own `heat_pump_config_reference: null`.")
    lines.append("- No multi-load-state (peak/shoulder/base) evaluation in this mode (section 5 above).")
    lines.append("- Target drilling depth is metadata only and does not currently drive any cost component "
                  "(section 3 above).")
    lines.append("- Synthetic/demo economics throughout -- CAPEX/OPEX figures are illustrative assumptions, "
                  "not commercial estimates.")
    lines.append("")

    return ("\n".join(lines) + "\n").encode("utf-8")


class FixedInterfaceWorkflowManifestRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = "1.0.0"
    scientific_normalization_rule_version: str = SCIENTIFIC_NORMALIZATION_RULE_VERSION
    run_type: Literal["fixed_interface_site_optimization"] = "fixed_interface_site_optimization"
    """MCP-style run-type discriminator (mirrors JointWorkflowV2ManifestRecord's
    own precedent) -- lets mcp_server/registry.py's rehydration decide, from
    the manifest alone, which typed result parser/summarizer to use."""
    run_id: str
    created_at: datetime
    files: dict[str, ArtifactHashRecord]
    bundle_scientific_sha256: str

    @model_validator(mode="after")
    def _validate(self) -> "FixedInterfaceWorkflowManifestRecord":
        errors: list[str] = []
        if not set(_CORE_SCIENTIFIC_FILENAMES) <= set(self.files.keys()):
            errors.append(f"files must contain at least {sorted(_CORE_SCIENTIFIC_FILENAMES)}, got {sorted(self.files.keys())}")
        if MANIFEST_FILENAME in self.files:
            errors.append("manifest.json must never hash itself")
        for filename in self.files:
            if "/" in filename or "\\" in filename or filename.startswith("."):
                errors.append(f"files[{filename!r}] must be a plain relative filename, not a path")
        expected_bundle_hash = canonical_raw_result_sha256(
            {filename: record.scientific_sha256 for filename, record in sorted(self.files.items())}
        )
        if self.bundle_scientific_sha256 != expected_bundle_hash:
            errors.append("bundle_scientific_sha256 does not match recomputation")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _hash_record_for_json_bytes(data: bytes) -> ArtifactHashRecord:
    parsed = json.loads(data)
    normalized = normalize_for_scientific_hash(parsed)
    scientific_hash = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()
    byte_hash = hashlib.sha256(data).hexdigest()
    return ArtifactHashRecord(byte_sha256=byte_hash, scientific_sha256=scientific_hash)


def _hash_record_for_plain_bytes(data: bytes) -> ArtifactHashRecord:
    byte_hash = hashlib.sha256(data).hexdigest()
    return ArtifactHashRecord(byte_sha256=byte_hash, scientific_sha256=byte_hash)


def write_fixed_interface_site_optimization_artifacts(
    result: FixedInterfaceWorkflowBoundaryResult,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    package_raw: dict[str, Any],
    output_dir: Path,
) -> FixedInterfaceWorkflowManifestRecord:
    hash_records: dict[str, ArtifactHashRecord] = {}

    pydoublet_input_bytes = canonical_raw_result_json_bytes(pydoublet_raw_result)
    (output_dir / PYDOUBLET_INPUT_FILENAME).write_bytes(pydoublet_input_bytes)
    hash_records[PYDOUBLET_INPUT_FILENAME] = _hash_record_for_json_bytes(pydoublet_input_bytes)

    config_snapshot_bytes = canonical_raw_result_json_bytes(config)
    (output_dir / CONFIG_SNAPSHOT_FILENAME).write_bytes(config_snapshot_bytes)
    hash_records[CONFIG_SNAPSHOT_FILENAME] = _hash_record_for_json_bytes(config_snapshot_bytes)

    package_snapshot_bytes = canonical_raw_result_json_bytes(package_raw)
    (output_dir / JOINT_STUDY_SNAPSHOT_FILENAME).write_bytes(package_snapshot_bytes)
    hash_records[JOINT_STUDY_SNAPSHOT_FILENAME] = _hash_record_for_json_bytes(package_snapshot_bytes)

    result_bytes = result.model_dump_json(indent=2).encode("utf-8")
    (output_dir / FIXED_INTERFACE_RESULT_FILENAME).write_bytes(result_bytes)
    hash_records[FIXED_INTERFACE_RESULT_FILENAME] = _hash_record_for_json_bytes(result_bytes)

    audit_bytes = result.audit.model_dump_json(indent=2).encode("utf-8")
    (output_dir / AUDIT_FILENAME).write_bytes(audit_bytes)
    hash_records[AUDIT_FILENAME] = _hash_record_for_json_bytes(audit_bytes)

    if isinstance(result, FixedInterfaceSiteOptimizationResult):
        station_bytes = render_fixed_integration_station_json(result)
        (output_dir / FIXED_STATION_FILENAME).write_bytes(station_bytes)
        hash_records[FIXED_STATION_FILENAME] = _hash_record_for_json_bytes(station_bytes)

        extra: dict[str, bytes] = {
            CANDIDATE_SITES_JSON_FILENAME: render_candidate_sites_json(result),
            CANDIDATE_SITES_CSV_FILENAME: render_candidate_sites_csv(result),
            GEOTHERMAL_RESULTS_FILENAME: render_geothermal_results_json(result),
            CANDIDATE_NETWORK_FEASIBILITY_FILENAME: render_candidate_network_feasibility_json(result),
            CANDIDATE_ECONOMICS_FILENAME: render_candidate_economics_json(result),
            DRILLING_SITE_RANKING_JSON_FILENAME: render_drilling_site_ranking_json(result),
            DRILLING_SITE_RANKING_CSV_FILENAME: render_drilling_site_ranking_csv(result),
            SITE_SENSITIVITY_RESULTS_JSON_FILENAME: render_site_sensitivity_results_json(result),
            SITE_SENSITIVITY_RESULTS_CSV_FILENAME: render_site_sensitivity_results_csv(result),
            COST_BREAKDOWN_CSV_FILENAME: render_cost_breakdown_csv(result),
            RESEARCH_FINDINGS_FILENAME: render_research_findings_markdown(result),
        }
        for filename, data in extra.items():
            (output_dir / filename).write_bytes(data)
            hash_records[filename] = (
                _hash_record_for_json_bytes(data) if filename in _JSON_FILENAMES else _hash_record_for_plain_bytes(data)
            )
    else:
        # A failure that already reached station resolution still gets an
        # honest fixed_integration_station.json omitted (never resolved) --
        # nothing to write; the failure's own audit/message names the stage.
        pass

    bundle_scientific_sha256 = canonical_raw_result_sha256(
        {filename: record.scientific_sha256 for filename, record in sorted(hash_records.items())}
    )
    manifest = FixedInterfaceWorkflowManifestRecord(
        run_id=result.run_id, created_at=datetime.now(timezone.utc), files=hash_records,
        bundle_scientific_sha256=bundle_scientific_sha256,
    )
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest
