"""Full test matrix for workflow/cli.py -- the r3chain-geothermal-demo
CLI entry point (T2.4B2). Runs `run_cli()` in-process (never subprocess --
faster and gives direct access to the exit code) against the real golden
fixture/config/provenance files, into a tempdir per test."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from r3chain_geothermal.workflow import cli as cli_module
from r3chain_geothermal.workflow.cli import (
    EXIT_ARTIFACT_PUBLICATION_FAILURE,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    EXIT_UNEXPECTED_ERROR,
    EXIT_WORKFLOW_FAILURE,
    run_cli,
)

_ROOT = Path(__file__).resolve().parents[2]
_INPUT_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_PROVENANCE_PATH = _ROOT / "config" / "demo_source_provenance.json"

_ALL_EIGHT_FILENAMES = (
    "pydoublet_input.json", "config_snapshot.json", "workflow_result.json", "audit.json",
    "candidate_comparison.csv", "network_candidates.svg", "recommendation.md", "manifest.json",
)
_FOUR_CORE_FILENAMES = ("pydoublet_input.json", "config_snapshot.json", "workflow_result.json", "audit.json", "manifest.json")


def _args(output_dir: Path, *, input_path: Path = _INPUT_PATH, config_path: Path = _CONFIG_PATH,
          provenance_path: Path = _PROVENANCE_PATH, overwrite: bool = False) -> list[str]:
    argv = [
        "--input", str(input_path), "--config", str(config_path),
        "--provenance", str(provenance_path), "--output-dir", str(output_dir),
    ]
    if overwrite:
        argv.append("--overwrite")
    return argv


def test_worked_case_exits_zero_and_publishes_all_eight_artifacts():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_OK
        for filename in _ALL_EIGHT_FILENAMES:
            assert (output_dir / filename).exists(), f"{filename} missing"


def test_worked_case_csv_has_committed_lcoh_and_stable_ordering():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        run_cli(_args(output_dir))
        text = (output_dir / "candidate_comparison.csv").read_text()
        lines = text.splitlines()
        assert lines[1].startswith("C1,")
        assert lines[2].startswith("C2,")
        assert lines[3].startswith("C3,")
        assert lines[4].startswith("C4,")
        assert "52.1714" in text


def test_manifest_has_all_eight_hash_entries():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        run_cli(_args(output_dir))
        manifest = json.loads((output_dir / "manifest.json").read_text())
        assert set(manifest["files"].keys()) == {f for f in _ALL_EIGHT_FILENAMES if f != "manifest.json"}


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


def test_invalid_provenance_exits_input_error():
    with tempfile.TemporaryDirectory() as td:
        bad_provenance = Path(td) / "bad_provenance.json"
        bad_provenance.write_text(json.dumps({"calculation_mode": "not_a_valid_mode"}))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, provenance_path=bad_provenance))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_non_object_json_input_exits_input_error():
    with tempfile.TemporaryDirectory() as td:
        list_path = Path(td) / "a_list.json"
        list_path.write_text("[1, 2, 3]")
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, input_path=list_path))
        assert exit_code == EXIT_INPUT_ERROR


def test_non_empty_output_dir_without_overwrite_is_refused_and_left_untouched():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        output_dir.mkdir()
        marker = output_dir / "pre_existing_file.txt"
        marker.write_text("do not touch")
        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_INPUT_ERROR
        assert marker.exists()
        assert marker.read_text() == "do not touch"
        assert not (output_dir / "manifest.json").exists()


def test_non_empty_output_dir_with_overwrite_replaces_cleanly():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        output_dir.mkdir()
        (output_dir / "stale_file.txt").write_text("stale")
        exit_code = run_cli(_args(output_dir, overwrite=True))
        assert exit_code == EXIT_OK
        assert not (output_dir / "stale_file.txt").exists()
        assert (output_dir / "manifest.json").exists()


def test_empty_existing_output_dir_does_not_require_overwrite():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        output_dir.mkdir()
        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_OK


def test_workflow_stopping_failure_exits_workflow_failure_and_still_publishes_audit_trail():
    with tempfile.TemporaryDirectory() as td:
        bad_input = Path(td) / "empty_pydoublet.json"
        bad_input.write_text("{}")
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, input_path=bad_input))
        assert exit_code == EXIT_WORKFLOW_FAILURE
        # Preserves raw inputs / audit trail even on a stopping failure (CLAUDE.md).
        for filename in _FOUR_CORE_FILENAMES:
            assert (output_dir / filename).exists(), f"{filename} missing on workflow failure"
        # No presentation artifacts -- a WorkflowFailure has no candidate/ranking data.
        assert not (output_dir / "recommendation.md").exists()


def test_zero_feasible_candidates_exits_zero_not_a_failure():
    """Reuses T2.3's own p_supply_bar_abs=4.51 contrivance (fails every
    candidate) -- a COMPLETED workflow with zero feasible candidates is a
    valid, honest result, never treated as an error (CLAUDE.md / plan)."""
    with tempfile.TemporaryDirectory() as td:
        config = json.loads(_CONFIG_PATH.read_text())
        config["network"]["p_supply_bar_abs"] = 4.51
        config_path = Path(td) / "config.json"
        config_path.write_text(json.dumps(config))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, config_path=config_path))
        assert exit_code == EXIT_OK
        recommendation = (output_dir / "recommendation.md").read_text()
        assert "No candidate is feasible" in recommendation


def test_two_complete_runs_produce_matching_bundle_scientific_hash():
    with tempfile.TemporaryDirectory() as td:
        output_dir_1 = Path(td) / "demo1"
        output_dir_2 = Path(td) / "demo2"
        run_cli(_args(output_dir_1))
        run_cli(_args(output_dir_2))
        manifest_1 = json.loads((output_dir_1 / "manifest.json").read_text())
        manifest_2 = json.loads((output_dir_2 / "manifest.json").read_text())
        assert manifest_1["bundle_scientific_sha256"] == manifest_2["bundle_scientific_sha256"]
        assert manifest_1["run_id"] == manifest_2["run_id"]


def test_temp_sibling_directory_is_not_left_behind_after_success():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        run_cli(_args(output_dir))
        leftovers = [p for p in Path(td).iterdir() if p != output_dir]
        assert leftovers == []


def test_temp_sibling_directory_is_not_left_behind_after_workflow_failure():
    with tempfile.TemporaryDirectory() as td:
        bad_input = Path(td) / "empty_pydoublet.json"
        bad_input.write_text("{}")
        output_dir = Path(td) / "demo"
        run_cli(_args(output_dir, input_path=bad_input))
        leftovers = [p for p in Path(td).iterdir() if p not in (output_dir, bad_input)]
        assert leftovers == []


def test_no_llm_agent_or_prompt_related_identifier_in_cli_module():
    """Matches the same structural check used at every earlier layer:
    this module never calls an LLM/agent/MCP tool of its own -- a bare
    "CLAUDE.md" citation (this project's own rules file, referenced by
    core.py/artifacts.py too) is not such a call, so it is excluded
    before scanning."""
    source = (_ROOT / "src" / "r3chain_geothermal" / "workflow" / "cli.py").read_text().lower()
    source_without_claude_md_citation = source.replace("claude.md", "")
    for forbidden in ("llm", "mcp", "agent", "prompt", "anthropic", "claude", "gpt", "openai"):
        assert forbidden not in source_without_claude_md_citation, f"unexpected {forbidden!r} found in cli.py"


@pytest.mark.parametrize("missing_flag", ["--input", "--config", "--provenance", "--output-dir"])
def test_missing_required_flag_exits_with_input_error_code_not_argparses_default(missing_flag: str):
    """argparse's own default for a bad/missing argument is exit code 2,
    which would collide with this CLI's documented EXIT_WORKFLOW_FAILURE
    (2) -- _CliArgumentParser.error() overrides this to EXIT_INPUT_ERROR (1)."""
    argv = _args(Path("/tmp/unused"))
    idx = argv.index(missing_flag)
    del argv[idx:idx + 2]
    with pytest.raises(SystemExit) as exc_info:
        run_cli(argv)
    assert exc_info.value.code == EXIT_INPUT_ERROR


def test_help_flag_exits_zero_not_input_error():
    with pytest.raises(SystemExit) as exc_info:
        run_cli(["--help"])
    assert exc_info.value.code == EXIT_OK


def test_unrecognized_flag_exits_with_input_error_code():
    with pytest.raises(SystemExit) as exc_info:
        run_cli(["--not-a-real-flag", "value"])
    assert exc_info.value.code == EXIT_INPUT_ERROR


# ── Non-finite (NaN/Infinity) JSON is rejected in all three inputs ──────────
@pytest.mark.parametrize("target", ["input", "config", "provenance"])
def test_non_finite_json_is_rejected_in_every_input_file(target: str):
    with tempfile.TemporaryDirectory() as td:
        bad_path = Path(td) / f"bad_{target}.json"
        bad_path.write_text('{"value": NaN}')
        output_dir = Path(td) / "demo"
        kwargs = {f"{target}_path": bad_path}
        exit_code = run_cli(_args(output_dir, **kwargs))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_each_non_finite_json_token_is_rejected(token: str):
    with tempfile.TemporaryDirectory() as td:
        bad_path = Path(td) / "bad_input.json"
        bad_path.write_text(f'{{"value": {token}}}')
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, input_path=bad_path))
        assert exit_code == EXIT_INPUT_ERROR


# ── A structurally malformed --config surfaces as exit code 1, not a crash ──
def test_config_missing_a_required_top_level_section_exits_input_error():
    with tempfile.TemporaryDirectory() as td:
        config = json.loads(_CONFIG_PATH.read_text())
        del config["gates"]
        config_path = Path(td) / "config.json"
        config_path.write_text(json.dumps(config))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, config_path=config_path))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_config_missing_a_required_nested_field_exits_input_error():
    with tempfile.TemporaryDirectory() as td:
        config = json.loads(_CONFIG_PATH.read_text())
        del config["coupling_assumptions"]["dh_supply_temperature_c"]
        config_path = Path(td) / "config.json"
        config_path.write_text(json.dumps(config))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, config_path=config_path))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_config_with_wrong_field_type_exits_input_error():
    """gates.min_pressure_bar_abs must be numeric; GateTolerances'
    pydantic validation rejects a string, surfacing as a ValidationError
    the CLI must catch and map to exit code 1, not an unhandled traceback."""
    with tempfile.TemporaryDirectory() as td:
        config = json.loads(_CONFIG_PATH.read_text())
        config["gates"]["min_pressure_bar_abs"] = "not-a-number"
        config_path = Path(td) / "config.json"
        config_path.write_text(json.dumps(config))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, config_path=config_path))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_config_with_an_invalid_value_exits_input_error_not_a_crash():
    """GateTolerances' own model_validator rejects a non-positive
    tolerance with a plain ValueError -- also caught and mapped to 1."""
    with tempfile.TemporaryDirectory() as td:
        config = json.loads(_CONFIG_PATH.read_text())
        config["gates"]["max_pipe_velocity_m_s"] = -1.0
        config_path = Path(td) / "config.json"
        config_path.write_text(json.dumps(config))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, config_path=config_path))
        assert exit_code == EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_valid_config_still_exits_zero_after_the_structure_error_handling_was_added():
    """Regression guard: validate_config_structure() must not
    accidentally reject a legitimate, structurally valid config."""
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_OK


# ── Exit code 4: an unexpected internal failure, kept distinguishable from
#    exit code 1 (config/input problem) -- reachable only AFTER config has
#    already been proven structurally valid ─────────────────────────────────
def test_unexpected_run_workflow_failure_exits_four_not_one(monkeypatch):
    """Simulates a genuine internal defect (a solver crash, a programming
    bug) by making run_workflow() itself raise, for an otherwise
    perfectly valid --config/--input/--provenance. This must be exit
    code 4, never exit code 1 -- conflating the two would misreport a
    real defect as "your configuration is wrong.\""""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated solver/programming defect")

    monkeypatch.setattr(cli_module, "run_workflow", _boom)
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_UNEXPECTED_ERROR
        assert exit_code != EXIT_INPUT_ERROR
        assert not output_dir.exists()


