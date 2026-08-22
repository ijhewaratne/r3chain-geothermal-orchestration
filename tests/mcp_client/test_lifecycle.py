"""No orphan server process / `r3chain-mcp-*` directory after a session
completes -- success, typed failure, and transport-failure(+fallback)
paths (T5.1B), mirroring T5.1A's own test_server_lifecycle.py real-
subprocess verification pattern."""
from __future__ import annotations

import glob
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from r3chain_geothermal.contracts import SourceProvenance  # noqa: E402
from r3chain_geothermal.mcp_client.runner import run_mcp_session  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_CRASHING_SERVER_SCRIPT = str(Path(__file__).resolve().parent / "fixtures" / "crashing_server.py")


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _crashing_server_factory():
    from mcp import StdioServerParameters
    return StdioServerParameters(command=sys.executable, args=[_CRASHING_SERVER_SCRIPT])


def _no_orphan_r3chain_mcp_dirs(before: set) -> None:
    after = set(glob.glob(str(Path(tempfile.gettempdir()) / "r3chain-mcp-*")))
    assert after - before == set(), f"orphan r3chain-mcp-* directories left behind: {after - before}"


def _no_child_python_processes_running_the_server(marker_pid_before: set) -> None:
    """A crude but effective orphan-process check: list all PIDs of
    processes whose command line mentions r3chain_geothermal.mcp_server
    .server, minus whatever was already running before the test (there
    should be none either way, but this guards against false positives
    from unrelated concurrent test runs on the same machine)."""
    try:
        result = subprocess.run(["pgrep", "-f", "r3chain_geothermal.mcp_server.server"], capture_output=True, text=True)
    except FileNotFoundError:
        pytest.skip("pgrep not available on this platform")
    current_pids = set(result.stdout.split())
    orphans = current_pids - marker_pid_before
    assert orphans == set(), f"orphan r3chain-geothermal-mcp-server process(es) left running: {orphans}"


def _current_server_pids() -> set:
    try:
        result = subprocess.run(["pgrep", "-f", "r3chain_geothermal.mcp_server.server"], capture_output=True, text=True)
    except FileNotFoundError:
        return set()
    return set(result.stdout.split())


def test_worked_case_leaves_no_orphan_directory_or_process():
    before_dirs = set(glob.glob(str(Path(tempfile.gettempdir()) / "r3chain-mcp-*")))
    before_pids = _current_server_pids()
    run_mcp_session(_raw(), _provenance())
    time.sleep(0.5)  # allow the subprocess's own shutdown sequence to complete
    _no_orphan_r3chain_mcp_dirs(before_dirs)
    _no_child_python_processes_running_the_server(before_pids)


def test_typed_failure_leaves_no_orphan_directory_or_process():
    before_dirs = set(glob.glob(str(Path(tempfile.gettempdir()) / "r3chain-mcp-*")))
    before_pids = _current_server_pids()
    run_mcp_session({}, _provenance())  # PYDOUBLET_PARSE_FAILED -- a stopped workflow
    time.sleep(0.5)
    _no_orphan_r3chain_mcp_dirs(before_dirs)
    _no_child_python_processes_running_the_server(before_pids)


def test_transport_failure_with_fallback_leaves_no_orphan_directory_or_process():
    before_dirs = set(glob.glob(str(Path(tempfile.gettempdir()) / "r3chain-mcp-*")))
    before_pids = _current_server_pids()
    run_mcp_session(_raw(), _provenance(), allow_cli_fallback=True, server_params_factory=_crashing_server_factory)
    time.sleep(0.5)
    _no_orphan_r3chain_mcp_dirs(before_dirs)
    _no_child_python_processes_running_the_server(before_pids)
