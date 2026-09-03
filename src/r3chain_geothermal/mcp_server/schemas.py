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
    """CAN-001: "predefined" (config/demo_assumptions.json's own C1-C4,
    the only mode geo_run_workflow itself currently drives) and
    "generated" (network.candidate_generation.generate_candidates(),
    available as a library call but not yet wired into geo_run_workflow)."""


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
    `geo_get_run_summary` return -- never the full `WorkflowResult`/
    `WorkflowFailure`."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success"] = "success"
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


RunWorkflowResult = Annotated[Union[RunSummary, ToolError], Field(discriminator="status")]
RunSummaryResult = Annotated[Union[RunSummary, ToolError], Field(discriminator="status")]


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
