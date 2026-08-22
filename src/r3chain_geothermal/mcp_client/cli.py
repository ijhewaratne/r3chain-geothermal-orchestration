"""`r3chain-geothermal-mcp-demo` -- the scripted MCP client entry point
(T5.1B). Runs the exact eight-step demonstration sequence against
`r3chain-geothermal-mcp-server` and publishes a compact
`session_record.json`.

No `--server-command` argument exists anywhere in this module -- the
server launch mechanism is fixed internally
(`runner.default_server_params_factory`); dependency injection
(`server_params_factory`) is available only to direct Python callers
(tests), never as a CLI flag.

## Exit codes

    0 -- the session completed (`execution_route` `"mcp"` or
         `"cli_fallback"`); `session_record.json` published.
    1 -- a CLI-level input problem: a missing/unreadable/invalid JSON
         `--input` or `--provenance` file, or a provenance file that
         fails `SourceProvenance` validation. Nothing is written.
    2 -- an MCP transport failure occurred (server could not start, or an
         established session's transport broke -- `runner.McpTransportFailure`)
         and `--enable-cli-fallback` was NOT given -- the session could
         not complete at all.
    3 -- anything else: a malformed/unexpected server response
         (`runner.McpContractFailure` -- wrong tool set, a response that
         fails schema validation, an artifact whose content does not
         match its own recorded hash; NEVER treated as a transport
         failure or silently masked by a fallback run even if
         `--enable-cli-fallback` was given), a genuine internal bug, or a
         failure publishing `session_record.json` itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..contracts import SourceProvenance
from .runner import McpTransportFailure, run_mcp_session
from .session import SessionRecord

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_TRANSPORT_FAILURE = 2
EXIT_UNEXPECTED_ERROR = 3


class _CliInputError(Exception):
    """Raised for any input-validation problem this CLI itself detects,
    before a session is ever attempted -- always maps to EXIT_INPUT_ERROR."""


class _CliArgumentParser(argparse.ArgumentParser):
    """Overrides only `error()` so a bad/missing argument maps to
    EXIT_INPUT_ERROR (1), not argparse's own default of 2 -- which would
    otherwise collide with this CLI's own documented
    EXIT_TRANSPORT_FAILURE (2). `-h`/`--help` is unaffected (calls
    `exit()`, not `error()`, default status 0)."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_INPUT_ERROR)


def _reject_non_finite_json_constant(token: str) -> None:
    raise ValueError(f"JSON input contains non-finite constant {token!r} (NaN/Infinity are not valid JSON, RFC 8259)")


def _load_json_dict(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise _CliInputError(f"{label} file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _CliInputError(f"{label} file could not be read: {path} ({exc})") from exc
    try:
        # json.JSONDecodeError is itself a ValueError subclass, so this one
        # except clause also covers _reject_non_finite_json_constant's raise.
        parsed = json.loads(text, parse_constant=_reject_non_finite_json_constant)
    except ValueError as exc:
        raise _CliInputError(f"{label} file is not valid JSON: {path} ({exc})") from exc
    if not isinstance(parsed, dict):
        raise _CliInputError(f"{label} file must contain a JSON object at the top level: {path}")
    return parsed


def _load_provenance(path: Path) -> SourceProvenance:
    raw = _load_json_dict(path, label="provenance")
    try:
        return SourceProvenance.model_validate(raw)
    except ValidationError as exc:
        raise _CliInputError(f"provenance file failed SourceProvenance validation: {path}\n{exc}") from exc


def _build_argument_parser() -> _CliArgumentParser:
    parser = _CliArgumentParser(
        prog="r3chain-geothermal-mcp-demo",
        description=(
            "Scripted MCP client: runs the eight-step demonstration sequence "
            "against r3chain-geothermal-mcp-server and publishes a compact session record."
        ),
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to the raw PyDoublet result JSON.")
    parser.add_argument("--provenance", required=True, type=Path, help="Path to the source provenance JSON.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory to publish session_record.json into.")
    parser.add_argument(
        "--enable-cli-fallback", action="store_true",
        help=(
            "Opt in to falling back to the deterministic CLI-equivalent path if the MCP "
            "transport itself fails (server start, broken pipe, protocol error). Never "
            "triggered by a typed workflow/domain outcome -- that is always a valid, "
            "audited MCP result."
        ),
    )
    return parser


def _publish_session_record(record: SessionRecord, output_dir: Path) -> Path:
    """Writes `session_record.json` via a temp-file-then-`os.replace()`
    swap -- a single-file `os.replace()` is already atomic on one
    filesystem (POSIX), so no directory-level backup/restore machinery is
    needed here (unlike `workflow/cli.py`'s own multi-file bundle
    publish). Cleans up the temp file if the write or replace fails."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "session_record.json"
    temp_path = output_dir / f".session_record.json.tmp-{os.getpid()}"
    try:
        temp_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temp_path, target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def run_cli(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)

    try:
        pydoublet_raw_result = _load_json_dict(args.input, label="input")
        source_provenance = _load_provenance(args.provenance)
    except _CliInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    try:
        record = run_mcp_session(pydoublet_raw_result, source_provenance, allow_cli_fallback=args.enable_cli_fallback)
    except McpTransportFailure as exc:
        print(f"error: MCP transport failed and --enable-cli-fallback was not given: {exc}", file=sys.stderr)
        return EXIT_TRANSPORT_FAILURE
    except Exception as exc:  # noqa: BLE001 -- the genuinely-unexpected boundary
        print(f"error: unexpected internal failure: {exc!r}", file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR

    try:
        published_path = _publish_session_record(record, args.output_dir)
    except OSError as exc:
        print(f"error: failed to publish session_record.json: {exc}", file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR

    print(f"execution_route: {record.execution_route}")
    print(f"run_id: {record.run_id}")
    print(record.recommendation_text)
    print(f"session record published: {published_path}")
    return EXIT_OK


def main() -> None:
    sys.exit(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
