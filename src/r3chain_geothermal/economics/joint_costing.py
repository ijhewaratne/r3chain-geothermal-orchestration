"""Joint site/scenario economics (S13, ECON-001..015,
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 4).

## Reuse, not reinvention (EVAL-004, GOV-010)

This module adds NO new cost formula. `compute_alternative_economics()`
builds an `EconomicAssumptions` override -- via `.model_copy(update=...)`,
the SAME idiom `workflow/joint_optimization.py`'s v1 module already
established for its own `drilling_capex_multiplier` (IMPL-021) -- and then
calls the EXISTING, unmodified `economics.costing.compute_candidate_economics()`
verbatim. Annuity, OPEX, LCOH: all computed by that one already-tested
function, exactly as the canonical single-scenario workflow and the v1
joint module both already use it.

## What the override actually overrides (ECON-001/002/006/007/014)

Only two `EconomicAssumptions` fields are ever overridden, one value each,
never additively combined with the base config's own value (ECON-014: no
double counting):

- `doublet_capex_eur` <- the scenario's OWN declared, already-validated
  `SiteEconomicInputs` CAPEX (aggregate OR summed component breakdown --
  `_scenario_doublet_capex_eur()` reads whichever S7.7's own contract
  validator (Phase 1) already confirmed is present; TERM-008/ECON-001's
  `doublet_capex_multiplier` was already baked into this declared value
  when the scenario's `SyntheticDerivation` was constructed -- it is
  audit provenance for HOW that number was derived, not something
  re-applied here a second time).
- `connection_pipe_capex_eur_per_m` <- the alternative's OWN
  `ConnectionDesignOption.capex_eur_per_paired_trench_m` (ECON-006).

HX CAPEX is deliberately NOT overridden (ECON-008: "HX CAPEX remains
fixed only when explicitly declared" -- no site/scenario-specific,
sourced HX-duty-dependent cost model exists in this prototype, so the
base config's own single declared value applies to every alternative,
exactly as it already does for the canonical workflow).

`candidate_result.candidate.surface_connection_length_m` (already set to
`route.paired_trench_length_m` by `workflow/joint_evaluation.py`) is the
ONE length `compute_candidate_economics()` consumes for connection CAPEX
-- automatically the SAME length pandapipes already solved against
(ECON-007), with no separate wiring needed here.

## Base assumptions: referenced, not duplicated (S7.16)

`JointEconomicPolicy` is a thin reference to the EXISTING
`config/demo_assumptions.json`-shaped economics config (S7.16: "This
joint wrapper identifies and hashes it... any site/scenario override must
be explicit, typed and non-overlapping") -- `load_base_assumptions()`
resolves `base_assumptions_package_relative_path` under the package root
and constructs the SAME `EconomicAssumptions.from_config_dict()` the
canonical workflow already uses. Byte-hash verification against
`base_assumptions_sha256` is NOT implemented in this phase -- a stated
limitation (Phase 5's own audit-completeness concern), not silently
skipped."""
from __future__ import annotations

import json
from pathlib import Path

from ..data_contracts.joint_study import GeothermalResourceScenario, SiteEconomicInputs, ConnectionDesignOption, JointEconomicPolicy
from ..network import CandidateEvaluationResult
from .assumptions import EconomicAssumptions
from .costing import BaselineEconomicResult, CandidateEconomicResult, compute_candidate_economics


def _scenario_doublet_capex_eur(economic_inputs: SiteEconomicInputs) -> float:
    """S7.7's own XOR rule (aggregate xor complete component breakdown)
    is already enforced by SiteEconomicInputs's own validator (Phase 1)
    -- this just reads whichever form is present."""
    if economic_inputs.doublet_capex_eur is not None:
        return economic_inputs.doublet_capex_eur
    components = [
        economic_inputs.drilling_producer_well_capex_eur, economic_inputs.drilling_injector_well_capex_eur,
        economic_inputs.well_completion_capex_eur, economic_inputs.surface_plant_capex_eur,
        economic_inputs.contingency_capex_eur,
    ]
    return sum(c for c in components if c is not None)


def load_base_assumptions(economic_policy: JointEconomicPolicy, package_root: Path) -> EconomicAssumptions:
    """Resolves `base_assumptions_package_relative_path` under
    `package_root` and constructs the EXISTING `EconomicAssumptions` the
    canonical workflow already uses -- never a second, competing
    economics-config schema."""
    path = (package_root / economic_policy.base_assumptions_package_relative_path).resolve()
    if package_root.resolve() not in path.parents and path != package_root.resolve():
        raise ValueError(f"base_assumptions_package_relative_path escapes the package root: {path}")
    config = json.loads(path.read_text())
    return EconomicAssumptions.from_config_dict(config)


def compute_alternative_economics(
    candidate_result: CandidateEvaluationResult,
    scenario: GeothermalResourceScenario,
    design: ConnectionDesignOption,
    baseline_economics: BaselineEconomicResult,
    base_assumptions: EconomicAssumptions,
) -> CandidateEconomicResult:
    """ECON-001..007/014: builds the two-field override described in the
    module docstring, then delegates entirely to
    `economics.costing.compute_candidate_economics()` -- no new
    arithmetic. Only ever called on an already-FEASIBLE
    `CandidateEvaluationResult` (EVAL-009/DEC-010: never calculate
    economics for an infeasible alternative) -- enforced by the caller
    (`workflow.joint_evaluation`), not re-checked here."""
    overridden_assumptions = base_assumptions.model_copy(update={
        "doublet_capex_eur": _scenario_doublet_capex_eur(scenario.economic_inputs),
        "connection_pipe_capex_eur_per_m": design.capex_eur_per_paired_trench_m,
    })
    return compute_candidate_economics(candidate_result, baseline_economics, assumptions=overridden_assumptions)
