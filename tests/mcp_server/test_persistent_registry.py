"""Persistent, restart-safe run registry (RR-001..RR-009,
docs/issues/mcp-persistent-run-registry.md).

`tests/mcp_server/test_registry.py` covers the original ephemeral-registry
concurrency mechanics, entirely unaffected by this feature (persistent=False
is the untouched default). This file covers what's new: RR-008's full
restart-recovery acceptance test, atomic publication, corrupt-bundle
handling, and run-id/path safety on rehydration.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from r3chain_geothermal.mcp_server import tools
from r3chain_geothermal.mcp_server.config import load_fixed_server_config
from r3chain_geothermal.mcp_server.errors import ToolErrorCode
from r3chain_geothermal.mcp_server.registry import RegistryClosedError, RunRegistry
from r3chain_geothermal.mcp_server.schemas import RunSummary, SourceProvenanceInput

_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"
_GOLDEN_RUN_ID = "r3chain-run-93d41133daa11d1a"


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance() -> SourceProvenanceInput:
    return SourceProvenanceInput(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT, source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )


@pytest.fixture
def fixed_config():
    return load_fixed_server_config()


# ── RR-001: persistent=True requires an explicit root_dir ───────────────────
def test_persistent_requires_explicit_root_dir():
    with pytest.raises(ValueError):
        RunRegistry(persistent=True)


# ── RR-001: close() does not delete root_dir when persistent ────────────────
def test_close_does_not_delete_root_dir_when_persistent():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        reg = RunRegistry(root_dir=root, persistent=True)
        reg.close()
        assert root.is_dir()  # tempfile.TemporaryDirectory's own cleanup removes it after the `with` exits


def test_close_still_deletes_root_dir_when_not_persistent():
    td = tempfile.mkdtemp()
    root = Path(td)
    reg = RunRegistry(root_dir=root, persistent=False)
    reg.close()
    assert not root.exists()


# ── RR-008: the full restart-recovery acceptance test ───────────────────────
def test_rr008_restart_recovery_full_acceptance(fixed_config):
    """1. start a server (registry) with a temporary persistent root;
    2. run a complete workflow;
    3. terminate the server cleanly (close());
    4. start a new server process (a fresh RunRegistry) against the same root;
    5. retrieve the summary and audit;
    6. retrieve all pages of workflow_result.json;
    7. reconstruct the bytes and verify the manifest hash;
    8. confirm no new workflow computation occurred."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # 1-2: first "server" runs the workflow.
        reg1 = RunRegistry(root_dir=root, persistent=True)
        first_result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=reg1)
        assert isinstance(first_result, RunSummary)
        assert first_result.run_id == _GOLDEN_RUN_ID
        original_entry = reg1.get(_GOLDEN_RUN_ID)
        assert original_entry is not None

        # 3: terminate cleanly -- root_dir must survive this (already
        # covered above, re-asserted here as part of the full flow).
        reg1.close()
        assert root.is_dir()

        # 4: a genuinely new registry instance, simulating a fresh process,
        # against the SAME root -- rehydration happens inside __init__.
        reg2 = RunRegistry(root_dir=root, persistent=True)
        assert reg2.rehydration_warnings == []

        # 5: summary + audit retrievable, and IDENTICAL scientific content
        # to the original run (same audit run_id/stage calls, same bundle
        # hash below) -- proof this is the rehydrated entry, not a fresh
        # recomputation (RunEntry.created_at is a wall-clock "when this
        # object was constructed" timestamp, deliberately different from
        # manifest.created_at -- not a useful equality check on its own;
        # "no recomputation occurred" is proven precisely in step 8 below
        # via reused_existing_run).
        rehydrated_entry = reg2.get(_GOLDEN_RUN_ID)
        assert rehydrated_entry is not None
        assert rehydrated_entry.audit.run_id == original_entry.audit.run_id
        summary_result = tools.get_run_summary(_GOLDEN_RUN_ID, registry=reg2)
        assert isinstance(summary_result, RunSummary)
        assert summary_result.run_id == _GOLDEN_RUN_ID
        assert summary_result.bundle_scientific_sha256 == first_result.bundle_scientific_sha256
        audit_result = tools.get_audit(_GOLDEN_RUN_ID, registry=reg2)
        assert audit_result.audit.run_id == _GOLDEN_RUN_ID

        # 6-7: full pagination of workflow_result.json reconstructs the
        # exact original bytes, verified against the manifest's own hash.
        manifest_slice = tools.get_artifact(_GOLDEN_RUN_ID, "manifest.json", registry=reg2)
        manifest = json.loads(manifest_slice.content)
        expected_hash = manifest["files"]["workflow_result.json"]["byte_sha256"]

        chunks = []
        offset = 0
        while True:
            piece = tools.get_artifact(_GOLDEN_RUN_ID, "workflow_result.json", registry=reg2, offset=offset)
            chunks.append(piece.content)
            if piece.next_offset is None:
                break
            offset = piece.next_offset
        reconstructed = "".join(chunks)
        import hashlib
        assert hashlib.sha256(reconstructed.encode("utf-8")).hexdigest() == expected_hash

        # 8: no new computation -- get_or_run's own "reused_existing_run"
        # flag on a THIRD call against reg2 confirms this run_id is served
        # from the (now in-memory, rehydrated) entry, not recomputed.
        third_call = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=reg2)
        assert isinstance(third_call, RunSummary)
        assert third_call.reused_existing_run is True

        reg2.close()


# ── RR-003: corrupt/incomplete bundles are skipped, never crash startup ─────
def test_corrupt_manifest_is_skipped_with_a_warning(fixed_config):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        reg1 = RunRegistry(root_dir=root, persistent=True)
        result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=reg1)
        assert isinstance(result, RunSummary)
        reg1.close()

        # Corrupt the published manifest.json in place.
        manifest_path = root / result.run_id / "manifest.json"
        manifest_path.write_text("{not valid json")

        reg2 = RunRegistry(root_dir=root, persistent=True)
        assert reg2.get(result.run_id) is None
        assert len(reg2.rehydration_warnings) == 1
        assert result.run_id in reg2.rehydration_warnings[0]
        # RUN_NOT_FOUND for any tool call against it -- never a crash, never
        # silently-served corrupt/partial data.
        assert tools.get_run_summary(result.run_id, registry=reg2).code == ToolErrorCode.RUN_NOT_FOUND
        reg2.close()


def test_missing_declared_file_is_skipped_with_a_warning(fixed_config):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        reg1 = RunRegistry(root_dir=root, persistent=True)
        result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=reg1)
        assert isinstance(result, RunSummary)
        reg1.close()

        (root / result.run_id / "candidate_comparison.csv").unlink()

        reg2 = RunRegistry(root_dir=root, persistent=True)
        assert reg2.get(result.run_id) is None
        assert len(reg2.rehydration_warnings) == 1
        reg2.close()


def test_tampered_file_content_is_skipped_with_a_warning(fixed_config):
    """The manifest's own self-consistency check (ManifestRecord's
    model_validator) only proves the manifest is internally coherent --
    this test proves rehydration ALSO checks the manifest's claimed
    byte_sha256 against what is actually on disk."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        reg1 = RunRegistry(root_dir=root, persistent=True)
        result = tools.run_workflow_tool(_raw(), _provenance(), fixed_config=fixed_config, registry=reg1)
        assert isinstance(result, RunSummary)
        reg1.close()

        recommendation_path = root / result.run_id / "recommendation.md"
        recommendation_path.write_text(recommendation_path.read_text() + "\ntampered\n")

        reg2 = RunRegistry(root_dir=root, persistent=True)
        assert reg2.get(result.run_id) is None
        assert len(reg2.rehydration_warnings) == 1
        reg2.close()


# ── RR-003/security: non-matching directory names are silently ignored, not errors ──
def test_unrelated_directories_in_root_are_ignored():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "not-a-run-id").mkdir()
        (root / "..").resolve()  # sanity: this test itself never escapes root
        reg = RunRegistry(root_dir=root, persistent=True)
        assert reg.rehydration_warnings == []
        assert len(reg) == 0
        reg.close()


# ── RR-004: abandoned staging directories are cleaned up on rehydration ─────
def test_abandoned_staging_directory_is_removed_on_rehydration():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stale_staging = root / ".staging-r3chain-run-0000000000000000-abcd1234"
        stale_staging.mkdir()
        (stale_staging / "partial.txt").write_text("incomplete")
        reg = RunRegistry(root_dir=root, persistent=True)
        assert not stale_staging.exists()
        assert reg.rehydration_warnings == []  # cleanup is silent, not a warning -- it's expected debris
        reg.close()


# ── RR-002: publish_artifact_dir refuses to publish an incomplete staging dir ──
def test_publish_refuses_a_staging_dir_with_no_manifest():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        reg = RunRegistry(root_dir=root, persistent=False)
        run_id = "r3chain-run-0000000000000000"
        staging = reg.new_artifact_dir(run_id)
        (staging / "workflow_result.json").write_text("{}")  # no manifest.json
        with pytest.raises(ValueError):
            reg.publish_artifact_dir(run_id, staging)
        assert not (root / run_id).exists()  # never published
        reg.close()
