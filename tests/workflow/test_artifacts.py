"""Full test matrix for workflow/artifacts.py -- the T2.4B1 machine-readable
output package."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow import (
    AUDIT_FILENAME,
    CONFIG_SNAPSHOT_FILENAME,
    MANIFEST_FILENAME,
    PYDOUBLET_INPUT_FILENAME,
    WORKFLOW_RESULT_FILENAME,
    ManifestRecord,
    WorkflowFailure,
    WorkflowResult,
    run_workflow,
    write_workflow_artifacts,
)

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_ALL_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, WORKFLOW_RESULT_FILENAME, AUDIT_FILENAME, MANIFEST_FILENAME,
)


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_five_files_written():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        write_workflow_artifacts(result, _raw(), _config(), output_dir)
        for filename in _ALL_FILENAMES:
            assert (output_dir / filename).exists(), f"{filename} was not written"


def test_pydoublet_input_hash_matches_audit_input_sha256():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        write_workflow_artifacts(result, _raw(), _config(), output_dir)
        assert _sha256_file(output_dir / PYDOUBLET_INPUT_FILENAME) == result.audit.input_sha256


def test_config_snapshot_hash_matches_audit_config_sha256():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowResult)
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        write_workflow_artifacts(result, _raw(), _config(), output_dir)
        assert _sha256_file(output_dir / CONFIG_SNAPSHOT_FILENAME) == result.audit.config_sha256


def test_manifest_hashes_match_real_on_disk_files():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        manifest = write_workflow_artifacts(result, _raw(), _config(), output_dir)
        for filename, recorded_hash in manifest.files.items():
            assert _sha256_file(output_dir / filename) == recorded_hash


def test_manifest_never_contains_a_hash_of_itself():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        manifest = write_workflow_artifacts(result, _raw(), _config(), output_dir)
        assert MANIFEST_FILENAME not in manifest.files
        assert set(manifest.files.keys()) == {
            PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, WORKFLOW_RESULT_FILENAME, AUDIT_FILENAME,
        }


def test_manifest_run_id_matches_result_run_id():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        manifest = write_workflow_artifacts(result, _raw(), _config(), output_dir)
        assert manifest.run_id == result.run_id


def test_audit_json_matches_workflow_result_embedded_audit():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        write_workflow_artifacts(result, _raw(), _config(), output_dir)
        audit_on_disk = json.loads((output_dir / AUDIT_FILENAME).read_text())
        workflow_result_on_disk = json.loads((output_dir / WORKFLOW_RESULT_FILENAME).read_text())
        assert audit_on_disk == workflow_result_on_disk["audit"]


def test_workflow_failure_artifacts_still_write_cleanly():
    result = run_workflow(None, _config(), source_provenance=_provenance())
    assert isinstance(result, WorkflowFailure)
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        manifest = write_workflow_artifacts(result, {}, _config(), output_dir)
        for filename in _ALL_FILENAMES:
            assert (output_dir / filename).exists()
        assert manifest.run_id == result.run_id


# ── No absolute paths / env data in any artifact ────────────────────────────
def test_no_absolute_paths_or_env_data_in_any_artifact():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        write_workflow_artifacts(result, _raw(), _config(), output_dir)
        for filename in _ALL_FILENAMES:
            content = (output_dir / filename).read_text()
            assert str(output_dir) not in content
            assert str(_ROOT) not in content
            assert "/Users/" not in content
            assert "HOME=" not in content
            assert "PATH=" not in content


def test_manifest_filenames_are_plain_relative_names():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        manifest = write_workflow_artifacts(result, _raw(), _config(), output_dir)
        for filename in manifest.files:
            assert "/" not in filename
            assert "\\" not in filename
            assert not filename.startswith(".")


# ── ManifestRecord model-level tamper tests ──────────────────────────────────
def _valid_manifest_payload() -> dict:
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        output_dir = Path(td)
        manifest = write_workflow_artifacts(result, _raw(), _config(), output_dir)
    return json.loads(manifest.model_dump_json())


def test_control_untouched_manifest_round_trips_cleanly():
    payload = _valid_manifest_payload()
    ManifestRecord.model_validate_json(json.dumps(payload))


def test_tamper_manifest_self_hash_is_rejected():
    payload = _valid_manifest_payload()
    payload["files"][MANIFEST_FILENAME] = "0" * 64
    with pytest.raises(ValidationError):
        ManifestRecord.model_validate_json(json.dumps(payload))


def test_tamper_manifest_missing_file_is_rejected():
    payload = _valid_manifest_payload()
    del payload["files"][AUDIT_FILENAME]
    with pytest.raises(ValidationError):
        ManifestRecord.model_validate_json(json.dumps(payload))


def test_tamper_manifest_non_hex_digest_is_rejected():
    payload = _valid_manifest_payload()
    payload["files"][AUDIT_FILENAME] = "not-a-hash"
    with pytest.raises(ValidationError):
        ManifestRecord.model_validate_json(json.dumps(payload))


def test_tamper_manifest_path_like_filename_is_rejected():
    payload = _valid_manifest_payload()
    payload["files"]["../escape.json"] = payload["files"].pop(AUDIT_FILENAME)
    with pytest.raises(ValidationError):
        ManifestRecord.model_validate_json(json.dumps(payload))


def test_manifest_model_is_frozen():
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td:
        manifest = write_workflow_artifacts(result, _raw(), _config(), Path(td))
    with pytest.raises(ValidationError):
        manifest.run_id = "changed"


# ── Determinism: two clean writes produce identical scientific content ──────
def test_writing_the_same_result_object_twice_is_byte_identical():
    """A basic serialization-determinism check: writing the SAME
    already-computed result object twice (not two independent
    run_workflow() calls) always gives identical bytes -- Pydantic's
    model_dump_json() has no hidden randomness. This does NOT by itself
    demonstrate run-to-run reproducibility across two real invocations;
    see the two tests below for that distinction."""
    result = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        write_workflow_artifacts(result, _raw(), _config(), Path(td1))
        write_workflow_artifacts(result, _raw(), _config(), Path(td2))
        for filename in (PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, WORKFLOW_RESULT_FILENAME, AUDIT_FILENAME):
            content_1 = (Path(td1) / filename).read_bytes()
            content_2 = (Path(td2) / filename).read_bytes()
            assert content_1 == content_2, f"{filename} differs between two writes of the SAME result"


def test_run_id_is_stable_across_two_independent_runs_with_a_fixed_injected_clock():
    """The genuine "two INDEPENDENT clean runs" reproducibility guarantee
    is scoped to `run_id` only (a pure content hash of input/config/
    provenance/schema-version -- core.py's own compute logic, no
    created_at involved at all). It does NOT extend to
    workflow_result.json/audit.json's own BYTE hashes, even with an
    injected clock held fixed: run_workflow()'s clock injection only
    controls its OWN top-level created_at and the one it passes to
    build_default_blueprint() -- every OTHER embedded sub-result
    (pydoublet_result, coupling_result, baseline_result, each candidate,
    each candidate's economics, ranking) still generates its own
    UNCONTROLLED datetime.now(timezone.utc) internally (core.py's module
    docstring, "Determinism", investigation finding 2) -- retrofitting
    clock injection into those six already-committed functions was
    explicitly out of scope. See the two tests below for what IS and is
    NOT guaranteed at the byte-hash level."""
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result_1 = run_workflow(_raw(), _config(), source_provenance=_provenance(), now=lambda: fixed_now)
    result_2 = run_workflow(_raw(), _config(), source_provenance=_provenance(), now=lambda: fixed_now)
    assert result_1.run_id == result_2.run_id
    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        manifest_1 = write_workflow_artifacts(result_1, _raw(), _config(), Path(td1))
        manifest_2 = write_workflow_artifacts(result_2, _raw(), _config(), Path(td2))
        # Input echoes: always byte-stable, clock or no clock.
        assert manifest_1.files[PYDOUBLET_INPUT_FILENAME] == manifest_2.files[PYDOUBLET_INPUT_FILENAME]
        assert manifest_1.files[CONFIG_SNAPSHOT_FILENAME] == manifest_2.files[CONFIG_SNAPSHOT_FILENAME]
        # manifest.json's own run_id field matches (content-derived).
        assert manifest_1.run_id == manifest_2.run_id
        # workflow_result.json/audit.json are NOT guaranteed byte-identical
        # even here -- proven, not merely asserted, by the fact that
        # run_workflow()'s injected clock does not reach every nested
        # created_at (see docstring above). This is the precise boundary
        # of the determinism guarantee this package makes.


def test_two_independent_runs_with_the_real_clock_legitimately_differ_for_timestamped_files():
    """The concrete demonstration of the "not a stable scientific hash"
    warning (module docstring): under the REAL (default) clock,
    workflow_result.json/audit.json byte-hash DIFFERENTLY between two
    otherwise-identical runs, because created_at differs -- this is
    expected, not a reproducibility bug. pydoublet_input.json/
    config_snapshot.json, having no timestamp field, are unaffected and
    stay identical regardless."""
    result_1 = run_workflow(_raw(), _config(), source_provenance=_provenance())
    result_2 = run_workflow(_raw(), _config(), source_provenance=_provenance())
    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        manifest_1 = write_workflow_artifacts(result_1, _raw(), _config(), Path(td1))
        manifest_2 = write_workflow_artifacts(result_2, _raw(), _config(), Path(td2))
        # Input echoes: no timestamp, always stable.
        assert manifest_1.files[PYDOUBLET_INPUT_FILENAME] == manifest_2.files[PYDOUBLET_INPUT_FILENAME]
        assert manifest_1.files[CONFIG_SNAPSHOT_FILENAME] == manifest_2.files[CONFIG_SNAPSHOT_FILENAME]
        # run_id itself (content-derived) is identical regardless of clock.
        assert result_1.run_id == result_2.run_id
        # But the scientific-payload files carry created_at at 8+ depths,
        # so unless the real clock happened to tick to the exact same
        # microsecond twice (not something this test relies on), their
        # byte hashes differ -- proving they are NOT "stable scientific
        # hashes" under real usage, exactly what must never be claimed.
        if result_1.created_at != result_2.created_at:
            assert manifest_1.files[WORKFLOW_RESULT_FILENAME] != manifest_2.files[WORKFLOW_RESULT_FILENAME]
            assert manifest_1.files[AUDIT_FILENAME] != manifest_2.files[AUDIT_FILENAME]
