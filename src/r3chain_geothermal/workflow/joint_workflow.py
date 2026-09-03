"""R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase 4: the joint
synthetic site/connection optimisation demonstration
(`joint_optimization.py`), exposed as its own top-level workflow entry
point -- `run_joint_optimization_workflow()` -- through the SAME
config/provenance conventions `workflow/core.py::run_workflow()` uses,
rather than as a branch inside that already heavily-validated function.

## Why a separate entry point, not a branch inside run_workflow()

`WorkflowResult`'s own shape (`candidate_results: dict[str,
CandidateEvaluationBoundaryResult]`, `ranking: RankingResult`) is
specific to ONE geothermal scenario evaluated against a fixed candidate
set. A joint-optimization run's own result
(`JointOptimizationResult`) carries a genuinely different identity (a
`(scenario, candidate)` GRID, not a flat candidate set) and a Pareto
shortlist rather than a single lowest-cost ranking (OPT-003: no approved
multi-objective weighting policy exists). Reusing `WorkflowResult`'s own
frozen, heavily-tested, hash-pinned contract for a shape it was never
designed to hold would risk exactly the kind of silent scientific-meaning
drift CLAUDE.md prohibits. This module instead defines its own small,
parallel `JointOptimizationWorkflowResult`/`JointOptimizationWorkflowFailure`
envelope, reusing `WorkflowAuditRecord`/`SourceProvenance`/`run_id`
computation UNCHANGED from `core.py` (the same content-addressed
identity scheme), so it remains directly comparable and auditable
alongside every other run in the SAME persistent registry.

## How this stays reachable through the existing one-server MCP

Exactly like `candidates.mode=="generated"` (Phase 3.2): triggered purely
by CONFIG content (`config["joint_optimization"]["enabled"]==True`), never
a new MCP tool parameter or a 7th tool. `mcp_server/tools.py::run_workflow_tool()`
dispatches to this function instead of `core.run_workflow()` when the
server's own fixed_config opts in -- reachable by pointing the server's
`R3CHAIN_MCP_CONFIG_PATH` at such a config, the same mechanism already
established for the workshop-negative-demo and generated-candidates
configs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ..adapter import CouplingAssumptions
from ..contracts import PyDoubletCouplingFailure, PyDoubletCouplingResult, SourceProvenance
from ..economics import EconomicAssumptions
from ..hashing import (
    SCIENTIFIC_NORMALIZATION_RULE_VERSION,
    canonical_raw_result_json_bytes,
    canonical_raw_result_sha256,
    normalize_for_scientific_hash,
)
from ..network import GateTolerances, GeothermalInjectionPolicy, ScreenedCandidate, build_default_blueprint, generate_candidates, run_baseline_evaluation
from ..network.baseline import BaselineNetworkFailure, BaselineNetworkResult
from ..parsers.pydoublet_parser import parse_pydoublet_result
from .artifacts import ArtifactHashRecord
from .core import (
    StageCallRecord,
    WorkflowAuditRecord,
    WorkflowWarningRecord,
    _build_blueprint_kwargs,
    _default_now,
    compute_run_id,
    compute_source_provenance_sha256,
    WORKFLOW_CONTRACT_SCHEMA_VERSION,
)
from .errors import WorkflowFailureCode
from .joint_optimization import (
    JOINT_OPTIMIZATION_CONTRACT_SCHEMA_VERSION,
    JointOptimizationResult,
    run_joint_optimization_full_product,
)
from .joint_optimization_export import (
    render_alternative_comparison_csv,
    render_generated_candidates_json,
    render_joint_recommendation_markdown,
    render_pareto_or_ranking_json,
    render_screened_alternatives_json,
)

JOINT_WORKFLOW_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

# ── artifact filenames (module-level constants, mirrored into
# mcp_server/tools.py's own artifact allow-list) ──────────────────────────
PYDOUBLET_INPUT_FILENAME = "pydoublet_input.json"
CONFIG_SNAPSHOT_FILENAME = "config_snapshot.json"
JOINT_RESULT_FILENAME = "joint_optimization_result.json"
AUDIT_FILENAME = "audit.json"
GENERATED_CANDIDATES_FILENAME = "generated_candidates.json"
SCREENED_ALTERNATIVES_FILENAME = "screened_alternatives.json"
ALTERNATIVE_COMPARISON_CSV_FILENAME = "alternative_comparison.csv"
PARETO_OR_RANKING_FILENAME = "pareto_or_ranking.json"
JOINT_RECOMMENDATION_MD_FILENAME = "joint_recommendation.md"
MANIFEST_FILENAME = "manifest.json"

_JSON_FILENAMES = frozenset((
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, JOINT_RESULT_FILENAME, AUDIT_FILENAME,
    GENERATED_CANDIDATES_FILENAME, SCREENED_ALTERNATIVES_FILENAME, PARETO_OR_RANKING_FILENAME,
))
_CORE_SCIENTIFIC_FILENAMES = (PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, JOINT_RESULT_FILENAME, AUDIT_FILENAME)

JOINT_MANIFEST_CONTRACT_SCHEMA_VERSION = "1.0.0"


class JointOptimizationManifestRecord(BaseModel):
    """manifest.json's own content for a joint-optimization run --
    mirrors workflow/artifacts.py::ManifestRecord's shape and invariants
    exactly, EXCEPT its own core-filename set (that class hardcodes the
    single-scenario workflow's own `workflow_result.json`, which does not
    exist in this bundle at all -- reusing it directly would either force
    a misleading filename or fail validation; a small parallel model is
    the honest fix, not a shared one stretched to fit two shapes)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = JOINT_MANIFEST_CONTRACT_SCHEMA_VERSION
    scientific_normalization_rule_version: str = SCIENTIFIC_NORMALIZATION_RULE_VERSION
    run_id: str
    created_at: datetime
    files: dict[str, ArtifactHashRecord]
    bundle_scientific_sha256: str

    @model_validator(mode="after")
    def _validate(self) -> "JointOptimizationManifestRecord":
        errors: list[str] = []
        if not set(_CORE_SCIENTIFIC_FILENAMES) <= set(self.files.keys()):
            errors.append(
                f"files must contain at least the core scientific files {sorted(_CORE_SCIENTIFIC_FILENAMES)}, "
                f"got {sorted(self.files.keys())}"
            )
        if MANIFEST_FILENAME in self.files:
            errors.append("manifest.json must never hash itself")
        for filename in self.files:
            if "/" in filename or "\\" in filename or filename.startswith("."):
                errors.append(f"files[{filename!r}] must be a plain relative filename, not a path")
        expected_bundle_hash = canonical_raw_result_sha256(
            {filename: record.scientific_sha256 for filename, record in sorted(self.files.items())}
        )
        if self.bundle_scientific_sha256 != expected_bundle_hash:
            errors.append("bundle_scientific_sha256 does not match recomputation from files' own scientific_sha256 values")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class JointOptimizationWorkflowResult(BaseModel):
    """A completed joint-optimization run -- meaning the fixed sequence
    finished, not that any alternative was recommended (`joint_result
    .pareto_shortlist_alternative_ids` may legitimately be empty when no
    alternative in the grid is feasible; a normal, honest outcome, never
    an error -- see `render_joint_recommendation_markdown`'s own
    "no feasible alternative" text)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = JOINT_WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    run_id: str
    pydoublet_result: PyDoubletCouplingResult
    joint_result: JointOptimizationResult
    screened_candidates: list[ScreenedCandidate]
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "JointOptimizationWorkflowResult":
        if self.run_id != self.audit.run_id:
            raise ValueError("run_id does not match audit.run_id")
        return self


class JointOptimizationWorkflowFailure(BaseModel):
    """A joint-optimization run that stopped before any alternative was
    evaluated. Reuses WorkflowFailureCode's own PYDOUBLET_PARSE_FAILED/
    BLUEPRINT_CONSTRUCTION_FAILED/BASELINE_EVALUATION_FAILED -- the same
    three stopping conditions run_workflow() itself can hit before its
    own candidate-evaluation stage; HEAT_EXCHANGER_COUPLING_FAILED does
    not apply here, since HX coupling is evaluated per (scenario,
    candidate) alternative inside joint_result, never as one shared
    top-level stage."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = JOINT_WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"

    run_id: str
    failure_code: WorkflowFailureCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    pydoublet_result: PyDoubletCouplingResult | None = None
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "JointOptimizationWorkflowFailure":
        errors: list[str] = []
        if self.run_id != self.audit.run_id:
            errors.append("run_id does not match audit.run_id")
        if self.failure_code == WorkflowFailureCode.PYDOUBLET_PARSE_FAILED and self.pydoublet_result is not None:
            errors.append("PYDOUBLET_PARSE_FAILED must not carry a pydoublet_result")
        if self.failure_code != WorkflowFailureCode.PYDOUBLET_PARSE_FAILED and self.pydoublet_result is None:
            errors.append(f"{self.failure_code} must carry a pydoublet_result (an earlier stage than the one that failed)")
        if errors:
            raise ValueError("; ".join(errors))
        return self


