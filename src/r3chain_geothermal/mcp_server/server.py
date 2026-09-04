"""The interim standalone MCP server (T5.1A) -- stdio transport, mcp 1.x
(`mcp>=1.28,<2`, matching pandapipesAI's own verified-working v1 API pin,
`docs/spikes/mcp-entrypoint-spike.md` §6). Registers exactly six `geo_`
tools, each a thin `@mcp.tool()` wrapper around the plain functions in
`tools.py` -- no physics/economics/ranking logic lives here.

This module (unlike `tools.py`/`registry.py`/`errors.py`/`schemas.py`,
which have zero import-time dependency on the `mcp` package) is the ONLY
place in `mcp_server/` that touches `mcp` -- and even here the actual
`import mcp...` statement is LAZY (inside `build_server()`, not at module
top level), so `import r3chain_geothermal.mcp_server.server` itself
succeeds without the optional `mcp` extra installed; only calling
`build_server()`/`main()` requires it. This is what lets `main()` catch a
missing `mcp` package and print one concise, actionable line instead of
letting a raw `ModuleNotFoundError` (with its installed-site-packages
absolute path baked into the traceback) reach the console-script caller.

    This demonstrates Claude/MCP orchestration of the deterministic
    R3-CHAIN workflow. The R3-CHAIN MCP server is the selected one-server
    integration architecture (Q1/Q9, decided): no separate PyDoublet-MCP
    server exists or will be built for this project.
"""
from __future__ import annotations

import atexit
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from .config import load_fixed_server_config, resolve_fixed_config_path, resolve_run_root
from .registry import DEFAULT_MAX_REGISTRY_SIZE, RunRegistry
from .schemas import (
    ArtifactResult,
    AuditResult,
    CapabilitiesResult,
    PyDoubletValidationResult,
    RunSummaryResult,
    RunWorkflowResult,
    SourceProvenanceInput,
)
from .tools import (
    MAX_ARTIFACT_SLICE_CHARS,
    MIN_ARTIFACT_SLICE_LIMIT,
    dispatch_run_workflow,
    get_artifact,
    get_audit,
    get_capabilities,
    get_run_summary,
    validate_pydoublet_result,
)

if TYPE_CHECKING:
    # Only for type checkers -- never executed, so it never requires `mcp`
    # to be installed just to import this module.
    from mcp.server.fastmcp import FastMCP

SERVER_INSTRUCTIONS = (
    "R3-CHAIN interim geothermal-to-district-heating demonstration server. "
    "This demonstrates Claude/MCP orchestration of the deterministic R3-CHAIN "
    "workflow. The R3-CHAIN MCP server is the selected one-server integration "
    "architecture (Q1/Q9, decided): no separate PyDoublet-MCP server exists or "
    "will be built for this project. Typical sequence: geo_get_capabilities -> "
    "geo_validate_pydoublet_result -> geo_run_workflow -> geo_get_run_summary / "
    "geo_get_audit / geo_get_artifact."
)

MCP_EXTRA_INSTALL_HINT = 'pip install "r3chain-geothermal[mcp]"'


class MissingMcpDependencyError(Exception):
    """Raised by `build_server()` when the optional `mcp` package is not
    installed. A real, catchable exception for library callers; `main()`
    is the one place that catches it to print a concise, actionable
    message instead of a traceback."""


