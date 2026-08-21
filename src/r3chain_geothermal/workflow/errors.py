"""Typed failure codes for the T2.4B1 deterministic workflow orchestrator.

Four STOPPING failures only -- a candidate's own failure (T2.3's
CandidateFailureCode) is never one of these, since per-candidate outcomes
never stop the workflow (see core.py's module docstring)."""
from __future__ import annotations

from enum import Enum


class WorkflowFailureCode(str, Enum):
    """Stable, machine-readable failure codes for a workflow run that
    stopped before reaching candidate ranking."""

    PYDOUBLET_PARSE_FAILED = "PYDOUBLET_PARSE_FAILED"
    """parse_pydoublet_result returned PyDoubletCouplingFailure. The
    upstream PyDoubletFailureCode is preserved verbatim in
    WorkflowFailure.details, never re-derived or paraphrased."""

    HEAT_EXCHANGER_COUPLING_FAILED = "HEAT_EXCHANGER_COUPLING_FAILED"
    """evaluate_heat_exchanger_coupling returned HeatExchangerCouplingFailure.
    The upstream AdapterFailureCode is preserved verbatim in
    WorkflowFailure.details."""

    BLUEPRINT_CONSTRUCTION_FAILED = "BLUEPRINT_CONSTRUCTION_FAILED"
    """build_default_blueprint raised ValueError (most commonly a
    consumer_demands_kw key mismatch against config -- a config-authoring
    bug, never influenced by PyDoublet's own runtime data). The exception
    message is preserved verbatim in WorkflowFailure.details."""

    BASELINE_EVALUATION_FAILED = "BASELINE_EVALUATION_FAILED"
    """run_baseline_evaluation returned BaselineNetworkFailure. The
    upstream BaselineFailureCode is preserved verbatim in
    WorkflowFailure.details."""
