"""Server/registry temp-directory lifecycle tests (T5.1A hardening round
2): a server-owned registry's root directory must be cleaned up on normal
process exit; a caller-supplied registry's lifecycle is never touched by
build_server()."""
from __future__ import annotations

import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from r3chain_geothermal.mcp_server.registry import RunRegistry
from r3chain_geothermal.mcp_server.server import build_server


def _run_registry_close_calls(mock_register: mock.MagicMock) -> list:
    """`atexit.register` is a single, process-global function -- patching
    it (necessarily globally, since `server.atexit` IS the same module
    object as the top-level `atexit` module) can also observe unrelated
    registrations made by other code (e.g. multiprocessing's own internal
    `_exit_function`, lazily triggered the first time something in the
    `mcp`/anyio import chain runs). Filter down to calls that registered
    a `RunRegistry.close` bound method specifically."""
    return [
        call.args[0] for call in mock_register.call_args_list
        if call.args and getattr(call.args[0], "__func__", None) is RunRegistry.close
    ]


def test_build_server_registers_atexit_cleanup_for_a_server_owned_registry():
    with mock.patch("r3chain_geothermal.mcp_server.server.atexit.register") as mock_register:
        build_server()
    close_calls = _run_registry_close_calls(mock_register)
    assert len(close_calls) == 1
    registered_callable = close_calls[0]
    assert registered_callable.__self__.__class__ is RunRegistry
    # Mocking atexit.register means the real cleanup callback was never
    # invoked -- close the registry this call actually created so the
    # test doesn't leave a stray /tmp/r3chain-mcp-* directory behind.
    registered_callable()


def test_build_server_does_not_register_atexit_cleanup_for_a_caller_supplied_registry():
    with tempfile.TemporaryDirectory() as td:
        supplied_registry = RunRegistry(max_size=5, root_dir=Path(td))
        with mock.patch("r3chain_geothermal.mcp_server.server.atexit.register") as mock_register:
            build_server(registry=supplied_registry)
        assert _run_registry_close_calls(mock_register) == []


def test_build_server_creates_a_real_root_directory_that_atexit_would_clean_up():
    """Confirms the exact object atexit.register is wired to actually
    owns a real, existing directory -- the behavior a process-exit
    atexit callback would perform, exercised directly (killing the
    interpreter to prove atexit itself fires is not something a unit
    test can do; registry.close()'s own removal behavior is covered by
    tests/mcp_server/test_registry.py::test_close_removes_the_entire_root_directory)."""
    created_registries: list[RunRegistry] = []
    real_init = RunRegistry.__init__

    def _capturing_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        created_registries.append(self)

    with mock.patch.object(RunRegistry, "__init__", _capturing_init):
        build_server()

    assert len(created_registries) == 1
    assert created_registries[0].root_dir.exists()


def test_build_server_defaults_to_ephemeral_registry_without_the_env_var(monkeypatch):
    """RR-001 (docs/issues/mcp-persistent-run-registry.md): the default
    (R3CHAIN_RUN_ROOT unset) must be byte-for-byte the original ephemeral
    behavior -- this is the regression guard for every other test in this
    file and test_registry.py that calls build_server()/RunRegistry()
    without expecting to touch a real, persistent filesystem location."""
    monkeypatch.delenv("R3CHAIN_RUN_ROOT", raising=False)
    with mock.patch("r3chain_geothermal.mcp_server.server.atexit.register") as mock_register:
        build_server()
    close_calls = _run_registry_close_calls(mock_register)
    assert len(close_calls) == 1
    registry_obj = close_calls[0].__self__
    assert registry_obj.persistent is False
    close_calls[0]()  # clean up the real tempdir this call created


def test_build_server_builds_a_persistent_registry_when_env_var_is_set(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        run_root = Path(td) / "runs"
        monkeypatch.setenv("R3CHAIN_RUN_ROOT", str(run_root))
        with mock.patch("r3chain_geothermal.mcp_server.server.atexit.register") as mock_register:
            build_server()
        close_calls = _run_registry_close_calls(mock_register)
        assert len(close_calls) == 1
        registry_obj = close_calls[0].__self__
        assert registry_obj.persistent is True
        assert registry_obj.root_dir == run_root
        close_calls[0]()
        assert run_root.is_dir()  # persistent close() must NOT delete root_dir


def test_real_server_process_cleans_up_its_temp_directory_on_sigterm():
    """The direct regression test for the actual leak this hardening round
    found: the MCP stdio client's own documented shutdown sequence closes
    the server's stdin, waits, then sends SIGTERM as the NORMAL path (not
    a hang fallback) -- verified empirically during this hardening round
    by reading mcp.client.stdio's own source (PROCESS_TERMINATION_TIMEOUT
    = 2.0s). Before the SIGTERM handler was added, every such shutdown
    left a `/tmp/r3chain-mcp-*` directory behind (51 were found
    accumulated from this session's own manual verification runs).

    This test launches the real server as a real subprocess, locates the
    temp directory it actually created, sends it a real SIGTERM, and
    asserts the directory is gone afterward."""
    before = set(Path(tempfile.gettempdir()).glob("r3chain-mcp-*"))

    process = subprocess.Popen(
        [sys.executable, "-m", "r3chain_geothermal.mcp_server.server"],
        # docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
        # Phase 7/9: a real macos-latest GitHub Actions CI run timed out
        # waiting for this process to exit after SIGTERM -- STILL at a
        # widened 20s, which merely bumping the number again would not fix
        # with confidence. Root cause diagnosed instead: stdout/stderr were
        # `subprocess.PIPE` but this test never reads either stream. If the
        # server (or an import it triggers -- numpy/pandapipes deprecation
        # warnings are exactly this shape) writes enough bytes to fill the
        # OS pipe buffer, the child blocks on write() indefinitely, unable
        # to ever finish handling SIGTERM regardless of how long this test
        # waits -- no finite timeout fixes a genuine full-pipe deadlock.
        # DEVNULL removes the possibility entirely: this test only ever
        # needs the process's exit behaviour, never its output content.
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        new_dir = None
        # 15s: widened from an original 5.0s after two real macos-latest CI
        # runs (2026-09-05) failed with "server subprocess never created its
        # temp directory in time" on an otherwise-unrelated docs-only push --
        # a loaded/slow CI runner can take longer than 5s just to import
        # pandapipes/numpy before the server ever reaches its own registry
        # temp-directory creation. Not a change to what the test proves (the
        # directory must still appear and later be cleaned up on SIGTERM).
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            after = set(Path(tempfile.gettempdir()).glob("r3chain-mcp-*"))
            created = after - before
            if created:
                new_dir = created.pop()
                break
            time.sleep(0.02)
        assert new_dir is not None, "server subprocess never created its temp directory in time"
        assert new_dir.exists()

        process.send_signal(signal.SIGTERM)
        # 30s: a generous CI-environment timing margin for real process
        # teardown (unrelated to the pipe-deadlock fix above, which
        # addresses a different, likely more significant failure mode) --
        # not a change to what the test actually proves (the temp
        # directory must still be gone once the process has exited -- the
        # assertion below is unchanged).
        process.wait(timeout=30)

        assert not new_dir.exists(), "SIGTERM handler did not clean up the registry's temp directory"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
