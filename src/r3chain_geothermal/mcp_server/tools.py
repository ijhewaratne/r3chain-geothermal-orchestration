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
from pathlib import Path
from typing import Any

from .. import __version__ as PACKAGE_VERSION
from ..contracts import PyDoubletCouplingFailure, PyDoubletCouplingResult, SourceProvenance
from ..errors import FailureCode
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
from ..workflow.joint_workflow_v2 import (
    ALTERNATIVE_COMPARISON_CSV_FILENAME,
    COMPATIBLE_ALTERNATIVES_FILENAME,
    JOINT_RECOMMENDATION_MD_FILENAME,
    JOINT_RESULT_FILENAME,
    JOINT_STUDY_SNAPSHOT_FILENAME,
    OBJECTIVE_POLICY_FILENAME,
    PARETO_OR_RANKING_FILENAME,
    RESOURCE_INPUT_INDEX_FILENAME,
    RESOURCE_SCENARIOS_FILENAME,
    SCREENED_ROUTES_FILENAME,
    SITE_ROUTE_GEOMETRY_FILENAME,
    SITES_FILENAME,
    JointWorkflowV2Failure,
    JointWorkflowV2Result,
    is_joint_study_v2_enabled,
    resolve_joint_workflow_v2_run_id,
    run_joint_workflow_v2,
    write_joint_workflow_v2_artifacts,
)
from ..workflow.research_experiment import (
    ResearchExperimentFailure,
    ResearchExperimentResult,
    is_research_experiment_enabled,
    resolve_research_experiment_run_id,
    run_research_experiment,
)
from ..workflow.research_experiment_export import write_research_experiment_artifacts
from .config import config_sha256
from .errors import ToolError, ToolErrorCode
from .registry import RunEntry, RunRegistry
from .schemas import (
    ArtifactSlice,
    AuditSummary,
    CapabilitiesSummary,
    JointWorkflowSummary,
    PyDoubletValidationSummary,
    ResearchExperimentSummary,
    RunSummary,
    SourceProvenanceInput,
    _CALCULATION_MODES,
    _SOURCE_FORMAT_HINTS,
    summarize_joint_workflow_v2_result,
    summarize_research_experiment_result,
    summarize_workflow_result,
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

_CANONICAL_ARTIFACT_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    WORKFLOW_RESULT_FILENAME,
    AUDIT_FILENAME,
    CANDIDATE_COMPARISON_CSV_FILENAME,
    NETWORK_CANDIDATES_SVG_FILENAME,
    RECOMMENDATION_MD_FILENAME,
    MANIFEST_FILENAME,
)
"""Exactly the 8 filenames a CANONICAL (`workflow_mode == "canonical"`)
run ever publishes -- named separately from `_ALLOWED_ARTIFACT_FILENAMES`
below (Phase 6's own superset allow-list) so a test/caller can assert a
canonical run's own artifact_filenames precisely, without that assertion
silently widening every time a new joint-only filename is added."""

_JOINT_ARTIFACT_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    JOINT_STUDY_SNAPSHOT_FILENAME,
    RESOURCE_INPUT_INDEX_FILENAME,
    SITES_FILENAME,
    RESOURCE_SCENARIOS_FILENAME,
    SCREENED_ROUTES_FILENAME,
    SITE_ROUTE_GEOMETRY_FILENAME,
    COMPATIBLE_ALTERNATIVES_FILENAME,
    JOINT_RESULT_FILENAME,
    ALTERNATIVE_COMPARISON_CSV_FILENAME,
    OBJECTIVE_POLICY_FILENAME,
    PARETO_OR_RANKING_FILENAME,
    NETWORK_CANDIDATES_SVG_FILENAME,  # same literal string as joint_workflow_v2's own constant -- not re-imported
    JOINT_RECOMMENDATION_MD_FILENAME,
    AUDIT_FILENAME,
    MANIFEST_FILENAME,
)
"""Exactly the 17 filenames a completed (`workflow_status == "completed"`)
joint_site_connection run publishes -- mirrors workflow/joint_workflow_v2.py's
own `write_joint_workflow_v2_artifacts()` bundle exactly (16 hashed files,
the full docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
§17 set, plus manifest.json itself, which never hashes itself)."""

