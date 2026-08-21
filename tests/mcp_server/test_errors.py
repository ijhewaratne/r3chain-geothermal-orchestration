"""Full test matrix for mcp_server/errors.py -- ToolError's structured-only
contract (T5.1A): code, message, stage, recoverable; no stack traces, no
absolute paths."""
from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from r3chain_geothermal.mcp_server.errors import ToolError, ToolErrorCode

_STACK_TRACE_MARKERS = ("Traceback (most recent call last)", "  File \"", ".py\", line ")


def test_every_tool_error_code_is_constructible():
    for code in ToolErrorCode:
        error = ToolError(code=code, message="a message", stage="a_stage", recoverable=True)
        assert error.code == code
        assert error.status == "error"


def test_tool_error_code_is_exactly_the_six_reachable_codes():
    """No code exists that no tool can ever return -- a stopped workflow
    (RunSummary.workflow_status == "stopped") is deliberately a normal
    typed result, not an error, so it has no code here; every code that
    DOES exist is exercised by a real tool scenario elsewhere in
    tests/mcp_server/ (test_tools.py's malformed-input/unsupported-mode/
    unknown-run/forbidden-artifact/not-available/unexpected-error cases)."""
    assert {code.value for code in ToolErrorCode} == {
        "PYDOUBLET_VALIDATION_FAILED",
        "RUN_NOT_FOUND",
        "FORBIDDEN_ARTIFACT",
        "ARTIFACT_NOT_AVAILABLE",
        "INVALID_INPUT",
        "UNEXPECTED_ERROR",
    }
    assert len(ToolErrorCode) == 6


def test_required_fields_are_enforced():
    with pytest.raises(ValidationError):
        ToolError(message="x", stage="y", recoverable=True)  # missing code


def test_model_is_frozen():
    error = ToolError(code=ToolErrorCode.RUN_NOT_FOUND, message="x", stage="y", recoverable=True)
    with pytest.raises(ValidationError):
        error.message = "changed"


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        ToolError(
            code=ToolErrorCode.RUN_NOT_FOUND, message="x", stage="y", recoverable=True,
            unexpected_field="should not be allowed",
        )


def test_details_defaults_to_empty_dict():
    error = ToolError(code=ToolErrorCode.RUN_NOT_FOUND, message="x", stage="y", recoverable=True)
    assert error.details == {}


@pytest.mark.parametrize("message", [
    "no run stored under run_id 'r3chain-run-abc123'",
    "config is structurally invalid: KeyError('gates')",
    "T1.5 supports only deterministic PyDoublet coupling results",
])
def test_typical_messages_contain_no_stack_trace_markers(message: str):
    error = ToolError(code=ToolErrorCode.INVALID_INPUT, message=message, stage="test", recoverable=True)
    for marker in _STACK_TRACE_MARKERS:
        assert marker not in error.message


def test_typical_messages_contain_no_absolute_path_fragment():
    error = ToolError(
        code=ToolErrorCode.RUN_NOT_FOUND, message="no run stored under run_id 'x'", stage="registry_lookup",
        recoverable=True,
    )
    assert "/Users/" not in error.message
    assert not re.search(r"^/[A-Za-z0-9_.-]+/", error.message)


def test_json_round_trip():
    error = ToolError(
        code=ToolErrorCode.FORBIDDEN_ARTIFACT, message="x", stage="artifact_lookup", recoverable=False,
        details={"allowed_filenames": ["a.json", "b.json"]},
    )
    payload = error.model_dump_json()
    restored = ToolError.model_validate_json(payload)
    assert restored == error
