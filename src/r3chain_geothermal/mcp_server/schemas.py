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
from ..workflow import WorkflowAuditRecord
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
