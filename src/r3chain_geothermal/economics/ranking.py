"""Feasibility-first candidate ranking (T2.4A, implementation plan §12.3).

Two-stage deterministic rule, exactly as the plan specifies: (1) reject
every candidate that fails a hard technical gate -- already done by T2.3,
never re-derived here; (2) rank the remaining FEASIBLE candidates by
lowest annualised cost. No weighted multi-criteria score anywhere in this
module (plan §12.3: "Avoid a weighted multi-criteria score in version
one. A weighted score can hide a physical failure and introduces
arbitrary weights.") -- an infeasible candidate is never assigned a cost,
a rank, or folded into any combined figure; it is reported separately,
with its exact `CandidateFailureCode`, alongside the feasible ranking.

## Ranking key and tie-breakers (config `economics.tie_breakers`, order preserved)

Primary key: `annualised_cost_total_eur_per_a`, ascending. Doublet and
heat-exchanger CAPEX (and their annuities) are IDENTICAL across every
feasible candidate (same PyDoublet scenario, same coupling result), so
ranking by the absolute annualised cost and ranking by the cost DELTA
against the baseline counterfactual produce the same relative order here
-- absolute is used (simpler, standard LCOH-table presentation).
`RankingResult.shared_capex_statement` states this explicitly on every
result (CLAUDE.md, explicit instruction: "identical doublet CAPEX across
C1-C4 means the ranking evaluates network-connection differences, not
geological/drilling-location differences").

Three tie-breakers, each a concrete numeric key (never left implicit):

1. `lower_dh_pumping_electricity` -> `opex_electricity_dh_pumping_eur_per_a`, ascending.
2. `shorter_connection_length` -> `candidate.surface_connection_length_m`, ascending.
3. `greater_technical_margin` -> the MINIMUM of three gate margins, each
   normalized as a fraction of its own gate's budget (so a bar/m-s/K
   triple becomes comparable), larger is better:

   ```
   pressure_margin_fraction    = (min_pressure_bar_abs - tolerances.min_pressure_bar_abs) / tolerances.min_pressure_bar_abs
   velocity_margin_fraction    = (tolerances.max_pipe_velocity_m_s - max_velocity_m_s) / tolerances.max_pipe_velocity_m_s
   temperature_margin_fraction = (tolerances.max_consumer_supply_drop_k - worst_consumer_supply_drop_k) / tolerances.max_consumer_supply_drop_k
   technical_margin_fraction   = min(pressure_margin_fraction, velocity_margin_fraction, temperature_margin_fraction)
   ```

   Rewards the candidate whose TIGHTEST gate still has the most relative
   headroom, not one with a large margin on an already-loose gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ..network.baseline import BaselineNetworkResult, GateTolerances
from ..network.candidate import (
    CandidateEvaluationBoundaryResult,
    CandidateEvaluationFailure,
    CandidateEvaluationResult,
    CandidateFailureCode,
)
from .assumptions import EconomicAssumptions
from .costing import BaselineEconomicResult, CandidateEconomicResult, compute_baseline_economics, compute_candidate_economics

RANKING_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

SHARED_CAPEX_STATEMENT = (
    "Every feasible candidate reuses the identical PyDoublet scenario and coupling "
    "result, so doublet and heat-exchanger CAPEX (and their annuities) are numerically "
    "identical across every candidate evaluated in this run (predefined or generated) "
    "and do not drive this ranking. This ranking evaluates network-CONNECTION-location "
    "differences (connection length, DH pumping, technical margin) only -- it is not, "
    "and must never be read as, a geological or drilling-location recommendation."
)


def _compute_technical_margins(
    candidate_result: CandidateEvaluationResult, tolerances: GateTolerances,
) -> tuple[float, float, float, float]:
    """Returns (pressure_fraction, velocity_fraction, temperature_fraction, min_of_three)."""
    pressure_fraction = (
        (candidate_result.min_pressure_bar_abs - tolerances.min_pressure_bar_abs) / tolerances.min_pressure_bar_abs
    )
    velocity_fraction = (
        (tolerances.max_pipe_velocity_m_s - candidate_result.max_velocity_m_s) / tolerances.max_pipe_velocity_m_s
    )
    worst_supply_drop_k = max(c.supply_temperature_drop_k for c in candidate_result.consumers.values())
    temperature_fraction = (
        (tolerances.max_consumer_supply_drop_k - worst_supply_drop_k) / tolerances.max_consumer_supply_drop_k
    )
    return pressure_fraction, velocity_fraction, temperature_fraction, min(
        pressure_fraction, velocity_fraction, temperature_fraction,
    )


class CandidateRankingEntry(BaseModel):
    """One feasible candidate's position in the ranking, with its full
    economic breakdown and the tie-break keys that placed it there."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    rank: int
    """1-based; contiguous; the ranking's own sort order."""
    candidate_id: str
    economics: CandidateEconomicResult

    pressure_margin_fraction: float
    velocity_margin_fraction: float
    temperature_margin_fraction: float
    technical_margin_fraction: float
    """min() of the three fractions above -- tie-break 3's key."""

    @model_validator(mode="after")
    def _validate_margin_consistency(self) -> "CandidateRankingEntry":
        expected_min = min(self.pressure_margin_fraction, self.velocity_margin_fraction, self.temperature_margin_fraction)
        if self.technical_margin_fraction != expected_min:
            raise ValueError("technical_margin_fraction does not equal the minimum of the three margin fractions")
        if self.rank < 1:
            raise ValueError(f"rank must be >= 1, got {self.rank!r}")
        if self.candidate_id != self.economics.candidate_id:
            raise ValueError("candidate_id does not match economics.candidate_id")
        return self


class InfeasibleCandidateEntry(BaseModel):
    """One infeasible candidate, reported with its exact failure code --
    NEVER assigned a cost, a rank, or folded into the feasible ranking."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    candidate_id: str
    failure_code: CandidateFailureCode
    message: str


class RankingResult(BaseModel):
    """The full feasibility-first ranking output. Model-level invariants
    check rank contiguity/ordering and that no candidate_id appears in
    both `ranked` and `infeasible`."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: Literal["1.0.0"] = RANKING_CONTRACT_SCHEMA_VERSION
    ranked: list[CandidateRankingEntry]
    infeasible: list[InfeasibleCandidateEntry]
    baseline_economics: BaselineEconomicResult
    shared_capex_statement: Literal[SHARED_CAPEX_STATEMENT] = SHARED_CAPEX_STATEMENT
    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "RankingResult":
        errors: list[str] = []

        ranked_ids = [entry.candidate_id for entry in self.ranked]
        if len(set(ranked_ids)) != len(ranked_ids):
            errors.append("ranked contains a duplicate candidate_id")
        infeasible_ids = [entry.candidate_id for entry in self.infeasible]
        if len(set(infeasible_ids)) != len(infeasible_ids):
            errors.append("infeasible contains a duplicate candidate_id")
        if set(ranked_ids) & set(infeasible_ids):
            errors.append("a candidate_id appears in both ranked and infeasible")

        expected_ranks = list(range(1, len(self.ranked) + 1))
        actual_ranks = [entry.rank for entry in self.ranked]
        if actual_ranks != expected_ranks:
            errors.append("ranked entries' rank fields are not contiguous 1..N in list order")

        costs = [entry.economics.annualised_cost_total_eur_per_a for entry in self.ranked]
        if costs != sorted(costs):
            errors.append("ranked is not sorted by ascending annualised_cost_total_eur_per_a")

        if errors:
            raise ValueError("; ".join(errors))
        return self


def rank_candidates(
    results: dict[str, CandidateEvaluationBoundaryResult], baseline: BaselineNetworkResult,
    *, economic_assumptions: EconomicAssumptions, tolerances: GateTolerances,
) -> RankingResult:
    """Feasibility-first: partitions `results` into feasible/infeasible
    FIRST (by type, not by inspecting any numeric field), computes
    economics only for the feasible set, then sorts by the module
    docstring's key/tie-breakers. Never raises; `results` may be empty or
    entirely infeasible (an empty `ranked` list is a valid outcome)."""
    created_at = datetime.now(timezone.utc)
    baseline_economics = compute_baseline_economics(baseline, assumptions=economic_assumptions)

    feasible: dict[str, CandidateEvaluationResult] = {}
    infeasible: list[InfeasibleCandidateEntry] = []
    for candidate_id, result in results.items():
        if isinstance(result, CandidateEvaluationResult):
            feasible[candidate_id] = result
        elif isinstance(result, CandidateEvaluationFailure):
            infeasible.append(InfeasibleCandidateEntry(
                candidate_id=candidate_id, failure_code=result.failure_code, message=result.message,
            ))
        else:
            raise TypeError(f"unexpected result type for {candidate_id!r}: {type(result)!r}")
    infeasible.sort(key=lambda entry: entry.candidate_id)

    unranked_entries: list[tuple[Any, ...]] = []
    for candidate_id in sorted(feasible):
        candidate_result = feasible[candidate_id]
        economics = compute_candidate_economics(
            candidate_result, baseline_economics, assumptions=economic_assumptions,
        )
        pressure_f, velocity_f, temperature_f, technical_margin = _compute_technical_margins(
            candidate_result, tolerances,
        )
        sort_key = (
            economics.annualised_cost_total_eur_per_a,
            economics.opex_electricity_dh_pumping_eur_per_a,
            candidate_result.candidate.surface_connection_length_m,
            -technical_margin,
        )
        unranked_entries.append((sort_key, candidate_id, economics, pressure_f, velocity_f, temperature_f, technical_margin))

    unranked_entries.sort(key=lambda item: item[0])

    ranked: list[CandidateRankingEntry] = []
    for rank, (_, candidate_id, economics, pressure_f, velocity_f, temperature_f, technical_margin) in enumerate(
        unranked_entries, start=1,
    ):
        ranked.append(CandidateRankingEntry(
            rank=rank, candidate_id=candidate_id, economics=economics,
            pressure_margin_fraction=pressure_f, velocity_margin_fraction=velocity_f,
            temperature_margin_fraction=temperature_f, technical_margin_fraction=technical_margin,
        ))

    return RankingResult(
        ranked=ranked, infeasible=infeasible, baseline_economics=baseline_economics, created_at=created_at,
    )
