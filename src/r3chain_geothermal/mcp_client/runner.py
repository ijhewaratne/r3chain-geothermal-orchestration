"""Real MCP client orchestration (T5.1B) -- the exact eight-step
sequence over a real `mcp.ClientSession`:

    1. initialize
    2. tools/list
    3. geo_get_capabilities
    4. geo_validate_pydoublet_result
    5. geo_run_workflow
    6. geo_get_run_summary
    7. geo_get_audit
    8. paginated geo_get_artifact

`run_mcp_session()` is the public, SYNCHRONOUS entry point (matching
every other layer's own synchronous style; `asyncio.run()` is an
internal implementation detail). No `mcp` import happens at this
module's top level -- only inside the functions that actually need it --
so `r3chain_geothermal.mcp_client` stays importable without the optional
`mcp` extra, matching `mcp_server`'s own established discipline.

## Fallback boundary (exact, narrowed)

Three, deliberately distinct, categories of failure can reach
`run_mcp_session()`:

  - `McpTransportFailure` -- the MCP server could not be started, or an
    already-established session's transport broke (closed pipe, EOF, an
    `mcp.shared.exceptions.McpError`, or an equivalent anyio stream
    failure) -- ELIGIBLE for `allow_cli_fallback`. `_is_transport_exception()`
    is the one place that decides membership in this category; it is
    checked, never assumed, for every exception that escapes the real
    session's transport/protocol calls.
  - `McpContractFailure` -- the server responded, but not with what a
    correct `r3chain-geothermal-mcp-server` would send: the wrong tool
    set, a `geo_run_workflow` payload that fails `RunSummary` validation,
    or a `workflow_result.json` reconstructed via pagination whose SHA-256
    does not match the hash `manifest.json` itself recorded for that
    file. NEVER eligible for fallback -- silently substituting a
    deterministic CLI run for what might be a genuine client-side parsing
    bug would hide that bug instead of surfacing it.
  - Any other, genuinely unexpected exception (a bug in this client's own
    code) -- also NEVER eligible for fallback, for the same reason.

A `ToolError` or a completed workflow with `workflow_status == "stopped"`
is never one of the three categories above -- both are normal, typed
`call_tool()` return values, not Python exceptions, and are always
returned with `execution_route == "mcp"`.

No `--server-command` argument exists anywhere in this package (per
T5.1B's own explicit requirement) -- `server_params_factory` is a
dependency-injection seam for tests only (mirrors `mcp_server.server
.build_server()`'s own `config`/`registry` test-only-parameter pattern),
never exposed as a CLI flag; the default factory always launches
`[sys.executable, "-m", "r3chain_geothermal.mcp_server.server"]`
(T5.1A's own established, PATH-independent precedent).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from pydantic import ValidationError

from ..contracts import SourceProvenance
from ..workflow import MANIFEST_FILENAME
from .cli_fallback import run_cli_fallback_session
from .session import SessionRecord, ToolCallRecord, build_session_record, compact_pydoublet_input

if TYPE_CHECKING:
    from mcp import ClientSession, StdioServerParameters

PAGINATED_ARTIFACT_FILENAME = "workflow_result.json"
ARTIFACT_PAGE_LIMIT_CHARS = 2000
"""Deliberately smaller than the server's own MAX_ARTIFACT_SLICE_CHARS
(16384) -- forces genuine multi-page pagination for the demo sequence's
`workflow_result.json` fetch, rather than completing in a single page."""


class McpTransportFailure(Exception):
    """A genuine MCP transport/protocol-layer failure: the server could
    not be started, or an established session's stream broke (closed
    pipe, EOF, an SDK-level protocol error). The ONLY category eligible
    for `allow_cli_fallback` -- see module docstring, "Fallback
    boundary"."""


class McpContractFailure(Exception):
    """The MCP server responded, but not with what a correct
    `r3chain-geothermal-mcp-server` would send: the wrong tool set, a
    response that fails schema validation, or a paginated artifact whose
    reconstructed content does not match its own recorded hash. NEVER
    eligible for `allow_cli_fallback` -- see module docstring, "Fallback
    boundary"."""


