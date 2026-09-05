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

**Honesty boundary, corrected by real evidence (docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 7/9, REPRO-001..005, docs/issues/cross-platform-reproducibility.md):**
this constant is a principled, documented, testable mechanism for the
diagnosed class of noise, verified directly by
tests/test_hashing.py::test_a_one_ulp_scale_float_difference_produces_the_same_hash
and test_a_genuinely_different_value_still_changes_the_hash -- but it is
NOT sufficient to make `bundle_scientific_sha256` byte-identical across
every CPU architecture, and this module's own PRIOR version of this note
was wrong to suggest otherwise. What actually happened: Phase 7 verified
this project's canonical golden run inside genuine Linux/arm64 containers
(Python 3.11 and 3.12, OpenBLAS, glibc) via Docker and found the IDENTICAL
`bundle_scientific_sha256`
(`ee76b2a626f57fd4825c554ac55e57e81e567f86c7bf4acd771cb23a4389f3c8`) this
project's macOS ARM64 (Apple Accelerate) environment already asserts --
genuine evidence, but only for ARM64-vs-ARM64. A real `ubuntu-latest`
GitHub Actions CI run (genuine x86_64 hardware, Python 3.11 AND 3.12, both
reproducing the SAME divergent value) subsequently showed a DIFFERENT
`bundle_scientific_sha256`
(`6e528746c56f2a1ceda9509b2f5ba2d65f1d45c7961caa69a09fa5577b6a9e25`) for
the identical canonical run -- while `run_id` (a pure hash of INPUT bytes,
never touched by solver output) and every KPI/ranking value stayed
identical on every platform tested. This means x86_64's own numerical
noise for this project's linear solves exceeds the 12th significant
figure this constant quantizes to -- a genuinely different, real finding,
not assumed. **This module's own scientific-fingerprint mechanism is
therefore NOT the tool this project now relies on for cross-platform CI
comparison**: per this specification's own §18 three-tier model (byte
hash / scientific fingerprint / scientific equivalence), the tests that
used to assert an exact cross-platform `bundle_scientific_sha256` literal
now assert "scientific equivalence" instead (`run_id` plus KPI/ranking
values within their own already-declared tolerances) -- see
tests/mcp_server/test_input_provenance_mcp.py's own note for the affected
tests. `bundle_scientific_sha256` remains exactly as useful as before for
its ORIGINAL, still-valid purpose: detecting a scientific regression
BETWEEN two runs on the SAME machine/BLAS backend (e.g. restart-recovery,
"run twice" determinism checks) -- this finding only narrows the
cross-architecture claim, it does not weaken same-platform reproducibility
in any way. Widening `SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES` further
was deliberately NOT attempted as a fix here: doing so without a genuine
per-field diff of the actual divergent value (REPRO-002, which would
require iterative authorized-push CI access this session did not have)
would be exactly the "guess a new number" REPRO-003 warns against."""


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
