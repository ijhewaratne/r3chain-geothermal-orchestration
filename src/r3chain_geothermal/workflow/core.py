"""Deterministic workflow orchestrator (T2.4B1): the one function that
calls every earlier layer (T1.5B PyDoublet parsing, T2.1 HX adapter, T2.2
synthetic network, T2.3 candidate evaluation, T2.4A economics/ranking) in
the implementation plan's own fixed order (plan §14), producing a single
typed result and a full audit trail.

This module NEVER re-derives physics, NEVER re-checks a technical gate,
and NEVER calls PyDoublet as a subprocess -- it only sequences already-
published, already-independently-tested public functions from
`parsers`, `adapter`, `network`, and `economics`, and records what
happened. `stage_calls` on `WorkflowAuditRecord` records ORDERED
FUNCTION CALLS in this orchestration -- they are deliberately never
called "tool calls" anywhere in this module, its docstrings, or its
field names, since MCP tool wrapping is a separate, not-yet-built layer
(CLAUDE.md: "Keep PyDoublet, the adapter, pandapipes evaluation,
economics, MCP wrappers, and presentation outputs as separate layers").

## Fixed sequence (plan §14, your own 7 steps)

1. Parse and validate the raw PyDoublet result -- `parse_pydoublet_result()`.
2. Run the HX adapter -- `evaluate_heat_exchanger_coupling()`.
3. Build the synthetic-network blueprint -- `build_default_blueprint()`.
4. Evaluate the baseline -- `run_baseline_evaluation()`.
5. Evaluate C1-C4 independently, in `sorted()` order -- `evaluate_candidate()`
   once per candidate. **Never stops the workflow** -- both a success and
   a failure are recorded and the loop continues to the next candidate.
6. Compute economics only for feasible candidates.
7. Apply feasibility-first ranking.

Steps 6 and 7 are BOTH accomplished by one call to `rank_candidates()`
(T2.4A already partitions feasible/infeasible internally and computes
economics only for the feasible subset) -- this module never calls
`compute_candidate_economics()` directly; the per-candidate "economics
computed" stage-call records are DERIVED after the fact from
`ranking.ranked` (one entry per success) and `ranking.infeasible` (no
entry at all -- economics is never computed for an infeasible candidate).

Steps 1-4 are STOPPING conditions: a failure at any of them returns a
typed `WorkflowFailure` immediately, preserving whatever earlier stages
DID complete. Step 5's per-candidate outcomes and step 7's
"zero feasible candidates" outcome are both NORMAL, COMPLETED workflow
results -- `WorkflowResult.ranking.ranked` may legitimately be empty;
this is not, and must never be treated as, an error.

## Determinism

`run_id` is derived from FOUR canonical SHA-256 hashes (via
`hashing.canonical_raw_result_sha256` -- a generic canonical-JSON hasher
already used by T1.5B for its own `result_identifier`, reused here
unchanged): the raw PyDoublet result dict, the config dict, the
CALLER-SUPPLIED `SourceProvenance` (never inferred -- `calculation_mode`
gates whether `parse_pydoublet_result` even attempts to parse at all,
and `source_format_hint`/`source_pydoublet_commit` gate whether T1.5B's
legacy-field-correction logic is permitted, so provenance is
behaviour-changing input on the same footing as the raw result and
config, not metadata), and `WORKFLOW_CONTRACT_SCHEMA_VERSION` itself (so
a future schema change can never silently collide with an older run's
`run_id`). Changing ANY ONE of the four changes `run_id`; identical
inputs across all four always reproduce the identical `run_id` --
never from a timestamp or a filesystem path. No underlying
layer function (`parse_pydoublet_result`, `evaluate_heat_exchanger_coupling`,
`run_baseline_evaluation`, `evaluate_candidate`, `compute_candidate_economics`,
`rank_candidates`) accepts an injected clock -- each generates its own
`created_at` internally, exactly as before T2.4B (retrofitting six
already-committed, independently-tested functions was judged out of
proportion to this task). Only `run_workflow()`'s OWN top-level
`created_at`, and the one `created_at` it passes to
`build_default_blueprint()` (which DOES accept it), are controlled by the
injected `now` callable. Determinism is therefore achieved by EXCLUDING
every `created_at` occurrence -- at every nesting depth across the full
embedded result tree -- from any identity/comparison, not by making every
timestamp deterministic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ..adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from ..adapter.heat_exchanger import HeatExchangerCouplingFailure, HeatExchangerCouplingResult
from ..contracts import CouplingWarning, PyDoubletCouplingFailure, PyDoubletCouplingResult, SourceProvenance
from ..economics import EconomicAssumptions, RankingResult, rank_candidates
from ..hashing import canonical_raw_result_sha256
from ..network import (
    BaselineNetworkFailure,
    BaselineNetworkResult,
    CandidateEvaluationBoundaryResult,
    CandidateEvaluationFailure,
    CandidateEvaluationResult,
    GateTolerances,
    GeothermalInjectionPolicy,
    NetworkBlueprint,
    build_default_blueprint,
    evaluate_candidate,
    run_baseline_evaluation,
)
from ..parsers.pydoublet_parser import parse_pydoublet_result
from .errors import WorkflowFailureCode

WORKFLOW_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

WORKFLOW_RUN_ID_PREFIX = "r3chain-run-"
WORKFLOW_RUN_ID_HASH_LENGTH = 16
"""Mirrors T1.5B's own RESULT_IDENTIFIER_PREFIX/RESULT_IDENTIFIER_HASH_LENGTH
construction exactly (contracts/coupling_result.py) -- a stable prefix
plus a truncated canonical-content hash, never a timestamp or path."""


def compute_source_provenance_sha256(source_provenance: SourceProvenance) -> str:
    """Canonical SHA-256 of `source_provenance`'s own content (all four
    fields: source_pydoublet_commit, source_format_hint, calculation_mode,
    scenario_identifier) -- SourceProvenance is BEHAVIOUR-CHANGING input
    (calculation_mode gates whether parse_pydoublet_result even attempts
    to parse at all; source_format_hint/source_pydoublet_commit gate
    whether legacy-field-correction logic is permitted, T1.5B), so it
    participates in run_id on the same footing as the raw PyDoublet
    result and config -- never silently excluded."""
    return canonical_raw_result_sha256(source_provenance.model_dump(mode="json"))


def compute_run_id(input_sha256: str, config_sha256: str, source_provenance_sha256: str, contract_schema_version: str) -> str:
    """Pure, content-derived from FOUR canonical hashes -- the raw
    PyDoublet result, the config, the source provenance (see
    compute_source_provenance_sha256), and this module's own
    WORKFLOW_CONTRACT_SCHEMA_VERSION (so a future schema change can never
    silently collide with an older run's run_id even given identical
    input/config/provenance). The SAME four hashes always produce the
    SAME run_id, regardless of when or where run_workflow() executes;
    changing ANY ONE of the four changes run_id.

    Public (T5.1A): mcp_server/tools.py imports this directly to learn a
    run's run_id BEFORE deciding whether to call run_workflow() at all
    (GEO_REGISTRY's reuse-instead-of-rerun path) -- reusing this exact
    function, rather than re-deriving the same formula independently,
    guarantees the MCP server's run_id can never silently drift from
    run_workflow()'s own."""
    combined = canonical_raw_result_sha256({
        "input_sha256": input_sha256, "config_sha256": config_sha256,
        "source_provenance_sha256": source_provenance_sha256, "contract_schema_version": contract_schema_version,
    })
    return f"{WORKFLOW_RUN_ID_PREFIX}{combined[:WORKFLOW_RUN_ID_HASH_LENGTH]}"


class StageCallRecord(BaseModel):
    """One ordered function call in the fixed sequence -- deliberately
    never called a "tool call" (module docstring)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    order: int
    """1-based, matches this record's position in stage_calls -- explicit
    and redundant with list order, for JSON consumers that don't want to
    rely on array-index semantics."""
    stage_name: str
    status: Literal["success", "failure"]
    failure_code: str | None = None
    message: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "StageCallRecord":
        if self.order < 1:
            raise ValueError(f"order must be >= 1, got {self.order!r}")
        if self.status == "success" and (self.failure_code is not None or self.message is not None):
            raise ValueError("a success stage_call must not carry failure_code/message")
        if self.status == "failure" and self.failure_code is None:
            raise ValueError("a failure stage_call must carry failure_code")
        return self


class WorkflowWarningRecord(BaseModel):
    """One warning, tagged with the stage it originated from -- an
    additional flat index; the warning is NOT removed from the embedded
    sub-result it also lives on."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    stage: str
    warning: CouplingWarning


class WorkflowAuditRecord(BaseModel):
    """The full provenance/process trail for one run -- extracted
    verbatim to audit.json by artifacts.py, and also embedded on
    WorkflowResult/WorkflowFailure as `audit` so the scientific payload
    and its own audit trail can never drift apart silently.

    `source_provenance` is embedded here VERBATIM (all four fields:
    source_pydoublet_commit, source_format_hint, calculation_mode,
    scenario_identifier) -- this IS the "complete, independently hashed
    input section" preservation your review asked for (the alternative
    to a separate source_provenance.json file); `source_provenance_sha256`
    is the independent hash of that same section, checked against run_id
    below."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    run_id: str
    contract_schema_version: str
    created_at: datetime
    input_sha256: str
    config_sha256: str
    source_provenance: SourceProvenance
    source_provenance_sha256: str
    stage_calls: list[StageCallRecord]
    coupling_assumptions: CouplingAssumptions
    gate_tolerances: GateTolerances
    injection_policy: GeothermalInjectionPolicy
    economic_assumptions: EconomicAssumptions
    warnings: list[WorkflowWarningRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "WorkflowAuditRecord":
        errors: list[str] = []
        expected_provenance_hash = compute_source_provenance_sha256(self.source_provenance)
        if self.source_provenance_sha256 != expected_provenance_hash:
            errors.append("source_provenance_sha256 does not match recomputation from source_provenance")
        expected_run_id = compute_run_id(
            self.input_sha256, self.config_sha256, self.source_provenance_sha256, self.contract_schema_version,
        )
        if self.run_id != expected_run_id:
            errors.append(
                "run_id does not match recomputation from input_sha256/config_sha256/"
                "source_provenance_sha256/contract_schema_version"
            )
        if not self.stage_calls:
            errors.append("stage_calls must not be empty")
        else:
            expected_orders = list(range(1, len(self.stage_calls) + 1))
            actual_orders = [sc.order for sc in self.stage_calls]
            if actual_orders != expected_orders:
                errors.append("stage_calls.order values are not contiguous 1..N in list order")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class WorkflowResult(BaseModel):
    """A completed workflow run -- meaning the fixed sequence finished,
    NOT that a candidate was recommended. `ranking.ranked` may
    legitimately be empty (zero feasible candidates); that is a normal,
    complete result, never an error."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    run_id: str
    pydoublet_result: PyDoubletCouplingResult
    coupling_result: HeatExchangerCouplingResult
    blueprint: NetworkBlueprint
    baseline_result: BaselineNetworkResult
    candidate_results: dict[str, CandidateEvaluationBoundaryResult]
    ranking: RankingResult
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "WorkflowResult":
        errors: list[str] = []
        if self.run_id != self.audit.run_id:
            errors.append("run_id does not match audit.run_id")
        if set(self.candidate_results.keys()) != set(sorted(self.blueprint.candidates.keys())):
            errors.append("candidate_results keys do not match blueprint.candidates keys")

        ranked_ids = {entry.candidate_id for entry in self.ranking.ranked}
        infeasible_ids = {entry.candidate_id for entry in self.ranking.infeasible}
        feasible_result_ids = {
            cid for cid, result in self.candidate_results.items() if isinstance(result, CandidateEvaluationResult)
        }
        infeasible_result_ids = {
            cid for cid, result in self.candidate_results.items() if isinstance(result, CandidateEvaluationFailure)
        }
        if ranked_ids != feasible_result_ids:
            errors.append("ranking.ranked does not match the feasible subset of candidate_results")
        if infeasible_ids != infeasible_result_ids:
            errors.append("ranking.infeasible does not match the infeasible subset of candidate_results")

        stage_names = {sc.stage_name for sc in self.audit.stage_calls}
        for cid in self.candidate_results:
            if f"evaluate_candidate:{cid}" not in stage_names:
                errors.append(f"audit.stage_calls is missing evaluate_candidate:{cid}")
        for cid in ranked_ids:
            if f"compute_candidate_economics:{cid}" not in stage_names:
                errors.append(f"audit.stage_calls is missing compute_candidate_economics:{cid}")
        for cid in infeasible_ids:
            if f"compute_candidate_economics:{cid}" in stage_names:
                errors.append(f"audit.stage_calls has compute_candidate_economics:{cid} for an infeasible candidate")

        if errors:
            raise ValueError("; ".join(errors))
        return self


class WorkflowFailure(BaseModel):
    """A workflow that stopped before candidate evaluation began.
    Whichever of pydoublet_result/coupling_result/blueprint DID complete
    before the stop is preserved (None otherwise) -- a failure is still
    fully auditable, the same rule as every earlier layer."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"

    run_id: str
    failure_code: WorkflowFailureCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    pydoublet_result: PyDoubletCouplingResult | None = None
    coupling_result: HeatExchangerCouplingResult | None = None
    blueprint: NetworkBlueprint | None = None
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "WorkflowFailure":
        errors: list[str] = []
        if self.run_id != self.audit.run_id:
            errors.append("run_id does not match audit.run_id")
        if self.failure_code == WorkflowFailureCode.PYDOUBLET_PARSE_FAILED and self.pydoublet_result is not None:
            errors.append("PYDOUBLET_PARSE_FAILED must not carry a pydoublet_result")
        if self.failure_code != WorkflowFailureCode.PYDOUBLET_PARSE_FAILED and self.pydoublet_result is None:
            errors.append(f"{self.failure_code} must carry a pydoublet_result (an earlier stage than the one that failed)")
        if self.failure_code in (
            WorkflowFailureCode.BLUEPRINT_CONSTRUCTION_FAILED, WorkflowFailureCode.BASELINE_EVALUATION_FAILED,
        ) and self.coupling_result is None:
            errors.append(f"{self.failure_code} must carry a coupling_result")
        if self.failure_code == WorkflowFailureCode.BASELINE_EVALUATION_FAILED and self.blueprint is None:
            errors.append("BASELINE_EVALUATION_FAILED must carry a blueprint")
        if errors:
            raise ValueError("; ".join(errors))
        return self


WorkflowBoundaryResult = Annotated[Union[WorkflowResult, WorkflowFailure], Field(discriminator="status")]
_boundary_result_adapter: TypeAdapter = TypeAdapter(WorkflowBoundaryResult)


def parse_workflow_result_json(json_str: str) -> WorkflowBoundaryResult:
    return _boundary_result_adapter.validate_json(json_str)


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_blueprint_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    """Pure mapping from config -> build_default_blueprint()'s kwargs
    (no such mapping existed anywhere in the codebase before T2.4B1 --
    every prior test file hand-built these kwargs itself)."""
    network_cfg = config["network"]
    coupling_cfg = config["coupling_assumptions"]
    return dict(
        consumer_demands_kw={c["id"]: c["demand_kw"] for c in network_cfg["consumers"]},
        trunk_pipe_dn_mm=network_cfg["pipe_sizing"]["trunk_pipe_dn_mm"],
        branch_pipe_dn_mm=network_cfg["pipe_sizing"]["branch_pipe_dn_mm"],
        design_delta_t_k=network_cfg["design_delta_t_k"],
        supply_temperature_c=coupling_cfg["dh_supply_temperature_c"],
        return_temperature_c=coupling_cfg["dh_return_temperature_c"],
        ground_temperature_c=network_cfg["ground_temperature_c"],
        pipe_heat_transfer_coefficient_w_per_m2k=network_cfg["pipe_sizing"]["pipe_heat_transfer_coefficient_w_per_m2k"],
        pipe_roughness_mm=network_cfg["pipe_roughness_mm"],
        p_supply_bar_abs=network_cfg["p_supply_bar_abs"],
        pump_pressure_lift_bar=network_cfg["circulation_pump"]["pressure_lift_bar"],
    )


class WorkflowConfigurationError(Exception):
    """Raised ONLY by `validate_config_structure()` -- a `config` dict
    that is structurally invalid for `run_workflow()`: a missing section,
    a wrong field type, or a value one of the typed assumption-snapshot
    models itself rejects (`CouplingAssumptions`/`GateTolerances`/
    `GeothermalInjectionPolicy`/`EconomicAssumptions.from_config_dict()`,
    or `_build_blueprint_kwargs()`).

    Deliberately narrow, and deliberately NOT raised for anything else
    `run_workflow()` might unexpectedly fail on. `run_workflow()` itself
    never raises this -- callers validate `config` with
    `validate_config_structure()` BEFORE calling `run_workflow()`, so
    that a genuinely malformed config (this class, mapped to one exit
    code by a caller such as `cli.py`) stays distinguishable from a
    truly unexpected internal failure during a validated run (a solver
    defect, a programming bug -- mapped to a DIFFERENT exit code). A
    single broad `except (KeyError, TypeError, ValueError, ValidationError)`
    wrapped around the whole `run_workflow()` call would conflate the
    two; this class exists specifically so callers do not have to."""


_CONFIG_STRUCTURE_ERRORS: tuple[type[Exception], ...] = (KeyError, TypeError, ValueError, ValidationError)


def validate_config_structure(config: dict[str, Any]) -> None:
    """Attempts to construct every config-derived object `run_workflow()`
    itself builds from `config` -- the four assumption-snapshot
    classmethods plus `_build_blueprint_kwargs()` -- WITHOUT running the
    workflow. Raises `WorkflowConfigurationError` (never a bare
    `KeyError`/`TypeError`/`ValueError`/pydantic `ValidationError`) if
    any of them fails.

    A successful call is a guarantee: `run_workflow()` will not itself
    raise for a config-STRUCTURE reason afterward (the exact same
    construction calls run internally, on the exact same already-loaded
    `config` dict). Callers (e.g. `cli.py`) can therefore validate
    `--config` narrowly, before calling `run_workflow()`, and treat any
    exception that DOES still escape `run_workflow()` as a genuinely
    unexpected failure -- never silently reclassified as "your config is
    wrong"."""
    try:
        CouplingAssumptions.from_config_dict(config)
        GateTolerances.from_config_dict(config)
        GeothermalInjectionPolicy.from_config_dict(config)
        EconomicAssumptions.from_config_dict(config)
        _build_blueprint_kwargs(config)
    except _CONFIG_STRUCTURE_ERRORS as exc:
        raise WorkflowConfigurationError(f"config is structurally invalid: {exc!r}") from exc


def run_workflow(
    pydoublet_raw_result: dict[str, Any] | None,
    config: dict[str, Any],
    *,
    source_provenance: SourceProvenance,
    now: Callable[[], datetime] = _default_now,
) -> WorkflowBoundaryResult:
    """Run the fixed 7-step sequence (module docstring) once. Never
    raises for any of the 4 stopping-failure conditions or any
    per-candidate outcome; the one exception it catches itself is
    build_default_blueprint()'s ValueError on a malformed config."""
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

    def _audit(extra_stage_calls: list[StageCallRecord] | None = None) -> WorkflowAuditRecord:
        return WorkflowAuditRecord(
            run_id=run_id, contract_schema_version=WORKFLOW_CONTRACT_SCHEMA_VERSION, created_at=workflow_created_at,
            input_sha256=input_sha256, config_sha256=config_sha256, source_provenance=source_provenance,
            source_provenance_sha256=source_provenance_sha256, stage_calls=stage_calls + (extra_stage_calls or []),
            coupling_assumptions=coupling_assumptions, gate_tolerances=gate_tolerances,
            injection_policy=injection_policy, economic_assumptions=economic_assumptions, warnings=list(warnings),
        )

    # ── Stage 1: parse and validate the raw PyDoublet result ──
    pydoublet_boundary = parse_pydoublet_result(pydoublet_raw_result, source_provenance=source_provenance)
    if isinstance(pydoublet_boundary, PyDoubletCouplingFailure):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="parse_pydoublet_result", status="failure",
            failure_code=pydoublet_boundary.failure_code.value, message=pydoublet_boundary.message,
        ))
        return WorkflowFailure(
            run_id=run_id, failure_code=WorkflowFailureCode.PYDOUBLET_PARSE_FAILED,
            message=f"parse_pydoublet_result failed: {pydoublet_boundary.message}",
            details={"failure_code": pydoublet_boundary.failure_code.value, "upstream_details": pydoublet_boundary.details},
            audit=_audit(), created_at=workflow_created_at,
        )
    pydoublet_result: PyDoubletCouplingResult = pydoublet_boundary
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="parse_pydoublet_result", status="success"))

    # ── Stage 2: run the HX adapter ──
    coupling_boundary = evaluate_heat_exchanger_coupling(pydoublet_result, assumptions=coupling_assumptions)
    if isinstance(coupling_boundary, HeatExchangerCouplingFailure):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="evaluate_heat_exchanger_coupling", status="failure",
            failure_code=coupling_boundary.failure_code.value, message=coupling_boundary.message,
        ))
        return WorkflowFailure(
            run_id=run_id, failure_code=WorkflowFailureCode.HEAT_EXCHANGER_COUPLING_FAILED,
            message=f"evaluate_heat_exchanger_coupling failed: {coupling_boundary.message}",
            details={"failure_code": coupling_boundary.failure_code.value, "upstream_details": coupling_boundary.details},
            pydoublet_result=pydoublet_result, audit=_audit(), created_at=workflow_created_at,
        )
    coupling_result: HeatExchangerCouplingResult = coupling_boundary
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="evaluate_heat_exchanger_coupling", status="success"))
    warnings.extend(WorkflowWarningRecord(stage="evaluate_heat_exchanger_coupling", warning=w) for w in coupling_result.warnings)

    # ── Stage 3: build the synthetic-network blueprint ──
    try:
        blueprint = build_default_blueprint(created_at=workflow_created_at, **_build_blueprint_kwargs(config))
    except ValueError as exc:
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="build_blueprint", status="failure",
            failure_code=WorkflowFailureCode.BLUEPRINT_CONSTRUCTION_FAILED.value, message=str(exc),
        ))
        return WorkflowFailure(
            run_id=run_id, failure_code=WorkflowFailureCode.BLUEPRINT_CONSTRUCTION_FAILED,
            message=f"build_default_blueprint raised ValueError: {exc}", details={"exception_message": str(exc)},
            pydoublet_result=pydoublet_result, coupling_result=coupling_result,
            audit=_audit(), created_at=workflow_created_at,
        )
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="build_blueprint", status="success"))

    # ── Stage 4: evaluate the baseline ──
    baseline_boundary = run_baseline_evaluation(blueprint, tolerances=gate_tolerances)
    if isinstance(baseline_boundary, BaselineNetworkFailure):
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name="run_baseline_evaluation", status="failure",
            failure_code=baseline_boundary.failure_code.value, message=baseline_boundary.message,
        ))
        return WorkflowFailure(
            run_id=run_id, failure_code=WorkflowFailureCode.BASELINE_EVALUATION_FAILED,
            message=f"run_baseline_evaluation failed: {baseline_boundary.message}",
            details={"failure_code": baseline_boundary.failure_code.value, "upstream_details": baseline_boundary.details},
            pydoublet_result=pydoublet_result, coupling_result=coupling_result, blueprint=blueprint,
            audit=_audit(), created_at=workflow_created_at,
        )
    baseline_result: BaselineNetworkResult = baseline_boundary
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="run_baseline_evaluation", status="success"))

    # ── Stage 5: evaluate C1-C4 independently, sorted order, never stops ──
    candidate_results: dict[str, CandidateEvaluationBoundaryResult] = {}
    for candidate_id in sorted(blueprint.candidates):
        candidate_result = evaluate_candidate(
            coupling_result, blueprint, blueprint.candidates[candidate_id], baseline_result,
            injection_policy=injection_policy, tolerances=gate_tolerances,
        )
        candidate_results[candidate_id] = candidate_result
        if isinstance(candidate_result, CandidateEvaluationResult):
            stage_calls.append(StageCallRecord(
                order=len(stage_calls) + 1, stage_name=f"evaluate_candidate:{candidate_id}", status="success",
            ))
            warnings.extend(
                WorkflowWarningRecord(stage=f"evaluate_candidate:{candidate_id}", warning=w)
                for w in candidate_result.warnings
            )
        else:
            stage_calls.append(StageCallRecord(
                order=len(stage_calls) + 1, stage_name=f"evaluate_candidate:{candidate_id}", status="failure",
                failure_code=candidate_result.failure_code.value, message=candidate_result.message,
            ))

    # ── Steps 6+7: economics (feasible only) + feasibility-first ranking,
    # both accomplished by one rank_candidates() call (module docstring). ──
    ranking = rank_candidates(
        candidate_results, baseline_result, economic_assumptions=economic_assumptions, tolerances=gate_tolerances,
    )
    for entry in ranking.ranked:
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name=f"compute_candidate_economics:{entry.candidate_id}", status="success",
        ))
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="rank_candidates", status="success"))

    return WorkflowResult(
        run_id=run_id, pydoublet_result=pydoublet_result, coupling_result=coupling_result, blueprint=blueprint,
        baseline_result=baseline_result, candidate_results=candidate_results, ranking=ranking,
        audit=_audit(), created_at=workflow_created_at,
    )
