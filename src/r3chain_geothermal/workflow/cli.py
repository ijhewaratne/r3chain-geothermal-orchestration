"""`r3chain-geothermal-demo` -- the one-command reproducible-demo CLI
(T2.4B2). A thin wrapper around `run_workflow()` and
`write_workflow_artifacts()`: it loads and validates three JSON inputs,
runs the existing deterministic workflow unchanged, renders the three
T2.4B2 presentation artifacts, and publishes the complete bundle via a
staged, rollback-safe replacement. It NEVER reimplements physics,
economics, or feasibility logic of its own.

Usage:

    r3chain-geothermal-demo \\
        --input fixtures/pydoublet/repaired_result.json \\
        --config config/demo_assumptions.json \\
        --provenance config/demo_source_provenance.json \\
        --output-dir artifacts/demo \\
        [--overwrite]

## What is validated where

CLI-level validation, BEFORE `run_workflow()` is ever called: each of the
three input files exists, is readable, is well-formed finite JSON (no
NaN/Infinity -- not valid per RFC 8259), and is a JSON object; the
provenance file additionally validates against the typed
`SourceProvenance` schema; `config`'s STRUCTURAL shape is checked by
`core.validate_config_structure()` (constructing every config-derived
object `run_workflow()` itself builds, WITHOUT running the workflow) --
a missing section, wrong field type, or a rejected value raises the
narrow, dedicated `WorkflowConfigurationError`, caught here and reported
as exit code 1, same as every other CLI-level input problem;
`--output-dir` is either absent, empty, or `--overwrite` was given.

`run_workflow()`-level validation: everything about the raw PyDoublet
result's OWN content (units, physics, energy consistency) and the
network/candidate/ranking outcome -- these produce a typed
`WorkflowFailure` (exit code 2), never an exception.

Because `config` is already proven structurally valid before
`run_workflow()` is called, ANY exception that still escapes that call is
genuinely unexpected -- a solver defect or a programming bug, not a
config problem. This CLI deliberately does NOT wrap the whole
`run_workflow()` call in a broad `except (KeyError, TypeError, ValueError,
ValidationError)`: doing so would risk silently reporting a real defect
as "invalid configuration." Instead, an unexpected failure here is its
own exit code (4), kept distinguishable from exit code 1.

## Staged, rollback-safe replacement (NOT crash-atomic)

The complete artifact bundle (all core + presentation files +
manifest.json) is built in a TEMPORARY SIBLING directory
(`{output_dir}.tmp-*` next to `output_dir`, never inside it). Publishing
that bundle at `output_dir`'s path never deletes an existing bundle
before the new one is confirmed in place: if `output_dir` already exists
(the `--overwrite` path), it is first renamed aside to a backup sibling
directory (a same-filesystem `os.replace()` rename, not a copy); the new
bundle is then swapped into `output_dir`'s path; the backup is removed
ONLY after that swap succeeds. If the swap itself raises, the backup is
restored to `output_dir` before the error is reported -- the previous
valid bundle survives any publication failure this process can catch and
handle, including one injected mid-swap (tested).

This is **rollback-safe for every error this process can catch**, not
**crash-atomic**: nothing prevents the OS or hardware from stopping the
process between the rename-aside step and the final swap (a kill -9, a
power loss). No POSIX filesystem operation can make a two-step directory
replacement atomic against that; only a single `os.replace()` on ONE
already-fully-written path is atomic in that stronger sense, and this
publish sequence is not reducible to one such call. "Atomic" is therefore
deliberately not used to describe this sequence anywhere in this module.

## Exit codes

    0 -- the workflow completed (a WorkflowResult was produced and its
         bundle was published) -- this INCLUDES a completed evaluation
         with zero feasible candidates; that is a valid, honest result,
         never treated as failure. `--help`/`-h` also exits 0.
    1 -- a usage or input problem: bad/missing CLI arguments, a
         missing/unreadable file, non-finite (NaN/Infinity) or otherwise
         invalid JSON, a provenance file that fails SourceProvenance
         validation, a structurally malformed --config file (missing
         section/field, wrong type -- WorkflowConfigurationError), or
         `output_dir` exists, is non-empty, and `--overwrite` was not
         given. Nothing is written to `output_dir` for any of these.
    2 -- the workflow itself stopped (a typed WorkflowFailure -- PyDoublet
         parsing, HX coupling, blueprint construction, or baseline
         evaluation failed). Its audit trail is still published (the 4
         core scientific/audit files + manifest.json -- 5 files, not 8;
         a WorkflowFailure has no candidate/ranking data for the 3
         presentation artifacts to describe).
    3 -- artifact publication failed after a completed/failed workflow
         result was already produced (e.g. disk full, permission denied,
         or a failure injected mid-swap) -- any previously published
         bundle at `output_dir` is left exactly as it was.
    4 -- an UNEXPECTED internal failure during `run_workflow()` itself,
         AFTER `config` was already proven structurally valid by
         `validate_config_structure()` -- a solver defect or a genuine
         programming bug, deliberately kept distinguishable from exit
         code 1 (a config/input problem) rather than folded into it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..contracts import SourceProvenance
from .artifacts import write_workflow_artifacts
from .core import WorkflowConfigurationError, WorkflowFailure, WorkflowResult, run_workflow, validate_config_structure
from .csv_export import render_candidate_comparison_csv
from .joint_workflow import (
    JointOptimizationWorkflowFailure,
    JointOptimizationWorkflowResult,
    is_joint_optimization_enabled,
    run_joint_optimization_workflow,
    write_joint_optimization_artifacts,
)
from .recommendation import render_recommendation_markdown
from .svg_export import render_network_candidates_svg

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_WORKFLOW_FAILURE = 2
EXIT_ARTIFACT_PUBLICATION_FAILURE = 3
EXIT_UNEXPECTED_ERROR = 4

_CANDIDATE_COMPARISON_CSV_FILENAME = "candidate_comparison.csv"
_NETWORK_CANDIDATES_SVG_FILENAME = "network_candidates.svg"
_RECOMMENDATION_MD_FILENAME = "recommendation.md"


class _CliInputError(Exception):
    """Raised for any input-validation problem this CLI itself detects,
    before run_workflow() is ever called -- always maps to EXIT_INPUT_ERROR."""


class _CliArgumentParser(argparse.ArgumentParser):
    """Overrides only `error()` so a bad/missing argument maps to
    EXIT_INPUT_ERROR (1), not argparse's own default of 2 -- which would
    otherwise collide with this CLI's own documented EXIT_WORKFLOW_FAILURE
    (2). `-h`/`--help` is unaffected: it calls `exit()`, not `error()`,
    and this class does not override `exit()`, so `--help` still exits 0."""

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


def _validate_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if output_dir.exists():
        if not output_dir.is_dir():
            raise _CliInputError(f"--output-dir exists and is not a directory: {output_dir}")
        if any(output_dir.iterdir()) and not overwrite:
            raise _CliInputError(
                f"--output-dir is non-empty: {output_dir} (pass --overwrite to replace its contents)"
            )


def _build_bundle_in_temp_dir(
    result: WorkflowResult | WorkflowFailure,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    temp_dir: Path,
) -> None:
    """Writes the full artifact bundle into an already-created empty
    directory. Presentation artifacts (CSV/SVG/Markdown) are rendered
    only for a completed WorkflowResult -- a WorkflowFailure has no
    candidate/ranking data for them to describe, and still gets the 4
    core scientific/audit files (preserving raw inputs and the audit
    trail on failure, CLAUDE.md)."""
    extra_artifacts: dict[str, bytes] | None = None
    if isinstance(result, WorkflowResult):
        extra_artifacts = {
            _CANDIDATE_COMPARISON_CSV_FILENAME: render_candidate_comparison_csv(result),
            _NETWORK_CANDIDATES_SVG_FILENAME: render_network_candidates_svg(result),
            _RECOMMENDATION_MD_FILENAME: render_recommendation_markdown(result),
        }
    write_workflow_artifacts(result, pydoublet_raw_result, config, temp_dir, extra_artifacts=extra_artifacts)


def _publish_temp_dir(temp_dir: Path, output_dir: Path) -> None:
    """Staged, rollback-safe replacement using same-filesystem renames --
    NOT crash-atomic (module docstring). Never deletes an existing bundle
    before the new one is confirmed in place. `os.replace()` on a
    directory is a plain rename -- cheap on a single filesystem, no data
    is copied -- but this function performs TWO such renames in sequence
    (aside, then in), and nothing guarantees the process survives between
    them."""
    backup_dir: Path | None = None
    if output_dir.exists():
        backup_dir = output_dir.parent / f".{output_dir.name}.bak-{os.getpid()}-{id(temp_dir)}"
        os.replace(output_dir, backup_dir)
    try:
        os.replace(temp_dir, output_dir)
    except Exception:
        if backup_dir is not None:
            os.replace(backup_dir, output_dir)
        raise
    else:
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)


def _build_argument_parser() -> _CliArgumentParser:
    parser = _CliArgumentParser(
        prog="r3chain-geothermal-demo",
        description=(
            "Runs the deterministic R3-CHAIN geothermal-to-district-heating "
            "candidate-connection workflow once and publishes its complete, "
            "auditable artifact bundle."
        ),
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to the raw PyDoublet result JSON.")
    parser.add_argument("--config", required=True, type=Path, help="Path to the demo assumptions config JSON.")
    parser.add_argument("--provenance", required=True, type=Path, help="Path to the source provenance JSON.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory to publish the artifact bundle into.")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Required if --output-dir already exists and is non-empty.",
    )
    return parser


def _run_joint_optimization_cli(
    pydoublet_raw_result: dict[str, Any], config: dict[str, Any], source_provenance: SourceProvenance, output_dir: Path,
) -> int:
    """R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase 4: the SAME
    CLI entry point dispatches here instead of the single-scenario path
    whenever `config["joint_optimization"]["enabled"]` is true -- the
    same config-driven mode-switch convention already established for
    `candidates.mode` (Phase 3.2), not a second command. Reuses this
    module's own staged, rollback-safe publish machinery
    (`_publish_temp_dir`) unchanged; only the run/build step differs from
    the single-scenario path above.

    NOTE on exit codes: unlike the single-scenario path,
    `validate_config_structure()` does not (yet) check
    `candidates.generated`'s own presence/validity when joint-optimization
    is enabled (that config section is only ever read here, inside
    `run_joint_optimization_workflow()` itself). A joint-optimization
    config that is missing/malformed there is therefore reported as
    EXIT_WORKFLOW_FAILURE (2) with a `BLUEPRINT_CONSTRUCTION_FAILED`
    JointOptimizationWorkflowFailure, not EXIT_INPUT_ERROR (1) -- still a
    typed, audited, non-crashing outcome, just a different exit code than
    the single-scenario path's own pre-validated config guarantee."""
    result = run_joint_optimization_workflow(pydoublet_raw_result, config, source_provenance=source_provenance)

    try:
        parent_dir = output_dir.parent if str(output_dir.parent) else Path(".")
        parent_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=str(parent_dir)))
    except OSError as exc:
        print(f"error: failed to create a temporary working directory: {exc}", file=sys.stderr)
        return EXIT_ARTIFACT_PUBLICATION_FAILURE

    try:
        write_joint_optimization_artifacts(result, pydoublet_raw_result, config, temp_dir)
        _publish_temp_dir(temp_dir, output_dir)
    except Exception as exc:  # noqa: BLE001 -- any publication-stage failure maps to one exit code
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"error: failed to publish the artifact bundle: {exc}", file=sys.stderr)
        return EXIT_ARTIFACT_PUBLICATION_FAILURE

    if isinstance(result, JointOptimizationWorkflowFailure):
        print(f"joint-optimization workflow stopped: {result.failure_code.value}: {result.message}", file=sys.stderr)
        print(f"run_id: {result.run_id}", file=sys.stderr)
        print(f"bundle published (failure audit trail): {output_dir}", file=sys.stderr)
        return EXIT_WORKFLOW_FAILURE

    assert isinstance(result, JointOptimizationWorkflowResult)
    print(f"run_id: {result.run_id}")
    n_alternatives = len(result.joint_result.alternatives)
    n_feasible = sum(1 for a in result.joint_result.alternatives if a.feasible)
    print(f"evaluated {n_alternatives} (scenario, candidate) alternatives -- {n_feasible} feasible")
    if result.joint_result.pareto_shortlist_alternative_ids:
        print(f"Pareto shortlist ({len(result.joint_result.pareto_shortlist_alternative_ids)} non-dominated):")
        for alt_id in result.joint_result.pareto_shortlist_alternative_ids:
            print(f"  {alt_id}")
    else:
        print("no feasible alternative -- no recommendation (synthetic scenario/connection/design comparison only)")
    print(f"bundle published: {output_dir}")
    return EXIT_OK


