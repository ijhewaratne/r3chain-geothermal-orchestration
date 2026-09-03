"""Typed failure codes for the PyDoublet coupling boundary.

Every code here corresponds to a distinct, deliberate rejection reason the
parser can return -- see parsers/pydoublet_parser.py for where each is
raised. String-valued (not IntEnum), matching this project's established
stable-string failure/warning-code convention (pandapipesAI's
core/contract.py, ADR-002's LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK).
"""
from __future__ import annotations

from enum import Enum


class FailureCode(str, Enum):
    """Stable, machine-readable failure codes for a failed coupling parse."""

    PYDOUBLET_NON_CONVERGENCE = "PYDOUBLET_NON_CONVERGENCE"
    PYDOUBLET_RESULT_VALIDATION_FAILED = "PYDOUBLET_RESULT_VALIDATION_FAILED"
    PYDOUBLET_MISSING_REQUIRED_FIELD = "PYDOUBLET_MISSING_REQUIRED_FIELD"
    PYDOUBLET_INVALID_NUMERIC_VALUE = "PYDOUBLET_INVALID_NUMERIC_VALUE"
    PYDOUBLET_NAMED_LEGACY_TEMPERATURE_MISMATCH = "PYDOUBLET_NAMED_LEGACY_TEMPERATURE_MISMATCH"
    PYDOUBLET_UNRECOGNIZED_LEGACY_SCHEMA = "PYDOUBLET_UNRECOGNIZED_LEGACY_SCHEMA"
    PYDOUBLET_LEGACY_RUN_COUNT_AMBIGUOUS = "PYDOUBLET_LEGACY_RUN_COUNT_AMBIGUOUS"
    """Added beyond the original six T1.5 failure codes at the user's
    explicit instruction (T1.5B correction round): trusted legacy/pristine
    provenance was confirmed, but the reported actual_runs_completed does not
    match the known single-deterministic-run defect signature
    (actual_runs_completed == monte_carlo_runs). Applying the
    legacy_deterministic_run_count_metadata_correction in that situation
    would be guessing at calculation mode rather than confirming it, so the
    parser fails clearly instead."""
    PYDOUBLET_UNSUPPORTED_CALCULATION_MODE = "PYDOUBLET_UNSUPPORTED_CALCULATION_MODE"
    """T1.5 supports only deterministic PyDoublet coupling results.
    source_provenance.calculation_mode was not explicitly "deterministic"
    (i.e. it was "monte_carlo" or "unknown") -- a source commit or known
    format hint alone must never imply deterministic mode."""
    PYDOUBLET_RAW_HASH_MISMATCH = "PYDOUBLET_RAW_HASH_MISMATCH"
    """docs/issues/mcp-input-provenance-enforcement.md (IP-003). Raised
    before any scientific parsing when source_provenance.expected_raw_sha256
    is supplied and does not equal canonical_raw_result_sha256(raw_result)
    as independently computed by the server -- never trusting a
    client-supplied "actual" hash. Prevents a valid but unintended,
    truncated, retyped, or previously-preserved raw result from being
    accepted as if it were the specific file the caller meant to send."""


LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK = "LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK"
"""Warning code for a successful parse that used the legacy temperature
fallback (ADR-002) -- distinct from FailureCode, since this is attached to a
*successful* PyDoubletCouplingResult.warnings entry, not a failure."""

LEGACY_PYDOUBLET_RUN_COUNT_METADATA_CORRECTED = "LEGACY_PYDOUBLET_RUN_COUNT_METADATA_CORRECTED"
"""Warning code for a successful parse where the known legacy
actual_runs_completed defect (copy-pasted from monte_carlo_runs despite only
one deterministic run executing) was detected and corrected to 1. Only
emitted alongside the legacy_deterministic_run_count_metadata_correction
transformation -- see parsers/pydoublet_parser.py."""
