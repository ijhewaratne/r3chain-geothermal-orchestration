"""Typed request/response models for the six `geo_` tools (T5.1A).

Every success model here is frozen (`extra="forbid"`), matching every
earlier layer's own discipline. Nothing here recomputes a technical or
economic value -- these models only shape ALREADY-COMPUTED, already-typed
data (`WorkflowResult`/`WorkflowFailure`/`WorkflowAuditRecord`/
`PyDoubletCouplingResult`) for the MCP boundary: compact summaries and
stable `run_id` handles, never the enormous full workflow payload.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import CouplingWarning
from ..workflow import WorkflowAuditRecord, WorkflowFailure, WorkflowResult
from ..workflow.joint_workflow_v2 import JointWorkflowV2Failure, JointWorkflowV2Result
from .errors import ToolError

_SOURCE_FORMAT_HINTS = ("known_pristine", "known_repaired", "unknown")
_CALCULATION_MODES = ("deterministic", "monte_carlo", "unknown")


class SourceProvenanceInput(BaseModel):
    """The tool-facing provenance input. Mirrors `contracts.SourceProvenance`'s
    own four fields exactly, but marks the three trust-relevant ones
    REQUIRED at the tool-schema level -- no default value (e.g. an
    implicit "unknown"/"unknown") can reach the MCP boundary; a caller (or
    Claude) must state them explicitly. `parse_pydoublet_result()`'s own
    unchanged gate still only accepts `calculation_mode == "deterministic"`
    downstream -- this model does not loosen or duplicate that check, it
    only removes the "silently defaulted" path at the tool-argument layer."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_pydoublet_commit: str | None
    source_format_hint: Literal["known_pristine", "known_repaired", "unknown"]
    calculation_mode: Literal["deterministic", "monte_carlo", "unknown"]
    scenario_identifier: str | None = None
    expected_raw_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    """Optional exact-hash pin (IP-001,
    docs/issues/mcp-input-provenance-enforcement.md). Omitted by default --
    every existing caller is unaffected. When supplied, must be a lowercase
    64-hex-character SHA-256; mirrors contracts.SourceProvenance's own field
    exactly, see that field's docstring for the full semantics."""


class CapabilitiesSummary(BaseModel):
    """`geo_get_capabilities()`'s success return -- cheap, idempotent,
    never touches GEO_REGISTRY."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success"] = "success"
    server_name: str
    server_version: str
    workflow_contract_schema_version: str
    interim_architecture_disclaimer: str
    tools: list[str]
    demo_assumptions_config_sha256: str
    allowed_artifact_filenames: list[str]
    max_registry_size: int
    supported_source_format_hints: list[str]
    supported_calculation_modes: list[str]
    provenance_hash_enforcement_supported: bool
    """IP-001: expected_raw_sha256 is accepted by geo_validate_pydoublet_result
    and geo_run_workflow."""
    persistent_registry_enabled: bool
    """RR-001: whether THIS running server instance was started with
    R3CHAIN_RUN_ROOT set (runs survive a restart) -- reflects the actual
    running registry, never a static capability claim."""
    available_shortfall_policies: list[str]
    """DSP-001: GeothermalInjectionPolicy.auxiliary_policy's accepted values."""
    available_injection_sizing_policies: list[str]
    """DSP-005: GeothermalInjectionPolicy.injection_sizing_policy's accepted values."""
    candidate_generation_modes: list[str]
    """CAN-001 (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase
    3.2): "predefined" (config/demo_assumptions.json's own fixed C1-C4)
    and "generated" (network.candidate_generation.generate_candidates(),
    workflow/core.py::_apply_candidate_mode) are BOTH genuinely reachable
    through geo_run_workflow -- whichever this server's own fixed_config
    (loaded once at server start from R3CHAIN_MCP_CONFIG_PATH or the
    packaged default) sets under candidates.mode. This field lists modes
    the SERVER IMPLEMENTATION supports, not which one the currently
    loaded fixed_config happens to use (mirrors
    available_shortfall_policies/available_injection_sizing_policies'
    own convention below) -- see config/demo_assumptions_generated_candidates.json
    for a config that exercises "generated" specifically, and that
    function's own docstring for the one documented limitation (a
    generated candidate's own connection_pipe_dn_mm design axis is not
    yet consumed by the physics evaluator)."""
    supported_workflow_modes: list[str]
    """MCP-001 (docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    Phase 6): always `["canonical", "joint_site_connection"]` -- both
    workflow_mode values this SERVER IMPLEMENTATION can dispatch
    geo_run_workflow to, mirroring candidate_generation_modes' own
    "implementation capability, not current config" convention."""
    joint_study_v2_enabled: bool
    """Whether THIS server's own currently loaded fixed_config actually
    has `joint_study_v2.enabled == true` -- i.e., whether calling
    geo_run_workflow against it right now would dispatch to the joint
    site/connection workflow rather than the canonical one. Distinct from
    supported_workflow_modes above exactly the way persistent_registry_enabled
    is distinct from a generic "supports persistence" capability claim:
    this reflects the ACTUAL running configuration, not a static
    capability."""