def build_server(
    config: dict[str, Any] | None = None,
    *,
    config_path: Path | None = None,
    max_registry_size: int = DEFAULT_MAX_REGISTRY_SIZE,
    registry: RunRegistry | None = None,
    package_root: Path | None = None,
    _install_signal_handler: bool = False,
) -> "FastMCP":
    """Builds one FastMCP server instance with its own fixed config and
    its own GEO_REGISTRY. `config`/`config_path` are TEST-ONLY seams (used
    by tests/mcp_server/test_tools.py's zero-feasible-candidates case to
    build a server against a deliberately different fixed config) --
    NEVER exposed as a tool argument on any live server; a deployed
    server always uses the one config resolved by
    `config.load_fixed_server_config()` at build time.

    `package_root` (docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    Phase 6, fixed in Phase 7): the directory `joint_study_v2.package_path`
    is resolved against when the loaded config enables it -- another
    TEST-ONLY seam (matching `config`/`config_path` above), letting a test
    pass an explicit, cwd-independent root. `None` (a live server's only
    real path) is resolved HERE, at build time, from the ACTUAL config
    file path actually used (`config_path` if given, else
    `config.resolve_fixed_config_path()`'s own env-var resolution) as
    `that_path.resolve().parent.parent` -- NEVER from `Path.cwd()` (a
    Phase 7 fix: cwd-based resolution only happened to work when the
    server process's cwd was the repository root, mirroring
    `workflow/cli.py::_run_joint_study_v2_cli()`'s own identical fix,
    found by this phase's own cross-platform wheel-smoke-test
    verification). Every committed package-relative path is written as
    `"config/<name>.json"`, relative to whatever directory contains that
    config file's own `config/` folder -- unaffected when `config` (the
    raw-dict seam) is used instead of a real file, in which case this
    derivation is skipped and the caller is expected to pass
    `package_root` explicitly if it exercises `joint_study_v2` (every
    such test in this project's own suite already does).

    When `registry` is not supplied: if `R3CHAIN_RUN_ROOT` is set
    (`config.resolve_run_root()`), builds a PERSISTENT `RunRegistry`
    rooted there (RR-001, docs/issues/mcp-persistent-run-registry.md) --
    completed runs survive this process, and any pre-existing runs under
    that root are rehydrated immediately. Otherwise (the original,
    unchanged default), creates a fresh `RunRegistry` backed by its own
    `tempfile.mkdtemp()` root (registry.py's own default) and registers
    `atexit.register(run_registry.close)` so that root directory is
    actually removed on normal process exit -- `mkdtemp()` itself does
    NOT self-clean, unlike
    `tempfile.TemporaryDirectory()`. A CALLER-supplied `registry` (tests,
    or an embedding application managing its own lifecycle) is never
    auto-closed here -- its owner is responsible for calling `close()`.

    `_install_signal_handler` is set ONLY by `main()` -- it additionally
    installs a `SIGTERM` handler that closes the registry before exiting.
    This matters in practice: the MCP stdio client's OWN documented
    shutdown sequence (`mcp.client.stdio`) closes the server's stdin, waits
    2 seconds, and then sends SIGTERM -- the NORMAL path for a client that
    finished its work and is tearing the transport down, not a hang
    fallback. `atexit` alone does not cover this, because CPython's
    default SIGTERM disposition terminates the process WITHOUT running
    atexit handlers. `_install_signal_handler` defaults to False and is
    never turned on by ordinary/test calls to `build_server()`, so calling
    it repeatedly in-process (as this project's own test suite does many
    times) never mutates the process's global signal handling.

    Raises `MissingMcpDependencyError` if the optional `mcp` package is
    not installed."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise MissingMcpDependencyError(
            f"the 'mcp' package is required to build/run the MCP server. Install it with: {MCP_EXTRA_INSTALL_HINT}"
        ) from exc

    fixed_config = config if config is not None else load_fixed_server_config(config_path)
    if package_root is None and config is None:
        # Phase 7 fix (REPRO/AC-J16, mirrors workflow/cli.py's own
        # identical fix): derive package_root from the ACTUAL resolved
        # config file path -- config_path.resolve().parent.parent -- never
        # from Path.cwd(), which only happens to work when the server
        # process's cwd is the repository root. Every committed
        # package-relative path is written as "config/<name>.json",
        # relative to whatever directory contains that config file's own
        # config/ folder. Only applies when `config` (the raw-dict
        # test-only seam) was NOT given -- a caller supplying a raw config
        # dict directly has no real on-disk config path to derive from,
        # and is expected to pass package_root explicitly if it exercises
        # joint_study_v2 (every such test in this project's own suite
        # already does).
        resolved_config_path = config_path if config_path is not None else resolve_fixed_config_path()
        if resolved_config_path is not None:
            package_root = resolved_config_path.resolve().parent.parent
    if registry is not None:
        run_registry = registry
    else:
        run_root = resolve_run_root()
        if run_root is not None:
            # RR-001 (docs/issues/mcp-persistent-run-registry.md): an
            # operator has opted into a persistent, restart-surviving
            # registry via R3CHAIN_RUN_ROOT. Rehydration (any warnings
            # recorded on run_registry.rehydration_warnings) happens
            # inside this constructor call itself.
            run_registry = RunRegistry(max_size=max_registry_size, root_dir=run_root, persistent=True)
        else:
            run_registry = RunRegistry(max_size=max_registry_size)
        atexit.register(run_registry.close)
        if _install_signal_handler:
            def _handle_sigterm(signum: int, frame: Any) -> None:
                run_registry.close()
                sys.exit(0)
            try:
                signal.signal(signal.SIGTERM, _handle_sigterm)
            except ValueError:
                pass  # not the main thread -- atexit remains the fallback

    mcp = FastMCP("r3chain-geothermal-mcp", instructions=SERVER_INSTRUCTIONS)

    @mcp.tool(name="geo_get_capabilities", structured_output=True)
    def geo_get_capabilities() -> CapabilitiesResult:
        return get_capabilities(fixed_config=fixed_config, registry=run_registry)

    @mcp.tool(name="geo_validate_pydoublet_result", structured_output=True)
    def geo_validate_pydoublet_result(
        pydoublet_raw_result: dict[str, Any], source_provenance: SourceProvenanceInput,
    ) -> PyDoubletValidationResult:
        return validate_pydoublet_result(pydoublet_raw_result, source_provenance)

    @mcp.tool(name="geo_run_workflow", structured_output=True)
    def geo_run_workflow(
        pydoublet_raw_result: dict[str, Any], source_provenance: SourceProvenanceInput,
    ) -> RunWorkflowResult:
        return dispatch_run_workflow(
            pydoublet_raw_result, source_provenance, fixed_config=fixed_config, registry=run_registry,
            package_root=package_root,
        )

    @mcp.tool(name="geo_get_run_summary", structured_output=True)
    def geo_get_run_summary(run_id: str) -> RunSummaryResult:
        return get_run_summary(run_id, registry=run_registry)

    @mcp.tool(name="geo_get_audit", structured_output=True)
    def geo_get_audit(run_id: str) -> AuditResult:
        return get_audit(run_id, registry=run_registry)

    @mcp.tool(name="geo_get_artifact", structured_output=True)
    def geo_get_artifact(
        run_id: str,
        filename: str,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=MIN_ARTIFACT_SLICE_LIMIT, le=MAX_ARTIFACT_SLICE_CHARS)] = MAX_ARTIFACT_SLICE_CHARS,
    ) -> ArtifactResult:
        return get_artifact(run_id, filename, registry=run_registry, offset=offset, limit=limit)

    return mcp


def main() -> None:
    transport = "stdio"
    if len(sys.argv) > 1 and sys.argv[1] in ("stdio", "sse", "streamable-http"):
        transport = sys.argv[1]
    try:
        server = build_server(_install_signal_handler=True)
    except MissingMcpDependencyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    server.run(transport=transport)


if __name__ == "__main__":
    main()