def _is_transport_exception(exc: BaseException) -> bool:
    """True only for a failure originating in the MCP transport/protocol
    layer itself. False for anything else -- INCLUDING `McpContractFailure`
    and any unexpected bug in this client's own code -- both of which
    must propagate unchanged rather than being silently reclassified as
    "the transport failed" and routed to the CLI fallback. Recurses into
    `BaseExceptionGroup` (anyio/mcp internals occasionally surface a
    failure wrapped in one): classified as a transport failure only if
    EVERY leaf exception is one."""
    from mcp.shared.exceptions import McpError

    import anyio

    transport_types: tuple[type[BaseException], ...] = (
        McpError, OSError, ConnectionError, EOFError, TimeoutError,
        anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream,
    )
    if isinstance(exc, BaseExceptionGroup):
        return bool(exc.exceptions) and all(_is_transport_exception(sub) for sub in exc.exceptions)
    return isinstance(exc, transport_types)


def _innermost_exception(exc: BaseException) -> BaseException:
    """anyio's task groups (used internally by `stdio_client`/
    `ClientSession`) wrap even a single exception raised inside their
    `async with` body in a `BaseExceptionGroup` -- often nested one level
    per task group. Unwraps down to the real, original exception (a
    `TypeError` from a client-side bug, an `McpContractFailure`, an
    `McpError`, ...) as long as each level holds exactly one sub-
    exception; stops at a genuine multi-exception group (rare -- this
    client never spawns concurrent tasks of its own)."""
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


def default_server_params_factory() -> "StdioServerParameters":
    try:
        from mcp import StdioServerParameters
    except ModuleNotFoundError as exc:
        from ..mcp_server.server import MCP_EXTRA_INSTALL_HINT

        raise McpTransportFailure(
            f"the 'mcp' package is required to run the scripted MCP client. Install it with: {MCP_EXTRA_INSTALL_HINT}"
        ) from exc

    return StdioServerParameters(command=sys.executable, args=["-m", "r3chain_geothermal.mcp_server.server"])


def _unwrap_tool_result(call_result: Any) -> dict[str, Any]:
    """FastMCP wraps a non-object top-level return type (the six tools'
    own `status`-discriminated `Union[Success, ToolError]`) under a
    `{"result": ...}` envelope in `structuredContent` -- unwraps it
    uniformly; `structuredContent` itself is `None` only for a
    transport-level error, which never reaches this function (the call
    that produced it already raised)."""
    payload = call_result.structuredContent or {}
    return payload.get("result", payload)


def _record(order: int, tool_name: str, compact_input: dict[str, Any], compact_output: dict[str, Any]) -> ToolCallRecord:
    status = "error" if compact_output.get("status") == "error" else "success"
    return ToolCallRecord(order=order, tool_name=tool_name, compact_input=compact_input, compact_output=compact_output, status=status)


async def _fetch_full_artifact_text(
    session: "ClientSession", run_id: str, filename: str, *, page_limit: int = ARTIFACT_PAGE_LIMIT_CHARS,
) -> tuple[str, int]:
    """Paginates through `filename` via repeated `geo_get_artifact` calls
    until `next_offset` is `None`, returning `(reconstructed_text, pages_fetched)`.
    Used both by the production 8-step sequence (step 8) and directly by
    tests verifying pagination reconstruction against a separately-
    fetched hash. A `ToolError` returned mid-pagination is a malformed/
    unexpected RESPONSE, not a broken transport -- `McpContractFailure`,
    never `McpTransportFailure`."""
    offset = 0
    pages_fetched = 0
    chunks: list[str] = []
    while True:
        call_result = await session.call_tool(
            "geo_get_artifact", {"run_id": run_id, "filename": filename, "offset": offset, "limit": page_limit},
        )
        payload = _unwrap_tool_result(call_result)
        if payload.get("status") == "error":
            raise McpContractFailure(f"geo_get_artifact returned an unexpected error mid-pagination: {payload.get('code')}")
        chunks.append(payload["content"])
        pages_fetched += 1
        next_offset = payload.get("next_offset")
        if next_offset is None:
            break
        offset = next_offset
    return "".join(chunks), pages_fetched