class PyDoubletValidationSummary(BaseModel):
    """`geo_validate_pydoublet_result()`'s success return -- field names
    match `contracts.PyDoubletCouplingResult` exactly (unwrapped from each
    `NormalizedQuantity.value`), never renamed."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success"] = "success"
    raw_result_sha256: str
    result_identifier: str
    scenario_identifier: str
    producer_wellhead_temperature_c: float
    geothermal_brine_hx_outlet_temperature_c: float
    raw_geothermal_thermal_power_kw: float
    geothermal_brine_mass_flow_kg_s: float
    raw_cop_dimensionless: float


PyDoubletValidationResult = Annotated[
    Union[PyDoubletValidationSummary, ToolError], Field(discriminator="status")
]


class RankedCandidateSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    rank: int
    indicative_lcoh_eur_per_mwh: float


class InfeasibleCandidateSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    failure_code: str


class RunSummary(BaseModel):
    """The one compact result shape both `geo_run_workflow` and
    `geo_get_run_summary` return for the CANONICAL single-scenario
    workflow -- never the full `WorkflowResult`/`WorkflowFailure`."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success"] = "success"
    workflow_mode: Literal["canonical"] = "canonical"
    """docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    Phase 6 (MCP-003): the discriminator distinguishing this shape from
    `JointWorkflowSummary.workflow_mode == "joint_site_connection"` below,
    so `geo_run_workflow`'s return type can be a genuine discriminated
    union instead of forcing a Pareto/joint result into this model's own
    canonical-candidate-ranking fields. A fixed default -- every existing
    caller/test that never mentions this field is completely unaffected
    (MCP-008: canonical responses remain backward compatible)."""
    run_id: str
    workflow_status: Literal["completed", "stopped"]
    preferred_candidate_id: str | None
    ranked: list[RankedCandidateSummary]
    infeasible: list[InfeasibleCandidateSummary]
    stopping_failure_code: str | None
    warnings: list[CouplingWarning]
    artifact_filenames: list[str]
    bundle_scientific_sha256: str
    reused_existing_run: bool


