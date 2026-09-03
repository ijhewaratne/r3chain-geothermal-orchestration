"""Clean-wheel execution outside the repository (T5.1B acceptance
criterion) -- builds the real wheel, installs it with the `mcp` extra
into a fresh, isolated venv, and runs `r3chain-geothermal-mcp-demo`
against the golden fixture from a directory outside the repository,
confirming parity with the in-repo result. Mirrors T5.1A's own
`test_optional_dependency.py` fixture pattern exactly, including its
`build/` directory cleanup fix."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory) -> Path:
    build_dir = tmp_path_factory.mktemp("wheel-build")
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
def mcp_venv(tmp_path_factory, wheel_path: Path) -> Path:
    venv_dir = tmp_path_factory.mktemp("mcp-venv") / "venv"
    venv.create(venv_dir, with_pip=True)
    python = venv_dir / "bin" / "python"
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", f"{wheel_path}[mcp]"], capture_output=True, text=True,
    )
    assert result.returncode == 0, f"install failed:\n{result.stdout}\n{result.stderr}"
    return venv_dir


@pytest.fixture(scope="module")
def no_mcp_venv(tmp_path_factory, wheel_path: Path) -> Path:
    """The SAME wheel, installed WITHOUT the `mcp` extra -- proves the
    core package/deterministic CLI never require it, and that
    r3chain-geothermal-mcp-demo fails cleanly (no traceback, no absolute
    installed-site-packages path, no eager `mcp` import) rather than with
    a raw ModuleNotFoundError."""
    venv_dir = tmp_path_factory.mktemp("no-mcp-venv") / "venv"
    venv.create(venv_dir, with_pip=True)
    python = venv_dir / "bin" / "python"
    result = subprocess.run([str(python), "-m", "pip", "install", "--quiet", str(wheel_path)], capture_output=True, text=True)
    assert result.returncode == 0, f"install failed:\n{result.stdout}\n{result.stderr}"
    return venv_dir


def test_mcp_client_package_imports_without_mcp_installed_in_a_real_wheel_install(no_mcp_venv: Path):
    """Belt-and-suspenders companion to test_structural.py's source-level
    AST check (`test_runner_and_cli_only_import_mcp_lazily_not_at_module_top_level`)
    -- this proves the same "no eager mcp import" contract holds for an
    actual wheel install with `mcp` genuinely absent, not just for the
    source tree with `mcp` merely importable-but-unused."""
    python = no_mcp_venv / "bin" / "python"
    result = subprocess.run(
        [str(python), "-c", "import r3chain_geothermal.mcp_client; print('OK')"], capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stdout


def test_core_package_and_deterministic_cli_still_work_without_the_mcp_extra(no_mcp_venv: Path, tmp_path: Path):
    external_run_dir = tmp_path / "external-run-no-mcp"
    external_run_dir.mkdir()
    output_dir = external_run_dir / "output"
    demo_script = no_mcp_venv / "bin" / "r3chain-geothermal-demo"
    result = subprocess.run(
        [
            str(demo_script),
            "--input", str(_ROOT / "fixtures" / "pydoublet" / "repaired_result.json"),
            "--config", str(_ROOT / "config" / "demo_assumptions.json"),
            "--provenance", str(_ROOT / "config" / "demo_source_provenance.json"),
            "--output-dir", str(output_dir),
        ],
        capture_output=True, text=True, cwd=str(external_run_dir), timeout=60,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert (output_dir / "manifest.json").exists()


def test_mcp_demo_entry_point_exits_with_a_concise_install_hint_without_the_mcp_extra(no_mcp_venv: Path, tmp_path: Path):
    external_run_dir = tmp_path / "external-run-missing-mcp"
    external_run_dir.mkdir()
    (external_run_dir / "inputs").mkdir()
    shutil.copy(_ROOT / "fixtures" / "pydoublet" / "repaired_result.json", external_run_dir / "inputs" / "repaired_result.json")
    shutil.copy(_ROOT / "config" / "demo_source_provenance.json", external_run_dir / "inputs" / "demo_source_provenance.json")

    demo_script = no_mcp_venv / "bin" / "r3chain-geothermal-mcp-demo"
    output_dir = external_run_dir / "output"
    result = subprocess.run(
        [
            str(demo_script),
            "--input", str(external_run_dir / "inputs" / "repaired_result.json"),
            "--provenance", str(external_run_dir / "inputs" / "demo_source_provenance.json"),
            "--output-dir", str(output_dir),
        ],
        capture_output=True, text=True, cwd=str(external_run_dir), timeout=30,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Traceback (most recent call last)" not in combined
    assert str(no_mcp_venv) not in combined  # no absolute installed-site-packages path leaked
    assert "mcp" in combined.lower()
    assert 'pip install "r3chain-geothermal[mcp]"' in combined
    assert not output_dir.exists()  # nothing published for a session that never started


def test_mcp_demo_entry_point_runs_outside_the_repo_and_matches_in_repo_parity(mcp_venv: Path, tmp_path: Path):
    external_run_dir = tmp_path / "external-run"
    external_run_dir.mkdir()
    (external_run_dir / "inputs").mkdir()
    shutil.copy(_ROOT / "fixtures" / "pydoublet" / "repaired_result.json", external_run_dir / "inputs" / "repaired_result.json")
    shutil.copy(_ROOT / "config" / "demo_source_provenance.json", external_run_dir / "inputs" / "demo_source_provenance.json")

    demo_script = mcp_venv / "bin" / "r3chain-geothermal-mcp-demo"
    output_dir = external_run_dir / "output"
    result = subprocess.run(
        [
            str(demo_script),
            "--input", str(external_run_dir / "inputs" / "repaired_result.json"),
            "--provenance", str(external_run_dir / "inputs" / "demo_source_provenance.json"),
            "--output-dir", str(output_dir),
        ],
        capture_output=True, text=True, cwd=str(external_run_dir), timeout=60,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    record = json.loads((output_dir / "session_record.json").read_text())
    assert record["execution_route"] == "mcp"
    assert record["run_id"] == "r3chain-run-93d41133daa11d1a"
    # bundle_scientific_sha256 rebaselined (CFG-003, decision-register.md
    # IMPL-007): CandidateEvaluationResult's embedded GateTolerances gained
    # max_pump_dp_bar and GeothermalInjectionPolicy gained
    # heat_delivery_tolerance_fraction (both schema 1.0.0 -> 1.1.0), new
    # fields in workflow_result.json's own hashed content. run_id above is
    # UNCHANGED (it never depends on these models) and the LCOH assertion
    # below proves the actual canonical numeric ranking is also unchanged --
    # only the artifact bundle's byte-shape hash moved, exactly as
    # NFR-007/AUD-002 anticipate for a versioned schema addition.
    assert record["bundle_scientific_sha256"] == "fd1e3408cbccfeb81d2847a60d809c2c8e407fb26de4738a624cb28ad00456f6"
    lcoh_by_id = {r["candidate_id"]: round(r["indicative_lcoh_eur_per_mwh"], 4) for r in record["ranked"]}
    assert lcoh_by_id == {"C1": 52.1714, "C2": 52.2602, "C3": 52.3489, "C4": 52.4821}