_RESEARCH_EXPERIMENT_ARTIFACT_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    "referenced_v2_result_snapshot.json",
    "research_experiment_result.json",
    AUDIT_FILENAME,
    "experiment_input.json",
    JOINT_STUDY_SNAPSHOT_FILENAME,  # same literal string as joint_workflow_v2's own constant -- not re-imported
    "load_states.json",
    "load_state_results.json",
    "annualized_alternative_comparison.csv",
    "annualized_integrated_result.json",
    "geothermal_only_result.json",
    "geothermal_only_comparison.csv",
    "network_only_result.json",
    "network_only_comparison.csv",
    "research_comparison.json",
    "research_comparison.csv",
    "sensitivity_results.json",
    "sensitivity_comparison.csv",
    OBJECTIVE_POLICY_FILENAME,  # same literal string as joint_workflow_v2's own constant -- not re-imported
    PARETO_OR_RANKING_FILENAME,  # same literal string as joint_workflow_v2's own constant -- not re-imported
    "research_findings.md",
    MANIFEST_FILENAME,
)
"""Exactly the 22 filenames (19 spec-§17-named + referenced_v2_result_snapshot.json
+ research_experiment_result.json + manifest.json) a completed
(`workflow_status == "completed"`) research_experiment run publishes -- mirrors
workflow/research_experiment_export.py's own `write_research_experiment_artifacts()`
bundle exactly (conformance round: the spec's own "shall publish at least" §17 list,
not the smaller 8-file bundle this tuple originally named). Filenames unique to
this run type are written as literal strings (not re-imported constants),
matching `_JOINT_ARTIFACT_FILENAMES`'s own documented precedent for
NETWORK_CANDIDATES_SVG_FILENAME above; filenames that happen to share the exact
same string as an already-imported joint_workflow_v2/core constant reuse that
import instead of re-typing the literal a second time."""

_ALLOWED_ARTIFACT_FILENAMES = tuple(dict.fromkeys(
    _CANONICAL_ARTIFACT_FILENAMES + _JOINT_ARTIFACT_FILENAMES + _RESEARCH_EXPERIMENT_ARTIFACT_FILENAMES
))
"""docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 6 (MCP-005): the union of both workflow modes' own filenames --
joint_study_v2 artifacts share this SAME allow-list and geo_get_artifact's
own pagination protections, not a second mechanism. `dict.fromkeys(...)`
de-duplicates the filenames the two tuples share (PYDOUBLET_INPUT_FILENAME/
CONFIG_SNAPSHOT_FILENAME/AUDIT_FILENAME/MANIFEST_FILENAME are the exact
same literal strings in both modules, deliberately) while preserving
insertion order, so CapabilitiesSummary.allowed_artifact_filenames never
lists a filename twice."""
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
    # Deliberately does NOT carry expected_raw_sha256 across -- that field
    # lives only on the tool-facing SourceProvenanceInput, never on the
    # contracts.SourceProvenance that gets embedded verbatim into the
    # audit record (see SourceProvenance's own docstring). Callers below
    # read source_provenance.expected_raw_sha256 directly and pass it as
    # its own keyword argument to parse_pydoublet_result()/run_workflow().
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
        provenance_hash_enforcement_supported=True,
        persistent_registry_enabled=registry.persistent,
        available_shortfall_policies=["cost_shortfall", "strict_infeasible"],
        available_injection_sizing_policies=["fixed_design_temperature", "self_consistent"],
        candidate_generation_modes=["predefined", "generated"],
        supported_workflow_modes=["canonical", "joint_site_connection", "research_experiment"],
        joint_study_v2_enabled=is_joint_study_v2_enabled(fixed_config),
        research_experiment_enabled=is_research_experiment_enabled(fixed_config),
    )