class JointWorkflowSummary(BaseModel):
    """`geo_run_workflow`'s (and `geo_get_run_summary`'s) success return
    for a `joint_study_v2`-enabled run -- docs/specifications/
    R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    §16.1's own field list, PLUS `workflow_status`/`stopping_failure_code`
    (a deliberate, documented addition -- see this module's own docstring
    note below the class for why). Never forces a Pareto-only result's
    `preferred_alternative_id` to a non-null value (MCP-004): it is null
    both under `decision_policy_mode == pareto_only` AND whenever rank 1
    contains more than one materially tied alternative under
    `primary_objective_ranking` -- this model simply carries
    `JointDecisionResult.preferred_alternative_id` straight through,
    unchanged, never recomputing or overriding it."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success"] = "success"
    workflow_mode: Literal["joint_site_connection"] = "joint_site_connection"
    run_id: str
    workflow_status: Literal["completed", "stopped"]
    """Addition beyond the spec's own literal §16.1 field list: mirrors
    `RunSummary.workflow_status` exactly, so a `JointWorkflowV2Failure`
    (e.g. an invalid study package, or a PyDoublet parse failure) is
    reported the SAME way the canonical path already reports a
    `WorkflowFailure` -- a valid, audited, typed "stopped" outcome, tool
    status still "success" (errors.py's own documented principle: "stopped
    is not an error either, it is an audited, typed outcome") -- rather
    than as a `ToolError`, which would need a new error code FAIL-005
    explicitly discourages inventing. Every count/decision field below is
    `None` when `workflow_status == "stopped"`, since the run never
    reached the stage that would produce them."""
    stopping_failure_code: str | None
    study_classification: Literal["synthetic"] | None
    site_count: int | None
    resource_scenario_count: int | None
    network_attachment_count: int | None
    route_count: int | None
    """The ACCEPTED route count (`JointWorkflowV2Counts.accepted_route_count`)
    -- the spec's own §16.1 field list names only one `route_count`, not
    separate generated/accepted figures; accepted is the count that
    actually participates in any evaluated alternative, so it is the more
    informative single number for this compact summary. The full
    generated/accepted/rejected breakdown remains available, unabridged,
    via `geo_get_artifact(..., "screened_site_connection_routes.json")`."""
    design_option_count: int | None
    operating_policy_count: int | None
    compatible_alternative_count: int | None
    evaluated_alternative_count: int | None
    feasible_alternative_count: int | None
    active_dimensions: list[str]
    controlled_dimensions: list[str]
    pareto_shortlist_alternative_ids: list[str]
    ranked_alternative_groups: list[list[str]]
    preferred_alternative_id: str | None
    decision_policy_mode: Literal["pareto_only", "primary_objective_ranking"] | None
    artifact_filenames: list[str]
    bundle_scientific_sha256: str
    reused_existing_run: bool


_AnyRunSummary = Annotated[Union[RunSummary, JointWorkflowSummary], Field(discriminator="workflow_mode")]
"""A nested discriminated union (pydantic's own documented pattern): both
members share `status == "success"` as a LITERAL, so `status` alone
cannot tell them apart -- `workflow_mode` is the inner tag that does.
`RunWorkflowResult`/`RunSummaryResult` below wrap this union together with
`ToolError` (whose own `status == "error"`), discriminating on `status` at
the OUTER level -- pydantic descends into this inner union only once
`status == "success"` is already established."""

RunWorkflowResult = Annotated[Union[_AnyRunSummary, ToolError], Field(discriminator="status")]
RunSummaryResult = Annotated[Union[_AnyRunSummary, ToolError], Field(discriminator="status")]


# ── shared: WorkflowResult/WorkflowFailure -> RunSummary ────────────────────
def summarize_workflow_result(
    result: WorkflowResult | WorkflowFailure, artifact_filenames: frozenset[str], *, reused_existing_run: bool,
) -> RunSummary:
    """Public (T5.1B, moved here from tools.py under RR-persistent-registry
    to break a circular import -- registry.py's rehydration path needs this
    same mapping, and tools.py already imports FROM registry.py): the ONE
    place a `WorkflowResult`/`WorkflowFailure` is mapped to the compact
    `RunSummary` shape every `geo_` tool, the scripted client's own
    deterministic CLI-fallback path (`mcp_client.cli_fallback`), AND
    registry.py's own startup rehydration all return. Reusing this function
    directly from every caller -- rather than each maintaining its own copy
    of this mapping -- is what makes "the fallback path (and a rehydrated
    run) reproduces the same deterministic identifiers and ranking as a
    live MCP run" a structural guarantee instead of something that could
    silently drift between independently-written implementations.
    `tools.summarize_workflow_result` and `mcp_server.summarize_workflow_
    result` remain valid, identical references to this same function object
    (tools.py imports it from here) -- see
    tests/mcp_server/test_summarize_workflow_result.py's own identity
    assertions, unaffected by this move."""
    if isinstance(result, WorkflowFailure):
        return RunSummary(
            run_id=result.run_id,
            workflow_status="stopped",
            preferred_candidate_id=None,
            ranked=[],
            infeasible=[],
            stopping_failure_code=result.failure_code.value,
            warnings=[],
            artifact_filenames=sorted(artifact_filenames),
            bundle_scientific_sha256="",
            reused_existing_run=reused_existing_run,
        )
    ranked = [
        RankedCandidateSummary(
            candidate_id=entry.candidate_id, rank=entry.rank,
            indicative_lcoh_eur_per_mwh=entry.economics.indicative_lcoh_eur_per_kwh * 1000.0,
        )
        for entry in result.ranking.ranked
    ]
    infeasible = [
        InfeasibleCandidateSummary(candidate_id=entry.candidate_id, failure_code=entry.failure_code.value)
        for entry in result.ranking.infeasible
    ]
    return RunSummary(
        run_id=result.run_id,
        workflow_status="completed",
        preferred_candidate_id=ranked[0].candidate_id if ranked else None,
        ranked=ranked,
        infeasible=infeasible,
        stopping_failure_code=None,
        warnings=[w.warning for w in result.audit.warnings],
        artifact_filenames=sorted(artifact_filenames),
        bundle_scientific_sha256="",  # filled in by the caller once known (a fresh run: after
        # write_workflow_artifacts(); a rehydrated run: from the persisted manifest.json)
        reused_existing_run=reused_existing_run,
    )


def summarize_joint_workflow_v2_result(
    result: "JointWorkflowV2Result | JointWorkflowV2Failure", artifact_filenames: frozenset[str], *,
    reused_existing_run: bool,
) -> JointWorkflowSummary:
    """The joint-workflow analogue of `summarize_workflow_result()` above
    -- the ONE place a `JointWorkflowV2Result`/`JointWorkflowV2Failure` is
    mapped to the compact `JointWorkflowSummary` shape, reused identically
    by `mcp_server/tools.py::run_joint_workflow_tool()` and
    `mcp_server/registry.py`'s own rehydration path (MCP-007), exactly
    mirroring how `summarize_workflow_result` is shared by the canonical
    path's live-run and rehydration call sites."""
    if isinstance(result, JointWorkflowV2Failure):
        return JointWorkflowSummary(
            run_id=result.run_id, workflow_status="stopped", stopping_failure_code=result.failure_code,
            study_classification=None, site_count=None, resource_scenario_count=None,
            network_attachment_count=None, route_count=None, design_option_count=None,
            operating_policy_count=None, compatible_alternative_count=None, evaluated_alternative_count=None,
            feasible_alternative_count=None, active_dimensions=[], controlled_dimensions=[],
            pareto_shortlist_alternative_ids=[], ranked_alternative_groups=[], preferred_alternative_id=None,
            decision_policy_mode=None, artifact_filenames=sorted(artifact_filenames),
            bundle_scientific_sha256="", reused_existing_run=reused_existing_run,
        )
    c = result.counts
    return JointWorkflowSummary(
        run_id=result.run_id, workflow_status="completed", stopping_failure_code=None,
        study_classification="synthetic", site_count=c.site_count,
        resource_scenario_count=c.resource_scenario_count, network_attachment_count=c.network_attachment_count,
        route_count=c.accepted_route_count, design_option_count=c.design_option_count,
        operating_policy_count=c.operating_policy_count, compatible_alternative_count=c.compatible_alternative_count,
        evaluated_alternative_count=c.evaluated_alternative_count, feasible_alternative_count=c.feasible_alternative_count,
        active_dimensions=list(result.active_dimensions.active_dimensions),
        controlled_dimensions=list(result.active_dimensions.controlled_dimensions),
        pareto_shortlist_alternative_ids=list(result.decision.pareto_shortlist_alternative_ids),
        ranked_alternative_groups=[list(group) for group in result.decision.ranked_alternative_groups],
        preferred_alternative_id=result.decision.preferred_alternative_id,
        decision_policy_mode=result.decision.mode.value,
        artifact_filenames=sorted(artifact_filenames),
        bundle_scientific_sha256="",  # filled in by the caller once known, same convention as summarize_workflow_result
        reused_existing_run=reused_existing_run,
    )


class AuditSummary(BaseModel):
    """`geo_get_audit()`'s success return -- the run's own
    WorkflowAuditRecord, embedded verbatim (already bounded/self-contained,
    distinct from the full workflow_result.json)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success"] = "success"
    run_id: str
    audit: WorkflowAuditRecord


AuditResult = Annotated[Union[AuditSummary, ToolError], Field(discriminator="status")]


class ArtifactSlice(BaseModel):
    """`geo_get_artifact()`'s success return -- bounded/paginated text."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success"] = "success"
    run_id: str
    filename: str
    content: str
    offset: int
    total_length: int
    next_offset: int | None


ArtifactResult = Annotated[Union[ArtifactSlice, ToolError], Field(discriminator="status")]

CapabilitiesResult = Annotated[Union[CapabilitiesSummary, ToolError], Field(discriminator="status")]
