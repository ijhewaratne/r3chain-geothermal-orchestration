"""Research-experiment orchestrator (Phase 5, R3-CHAIN Final Research-Alignment
Implementation Specification).

## Reuse, not reinvention

This orchestrator calls `run_joint_workflow_v2()` UNCHANGED to load and
validate the referenced v2 study package, parse the golden PyDoublet
result, generate site routes, and enumerate compatible alternatives -- it
never re-implements any of that. For every compatible alternative it then
calls, in order: `workflow.load_state_evaluation.evaluate_alternative_across_load_states()`
(Phase 2), `economics.annualized_system_costing.compute_annualized_system_economics()`
(Phase 3), and the various `decision.research_comparison` functions
(Phase 4) -- all reused unchanged. This module's only new logic is the
staged orchestration sequence itself and the top-level result/failure
contract.

## Config shape

`config["research_experiment"]` extends the SAME config dict
`run_joint_workflow_v2()` already consumes (it must also carry
`joint_study_v2`, `coupling_assumptions`, `gates`, `network`, `economics`
-- exactly `config/demo_assumptions_joint_study_v2.json`'s own shape) with
one new section shaped like `data_contracts.research_experiment
.ResearchExperimentConfig`. `is_research_experiment_enabled()` is the
single explicit switch, absent from every canonical/v1/v2-only config, so
none of those workflows are affected (matches
`is_joint_study_v2_enabled()`'s own convention exactly)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..adapter import CouplingAssumptions
from ..contracts import SourceProvenance
from ..data_contracts.research_experiment import (
    RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION,
    AnnualizedAlternativeEconomicResult,
    BaselineComparisonResult,
    ResearchExperimentConfig,
    ResearchExperimentDecisionSummary,
    validate_load_state_durations,
)
from ..decision.joint_policy import JointDecisionResult
from ..decision.research_comparison import (
    compare_baselines,
    decide_integrated,
    rank_geothermal_only_baseline,
    rank_network_only_baseline,
    run_sensitivity_study,
    select_fixed_reference_scenario,
)
from ..economics.annualized_system_costing import compute_annualized_system_economics
from ..economics.assumptions import EconomicAssumptions
from ..economics.costing import CandidateEconomicResult
from ..economics.joint_costing import load_base_assumptions
from ..hashing import canonical_raw_result_sha256
from ..network import GateTolerances, GeothermalInjectionPolicy
from .core import (
    WorkflowAuditRecord,
    WorkflowWarningRecord,
    StageCallRecord,
    _default_now,
    compute_run_id,
    compute_source_provenance_sha256,
)
from .joint_workflow_v2 import JointWorkflowV2Failure, JointWorkflowV2Result, run_joint_workflow_v2
from .load_state_evaluation import evaluate_alternative_across_load_states

RESEARCH_EXPERIMENT_WORKFLOW_CONTRACT_SCHEMA_VERSION = RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION


def is_research_experiment_enabled(config: dict[str, Any]) -> bool:
    """The single, explicit config switch (matches
    is_joint_study_v2_enabled()'s own convention) -- absent from
    config/demo_assumptions.json and config/demo_assumptions_joint_study_v2.json,
    so neither the canonical nor the v2-only workflow is affected."""
    return bool(config.get("research_experiment", {}).get("enabled", False))


class ResearchExperimentAlternativeSummary(BaseModel):
    """One compatible alternative's annualized-economics outcome plus its
    identity's site/attachment/resource-scenario, kept together for the
    export/comparison layers so they never need a second lookup into the
    referenced v2 package."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    alternative_id: str
    surface_site_id: str
    attachment_id: str
    resource_scenario_id: str
    annualized_economics: AnnualizedAlternativeEconomicResult


class ResearchExperimentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = RESEARCH_EXPERIMENT_WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["success"] = "success"

    run_id: str
    research_config: ResearchExperimentConfig
    referenced_v2_result: JointWorkflowV2Result
    alternative_summaries: list[ResearchExperimentAlternativeSummary]
    integrated_decision: JointDecisionResult
    geothermal_only_preferred_site_id: str | None
    network_only_preferred_attachment_id: str | None
    baseline_comparison: BaselineComparisonResult
    sensitivity_decision_summary: ResearchExperimentDecisionSummary
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "ResearchExperimentResult":
        if self.run_id != self.audit.run_id:
            raise ValueError("run_id does not match audit.run_id")
        return self


class ResearchExperimentFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = RESEARCH_EXPERIMENT_WORKFLOW_CONTRACT_SCHEMA_VERSION
    status: Literal["failure"] = "failure"

    run_id: str
    failure_code: str
    stage: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    audit: WorkflowAuditRecord
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "ResearchExperimentFailure":
        if self.run_id != self.audit.run_id:
            raise ValueError("run_id does not match audit.run_id")
        return self


ResearchExperimentBoundaryResult = Annotated[
    Union[ResearchExperimentResult, ResearchExperimentFailure], Field(discriminator="status"),
]
_boundary_result_adapter: TypeAdapter = TypeAdapter(ResearchExperimentBoundaryResult)


def parse_research_experiment_result_json(json_str: str) -> ResearchExperimentBoundaryResult:
    return _boundary_result_adapter.validate_json(json_str)


def _build_audit(
    *, run_id: str, created_at: datetime, input_sha256: str, config_sha256: str,
    source_provenance: SourceProvenance, source_provenance_sha256: str,
    stage_calls: list[StageCallRecord], warnings: list[WorkflowWarningRecord], config: dict[str, Any],
) -> WorkflowAuditRecord:
    """Same construction shape as workflow.joint_workflow_v2's own private
    `_audit_stub()` -- independently reimplemented (this project's
    established cross-module convention for a private helper) with this
    module's own `RESEARCH_EXPERIMENT_WORKFLOW_CONTRACT_SCHEMA_VERSION`."""
    return WorkflowAuditRecord(
        run_id=run_id, contract_schema_version=RESEARCH_EXPERIMENT_WORKFLOW_CONTRACT_SCHEMA_VERSION,
        created_at=created_at, input_sha256=input_sha256, config_sha256=config_sha256,
        source_provenance=source_provenance, source_provenance_sha256=source_provenance_sha256,
        stage_calls=list(stage_calls),
        coupling_assumptions=CouplingAssumptions.from_config_dict(config),
        gate_tolerances=GateTolerances.from_config_dict(config),
        injection_policy=GeothermalInjectionPolicy.from_config_dict(config),
        economic_assumptions=EconomicAssumptions.from_config_dict(config), warnings=list(warnings),
    )


def resolve_research_experiment_run_id(
    pydoublet_raw_result: dict[str, Any], config: dict[str, Any], *, source_provenance: SourceProvenance,
) -> str:
    """Public, cheap (no simulation, no filesystem access) helper for a
    caller that needs this run's stable `run_id` BEFORE deciding whether
    to actually invoke `run_research_experiment()` -- the MCP tool layer's
    own pre-registry-lookup step, mirroring
    `workflow.joint_workflow_v2.resolve_joint_workflow_v2_run_id()`'s own
    role. Unlike that function, this one never needs to load any package
    to compute the id (this layer's own run_id never folds in package
    content -- only input/config/provenance/schema-version, exactly what
    `run_research_experiment()` itself hashes), so there is nothing here
    that can fail."""
    input_sha256 = canonical_raw_result_sha256(pydoublet_raw_result)
    config_sha256 = canonical_raw_result_sha256(config)
    source_provenance_sha256 = compute_source_provenance_sha256(source_provenance)
    return compute_run_id(
        input_sha256, config_sha256, source_provenance_sha256, RESEARCH_EXPERIMENT_WORKFLOW_CONTRACT_SCHEMA_VERSION,
    )


def run_research_experiment(
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    *,
    source_provenance: SourceProvenance,
    package_root: Path,
    expected_raw_sha256: str | None = None,
    now: Callable[[], datetime] = _default_now,
) -> ResearchExperimentBoundaryResult:
    """Never raises for any of its named stopping conditions -- matches
    run_joint_workflow_v2()'s own discipline (WF-003)."""
    workflow_created_at = now()
    input_sha256 = canonical_raw_result_sha256(pydoublet_raw_result)
    config_sha256 = canonical_raw_result_sha256(config)
    source_provenance_sha256 = compute_source_provenance_sha256(source_provenance)
    run_id = compute_run_id(
        input_sha256, config_sha256, source_provenance_sha256, RESEARCH_EXPERIMENT_WORKFLOW_CONTRACT_SCHEMA_VERSION,
    )

    stage_calls: list[StageCallRecord] = []
    warnings: list[WorkflowWarningRecord] = []

    def _audit() -> WorkflowAuditRecord:
        return _build_audit(
            run_id=run_id, created_at=workflow_created_at, input_sha256=input_sha256, config_sha256=config_sha256,
            source_provenance=source_provenance, source_provenance_sha256=source_provenance_sha256,
            stage_calls=stage_calls, warnings=warnings, config=config,
        )

    # ── Stage 0: parse this layer's own config section ──
    # config["research_experiment"] carries documentation-only keys ("enabled",
    # "_status", "_note", and "*_note" companions) alongside the typed fields,
    # matching this project's established config-file convention (e.g.
    # config["gates"]/config["network"] read via plain dict access elsewhere,
    # which silently tolerates such keys) -- ResearchExperimentConfig's own
    # extra="forbid" would reject them, so only the model's own declared
    # top-level fields are passed through. "enabled" itself is never part of
    # this model (mirrors joint_study_v2.enabled, read directly off the
    # config dict by is_research_experiment_enabled(), never part of
    # JointStudyPackage either).
    try:
        raw_section = config.get("research_experiment", {})
        research_config = ResearchExperimentConfig.model_validate(
            {k: v for k, v in raw_section.items() if k in ResearchExperimentConfig.model_fields}
        )
    except Exception as exc:  # noqa: BLE001 -- config-structure errors are an expected stopping condition here
        stage_calls.append(StageCallRecord(
            order=1, stage_name="parse_research_experiment_config", status="failure",
            failure_code="RESEARCH_EXPERIMENT_CONFIG_INVALID", message=str(exc),
        ))
        return ResearchExperimentFailure(
            run_id=run_id, failure_code="RESEARCH_EXPERIMENT_CONFIG_INVALID", stage="parse_research_experiment_config",
            message=f"config['research_experiment'] failed validation: {exc}", details={"exception_message": str(exc)},
            audit=_audit(), created_at=workflow_created_at,
        )
    stage_calls.append(StageCallRecord(order=1, stage_name="parse_research_experiment_config", status="success"))

    # ── Stage 1: reuse run_joint_workflow_v2() wholesale ──
    v2_boundary = run_joint_workflow_v2(
        pydoublet_raw_result, config, source_provenance=source_provenance, package_root=package_root,
        expected_raw_sha256=expected_raw_sha256, now=now,
    )
    if isinstance(v2_boundary, JointWorkflowV2Failure):
        stage_calls.append(StageCallRecord(
            order=2, stage_name="run_joint_workflow_v2", status="failure",
            failure_code=v2_boundary.failure_code, message=v2_boundary.message,
        ))
        return ResearchExperimentFailure(
            run_id=run_id, failure_code=v2_boundary.failure_code, stage=f"run_joint_workflow_v2:{v2_boundary.stage}",
            message=f"the referenced v2 joint workflow did not complete: {v2_boundary.message}",
            details=v2_boundary.details, audit=_audit(), created_at=workflow_created_at,
        )
    v2_result: JointWorkflowV2Result = v2_boundary
    stage_calls.append(StageCallRecord(order=2, stage_name="run_joint_workflow_v2", status="success"))

    # ── Stage 2: provenance cross-check (the referenced package must match) ──
    declared_package_path = config.get("joint_study_v2", {}).get("package_path")
    if research_config.referenced_study_package_relative_path != declared_package_path:
        stage_calls.append(StageCallRecord(
            order=3, stage_name="verify_referenced_study_package", status="failure",
            failure_code="RESEARCH_EXPERIMENT_PACKAGE_REFERENCE_MISMATCH",
            message=f"research_experiment.referenced_study_package_relative_path "
                    f"({research_config.referenced_study_package_relative_path!r}) does not match "
                    f"joint_study_v2.package_path ({declared_package_path!r})",
        ))
        return ResearchExperimentFailure(
            run_id=run_id, failure_code="RESEARCH_EXPERIMENT_PACKAGE_REFERENCE_MISMATCH",
            stage="verify_referenced_study_package",
            message="the research-experiment config references a different study package than "
                    "joint_study_v2.package_path names",
            details={
                "referenced_study_package_relative_path": research_config.referenced_study_package_relative_path,
                "joint_study_v2_package_path": declared_package_path,
            },
            audit=_audit(), created_at=workflow_created_at,
        )
    stage_calls.append(StageCallRecord(order=3, stage_name="verify_referenced_study_package", status="success"))

    # ── Stage 3: per-alternative load-state evaluation + annualized economics ──
    coupling_assumptions = CouplingAssumptions.from_config_dict(config)
    injection_policy = GeothermalInjectionPolicy.from_config_dict(config)
    tolerances = GateTolerances.from_config_dict(config)
    base_assumptions = load_base_assumptions(v2_result.package.economics, package_root)

    duration_errors = validate_load_state_durations(
        research_config.load_states, annual_operating_hours=base_assumptions.annual_full_load_hours,
    )
    if duration_errors:
        stage_calls.append(StageCallRecord(
            order=4, stage_name="validate_load_state_durations", status="failure",
            failure_code="RESEARCH_EXPERIMENT_LOAD_STATE_DURATIONS_INVALID", message="; ".join(duration_errors),
        ))
        return ResearchExperimentFailure(
            run_id=run_id, failure_code="RESEARCH_EXPERIMENT_LOAD_STATE_DURATIONS_INVALID",
            stage="validate_load_state_durations",
            message=f"declared load_states are invalid against the referenced base economics' own "
                    f"annual_full_load_hours ({base_assumptions.annual_full_load_hours!r}): {'; '.join(duration_errors)}",
            details={"errors": duration_errors}, audit=_audit(), created_at=workflow_created_at,
        )
    stage_calls.append(StageCallRecord(order=4, stage_name="validate_load_state_durations", status="success"))

    scenarios_by_key = {(s.scenario_id, s.site_id): s for s in v2_result.package.resource_scenarios}
    routes_by_id = {r.route_id: r for r in v2_result.routes}
    attachments_by_id = {a.attachment_id: a for a in v2_result.package.network_attachments}
    designs_by_id = {d.design_option_id: d for d in v2_result.package.design_options}

    alternative_summaries: list[ResearchExperimentAlternativeSummary] = []
    annualized_by_id: dict[str, AnnualizedAlternativeEconomicResult] = {}
    capex_economics_by_id: dict[str, CandidateEconomicResult | None] = {}
    site_by_id: dict[str, str] = {}
    attachment_by_id: dict[str, str] = {}
    resource_scenario_by_id: dict[str, str] = {}

    for alt in v2_result.alternatives:
        identity = alt.identity
        scenario = scenarios_by_key[(identity.resource_scenario_id, identity.surface_site_id)]
        route = routes_by_id[identity.route_id]
        attachment = attachments_by_id[identity.attachment_id]
        design = designs_by_id[identity.design_option_id]

        outcome = evaluate_alternative_across_load_states(
            identity, scenario, route, attachment, design, v2_result.pydoublet_result, config, base_assumptions,
            research_config.load_states, coupling_assumptions=coupling_assumptions, injection_policy=injection_policy,
            tolerances=tolerances,
        )
        annualized = compute_annualized_system_economics(
            identity.alternative_id, outcome.load_state_results, outcome.representative_capex_economics,
            assumptions=base_assumptions,
        )
        stage_calls.append(StageCallRecord(
            order=len(stage_calls) + 1, stage_name=f"evaluate_alternative_across_load_states:{identity.alternative_id}",
            status="success" if annualized.computable else "failure",
            failure_code=None if annualized.computable else "RESEARCH_EXPERIMENT_ALTERNATIVE_NOT_COMPUTABLE",
            message=None if annualized.computable else annualized.non_computable_reason,
        ))

        annualized_by_id[identity.alternative_id] = annualized
        capex_economics_by_id[identity.alternative_id] = outcome.representative_capex_economics
        site_by_id[identity.alternative_id] = identity.surface_site_id
        attachment_by_id[identity.alternative_id] = identity.attachment_id
        resource_scenario_by_id[identity.alternative_id] = identity.resource_scenario_id
        alternative_summaries.append(ResearchExperimentAlternativeSummary(
            alternative_id=identity.alternative_id, surface_site_id=identity.surface_site_id,
            attachment_id=identity.attachment_id, resource_scenario_id=identity.resource_scenario_id,
            annualized_economics=annualized,
        ))

    # ── Stage 4: integrated decision (reuse, unchanged) ──
    integrated_decision = decide_integrated(annualized_by_id, research_config.decision_policy)
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="decide_integrated", status="success"))
    integrated_has_any_feasible = any(a.computable for a in annualized_by_id.values())

    # ── Stage 5: geothermal-only baseline ──
    geo_only_preferred_site, geo_only_has_any_rankable, _ = rank_geothermal_only_baseline(
        v2_result.package.resource_scenarios, v2_result.pydoublet_result,
        coupling_assumptions=coupling_assumptions, base_assumptions=base_assumptions,
    )
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="rank_geothermal_only_baseline", status="success"))

    # ── Stage 6: network-only, fixed-source baseline ──
    fixed_reference_scenario = select_fixed_reference_scenario(v2_result.package.resource_scenarios)
    if fixed_reference_scenario is not None:
        network_only_preferred_attachment, network_only_has_any_rankable, _ = rank_network_only_baseline(
            annualized_by_id, attachment_by_id, resource_scenario_by_id,
            fixed_reference_scenario.scenario_id, research_config.decision_policy,
        )
    else:
        network_only_preferred_attachment, network_only_has_any_rankable = None, False
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="rank_network_only_baseline", status="success"))

    # ── Stage 7: cross-baseline comparison ──
    baseline_comparison = compare_baselines(
        integrated_preferred_alternative_id=integrated_decision.preferred_alternative_id,
        integrated_has_any_feasible=integrated_has_any_feasible,
        integrated_site_by_alternative_id=site_by_id, integrated_attachment_by_alternative_id=attachment_by_id,
        geothermal_only_preferred_site_id=geo_only_preferred_site,
        geothermal_only_has_any_rankable=geo_only_has_any_rankable,
        network_only_preferred_attachment_id=network_only_preferred_attachment,
        network_only_has_any_rankable=network_only_has_any_rankable,
    )
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="compare_baselines", status="success"))

    # ── Stage 8: sensitivity / robustness ──
    sensitivity_summary = run_sensitivity_study(
        annualized_by_id, capex_economics_by_id, research_config.sensitivity_cases, research_config.decision_policy,
        assumptions=base_assumptions, base_case_preferred_alternative_id=integrated_decision.preferred_alternative_id,
        site_by_alternative_id=site_by_id, attachment_by_alternative_id=attachment_by_id,
    )
    stage_calls.append(StageCallRecord(order=len(stage_calls) + 1, stage_name="run_sensitivity_study", status="success"))

    return ResearchExperimentResult(
        run_id=run_id, research_config=research_config, referenced_v2_result=v2_result,
        alternative_summaries=alternative_summaries, integrated_decision=integrated_decision,
        geothermal_only_preferred_site_id=geo_only_preferred_site,
        network_only_preferred_attachment_id=network_only_preferred_attachment,
        baseline_comparison=baseline_comparison, sensitivity_decision_summary=sensitivity_summary,
        audit=_audit(), created_at=workflow_created_at,
    )