# ── 2. geo_validate_pydoublet_result ────────────────────────────────────────
def validate_pydoublet_result(
    pydoublet_raw_result: dict[str, Any], source_provenance: SourceProvenanceInput,
) -> PyDoubletValidationSummary | ToolError:
    boundary = parse_pydoublet_result(
        pydoublet_raw_result, source_provenance=_source_provenance_from_input(source_provenance),
        expected_raw_sha256=source_provenance.expected_raw_sha256,
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
            result = run_workflow(
                pydoublet_raw_result, fixed_config, source_provenance=provenance,
                expected_raw_sha256=source_provenance.expected_raw_sha256,
            )
        except Exception as exc:  # noqa: BLE001 -- the narrow "unexpected" boundary, module docstring
            raise _UnexpectedWorkflowError(str(exc)) from exc

        if (
            isinstance(result, WorkflowFailure)
            and result.details.get("failure_code") == FailureCode.PYDOUBLET_RAW_HASH_MISMATCH.value
        ):
            # IP-006: no workflow artifact directory is ever created for a
            # provenance mismatch -- deliberately NOT the same path as every
            # other stopping failure (parse/HX/blueprint/baseline), which DO
            # get an audited "stopped" bundle by design (CLAUDE.md: a
            # stopped workflow is a valid, honest outcome). A hash mismatch
            # is different in kind: it means the caller did not send the
            # input they believed they were sending, so there is nothing
            # here worth persisting as an audited scientific attempt. This
            # raise happens BEFORE registry.new_artifact_dir() below, so
            # zero filesystem footprint results -- verified directly in
            # tests/mcp_server/test_tools.py.
            raise _ProvenanceMismatchError(result.message, result.details)

        # RR-002 (docs/issues/mcp-persistent-run-registry.md): write into a
        # STAGING directory first, then atomically publish -- new_artifact_dir()
        # no longer returns the final run_id-named directory directly.
        staging_dir = registry.new_artifact_dir(run_id)
        extra_artifacts: dict[str, bytes] | None = None
        if isinstance(result, WorkflowResult):
            extra_artifacts = {
                CANDIDATE_COMPARISON_CSV_FILENAME: render_candidate_comparison_csv(result),
                NETWORK_CANDIDATES_SVG_FILENAME: render_network_candidates_svg(result),
                RECOMMENDATION_MD_FILENAME: render_recommendation_markdown(result),
            }
        manifest = write_workflow_artifacts(
            result, pydoublet_raw_result, fixed_config, staging_dir, extra_artifacts=extra_artifacts,
        )
        # manifest.files never lists manifest.json itself (ManifestRecord's
        # own invariant, workflow/artifacts.py) -- but the file genuinely
        # exists on disk (write_workflow_artifacts() always writes it last),
        # so it must still be a valid geo_get_artifact target.
        all_filenames = frozenset(manifest.files.keys()) | {MANIFEST_FILENAME}
        run_dir = registry.publish_artifact_dir(run_id, staging_dir)
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
    except _ProvenanceMismatchError as exc:
        # exc.details is the upstream WorkflowFailure.details verbatim --
        # already {"failure_code": "PYDOUBLET_RAW_HASH_MISMATCH",
        # "upstream_details": {...expected/calculated hashes...}}, the same
        # shape _pydoublet_validation_failure_to_tool_error() uses for
        # geo_validate_pydoublet_result, never paraphrased here.
        return ToolError(
            code=ToolErrorCode.PYDOUBLET_VALIDATION_FAILED, message=exc.message,
            stage="input_provenance_validation", recoverable=True, details=exc.details,
        )

    if reused:
        return entry.summary.model_copy(update={"reused_existing_run": True})
    return entry.summary


class _UnexpectedWorkflowError(Exception):
    """Internal-only signal from run_workflow_tool()'s factory to its own
    caller -- never returned or serialized; converted to a ToolError
    immediately at the one call site above."""


class _ProvenanceMismatchError(Exception):
    """Internal-only signal, exactly like _UnexpectedWorkflowError above,
    for the one other condition run_workflow_tool()'s factory must raise
    rather than return normally: an expected_raw_sha256 mismatch (IP-003),
    which must never reach registry.new_artifact_dir()/write_workflow_
    artifacts() (IP-006 -- no artifact directory for a mismatch). Raising
    achieves this "for free" via get_or_run()'s own generic
    except-cache-reraise handling (registry.py) -- no registry.py change
    needed; every concurrent waiter for this run_id observes the same
    re-raised failure, exactly as for _UnexpectedWorkflowError."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


# ── 3b. geo_run_workflow, joint_study_v2 dispatch target ─────────────────────
def run_joint_workflow_tool(
    pydoublet_raw_result: dict[str, Any],
    source_provenance: SourceProvenanceInput,
    *,
    fixed_config: dict[str, Any],
    registry: RunRegistry,
    package_root: Path,
) -> JointWorkflowSummary | ToolError:
    """docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    Phase 6 (MCP-002): the joint-site-connection analogue of
    `run_workflow_tool()` above, following the exact same shape --
    pre-registry run_id computation, a `_factory()` closure that raises
    the SAME two internal signals (`_UnexpectedWorkflowError`,
    `_ProvenanceMismatchError`) for `registry.get_or_run()`'s own generic
    handling, staged artifact publication, and a
    `reused_existing_run`-copied summary on cache hit -- reusing
    `run_joint_workflow_v2()`/`write_joint_workflow_v2_artifacts()`
    unchanged, never re-deriving anything about the physics, economics or
    decision logic. `package_root` is a required keyword, not defaulted to
    `Path.cwd()` here, so this function's own behaviour never depends on
    which directory happens to be the current one at call time --
    `dispatch_run_workflow()` below is the one place that resolves the
    real default."""
    provenance = _source_provenance_from_input(source_provenance)
    run_id, package_raw_for_run_id = resolve_joint_workflow_v2_run_id(
        pydoublet_raw_result, fixed_config, source_provenance=provenance, package_root=package_root,
    )

    def _factory() -> RunEntry:
        try:
            result = run_joint_workflow_v2(
                pydoublet_raw_result, fixed_config, source_provenance=provenance, package_root=package_root,
                expected_raw_sha256=source_provenance.expected_raw_sha256,
            )
        except Exception as exc:  # noqa: BLE001 -- the narrow "unexpected" boundary, module docstring
            raise _UnexpectedWorkflowError(str(exc)) from exc

        if isinstance(result, JointWorkflowV2Failure) and result.failure_code == "PYDOUBLET_RAW_HASH_MISMATCH":
            # MCP-009 (mirrors run_workflow_tool()'s own IP-006 handling
            # exactly): no run directory is ever created for a provenance
            # mismatch -- raised BEFORE registry.new_artifact_dir() below.
            raise _ProvenanceMismatchError(result.message, result.details)

        staging_dir = registry.new_artifact_dir(run_id)
        # A best-effort package_raw for the artifact bundle's own
        # joint_study_snapshot.json -- run_id above was already computed
        # from whatever resolve_joint_workflow_v2_run_id() itself managed
        # to load (module docstring); if the package could not be loaded
        # at all, run_joint_workflow_v2() above already reports a
        # JOINT_STUDY_PACKAGE_INVALID JointWorkflowV2Failure, and the
        # snapshot is written as an empty object, exactly like the CLI's
        # own documented fallback (workflow/cli.py::_run_joint_study_v2_cli).
        package_raw = package_raw_for_run_id if package_raw_for_run_id is not None else {}
        manifest = write_joint_workflow_v2_artifacts(result, pydoublet_raw_result, fixed_config, package_raw, staging_dir)
        all_filenames = frozenset(manifest.files.keys()) | {MANIFEST_FILENAME}
        run_dir = registry.publish_artifact_dir(run_id, staging_dir)
        summary = summarize_joint_workflow_v2_result(result, all_filenames, reused_existing_run=False)
        summary = summary.model_copy(update={"bundle_scientific_sha256": manifest.bundle_scientific_sha256})
        return RunEntry(
            run_id=run_id, summary=summary, audit=result.audit,
            artifact_dir=run_dir, artifact_filenames=all_filenames,
            created_at=datetime.now(timezone.utc), run_type="joint_site_connection",
        )

    try:
        entry, reused = registry.get_or_run(run_id, _factory)
    except _UnexpectedWorkflowError as exc:
        return ToolError(
            code=ToolErrorCode.UNEXPECTED_ERROR, message=str(exc), stage="run_joint_workflow_v2", recoverable=False,
        )
    except _ProvenanceMismatchError as exc:
        return ToolError(
            code=ToolErrorCode.PYDOUBLET_VALIDATION_FAILED, message=exc.message,
            stage="input_provenance_validation", recoverable=True, details=exc.details,
        )

    if reused:
        return entry.summary.model_copy(update={"reused_existing_run": True})
    return entry.summary


def run_research_experiment_tool(
    pydoublet_raw_result: dict[str, Any],
    source_provenance: SourceProvenanceInput,
    *,
    fixed_config: dict[str, Any],
    registry: RunRegistry,
    package_root: Path,
) -> ResearchExperimentSummary | ToolError:
    """R3-CHAIN Final Research-Alignment Implementation Specification,
    Phase 6: the research-experiment analogue of `run_joint_workflow_tool()`,
    following the exact same shape -- pre-registry run_id computation, a
    `_factory()` closure raising the SAME two internal signals for
    `registry.get_or_run()`'s own generic handling, staged artifact
    publication, and a `reused_existing_run`-copied summary on cache hit --
    reusing `run_research_experiment()`/`write_research_experiment_artifacts()`
    unchanged, never re-deriving anything about the physics, economics or
    decision logic."""
    provenance = _source_provenance_from_input(source_provenance)
    run_id = resolve_research_experiment_run_id(pydoublet_raw_result, fixed_config, source_provenance=provenance)

    def _factory() -> RunEntry:
        try:
            result = run_research_experiment(
                pydoublet_raw_result, fixed_config, source_provenance=provenance, package_root=package_root,
                expected_raw_sha256=source_provenance.expected_raw_sha256,
            )
        except Exception as exc:  # noqa: BLE001 -- the narrow "unexpected" boundary, module docstring
            raise _UnexpectedWorkflowError(str(exc)) from exc

        if isinstance(result, ResearchExperimentFailure) and result.failure_code == "PYDOUBLET_RAW_HASH_MISMATCH":
            raise _ProvenanceMismatchError(result.message, result.details)

        staging_dir = registry.new_artifact_dir(run_id)
        manifest = write_research_experiment_artifacts(result, pydoublet_raw_result, fixed_config, staging_dir)
        all_filenames = frozenset(manifest.files.keys()) | {MANIFEST_FILENAME}
        run_dir = registry.publish_artifact_dir(run_id, staging_dir)
        summary = summarize_research_experiment_result(result, all_filenames, reused_existing_run=False)
        summary = summary.model_copy(update={"bundle_scientific_sha256": manifest.bundle_scientific_sha256})
        return RunEntry(
            run_id=run_id, summary=summary, audit=result.audit,
            artifact_dir=run_dir, artifact_filenames=all_filenames,
            created_at=datetime.now(timezone.utc), run_type="research_experiment",
        )

    try:
        entry, reused = registry.get_or_run(run_id, _factory)
    except _UnexpectedWorkflowError as exc:
        return ToolError(
            code=ToolErrorCode.UNEXPECTED_ERROR, message=str(exc), stage="run_research_experiment", recoverable=False,
        )
    except _ProvenanceMismatchError as exc:
        return ToolError(
            code=ToolErrorCode.PYDOUBLET_VALIDATION_FAILED, message=exc.message,
            stage="input_provenance_validation", recoverable=True, details=exc.details,
        )

    if reused:
        return entry.summary.model_copy(update={"reused_existing_run": True})
    return entry.summary


def dispatch_run_workflow(
    pydoublet_raw_result: dict[str, Any],
    source_provenance: SourceProvenanceInput,
    *,
    fixed_config: dict[str, Any],
    registry: RunRegistry,
    package_root: Path | None = None,
) -> RunSummary | JointWorkflowSummary | ResearchExperimentSummary | ToolError:
    """MCP-002: the ONE dispatch point `server.py`'s own `geo_run_workflow`
    tool wrapper (and `GEO_TOOL_REGISTRY["geo_run_workflow"]`) calls --
    checks `fixed_config["research_experiment"]["enabled"]` FIRST (the
    most specific layer, mirroring `workflow/cli.py::run_cli()`'s own
    ordering -- a research-experiment config also carries its own
    joint_study_v2 section), then `fixed_config["joint_study_v2"]["enabled"]`
    (the exact same config-driven mode switch `workflow/cli.py
    ::is_joint_study_v2_enabled` already established for the CLI), and
    routes to `run_research_experiment_tool()`, `run_joint_workflow_tool()`,
    or, unchanged, `run_workflow_tool()`.
    `package_root` defaults to `Path.cwd()` ONLY here, at the one call
    site that actually needs a real default -- mirrors
    `workflow/cli.py::_run_joint_study_v2_cli()`'s own documented choice:
    every package-relative path in the committed fixtures is written
    relative to the repository root, and this server -- like the CLI --
    is expected to be launched from there when `joint_study_v2` is
    enabled. `build_server()` exposes `package_root` as its own test-only
    seam (matching `config`/`config_path`) for a caller that needs an
    explicit, cwd-independent root."""
    if is_research_experiment_enabled(fixed_config):
        return run_research_experiment_tool(
            pydoublet_raw_result, source_provenance, fixed_config=fixed_config, registry=registry,
            package_root=package_root if package_root is not None else Path.cwd(),
        )
    if is_joint_study_v2_enabled(fixed_config):
        return run_joint_workflow_tool(
            pydoublet_raw_result, source_provenance, fixed_config=fixed_config, registry=registry,
            package_root=package_root if package_root is not None else Path.cwd(),
        )
    return run_workflow_tool(pydoublet_raw_result, source_provenance, fixed_config=fixed_config, registry=registry)


# ── 4. geo_get_run_summary ──────────────────────────────────────────────────
def get_run_summary(
    run_id: str, *, registry: RunRegistry,
) -> RunSummary | JointWorkflowSummary | ResearchExperimentSummary | ToolError:
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
    "geo_run_workflow": dispatch_run_workflow,
    "geo_get_run_summary": get_run_summary,
    "geo_get_audit": get_audit,
    "geo_get_artifact": get_artifact,
}
"""Static, plain dict[str, Callable] -- matches pandapipesAI's own
CORE_REGISTRY/... precedent (module docstring): used ONLY for contract
testing (exact membership, `geo_` prefix, no collisions), deliberately
decoupled from server.py's own @mcp.tool() live wiring."""
