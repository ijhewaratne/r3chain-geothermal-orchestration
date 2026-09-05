"""Artifact bundle for the research-experiment layer (Phase 7, R3-CHAIN Final
Research-Alignment Implementation Specification, RA-ART).

Follows `workflow.joint_workflow_v2`'s own hashing/manifest pattern exactly
(`ArtifactHashRecord`'s byte/scientific-hash split, `normalize_for_scientific_hash()`
for JSON files, a `manifest.json` that never hashes itself). Scoped narrower
than the v2 bundle's own full site-route SVG map -- this layer's own
contribution is the load-state/annualized/comparison story, not connection
geometry (the referenced v2 run's own bundle already covers that map)."""
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
ALTERNATIVE_ANNUALIZED_COMPARISON_CSV_FILENAME = "alternative_annualized_comparison.csv"
RESEARCH_EXPERIMENT_REPORT_MD_FILENAME = "research_experiment_report.md"
MANIFEST_FILENAME = "manifest.json"

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


def render_alternative_annualized_comparison_csv(result: ResearchExperimentResult) -> bytes:
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


def render_research_experiment_report_markdown(result: ResearchExperimentResult) -> bytes:
    lines = [
        "# Research-experiment report (synthetic)\n\n", RESEARCH_EXPERIMENT_SYNTHETIC_DISCLAIMER, "\n\n",
        f"run_id: `{result.run_id}`\n\n",
        f"Referenced v2 study package run: `{result.referenced_v2_result.run_id}`\n\n",
        f"Compatible alternatives evaluated across {len(result.research_config.load_states)} load state(s): "
        f"{len(result.alternative_summaries)}\n\n",
        "## Integrated decision\n\n",
    ]
    if result.integrated_decision.preferred_alternative_id:
        lines.append(f"Preferred alternative: `{result.integrated_decision.preferred_alternative_id}`\n\n")
    else:
        lines.append("No single unique preferred alternative (materially tied, or none computable).\n\n")
    lines.append("## Cross-baseline comparison\n\n")
    lines.append(f"Interpretation: `{result.baseline_comparison.interpretation_code.value}`\n\n")
    lines.append(f"{result.baseline_comparison.explanation}\n\n")
    lines.append("## Sensitivity / robustness\n\n")
    lines.append(f"Classification: `{result.sensitivity_decision_summary.robustness_classification.value}`\n\n")
    lines.append(f"{result.sensitivity_decision_summary.explanation}\n\n")
    return "".join(lines).encode("utf-8")


def write_research_experiment_artifacts(
    result: ResearchExperimentBoundaryResult,
    pydoublet_raw_result: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
) -> ResearchExperimentManifestRecord:
    """AUD-style bundle for this module -- the same declared-inputs +
    scientific-payload + audit core every run type in this project writes
    (`_CORE_SCIENTIFIC_FILENAMES`), plus this layer's own comparison CSV
    and markdown report on a successful run."""
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

        csv_bytes = render_alternative_annualized_comparison_csv(result)
        (output_dir / ALTERNATIVE_ANNUALIZED_COMPARISON_CSV_FILENAME).write_bytes(csv_bytes)
        hash_records[ALTERNATIVE_ANNUALIZED_COMPARISON_CSV_FILENAME] = _hash_record_for_plain_bytes(csv_bytes)

        report_bytes = render_research_experiment_report_markdown(result)
        (output_dir / RESEARCH_EXPERIMENT_REPORT_MD_FILENAME).write_bytes(report_bytes)
        hash_records[RESEARCH_EXPERIMENT_REPORT_MD_FILENAME] = _hash_record_for_plain_bytes(report_bytes)

    bundle_scientific_sha256 = canonical_raw_result_sha256(
        {filename: record.scientific_sha256 for filename, record in sorted(hash_records.items())}
    )
    manifest = ResearchExperimentManifestRecord(
        run_id=result.run_id, created_at=datetime.now(timezone.utc), files=hash_records,
        bundle_scientific_sha256=bundle_scientific_sha256,
    )
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest
