"""OPT-007's extended-mode artifact set for the synthetic joint
optimisation demonstration.

Deliberately a LIGHTER-WEIGHT export than `workflow/artifacts.py`'s own
manifest/hash-audited bundle for the single-scenario workflow: this
writes the six OPT-007-named files (`generated_candidates.json`,
`screened_alternatives.json`, `alternative_comparison.csv`,
`pareto_or_ranking.json`, `recommendation.md`, plus `study_readiness.json`
when a readiness report is supplied) as plain, deterministic files,
without a full byte/scientific-hash manifest. Extending the existing
manifest infrastructure to also cover this extended mode is a reasonable
next step, explicitly NOT implemented here (see
docs/issues/joint-location-optimization.md) -- reported as a scope
decision, not a silent gap. `location_shortlist.geojson` is not produced:
this demonstration has no real spatial coordinate data (OPT-007's own
"when spatial inputs exist" qualifier).

Every file is a pure function of already-computed, already-typed data
(`JointOptimizationResult`, plus the Workstream H `ScreenedCandidate`
list) -- no new computation happens in this module beyond formatting.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ..data_contracts import StudyReadinessReport
from ..network import ScreenedCandidate
from .joint_optimization import JointOptimizationResult

RECOMMENDATION_SYNTHETIC_DISCLAIMER = (
    "This is a SYNTHETIC demonstration: every geothermal scenario, network junction, and "
    "connection candidate here is explicitly invented for this prototype. It contains no real "
    "Wuppertal (or any other real place's) data, and must never be read as a real geological "
    "drilling-site recommendation, a real network-connection recommendation, or a validated "
    "economic result."
)


def render_generated_candidates_json(screened_candidates: list[ScreenedCandidate]) -> bytes:
    payload = [json.loads(sc.model_dump_json()) for sc in sorted(screened_candidates, key=lambda s: s.candidate_id)]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_screened_alternatives_json(result: JointOptimizationResult) -> bytes:
    payload = [
        json.loads(alt.model_dump_json(exclude={"created_at"}))
        for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id)
    ]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_alternative_comparison_csv(result: JointOptimizationResult) -> bytes:
    fieldnames = [
        "alternative_id", "geothermal_scenario_id", "surface_site_id", "connection_candidate_id",
        "route_id", "design_option_id", "operating_policy_id", "feasible", "stage_reached",
        "failure_code", "annualised_cost_total_eur_per_a", "indicative_lcoh_eur_per_mwh",
        "geothermal_injected_heat_kw", "surface_connection_length_m", "in_pareto_shortlist",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for alt in sorted(result.alternatives, key=lambda a: a.identity.alternative_id):
        row = {
            "alternative_id": alt.identity.alternative_id,
            "geothermal_scenario_id": alt.identity.geothermal_scenario_id,
            "surface_site_id": alt.identity.surface_site_id,
            "connection_candidate_id": alt.identity.connection_candidate_id,
            "route_id": alt.identity.route_id,
            "design_option_id": alt.identity.design_option_id,
            "operating_policy_id": alt.identity.operating_policy_id,
            "feasible": alt.feasible,
            "stage_reached": alt.stage_reached.value,
            "failure_code": alt.failure_code or "",
            "annualised_cost_total_eur_per_a": f"{alt.economics.annualised_cost_total_eur_per_a:.6f}" if alt.economics else "",
            "indicative_lcoh_eur_per_mwh": f"{alt.economics.indicative_lcoh_eur_per_kwh * 1000.0:.6f}" if alt.economics else "",
            "geothermal_injected_heat_kw": f"{alt.candidate_result.geothermal_injected_heat_kw:.6f}" if alt.candidate_result else "",
            "surface_connection_length_m": f"{alt.candidate_result.candidate.surface_connection_length_m:.6f}" if alt.candidate_result else "",
            "in_pareto_shortlist": alt.identity.alternative_id in result.pareto_shortlist_alternative_ids,
        }
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def render_pareto_or_ranking_json(result: JointOptimizationResult) -> bytes:
    payload = {
        "objectives_considered": result.objectives_considered,
        "pareto_shortlist_alternative_ids": result.pareto_shortlist_alternative_ids,
        "policy_note": (
            "No approved multi-objective weighting policy exists for this prototype "
            "(decision-register.md) -- a Pareto/non-dominated shortlist is returned, never an "
            "invented weighted ranking (OPT-003)."
        ),
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_study_readiness_json(report: StudyReadinessReport) -> bytes:
    return (report.model_dump_json(indent=2) + "\n").encode("utf-8")


def render_joint_recommendation_markdown(result: JointOptimizationResult) -> bytes:
    lines: list[str] = []
    lines.append("# R3-CHAIN synthetic joint site/connection optimisation demonstration")
    lines.append("")
    lines.append(RECOMMENDATION_SYNTHETIC_DISCLAIMER)
    lines.append("")
    lines.append(
        f"Scenarios evaluated: {', '.join(s.scenario_id for s in result.scenarios)}. "
        f"Alternatives evaluated: {len(result.alternatives)}."
    )
    lines.append("")

    lines.append("## Feasible alternatives (technical gates passed)")
    lines.append("")
    feasible = [a for a in result.alternatives if a.feasible]
    if feasible:
        lines.append("| Alternative | Annualised cost (EUR/a) | Indicative LCOH (EUR/MWh) | In Pareto shortlist |")
        lines.append("|---|---:|---:|:---:|")
        for alt in sorted(feasible, key=lambda a: a.identity.alternative_id):
            in_shortlist = "yes" if alt.identity.alternative_id in result.pareto_shortlist_alternative_ids else "no"
            lines.append(
                f"| `{alt.identity.alternative_id}` | {alt.economics.annualised_cost_total_eur_per_a:,.2f} "
                f"| {alt.economics.indicative_lcoh_eur_per_kwh * 1000.0:.4f} | {in_shortlist} |"
            )
    else:
        lines.append("No alternative was technically feasible.")
    lines.append("")

    lines.append("## Rejected alternatives")
    lines.append("")
    rejected = [a for a in result.alternatives if not a.feasible]
    if rejected:
        lines.append("| Alternative | Stage | Failure code | Message |")
        lines.append("|---|---|---|---|")
        for alt in sorted(rejected, key=lambda a: a.identity.alternative_id):
            lines.append(f"| `{alt.identity.alternative_id}` | {alt.stage_reached.value} | `{alt.failure_code}` | {alt.message} |")
    else:
        lines.append("No alternative was rejected.")
    lines.append("")

    lines.append("## Method and scope")
    lines.append("")
    lines.append(
        "Geological/site suitability (whether a geothermal scenario's own heat-exchanger "
        "coupling boundary is feasible) and network-connection suitability (whether a specific "
        "candidate's independent pandapipes solve passes every technical gate) are evaluated as "
        "SEPARATE, sequential stages -- a rejection at the site stage never reaches the "
        "network-connection stage, and vice versa. Only objectives with actual computed data for "
        "every compared alternative are considered (OPT-003); no weighting policy has been "
        "approved for this prototype, so a Pareto/non-dominated shortlist is returned rather than "
        "a single invented-weight ranking."
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_joint_optimization_bundle(
    result: JointOptimizationResult,
    screened_candidates: list[ScreenedCandidate],
    output_dir: Path,
    *,
    readiness_report: StudyReadinessReport | None = None,
) -> dict[str, Path]:
    """Writes every OPT-007 file this demonstration produces to
    `output_dir` (created if absent) and returns {filename: path}.
    `location_shortlist.geojson` is never written (module docstring)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    files: dict[str, bytes] = {
        "generated_candidates.json": render_generated_candidates_json(screened_candidates),
        "screened_alternatives.json": render_screened_alternatives_json(result),
        "alternative_comparison.csv": render_alternative_comparison_csv(result),
        "pareto_or_ranking.json": render_pareto_or_ranking_json(result),
        "recommendation.md": render_joint_recommendation_markdown(result),
    }
    if readiness_report is not None:
        files["study_readiness.json"] = render_study_readiness_json(readiness_report)

    for filename, content in files.items():
        path = output_dir / filename
        path.write_bytes(content)
        written[filename] = path
    return written