async def _fetch_full_artifact_text_verified(
    session: "ClientSession", run_id: str, filename: str, *, expected_sha256: str, page_limit: int = ARTIFACT_PAGE_LIMIT_CHARS,
) -> tuple[str, int]:
    """Same as `_fetch_full_artifact_text()`, plus a check that the
    reconstructed text's own SHA-256 matches `expected_sha256` (the
    byte_sha256 `manifest.json` itself recorded for this file) --
    proving pagination reassembled the artifact correctly rather than
    silently dropping or duplicating a page. A mismatch is a malformed
    response, `McpContractFailure`, never a transport failure."""
    text, pages_fetched = await _fetch_full_artifact_text(session, run_id, filename, page_limit=page_limit)
    actual_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual_sha256 != expected_sha256:
        raise McpContractFailure(
            f"{filename} reconstructed via pagination does not match manifest.json's own recorded byte_sha256 "
            f"(expected {expected_sha256}, got {actual_sha256})"
        )
    return text, pages_fetched


async def _run_real_mcp_session(
    pydoublet_raw_result: dict[str, Any],
    source_provenance: SourceProvenance,
    server_params: "StdioServerParameters",
    interim_architecture_disclaimer: str,
) -> SessionRecord:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    from ..mcp_server.tools import GEO_TOOL_NAMES

    tool_calls: list[ToolCallRecord] = []
    provenance_payload = source_provenance.model_dump(mode="json")
    compact_pydoublet = compact_pydoublet_input(pydoublet_raw_result, source_provenance)
    run_summary = None

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # 1. initialize
                init_result = await session.initialize()
                server_name = init_result.serverInfo.name
                protocol_version = init_result.protocolVersion

                # 2. tools/list
                tools_result = await session.list_tools()
                tools_discovered = sorted(t.name for t in tools_result.tools)
                if tools_discovered != sorted(GEO_TOOL_NAMES):
                    raise McpContractFailure(
                        f"unexpected tool set from the MCP server: expected {sorted(GEO_TOOL_NAMES)}, got {tools_discovered}"
                    )

                # 3. geo_get_capabilities
                caps_result = await session.call_tool("geo_get_capabilities", {})
                tool_calls.append(_record(3, "geo_get_capabilities", {}, _unwrap_tool_result(caps_result)))

                # 4. geo_validate_pydoublet_result
                validate_result = await session.call_tool(
                    "geo_validate_pydoublet_result",
                    {"pydoublet_raw_result": pydoublet_raw_result, "source_provenance": provenance_payload},
                )
                tool_calls.append(_record(4, "geo_validate_pydoublet_result", compact_pydoublet, _unwrap_tool_result(validate_result)))

                # 5. geo_run_workflow
                run_result = await session.call_tool(
                    "geo_run_workflow",
                    {"pydoublet_raw_result": pydoublet_raw_result, "source_provenance": provenance_payload},
                )
                run_payload = _unwrap_tool_result(run_result)
                run_record = _record(5, "geo_run_workflow", compact_pydoublet, run_payload)
                tool_calls.append(run_record)

                if run_record.status == "success":
                    from ..mcp_server.schemas import RunSummary

                    try:
                        run_summary = RunSummary.model_validate(run_payload)
                    except ValidationError as exc:
                        raise McpContractFailure(
                            f"geo_run_workflow returned a payload that failed RunSummary validation: {exc}"
                        ) from exc
                    run_id = run_summary.run_id

                    # 6. geo_get_run_summary
                    summary_result = await session.call_tool("geo_get_run_summary", {"run_id": run_id})
                    tool_calls.append(_record(6, "geo_get_run_summary", {"run_id": run_id}, _unwrap_tool_result(summary_result)))

                    # 7. geo_get_audit
                    audit_result = await session.call_tool("geo_get_audit", {"run_id": run_id})
                    tool_calls.append(_record(7, "geo_get_audit", {"run_id": run_id}, _unwrap_tool_result(audit_result)))

                    # 8. paginated geo_get_artifact, verified against manifest.json's own recorded hash
                    if PAGINATED_ARTIFACT_FILENAME in run_summary.artifact_filenames:
                        manifest_text, _ = await _fetch_full_artifact_text(session, run_id, MANIFEST_FILENAME)
                        try:
                            expected_sha256 = json.loads(manifest_text)["files"][PAGINATED_ARTIFACT_FILENAME]["byte_sha256"]
                        except (KeyError, ValueError) as exc:
                            raise McpContractFailure(f"manifest.json fetched via geo_get_artifact is malformed: {exc}") from exc

                        _reconstructed_text, pages_fetched = await _fetch_full_artifact_text_verified(
                            session, run_id, PAGINATED_ARTIFACT_FILENAME, expected_sha256=expected_sha256,
                        )
                        tool_calls.append(ToolCallRecord(
                            order=8, tool_name="geo_get_artifact",
                            compact_input={"filename": PAGINATED_ARTIFACT_FILENAME, "page_limit": ARTIFACT_PAGE_LIMIT_CHARS},
                            compact_output={
                                "filename": PAGINATED_ARTIFACT_FILENAME, "pages_fetched": pages_fetched,
                                "total_length": len(_reconstructed_text), "byte_sha256_verified": True,
                            },
                            status="success",
                        ))
    except* BaseException as eg:
        # anyio's task groups (stdio_client/ClientSession, both used
        # above) always surface a failure wrapped in a BaseExceptionGroup,
        # even for a single, non-concurrent exception -- unwrap back to
        # the real exception before classifying it, so a McpContractFailure
        # or an unexpected client-side bug propagates AS ITSELF, never as
        # an opaque ExceptionGroup wrapper.
        leaf = _innermost_exception(eg.exceptions[0]) if len(eg.exceptions) == 1 else eg
        if _is_transport_exception(leaf):
            raise McpTransportFailure(str(leaf)) from eg
        raise leaf from eg

    return build_session_record(
        execution_route="mcp", server_name=server_name, protocol_version=protocol_version,
        tools_discovered=tools_discovered, tool_calls=tool_calls, run_summary=run_summary,
        created_at=datetime.now(timezone.utc), interim_architecture_disclaimer=interim_architecture_disclaimer,
    )


def run_mcp_session(
    pydoublet_raw_result: dict[str, Any],
    source_provenance: SourceProvenance,
    *,
    allow_cli_fallback: bool = False,
    server_params_factory: "Callable[[], StdioServerParameters] | None" = None,
    interim_architecture_disclaimer: str | None = None,
) -> SessionRecord:
    """Runs the real 8-step MCP sequence. On `McpTransportFailure` ONLY
    (module docstring, "Fallback boundary"), falls back to the
    deterministic CLI path if `allow_cli_fallback`, otherwise re-raises
    unchanged. `McpContractFailure` and any other exception always
    propagate -- neither is ever caught here, so neither can ever trigger
    a fallback. A typed domain outcome (a `ToolError`, or
    `workflow_status == "stopped"`) is never an exception at all -- it is
    returned normally with `execution_route == "mcp"`."""
    from ..mcp_server.tools import INTERIM_ARCHITECTURE_DISCLAIMER

    disclaimer = interim_architecture_disclaimer if interim_architecture_disclaimer is not None else INTERIM_ARCHITECTURE_DISCLAIMER
    factory = server_params_factory if server_params_factory is not None else default_server_params_factory

    try:
        server_params = factory()
        return asyncio.run(_run_real_mcp_session(pydoublet_raw_result, source_provenance, server_params, disclaimer))
    except McpTransportFailure:
        if allow_cli_fallback:
            return run_cli_fallback_session(pydoublet_raw_result, source_provenance, interim_architecture_disclaimer=disclaimer)
        raise
