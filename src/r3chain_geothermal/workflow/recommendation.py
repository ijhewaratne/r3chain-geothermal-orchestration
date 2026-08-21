"""Deterministic `recommendation.md` rendering (T2.4B2).

Rendered from a FIXED Python string template over an already-computed
`WorkflowResult` -- never free-text-generated, never an LLM call. Every
number/statement below is read directly off already-typed, already-
validated fields (T2.3/T2.4A's own results); this module performs no
new computation of its own beyond string formatting and ordering.
"""
from __future__ import annotations

from .core import WorkflowResult

MINIMUM_AUXILIARY_MARGIN_CAVEAT = (
    "The geothermal-injection curtailment margin (`minimum_auxiliary_circulation_fraction`) "
    "is a documented numerical-stability assumption, not a physical operating choice -- it "
    "exists for two independently-discovered reasons: (1) it keeps the main plant pump's "
    "converged net mass flow clear of pandapipes 0.14.0's zero-tolerance circulation-pump "
    "direction-change check; (2) it keeps the network's thermal field sufficiently anchored "
    "by the main pump's own design-temperature flow that consumer_1 does not breach the "
    "consumer supply-temperature-drop gate (a temperature-anchoring effect). See "
    "`docs/technical-observations/pandapipes-circulation-pump-direction-check.md` for the "
    "full evidence and measured boundary."
)


def _format_eur_per_mwh(eur_per_kwh: float) -> str:
    return f"{eur_per_kwh * 1000.0:.4f} EUR/MWh"


def render_recommendation_markdown(result: WorkflowResult) -> bytes:
    """Renders `recommendation.md`'s exact bytes -- deterministic (no
    created_at anywhere in this file; byte_sha256 == scientific_sha256
    for it, artifacts.py's own convention)."""
    lines: list[str] = []
    lines.append("# R3-CHAIN geothermal candidate recommendation")
    lines.append("")
    lines.append(
        "This report evaluates network CONNECTION locations for one already-computed "
        "geothermal doublet result -- it is **not**, and must never be read as, a "
        "geological or drilling-location recommendation."
    )
    lines.append("")
    lines.append(f"Run ID: `{result.run_id}`")
    lines.append("")

    lines.append("## Result")
    lines.append("")
    if result.ranking.ranked:
        winner = result.ranking.ranked[0]
        lines.append(
            f"**{winner.candidate_id} is preferred** for this worked case -- rank 1 of "
            f"{len(result.ranking.ranked)} feasible candidate(s), lowest indicative LCOH at "
            f"{_format_eur_per_mwh(winner.economics.indicative_lcoh_eur_per_kwh)}."
        )
        lines.append("")
        lines.append("| Rank | Candidate | Indicative LCOH | Total annualised cost |")
        lines.append("|---:|---|---:|---:|")
        for entry in result.ranking.ranked:
            lines.append(
                f"| {entry.rank} | {entry.candidate_id} | "
                f"{_format_eur_per_mwh(entry.economics.indicative_lcoh_eur_per_kwh)} | "
                f"{entry.economics.annualised_cost_total_eur_per_a:,.2f} EUR/a |"
            )
    else:
        lines.append(
            "**No candidate is feasible for this worked case.** No recommendation is made -- "
            "a completed evaluation with zero feasible candidates is a valid, honest result, "
            "not an error to be papered over with an invented ranking."
        )

    if result.ranking.infeasible:
        lines.append("")
        lines.append("### Rejected candidates")
        lines.append("")
        lines.append("| Candidate | Rejection code | Reason |")
        lines.append("|---|---|---|")
        for entry in result.ranking.infeasible:
            lines.append(f"| {entry.candidate_id} | `{entry.failure_code.value}` | {entry.message} |")

    lines.append("")
    lines.append("## Method and scope")
    lines.append("")
    lines.append(
        "Hard technical feasibility gates (convergence, consumer temperature delivery, "
        "absolute pressure, pipe velocity, mass balance, physical energy balance, and the "
        "geothermal-injection hydraulic check) were applied to every candidate BEFORE any "
        "economic figure was computed -- an infeasible candidate is never assigned a cost, "
        "an LCOH, or a rank (feasibility-first ranking, plan §12.3)."
    )
    lines.append("")
    lines.append(result.ranking.shared_capex_statement)

    lines.append("")
    lines.append("## Provisional assumptions")
    lines.append("")
    lines.append(
        "The synthetic network geometry (trunk/branch layout, candidate connection lengths) "
        "and every economic value (CAPEX, O&M fraction, interest rate, electricity/auxiliary "
        "heat prices, DH pump efficiency) are documented `demo_assumption` placeholders "
        "(`config/demo_assumptions.json`), not validated engineering or market facts -- see "
        "that file's own `_status`/`source_status` fields for the exact provenance of each."
    )
    lines.append("")
    lines.append(MINIMUM_AUXILIARY_MARGIN_CAVEAT)
    lines.append("")
    lines.append(result.ranking.baseline_economics.scope_caveat)

    return ("\n".join(lines) + "\n").encode("utf-8")
