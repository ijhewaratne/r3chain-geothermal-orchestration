"""Corrected joint site/connection workflow (S15/S17, WF-001..012,
AUD-001..012, docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 5).

## Not workflow/joint_workflow.py

That module (and `workflow/joint_optimization.py` it wraps) is the v1
joint layer -- untouched throughout Phases 1-4, and untouched here.
`R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md`'s own
§6.2 suggests the same filename for the v2 orchestrator; this module is
named `joint_workflow_v2` instead specifically to avoid overwriting or
colliding with the existing, still-relied-upon v1 entry point.

## What this orchestrates (WF-003/004/006, reuse only -- EVAL-004)

`run_joint_workflow_v2()` sequences, in order: load + validate the study
package (`data_contracts.joint_study.validate_joint_study_package()`,
Phase 1) BEFORE any simulation (WF-003); verify the resource input's own
raw-hash binding; parse the primary PyDoublet input
(`parsers.pydoublet_parser.parse_pydoublet_result()`, unchanged); build
the fixed synthetic blueprint and run its baseline (unchanged,
`network.blueprint`/`network.baseline`); generate site-origin-aware
routes (`network.site_routing`, Phase 2); enumerate ONLY compatible
alternatives (`workflow.joint_enumeration`, Phase 2 -- WF-004); evaluate
each one, with economics on every feasible result
(`workflow.joint_evaluation`, Phases 2/4); and compute a decision
(`decision.joint_policy`, Phase 4). No new scientific computation exists
in this module -- it is sequencing and audit/artifact bookkeeping only,
exactly like `workflow/joint_workflow.py`'s own v1 precedent, whose
hashing/manifest idiom this module deliberately mirrors (not imports,
since that module's own helpers are private to it)."""
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
from .joint_enumeration import enumerate_compatible_alternatives, possible_combination_count
from .joint_evaluation import JointAlternativeEvaluation, evaluate_compatible_alternatives

JOINT_WORKFLOW_V2_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

# ── artifact filenames ───────────────────────────────────────────────────────
PYDOUBLET_INPUT_FILENAME = "pydoublet_input.json"
CONFIG_SNAPSHOT_FILENAME = "config_snapshot.json"
JOINT_STUDY_SNAPSHOT_FILENAME = "joint_study_snapshot.json"
RESOURCE_INPUT_INDEX_FILENAME = "resource_input_index.json"
SITES_FILENAME = "sites.json"
RESOURCE_SCENARIOS_FILENAME = "resource_scenarios.json"
SCREENED_ROUTES_FILENAME = "screened_site_connection_routes.json"
SITE_ROUTE_GEOMETRY_FILENAME = "site_route_geometry.json"
COMPATIBLE_ALTERNATIVES_FILENAME = "compatible_alternatives.json"
JOINT_RESULT_FILENAME = "joint_optimization_result.json"
ALTERNATIVE_COMPARISON_CSV_FILENAME = "alternative_comparison.csv"
OBJECTIVE_POLICY_FILENAME = "objective_policy.json"
PARETO_OR_RANKING_FILENAME = "pareto_or_ranking.json"
NETWORK_CANDIDATES_SVG_FILENAME = "network_candidates.svg"
JOINT_RECOMMENDATION_MD_FILENAME = "joint_recommendation.md"
AUDIT_FILENAME = "audit.json"
MANIFEST_FILENAME = "manifest.json"

_JSON_FILENAMES = frozenset((
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, JOINT_STUDY_SNAPSHOT_FILENAME, RESOURCE_INPUT_INDEX_FILENAME,
    SITES_FILENAME, RESOURCE_SCENARIOS_FILENAME, SCREENED_ROUTES_FILENAME, SITE_ROUTE_GEOMETRY_FILENAME,
    COMPATIBLE_ALTERNATIVES_FILENAME, JOINT_RESULT_FILENAME, OBJECTIVE_POLICY_FILENAME, PARETO_OR_RANKING_FILENAME,
    AUDIT_FILENAME,
))
_CORE_SCIENTIFIC_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, JOINT_STUDY_SNAPSHOT_FILENAME, JOINT_RESULT_FILENAME,
    AUDIT_FILENAME,
)
"""AUD-001: declared inputs (pydoublet_input, config_snapshot,
joint_study_snapshot) and calculated results (joint_optimization_result)
preserved separately, plus the audit trail -- the minimum every bundle
this module writes must contain. The full completed bundle (see
write_joint_workflow_v2_artifacts()) additionally publishes every file
S17 of docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
names -- resource_input_index.json/sites.json/resource_scenarios.json/
site_route_geometry.json/network_candidates.svg were originally deferred
here as redundant with joint_study_snapshot.json/screened_site_connection_routes.json;
that deferral was withdrawn (Phase 9) once the specification's own literal
"SHALL publish" wording was read as requiring these named files
separately, not merely as recoverable sub-content of a larger file."""


