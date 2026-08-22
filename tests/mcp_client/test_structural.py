"""Structural/contract tests for mcp_client/ (T5.1B): no LLM/agent-
decision code, "mcp is optional" install contract -- same pattern as
every earlier layer's own structural tests (mcp_server/test_server_contract.py,
workflow/cli.py's own equivalent).

Repository-scope checks (nested repos untouched, mcp_server/ untouched)
are deliberately NOT automated tests here: repository scope is a
pre-commit check, not a stable software behavior, and a test whose result
depends on `git status`/`git diff` breaks the moment an authorized,
in-scope change touches one of those paths (as correction #2 of this
same task legitimately did to mcp_server/tools.py). Verify repository
scope manually, once, immediately before each commit."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MCP_CLIENT_SRC = _ROOT / "src" / "r3chain_geothermal" / "mcp_client"


def test_no_llm_agent_or_prompt_related_identifier_in_mcp_client_package():
    """Matches the same structural check used at every earlier layer --
    mcp_client/ never calls an LLM/agent of its own; the workshop
    PROMPT TEXT itself (prompt.py) legitimately contains the word
    "prompt" describing itself and instructs *Claude* (via a human
    pasting it into Claude Desktop) -- that is not this code calling an
    LLM, so prompt.py is excluded from the "prompt"/"claude" substring
    scan (its own dedicated tests, test_prompt.py, verify its content
    structurally instead)."""
    legitimate_negation_phrases = (
        "claude.md", "claude/mcp", "claude desktop", "claude-ready",
        "never an llm call", "no llm/agent-decision code", "not this code calling an\n    llm",
    )
    for path in _MCP_CLIENT_SRC.glob("*.py"):
        if path.name == "prompt.py":
            continue
        source = path.read_text().lower()
        source_without_citations = source
        for phrase in legitimate_negation_phrases:
            source_without_citations = source_without_citations.replace(phrase, "")
        for forbidden in ("llm", "agent", "anthropic", "gpt", "openai", "prompt"):
            assert forbidden not in source_without_citations, f"unexpected {forbidden!r} found in {path.name}"


def test_no_physics_economics_or_ranking_recomputation_keywords():
    forbidden_imports = ("import pandapipes", "import pydoublet", "from pydoublet")
    for path in _MCP_CLIENT_SRC.glob("*.py"):
        content = path.read_text()
        for forbidden in forbidden_imports:
            assert forbidden not in content, f"unexpected {forbidden!r} found in {path.name}"


# ── "mcp is optional" install contract ───────────────────────────────────
def test_mcp_client_package_imports_without_the_mcp_extra_installed():
    non_mcp_modules = [
        p for p in _MCP_CLIENT_SRC.glob("*.py")
        if p.name not in ("runner.py", "cli.py", "__init__.py")
    ]
    for path in non_mcp_modules:
        content = path.read_text()
        assert "import mcp" not in content, f"{path.name} must not import the mcp package"
    init_content = (_MCP_CLIENT_SRC / "__init__.py").read_text()
    assert "import mcp" not in init_content


def test_runner_and_cli_only_import_mcp_lazily_not_at_module_top_level():
    """`from mcp import ...`/`from mcp.client... import ...` must appear
    only inside function bodies (or a TYPE_CHECKING guard), never as an
    unconditional top-of-module import -- otherwise importing
    r3chain_geothermal.mcp_client.runner/.cli itself would require the
    optional extra."""
    import ast

    for filename in ("runner.py", "cli.py"):
        tree = ast.parse((_MCP_CLIENT_SRC / filename).read_text())
        for node in tree.body:  # only MODULE-LEVEL (top-level) statements
            if isinstance(node, ast.If):
                continue  # TYPE_CHECKING guard is fine
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mcp"):
                assert False, f"{filename} imports {node.module!r} at module top level, not lazily"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("mcp") or alias.name.startswith("mcp_"), (
                        f"{filename} imports {alias.name!r} at module top level, not lazily"
                    )


def test_mcp_client_subpackage_actually_importable_right_now():
    result = subprocess.run(
        [sys.executable, "-c", "import r3chain_geothermal.mcp_client; print('OK')"],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_no_official_coupling_claim_anywhere_in_mcp_client_source():
    """Never claim PyDoublet-MCP <-> pandapipesAI-MCP coupling."""
    forbidden_phrases = ("official pydoublet-mcp", "pandapipesai mcp server coupling")
    for path in _MCP_CLIENT_SRC.glob("*.py"):
        content = path.read_text().lower()
        for phrase in forbidden_phrases:
            assert phrase not in content, f"unexpected coupling claim {phrase!r} found in {path.name}"
