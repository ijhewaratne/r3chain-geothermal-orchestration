"""Canonical-content hashing for raw PyDoublet results.

Deliberately dependency-free (stdlib only) so both `contracts` (model-level
hash-consistency validation) and `parsers` (parse-time hashing) can import it
without creating a circular import between those two packages.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_raw_result_json_bytes(raw_result: dict[str, Any]) -> bytes:
    """Strict canonical-JSON encoding of raw_result, as UTF-8 bytes.

    This is a CANONICAL-CONTENT hash input, not necessarily identical to the
    bytes of whatever source file the raw result was originally read from --
    key order and whitespace are normalized, so two structurally-identical
    dicts always produce the same bytes regardless of how they were
    serialized upstream.

    Raises:
        ValueError: raw_result contains NaN or Infinity anywhere (allow_nan=False
            rejects these, since they are not valid JSON per RFC 8259 and
            would otherwise silently produce a non-standard-JSON hash input).
        TypeError: raw_result contains a value that is not a JSON-native type
            (e.g. a pathlib.Path, a set, an arbitrary object) -- json.dumps()
            cannot serialize it. Callers must catch this alongside ValueError;
            see parsers/pydoublet_parser.py's PYDOUBLET_RESULT_VALIDATION_FAILED
            handling for the public-API-facing conversion of this exception.
    """
    text = json.dumps(
        raw_result, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    return text.encode("utf-8")


def canonical_raw_result_sha256(raw_result: dict[str, Any]) -> str:
    """SHA-256 hex digest of canonical_raw_result_json_bytes(raw_result).
    Raises ValueError/TypeError under the same conditions."""
    return hashlib.sha256(canonical_raw_result_json_bytes(raw_result)).hexdigest()


SCIENTIFIC_NORMALIZATION_RULE_VERSION = "1.0.0"
"""Versioned independently of every contract schema (T2.4B2) -- a future
change to WHICH fields get normalized away before scientific hashing must
bump this, never silently change scientific_sha256's meaning under an
unchanged version number."""


def normalize_for_scientific_hash(obj: Any) -> Any:
    """Recursively removes every key literally named `created_at`, wherever
    it appears in a nested dict/list -- version SCIENTIFIC_NORMALIZATION_RULE_VERSION
    of this rule (T2.4B2).

    Deliberately narrow: matches the EXACT string "created_at" only.
    Every other timestamp-shaped field in this project's own contracts is
    named differently on purpose and is NEVER touched by this function:
    PyDoublet's own raw `/metadata/timestamp` (a raw-result JSON Pointer
    target, key "timestamp" not "created_at"), `PyDoubletCouplingResult
    .source_timestamp`, and every field on `SourceProvenance` (source
    commit/format hint/calculation mode/scenario identifier) all survive
    normalization completely unchanged -- they are genuine scientific/
    provenance content, not run-metadata noise, and must always
    participate in the scientific hash. Warnings, assumptions, and every
    numeric/typed result field are likewise left untouched; only the
    literal key "created_at" is ever removed, at any nesting depth.

    Args:
        obj: any JSON-native value (dict, list, or scalar) -- typically
            the result of `json.loads()` on one of this project's own
            `model_dump_json()` outputs.

    Returns:
        A new, structurally-identical value with every "created_at" key
        removed from every dict at every depth. Does not mutate `obj`.
    """
    if isinstance(obj, dict):
        return {key: normalize_for_scientific_hash(value) for key, value in obj.items() if key != "created_at"}
    if isinstance(obj, list):
        return [normalize_for_scientific_hash(item) for item in obj]
    return obj
