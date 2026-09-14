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
    resolve_fixed_integration_station,
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
RESEARCH_FINDINGS_FILENAME = "research_findings.md"
AUDIT_FILENAME = "audit.json"
MANIFEST_FILENAME = "manifest.json"

_JSON_FILENAMES = frozenset((
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, JOINT_STUDY_SNAPSHOT_FILENAME, FIXED_INTERFACE_RESULT_FILENAME,
    FIXED_STATION_FILENAME, CANDIDATE_SITES_JSON_FILENAME, GEOTHERMAL_RESULTS_FILENAME,
    CANDIDATE_NETWORK_FEASIBILITY_FILENAME, CANDIDATE_ECONOMICS_FILENAME, DRILLING_SITE_RANKING_JSON_FILENAME,
    AUDIT_FILENAME,
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

    @model_validator(mode="after")
    def _validate(self) -> "FixedInterfaceWorkflowCounts":
        if self.evaluated_alternative_count != self.compatible_alternative_count:
            raise ValueError("evaluated_alternative_count must equal compatible_alternative_count")
        if self.feasible_alternative_count > self.evaluated_alternative_count:
            raise ValueError("feasible_alternative_count cannot exceed evaluated_alternative_count")
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
    pydoublet_result: PyDoubletCouplingResult
    routes: list[SiteConnectionRoute]
    alternatives: list[JointAlternativeEvaluation]
    active_dimensions: ActiveDimensionReport
    decision: JointDecisionResult
    counts: FixedInterfaceWorkflowCounts
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "FixedInterfaceSiteOptimizationResult":
        errors: list[str] = []
        if self.run_id != self.audit.run_id:
            errors.append("run_id does not match audit.run_id")
        offending = {a.identity.attachment_id for a in self.alternatives} - {self.fixed_integration_station.station_id}
        if offending:
            errors.append(
                f"every alternative must share the fixed station's own attachment_id "
                f"({self.fixed_integration_station.station_id!r}) -- found {sorted(offending)!r}"
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

    # ── Stage 7: decision (UNCHANGED) ──
    feasible = [a for a in alternatives if a.feasible]
    alt_values = [
        compute_alternative_objective_values(a.identity.alternative_id, a.candidate_result, a.economics, package.decision_policy.objectives)
        for a in feasible
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
    )

    return FixedInterfaceSiteOptimizationResult(
        run_id=run_id, package=package, fixed_integration_station=station, pydoublet_result=golden, routes=routes,
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


def render_geothermal_results_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = [
        {
            "alternative_id": alt.identity.alternative_id,
            "surface_site_id": alt.identity.surface_site_id,
            "resource_scenario_id": alt.identity.resource_scenario_id,
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


def render_drilling_site_ranking_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    payload = {
        "fixed_dh_integration_point": result.fixed_integration_station.station_id,
        "decision": json.loads(result.decision.model_dump_json()),
    }
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def render_drilling_site_ranking_csv(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    import csv
    import io

    fieldnames = [
        "alternative_id", "surface_site_id", "resource_scenario_id", "network_entry_attachment_id",
        "feasible", "stage_reached", "failure_code", "surface_connection_length_m",
        "annualised_cost_total_eur_per_a", "indicative_lcoh_eur_per_mwh", "geothermal_coverage_fraction",
        "in_pareto_shortlist",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id):
        writer.writerow({
            "alternative_id": alt.identity.alternative_id,
            "surface_site_id": alt.identity.surface_site_id,
            "resource_scenario_id": alt.identity.resource_scenario_id,
            "network_entry_attachment_id": alt.identity.attachment_id,
            "feasible": alt.feasible,
            "stage_reached": alt.stage_reached.value,
            "failure_code": alt.failure_code or "",
            "surface_connection_length_m": (
                f"{alt.candidate_result.candidate.surface_connection_length_m:.6f}" if alt.candidate_result else ""
            ),
            "annualised_cost_total_eur_per_a": f"{alt.economics.annualised_cost_total_eur_per_a:.6f}" if alt.economics else "",
            "indicative_lcoh_eur_per_mwh": f"{alt.economics.indicative_lcoh_eur_per_kwh * 1000.0:.6f}" if alt.economics else "",
            "geothermal_coverage_fraction": f"{alt.candidate_result.geothermal_coverage_fraction:.6f}" if alt.candidate_result else "",
            "in_pareto_shortlist": alt.identity.alternative_id in result.decision.pareto_shortlist_alternative_ids,
        })
    return buffer.getvalue().encode("utf-8")


def render_fixed_integration_station_json(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    return (result.fixed_integration_station.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_research_findings_markdown(result: FixedInterfaceSiteOptimizationResult) -> bytes:
    station = result.fixed_integration_station
    lines: list[str] = []
    lines.append("# R3-CHAIN fixed-DH-interface drilling-site optimization")
    lines.append("")
    lines.append(RESEARCH_FINDINGS_SYNTHETIC_DISCLAIMER)
    lines.append("")
    lines.append(f"**Fixed DH integration point:** `{station.station_id}` ({station.name})")
    lines.append("")
    lines.append("**Primary spatial decision:** geothermal drilling site.")
    lines.append("")
    lines.append("**Network attachment optimization:** disabled for this methodology -- "
                  "every candidate below connects to the SAME fixed DH integration point.")
    lines.append("")
    c = result.counts
    lines.append(
        f"Candidate drilling sites: {c.site_count} &middot; resource scenarios: {c.resource_scenario_count} "
        f"&middot; routes generated: {c.generated_route_count} ({c.accepted_route_count} accepted) "
        f"&middot; possible combinations: {c.possible_alternative_count} &middot; "
        f"compatible: {c.compatible_alternative_count} &middot; evaluated: {c.evaluated_alternative_count} "
        f"&middot; feasible: {c.feasible_alternative_count}"
    )
    lines.append("")

    lines.append("## Feasible candidate drilling sites")
    lines.append("")
    feasible = [a for a in result.alternatives if a.feasible]
    if feasible:
        lines.append("| Site | Scenario | Distance to fixed station (m) | Annualised cost (EUR/a) | Indicative LCOH (EUR/MWh) | In Pareto shortlist |")
        lines.append("|---|---|---:|---:|---:|:---:|")
        for alt in sorted(feasible, key=lambda a: a.identity.alternative_id):
            in_shortlist = "yes" if alt.identity.alternative_id in result.decision.pareto_shortlist_alternative_ids else "no"
            length_m = alt.candidate_result.candidate.surface_connection_length_m if alt.candidate_result else float("nan")
            lines.append(
                f"| `{alt.identity.surface_site_id}` | `{alt.identity.resource_scenario_id}` | {length_m:,.1f} "
                f"| {alt.economics.annualised_cost_total_eur_per_a:,.2f} "
                f"| {alt.economics.indicative_lcoh_eur_per_kwh * 1000.0:.4f} | {in_shortlist} |"
            )
    else:
        lines.append("No candidate drilling site was technically feasible against this fixed DH interface "
                      "(a valid, completed outcome).")
    lines.append("")

    lines.append("## Rejected candidate drilling sites")
    lines.append("")
    rejected = [a for a in result.alternatives if not a.feasible]
    if rejected:
        lines.append("| Site | Scenario | Stage | Failure code | Message |")
        lines.append("|---|---|---|---|---|")
        for alt in sorted(rejected, key=lambda a: a.identity.alternative_id):
            lines.append(
                f"| `{alt.identity.surface_site_id}` | `{alt.identity.resource_scenario_id}` | "
                f"{alt.stage_reached.value} | `{alt.failure_code}` | {alt.message} |"
            )
    else:
        lines.append("No compatible candidate drilling site was rejected.")
    lines.append("")

    lines.append("## Decision")
    lines.append("")
    if result.decision.mode.value == "pareto_only":
        lines.append(
            f"Decision policy mode: `pareto_only` -- {len(result.decision.pareto_shortlist_alternative_ids)} "
            "non-dominated candidate drilling site(s), no single preferred site under this policy."
        )
        for alt_id in result.decision.pareto_shortlist_alternative_ids:
            lines.append(f"- `{alt_id}`: {result.decision.pareto_explanations.get(alt_id, '')}")
    else:
        if result.decision.preferred_alternative_id:
            preferred = next(
                a for a in result.alternatives if a.identity.alternative_id == result.decision.preferred_alternative_id
            )
            lines.append(f"**Preferred drilling site: `{preferred.identity.surface_site_id}`** "
                         f"(scenario `{preferred.identity.resource_scenario_id}`).")
            lines.append(f"\n{result.decision.synthetic_cost_sensitivity_caveat}")
        else:
            lines.append("No unique preferred drilling site -- rank 1 contains more than one materially tied candidate.")
    lines.append("")

    lines.append("## What this prototype does not claim")
    lines.append("")
    lines.append("- No real Wuppertal (or any other real place's) drilling-site recommendation.")
    lines.append("- No Fündigkeitsrisiko / geological probability-of-success model -- deferred, see "
                  "`docs/decisions/ADR-003-fixed-interface-drilling-site-optimization.md`.")
    lines.append("- No full network operating-envelope optimization -- prescribed DH supply/return "
                  "temperatures remain fixed inputs.")
    lines.append("- No heat-pump-assisted or hybrid integration mode is evaluated -- only direct heat "
                  "exchange, per the fixed station's own `heat_pump_config_reference: null`.")
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
