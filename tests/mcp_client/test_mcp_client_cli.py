"""Full test matrix for mcp_client/cli.py -- the r3chain-geothermal-mcp-demo
entry point (T5.1B): argument parsing, exit codes, atomic session_record.json
publish, --enable-cli-fallback behavior, and the structural guarantee that
no --server-command flag exists anywhere."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from r3chain_geothermal.mcp_client.cli import (  # noqa: E402
    EXIT_INPUT_ERROR,
    EXIT_OK,
    EXIT_TRANSPORT_FAILURE,
    run_cli,
)

_ROOT = Path(__file__).resolve().parents[2]
_INPUT_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_PROVENANCE_PATH = _ROOT / "config" / "demo_source_provenance.json"
_CLI_SRC_PATH = _ROOT / "src" / "r3chain_geothermal" / "mcp_client" / "cli.py"


def _args(output_dir: Path, *, input_path: Path = _INPUT_PATH, provenance_path: Path = _PROVENANCE_PATH,
          enable_cli_fallback: bool = False) -> list[str]:
    argv = ["--input", str(input_path), "--provenance", str(provenance_path), "--output-dir", str(output_dir)]
    if enable_cli_fallback:
        argv.append("--enable-cli-fallback")
    return argv


def test_worked_case_exits_zero_and_publishes_session_record():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_OK
        record_path = output_dir / "session_record.json"
        assert record_path.exists()
        record = json.loads(record_path.read_text())
        assert record["execution_route"] == "mcp"
        assert record["run_id"] == "r3chain-run-93d41133daa11d1a"


def test_missing_input_file_exits_input_error_and_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, input_path=Path(td) / "does-not-exist.json"))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_malformed_json_input_exits_input_error():
    with tempfile.TemporaryDirectory() as td:
        bad_path = Path(td) / "bad.json"
        bad_path.write_text("{not valid json")
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, input_path=bad_path))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_non_finite_json_input_exits_input_error():
    with tempfile.TemporaryDirectory() as td:
        bad_path = Path(td) / "bad.json"
        bad_path.write_text('{"value": NaN}')
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, input_path=bad_path))
        assert exit_code == EXIT_INPUT_ERROR


def test_invalid_provenance_exits_input_error():
    with tempfile.TemporaryDirectory() as td:
        bad_provenance = Path(td) / "bad_provenance.json"
        bad_provenance.write_text(json.dumps({"calculation_mode": "not_a_valid_mode"}))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, provenance_path=bad_provenance))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_transport_failure_without_fallback_exits_transport_failure_code(monkeypatch):
    def _broken_factory():
        from mcp import StdioServerParameters
        return StdioServerParameters(command="this-command-definitely-does-not-exist-r3chain-xyz", args=[])

    monkeypatch.setattr("r3chain_geothermal.mcp_client.runner.default_server_params_factory", _broken_factory)
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_TRANSPORT_FAILURE
        assert not output_dir.exists()


def test_transport_failure_with_fallback_flag_exits_ok(monkeypatch):
    def _broken_factory():
        from mcp import StdioServerParameters
        return StdioServerParameters(command="this-command-definitely-does-not-exist-r3chain-xyz", args=[])

    monkeypatch.setattr("r3chain_geothermal.mcp_client.runner.default_server_params_factory", _broken_factory)
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, enable_cli_fallback=True))
        assert exit_code == EXIT_OK
        record = json.loads((output_dir / "session_record.json").read_text())
        assert record["execution_route"] == "cli_fallback"


def test_session_record_is_published_atomically_no_partial_file_on_success():
    """A basic sanity check of the temp-file-then-replace pattern: after
    a successful run, no leftover `.session_record.json.tmp-*` file
    remains in the output directory."""
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        run_cli(_args(output_dir))
        leftovers = list(output_dir.glob(".session_record.json.tmp-*"))
        assert leftovers == []


def test_help_flag_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        run_cli(["--help"])
    assert exc_info.value.code == EXIT_OK


def test_missing_required_flag_exits_with_input_error_code_not_argparses_default():
    argv = _args(Path("/tmp/unused"))
    idx = argv.index("--input")
    del argv[idx:idx + 2]
    with pytest.raises(SystemExit) as exc_info:
        run_cli(argv)
    assert exc_info.value.code == EXIT_INPUT_ERROR


# ── Structural guarantee: no --server-command flag anywhere ───────────────
def test_no_server_command_flag_exists_in_cli_source():
    """Checks for the actual argparse flag REGISTRATION pattern, not a
    bare substring -- this module's own docstring legitimately mentions
    "--server-command" once, to document its deliberate absence."""
    source = _CLI_SRC_PATH.read_text()
    assert 'add_argument("--server-command"' not in source
    assert "add_argument('--server-command'" not in source
    assert "server_command" not in source  # no Python identifier of that name exists at all


def test_cli_argument_parser_rejects_an_unknown_server_command_flag():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        with pytest.raises(SystemExit) as exc_info:
            run_cli([*_args(output_dir), "--server-command", "something"])
        assert exc_info.value.code == EXIT_INPUT_ERROR
