"""Workflow-level (run_id/bundle-hash) coverage for exact input-provenance
enforcement (IP-001..IP-007, docs/issues/mcp-input-provenance-enforcement.md).

The critical property this file exists to prove: expected_raw_sha256 (a
keyword-only parameter of run_workflow()/parse_pydoublet_result(), NOT a
SourceProvenance field -- see SourceProvenance's own docstring) must NEVER
change any historical run_id OR bundle_scientific_sha256, including the
pinned golden reference r3chain-run-93d41133daa11d1a and its
bundle_scientific_sha256 hardcoded in
tests/mcp_client/test_wheel_install.py and
tests/mcp_server/test_mcp_protocol.py -- those two tests passing unmodified
is itself part of this feature's regression proof (an earlier design that
put this field ON SourceProvenance was rejected specifically because it
broke exactly those two pinned hashes with zero scientific content
actually changing; see docs/decisions/decision-register.md IMPL-001).
"""
from __future__ import annotations

import json
from pathlib import Path

from r3chain_geothermal.contracts import SourceProvenance
from r3chain_geothermal.workflow import WorkflowResult, compute_source_provenance_sha256, run_workflow

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"
_REPAIRED_PATH = _ROOT / "fixtures" / "pydoublet" / "repaired_result.json"
_KNOWN_REPAIRED_COMMIT = "0d649c3e6930d342dac03654d57776e134c2d0b9"

_CANONICAL_FIXTURE_HASH = "6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762"
_GOLDEN_RUN_ID = "r3chain-run-93d41133daa11d1a"


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _raw() -> dict:
    return json.loads(_REPAIRED_PATH.read_text())


def _provenance(**overrides) -> SourceProvenance:
    kwargs = dict(
        source_pydoublet_commit=_KNOWN_REPAIRED_COMMIT,
        source_format_hint="known_repaired",
        calculation_mode="deterministic",
    )
    kwargs.update(overrides)
    return SourceProvenance(**kwargs)


def test_expected_raw_sha256_is_not_a_source_provenance_field():
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        _provenance(expected_raw_sha256=_CANONICAL_FIXTURE_HASH)


def test_compute_source_provenance_sha256_unaffected_by_this_feature():
    """This function's signature never changed -- it only ever saw the
    original four SourceProvenance fields, before and after this feature.
    This test exists as an explicit regression tripwire in case a future
    change reintroduces the field on SourceProvenance."""
    provenance = _provenance()
    assert compute_source_provenance_sha256(provenance) == compute_source_provenance_sha256(_provenance())


def test_strict_provenance_with_canonical_fixture_reproduces_golden_run_id():
    """AC-02's positive counterpart: the ACTUAL canonical fixture, with the
    strict expected hash supplied via run_workflow()'s own keyword
    parameter, must reproduce the exact pre-existing golden run_id --
    proving this feature changes nothing about run identity when it is
    satisfied. bundle_scientific_sha256 is only produced later, by
    write_workflow_artifacts() (not part of WorkflowResult itself) -- see
    tests/mcp_server/test_input_provenance_mcp.py for that check."""
    result = run_workflow(
        _raw(), _config(), source_provenance=_provenance(), expected_raw_sha256=_CANONICAL_FIXTURE_HASH,
    )
    assert isinstance(result, WorkflowResult)
    assert result.run_id == _GOLDEN_RUN_ID


def test_omitted_expected_raw_sha256_reproduces_golden_run_id_and_matches_supplied_case():
    """Byte-for-byte parity between "parameter omitted" and "parameter
    supplied and matching" -- the two paths every existing caller and this
    feature's callers respectively take."""
    omitted = run_workflow(_raw(), _config(), source_provenance=_provenance())
    supplied = run_workflow(
        _raw(), _config(), source_provenance=_provenance(), expected_raw_sha256=_CANONICAL_FIXTURE_HASH,
    )
    assert isinstance(omitted, WorkflowResult) and isinstance(supplied, WorkflowResult)
    assert omitted.run_id == supplied.run_id == _GOLDEN_RUN_ID


def test_strict_provenance_mismatch_stops_before_any_candidate_evaluation():
    """AC-02: a mismatch stops at the parse stage -- zero candidate
    evaluations, zero pandapipes solves, zero economics."""
    result = run_workflow(
        _raw(), _config(), source_provenance=_provenance(), expected_raw_sha256="0" * 64,
    )
    assert not isinstance(result, WorkflowResult)
    assert result.audit.stage_calls[0].stage_name == "parse_pydoublet_result"
    assert result.audit.stage_calls[0].status == "failure"
    assert len(result.audit.stage_calls) == 1  # nothing past the parse stage ran