class JointWorkflowV2Counts(BaseModel):
    """WF-005: every count a reader needs to see how much the
    compatibility constraint actually excluded, not just the final
    number."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_count: int
    resource_scenario_count: int
    network_attachment_count: int
    design_option_count: int
    operating_policy_count: int
    generated_route_count: int
    accepted_route_count: int
    possible_alternative_count: int
    compatible_alternative_count: int
    evaluated_alternative_count: int
    feasible_alternative_count: int

    @model_validator(mode="after")
    def _validate(self) -> "JointWorkflowV2Counts":
        if self.evaluated_alternative_count != self.compatible_alternative_count:
            raise ValueError("evaluated_alternative_count must equal compatible_alternative_count (WF-006)")
        if self.feasible_alternative_count > self.evaluated_alternative_count:
            raise ValueError("feasible_alternative_count cannot exceed evaluated_alternative_count")
        return self


class JointWorkflowV2Result(BaseModel):
    """A completed v2 joint run -- meaning the fixed sequence finished,
    not that any alternative was recommended (WF-010: zero feasible
    alternatives is a valid, completed result with an empty shortlist,
    never a software error)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = JOINT_WORKFLOW_V2_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    run_id: str
    package: JointStudyPackage
    pydoublet_result: PyDoubletCouplingResult
    routes: list[SiteConnectionRoute]
    alternatives: list[JointAlternativeEvaluation]
    active_dimensions: ActiveDimensionReport
    decision: JointDecisionResult
    counts: JointWorkflowV2Counts
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "JointWorkflowV2Result":
        if self.run_id != self.audit.run_id:
            raise ValueError("run_id does not match audit.run_id")
        return self


class JointWorkflowV2Failure(BaseModel):
    """A v2 joint run that stopped before (or during) evaluation --
    FAIL-002/007: whole-run validation/provenance/readiness failures
    occur before any solver call; an unexpected internal exception would
    remain an uncaught software error, never mapped into this type."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = JOINT_WORKFLOW_V2_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"

    run_id: str
    failure_code: str
    """Either a data_contracts.joint_study.JointRunFailureCode value
    (JOINT_STUDY_PACKAGE_INVALID, PYDOUBLET_RAW_HASH_MISMATCH) or a
    reused workflow.errors.WorkflowFailureCode value (blueprint/baseline
    construction) -- FAIL-005: reuse existing codes, never a generic
    wrapper."""
    stage: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "JointWorkflowV2Failure":
        if self.run_id != self.audit.run_id:
            raise ValueError("run_id does not match audit.run_id")
        return self


JointWorkflowV2BoundaryResult = Annotated[
    Union[JointWorkflowV2Result, JointWorkflowV2Failure], Field(discriminator="status"),
]
_boundary_result_adapter: TypeAdapter = TypeAdapter(JointWorkflowV2BoundaryResult)


def parse_joint_workflow_v2_result_json(json_str: str) -> JointWorkflowV2BoundaryResult:
    return _boundary_result_adapter.validate_json(json_str)


def is_joint_study_v2_enabled(config: dict[str, Any]) -> bool:
    """The single, explicit config switch this module keys off --
    absent from config/demo_assumptions.json, so the canonical workflow
    is completely unaffected (WF-002)."""
    return bool(config.get("joint_study_v2", {}).get("enabled", False))


def _resolve_package_path(config: dict[str, Any], package_root: Path) -> Path:
    relative_path = config["joint_study_v2"]["package_path"]
    resolved = (package_root / relative_path).resolve()
    root = package_root.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"joint_study_v2.package_path escapes the package root: {resolved}")
    return resolved


@dataclass(frozen=True)
class _PackageLoadOutcome:
    """The exact result of Stage 0 (WF-003) -- factored out so
    `run_joint_workflow_v2()` and the MCP-layer's own pre-registry run_id
    computation (`resolve_joint_workflow_v2_run_id()`, mcp_server/tools.py)
    always agree on `run_id` BY CONSTRUCTION, never by hand-copied logic
    that could drift. `error` is `None` exactly when `package`/`package_raw`
    are both populated."""

    run_id: str
    config_sha256_for_audit: str
    """`combined_config_sha256` on the happy path (folds the package's own
    content into the run's content-address); the PLAIN `config_sha256` on
    the early-failure path, where no package content is yet available to
    fold in (module's own run_id note, preserved verbatim below)."""
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
    # Fold the study package's own content into the run's content-address --
    # otherwise two DIFFERENT package files pointed at by the SAME config
    # key would collide on run_id.
    combined_config_sha256 = canonical_raw_result_sha256({"config": config, "joint_study_package": package_raw})
    run_id = compute_run_id(input_sha256, combined_config_sha256, source_provenance_sha256, WORKFLOW_CONTRACT_SCHEMA_VERSION)
    return _PackageLoadOutcome(
        run_id=run_id, config_sha256_for_audit=combined_config_sha256, package_raw=package_raw, package=package, error=None,
    )


def resolve_joint_workflow_v2_run_id(
    pydoublet_raw_result: dict[str, Any], config: dict[str, Any], *,
    source_provenance: SourceProvenance, package_root: Path,
) -> tuple[str, dict[str, Any] | None]:
    """Public, cheap (no simulation) helper for a caller that needs this
    run's stable `run_id` (and, if available, the package's raw content)
    BEFORE deciding whether to actually invoke `run_joint_workflow_v2()` --
    the MCP tool layer's own pre-registry-lookup step
    (`mcp_server/tools.py::run_joint_workflow_tool()`), mirroring how the
    canonical path's `workflow/core.py::run_workflow()` run_id is already
    computed once outside `registry.get_or_run()` and once again (in
    agreement, by construction) inside the workflow call itself. Returns
    `(run_id, package_raw)` -- `package_raw` is `None` exactly when the
    package could not be loaded/parsed (the same early-failure case
    `run_joint_workflow_v2()` itself reports as `JOINT_STUDY_PACKAGE_INVALID`),
    in which case `run_id` is computed the same way that failure path
    computes it. Never raises."""
    outcome = _load_and_hash_package(
        pydoublet_raw_result, config, source_provenance=source_provenance, package_root=package_root,
    )
    return outcome.run_id, outcome.package_raw


def run_joint_workflow_v2(
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    *,
    source_provenance: SourceProvenance,
    package_root: Path,
    expected_raw_sha256: str | None = None,
    now: Callable[[], datetime] = _default_now,
) -> JointWorkflowV2BoundaryResult:
    """WF-003: package validation happens BEFORE baseline or candidate
    simulation. Never raises for any of its named stopping conditions."""
    workflow_created_at = now()
    input_sha256 = canonical_raw_result_sha256(pydoublet_raw_result)
    source_provenance_sha256 = compute_source_provenance_sha256(source_provenance)

    stage_calls: list[StageCallRecord] = []
    warnings: list[WorkflowWarningRecord] = []

    # ── Stage 0: load + validate the study package (WF-003, before anything else) ──
    outcome = _load_and_hash_package(
        pydoublet_raw_result, config, source_provenance=source_provenance, package_root=package_root,
    )
    run_id = outcome.run_id
    if outcome.error is not None:
        stage_calls.append(StageCallRecord(
            order=1, stage_name="load_and_validate_joint_study_package", status="failure",
            failure_code="JOINT_STUDY_PACKAGE_INVALID", message=str(outcome.error),
        ))
        return JointWorkflowV2Failure(
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
        # combined_config_sha256, not the plain config_sha256, to stay
        # consistent with how run_id above was itself derived (module's
        # own run_id note) -- WorkflowAuditRecord's own validator
        # recomputes run_id from exactly these four hashes.
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
        return JointWorkflowV2Failure(
            run_id=run_id, failure_code="JOINT_STUDY_PACKAGE_INVALID", stage="validate_joint_study_package",
            message=f"study package failed relationship validation ({len(relationship_result.errors)} error(s))",
            details={"errors": [json.loads(e.model_dump_json()) for e in relationship_result.errors]},
            audit=_audit(), created_at=workflow_created_at,
        )

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
            return JointWorkflowV2Failure(
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
        return JointWorkflowV2Failure(
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
        return JointWorkflowV2Failure(
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
        return JointWorkflowV2Failure(
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

    # ── Stage 4: site-origin-aware routes (Phase 2) ──
    # StageCallRecord's own invariant (workflow/core.py) forbids a
    # "success" record from carrying a message -- summary figures like
    # route/alternative counts live on JointWorkflowV2Counts (WF-005)
    # instead, not stuffed into the stage-call log.
    routes = generate_site_routes(package.sites, package.network_attachments, package.routing_policy)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="generate_site_routes", status="success"))

    # ── Stage 5: compatible enumeration (WF-004) ──
    identities = enumerate_compatible_alternatives(package, routes)
    possible_count = possible_combination_count(package, routes)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="enumerate_compatible_alternatives", status="success"))

    # ── Stage 6: evaluate every compatible alternative (Phases 2-4) ──
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

    # ── Stage 7: decision (Phase 4) -- WF-010: zero feasible is valid ──
    feasible = [a for a in alternatives if a.feasible]
    alt_values = [
        compute_alternative_objective_values(a.identity.alternative_id, a.candidate_result, a.economics, package.decision_policy.objectives)
        for a in feasible
    ]
    decision = decide(alt_values, package.decision_policy)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="decide", status="success"))

    active_dimensions = compute_active_dimensions(package, routes)

    counts = JointWorkflowV2Counts(
        site_count=len(package.sites), resource_scenario_count=len(package.resource_scenarios),
        network_attachment_count=len(package.network_attachments), design_option_count=len(package.design_options),
        operating_policy_count=len(package.operating_policies), generated_route_count=len(routes),
        accepted_route_count=sum(1 for r in routes if r.screening_status == RouteScreeningStatus.ACCEPTED),
        possible_alternative_count=possible_count, compatible_alternative_count=len(identities),
        evaluated_alternative_count=len(alternatives), feasible_alternative_count=len(feasible),
    )

    return JointWorkflowV2Result(
        run_id=run_id, package=package, pydoublet_result=golden, routes=routes, alternatives=alternatives,
        active_dimensions=active_dimensions, decision=decision, counts=counts, audit=_audit(),
        created_at=workflow_created_at,
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


# ── S17 artifacts (AUD-001..012) ─────────────────────────────────────────────

RECOMMENDATION_SYNTHETIC_DISCLAIMER = (
    "This is a SYNTHETIC demonstration: every site, resource scenario, route, design and policy here "
    "is explicitly invented for this prototype. It contains no real Wuppertal (or any other real "
    "place's) data, and must never be read as a real geological drilling-site recommendation, a real "
    "network-connection recommendation, or a validated economic result."
)


def render_alternative_comparison_csv(result: JointWorkflowV2Result) -> bytes:
    import csv
    import io

    fieldnames = [
        "alternative_id", "resource_scenario_id", "surface_site_id", "attachment_id", "route_id",
        "design_option_id", "operating_policy_id", "feasible", "stage_reached", "failure_code",
        "annualised_cost_total_eur_per_a", "indicative_lcoh_eur_per_mwh", "geothermal_coverage_fraction",
        "surface_connection_length_m", "in_pareto_shortlist",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id):
        writer.writerow({
            "alternative_id": alt.identity.alternative_id,
            "resource_scenario_id": alt.identity.resource_scenario_id,
            "surface_site_id": alt.identity.surface_site_id,
            "attachment_id": alt.identity.attachment_id,
            "route_id": alt.identity.route_id,
            "design_option_id": alt.identity.design_option_id,
            "operating_policy_id": alt.identity.operating_policy_id,
            "feasible": alt.feasible,
            "stage_reached": alt.stage_reached.value,
            "failure_code": alt.failure_code or "",
            "annualised_cost_total_eur_per_a": f"{alt.economics.annualised_cost_total_eur_per_a:.6f}" if alt.economics else "",
            "indicative_lcoh_eur_per_mwh": f"{alt.economics.indicative_lcoh_eur_per_kwh * 1000.0:.6f}" if alt.economics else "",
            "geothermal_coverage_fraction": f"{alt.candidate_result.geothermal_coverage_fraction:.6f}" if alt.candidate_result else "",
            "surface_connection_length_m": f"{alt.candidate_result.candidate.surface_connection_length_m:.6f}" if alt.candidate_result else "",
            "in_pareto_shortlist": alt.identity.alternative_id in result.decision.pareto_shortlist_alternative_ids,
        })
    return buffer.getvalue().encode("utf-8")


def render_objective_policy_json(result: JointWorkflowV2Result) -> bytes:
    payload = {
        "mode": result.decision.mode.value,
        "objectives": [json.loads(o.model_dump_json()) for o in result.package.decision_policy.objectives],
        "primary_objective": result.package.decision_policy.primary_objective,
        "tie_breakers": result.package.decision_policy.tie_breakers,
    }
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def render_pareto_or_ranking_json(result: JointWorkflowV2Result) -> bytes:
    return (result.decision.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_screened_routes_json(result: JointWorkflowV2Result) -> bytes:
    payload = [json.loads(r.model_dump_json()) for r in sorted(result.routes, key=lambda r: r.route_id)]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_compatible_alternatives_json(result: JointWorkflowV2Result) -> bytes:
    payload = [
        json.loads(a.identity.model_dump_json())
        for a in sorted(result.alternatives, key=lambda a: a.identity.alternative_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


# ── S17 named artifacts, added Phase 9 (docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
# §17's own literal "SHALL publish" list) -- each of these five files was
# previously deferred as redundant sub-content of joint_study_snapshot.json/
# screened_site_connection_routes.json; that deferral is withdrawn here.
# None invents new data: every field below is read straight from the
# already-validated JointStudyPackage/routes this run already computed.
def render_resource_input_index_json(package: JointStudyPackage) -> bytes:
    payload = [
        json.loads(ri.model_dump_json())
        for ri in sorted(package.resource_inputs, key=lambda ri: ri.resource_input_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_sites_json(package: JointStudyPackage) -> bytes:
    payload = [json.loads(s.model_dump_json()) for s in sorted(package.sites, key=lambda s: s.site_id)]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_resource_scenarios_json(package: JointStudyPackage) -> bytes:
    payload = [
        json.loads(s.model_dump_json())
        for s in sorted(package.resource_scenarios, key=lambda s: s.scenario_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_site_route_geometry_json(package: JointStudyPackage, routes: list[SiteConnectionRoute]) -> bytes:
    """Every route's own geometry, alongside an EXPLICIT declaration of the
    coordinate basis it is expressed in (`package.coordinate_reference`) --
    the specification's own explicit requirement that this file "declare
    the synthetic Cartesian coordinate basis." Includes every generated
    route (accepted and rejected), not only accepted ones -- the same full
    scope screened_site_connection_routes.json already covers, extracted
    here into its own dedicated, geometry-focused file."""
    payload = {
        "coordinate_basis": json.loads(package.coordinate_reference.model_dump_json()),
        "routes": [
            {
                "route_id": r.route_id,
                "surface_site_id": r.site_id,
                "attachment_id": r.attachment_id,
                "screening_status": r.screening_status.value,
                "route_kind": r.route_kind.value,
                "paired_trench_length_m": r.paired_trench_length_m,
                "route_geometry": [json.loads(pt.model_dump_json()) for pt in r.route_geometry],
            }
            for r in sorted(routes, key=lambda r: r.route_id)
        ],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_network_candidates_svg(
    package: JointStudyPackage, routes: list[SiteConnectionRoute], compatible_alternative_ids: frozenset[str],
) -> bytes:
    """A SYNTHETIC network diagram -- surface sites, network attachments,
    and every generated route (accepted, drawn solid; rejected, drawn
    dashed) in the package's own synthetic Cartesian coordinate system.
    Deliberately schematic: axis-scaled to the actual synthetic
    coordinates so relative distances are meaningful WITHIN this
    demonstration, but explicitly labelled SYNTHETIC in the image itself
    (title, legend, and a full-width disclaimer banner) so it can never be
    mistaken for a real geographic/GIS map -- the same synthetic-only
    Cartesian coordinate system this package's own `coordinate_reference`
    already declares, never real-world coordinates."""
    from .site_routing_svg import render_network_candidates_svg as _render  # local import: pure rendering helper, no cycle
    return _render(package, routes, compatible_alternative_ids)


def render_joint_recommendation_markdown(result: JointWorkflowV2Result) -> bytes:
    lines: list[str] = []
    lines.append("# R3-CHAIN corrected synthetic joint site/connection optimisation (v2)")
    lines.append("")
    lines.append(RECOMMENDATION_SYNTHETIC_DISCLAIMER)
    lines.append("")
    lines.append(
        "**Question this run answers:** Among the candidate geothermal doublet locations and "
        "associated network connections, which candidate provides the technically feasible "
        "minimum-cost/LCOH solution for supplying the four-consumer DH network?"
    )
    lines.append("")
    c = result.counts
    lines.append(
        f"Sites: {c.site_count} &middot; resource scenarios: {c.resource_scenario_count} &middot; "
        f"attachments: {c.network_attachment_count} &middot; design options: {c.design_option_count} &middot; "
        f"operating policies: {c.operating_policy_count}"
    )
    lines.append(
        f"Routes generated: {c.generated_route_count} ({c.accepted_route_count} accepted) &middot; "
        f"possible combinations: {c.possible_alternative_count} &middot; compatible: {c.compatible_alternative_count} "
        f"&middot; evaluated: {c.evaluated_alternative_count} &middot; feasible: {c.feasible_alternative_count}"
    )
    lines.append("")
    lines.append(
        f"Active dimensions (TERM-003/004): {', '.join(result.active_dimensions.active_dimensions)}. "
        f"Controlled: {', '.join(result.active_dimensions.controlled_dimensions)}."
    )
    lines.append("")

    lines.append("## Feasible alternatives")
    lines.append("")
    feasible = [a for a in result.alternatives if a.feasible]
    if feasible:
        lines.append("| Alternative | Annualised cost (EUR/a) | Indicative LCOH (EUR/MWh) | In Pareto shortlist |")
        lines.append("|---|---:|---:|:---:|")
        for alt in sorted(feasible, key=lambda a: a.identity.alternative_id):
            in_shortlist = "yes" if alt.identity.alternative_id in result.decision.pareto_shortlist_alternative_ids else "no"
            lines.append(
                f"| `{alt.identity.alternative_id}` | {alt.economics.annualised_cost_total_eur_per_a:,.2f} "
                f"| {alt.economics.indicative_lcoh_eur_per_kwh * 1000.0:.4f} | {in_shortlist} |"
            )
    else:
        lines.append("No alternative was technically feasible (WF-010: a valid, completed outcome).")
    lines.append("")

    lines.append("## Rejected alternatives")
    lines.append("")
    rejected = [a for a in result.alternatives if not a.feasible]
    if rejected:
        lines.append("| Alternative | Stage | Failure code | Message |")
        lines.append("|---|---|---|---|")
        for alt in sorted(rejected, key=lambda a: a.identity.alternative_id):
            lines.append(f"| `{alt.identity.alternative_id}` | {alt.stage_reached.value} | `{alt.failure_code}` | {alt.message} |")
    else:
        lines.append("No compatible alternative was rejected.")
    lines.append("")

    lines.append("## Decision")
    lines.append("")
    if result.decision.mode.value == "pareto_only":
        lines.append(
            f"Decision policy mode: `pareto_only` -- {len(result.decision.pareto_shortlist_alternative_ids)} "
            "non-dominated alternative(s), no single preferred result (DEC-008)."
        )
        for alt_id in result.decision.pareto_shortlist_alternative_ids:
            lines.append(f"- `{alt_id}`: {result.decision.pareto_explanations.get(alt_id, '')}")
    else:
        if result.decision.preferred_alternative_id:
            lines.append(f"Preferred alternative: `{result.decision.preferred_alternative_id}`.")
            lines.append(f"\n{result.decision.synthetic_cost_sensitivity_caveat}")
        else:
            lines.append("No unique preferred alternative -- rank 1 contains more than one materially tied alternative (DEC-011).")
    lines.append("")

    return ("\n".join(lines) + "\n").encode("utf-8")


class JointWorkflowV2ManifestRecord(BaseModel):
    """manifest.json's own content for a v2 joint run -- mirrors
    workflow/joint_workflow.py's own JointOptimizationManifestRecord
    shape/invariants exactly, for this module's own (different) filename
    set (AUD-009: created and validated last)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = "1.0.0"
    scientific_normalization_rule_version: str = SCIENTIFIC_NORMALIZATION_RULE_VERSION
    run_type: Literal["joint_site_connection"] = "joint_site_connection"
    """MCP-006 (docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    Phase 6): an explicit, on-disk run-type discriminator -- lets
    mcp_server/registry.py's own rehydration (`_load_run_entry`) decide,
    from the manifest alone, whether to parse `workflow_result.json` (the
    canonical `ManifestRecord`'s own `run_type="canonical"`) or
    `joint_optimization_result.json` via this module's own
    `parse_joint_workflow_v2_result_json()`, without guessing from which
    files happen to be present."""
    run_id: str
    created_at: datetime
    files: dict[str, ArtifactHashRecord]
    bundle_scientific_sha256: str

    @model_validator(mode="after")
    def _validate(self) -> "JointWorkflowV2ManifestRecord":
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


def write_joint_workflow_v2_artifacts(
    result: JointWorkflowV2BoundaryResult,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    package_raw: dict[str, Any],
    output_dir: Path,
) -> JointWorkflowV2ManifestRecord:
    """AUD-001..012's own bundle for this module. `config_snapshot.json`
    holds the PLAIN config dict actually used (never the combined
    config+package hash `audit.config_sha256` folds in for run_id
    purposes -- that field's own semantics are documented on
    `run_joint_workflow_v2()`)."""
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

    joint_result_bytes = result.model_dump_json(indent=2).encode("utf-8")
    (output_dir / JOINT_RESULT_FILENAME).write_bytes(joint_result_bytes)
    hash_records[JOINT_RESULT_FILENAME] = _hash_record_for_json_bytes(joint_result_bytes)

    audit_bytes = result.audit.model_dump_json(indent=2).encode("utf-8")
    (output_dir / AUDIT_FILENAME).write_bytes(audit_bytes)
    hash_records[AUDIT_FILENAME] = _hash_record_for_json_bytes(audit_bytes)

    if isinstance(result, JointWorkflowV2Result):
        compatible_alternative_ids = frozenset(a.identity.alternative_id for a in result.alternatives)
        extra: dict[str, bytes] = {
            RESOURCE_INPUT_INDEX_FILENAME: render_resource_input_index_json(result.package),
            SITES_FILENAME: render_sites_json(result.package),
            RESOURCE_SCENARIOS_FILENAME: render_resource_scenarios_json(result.package),
            SCREENED_ROUTES_FILENAME: render_screened_routes_json(result),
            SITE_ROUTE_GEOMETRY_FILENAME: render_site_route_geometry_json(result.package, result.routes),
            COMPATIBLE_ALTERNATIVES_FILENAME: render_compatible_alternatives_json(result),
            ALTERNATIVE_COMPARISON_CSV_FILENAME: render_alternative_comparison_csv(result),
            OBJECTIVE_POLICY_FILENAME: render_objective_policy_json(result),
            PARETO_OR_RANKING_FILENAME: render_pareto_or_ranking_json(result),
            NETWORK_CANDIDATES_SVG_FILENAME: render_network_candidates_svg(
                result.package, result.routes, compatible_alternative_ids,
            ),
            JOINT_RECOMMENDATION_MD_FILENAME: render_joint_recommendation_markdown(result),
        }
        for filename, data in extra.items():
            (output_dir / filename).write_bytes(data)
            hash_records[filename] = (
                _hash_record_for_json_bytes(data) if filename in _JSON_FILENAMES else _hash_record_for_plain_bytes(data)
            )

    bundle_scientific_sha256 = canonical_raw_result_sha256(
        {filename: record.scientific_sha256 for filename, record in sorted(hash_records.items())}
    )
    manifest = JointWorkflowV2ManifestRecord(
        run_id=result.run_id, created_at=datetime.now(timezone.utc), files=hash_records,
        bundle_scientific_sha256=bundle_scientific_sha256,
    )
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest
