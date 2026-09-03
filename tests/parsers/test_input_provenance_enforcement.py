"""Exact input-provenance enforcement (IP-001..IP-007,
docs/issues/mcp-input-provenance-enforcement.md).

Covers the parser/contracts layer (shared by the CLI and every MCP tool).
`expected_raw_sha256` is a keyword-only parameter of parse_pydoublet_result()
itself, NOT a field on SourceProvenance -- see SourceProvenance's own
docstring for why (it would silently change source_provenance_sha256/
bundle_scientific_sha256 for every existing caller, confirmed by measuring
it before settling on this design; see docs/decisions/decision-register.md
IMPL-001). See tests/mcp_server/test_input_provenance_mcp.py for the
MCP-boundary-specific behavior (no artifact directory on mismatch, CLI/MCP
equivalence) and tests/workflow/test_input_provenance_run_id.py for the
run_id/bundle-hash backward-compatibility proof.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from r3chain_geothermal.contracts import PyDoubletCouplingFailure, PyDoubletCouplingResult, SourceProvenance
from r3chain_geothermal.errors import FailureCode
from r3chain_geothermal.hashing import canonical_raw_result_sha256
from r3chain_geothermal.parsers.pydoublet_parser import parse_pydoublet_result

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPAIRED_PATH = _REPO_ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

# The pinned canonical hash of fixtures/pydoublet/repaired_result.json,
# independently reproduced and cross-checked against
# CODEX_REPOSITORY_ASSESSMENT.md and this project's own T5.1C evidence
# (docs/evidence/t5.1c/*/hash-diagnosis.md) multiple times this project.
_CANONICAL_FIXTURE_HASH = "6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762"

# Two independently-drifted, previously-preserved T5.1C evidence artifacts --
# each scientifically equivalent to the canonical fixture but NOT byte- or
# hash-identical to it (see their own docs/evidence/.../hash-diagnosis.md
# for the full pointer-level diagnosis). Used below as the "hand-transcribed
# Run 1/Run 2 input" IP-006 test case -- real artifacts, not synthesized.
_DRIFTED_INPUT_PATHS = [
    _REPO_ROOT / "docs/evidence/t5.1c/2026-08-31-preliminary-code-run/bundle/pydoublet_input.json",
    _REPO_ROOT / "docs/evidence/t5.1c/2026-09-03-desktop-run-1/bundle/pydoublet_input.json",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _provenance(**overrides) -> SourceProvenance:
    kwargs = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    kwargs.update(overrides)
    return SourceProvenance(**kwargs)


# ── SourceProvenance no longer carries this field at all ────────────────────
def test_source_provenance_rejects_expected_raw_sha256_as_a_field():
    """Confirms the deliberate design choice (SourceProvenance's own
    docstring): this is a parse_pydoublet_result()/run_workflow() keyword
    parameter, never a SourceProvenance field -- extra="forbid" must reject
    it if anyone tries to pass it there anyway."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        _provenance(expected_raw_sha256=_CANONICAL_FIXTURE_HASH)


# ── IP-006: correct fixture + correct expected hash succeeds ────────────────
def test_correct_fixture_with_correct_expected_hash_succeeds():
    raw = _load(_REPAIRED_PATH)
    assert canonical_raw_result_sha256(raw) == _CANONICAL_FIXTURE_HASH  # sanity: the pin is right
    result = parse_pydoublet_result(
        raw, source_provenance=_provenance(), expected_raw_sha256=_CANONICAL_FIXTURE_HASH,
    )
    assert isinstance(result, PyDoubletCouplingResult)
    assert result.raw_result_sha256 == _CANONICAL_FIXTURE_HASH


# ── IP-006: correct fixture + wrong expected hash fails ─────────────────────
def test_correct_fixture_with_wrong_expected_hash_fails():
    raw = _load(_REPAIRED_PATH)
    wrong_hash = "0" * 64
    result = parse_pydoublet_result(raw, source_provenance=_provenance(), expected_raw_sha256=wrong_hash)
    assert isinstance(result, PyDoubletCouplingFailure)
    assert result.failure_code == FailureCode.PYDOUBLET_RAW_HASH_MISMATCH
    assert result.details["expected_raw_sha256"] == wrong_hash
    assert result.details["calculated_raw_sha256"] == _CANONICAL_FIXTURE_HASH
    assert wrong_hash in result.message
    assert _CANONICAL_FIXTURE_HASH in result.message
    # IP-006: mismatch must be diagnosable from the two hashes alone,
    # without exposing the entire raw input.
    assert result.raw_result is None
    # raw_result_sha256 IS still populated (the server's own independently
    # computed hash, not the caller's claim) -- useful for audit/diagnosis.
    assert result.raw_result_sha256 == _CANONICAL_FIXTURE_HASH


@pytest.mark.parametrize("drifted_path", _DRIFTED_INPUT_PATHS)
def test_previously_drifted_evidence_input_with_canonical_expected_hash_fails(drifted_path: Path):
    """IP-006: a previously hand-transcribed Run 1/Run 2 input, resubmitted
    with the canonical fixture's expected hash, must fail -- even though
    the drifted content is scientifically equivalent under the current
    parser (already proven exhaustively in this project's own T5.1C
    evidence), it is NOT the byte-identical canonical fixture, and this
    feature's entire point is to catch exactly that distinction."""
    if not drifted_path.exists():
        pytest.skip(f"evidence artifact not present: {drifted_path}")
    raw = _load(drifted_path)
    assert canonical_raw_result_sha256(raw) != _CANONICAL_FIXTURE_HASH  # sanity: genuinely drifted
    result = parse_pydoublet_result(
        raw, source_provenance=_provenance(), expected_raw_sha256=_CANONICAL_FIXTURE_HASH,
    )
    assert isinstance(result, PyDoubletCouplingFailure)
    assert result.failure_code == FailureCode.PYDOUBLET_RAW_HASH_MISMATCH
    assert result.details["expected_raw_sha256"] == _CANONICAL_FIXTURE_HASH


# ── IP-006: malformed/uppercase/shortened/non-hex hash values fail ──────────
@pytest.mark.parametrize(
    "bad_hash",
    [
        "6C42D3368883070CD177ECB02572480D3AAB4238E4781357B78C742CEC642762",  # uppercase
        "6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec6427",  # 63 chars (shortened)
        "6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762a",  # 65 chars
        "6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec6427g",  # 'g' non-hex, 64 chars
        "not-a-hash-at-all",
        "",
    ],
)
def test_malformed_expected_hash_fails_validation(bad_hash: str):
    raw = _load(_REPAIRED_PATH)
    result = parse_pydoublet_result(raw, source_provenance=_provenance(), expected_raw_sha256=bad_hash)
    assert isinstance(result, PyDoubletCouplingFailure)
    assert result.failure_code == FailureCode.PYDOUBLET_RESULT_VALIDATION_FAILED


# ── IP-006: omitted expected hash preserves backward-compatible behavior ────
def test_omitted_expected_hash_is_backward_compatible():
    raw = _load(_REPAIRED_PATH)
    with_param_omitted = parse_pydoublet_result(raw, source_provenance=_provenance())
    with_param_none = parse_pydoublet_result(raw, source_provenance=_provenance(), expected_raw_sha256=None)
    assert isinstance(with_param_omitted, PyDoubletCouplingResult)
    assert isinstance(with_param_none, PyDoubletCouplingResult)
    assert with_param_omitted.raw_result_sha256 == with_param_none.raw_result_sha256 == _CANONICAL_FIXTURE_HASH
    # Byte-identical serialization too (excluding created_at, which
    # genuinely differs between the two separate calls above) -- not just
    # "same hash", the actual model content must be indistinguishable,
    # proving this parameter truly cannot leak into any persisted/audited
    # shape.
    assert with_param_omitted.model_dump(exclude={"created_at"}) == with_param_none.model_dump(exclude={"created_at"})
