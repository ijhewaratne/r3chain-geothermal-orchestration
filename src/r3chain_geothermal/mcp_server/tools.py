"""The six `geo_` tool implementation functions (T5.1A) -- plain, pure
Python, directly unit-testable without any MCP transport. Every tool
sequences already-published, already-tested layer functions
(`parse_pydoublet_result`, `run_workflow`, `write_workflow_artifacts`, the
three presentation renderers) unchanged -- no physics, economics, or
ranking logic is duplicated or re-derived here.

No tool ever raises for an expected failure condition; each returns its
own `status`-discriminated union (a typed success model or `ToolError`).
The one deliberate exception is a narrow catch-all around the
`run_workflow()` call itself inside `run_workflow_tool()`
(`ToolErrorCode.UNEXPECTED_ERROR`), mirroring `cli.py`'s own
`EXIT_UNEXPECTED_ERROR` boundary -- unreachable under a valid server
config (validated once, at server-build time, never per call), so it only
ever fires for a genuine internal defect, never a config/input problem.

`GEO_TOOL_REGISTRY` is a plain `dict[str, Callable]` mapping tool name to
the UNDECORATED function below -- matching pandapipesAI's own
`CORE_REGISTRY`/`NB_REGISTRY`/... precedent exactly (confirmed by direct,
read-only inspection of `repos/pandapipesAI`): used ONLY for static
contract testing (exact membership, `geo_` prefix, no collisions),
deliberately decoupled from `server.py`'s own `@mcp.tool()` wiring, which
wraps these same six functions independently.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import __version__ as PACKAGE_VERSION
from ..contracts import PyDoubletCouplingFailure, PyDoubletCouplingResult, SourceProvenance
from ..hashing import canonical_raw_result_sha256
from ..parsers.pydoublet_parser import parse_pydoublet_result
from ..workflow import (
    AUDIT_FILENAME,
    CANDIDATE_COMPARISON_CSV_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    MANIFEST_FILENAME,
    NETWORK_CANDIDATES_SVG_FILENAME,
    PYDOUBLET_INPUT_FILENAME,
    RECOMMENDATION_MD_FILENAME,
    WORKFLOW_CONTRACT_SCHEMA_VERSION,
    WORKFLOW_RESULT_FILENAME,
    WorkflowFailure,
    WorkflowResult,
    compute_run_id,
    compute_source_provenance_sha256,
    render_candidate_comparison_csv,
    render_network_candidates_svg,
    render_recommendation_markdown,
    run_workflow,
    write_workflow_artifacts,
)
from .config import config_sha256
from .errors import ToolError, ToolErrorCode
from .registry import RunEntry, RunRegistry
from .schemas import (
    ArtifactSlice,
    AuditSummary,
    CapabilitiesSummary,
    InfeasibleCandidateSummary,
    PyDoubletValidationSummary,
    RankedCandidateSummary,
    RunSummary,
    SourceProvenanceInput,
    _CALCULATION_MODES,
    _SOURCE_FORMAT_HINTS,
)

INTERIM_ARCHITECTURE_DISCLAIMER = (
    "This demonstrates Claude/MCP orchestration of the deterministic R3-CHAIN "
    "workflow. The R3-CHAIN MCP server is the selected one-server integration "
    "architecture (Q1/Q9, decided): no separate PyDoublet-MCP server exists or "
    "will be built for this project."
)

GEO_TOOL_NAMES = (
    "geo_get_capabilities",
    "geo_validate_pydoublet_result",
    "geo_run_workflow",
    "geo_get_run_summary",
    "geo_get_audit",
    "geo_get_artifact",
)

_ALLOWED_ARTIFACT_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    WORKFLOW_RESULT_FILENAME,
    AUDIT_FILENAME,
    CANDIDATE_COMPARISON_CSV_FILENAME,
    NETWORK_CANDIDATES_SVG_FILENAME,
    RECOMMENDATION_MD_FILENAME,
    MANIFEST_FILENAME,
)
_ALLOWED_ARTIFACT_FILENAME_SET = frozenset(_ALLOWED_ARTIFACT_FILENAMES)

MIN_ARTIFACT_SLICE_LIMIT = 1
MAX_ARTIFACT_SLICE_CHARS = 16_384
"""`geo_get_artifact`'s pagination bounds: `1 <= limit <= 16384`,
`offset >= 0`. Declared BOTH here (runtime validation, this module) and in
`server.py`'s tool signature (`Annotated[int, Field(ge=..., le=...)]`, so
the generated MCP tool schema itself states the bounds) -- imported by
server.py from here so the two never drift. Out-of-range values are
REJECTED with a structured ToolError, never silently clamped."""


def _source_provenance_from_input(source_provenance: SourceProvenanceInput) -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=source_provenance.source_pydoublet_commit,
        source_format_hint=source_provenance.source_format_hint,
        calculation_mode=source_provenance.calculation_mode,
        scenario_identifier=source_provenance.scenario_identifier,
    )


def _pydoublet_validation_failure_to_tool_error(failure: PyDoubletCouplingFailure) -> ToolError:
    return ToolError(
        code=ToolErrorCode.PYDOUBLET_VALIDATION_FAILED,
        message=failure.message,
        stage="parse_pydoublet_result",
        recoverable=True,
        details={"failure_code": failure.failure_code.value, "source_pointer": failure.source_pointer},
    )


# ── 1. geo_get_capabilities ─────────────────────────────────────────────────
def get_capabilities(*, fixed_config: dict[str, Any], registry: RunRegistry) -> CapabilitiesSummary:
    return CapabilitiesSummary(
        server_name="r3chain-geothermal-mcp",
        server_version=PACKAGE_VERSION,
        workflow_contract_schema_version=WORKFLOW_CONTRACT_SCHEMA_VERSION,
        interim_architecture_disclaimer=INTERIM_ARCHITECTURE_DISCLAIMER,
        tools=sorted(GEO_TOOL_NAMES),
        demo_assumptions_config_sha256=config_sha256(fixed_config),
        allowed_artifact_filenames=list(_ALLOWED_ARTIFACT_FILENAMES),
        max_registry_size=registry.max_size,
        supported_source_format_hints=list(_SOURCE_FORMAT_HINTS),
        supported_calculation_modes=list(_CALCULATION_MODES),
    )


# ── 2. geo_validate_pydoublet_result ────────────────────────────────────────
def validate_pydoublet_result(
    pydoublet_raw_result: dict[str, Any], source_provenance: SourceProvenanceInput,
) -> PyDoubletValidationSummary | ToolError:
    boundary = parse_pydoublet_result(
        pydoublet_raw_result, source_provenance=_source_provenance_from_input(source_provenance),
    )
    if isinstance(boundary, PyDoubletCouplingFailure):
        return _pydoublet_validation_failure_to_tool_error(boundary)
    result: PyDoubletCouplingResult = boundary
    return PyDoubletValidationSummary(
        raw_result_sha256=result.raw_result_sha256,
        result_identifier=result.result_identifier,
        scenario_identifier=result.scenario_identifier,
        producer_wellhead_temperature_c=result.producer_wellhead_temperature_c.value,
        geothermal_brine_hx_outlet_temperature_c=result.geothermal_brine_hx_outlet_temperature_c.value,
        raw_geothermal_thermal_power_kw=result.raw_geothermal_thermal_power_kw.value,
        geothermal_brine_mass_flow_kg_s=result.geothermal_brine_mass_flow_kg_s.value,
        raw_cop_dimensionless=result.raw_cop_dimensionless.value,
    )


# ── shared: WorkflowResult/WorkflowFailure -> RunSummary ────────────────────
def summarize_workflow_result(
    result: WorkflowResult | WorkflowFailure, artifact_filenames: frozenset[str], *, reused_existing_run: bool,
) -> RunSummary:
    """Public (T5.1B): the ONE place a `WorkflowResult`/`WorkflowFailure`
    is mapped to the compact `RunSummary` shape every `geo_` tool and the
    scripted client's own deterministic CLI-fallback path
    (`mcp_client.cli_fallback`) both return. Reusing this function
    directly from both callers -- rather than each maintaining its own
    copy of this mapping -- is what makes "the fallback path reproduces
    the same deterministic identifiers and ranking as the MCP path" a
    structural guarantee instead of something that could silently drift
    between two independently-written implementations."""
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
        bundle_scientific_sha256="",  # filled in by run_workflow_tool() after write_workflow_artifacts()
        reused_existing_run=reused_existing_run,
    )


# ── 3. geo_run_workflow ──────────────────────────────────────────────────────
def run_workflow_tool(
    pydoublet_raw_result: dict[str, Any],
    source_provenance: SourceProvenanceInput,
    *,
    fixed_config: dict[str, Any],
    registry: RunRegistry,
) -> RunSummary | ToolError:
    provenance = _source_provenance_from_input(source_provenance)

    try:
        input_sha256 = canonical_raw_result_sha256(pydoublet_raw_result)
        config_sha = canonical_raw_result_sha256(fixed_config)
        provenance_sha256 = compute_source_provenance_sha256(provenance)
        run_id = compute_run_id(input_sha256, config_sha, provenance_sha256, WORKFLOW_CONTRACT_SCHEMA_VERSION)
    except (ValueError, TypeError) as exc:
        return ToolError(
            code=ToolErrorCode.INVALID_INPUT, message=str(exc), stage="compute_run_id", recoverable=True,
        )

    def _factory() -> RunEntry:
        try:
            result = run_workflow(pydoublet_raw_result, fixed_config, source_provenance=provenance)
        except Exception as exc:  # noqa: BLE001 -- the narrow "unexpected" boundary, module docstring
            raise _UnexpectedWorkflowError(str(exc)) from exc

        run_dir = registry.new_artifact_dir(run_id)
        extra_artifacts: dict[str, bytes] | None = None
        if isinstance(result, WorkflowResult):
            extra_artifacts = {
                CANDIDATE_COMPARISON_CSV_FILENAME: render_candidate_comparison_csv(result),
                NETWORK_CANDIDATES_SVG_FILENAME: render_network_candidates_svg(result),
                RECOMMENDATION_MD_FILENAME: render_recommendation_markdown(result),
            }
        manifest = write_workflow_artifacts(result, pydoublet_raw_result, fixed_config, run_dir, extra_artifacts=extra_artifacts)
        # manifest.files never lists manifest.json itself (ManifestRecord's
        # own invariant, workflow/artifacts.py) -- but the file genuinely
        # exists on disk (write_workflow_artifacts() always writes it last),
        # so it must still be a valid geo_get_artifact target.
        all_filenames = frozenset(manifest.files.keys()) | {MANIFEST_FILENAME}
        summary = summarize_workflow_result(result, all_filenames, reused_existing_run=False)
        summary = summary.model_copy(update={"bundle_scientific_sha256": manifest.bundle_scientific_sha256})
        return RunEntry(
            run_id=run_id, summary=summary, audit=result.audit,
            artifact_dir=run_dir, artifact_filenames=all_filenames,
            created_at=datetime.now(timezone.utc),
        )

    try:
        entry, reused = registry.get_or_run(run_id, _factory)
    except _UnexpectedWorkflowError as exc:
        return ToolError(
            code=ToolErrorCode.UNEXPECTED_ERROR, message=str(exc), stage="run_workflow", recoverable=False,
        )

    if reused:
        return entry.summary.model_copy(update={"reused_existing_run": True})
    return entry.summary


class _UnexpectedWorkflowError(Exception):
    """Internal-only signal from run_workflow_tool()'s factory to its own
    caller -- never returned or serialized; converted to a ToolError
    immediately at the one call site above."""


# ── 4. geo_get_run_summary ──────────────────────────────────────────────────
def get_run_summary(run_id: str, *, registry: RunRegistry) -> RunSummary | ToolError:
    entry = registry.get(run_id)
    if entry is None:
        return ToolError(
            code=ToolErrorCode.RUN_NOT_FOUND, message=f"no run stored under run_id {run_id!r}",
            stage="registry_lookup", recoverable=True,
        )
    return entry.summary.model_copy(update={"reused_existing_run": True})


# ── 5. geo_get_audit ─────────────────────────────────────────────────────────
def get_audit(run_id: str, *, registry: RunRegistry) -> AuditSummary | ToolError:
    entry = registry.get(run_id)
    if entry is None:
        return ToolError(
            code=ToolErrorCode.RUN_NOT_FOUND, message=f"no run stored under run_id {run_id!r}",
            stage="registry_lookup", recoverable=True,
        )
    return AuditSummary(run_id=run_id, audit=entry.audit)


# ── 6. geo_get_artifact ──────────────────────────────────────────────────────
def get_artifact(
    run_id: str, filename: str, *, registry: RunRegistry, offset: int = 0, limit: int = MAX_ARTIFACT_SLICE_CHARS,
) -> ArtifactSlice | ToolError:
    if filename not in _ALLOWED_ARTIFACT_FILENAME_SET:
        return ToolError(
            code=ToolErrorCode.FORBIDDEN_ARTIFACT,
            message=f"{filename!r} is not one of the known artifact filenames",
            stage="artifact_lookup", recoverable=False,
            details={"allowed_filenames": list(_ALLOWED_ARTIFACT_FILENAMES)},
        )
    if offset < 0:
        return ToolError(
            code=ToolErrorCode.INVALID_INPUT, message=f"offset must be >= 0, got {offset!r}",
            stage="pagination_validation", recoverable=True,
        )
    if not (MIN_ARTIFACT_SLICE_LIMIT <= limit <= MAX_ARTIFACT_SLICE_CHARS):
        return ToolError(
            code=ToolErrorCode.INVALID_INPUT,
            message=f"limit must be between {MIN_ARTIFACT_SLICE_LIMIT} and {MAX_ARTIFACT_SLICE_CHARS}, got {limit!r}",
            stage="pagination_validation", recoverable=True,
        )
    entry = registry.get(run_id)
    if entry is None:
        return ToolError(
            code=ToolErrorCode.RUN_NOT_FOUND, message=f"no run stored under run_id {run_id!r}",
            stage="registry_lookup", recoverable=True,
        )
    if filename not in entry.artifact_filenames:
        return ToolError(
            code=ToolErrorCode.ARTIFACT_NOT_AVAILABLE,
            message=f"run {run_id!r} did not publish {filename!r}",
            stage="artifact_lookup", recoverable=False,
            details={"available_filenames": sorted(entry.artifact_filenames)},
        )

    # Pinned against concurrent eviction for the duration of the read
    # (registry.py's own module docstring) -- never a direct filesystem
    # access here, so this can never race a concurrent get_or_run()
    # inserting past the bound and deleting this run_id's directory.
    text = registry.read_artifact_text(run_id, filename)
    if text is None:
        # run_id was evicted between the registry.get() check above and
        # this read (an extremely narrow window) -- a fresh, honest
        # RUN_NOT_FOUND, never a raw filesystem exception.
        return ToolError(
            code=ToolErrorCode.RUN_NOT_FOUND, message=f"no run stored under run_id {run_id!r}",
            stage="registry_lookup", recoverable=True,
        )

    content = text[offset : offset + limit]
    end = offset + len(content)
    next_offset = end if end < len(text) else None
    return ArtifactSlice(
        run_id=run_id, filename=filename, content=content,
        offset=offset, total_length=len(text), next_offset=next_offset,
    )


GEO_TOOL_REGISTRY: dict[str, Any] = {
    "geo_get_capabilities": get_capabilities,
    "geo_validate_pydoublet_result": validate_pydoublet_result,
    "geo_run_workflow": run_workflow_tool,
    "geo_get_run_summary": get_run_summary,
    "geo_get_audit": get_audit,
    "geo_get_artifact": get_artifact,
}
"""Static, plain dict[str, Callable] -- matches pandapipesAI's own
CORE_REGISTRY/... precedent (module docstring): used ONLY for contract
testing (exact membership, `geo_` prefix, no collisions), deliberately
decoupled from server.py's own @mcp.tool() live wiring."""
