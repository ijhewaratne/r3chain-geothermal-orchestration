"""Per-alternative scientific evaluation (S12, EVAL-001..014,
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 2).

## Reuse, not reinvention (EVAL-004, GOV-010, ARCH-002)

This module adds NO new physics. Every alternative's HX boundary is
computed by the SAME `adapter.evaluate_heat_exchanger_coupling()` the
canonical single-scenario workflow and the v1 joint layer both already
use; every alternative's network feasibility is computed by the SAME
`network.candidate.evaluate_candidate()` (a fresh pandapipes network per
alternative, per its own docstring -- EVAL-005: no mutation leakage).
This module's only new logic is: deriving each scenario's own coupling
input from its declared `SyntheticDerivation` (not v1's hidden logic),
resolving a `SiteConnectionRoute`'s geometry-derived length and a
`NetworkAttachment`'s junction ids into a `BlueprintCandidate`, and
recording which of two stages an alternative reached.

## Phase 4 addition: economics only on feasible alternatives (EVAL-009/DEC-010)

`economics.joint_costing.compute_alternative_economics()` is called ONLY
after `ADDED_TO_DECISION_SET` is reached -- never for an infeasible
alternative (S12/EVAL-009: "never calculate economics for an infeasible
alternative"), matching the canonical workflow's and the v1 joint
module's own sequencing exactly."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict

from ..adapter import CouplingAssumptions, evaluate_heat_exchanger_coupling
from ..adapter.heat_exchanger import HeatExchangerCouplingFailure
from ..contracts.coupling_result import PyDoubletCouplingResult
from ..data_contracts.joint_study import (
    AlternativeIdentity,
    ConnectionDesignOption,
    GeothermalResourceScenario,
    JointStudyPackage,
    NetworkAttachment,
    SiteConnectionRoute,
)
from ..data_contracts.joint_study_synthetic_v2 import apply_synthetic_derivation
from ..economics.assumptions import EconomicAssumptions
from ..economics.costing import BaselineEconomicResult, CandidateEconomicResult
from ..economics.joint_costing import compute_alternative_economics
from ..network import (
    BaselineNetworkResult,
    BlueprintCandidate,
    CandidateEvaluationFailure,
    CandidateEvaluationResult,
    GateTolerances,
    GeothermalInjectionPolicy,
    NetworkBlueprint,
    evaluate_candidate,
)


class JointEvaluationStage(str, Enum):
    """Two reachable stages this module can observe -- EVAL-001's own
    provenance/compatibility validation is satisfied upstream by
    construction (only ever called with an already-validated package and
    an already-screened, accepted route)."""

    CALCULATE_HX_COUPLING_BOUNDARY = "CALCULATE_HX_COUPLING_BOUNDARY"
    APPLY_NETWORK_TECHNICAL_GATES = "APPLY_NETWORK_TECHNICAL_GATES"
    ADDED_TO_DECISION_SET = "ADDED_TO_DECISION_SET"


class JointAlternativeEvaluation(BaseModel):
    """One alternative's full evaluation record -- retained whether
    feasible or not (EVAL-010/013: one alternative's expected failure
    never aborts evaluation of the others)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: AlternativeIdentity
    stage_reached: JointEvaluationStage
    feasible: bool
    failure_code: str | None
    message: str
    candidate_result: CandidateEvaluationResult | None = None
    economics: CandidateEconomicResult | None = None
    """Non-null if and only if feasible (EVAL-009/DEC-010)."""
    created_at: datetime


def evaluate_alternative(
    identity: AlternativeIdentity,
    scenario: GeothermalResourceScenario,
    route: SiteConnectionRoute,
    attachment: NetworkAttachment,
    design: ConnectionDesignOption,
    golden: PyDoubletCouplingResult,
    blueprint: NetworkBlueprint,
    baseline: BaselineNetworkResult,
    baseline_economics: BaselineEconomicResult,
    base_assumptions: EconomicAssumptions,
    *,
    coupling_assumptions: CouplingAssumptions,
    injection_policy: GeothermalInjectionPolicy,
    tolerances: GateTolerances,
) -> JointAlternativeEvaluation:
    """EVAL-014: never raises for an expected scientific outcome -- an
    unexpected internal exception is a software error, not caught or
    relabelled here (S12's own FAIL-007)."""
    created_at = datetime.now(timezone.utc)

    coupling_input = apply_synthetic_derivation(golden, scenario.derivation)
    coupling_boundary = evaluate_heat_exchanger_coupling(coupling_input, assumptions=coupling_assumptions)
    if isinstance(coupling_boundary, HeatExchangerCouplingFailure):
        return JointAlternativeEvaluation(
            identity=identity, stage_reached=JointEvaluationStage.CALCULATE_HX_COUPLING_BOUNDARY,
            feasible=False, failure_code=coupling_boundary.failure_code.value, message=coupling_boundary.message,
            created_at=created_at,
        )

    candidate = BlueprintCandidate(
        id=identity.alternative_id, label=f"{identity.surface_site_id} -> {identity.attachment_id}",
        supply_junction=attachment.supply_junction_id, return_junction=attachment.return_junction_id,
        surface_connection_length_m=route.paired_trench_length_m,
    )
    candidate_boundary = evaluate_candidate(
        coupling_boundary, blueprint, candidate, baseline, injection_policy=injection_policy, tolerances=tolerances,
        connection_pipe_inner_diameter_mm=design.connection_pipe_inner_diameter_mm,
    )
    if isinstance(candidate_boundary, CandidateEvaluationFailure):
        return JointAlternativeEvaluation(
            identity=identity, stage_reached=JointEvaluationStage.APPLY_NETWORK_TECHNICAL_GATES,
            feasible=False, failure_code=candidate_boundary.failure_code.value, message=candidate_boundary.message,
            created_at=created_at,
        )

    economics = compute_alternative_economics(candidate_boundary, scenario, design, baseline_economics, base_assumptions)

    return JointAlternativeEvaluation(
        identity=identity, stage_reached=JointEvaluationStage.ADDED_TO_DECISION_SET,
        feasible=True, failure_code=None, message="feasible", candidate_result=candidate_boundary,
        economics=economics, created_at=created_at,
    )


def evaluate_compatible_alternatives(
    identities: list[AlternativeIdentity],
    package: JointStudyPackage,
    routes_by_id: dict[str, SiteConnectionRoute],
    attachments_by_id: dict[str, NetworkAttachment],
    golden: PyDoubletCouplingResult,
    blueprint: NetworkBlueprint,
    baseline: BaselineNetworkResult,
    baseline_economics: BaselineEconomicResult,
    base_assumptions: EconomicAssumptions,
    *,
    coupling_assumptions: CouplingAssumptions,
    injection_policy: GeothermalInjectionPolicy,
    tolerances: GateTolerances,
) -> list[JointAlternativeEvaluation]:
    scenarios_by_key = {(s.scenario_id, s.site_id): s for s in package.resource_scenarios}
    designs_by_id = {d.design_option_id: d for d in package.design_options}
    results: list[JointAlternativeEvaluation] = []
    for identity in identities:
        scenario = scenarios_by_key[(identity.resource_scenario_id, identity.surface_site_id)]
        route = routes_by_id[identity.route_id]
        attachment = attachments_by_id[identity.attachment_id]
        design = designs_by_id[identity.design_option_id]
        results.append(evaluate_alternative(
            identity, scenario, route, attachment, design, golden, blueprint, baseline,
            baseline_economics, base_assumptions,
            coupling_assumptions=coupling_assumptions, injection_policy=injection_policy, tolerances=tolerances,
        ))
    return results
