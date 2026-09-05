"""Artifact bundle for the research-experiment layer (Phase 7, R3-CHAIN Final
Research-Alignment Implementation Specification, RA-ART).

Follows `workflow.joint_workflow_v2`'s own hashing/manifest pattern exactly
(`ArtifactHashRecord`'s byte/scientific-hash split, `normalize_for_scientific_hash()`
for JSON files, a `manifest.json` that never hashes itself). Scoped narrower
than the v2 bundle's own full site-route SVG map -- this layer's own
contribution is the load-state/annualized/comparison story, not connection
geometry (the referenced v2 run's own bundle already covers that map).

## Conformance-round revision (this file's own second edit)

The bundle now publishes every file the specification's own §17 "shall publish
at least" list names (19 files total, `_SPEC_NAMED_FILENAMES` below), not the
smaller 8-file bundle this module originally shipped with. Every added file is
a thin serialization of data `ResearchExperimentResult` already carries (or, for
the geothermal-only/network-only breakdowns, data
`decision.research_comparison`'s own ranking functions already compute and the
orchestrator threads through as `geothermal_only_decision`/
`geothermal_only_lcoh_by_scenario_id`/`network_only_decision`/`network_only_subset`)
-- no new domain computation was added for this revision.

## Third revision -- rank-1 SET semantics (this file's own third edit)

`geothermal_only_result.json`/`.csv` now report every eligible SCENARIO
individually (never collapsed per site -- spec §10.2); `research_comparison
.json`/`.csv` and `research_findings.md` now expose rank-1 SETS
(`geothermal_only_best_scenario_ids`, `integrated_best_site_ids`, etc.) rather
than single winner IDs, matching `decision.research_comparison`'s own
corrected rank-1-set comparison; `sensitivity_comparison.csv` now records each
case's own rank-1 group and newly-infeasible alternatives, not one winner."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ..hashing import (
    SCIENTIFIC_NORMALIZATION_RULE_VERSION,
    canonical_raw_result_json_bytes,
    canonical_raw_result_sha256,
    normalize_for_scientific_hash,
)
from .artifacts import ArtifactHashRecord
from .research_experiment import (
    ResearchExperimentBoundaryResult,
    ResearchExperimentFailure,
    ResearchExperimentResult,
)

PYDOUBLET_INPUT_FILENAME = "pydoublet_input.json"
CONFIG_SNAPSHOT_FILENAME = "config_snapshot.json"
REFERENCED_V2_RESULT_FILENAME = "referenced_v2_result_snapshot.json"
RESEARCH_EXPERIMENT_RESULT_FILENAME = "research_experiment_result.json"
AUDIT_FILENAME = "audit.json"
MANIFEST_FILENAME = "manifest.json"

# ── §17-named files (spec's own exact filenames) ─────────────────────────────
EXPERIMENT_INPUT_FILENAME = "experiment_input.json"
JOINT_STUDY_SNAPSHOT_FILENAME = "joint_study_snapshot.json"
LOAD_STATES_FILENAME = "load_states.json"
LOAD_STATE_RESULTS_FILENAME = "load_state_results.json"
ANNUALIZED_ALTERNATIVE_COMPARISON_CSV_FILENAME = "annualized_alternative_comparison.csv"
ANNUALIZED_INTEGRATED_RESULT_FILENAME = "annualized_integrated_result.json"
GEOTHERMAL_ONLY_RESULT_FILENAME = "geothermal_only_result.json"
GEOTHERMAL_ONLY_COMPARISON_CSV_FILENAME = "geothermal_only_comparison.csv"
NETWORK_ONLY_RESULT_FILENAME = "network_only_result.json"
NETWORK_ONLY_COMPARISON_CSV_FILENAME = "network_only_comparison.csv"
RESEARCH_COMPARISON_FILENAME = "research_comparison.json"
RESEARCH_COMPARISON_CSV_FILENAME = "research_comparison.csv"
SENSITIVITY_RESULTS_FILENAME = "sensitivity_results.json"
SENSITIVITY_COMPARISON_CSV_FILENAME = "sensitivity_comparison.csv"
OBJECTIVE_POLICY_FILENAME = "objective_policy.json"
PARETO_OR_RANKING_FILENAME = "pareto_or_ranking.json"
RESEARCH_FINDINGS_MD_FILENAME = "research_findings.md"

# ── Beyond the spec's own literal §17 list: an explicit reviewer convenience ──
SENSITIVITY_RANK_CHANGES_CSV_FILENAME = "sensitivity_rank_changes.csv"
"""Not one of the spec's own §17-named files -- an ADDITIONAL export (spec
§14.3's "maximum observed rank change for each base candidate", already
present inside `sensitivity_results.json`'s own `candidate_rank_sensitivity`
field) so a reviewer can inspect per-candidate rank movement directly,
without opening the aggregate JSON file."""

RESEARCH_EXPERIMENT_SYNTHETIC_DISCLAIMER = (
    "This is a SYNTHETIC demonstration: every site, resource scenario, route, design, load state and "
    "sensitivity case here is explicitly invented for this prototype. It contains no real Wuppertal (or "
    "any other real place's) data, and must never be read as a real geological drilling-site "
    "recommendation, a real network-connection recommendation, or a validated economic result. This "
    "layer compares the source-side, network-only and integrated preferences against each other; it "
    "does not determine where a doublet should be drilled or claim any result is assumption-robust "
    "beyond the small, explicitly deterministic sensitivity cases actually tested."
)

_CORE_SCIENTIFIC_FILENAMES = (
    PYDOUBLET_INPUT_FILENAME, CONFIG_SNAPSHOT_FILENAME, RESEARCH_EXPERIMENT_RESULT_FILENAME, AUDIT_FILENAME,
)
_SPEC_NAMED_JSON_FILENAMES = (
    EXPERIMENT_INPUT_FILENAME, JOINT_STUDY_SNAPSHOT_FILENAME, LOAD_STATES_FILENAME, LOAD_STATE_RESULTS_FILENAME,
    ANNUALIZED_INTEGRATED_RESULT_FILENAME, GEOTHERMAL_ONLY_RESULT_FILENAME, NETWORK_ONLY_RESULT_FILENAME,
    RESEARCH_COMPARISON_FILENAME, SENSITIVITY_RESULTS_FILENAME, OBJECTIVE_POLICY_FILENAME, PARETO_OR_RANKING_FILENAME,
)
_SPEC_NAMED_CSV_FILENAMES = (
    ANNUALIZED_ALTERNATIVE_COMPARISON_CSV_FILENAME, GEOTHERMAL_ONLY_COMPARISON_CSV_FILENAME,
    NETWORK_ONLY_COMPARISON_CSV_FILENAME, RESEARCH_COMPARISON_CSV_FILENAME, SENSITIVITY_COMPARISON_CSV_FILENAME,
)


class ResearchExperimentManifestRecord(BaseModel):
    """manifest.json's own content -- mirrors
    JointWorkflowV2ManifestRecord's shape/invariants exactly, for this
    module's own (different) filename set."""
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    contract_schema_version: str = "1.0.0"
    scientific_normalization_rule_version: str = SCIENTIFIC_NORMALIZATION_RULE_VERSION
    run_type: Literal["research_experiment"] = "research_experiment"
    """An explicit, on-disk run-type discriminator, matching how
    JointWorkflowV2ManifestRecord.run_type lets mcp_server/registry.py's
    own rehydration decide, from the manifest alone, which parser to use
    -- Phase 6 extends that same dispatch with this third value."""
    run_id: str
    created_at: datetime
    files: dict[str, ArtifactHashRecord]
    bundle_scientific_sha256: str

    @model_validator(mode="after")
    def _validate(self) -> "ResearchExperimentManifestRecord":
        errors: list[str] = []
        if not set(_CORE_SCIENTIFIC_FILENAMES) <= set(self.files.keys()):
            errors.append(f"files must contain at least {sorted(_CORE_SCIENTIFIC_FILENAMES)}, got {sorted(self.files.keys())}")
        if MANIFEST_FILENAME in self.files:
            errors.append("manifest.json must never hash itself")
        for filename in self.files:
            if "/" in filename or "\\" in filename or filename.startswith("."):
                errors.append(f"files[{filename!r}] must be a plain relative filename, not a path")
        expected_bundle_hash = canonical_raw_result_sha256(
            {filename: record.scientific_sha256 for filename, record in sorted(self.files.items())}
        )
        if self.bundle_scientific_sha256 != expected_bundle_hash:
            errors.append("bundle_scientific_sha256 does not match recomputation")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _hash_record_for_json_bytes(data: bytes) -> ArtifactHashRecord:
    parsed = json.loads(data)
    normalized = normalize_for_scientific_hash(parsed)
    scientific_hash = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()
    byte_hash = hashlib.sha256(data).hexdigest()
    return ArtifactHashRecord(byte_sha256=byte_hash, scientific_sha256=scientific_hash)


def _hash_record_for_plain_bytes(data: bytes) -> ArtifactHashRecord:
    byte_hash = hashlib.sha256(data).hexdigest()
    return ArtifactHashRecord(byte_sha256=byte_hash, scientific_sha256=byte_hash)


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


# ── §17 JSON renderers -- each a thin serialization of already-existing data ──

def render_experiment_input_json(result: ResearchExperimentResult) -> bytes:
    """"experiment_input.json -- normalized experiment package" (spec §17)."""
    return (result.research_config.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_joint_study_snapshot_json(result: ResearchExperimentResult) -> bytes:
    """"joint_study_snapshot.json -- exact referenced v2 study package" (spec §17).
    The spec explicitly permits copying/referencing the existing v2 artifact rather
    than redundantly recomputing it; this renders the SAME package object already
    embedded (and hash-verified) on `referenced_v2_result.package`."""
    return (result.referenced_v2_result.package.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_load_states_json(result: ResearchExperimentResult) -> bytes:
    payload = [json.loads(ls.model_dump_json()) for ls in result.research_config.load_states]
    return _json_bytes(payload)


def render_load_state_results_json(result: ResearchExperimentResult) -> bytes:
    """"one result per integrated alternative x load state" (spec §17) -- a flat
    list, each row tagged with its own alternative_id."""
    rows: list[dict[str, Any]] = []
    for summary in sorted(result.alternative_summaries, key=lambda s: s.alternative_id):
        for state_result in summary.annualized_economics.load_state_results:
            row = json.loads(state_result.model_dump_json())
            row["alternative_id"] = summary.alternative_id
            rows.append(row)
    return _json_bytes(rows)


def render_annualized_integrated_result_json(result: ResearchExperimentResult) -> bytes:
    payload = {
        "decision": json.loads(result.integrated_decision.model_dump_json()),
        "alternatives": {
            summary.alternative_id: json.loads(summary.annualized_economics.model_dump_json())
            for summary in result.alternative_summaries
        },
    }
    return _json_bytes(payload)


def render_geothermal_only_result_json(result: ResearchExperimentResult) -> bytes:
    """Reports every eligible SCENARIO individually (spec §10.2: "do not
    silently collapse multiple scenarios at one site into one best-site
    value") -- never a per-site value."""
    payload = {
        "rank1_scenario_ids": (
            list(result.geothermal_only_decision.ranked_alternative_groups[0])
            if result.geothermal_only_decision.ranked_alternative_groups else []
        ),
        "lcoh_eur_per_mwh_by_scenario_id": result.geothermal_only_lcoh_by_scenario_id,
        "decision": json.loads(result.geothermal_only_decision.model_dump_json()),
    }
    return _json_bytes(payload)


def render_network_only_result_json(result: ResearchExperimentResult) -> bytes:
    payload = {
        "rank1_alternative_ids": (
            list(result.network_only_decision.ranked_alternative_groups[0])
            if result.network_only_decision.ranked_alternative_groups else []
        ),
        "decision": json.loads(result.network_only_decision.model_dump_json()),
        "alternatives": {
            alt_id: json.loads(annualized.model_dump_json())
            for alt_id, annualized in result.network_only_subset.items()
        },
    }
    return _json_bytes(payload)


def render_research_comparison_json(result: ResearchExperimentResult) -> bytes:
    return (result.baseline_comparison.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_sensitivity_results_json(result: ResearchExperimentResult) -> bytes:
    return (result.sensitivity_decision_summary.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_objective_policy_json(result: ResearchExperimentResult) -> bytes:
    return (result.research_config.decision_policy.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_pareto_or_ranking_json(result: ResearchExperimentResult) -> bytes:
    """Matches workflow.joint_workflow_v2.render_pareto_or_ranking_json()'s own
    content shape exactly -- the full JointDecisionResult, verbatim."""
    return (result.integrated_decision.model_dump_json(indent=2) + "\n").encode("utf-8")


# ── §17 CSV renderers ─────────────────────────────────────────────────────────

def render_annualized_alternative_comparison_csv(result: ResearchExperimentResult) -> bytes:
    """One row per compatible alternative -- deterministic order by
    alternative_id (DEC-015: display order only, never a scientific
    decision)."""
    header = (
        "alternative_id,surface_site_id,attachment_id,resource_scenario_id,computable,"
        "annualized_system_lcoh_eur_per_mwh,annual_useful_heat_mwh_per_a,non_computable_reason\n"
    )
    lines = [header]
    for summary in sorted(result.alternative_summaries, key=lambda s: s.alternative_id):
        econ = summary.annualized_economics
        lcoh = "" if econ.annualized_system_lcoh_eur_per_mwh is None else f"{econ.annualized_system_lcoh_eur_per_mwh:.6f}"
        useful = "" if econ.annual_useful_heat_mwh_per_a is None else f"{econ.annual_useful_heat_mwh_per_a:.6f}"
        reason = (econ.non_computable_reason or "").replace(",", ";")
        lines.append(
            f"{summary.alternative_id},{summary.surface_site_id},{summary.attachment_id},"
            f"{summary.resource_scenario_id},{econ.computable},{lcoh},{useful},{reason}\n"
        )
    return "".join(lines).encode("utf-8")


def render_geothermal_only_comparison_csv(result: ResearchExperimentResult) -> bytes:
    """One row PER SCENARIO (never per site -- spec §10.2)."""
    header = "scenario_id,site_id,lcoh_eur_per_mwh,is_rank1\n"
    lines = [header]
    scenario_site_by_id = {s.scenario_id: s.site_id for s in result.referenced_v2_result.package.resource_scenarios}
    rank1_ids = set(
        result.geothermal_only_decision.ranked_alternative_groups[0]
        if result.geothermal_only_decision.ranked_alternative_groups else []
    )
    for scenario_id in sorted(result.geothermal_only_lcoh_by_scenario_id):
        lcoh = result.geothermal_only_lcoh_by_scenario_id[scenario_id]
        site_id = scenario_site_by_id.get(scenario_id, "")
        is_rank1 = scenario_id in rank1_ids
        lines.append(f"{scenario_id},{site_id},{lcoh:.6f},{is_rank1}\n")
    return "".join(lines).encode("utf-8")


def render_network_only_comparison_csv(result: ResearchExperimentResult) -> bytes:
    header = "alternative_id,attachment_id,computable,annualized_system_lcoh_eur_per_mwh,is_rank1\n"
    lines = [header]
    attachment_by_id = {s.alternative_id: s.attachment_id for s in result.alternative_summaries}
    rank1_ids = set(
        result.network_only_decision.ranked_alternative_groups[0]
        if result.network_only_decision.ranked_alternative_groups else []
    )
    for alt_id in sorted(result.network_only_subset):
        annualized = result.network_only_subset[alt_id]
        attachment_id = attachment_by_id.get(alt_id, "")
        lcoh = "" if annualized.annualized_system_lcoh_eur_per_mwh is None else f"{annualized.annualized_system_lcoh_eur_per_mwh:.6f}"
        is_rank1 = alt_id in rank1_ids
        lines.append(f"{alt_id},{attachment_id},{annualized.computable},{lcoh},{is_rank1}\n")
    return "".join(lines).encode("utf-8")


def render_research_comparison_csv(result: ResearchExperimentResult) -> bytes:
    header = (
        "interpretation_code,geothermal_only_best_scenario_ids,network_only_best_attachment_ids,"
        "integrated_best_alternative_ids,integrated_best_site_ids,integrated_best_attachment_ids,"
        "site_decision_changed_after_integration,attachment_decision_changed_after_integration,explanation\n"
    )
    comparison = result.baseline_comparison
    explanation = comparison.explanation.replace(",", ";").replace("\n", " ")
    row = (
        f"{comparison.interpretation_code.value},{';'.join(comparison.geothermal_only_best_scenario_ids)},"
        f"{';'.join(comparison.network_only_best_attachment_ids)},{';'.join(comparison.integrated_best_alternative_ids)},"
        f"{';'.join(comparison.integrated_best_site_ids)},{';'.join(comparison.integrated_best_attachment_ids)},"
        f"{comparison.site_decision_changed_after_integration!s},{comparison.attachment_decision_changed_after_integration!s},"
        f"{explanation}\n"
    )
    return (header + row).encode("utf-8")


def render_sensitivity_comparison_csv(result: ResearchExperimentResult) -> bytes:
    header = (
        "case_id,rank1_alternative_ids,rank1_site_ids,rank1_attachment_ids,"
        "newly_infeasible_alternative_ids,preferred_alternative_id\n"
    )
    lines = [header]
    for case_result in result.sensitivity_decision_summary.sensitivity_case_results:
        lines.append(
            f"{case_result.case_id},{';'.join(case_result.rank1_alternative_ids)},"
            f"{';'.join(case_result.rank1_site_ids)},{';'.join(case_result.rank1_attachment_ids)},"
            f"{';'.join(case_result.newly_infeasible_alternative_ids)},{case_result.preferred_alternative_id or ''}\n"
        )
    return "".join(lines).encode("utf-8")


def render_sensitivity_rank_changes_csv(result: ResearchExperimentResult) -> bytes:
    """spec §14.3's "maximum observed rank change for each base candidate" --
    one row per candidate ever evaluated, matching `CandidateRankSensitivity`
    exactly (see `data_contracts.research_experiment` for field semantics)."""
    header = "alternative_id,base_rank,max_rank_change,became_infeasible_in_any_case,restored_to_feasibility_in_any_case\n"
    lines = [header]
    for entry in result.sensitivity_decision_summary.candidate_rank_sensitivity:
        base_rank = "" if entry.base_rank is None else str(entry.base_rank)
        max_rank_change = "" if entry.max_rank_change is None else str(entry.max_rank_change)
        lines.append(
            f"{entry.alternative_id},{base_rank},{max_rank_change},"
            f"{entry.became_infeasible_in_any_case},{entry.restored_to_feasibility_in_any_case}\n"
        )
    return "".join(lines).encode("utf-8")


# ── research_findings.md ──────────────────────────────────────────────────────

def render_research_findings_markdown(result: ResearchExperimentResult) -> bytes:
    """States, deterministically, every element spec §17.1 requires -- never a
    natural-language claim not derivable from `baseline_comparison`/
    `sensitivity_decision_summary`'s own fields."""
    comparison = result.baseline_comparison
    sensitivity = result.sensitivity_decision_summary
    lines = [
        "# Research findings (synthetic)\n\n", RESEARCH_EXPERIMENT_SYNTHETIC_DISCLAIMER, "\n\n",
        f"run_id: `{result.run_id}`\n\n",
        f"Referenced v2 study package run: `{result.referenced_v2_result.run_id}`\n\n",
        f"Compatible alternatives evaluated across {len(result.research_config.load_states)} load state(s): "
        f"{len(result.alternative_summaries)}\n\n",
        "## Best geothermal-only scenario(s) (rank-1 group -- never collapsed per site)\n\n",
        f"{comparison.geothermal_only_best_scenario_ids}\n\n" if comparison.geothermal_only_best_scenario_ids
        else "No rankable scenario (every scenario failed its own HX boundary).\n\n",
        "## Best network-only attachment(s) (fixed reference site/scenario, rank-1 group)\n\n",
        f"{comparison.network_only_best_attachment_ids}\n\n" if comparison.network_only_best_attachment_ids
        else "No rankable attachment for the declared reference scenario.\n\n",
        "## Integrated rank-1 group\n\n",
    ]
    if comparison.integrated_best_alternative_ids:
        lines.append(f"{comparison.integrated_best_alternative_ids}\n\n")
    else:
        lines.append("No computable alternative at all.\n\n")
    lines.append("## Did integration change the site and/or attachment conclusion?\n\n")
    lines.append(f"Interpretation code: `{comparison.interpretation_code.value}`\n\n")
    lines.append(f"{comparison.explanation}\n\n")
    lines.append("## Pareto shortlist (secondary diagnostic)\n\n")
    if result.integrated_decision.pareto_shortlist_alternative_ids:
        for alt_id in result.integrated_decision.pareto_shortlist_alternative_ids:
            lines.append(f"- `{alt_id}`\n")
        lines.append("\n")
    else:
        lines.append("Empty (no feasible/computable alternative).\n\n")
    lines.append("## Robustness classification\n\n")
    lines.append(f"`{sensitivity.robustness_classification.value}` (bounded to the tested range below -- "
                  "never a claim of global or uncertainty-proof robustness)\n\n")
    lines.append(f"{sensitivity.explanation}\n\n")
    lines.append("## Maximum observed rank change per candidate\n\n")
    if sensitivity.candidate_rank_sensitivity:
        lines.append("| alternative_id | base_rank | max_rank_change | became_infeasible_in_any_case | "
                      "restored_to_feasibility_in_any_case |\n|---|---|---|---|---|\n")
        for c in sensitivity.candidate_rank_sensitivity:
            lines.append(
                f"| `{c.alternative_id}` | {c.base_rank if c.base_rank is not None else 'n/a'} | "
                f"{c.max_rank_change if c.max_rank_change is not None else 'n/a'} | "
                f"{c.became_infeasible_in_any_case} | {c.restored_to_feasibility_in_any_case} |\n"
            )
        lines.append("\n")
    else:
        lines.append("No candidates evaluated.\n\n")
    lines.append("## Caveats\n\n")
    horizon = result.research_config.annualization.horizon_hours_per_year
    lines.append(
        "- Synthetic geology and costs: every site, resource scenario, route, design and cost figure here "
        "is explicitly invented for this prototype, never real Wuppertal (or any other real place's) data.\n"
        "- Steady-state PyDoublet boundary: one deterministic doublet coupling result, not an hourly or "
        "transient simulation.\n"
        f"- Represented operating horizon: {horizon:g} h/a -- the load states above are declared to sum "
        "exactly to this figure. This is NOT the 8760 h/a calendar year (a full year of chronological "
        "hours); it is this experiment's own smaller, explicitly declared representative operating regime, "
        "and is never described as a complete 8760-hour chronological simulation.\n"
        "- Geothermal-derating sensitivity is a deterministic economic what-if, not a re-evaluated physical "
        "state: it re-derives economics only from already-computed KPIs and never re-runs pandapipes or the "
        "HX evaluator, so it cannot discover new technical infeasibility on its own; it holds "
        "dh_hydraulic_pumping_power_kw at its base-case value as a documented simplification. It represents "
        "synthetic geothermal-availability uncertainty, never a geological exploration-risk model and never "
        "a new PyDoublet simulation.\n"
        "- No exploration risk: the sensitivity study is a small, explicit, deterministic set of what-if "
        "multipliers, never a probabilistic P10/P50/P90 estimate.\n"
        "- Not a real Wuppertal recommendation: this compares synthetic alternatives against each other; "
        "it never claims a real geological drilling-site or network-connection recommendation.\n"
    )
    return "".join(lines).encode("utf-8")


def write_research_experiment_artifacts(
    result: ResearchExperimentBoundaryResult,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
) -> ResearchExperimentManifestRecord:
    """AUD-style bundle for this module -- the core declared-inputs +
    scientific-payload + audit files every run type in this project writes
    (`_CORE_SCIENTIFIC_FILENAMES`), plus, on a completed run, the full §17-named
    set of derived exports (`_SPEC_NAMED_JSON_FILENAMES`/`_SPEC_NAMED_CSV_FILENAMES`)
    and `research_findings.md`."""
    hash_records: dict[str, ArtifactHashRecord] = {}

    pydoublet_input_bytes = canonical_raw_result_json_bytes(pydoublet_raw_result)
    (output_dir / PYDOUBLET_INPUT_FILENAME).write_bytes(pydoublet_input_bytes)
    hash_records[PYDOUBLET_INPUT_FILENAME] = _hash_record_for_json_bytes(pydoublet_input_bytes)

    config_snapshot_bytes = canonical_raw_result_json_bytes(config)
    (output_dir / CONFIG_SNAPSHOT_FILENAME).write_bytes(config_snapshot_bytes)
    hash_records[CONFIG_SNAPSHOT_FILENAME] = _hash_record_for_json_bytes(config_snapshot_bytes)

    result_bytes = result.model_dump_json(indent=2).encode("utf-8")
    (output_dir / RESEARCH_EXPERIMENT_RESULT_FILENAME).write_bytes(result_bytes)
    hash_records[RESEARCH_EXPERIMENT_RESULT_FILENAME] = _hash_record_for_json_bytes(result_bytes)

    audit_bytes = result.audit.model_dump_json(indent=2).encode("utf-8")
    (output_dir / AUDIT_FILENAME).write_bytes(audit_bytes)
    hash_records[AUDIT_FILENAME] = _hash_record_for_json_bytes(audit_bytes)

    if isinstance(result, ResearchExperimentResult):
        v2_snapshot_bytes = result.referenced_v2_result.model_dump_json(indent=2).encode("utf-8")
        (output_dir / REFERENCED_V2_RESULT_FILENAME).write_bytes(v2_snapshot_bytes)
        hash_records[REFERENCED_V2_RESULT_FILENAME] = _hash_record_for_json_bytes(v2_snapshot_bytes)

        json_renderers = {
            EXPERIMENT_INPUT_FILENAME: render_experiment_input_json,
            JOINT_STUDY_SNAPSHOT_FILENAME: render_joint_study_snapshot_json,
            LOAD_STATES_FILENAME: render_load_states_json,
            LOAD_STATE_RESULTS_FILENAME: render_load_state_results_json,
            ANNUALIZED_INTEGRATED_RESULT_FILENAME: render_annualized_integrated_result_json,
            GEOTHERMAL_ONLY_RESULT_FILENAME: render_geothermal_only_result_json,
            NETWORK_ONLY_RESULT_FILENAME: render_network_only_result_json,
            RESEARCH_COMPARISON_FILENAME: render_research_comparison_json,
            SENSITIVITY_RESULTS_FILENAME: render_sensitivity_results_json,
            OBJECTIVE_POLICY_FILENAME: render_objective_policy_json,
            PARETO_OR_RANKING_FILENAME: render_pareto_or_ranking_json,
        }
        for filename, render in json_renderers.items():
            data = render(result)
            (output_dir / filename).write_bytes(data)
            hash_records[filename] = _hash_record_for_json_bytes(data)

        csv_renderers = {
            ANNUALIZED_ALTERNATIVE_COMPARISON_CSV_FILENAME: render_annualized_alternative_comparison_csv,
            GEOTHERMAL_ONLY_COMPARISON_CSV_FILENAME: render_geothermal_only_comparison_csv,
            NETWORK_ONLY_COMPARISON_CSV_FILENAME: render_network_only_comparison_csv,
            RESEARCH_COMPARISON_CSV_FILENAME: render_research_comparison_csv,
            SENSITIVITY_COMPARISON_CSV_FILENAME: render_sensitivity_comparison_csv,
            SENSITIVITY_RANK_CHANGES_CSV_FILENAME: render_sensitivity_rank_changes_csv,
        }
        for filename, render in csv_renderers.items():
            data = render(result)
            (output_dir / filename).write_bytes(data)
            hash_records[filename] = _hash_record_for_plain_bytes(data)

        findings_bytes = render_research_findings_markdown(result)
        (output_dir / RESEARCH_FINDINGS_MD_FILENAME).write_bytes(findings_bytes)
        hash_records[RESEARCH_FINDINGS_MD_FILENAME] = _hash_record_for_plain_bytes(findings_bytes)

    bundle_scientific_sha256 = canonical_raw_result_sha256(
        {filename: record.scientific_sha256 for filename, record in sorted(hash_records.items())}
    )
    manifest = ResearchExperimentManifestRecord(
        run_id=result.run_id, created_at=datetime.now(timezone.utc), files=hash_records,
        bundle_scientific_sha256=bundle_scientific_sha256,
    )
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest
