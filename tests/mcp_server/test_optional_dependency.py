"""Optional-dependency install-boundary tests (T5.1A hardening round 2): a
wheel installed WITHOUT the `mcp` extra must still let the core package
and the existing CLI import and run; importing the main package must
never eagerly import `mcp`; and invoking the `r3chain-geothermal-mcp-server`
entry point without the extra must give one concise installation
instruction -- no traceback, no absolute path.

Builds the wheel and a bare (no-mcp) venv ONCE per test session (module
scope) -- these subprocess/venv operations are inherently slower than a
unit test, but this is exactly the install boundary the hardening round
asked to have verified for real, not just by source inspection."""
from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

import shutil

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory) -> Path:
    build_dir = tmp_path_factory.mktemp("wheel-build")
    # `python -m build` always stages an intermediate `build/` directory
    # INSIDE the source tree itself (--outdir only relocates the FINAL
    # wheel) -- clean it up afterward regardless of outcome, so running
    # this test never leaves a stray, untracked build/ directory behind
    # in the repo (the same hygiene issue hit manually during T2.4B2's own
    # wheel verification).
    stray_build_dir = _ROOT / "build"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(build_dir), str(_ROOT)],
            capture_output=True, text=True,
        )
    finally:
        shutil.rmtree(stray_build_dir, ignore_errors=True)
    assert result.returncode == 0, f"wheel build failed:\n{result.stdout}\n{result.stderr}"
    wheels = list(build_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def bare_venv(tmp_path_factory, wheel_path: Path) -> Path:
    """A fresh, isolated venv with r3chain-geothermal installed WITHOUT
    the `mcp` extra -- the "clean wheel install, no mcp" scenario."""
    venv_dir = tmp_path_factory.mktemp("bare-venv") / "venv"
    venv.create(venv_dir, with_pip=True)
    python = venv_dir / "bin" / "python"
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", str(wheel_path)], capture_output=True, text=True,
    )
    assert result.returncode == 0, f"bare install failed:\n{result.stdout}\n{result.stderr}"
    # Confirm the extra genuinely was NOT installed, so a later false-pass
    # (e.g. mcp already present in this venv's base image) cannot silently
    # invalidate the whole point of this fixture.
    check = subprocess.run([str(python), "-c", "import mcp"], capture_output=True, text=True)
    assert check.returncode != 0, "the bare venv unexpectedly has `mcp` installed -- fixture is not testing what it claims to"
    return venv_dir


def test_core_package_imports_without_mcp_extra(bare_venv: Path):
    python = bare_venv / "bin" / "python"
    result = subprocess.run(
        [str(python), "-c", "import r3chain_geothermal; import r3chain_geothermal.workflow; print('OK')"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_cli_still_runs_without_mcp_extra(bare_venv: Path):
    demo_script = bare_venv / "bin" / "r3chain-geothermal-demo"
    result = subprocess.run([str(demo_script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "r3chain-geothermal-demo" in result.stdout


def test_cli_end_to_end_run_still_works_without_mcp_extra(bare_venv: Path, tmp_path: Path):
    """Not just --help -- a full worked-case run, matching the exact
    T2.4B2 behavior, to prove the CLI layer is genuinely unaffected by
    mcp_server/'s presence in the same package."""
    demo_script = bare_venv / "bin" / "r3chain-geothermal-demo"
    output_dir = tmp_path / "demo-output"
    result = subprocess.run(
        [
            str(demo_script),
            "--input", str(_ROOT / "fixtures" / "pydoublet" / "repaired_result.json"),
            "--config", str(_ROOT / "config" / "demo_assumptions.json"),
            "--provenance", str(_ROOT / "config" / "demo_source_provenance.json"),
            "--output-dir", str(output_dir),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (output_dir / "manifest.json").exists()


def test_importing_r3chain_geothermal_does_not_eagerly_import_mcp(bare_venv: Path):
    python = bare_venv / "bin" / "python"
    result = subprocess.run(
        [str(python), "-c", "import sys; import r3chain_geothermal.workflow; print('mcp' in sys.modules)"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_mcp_server_subpackage_itself_imports_without_mcp_extra(bare_venv: Path):
    """mcp_server/__init__.py, tools.py, registry.py, errors.py, schemas.py,
    config.py have zero import-time dependency on `mcp` -- only server.py
    does, and only lazily (inside build_server(), not at module scope)."""
    python = bare_venv / "bin" / "python"
    result = subprocess.run(
        [str(python), "-c", "import sys; import r3chain_geothermal.mcp_server; "
                             "print('mcp' in sys.modules); print('OK')"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "False"
    assert lines[1] == "OK"


def test_mcp_server_module_itself_imports_without_mcp_extra(bare_venv: Path):
    """Even mcp_server.server -- the one module that DOES need mcp to
    actually build/run a server -- must be importable without mcp
    installed (the lazy-import design): only calling build_server()/main()
    requires it."""
    python = bare_venv / "bin" / "python"
    result = subprocess.run(
        [str(python), "-c", "import r3chain_geothermal.mcp_server.server; print('OK')"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_mcp_server_entry_point_without_extra_gives_a_concise_message_no_traceback(bare_venv: Path):
    server_script = bare_venv / "bin" / "r3chain-geothermal-mcp-server"
    result = subprocess.run([str(server_script)], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Traceback" not in combined, f"a raw traceback leaked:\n{combined}"
    assert "ModuleNotFoundError" not in combined
    assert str(bare_venv) not in combined, "an absolute installed-site-packages path leaked into the message"
    assert "/site-packages/" not in combined
    assert "mcp" in result.stderr.lower()
    assert "pip install" in result.stderr.lower()
    # Concise: a one/two-line message, not a wall of text.
    assert len(result.stderr.strip().splitlines()) <= 3
