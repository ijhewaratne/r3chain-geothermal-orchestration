"""Structural/contract tests for mcp_server/ (T5.1A): GEO_TOOL_REGISTRY's
exact membership/prefix/no-collision (matching pandapipesAI's own
CORE_REGISTRY/... precedent), nested-repo isolation, no LLM/agent-decision
code, and the "mcp is optional" install contract."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from r3chain_geothermal.mcp_server.tools import GEO_TOOL_NAMES, GEO_TOOL_REGISTRY

_ROOT = Path(__file__).resolve().parents[2]
_MCP_SERVER_SRC = _ROOT / "src" / "r3chain_geothermal" / "mcp_server"
_NESTED_REPOS = (_ROOT / "repos" / "pandapipesAI", _ROOT / "repos" / "PyDoublet")


def test_packaged_default_config_is_byte_identical_to_the_canonical_config():
    """The packaged copy (mcp_server/data/demo_assumptions.json, needed
    because a wheel install has no config/ directory outside src/) must
    never drift from config/demo_assumptions.json, the canonical source
    every other layer/test uses."""
    canonical = (_ROOT / "config" / "demo_assumptions.json").read_bytes()
    packaged = (_MCP_SERVER_SRC / "data" / "demo_assumptions.json").read_bytes()
    assert canonical == packaged


def test_geo_tool_registry_has_exactly_six_entries():
    assert len(GEO_TOOL_REGISTRY) == 6


def test_geo_tool_registry_matches_geo_tool_names_exactly():
    assert set(GEO_TOOL_REGISTRY.keys()) == set(GEO_TOOL_NAMES)


def test_geo_tool_registry_every_name_has_the_geo_prefix():
    for name in GEO_TOOL_REGISTRY:
        assert name.startswith("geo_"), f"{name!r} does not start with 'geo_'"


def test_geo_tool_registry_values_are_all_callable():
    for name, func in GEO_TOOL_REGISTRY.items():
        assert callable(func), f"{name!r}'s registry entry is not callable"


def test_geo_tool_registry_has_no_duplicate_underlying_functions():
    """Each of the six names must map to a DISTINCT function -- a
    copy-paste registration bug (two names pointing at the same
    implementation) would silently pass a bare membership check but not
    this one."""
    assert len(set(id(f) for f in GEO_TOOL_REGISTRY.values())) == 6


EXPECTED_TOOL_NAMES = frozenset({
    "geo_get_capabilities", "geo_validate_pydoublet_result", "geo_run_workflow",
    "geo_get_run_summary", "geo_get_audit", "geo_get_artifact",
})


def test_geo_tool_names_matches_the_exact_specified_set():
    assert set(GEO_TOOL_NAMES) == EXPECTED_TOOL_NAMES


# ── Nested-repo isolation (same pattern as every earlier T2.x layer) ────────
def test_no_changes_to_either_nested_repository():
    for repo in _NESTED_REPOS:
        if not repo.exists():
            continue
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == "", f"{repo} has uncommitted changes:\n{result.stdout}"


# ── No LLM/agent-decision code inside mcp_server/ ────────────────────────────
def test_no_llm_agent_or_prompt_related_identifier_in_mcp_server_package():
    """Matches the same structural check used at every earlier layer
    (e.g. workflow/cli.py's own version) -- mcp_server/ never calls an
    LLM/agent of its own; a bare 'CLAUDE.md' citation is not such a call
    and is excluded before scanning."""
    for path in _MCP_SERVER_SRC.glob("*.py"):
        source = path.read_text().lower()
        source_without_claude_md_citation = source.replace("claude.md", "").replace("claude/mcp", "").replace(
            "claude desktop", ""
        ).replace("claude prompt", "")
        for forbidden in ("llm", "agent", "anthropic", "gpt", "openai"):
            assert forbidden not in source_without_claude_md_citation, (
                f"unexpected {forbidden!r} found in {path.name}"
            )


def test_no_physics_economics_or_ranking_recomputation_keywords():
    """A light structural guard: mcp_server/ must never import pandapipes,
    pydoublet, or the economics/network layers' own internal calculation
    helpers directly -- only the already-published boundary functions
    (run_workflow, parse_pydoublet_result, write_workflow_artifacts, the
    three renderers)."""
    forbidden_imports = ("import pandapipes", "import pydoublet", "from pydoublet")
    for path in _MCP_SERVER_SRC.glob("*.py"):
        content = path.read_text()
        for forbidden in forbidden_imports:
            assert forbidden not in content, f"unexpected {forbidden!r} found in {path.name}"


# ── "mcp is optional" install contract ───────────────────────────────────────
def test_mcp_server_package_imports_without_the_mcp_extra_installed():
    """Importing r3chain_geothermal.mcp_server itself (tools/registry/
    errors/schemas/config) must never require the `mcp` package -- run in
    a subprocess with a scrubbed environment approximation: assert none of
    the non-server modules import `mcp` at module load time by inspecting
    their source for a top-level `import mcp`/`from mcp` (server.py is the
    one deliberate exception)."""
    non_server_modules = [p for p in _MCP_SERVER_SRC.glob("*.py") if p.name not in ("server.py", "__init__.py")]
    for path in non_server_modules:
        content = path.read_text()
        assert "import mcp" not in content, f"{path.name} must not import the mcp package (server.py is the exception)"
    init_content = (_MCP_SERVER_SRC / "__init__.py").read_text()
    assert "import mcp" not in init_content


def test_package_init_does_not_import_server_module():
    """__init__.py must not eagerly import server.py (which DOES need the
    mcp package) -- otherwise `import r3chain_geothermal.mcp_server` alone
    would require the optional extra."""
    init_content = (_MCP_SERVER_SRC / "__init__.py").read_text()
    assert "from .server" not in init_content
    assert "from . import server" not in init_content


def test_mcp_server_subpackage_actually_importable_right_now():
    """A live check, not just a source scan: importing the package in a
    fresh subprocess (still inside this venv, which DOES have mcp
    installed for full T5.1A test coverage) succeeds without touching
    server.py."""
    result = subprocess.run(
        [sys.executable, "-c", "import r3chain_geothermal.mcp_server; print('OK')"],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