JointOptimizationWorkflowBoundaryResult = Annotated[
    Union[JointOptimizationWorkflowResult, JointOptimizationWorkflowFailure], Field(discriminator="status"),
]
_boundary_result_adapter: TypeAdapter = TypeAdapter(JointOptimizationWorkflowBoundaryResult)


def parse_joint_optimization_workflow_result_json(json_str: str) -> JointOptimizationWorkflowBoundaryResult:
    return _boundary_result_adapter.validate_json(json_str)


def is_joint_optimization_enabled(config: dict[str, Any]) -> bool:
    """The single, explicit config switch this whole module keys off --
    absent from the canonical config/demo_assumptions.json, so it never
    silently changes that config's own behaviour."""
    return bool(config.get("joint_optimization", {}).get("enabled", False))


def run_joint_optimization_workflow(
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    *,
    source_provenance: SourceProvenance,
    expected_raw_sha256: str | None = None,
    now: Callable[[], datetime] = _default_now,
) -> JointOptimizationWorkflowBoundaryResult:
    """Runs: parse/validate the raw PyDoublet result (stage 1, same as
    run_workflow()) -> build the fixed synthetic blueprint (stage 2) ->
    run generate_candidates() over it using config["candidates"]["generated"]
    (the SAME config keys Phase 3.2 established, reused unchanged here --
    joint-optimization always evaluates against the generated candidate
    set, never only the four hand-picked C1-C4) -> run the baseline (stage
    3) -> evaluate the FULL scenario x accepted-candidate product
    (run_joint_optimization_full_product(), Phase 4). Never raises for any
    of its three stopping-failure codes."""
    workflow_created_at = now()
    input_sha256 = canonical_raw_result_sha256(pydoublet_raw_result)
    config_sha256 = canonical_raw_result_sha256(config)
    source_provenance_sha256 = compute_source_provenance_sha256(source_provenance)
    run_id = compute_run_id(input_sha256, config_sha256, source_provenance_sha256, WORKFLOW_CONTRACT_SCHEMA_VERSION)

    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    gate_tolerances = GateTolerances.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    economic_assumptions = EconomicAssumptions.from_config_dict(config)

    stage_calls: list[StageCallRecord] = []
    warnings: list[WorkflowWarningRecord] = []

    def _audit() -> WorkflowAuditRecord:
        return WorkflowAuditRecord(
            run_id=run_id, contract_schema_version=WORKFLOW_CONTRACT_SCHEMA_VERSION, created_at=workflow_created_at,
            input_sha256=input_sha256, config_sha256=config_sha256, source_provenance=source_provenance,
            source_provenance_sha256=source_provenance_sha256, stage_calls=list(stage_calls),
            coupling_assumptions=coupling_assumptions, gate_tolerances=gate_tolerances,
            injection_policy=injection_policy, economic_assumptions=economic_assumptions, warnings=list(warnings),
        )

    # ── Stage 1: parse and validate the raw PyDoublet result ──
    pydoublet_boundary = parse_pydoublet_result(
        pydoublet_raw_result, source_provenance=source_provenance, expected_raw_sha256=expected_raw_sha256,
    )
    if isinstance(pydoublet_boundary, PyDoubletCouplingFailure):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="parse_pydoublet_result", status="failure",
            failure_code=pydoublet_boundary.failure_code.value, message=pydoublet_boundary.message,
        ))
        return JointOptimizationWorkflowFailure(
            run_id=run_id, failure_code=WorkflowFailureCode.PYDOUBLET_PARSE_FAILED,
            message=f"parse_pydoublet_result failed: {pydoublet_boundary.message}",
            details={"failure_code": pydoublet_boundary.failure_code.value, "upstream_details": pydoublet_boundary.details},
            audit=_audit(), created_at=workflow_created_at,
        )
    pydoublet_result: PyDoubletCouplingResult = pydoublet_boundary
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="parse_pydoublet_result", status="success"))

    # ── Stage 2: build the fixed synthetic blueprint + generate candidates ──
    try:
        blueprint = build_default_blueprint(created_at=workflow_created_at, **_build_blueprint_kwargs(config))
        generated_cfg = config["candidates"]["generated"]
        generate_kwargs: dict[str, Any] = {"connection_pipe_dn_mm": generated_cfg["connection_pipe_dn_mm"]}
        if "max_route_length_m" in generated_cfg:
            generate_kwargs["max_route_length_m"] = generated_cfg["max_route_length_m"]
        screened = generate_candidates(blueprint, **generate_kwargs)
        max_candidates = generated_cfg.get("max_candidates")
        if max_candidates is not None:
            accepted_ids_in_order = sorted(sc.candidate_id for sc in screened if sc.accepted)[:max_candidates]
            allowed_ids = set(accepted_ids_in_order)
            screened = [sc for sc in screened if sc.accepted and sc.candidate_id in allowed_ids or not sc.accepted]
        if not any(sc.accepted for sc in screened):
            raise ValueError(
                f"joint_optimization requires at least one accepted generated candidate "
                f"({len(screened)} screened, all rejected/capped to zero)"
            )
    except (KeyError, ValueError, ValidationError) as exc:
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="build_blueprint_and_generate_candidates", status="failure",
            failure_code=WorkflowFailureCode.BLUEPRINT_CONSTRUCTION_FAILED.value, message=str(exc),
        ))
        return JointOptimizationWorkflowFailure(
            run_id=run_id, failure_code=WorkflowFailureCode.BLUEPRINT_CONSTRUCTION_FAILED,
            message=f"blueprint/candidate-generation setup raised {type(exc).__name__}: {exc}",
            details={"exception_message": str(exc)},
            pydoublet_result=pydoublet_result, audit=_audit(), created_at=workflow_created_at,
        )
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="build_blueprint_and_generate_candidates", status="success"))

    # ── Stage 3: baseline ──
    baseline_boundary = run_baseline_evaluation(blueprint, tolerances=gate_tolerances)
    if isinstance(baseline_boundary, BaselineNetworkFailure):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="run_baseline_evaluation", status="failure",
            failure_code=baseline_boundary.failure_code.value, message=baseline_boundary.message,
        ))
        return JointOptimizationWorkflowFailure(
            run_id=run_id, failure_code=WorkflowFailureCode.BASELINE_EVALUATION_FAILED,
            message=f"run_baseline_evaluation failed: {baseline_boundary.message}",
            details={"failure_code": baseline_boundary.failure_code.value, "upstream_details": baseline_boundary.details},
            pydoublet_result=pydoublet_result, audit=_audit(), created_at=workflow_created_at,
        )
    baseline_result: BaselineNetworkResult = baseline_boundary
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="run_baseline_evaluation", status="success"))

    # ── Stage 4: the full scenario x accepted-candidate product (Phase 4) ──
    screened_by_id = {sc.candidate_id: sc for sc in screened}
    joint_result = run_joint_optimization_full_product(
        pydoublet_result, blueprint, baseline_result, screened_by_id,
        coupling_assumptions=coupling_assumptions, injection_policy=injection_policy,
        tolerances=gate_tolerances, economic_assumptions=economic_assumptions,
    )
    for alt in joint_result.alternatives:
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

    return JointOptimizationWorkflowResult(
        run_id=run_id, pydoublet_result=pydoublet_result, joint_result=joint_result, screened_candidates=screened,
        audit=_audit(), created_at=workflow_created_at,
    )


