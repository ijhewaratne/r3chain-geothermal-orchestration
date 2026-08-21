"""Writes the T2.4B1 machine-readable output package (plan §15's scientific
subset -- the human-facing bundle, CSV/SVG/Markdown/CLI, is T2.4B2, not
implemented here).

Five files, written in a fixed order, in `output_dir` (must already
exist; this module never creates directories -- that is a CLI concern,
T2.4B2):

    pydoublet_input.json   -- the ORIGINAL raw PyDoublet result, unchanged
    config_snapshot.json   -- the config dict actually consumed, unchanged
    workflow_result.json   -- result.model_dump_json(indent=2)
    audit.json             -- result.audit.model_dump_json(indent=2)
    manifest.json           -- SHA-256 of the four files above's own bytes
                               (written LAST; never hashes itself)

No absolute local paths, credentials, or environment-specific data ever
appear INSIDE any artifact's JSON content -- `manifest.json` records only
relative filenames (never `str(output_dir)`), and the four hashed files
are the caller-supplied `pydoublet_raw_result`/`config` dicts and the
already-content-only typed `result`, none of which this module enriches
with anything path- or environment-derived.

## `manifest.json`'s hashes are RAW BYTE hashes, not "stable scientific
content" hashes -- read this precisely

`pydoublet_input.json`/`config_snapshot.json` are pure input echoes with
no timestamp field anywhere in them -- their byte hashes ARE stable and
reproducible across any number of runs with identical input/config.
`workflow_result.json`/`audit.json`, by contrast, embed `created_at` at
8+ nesting depths (`run_workflow()`'s own, and every wall-clock-generated
sub-result's own -- core.py's module docstring, "Determinism"). Under a
REAL (wall-clock) invocation, two otherwise-identical runs will
legitimately produce DIFFERENT byte hashes for these two files, because
`created_at` differs -- this is expected, not a reproducibility bug, and
`manifest.json`'s hashes must never be described elsewhere as
"stable"/"scientific-content" hashes on that basis alone. **Injecting a
fixed `now` into `run_workflow()` does NOT by itself make these two files
byte-identical across two independent runs either** -- the injected clock
only controls `run_workflow()`'s own top-level `created_at` and the one
it passes to `build_default_blueprint()`; every OTHER embedded
sub-result (PyDoublet, HX, baseline, each candidate, each candidate's
economics, ranking) still generates its own uncontrolled
`datetime.now(timezone.utc)` internally (core.py's module docstring,
"Determinism" -- retrofitting clock injection into those six
already-committed functions was explicitly out of scope for T2.4B1). The
ONLY thing guaranteed content-stable across independent runs, clock or
no clock, is `run_id` itself (a pure hash of input/config/provenance/
schema-version) and the two pure input echoes above. A separate,
timestamp-normalized "scientific content hash" for
`workflow_result.json`/`audit.json` (excluding every `created_at` before
hashing) is a T2.4B2 concern, not implemented here.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from ..hashing import canonical_raw_result_json_bytes
from .core import WorkflowBoundaryResult

MANIFEST_CONTRACT_SCHEMA_VERSION = "1.0.0"

PYDOUBLET_INPUT_FILENAME = "pydoublet_input.json"
CONFIG_SNAPSHOT_FILENAME = "config_snapshot.json"
WORKFLOW_RESULT_FILENAME = "workflow_result.json"
AUDIT_FILENAME = "audit.json"
MANIFEST_FILENAME = "manifest.json"

_HASHED_FILENAMES_IN_ORDER = (
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, WORKFLOW_RESULT_FILENAME, AUDIT_FILENAME,
)


class ManifestRecord(BaseModel):
    """manifest.json's own content -- the SHA-256 BYTE hash of the four
    other files' actual on-disk bytes (module docstring: NOT a
    timestamp-normalized "scientific content" hash -- workflow_result.json/
    audit.json legitimately hash differently across two real wall-clock
    runs of identical input, because they contain created_at). Never
    includes a hash of itself (by construction: `files` only ever
    contains _HASHED_FILENAMES_IN_ORDER, which excludes MANIFEST_FILENAME)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = MANIFEST_CONTRACT_SCHEMA_VERSION
    run_id: str
    created_at: datetime
    files: dict[str, str]
    """filename (relative, never an absolute path) -> lowercase hex SHA-256
    BYTE hash of that file's on-disk bytes (raw bytes, including any
    embedded created_at fields -- see module docstring)."""

    @model_validator(mode="after")
    def _validate(self) -> "ManifestRecord":
        errors: list[str] = []
        if set(self.files.keys()) != set(_HASHED_FILENAMES_IN_ORDER):
            errors.append(
                f"files must contain exactly {sorted(_HASHED_FILENAMES_IN_ORDER)}, got {sorted(self.files.keys())}"
            )
        if MANIFEST_FILENAME in self.files:
            errors.append("manifest.json must never hash itself")
        for filename, digest in self.files.items():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                errors.append(f"files[{filename!r}] is not a lowercase 64-char hex SHA-256 digest")
            if "/" in filename or "\\" in filename or filename.startswith("."):
                errors.append(f"files[{filename!r}] must be a plain relative filename, not a path")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_workflow_artifacts(
    result: WorkflowBoundaryResult,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
) -> ManifestRecord:
    """Writes the 5 artifacts into `output_dir` (must already exist and
    be writable -- this function never creates or removes directories).
    Returns the ManifestRecord that was also written to manifest.json."""
    pydoublet_input_bytes = canonical_raw_result_json_bytes(pydoublet_raw_result)
    (output_dir / PYDOUBLET_INPUT_FILENAME).write_bytes(pydoublet_input_bytes)

    config_snapshot_bytes = canonical_raw_result_json_bytes(config)
    (output_dir / CONFIG_SNAPSHOT_FILENAME).write_bytes(config_snapshot_bytes)

    workflow_result_bytes = result.model_dump_json(indent=2).encode("utf-8")
    (output_dir / WORKFLOW_RESULT_FILENAME).write_bytes(workflow_result_bytes)

    audit_bytes = result.audit.model_dump_json(indent=2).encode("utf-8")
    (output_dir / AUDIT_FILENAME).write_bytes(audit_bytes)

    manifest = ManifestRecord(
        run_id=result.run_id,
        created_at=datetime.now(timezone.utc),
        files={
            PYDOUBLET_INPUT_FILENAME: _sha256_of_bytes(pydoublet_input_bytes),
            CONFIG_SNAPSHOT_FILENAME: _sha256_of_bytes(config_snapshot_bytes),
            WORKFLOW_RESULT_FILENAME: _sha256_of_bytes(workflow_result_bytes),
            AUDIT_FILENAME: _sha256_of_bytes(audit_bytes),
        },
    )
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest
