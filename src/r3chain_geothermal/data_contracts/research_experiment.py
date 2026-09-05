"""Research-experiment layer contracts (v1.0.0, R3-CHAIN Final Research-Alignment
Implementation Specification, Phase 1).

## Relationship to the corrected v2 joint site/connection layer

This module is a NEW, ADDITIVE layer on top of `data_contracts.joint_study`
(`JointStudyPackage`, `DecisionPolicy`, `ObjectiveDefinition`, ...) -- it does not
replace or mutate that contract. A `ResearchExperimentConfig` REFERENCES an
already-committed `JointStudyPackage` by path and hash; it never redefines sites,
resource scenarios, attachments, routes or design options. The research question this
layer answers is orthogonal to v2's own: does the site/resource that source-side
Pareto analysis prefers remain preferred once its actual district-heating integration,
evaluated at more than one representative load level, is priced in?

## Reuse over reinvention (Phase-0 audit finding, this session)

`decision.joint_policy.decide()` / `pareto_shortlist()` / the materiality-aware
dominance machinery are reused UNCHANGED by later phases -- they operate purely on
`AlternativeObjectiveValues(alternative_id, values: dict[str, float])` +
`data_contracts.joint_study.DecisionPolicy`, which is already fully generic (any
named objective works structurally; only `decision.joint_policy`'s own
`_OBJECTIVE_EXTRACTORS` dict is specific to the v2 candidate-result shape). This
module therefore does NOT define a new decision-policy type: a
`ResearchExperimentConfig` embeds the EXISTING `data_contracts.joint_study.DecisionPolicy`
directly, with `primary_objective` naming the new
`annualized_system_lcoh_eur_per_mwh` objective. Later phases build
`AlternativeObjectiveValues` directly from `AnnualizedAlternativeEconomicResult`
rather than routing through `_OBJECTIVE_EXTRACTORS` (whose extractor signature is
shaped for one candidate/economics pair, not a multi-load-state annualized value).

## What Phase 1 delivers, and what it deliberately does not

Phase 1 implements the TYPED CONTRACTS only: `LoadStateDefinition`,
`ResearchExperimentConfig`, `LoadStatePerformanceResult`,
`AnnualizedAlternativeEconomicResult`, `SensitivityCaseDefinition`/`SensitivityCaseResult`,
`BaselineComparisonResult`/`ComparisonInterpretationCode`, and
`ResearchExperimentDecisionSummary`/`RobustnessClassification`. Each carries the same
recompute-on-validate invariant discipline used throughout this project
(`economics.costing.CandidateEconomicResult`, `network.candidate.CandidateEvaluationResult`):
a hand-tampered payload is rejected, not silently accepted. No enumeration,
per-load-state pandapipes evaluation, annuity/OPEX computation, decision reuse, MCP
wiring, or CLI wiring happens here -- those are Phase 2-6.

`LoadStatePerformanceResult` deliberately carries only plain scalar KPI fields (never
an embedded `network.candidate.CandidateEvaluationResult`/`economics.costing.
CandidateEconomicResult`) so this contracts module stays independently testable,
matching `data_contracts.joint_study`'s own stated ARCH-002 discipline -- it does not
import from `network` or `economics` at all.
"""
from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .joint_study import AssumptionStatus, DecisionPolicy, ObjectiveDefinition

RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""Versioned independently of every other layer's own contract schema (matching
JOINT_STUDY_CONTRACT_SCHEMA_VERSION/CANDIDATE_CONTRACT_SCHEMA_VERSION/
ECONOMICS_CONTRACT_SCHEMA_VERSION's own convention)."""

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_Sha256Hex = Field(pattern=_SHA256_HEX_PATTERN)

_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
"""allow_inf_nan=False on every model in this module structurally forbids
non-finite numeric values for every float field, matching data_contracts.joint_study's
own _MODEL_CONFIG."""


def _is_safe_package_relative_path(path: str) -> bool:
    """Independently reimplemented from data_contracts.joint_study's own
    identically-named private helper (not imported -- this project's established
    convention for a small private helper duplicated across independently-testable
    contract modules, e.g. network/candidate.py's _compute_injected_mass_flow_kg_s
    docstring). Same conservative rule: reject empty, absolute, drive-letter-absolute,
    or traversal paths."""
    if not path:
        return False
    normalized = path.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    if len(normalized) >= 2 and normalized[1] == ":":
        return False
    segments = normalized.split("/")
    return all(segment not in ("", "..") for segment in segments)


# ── Load states (RA-LOAD) ────────────────────────────────────────────────────

class LoadStateDefinition(BaseModel):
    """One representative steady-state load condition -- NOT a transient/hourly
    time series (spec's own explicit scope boundary: "three representative
    steady-state load conditions per integrated alternative"). `demand_scale_fraction`
    scales the v2 study package's own baseline consumer demand (network.blueprint's
    design demand is treated as the peak/1.0 reference); `annual_duration_hours` is
    this state's own share of the annualization horizon it represents (see
    `AnnualizationPolicy.horizon_hours_per_year` below -- the sum of every declared
    load state's own `annual_duration_hours` must equal that horizon exactly).

    v1.0 schema note: the governing specification's own suggested `LoadState` schema
    additionally names an optional `required_for_feasibility: bool` field (a state NOT
    so marked would be a diagnostic-only load level whose own infeasibility would not,
    by itself, make an alternative non-computable). That field is deliberately NOT
    implemented here: every load state declared in this v1.0 schema is implicitly
    mandatory -- `economics.annualized_system_costing.compute_annualized_system_economics()`
    reports `computable=False` whenever ANY declared state is infeasible, with no
    per-state override. This experiment's own three states must all be mandatory, so
    building unused optional-state configurability would be speculative complexity with
    no current caller (CLAUDE.md). Reserved for a future schema version if a genuinely
    diagnostic-only, non-mandatory load state is ever needed."""
    model_config = _MODEL_CONFIG

    load_state_id: str
    label: str
    demand_scale_fraction: float
    annual_duration_hours: float
    assumption_status: AssumptionStatus

    @model_validator(mode="after")
    def _validate(self) -> "LoadStateDefinition":
        errors: list[str] = []
        if not self.load_state_id:
            errors.append("load_state_id must not be empty")
        if not self.label:
            errors.append("label must not be empty")
        if not (0.0 < self.demand_scale_fraction <= 1.0):
            errors.append(
                f"demand_scale_fraction must be in (0, 1] (a fraction of the design/peak baseline demand), "
                f"got {self.demand_scale_fraction!r}"
            )
        if self.annual_duration_hours <= 0:
            errors.append(f"annual_duration_hours must be > 0, got {self.annual_duration_hours!r}")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def validate_load_state_durations(
    load_states: list[LoadStateDefinition], *, annualization_horizon_hours_per_year: float,
) -> list[str]:
    """Returns a list of violation messages (empty if none). Never raises --
    callers (ResearchExperimentConfig's own validator, and workflow-level checks)
    decide how to surface a non-empty result. Duplicate load_state_id and the spec's
    own explicit rule ("sum of all hours_per_year must equal the annualization horizon
    declared by policy") are both checkable at this purely-structural level; the
    CHOICE of scale fractions/durations/horizon themselves are a labelled
    synthetic_assumption, not structurally validated here."""
    errors: list[str] = []
    ids = [s.load_state_id for s in load_states]
    if len(ids) != len(set(ids)):
        errors.append("load_state_id values must be unique across load_states")
    total_hours = sum(s.annual_duration_hours for s in load_states)
    if not math.isclose(total_hours, annualization_horizon_hours_per_year, rel_tol=1e-9, abs_tol=1e-6):
        errors.append(
            f"sum of annual_duration_hours ({total_hours!r}) must equal "
            f"AnnualizationPolicy.horizon_hours_per_year ({annualization_horizon_hours_per_year!r}) exactly"
        )
    return errors


# ── Annualization horizon (RA-ECON) ──────────────────────────────────────────

class AnnualizationPolicy(BaseModel):
    """Explicit, declared counterpart of `economics.annualized_system_costing
    .compute_annualized_system_economics()`'s own ALREADY-FIXED behavior -- this
    model does not introduce new configurability; it makes that fixed behavior an
    honestly stated, checked fact rather than an implicit assumption no config value
    ever names. `horizon_hours_per_year` need not be the full 8760 h/a calendar year:
    it is whatever annual operating-hours horizon this experiment's own load states are
    meant to tile exactly (`validate_load_state_durations()` enforces the equality) --
    for a synthetic demonstration representing geothermal/DH operating hours rather
    than a full calendar year, a smaller declared horizon (matching the referenced v2
    package's own base economics `annual_full_load_hours`) is a legitimate, honestly
    labelled choice, not an error."""
    model_config = _MODEL_CONFIG

    horizon_hours_per_year: float
    useful_heat_boundary: Literal["consumer_delivery"] = "consumer_delivery"
    include_dh_pumping_electricity_in_opex: bool = True
    include_geothermal_pumping_electricity_in_opex: bool = True
    include_auxiliary_heat_in_opex: bool = True
    capex_annualized_once: bool = True

    @model_validator(mode="after")
    def _validate(self) -> "AnnualizationPolicy":
        errors: list[str] = []
        if self.horizon_hours_per_year <= 0:
            errors.append(f"horizon_hours_per_year must be > 0, got {self.horizon_hours_per_year!r}")
        # These five fields describe behavior compute_annualized_system_economics()
        # always implements -- there is no code path that honors any other
        # combination. A config declaring otherwise would silently misrepresent what
        # actually runs, so it is rejected here rather than accepted and ignored.
        if not self.include_dh_pumping_electricity_in_opex:
            errors.append("include_dh_pumping_electricity_in_opex must be true (always included by the implementation)")
        if not self.include_geothermal_pumping_electricity_in_opex:
            errors.append(
                "include_geothermal_pumping_electricity_in_opex must be true (always included by the implementation)"
            )
        if not self.include_auxiliary_heat_in_opex:
            errors.append("include_auxiliary_heat_in_opex must be true (always included by the implementation)")
        if not self.capex_annualized_once:
            errors.append("capex_annualized_once must be true (the implementation never annualizes CAPEX per load state)")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Sensitivity (RA-SENS) ─────────────────────────────────────────────────────

class SensitivityFactorName(str, Enum):
    """S-scoped, deterministic what-if factors -- never a probabilistic
    P10/P50/P90 exploration-risk framing (spec's own explicit constraint)."""
    CONNECTION_CAPEX_MULTIPLIER = "connection_capex_multiplier"
    GEOTHERMAL_DELIVERABLE_HEAT_DERATING_FRACTION = "geothermal_deliverable_heat_derating_fraction"


class SensitivityCaseDefinition(BaseModel):
    model_config = _MODEL_CONFIG

    case_id: str
    label: str
    factor_name: SensitivityFactorName
    multiplier: float
    reason: str
    assumption_status: AssumptionStatus

    @model_validator(mode="after")
    def _validate(self) -> "SensitivityCaseDefinition":
        errors: list[str] = []
        if not self.case_id:
            errors.append("case_id must not be empty")
        if not self.label:
            errors.append("label must not be empty")
        if not self.reason:
            errors.append("reason must not be empty (every sensitivity perturbation records why)")
        if self.multiplier <= 0:
            errors.append(f"multiplier must be > 0, got {self.multiplier!r}")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Baseline experiment policy (RA-BASE) ─────────────────────────────────────

class GeothermalOnlyBaselinePolicy(BaseModel):
    """Governs the geothermal-only baseline (spec §10): ranks resource
    SCENARIOS, each carrying its own linked site -- "do not silently collapse
    multiple scenarios at one site into one best-site value" (spec's own
    explicit words). `objective` is this baseline's own materiality-aware
    ranking definition (a genuinely different metric,
    `indicative_geothermal_lcoh_at_hx_eur_per_mwh`, from the integrated
    decision's own `annualized_system_lcoh_eur_per_mwh` -- reused
    `ObjectiveDefinition` type, own declared thresholds)."""
    model_config = _MODEL_CONFIG

    enabled: bool = True
    resource_scenario_ids: list[str] | None = None
    """None means every scenario in the referenced v2 package is eligible.
    When declared, only these scenario_ids are ranked -- never silently
    including or excluding a scenario the config doesn't name."""
    objective: ObjectiveDefinition


class NetworkOnlyBaselinePolicy(BaseModel):
    """Governs the network-only, fixed-source baseline (spec §11): "the
    policy must name one existing validated synthetic resource scenario and
    its site" -- an explicit, provenance-visible declaration, never an
    auto-selected default. `workflow.research_experiment` validates that
    `reference_resource_scenario_id` genuinely belongs to
    `reference_site_id` in the referenced v2 package (this model cannot
    check that itself -- the package isn't loaded yet at config-parse time)."""
    model_config = _MODEL_CONFIG

    enabled: bool = True
    reference_site_id: str
    reference_resource_scenario_id: str
    eligible_attachment_ids: list[str] | None = None
    """None means every network attachment compatible with the reference
    site is eligible."""

    @model_validator(mode="after")
    def _validate(self) -> "NetworkOnlyBaselinePolicy":
        errors: list[str] = []
        if not self.reference_site_id:
            errors.append("reference_site_id must not be empty")
        if not self.reference_resource_scenario_id:
            errors.append("reference_resource_scenario_id must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class IntegratedBaselinePolicy(BaseModel):
    model_config = _MODEL_CONFIG
    enabled: bool = True


class BaselineExperimentPolicy(BaseModel):
    """Spec §1.7.2's own suggested `BaselineExperimentPolicy` schema, adopted
    directly (field names/nesting) rather than reinvented."""
    model_config = _MODEL_CONFIG

    geothermal_only: GeothermalOnlyBaselinePolicy
    network_only: NetworkOnlyBaselinePolicy
    integrated: IntegratedBaselinePolicy


# ── Experiment configuration (RA-GOV/DATA) ───────────────────────────────────

class ResearchExperimentConfig(BaseModel):
    """References an already-committed v2 JointStudyPackage by package-relative
    path and expected SHA-256 -- never redefines sites/scenarios/attachments/
    routes/design options (those remain exclusively v2's own concern)."""
    model_config = _MODEL_CONFIG

    contract_schema_version: Literal["1.0.0"] = RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION
    referenced_study_package_relative_path: str
    referenced_study_package_expected_sha256: str = _Sha256Hex
    load_states: list[LoadStateDefinition]
    annualization: AnnualizationPolicy
    baselines: BaselineExperimentPolicy
    sensitivity_cases: list[SensitivityCaseDefinition]
    decision_policy: DecisionPolicy
    """Reused verbatim from data_contracts.joint_study -- see module docstring.
    Expected (but not structurally enforced here, since DecisionPolicy is
    intentionally generic) to name "annualized_system_lcoh_eur_per_mwh" as its
    primary_objective."""

    @model_validator(mode="after")
    def _validate(self) -> "ResearchExperimentConfig":
        errors: list[str] = []
        if not _is_safe_package_relative_path(self.referenced_study_package_relative_path):
            errors.append(
                f"referenced_study_package_relative_path is not a safe package-relative path: "
                f"{self.referenced_study_package_relative_path!r}"
            )
        if not self.load_states:
            errors.append("load_states must not be empty")
        ids = [s.load_state_id for s in self.load_states]
        if len(ids) != len(set(ids)):
            errors.append("load_state_id values must be unique across load_states")
        case_ids = [c.case_id for c in self.sensitivity_cases]
        if len(case_ids) != len(set(case_ids)):
            errors.append("case_id values must be unique across sensitivity_cases")
        if self.load_states:
            errors.extend(validate_load_state_durations(
                self.load_states, annualization_horizon_hours_per_year=self.annualization.horizon_hours_per_year,
            ))
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Per (alternative, load-state) performance (RA-LOAD) ──────────────────────

class LoadStatePerformanceResult(BaseModel):
    """One alternative's evaluation at one load state. Deliberately carries only
    plain scalar KPI fields (module docstring) rather than an embedded
    network.candidate.CandidateEvaluationResult. `annual_duration_hours` is
    duplicated here from the LoadStateDefinition it was evaluated against (this
    project's established self-contained-recomputability convention, e.g.
    CandidateEconomicResult's own baseline_* duplicate fields) so
    AnnualizedAlternativeEconomicResult can recompute its own aggregates from
    this model alone, without a second lookup into ResearchExperimentConfig."""
    model_config = _MODEL_CONFIG

    contract_schema_version: Literal["1.0.0"] = RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION
    load_state_id: str
    annual_duration_hours: float
    feasible: bool
    failure_code: str | None
    message: str | None

    geothermal_injected_heat_kw: float | None
    geothermal_curtailed_heat_kw: float | None
    auxiliary_heat_kw: float | None
    total_heat_delivered_kw: float | None
    doublet_pump_electric_power_kw: float | None
    dh_hydraulic_pumping_power_kw: float | None
    """Main plant pump + geothermal injection pump HYDRAULIC power, summed --
    matches economics.costing.CandidateEconomicResult.dh_hydraulic_pumping_power_kw's
    own field, before dh_pump_efficiency conversion (applied once, later, by
    economics.annualized_system_costing -- never here)."""
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "LoadStatePerformanceResult":
        errors: list[str] = []
        if not self.load_state_id:
            errors.append("load_state_id must not be empty")
        if self.annual_duration_hours <= 0:
            errors.append(f"annual_duration_hours must be > 0, got {self.annual_duration_hours!r}")
        kpi_fields = (
            self.geothermal_injected_heat_kw, self.geothermal_curtailed_heat_kw, self.auxiliary_heat_kw,
            self.total_heat_delivered_kw, self.doublet_pump_electric_power_kw, self.dh_hydraulic_pumping_power_kw,
        )
        if self.feasible:
            if self.failure_code is not None or self.message is not None:
                errors.append("failure_code and message must be null when feasible is True")
            if any(f is None for f in kpi_fields):
                errors.append("every KPI field is required when feasible is True")
            elif any(f < 0 for f in kpi_fields):
                errors.append("no KPI field may be negative")
        else:
            if not self.failure_code:
                errors.append("failure_code is required when feasible is False")
            if any(f is not None for f in kpi_fields):
                errors.append("every KPI field must be null when feasible is False")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Annualized system economics (RA-ECON) ────────────────────────────────────

class AnnualizedAlternativeEconomicResult(BaseModel):
    """One alternative's ANNUALIZED system economics across all of its load
    states. CAPEX/annuity is computed ONCE (never per load-state -- spec's own
    explicit rule); OPEX/auxiliary/pumping terms are summed across load states,
    each weighted by that state's own annual_duration_hours. Pumping electricity
    is always an OPEX/cost-numerator term -- NEVER subtracted from
    annual_useful_heat_mwh_per_a."""
    model_config = _MODEL_CONFIG

    contract_schema_version: Literal["1.0.0"] = RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION
    alternative_id: str
    load_state_results: list[LoadStatePerformanceResult]
    computable: bool
    non_computable_reason: str | None
    """Required (non-null) exactly when computable is False -- e.g. one or more
    load states failed to converge (module docstring, "Genuine risk" -- the
    Phase-0 audit's low-load curtailment finding). Never estimated or
    interpolated in that case; this alternative's annualized figure is simply
    not reported."""

    capex_doublet_eur: float | None
    capex_heat_exchanger_eur: float | None
    capex_connection_pipes_eur: float | None
    annuity_capital_eur_per_a: float | None
    """Computed once via economics.costing's existing
    _compute_annuity_capital_eur_per_a() (three separate lifetime-specific
    annuities, summed) -- not re-derived by this model's own invariant, since
    the three lifetimes/interest rate are not themselves stored here (they live
    on economics.assumptions.EconomicAssumptions, referenced by the v2 package's
    own economics section, not duplicated onto this contract)."""

    opex_fixed_eur_per_a: float | None
    opex_electricity_doublet_pump_eur_per_a: float | None
    opex_electricity_dh_pumping_eur_per_a: float | None
    opex_auxiliary_heat_eur_per_a: float | None

    annualized_total_system_cost_eur_per_a: float | None
    annual_useful_heat_mwh_per_a: float | None
    """E_useful = sum over load states r of (Q_delivered,r_kw * h_r) / 1000 --
    recomputed below straight from load_state_results, never from a separately
    stored per-state breakdown."""
    annualized_system_lcoh_eur_per_mwh: float | None

    created_at: datetime

    @model_validator(mode="after")
    def _validate_contract_invariants(self) -> "AnnualizedAlternativeEconomicResult":
        errors: list[str] = []
        if not self.load_state_results:
            errors.append("load_state_results must not be empty")
        all_feasible = bool(self.load_state_results) and all(r.feasible for r in self.load_state_results)
        if self.computable != all_feasible:
            errors.append("computable must be True iff every load_state_results entry is feasible")

        economics_fields = (
            self.capex_doublet_eur, self.capex_heat_exchanger_eur, self.capex_connection_pipes_eur,
            self.annuity_capital_eur_per_a, self.opex_fixed_eur_per_a,
            self.opex_electricity_doublet_pump_eur_per_a, self.opex_electricity_dh_pumping_eur_per_a,
            self.opex_auxiliary_heat_eur_per_a, self.annualized_total_system_cost_eur_per_a,
            self.annual_useful_heat_mwh_per_a, self.annualized_system_lcoh_eur_per_mwh,
        )
        if self.computable:
            if self.non_computable_reason is not None:
                errors.append("non_computable_reason must be null when computable is True")
            if any(f is None for f in economics_fields):
                errors.append("every economics field is required when computable is True")
            elif not all_feasible:
                # computable/all_feasible already disagree (logged above) -- an
                # infeasible load state's KPI fields are all None by its own
                # invariant, so recomputing E_useful here would crash rather
                # than cleanly reject; skip straight to raising the mismatch.
                pass
            else:
                expected_total_cost = (
                    self.annuity_capital_eur_per_a + self.opex_fixed_eur_per_a
                    + self.opex_electricity_doublet_pump_eur_per_a + self.opex_electricity_dh_pumping_eur_per_a
                    + self.opex_auxiliary_heat_eur_per_a
                )
                if not math.isclose(expected_total_cost, self.annualized_total_system_cost_eur_per_a, rel_tol=1e-9, abs_tol=1e-6):
                    errors.append("annualized_total_system_cost_eur_per_a does not match recomputation from its own components")
                expected_useful_mwh = sum(
                    (r.total_heat_delivered_kw * r.annual_duration_hours) / 1000.0
                    for r in self.load_state_results
                )
                if not math.isclose(expected_useful_mwh, self.annual_useful_heat_mwh_per_a, rel_tol=1e-9, abs_tol=1e-6):
                    errors.append("annual_useful_heat_mwh_per_a does not match recomputation from load_state_results")
                if self.annual_useful_heat_mwh_per_a is not None and self.annual_useful_heat_mwh_per_a <= 0:
                    errors.append("annual_useful_heat_mwh_per_a must be > 0 when computable")
                elif self.annualized_total_system_cost_eur_per_a is not None and self.annual_useful_heat_mwh_per_a:
                    expected_lcoh = self.annualized_total_system_cost_eur_per_a / self.annual_useful_heat_mwh_per_a
                    if not math.isclose(expected_lcoh, self.annualized_system_lcoh_eur_per_mwh, rel_tol=1e-9, abs_tol=1e-6):
                        errors.append("annualized_system_lcoh_eur_per_mwh does not match recomputation")
        else:
            if not self.non_computable_reason:
                errors.append("non_computable_reason is required when computable is False")
            if any(f is not None for f in economics_fields):
                errors.append("every economics field must be null when computable is False")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Cross-baseline comparison (RA-BASE) ──────────────────────────────────────

class ComparisonInterpretationCode(str, Enum):
    """Typed, deterministic, SET-based comparison outcomes (spec's own explicit
    requirement: "compare sets, not arbitrary first elements of tied groups").

    `MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON` is retained because the spec
    requires the full code set to exist, but is STRUCTURALLY UNREACHABLE from
    `decision.research_comparison.compare_baselines()`'s own current call
    pattern: disjointness between two rank-1 SETS is always computable once
    both sets are non-empty (they may contain more than one member -- a tie
    -- without preventing the disjointness check itself), and
    `primary_objective_ranking` mode always yields a non-empty rank-1 group
    whenever at least one alternative is computable. This is disclosed
    honestly (decision-register) rather than a fabricated test path invented
    just to exercise it."""
    INTEGRATED_MATCHES_BOTH_BASELINES = "INTEGRATED_MATCHES_BOTH_BASELINES"
    INTEGRATED_SITE_DIFFERS_FROM_GEO_ONLY = "INTEGRATED_SITE_DIFFERS_FROM_GEO_ONLY"
    INTEGRATED_ATTACHMENT_DIFFERS_FROM_NETWORK_ONLY = "INTEGRATED_ATTACHMENT_DIFFERS_FROM_NETWORK_ONLY"
    INTEGRATED_DIFFERS_FROM_BOTH = "INTEGRATED_DIFFERS_FROM_BOTH"
    MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON = "MATERIAL_TIE_PREVENTS_UNIQUE_COMPARISON"
    NO_FEASIBLE_INTEGRATED_ALTERNATIVE = "NO_FEASIBLE_INTEGRATED_ALTERNATIVE"
    BASELINE_NOT_RANKABLE = "BASELINE_NOT_RANKABLE"


class BaselineComparisonResult(BaseModel):
    """Spec §13's own suggested field list, adopted directly. Every `*_ids`
    field is a RANK-1 SET (sorted for determinism), never a single arbitrary
    winner -- "compare sets, not arbitrary first elements of tied groups"."""
    model_config = _MODEL_CONFIG

    contract_schema_version: Literal["1.0.0"] = RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION
    interpretation_code: ComparisonInterpretationCode
    geothermal_only_best_scenario_ids: list[str]
    network_only_best_attachment_ids: list[str]
    integrated_best_alternative_ids: list[str]
    integrated_best_site_ids: list[str]
    integrated_best_attachment_ids: list[str]
    site_decision_changed_after_integration: bool | None
    """True only when the integrated rank-1 site set is DISJOINT from the
    geothermal-only rank-1 site set; False on any overlap (spec §13's own
    exact rule); null when either baseline has no feasible/rankable result
    at all (never a fabricated True/False in that case)."""
    attachment_decision_changed_after_integration: bool | None
    explanation: str

    @model_validator(mode="after")
    def _validate(self) -> "BaselineComparisonResult":
        errors: list[str] = []
        if not self.explanation:
            errors.append("explanation must not be empty")
        no_feasible = self.interpretation_code == ComparisonInterpretationCode.NO_FEASIBLE_INTEGRATED_ALTERNATIVE
        not_rankable = self.interpretation_code == ComparisonInterpretationCode.BASELINE_NOT_RANKABLE
        if no_feasible and self.integrated_best_alternative_ids:
            errors.append("integrated_best_alternative_ids must be empty when interpretation_code is NO_FEASIBLE_INTEGRATED_ALTERNATIVE")
        if (no_feasible or not_rankable) and (
            self.site_decision_changed_after_integration is not None
            or self.attachment_decision_changed_after_integration is not None
        ):
            errors.append(
                "site_decision_changed_after_integration/attachment_decision_changed_after_integration must both "
                "be null when interpretation_code is NO_FEASIBLE_INTEGRATED_ALTERNATIVE or BASELINE_NOT_RANKABLE"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Sensitivity / robustness (RA-SENS) ───────────────────────────────────────

class SensitivityCaseResult(BaseModel):
    """Exposes the FULL rank-1 group under this sensitivity case (spec §14.3:
    "rank-1 group for every sensitivity case"), not merely a single winner.
    `preferred_alternative_id` is a convenience field, non-null only when the
    rank-1 group happens to contain exactly one alternative."""
    model_config = _MODEL_CONFIG

    contract_schema_version: Literal["1.0.0"] = RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION
    case_id: str
    rank1_alternative_ids: list[str]
    rank1_site_ids: list[str]
    rank1_attachment_ids: list[str]
    newly_infeasible_alternative_ids: list[str]
    """Alternatives `computable=True` in the base (unperturbed) case but not
    under this perturbation -- spec §14.3's "whether any candidate becomes
    infeasible"."""
    preferred_alternative_id: str | None

    @model_validator(mode="after")
    def _validate(self) -> "SensitivityCaseResult":
        errors: list[str] = []
        if not self.case_id:
            errors.append("case_id must not be empty")
        if self.preferred_alternative_id is not None and len(self.rank1_alternative_ids) != 1:
            errors.append("preferred_alternative_id must be null unless rank1_alternative_ids has exactly one member")
        if self.preferred_alternative_id is not None and self.preferred_alternative_id not in self.rank1_alternative_ids:
            errors.append("preferred_alternative_id must be a member of rank1_alternative_ids when set")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class RobustnessClassification(str, Enum):
    """Never shortened to "robust" without its qualifier (spec's own explicit
    naming discipline)."""
    ROBUST_OVER_TESTED_RANGE = "ROBUST_OVER_TESTED_RANGE"
    ROBUST_SITE_BUT_CONNECTION_SENSITIVE = "ROBUST_SITE_BUT_CONNECTION_SENSITIVE"
    ROBUST_CONNECTION_BUT_SITE_SENSITIVE = "ROBUST_CONNECTION_BUT_SITE_SENSITIVE"
    ASSUMPTION_SENSITIVE = "ASSUMPTION_SENSITIVE"
    NO_UNIQUE_BASE_WINNER = "NO_UNIQUE_BASE_WINNER"
    INSUFFICIENT_FEASIBLE_CASES = "INSUFFICIENT_FEASIBLE_CASES"


class CandidateRankSensitivity(BaseModel):
    """Per-candidate rank-movement summary across every declared sensitivity
    case (spec §14.3: "maximum observed rank change for each base
    candidate"). `base_rank`/each case's own rank are 1-based rank-GROUP
    indices from `decision.joint_policy.decide()`'s own
    `ranked_alternative_groups` (rank 1 = the first/best group; materially
    tied alternatives share one rank, matching this project's established
    ranking convention) -- never a re-derived or invented ranking."""
    model_config = _MODEL_CONFIG

    alternative_id: str
    base_rank: int | None
    """Null when this candidate was not computable at all in the base
    (unperturbed) case."""
    max_rank_change: int | None
    """max(abs(case_rank - base_rank)) over every sensitivity case where the
    candidate was computable in BOTH the base case and that case. Null when
    there is no such case (e.g. the candidate was never computable in the
    base case, or became/was infeasible in every declared case) -- an
    infeasible candidate is never assigned an ordinary numeric rank change,
    per `became_infeasible_in_any_case` below instead."""
    became_infeasible_in_any_case: bool
    """True when this candidate was computable in the base case but not
    computable under at least one declared sensitivity case."""
    restored_to_feasibility_in_any_case: bool
    """The symmetric case: not computable in the base case, but computable
    under at least one declared sensitivity case -- reported honestly
    rather than only tracking one direction."""

    @model_validator(mode="after")
    def _validate(self) -> "CandidateRankSensitivity":
        errors: list[str] = []
        if not self.alternative_id:
            errors.append("alternative_id must not be empty")
        if self.base_rank is not None and self.base_rank < 1:
            errors.append(f"base_rank must be >= 1 when set, got {self.base_rank!r}")
        if self.max_rank_change is not None and self.max_rank_change < 0:
            errors.append(f"max_rank_change must be >= 0 when set, got {self.max_rank_change!r}")
        if self.base_rank is None and self.max_rank_change is not None:
            errors.append("max_rank_change must be null when base_rank is null (not computable in the base case)")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class ResearchExperimentDecisionSummary(BaseModel):
    model_config = _MODEL_CONFIG

    contract_schema_version: Literal["1.0.0"] = RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION
    base_case_preferred_alternative_id: str | None
    sensitivity_case_results: list[SensitivityCaseResult]
    candidate_rank_sensitivity: list[CandidateRankSensitivity]
    robustness_classification: RobustnessClassification
    explanation: str

    @model_validator(mode="after")
    def _validate(self) -> "ResearchExperimentDecisionSummary":
        errors: list[str] = []
        if not self.explanation:
            errors.append("explanation must not be empty")
        if (
            self.robustness_classification == RobustnessClassification.NO_UNIQUE_BASE_WINNER
            and self.base_case_preferred_alternative_id is not None
        ):
            errors.append(
                "base_case_preferred_alternative_id must be null when robustness_classification is "
                "NO_UNIQUE_BASE_WINNER -- INSUFFICIENT_FEASIBLE_CASES is deliberately not restricted the "
                "same way, since it can mean a well-defined base winner with too few/ambiguous "
                "sensitivity cases to classify robustness against it"
            )
        case_ids = [c.case_id for c in self.sensitivity_case_results]
        if len(case_ids) != len(set(case_ids)):
            errors.append("case_id values must be unique across sensitivity_case_results")
        rank_sensitivity_ids = [c.alternative_id for c in self.candidate_rank_sensitivity]
        if len(rank_sensitivity_ids) != len(set(rank_sensitivity_ids)):
            errors.append("alternative_id values must be unique across candidate_rank_sensitivity")
        if errors:
            raise ValueError("; ".join(errors))
        return self