def _hash_record_for_json_bytes(data: bytes) -> ArtifactHashRecord:
    """Mirrors workflow/artifacts.py::_hash_record_for_json_bytes() exactly
    -- reimplemented rather than imported, since that name is private to
    its own module (module docstring, "a deliberately separate
    function")."""
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


def write_joint_optimization_artifacts(
    result: JointOptimizationWorkflowBoundaryResult,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
) -> JointOptimizationManifestRecord:
    """Phase 4's own artifact bundle -- mirrors workflow/artifacts.py::
    write_workflow_artifacts()'s exact hashing/manifest pattern (byte
    SHA-256 always; scientific SHA-256 additionally normalized for JSON
    files) but for THIS module's own result shape and filename set. A
    deliberately separate function, not a generalization of
    write_workflow_artifacts() itself, so the already-hash-pinned
    single-scenario workflow's own artifact path is never put at risk by
    this addition."""
    hash_records: dict[str, ArtifactHashRecord] = {}

    pydoublet_input_bytes = canonical_raw_result_json_bytes(pydoublet_raw_result)
    (output_dir / PYDOUBLET_INPUT_FILENAME).write_bytes(pydoublet_input_bytes)
    hash_records[PYDOUBLET_INPUT_FILENAME] = _hash_record_for_json_bytes(pydoublet_input_bytes)

    config_snapshot_bytes = canonical_raw_result_json_bytes(config)
    (output_dir / CONFIG_SNAPSHOT_FILENAME).write_bytes(config_snapshot_bytes)
    hash_records[CONFIG_SNAPSHOT_FILENAME] = _hash_record_for_json_bytes(config_snapshot_bytes)

    joint_result_bytes = result.model_dump_json(indent=2).encode("utf-8")
    (output_dir / JOINT_RESULT_FILENAME).write_bytes(joint_result_bytes)
    hash_records[JOINT_RESULT_FILENAME] = _hash_record_for_json_bytes(joint_result_bytes)

    audit_bytes = result.audit.model_dump_json(indent=2).encode("utf-8")
    (output_dir / AUDIT_FILENAME).write_bytes(audit_bytes)
    hash_records[AUDIT_FILENAME] = _hash_record_for_json_bytes(audit_bytes)

    if isinstance(result, JointOptimizationWorkflowResult):
        extra: dict[str, bytes] = {
            GENERATED_CANDIDATES_FILENAME: render_generated_candidates_json(result.screened_candidates),
            SCREENED_ALTERNATIVES_FILENAME: render_screened_alternatives_json(result.joint_result),
            ALTERNATIVE_COMPARISON_CSV_FILENAME: render_alternative_comparison_csv(result.joint_result),
            PARETO_OR_RANKING_FILENAME: render_pareto_or_ranking_json(result.joint_result),
            JOINT_RECOMMENDATION_MD_FILENAME: render_joint_recommendation_markdown(result.joint_result),
        }
        for filename, data in extra.items():
            (output_dir / filename).write_bytes(data)
            hash_records[filename] = (
                _hash_record_for_json_bytes(data) if filename in _JSON_FILENAMES else _hash_record_for_plain_bytes(data)
            )

    bundle_scientific_sha256 = canonical_raw_result_sha256(
        {filename: record.scientific_sha256 for filename, record in sorted(hash_records.items())}
    )
    manifest = JointOptimizationManifestRecord(
        run_id=result.run_id, created_at=datetime.now(timezone.utc), files=hash_records,
        bundle_scientific_sha256=bundle_scientific_sha256,
    )
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest
