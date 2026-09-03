"""No orphan server process / `r3chain-mcp-*` directory after a session
completes -- success, typed failure, and transport-failure(+fallback)
paths (T5.1B), mirroring T5.1A's own test_server_lifecycle.py real-
subprocess verification pattern.

## Process-detection hardening (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md
## Phase 1.3)

The original implementation used a bare `pgrep -f
"r3chain_geothermal.mcp_server.server"` -- a SYSTEM-WIDE pattern match
that would misreport an orphan if ANY unrelated process on the machine
happened to match that substring (e.g. a completely unrelated,
legitimately-running `r3chain-geothermal-mcp-server` instance -- this was
directly observed on a development machine with a live Claude Desktop
MCP configuration running that exact console script under a DIFFERENT
process tree entirely). It also could not distinguish "this test's own
subprocess is still in its normal shutdown grace period" from "a genuine
leak," since it never established a relationship to the CURRENT process
tree at all.

`_descendant_pids_matching()` below instead walks the real process tree
(`ps -e -o pid=,ppid=,command=`, parsed once per check) starting from the
CURRENT test process's own PID, and only ever considers a match if it is
an actual descendant of that PID. A same-named process anywhere else on
the machine, in an unrelated process tree, can never be mistaken for an
orphan of THIS test run, however its command line happens to read."""
from __future__ import annotations

import glob
import json
import os
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


def _all_processes() -> list[tuple[int, int, str]]:
    """One snapshot of every process on the machine as (pid, ppid,
    command) -- a single `ps` call parsed once, rather than one `pgrep`
    call per candidate, so the whole tree is consistent within itself."""
    try:
        result = subprocess.run(["ps", "-e", "-o", "pid=,ppid=,command="], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("`ps -e -o pid=,ppid=,command=` not available/usable on this platform")
    rows: list[tuple[int, int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) < 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        rows.append((pid, ppid, parts[2] if len(parts) > 2 else ""))
    return rows


def _descendant_pids_matching(root_pid: int, pattern: str) -> set[int]:
    """Every PID that is (a) a descendant of `root_pid` in the CURRENT
    process tree, at any depth, AND (b) whose own command line contains
    `pattern` -- see module docstring, "Process-detection hardening", for
    why this replaces a bare system-wide `pgrep -f`."""
    rows = _all_processes()
    children_by_parent: dict[int, list[int]] = {}
    command_by_pid: dict[int, str] = {}
    for pid, ppid, command in rows:
        children_by_parent.setdefault(ppid, []).append(pid)
        command_by_pid[pid] = command

    descendants: set[int] = set()
    stack = list(children_by_parent.get(root_pid, []))
    while stack:
        pid = stack.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        stack.extend(children_by_parent.get(pid, []))

    return {pid for pid in descendants if pattern in command_by_pid.get(pid, "")}


def _no_child_python_processes_running_the_server(marker_pid_before: set) -> None:
    """Orphan-process check, scoped to THIS test process's own descendant
    tree only (module docstring) -- immune to an unrelated, legitimately
    running same-named process anywhere else on the machine."""
    current_pids = _descendant_pids_matching(os.getpid(), "r3chain_geothermal.mcp_server.server")
    orphans = current_pids - marker_pid_before
    assert orphans == set(), f"orphan r3chain-geothermal-mcp-server process(es) left running: {orphans}"


def _current_server_pids() -> set:
    return _descendant_pids_matching(os.getpid(), "r3chain_geothermal.mcp_server.server")


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
