"""Writes the deterministic output package: T2.4B1's scientific/audit
subset (4 files) plus, when `extra_artifacts` is supplied, T2.4B2's
presentation bundle (`candidate_comparison.csv`/`network_candidates.svg`/
`recommendation.md`) -- ALL written by this one function, so `manifest.json`
is always computed and written LAST, after every applicable artifact
already exists on disk (never before).

Files, written in a fixed order, in `output_dir` (must already exist;
this module never creates directories -- that is `cli.py`'s concern):

    pydoublet_input.json     -- the ORIGINAL raw PyDoublet result, unchanged
    config_snapshot.json     -- the config dict actually consumed, unchanged
    workflow_result.json     -- result.model_dump_json(indent=2)
    audit.json               -- result.audit.model_dump_json(indent=2)
    [candidate_comparison.csv, network_candidates.svg, recommendation.md]
                              -- T2.4B2, via `extra_artifacts`, when supplied
    manifest.json             -- written LAST; never hashes itself

`extra_artifacts`' filenames are validated against an EXACT allow-list
(the three presentation filenames above, nothing else), and every value
is checked to be `bytes`, BEFORE any file is written -- see
`_validate_extra_artifacts` -- so a caller cannot use it for path
traversal (`../escape.txt`), a hidden file, overwriting a core scientific
file or `manifest.json` itself, or a partially-written directory from a
non-bytes payload failing mid-loop.

No absolute local paths, credentials, or environment-specific data ever
appear INSIDE any artifact's JSON content -- `manifest.json` records only
relative filenames (never `str(output_dir)`).

## Two DISTINCT hash concepts per file -- `byte_sha256` vs. `scientific_sha256`

`byte_sha256` is the SHA-256 of a file's EXACT on-disk bytes.
`pydoublet_input.json`/`config_snapshot.json`/the three T2.4B2
presentation files contain no `created_at` field anywhere and are
therefore byte-stable across any number of runs with identical
input/config/provenance. `workflow_result.json`/`audit.json`, by
contrast, embed `created_at` at 8+ nesting depths (`run_workflow()`'s
own, and every wall-clock-generated sub-result's own -- core.py's module
docstring, "Determinism") -- under a REAL (wall-clock) invocation, two
otherwise-identical runs legitimately produce DIFFERENT `byte_sha256` for
these two files. **Injecting a fixed `now` into `run_workflow()` does NOT
by itself make these two files byte-identical across two independent
runs either** -- the injected clock only controls `run_workflow()`'s own
top-level `created_at` and the one it passes to `build_default_blueprint()`;
every other embedded sub-result still wall-clocks internally
(retrofitting clock injection into those six already-committed T1.5B-T2.4A
functions was explicitly out of scope). `manifest.json`'s `byte_sha256`
values must therefore NEVER be described as "stable"/"scientific-content"
hashes on their own.

`scientific_sha256` is the hash of that SAME content after
`hashing.normalize_for_scientific_hash()` (versioned via
`scientific_normalization_rule_version` on the manifest) -- recursively
removing every key literally named `created_at`, nothing else. This IS
stable across independent runs of identical scientific input, regardless
of clock. For the three presentation files (already timestamp-free by
construction) and the two pure input echoes, `byte_sha256` and
`scientific_sha256` are identical; for `workflow_result.json`/`audit.json`
they generally differ in `byte_sha256` but always agree in
`scientific_sha256` across repeated runs of the same input.

`bundle_scientific_sha256` is one further hash derived from the ordered
(`sorted()` by filename) `scientific_sha256` values of every non-manifest
artifact actually written this run -- a single figure for "did the
complete scientific/presentation bundle come out identically."
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from ..hashing import (
    SCIENTIFIC_NORMALIZATION_RULE_VERSION,
    canonical_raw_result_json_bytes,
    canonical_raw_result_sha256,
    normalize_for_scientific_hash,
)
from .core import WorkflowBoundaryResult

MANIFEST_CONTRACT_SCHEMA_VERSION = "2.0.0"
"""Bumped from 1.0.0 (T2.4B1) -- a breaking change to ManifestRecord.files'
own shape (str -> ArtifactHashRecord) and the addition of
bundle_scientific_sha256/scientific_normalization_rule_version."""

PYDOUBLET_INPUT_FILENAME = "pydoublet_input.json"
CONFIG_SNAPSHOT_FILENAME = "config_snapshot.json"
WORKFLOW_RESULT_FILENAME = "workflow_result.json"
AUDIT_FILENAME = "audit.json"
CANDIDATE_COMPARISON_CSV_FILENAME = "candidate_comparison.csv"
NETWORK_CANDIDATES_SVG_FILENAME = "network_candidates.svg"
RECOMMENDATION_MD_FILENAME = "recommendation.md"
MANIFEST_FILENAME = "manifest.json"

_CORE_SCIENTIFIC_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, WORKFLOW_RESULT_FILENAME, AUDIT_FILENAME,
)
_JSON_FILENAMES = frozenset(_CORE_SCIENTIFIC_FILENAMES)
"""Files whose scientific_sha256 is computed via JSON-parse +
normalize_for_scientific_hash(); every other (non-JSON, presentation)
file's scientific_sha256 equals its own byte_sha256 directly (module
docstring)."""

_ALLOWED_EXTRA_ARTIFACT_FILENAMES = frozenset((
    CANDIDATE_COMPARISON_CSV_FILENAME, NETWORK_CANDIDATES_SVG_FILENAME, RECOMMENDATION_MD_FILENAME,
))
"""An EXACT allow-list, not a traversal/hidden-file blacklist -- a caller
may only ever write these three presentation filenames via
`extra_artifacts`. This categorically rules out path traversal
(`../escape.txt`), hidden files (`.hidden`), collision with a core
scientific file (`workflow_result.json`, etc.), collision with
`manifest.json` itself, and any other unexpected filename -- all in one
check, validated BEFORE any file is written (see
`_validate_extra_artifacts`)."""


def _validate_extra_artifacts(extra_artifacts: dict[str, bytes]) -> None:
    """Raises ValueError if `extra_artifacts` contains any filename
    outside `_ALLOWED_EXTRA_ARTIFACT_FILENAMES`, OR any value that is not
    `bytes` -- called as the very first thing `write_workflow_artifacts()`
    does, before it writes even the 4 core files, so a bad call
    (regardless of WHICH entry is bad, or whether it is the filename or
    the payload that is wrong) aborts with NOTHING written to
    `output_dir`. Checking filenames and types together, over the WHOLE
    dict, before any write -- rather than validating and writing
    filename-by-filename inside the same loop -- is what prevents a
    directory left holding some but not all of the intended files (e.g.
    the 4 core files already on disk, then a TypeError on the 2nd of 3
    presentation entries)."""
    unexpected = set(extra_artifacts) - _ALLOWED_EXTRA_ARTIFACT_FILENAMES
    if unexpected:
        raise ValueError(
            f"extra_artifacts contains unexpected filename(s) {sorted(unexpected)!r}; "
            f"only {sorted(_ALLOWED_EXTRA_ARTIFACT_FILENAMES)!r} are permitted"
        )
    non_bytes = {filename: type(data).__name__ for filename, data in extra_artifacts.items() if not isinstance(data, bytes)}
    if non_bytes:
        raise TypeError(f"extra_artifacts values must all be bytes, got non-bytes type(s): {non_bytes!r}")


class ArtifactHashRecord(BaseModel):
    """One artifact's two distinct hashes -- see module docstring."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    byte_sha256: str
    scientific_sha256: str

    @model_validator(mode="after")
    def _validate(self) -> "ArtifactHashRecord":
        for name, digest in (("byte_sha256", self.byte_sha256), ("scientific_sha256", self.scientific_sha256)):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError(f"{name} is not a lowercase 64-char hex SHA-256 digest, got {digest!r}")
        return self


class ManifestRecord(BaseModel):
    """manifest.json's own content. Never includes a hash of itself (by
    construction: `files` never contains MANIFEST_FILENAME)."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = MANIFEST_CONTRACT_SCHEMA_VERSION
    scientific_normalization_rule_version: str = SCIENTIFIC_NORMALIZATION_RULE_VERSION
    run_id: str
    created_at: datetime
    files: dict[str, ArtifactHashRecord]
    """filename (relative, never an absolute path) -> {byte_sha256, scientific_sha256}."""
    bundle_scientific_sha256: str
    """canonical_raw_result_sha256({filename: record.scientific_sha256 for
    filename, record in sorted(files.items())}) -- one figure summarizing
    whether the ENTIRE non-manifest bundle's scientific content matches
    across two runs."""

    @model_validator(mode="after")
    def _validate(self) -> "ManifestRecord":
        errors: list[str] = []
        if not set(_CORE_SCIENTIFIC_FILENAMES) <= set(self.files.keys()):
            errors.append(
                f"files must contain at least the core scientific files {sorted(_CORE_SCIENTIFIC_FILENAMES)}, "
                f"got {sorted(self.files.keys())}"
            )
        if MANIFEST_FILENAME in self.files:
            errors.append("manifest.json must never hash itself")
        for filename in self.files:
            if "/" in filename or "\\" in filename or filename.startswith("."):
                errors.append(f"files[{filename!r}] must be a plain relative filename, not a path")
        expected_bundle_hash = canonical_raw_result_sha256(
            {filename: record.scientific_sha256 for filename, record in sorted(self.files.items())}
        )
        if self.bundle_scientific_sha256 != expected_bundle_hash:
            errors.append("bundle_scientific_sha256 does not match recomputation from files' own scientific_sha256 values")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_record_for_json_bytes(data: bytes) -> ArtifactHashRecord:
    byte_hash = _sha256_of_bytes(data)
    parsed = json.loads(data)
    normalized = normalize_for_scientific_hash(parsed)
    scientific_hash = _sha256_of_bytes(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    )
    return ArtifactHashRecord(byte_sha256=byte_hash, scientific_sha256=scientific_hash)


def _hash_record_for_plain_bytes(data: bytes) -> ArtifactHashRecord:
    """For non-JSON (presentation) files: scientific_sha256 == byte_sha256
    directly (module docstring) -- these files are built with no
    timestamp content at all, so there is nothing to normalize away."""
    byte_hash = _sha256_of_bytes(data)
    return ArtifactHashRecord(byte_sha256=byte_hash, scientific_sha256=byte_hash)


def write_workflow_artifacts(
    result: WorkflowBoundaryResult,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
    *,
    extra_artifacts: dict[str, bytes] | None = None,
) -> ManifestRecord:
    """Writes the 4 core scientific files into `output_dir` (must already
    exist and be writable -- this function never creates or removes
    directories), then any T2.4B2 `extra_artifacts` (filename -> exact
    bytes to write verbatim, already rendered by csv_export.py/svg_export.py/
    recommendation.py), THEN computes and writes manifest.json LAST --
    always after every applicable artifact already exists on disk.
    Returns the ManifestRecord that was also written to manifest.json.

    Raises -- before writing anything, including the 4 core files --
    ValueError if `extra_artifacts` contains any filename outside the
    three known presentation filenames (path traversal, a hidden file, or
    a collision with a core/manifest filename), or TypeError if any of
    its values is not `bytes`."""
    extra_artifacts = extra_artifacts or {}
    _validate_extra_artifacts(extra_artifacts)

    hash_records: dict[str, ArtifactHashRecord] = {}

    pydoublet_input_bytes = canonical_raw_result_json_bytes(pydoublet_raw_result)
    (output_dir / PYDOUBLET_INPUT_FILENAME).write_bytes(pydoublet_input_bytes)
    hash_records[PYDOUBLET_INPUT_FILENAME] = _hash_record_for_json_bytes(pydoublet_input_bytes)

    config_snapshot_bytes = canonical_raw_result_json_bytes(config)
    (output_dir / CONFIG_SNAPSHOT_FILENAME).write_bytes(config_snapshot_bytes)
    hash_records[CONFIG_SNAPSHOT_FILENAME] = _hash_record_for_json_bytes(config_snapshot_bytes)

    workflow_result_bytes = result.model_dump_json(indent=2).encode("utf-8")
    (output_dir / WORKFLOW_RESULT_FILENAME).write_bytes(workflow_result_bytes)
    hash_records[WORKFLOW_RESULT_FILENAME] = _hash_record_for_json_bytes(workflow_result_bytes)

    audit_bytes = result.audit.model_dump_json(indent=2).encode("utf-8")
    (output_dir / AUDIT_FILENAME).write_bytes(audit_bytes)
    hash_records[AUDIT_FILENAME] = _hash_record_for_json_bytes(audit_bytes)

    for filename, data in extra_artifacts.items():
        (output_dir / filename).write_bytes(data)
        hash_records[filename] = (
            _hash_record_for_json_bytes(data) if filename in _JSON_FILENAMES else _hash_record_for_plain_bytes(data)
        )

    bundle_scientific_sha256 = canonical_raw_result_sha256(
        {filename: record.scientific_sha256 for filename, record in sorted(hash_records.items())}
    )
    manifest = ManifestRecord(
        run_id=result.run_id,
        created_at=datetime.now(timezone.utc),
        files=hash_records,
        bundle_scientific_sha256=bundle_scientific_sha256,
    )
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest
