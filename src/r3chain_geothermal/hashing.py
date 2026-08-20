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