def test_a_malformed_config_exits_one_not_four():
    """The counterpart to the test above: a STRUCTURALLY invalid config
    is caught by validate_config_structure() before run_workflow() is
    ever called, and must stay exit code 1, never drift to exit code 4."""
    with tempfile.TemporaryDirectory() as td:
        config = json.loads(_CONFIG_PATH.read_text())
        del config["gates"]
        config_path = Path(td) / "config.json"
        config_path.write_text(json.dumps(config))
        output_dir = Path(td) / "demo"
        exit_code = run_cli(_args(output_dir, config_path=config_path))
        assert exit_code == EXIT_INPUT_ERROR
        assert exit_code != EXIT_UNEXPECTED_ERROR


# ── Staged, rollback-safe replacement (NOT crash-atomic): backup/swap/restore
#    -- see cli.py's own module docstring for why "atomic" is not used ──────
def test_overwrite_publication_failure_preserves_the_previous_bundle(monkeypatch):
    """Publishes a valid bundle, then injects a failure into the FINAL
    swap (temp_dir -> output_dir) of a second, --overwrite run. The
    previous bundle must survive completely unchanged, and the CLI must
    report EXIT_ARTIFACT_PUBLICATION_FAILURE, not silently lose data."""
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"

        exit_code = run_cli(_args(output_dir))
        assert exit_code == EXIT_OK
        original_manifest_bytes = (output_dir / "manifest.json").read_bytes()
        original_csv_bytes = (output_dir / "candidate_comparison.csv").read_bytes()

        real_replace = os.replace
        call_count = {"n": 0}

        def _flaky_replace(src, dst):
            if str(dst) == str(output_dir):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise OSError("simulated failure swapping in the new bundle")
            return real_replace(src, dst)

        monkeypatch.setattr(cli_module.os, "replace", _flaky_replace)

        exit_code = run_cli(_args(output_dir, overwrite=True))
        assert exit_code == EXIT_ARTIFACT_PUBLICATION_FAILURE

        # The previous bundle must still be there, byte-for-byte unchanged.
        assert output_dir.exists()
        assert (output_dir / "manifest.json").read_bytes() == original_manifest_bytes
        assert (output_dir / "candidate_comparison.csv").read_bytes() == original_csv_bytes

        # No stray backup/temp directories left behind in the parent.
        leftovers = [p for p in Path(td).iterdir() if p != output_dir]
        assert leftovers == [], f"unexpected leftover paths: {leftovers}"

        # The restore itself was exercised (not just the initial failure).
        assert call_count["n"] == 2