def run_cli(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)

    output_dir: Path = args.output_dir

    try:
        pydoublet_raw_result = _load_json_dict(args.input, label="input")
        config = _load_json_dict(args.config, label="config")
        source_provenance = _load_provenance(args.provenance)
        validate_config_structure(config)
        _validate_output_dir(output_dir, overwrite=args.overwrite)
    except (_CliInputError, WorkflowConfigurationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    if is_joint_optimization_enabled(config):
        return _run_joint_optimization_cli(pydoublet_raw_result, config, source_provenance, output_dir)

    # config is now proven structurally valid (validate_config_structure()
    # above ran every construction run_workflow() itself performs from it).
    # Any exception that still escapes this call is genuinely unexpected --
    # never conflated with a config problem (module docstring).
    try:
        result = run_workflow(pydoublet_raw_result, config, source_provenance=source_provenance)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: this IS the "unexpected" boundary
        print(f"error: unexpected internal failure while running the workflow: {exc!r}", file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR

    try:
        parent_dir = output_dir.parent if str(output_dir.parent) else Path(".")
        parent_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=str(parent_dir)))
    except OSError as exc:
        print(f"error: failed to create a temporary working directory: {exc}", file=sys.stderr)
        return EXIT_ARTIFACT_PUBLICATION_FAILURE

    try:
        _build_bundle_in_temp_dir(result, pydoublet_raw_result, config, temp_dir)
        _publish_temp_dir(temp_dir, output_dir)
    except Exception as exc:  # noqa: BLE001 -- any publication-stage failure maps to one exit code
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"error: failed to publish the artifact bundle: {exc}", file=sys.stderr)
        return EXIT_ARTIFACT_PUBLICATION_FAILURE

    if isinstance(result, WorkflowFailure):
        print(f"workflow stopped: {result.failure_code.value}: {result.message}", file=sys.stderr)
        print(f"run_id: {result.run_id}", file=sys.stderr)
        print(f"bundle published (failure audit trail): {output_dir}", file=sys.stderr)
        return EXIT_WORKFLOW_FAILURE

    print(f"run_id: {result.run_id}")
    if result.ranking.ranked:
        winner = result.ranking.ranked[0]
        print(f"preferred candidate: {winner.candidate_id} (rank 1 of {len(result.ranking.ranked)} feasible)")
    else:
        print("completed with zero feasible candidates -- no recommendation")
    print(f"bundle published: {output_dir}")
    return EXIT_OK


def main() -> None:
    sys.exit(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
