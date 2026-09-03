"""Canonical-content hashing for raw PyDoublet results.

Deliberately dependency-free (stdlib only) so both `contracts` (model-level
hash-consistency validation) and `parsers` (parse-time hashing) can import it
without creating a circular import between those two packages.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICAL_RAW_HASH_ALGORITHM_VERSION = "1.0.0"
"""Versioned independently of SCIENTIFIC_NORMALIZATION_RULE_VERSION below --
this identifies canonical_raw_result_sha256()'s own encoding rule (sorted
keys, no insignificant whitespace, UTF-8, non-finite numbers rejected). A
future change to THIS encoding (e.g. adopting RFC 8785 numeric
canonicalization) must bump this version, so any caller recording it
(docs/issues/mcp-input-provenance-enforcement.md, IP-004) can tell which
canonicalization rule an expected_raw_sha256 pin was computed under."""


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


SCIENTIFIC_NORMALIZATION_RULE_VERSION = "1.1.0"
"""Versioned independently of every contract schema (T2.4B2) -- a future
change to WHICH fields get normalized away, or HOW numeric values are
quantized, before scientific hashing must bump this, never silently
change scientific_sha256's meaning under an unchanged version number.

Bumped 1.0.0 -> 1.1.0 (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md
Phase 2, a documented release-blocker investigation): added
SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES quantization -- see that
constant's own docstring for the full diagnosis and justification. This
is an ADDITIVE change to the normalization rule (created_at removal is
unchanged); it only ever makes two representations of the SAME physical
value hash identically where they previously did not -- it never makes
two DIFFERENT physical values collide (12 significant figures is far
finer than any gate tolerance this project enforces, the loosest being
2%, i.e. ~2 significant figures)."""

SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES = 12
"""Phase 2 (release-blocker) diagnosis: a genuinely clean macOS ARM64
Python 3.11.16 / pandapipes 0.14.0 run and an independently-reported
clean Linux run of the SAME canonical workflow produced the SAME
`run_id`, the SAME feasibility/ranking, and the SAME KPI values when
compared at the precision actually reported (4 decimal places on
LCOH/EUR figures) -- but two DIFFERENT `bundle_scientific_sha256`
values. Root cause (this codebase, not re-guessed): prior to this
version, `normalize_for_scientific_hash()` removed only `created_at` and
otherwise passed every float through completely untouched into
`json.dumps()`'s shortest-round-trip representation. pandapipes' own
sequential thermo-hydraulic solve depends on a sparse linear solve
(scipy/SuiteSparse), whose exact floating-point result CAN legitimately
differ from a DIFFERENT BLAS/LAPACK backend (e.g. Apple Accelerate on
macOS vs. OpenBLAS on Linux) by roughly the last few bits of a
double's ~15-17 significant decimal digits, even though both are
numerically "the same" converged physical solution to well within every
gate tolerance this project enforces. That single-ULP-scale difference
in one intermediate quantity, propagated through JSON's exact-repr
float formatting, is sufficient to change every downstream byte and
therefore the whole bundle hash -- without changing any scientifically
meaningful result at all.

12 significant figures is the chosen quantization: comfortably finer
than every numeric gate tolerance in this project (mass balance 0.5%,
energy balance 2%, PyDoublet energy consistency 1-2%; i.e. 2-3
significant figures at the loosest), so it can NEVER mask a genuinely
different scientific/economic/ranking result -- and comfortably coarser
than typical cross-platform BLAS/LAPACK noise for a well-conditioned
linear solve (commonly below the 13th-15th significant digit), so it
correctly makes the SAME physical solution, computed on two different
platforms, hash identically.

**Honesty boundary (Phase 2.3's own required fallback, since only one
platform -- macOS ARM64 -- was available to test this change against):**
this constant is a principled, documented, testable mechanism for the
diagnosed class of noise, verified directly by
tests/test_hashing.py::test_a_one_ulp_scale_float_difference_produces_the_same_hash
and test_a_genuinely_different_value_still_changes_the_hash. It is NOT,
and must not be read as, an empirically-reproduced guarantee that THIS
specific macOS/Linux hash pair now converges -- that would require
actually re-running the workflow on a Linux machine, which this session
could not do. The supported reproducibility boundary is: identical
`bundle_scientific_sha256` is expected across platforms/BLAS backends
whose numerical noise for this project's own linear solves stays below
the 12th significant figure; a platform whose noise exceeds that (e.g. a
genuinely different solver algorithm, not just a different BLAS) is
outside this boundary and would need its own investigation, not a
silent widening of this constant."""


def _quantize_float_for_scientific_hash(value: float) -> float:
    """Rounds `value` to SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES
    significant figures via Python's own `%g` formatting (handles 0.0,
    negative numbers, and very large/small magnitudes correctly without a
    separate log10/edge-case branch) and re-parses it back to a float.
    NaN/Infinity are never produced by this project's own JSON-serializable
    results (canonical_raw_result_json_bytes already rejects them
    upstream), so no special-casing for them is needed here."""
    return float(f"{value:.{SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES}g}")


def normalize_for_scientific_hash(obj: Any) -> Any:
    """Recursively (1) removes every key literally named `created_at`,
    wherever it appears in a nested dict/list, and (2) quantizes every
    float to SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES significant figures
    -- version SCIENTIFIC_NORMALIZATION_RULE_VERSION of this rule (T2.4B2,
    extended in Phase 2 of R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md).

    created_at removal is deliberately narrow: matches the EXACT string
    "created_at" only. Every other timestamp-shaped field in this
    project's own contracts is named differently on purpose and is NEVER
    touched by this function: PyDoublet's own raw `/metadata/timestamp`
    (a raw-result JSON Pointer target, key "timestamp" not "created_at"),
    `PyDoubletCouplingResult.source_timestamp`, and every field on
    `SourceProvenance` (source commit/format hint/calculation mode/
    scenario identifier) all survive normalization completely unchanged
    -- they are genuine scientific/provenance content, not run-metadata
    noise, and must always participate in the scientific hash. Warnings,
    assumptions, and every numeric/typed result field are likewise left
    structurally untouched; only the literal key "created_at" is ever
    removed, at any nesting depth, and only `float` VALUES (never `int`,
    which is always numerically exact -- and never `bool`, which is not
    quantized despite being an `int` subclass in Python) are ever
    quantized.

    Args:
        obj: any JSON-native value (dict, list, or scalar) -- typically
            the result of `json.loads()` on one of this project's own
            `model_dump_json()` outputs.

    Returns:
        A new, structurally-identical value with every "created_at" key
        removed from every dict at every depth, and every float quantized
        per SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES. Does not mutate `obj`.
    """
    if isinstance(obj, dict):
        return {key: normalize_for_scientific_hash(value) for key, value in obj.items() if key != "created_at"}
    if isinstance(obj, list):
        return [normalize_for_scientific_hash(item) for item in obj]
    if isinstance(obj, float):
        return _quantize_float_for_scientific_hash(obj)
    return obj