def test_overwrite_success_leaves_no_backup_directory_behind():
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td) / "demo"
        run_cli(_args(output_dir))
        run_cli(_args(output_dir, overwrite=True))
        leftovers = [p for p in Path(td).iterdir() if p != output_dir]
        assert leftovers == []


def test_overwrite_of_a_stopping_failure_bundle_also_rolls_back_on_publication_failure(monkeypatch):
    """The backup/swap/restore path is exercised identically regardless
    of whether the PREVIOUS bundle was a completed result or a stopped
    WorkflowFailure's 5-file audit trail."""
    with tempfile.TemporaryDirectory() as td:
        bad_input = Path(td) / "empty_pydoublet.json"
        bad_input.write_text("{}")
        output_dir = Path(td) / "demo"

        exit_code = run_cli(_args(output_dir, input_path=bad_input))
        assert exit_code == EXIT_WORKFLOW_FAILURE
        original_manifest_bytes = (output_dir / "manifest.json").read_bytes()

        real_replace = os.replace
        call_count = {"n": 0}

        def _flaky_replace(src, dst):
            if str(dst) == str(output_dir):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise OSError("simulated failure swapping in the new bundle")
            return real_replace(src, dst)

        monkeypatch.setattr(cli_module.os, "replace", _flaky_replace)

        exit_code = run_cli(_args(output_dir, input_path=bad_input, overwrite=True))
        assert exit_code == EXIT_ARTIFACT_PUBLICATION_FAILURE
        assert (output_dir / "manifest.json").read_bytes() == original_manifest_bytes
