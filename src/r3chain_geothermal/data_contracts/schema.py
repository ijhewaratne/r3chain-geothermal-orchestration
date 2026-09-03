"""Real network/GIS/geological study-package data contracts (DATA-001..006,
R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Workstream I).

## Principle (14.1)

This package implements TYPED CONTRACTS, validation (`validation.py`) and
example packages (`fixtures/study_package/`, DATA-008) for real network,
GIS and geological data. It never fabricates, scrapes, infers or
synthesizes a real dataset -- every value in every synthetic example
package is explicitly `classification="synthetic"`, and real-data
ingestion remains blocked (returns typed validation errors, never a
solver run or a recommendation) until an actually-supplied package
validates AND is approved (see `validation.py`/`readiness.py`).

## Scope

These models describe the STUDY PACKAGE'S OWN DATA CONTRACT -- they are
NOT wired into `network/blueprint.py`'s synthetic network builder or
`workflow/core.py`'s orchestrator in this phase. Actual real-data
ingestion (constructing a `NetworkBlueprint` from a validated
`NetworkDataPackage`, for instance) is Phase 8's own external-data-gated
concern; this phase only proves the contract, validator and readiness
report exist and behave correctly (AC-09), consistent with the
project's Phase-6 exit gate ("complete synthetic package validates;
intentionally incomplete real package fails safely; no real data are
fabricated").

## Spatial layers, deliberately metadata-only

`SpatialLayerReference` records a spatial file's DECLARED metadata (path,
CRS, hash, feature count, whether geometry validity was actually
checked) -- it does not parse or validate GeoJSON geometry itself (no new
GIS library dependency was introduced for this prototype; NFR-005 and
CLAUDE.md's dependency discipline). DATA-004's core requirement -- "CRS
must be declared; silent CRS guessing is prohibited" -- is enforced at
this metadata layer: every `SpatialLayerReference.crs` is a REQUIRED,
non-empty field with no default.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DATA_CONTRACTS_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
"""Versioned independently of every other layer's own contract schema."""

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


class DatasetClassification(str, Enum):
    """DATA-002/DATA-008: every study package MUST declare this
    explicitly -- there is no default."""

    SYNTHETIC = "synthetic"
    REAL = "real"


class ApprovalStatus(str, Enum):
    PROVISIONAL = "provisional"
    APPROVED = "approved"
    REJECTED = "rejected"


class DataOwnerReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    organization: str
    contact: str | None = None


class LicenceReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    licence_name: str
    use_restrictions: str


class SpatialLayerReference(BaseModel):
    """DATA-002/DATA-004: one spatial file's declared metadata."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str
    crs: str | None = None
    """A CRS identifier (e.g. "EPSG:25832") -- semantically REQUIRED
    (DATA-004: silent CRS guessing is prohibited), but kept OPTIONAL at
    this type level (like GeothermalScenarioRecord's own provenance
    hashes) so a package missing it can still be CONSTRUCTED and then
    caught uniformly by validate_study_package()'s MISSING_CRS check
    (DATA-007/AC-09), rather than rejected earlier at this model's own
    boundary where the resulting error would be indistinguishable from
    any other malformed-string rejection."""
    byte_sha256: Annotated[str, Field(pattern=_SHA256_HEX_PATTERN)]
    feature_count: int
    geometry_validated: bool
    """Whether this layer's geometry validity was actually checked
    (DATA-004: "geometry validity must be checked") -- False is a valid,
    honestly-reported value; this field exists so that fact is never
    silently assumed."""

    @model_validator(mode="after")
    def _validate(self) -> "SpatialLayerReference":
        if not self.file_path:
            raise ValueError("file_path must not be empty")
        if self.feature_count < 0:
            raise ValueError("feature_count must be >= 0")
        return self


class StudyPackageManifest(BaseModel):
    """DATA-002's required manifest fields."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    schema_version: Literal["1.0.0"] = DATA_CONTRACTS_SCHEMA_VERSION
    title: str
    classification: DatasetClassification
    created_at: datetime
    updated_at: datetime
    data_owners: list[DataOwnerReference]
    licence: LicenceReference
    unit_conventions: dict[str, str]
    approval_status: ApprovalStatus
    file_inventory: dict[str, Annotated[str, Field(pattern=_SHA256_HEX_PATTERN)]]
    """relative file path -> byte_sha256, for EVERY file in the package."""
    spatial_layers: list[SpatialLayerReference] = Field(default_factory=list)
    expected_scenario_hashes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> "StudyPackageManifest":
        errors: list[str] = []
        if not self.study_id:
            errors.append("study_id must not be empty")
        if not self.data_owners:
            errors.append("data_owners must not be empty")
        if self.updated_at < self.created_at:
            errors.append("updated_at must not be before created_at")
        for layer in self.spatial_layers:
            if layer.file_path not in self.file_inventory:
                errors.append(f"spatial_layers entry {layer.file_path!r} is not listed in file_inventory")
            elif self.file_inventory[layer.file_path] != layer.byte_sha256:
                errors.append(f"spatial_layers entry {layer.file_path!r} hash disagrees with file_inventory")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── DATA-003: network requirements ──────────────────────────────────────────

class NetworkSide(str, Enum):
    SUPPLY = "supply"
    RETURN = "return"


class JunctionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    junction_id: str
    x_m: float
    y_m: float
    elevation_m: float
    side: NetworkSide


class PipeRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pipe_id: str
    from_junction: str
    to_junction: str
    length_m: float
    internal_diameter_mm: float
    material: str
    roughness_mm: float
    insulation_u_value_w_per_m2k: float | None = None
    status: Literal["active", "planned", "decommissioned"]


class ControlComponentRecord(BaseModel):
    """DATA-003's "pumps, valves, heat sources and pressure controls" --
    one generic record with a `kind` discriminator rather than four
    exhaustive per-type schemas (judged out of proportion to this
    workstream's contract/validator scope)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: str
    kind: Literal["pump", "valve", "heat_source", "pressure_control"]
    junction_id: str
    parameters: dict[str, float] = Field(default_factory=dict)


class ConsumerRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    consumer_id: str
    substation_id: str
    design_load_kw: float
    return_temperature_behavior: str
    """Free-text description/reference (e.g. "fixed 5K delta-T design",
    or a pointer to a measured return-temperature curve) -- a full
    behavior-curve schema was judged out of proportion to this
    workstream."""


class OperatingLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_pressure_bar_abs: float
    max_pressure_bar_abs: float
    min_temperature_c: float
    max_temperature_c: float

    @model_validator(mode="after")
    def _validate(self) -> "OperatingLimits":
        if self.min_pressure_bar_abs <= 0:
            raise ValueError("min_pressure_bar_abs must be > 0")
        if self.max_pressure_bar_abs <= self.min_pressure_bar_abs:
            raise ValueError("max_pressure_bar_abs must be > min_pressure_bar_abs")
        if self.max_temperature_c <= self.min_temperature_c:
            raise ValueError("max_temperature_c must be > min_temperature_c")
        return self


class DemandProfileDeclaration(BaseModel):
    """DATA-003: "demand profile or explicit static-demo declaration" --
    one of the two must be present, never silently omitted."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["time_series_reference", "static_demo"]
    time_series_reference: str | None = None
    static_demo_note: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "DemandProfileDeclaration":
        if self.mode == "time_series_reference" and not self.time_series_reference:
            errors = "time_series_reference is required when mode=='time_series_reference'"
            raise ValueError(errors)
        if self.mode == "static_demo" and not self.static_demo_note:
            raise ValueError("static_demo_note is required when mode=='static_demo'")
        return self


class NetworkDataPackage(BaseModel):
    """DATA-003's full network-requirements contract."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    junctions: list[JunctionRecord]
    pipes: list[PipeRecord]
    consumers: list[ConsumerRecord]
    controls: list[ControlComponentRecord] = Field(default_factory=list)
    operating_limits: OperatingLimits
    demand_profile: DemandProfileDeclaration
    candidate_tie_in_eligible_junction_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "NetworkDataPackage":
        if not self.junctions:
            raise ValueError("junctions must not be empty")
        if not self.pipes:
            raise ValueError("pipes must not be empty")
        return self


# ── DATA-005: geological scenarios ──────────────────────────────────────────

class GeothermalScenarioRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    site_id: str
    geometry_or_parcel_reference: str
    pydoublet_input_reference: str
    pydoublet_input_sha256: Annotated[str, Field(pattern=_SHA256_HEX_PATTERN)] | None = None
    pydoublet_result_reference: str
    pydoublet_result_sha256: Annotated[str, Field(pattern=_SHA256_HEX_PATTERN)] | None = None
    """Both hashes are OPTIONAL at the type level (unlike, e.g.,
    SpatialLayerReference.byte_sha256) specifically so an incomplete real
    package -- missing exactly this provenance -- can still be
    CONSTRUCTED and then caught by validate_study_package()'s own
    MISSING_PROVENANCE check (DATA-007/AC-09), rather than being
    rejected earlier by this model's own field pattern where the
    resulting error would be indistinguishable from any other malformed-
    string rejection."""
    depth_m: float
    temperature_assumption_c: float
    mass_flow_or_transmissivity_basis: str
    fluid_salinity_note: str | None = None
    reinjection_constraint_c: float
    well_spacing_m: float
    well_trajectory_note: str
    production_pump_requirement_kw: float
    injection_pump_requirement_kw: float
    uncertainty_or_risk_note: str
    calculation_mode: Literal["deterministic", "monte_carlo", "unknown"]
    upstream_commit_or_model_version: str

    @model_validator(mode="after")
    def _validate(self) -> "GeothermalScenarioRecord":
        if self.depth_m <= 0:
            raise ValueError("depth_m must be > 0")
        if self.temperature_assumption_c <= self.reinjection_constraint_c:
            raise ValueError("temperature_assumption_c must exceed reinjection_constraint_c")
        if self.well_spacing_m <= 0:
            raise ValueError("well_spacing_m must be > 0")
        return self


# ── DATA-006: economics and planning data ───────────────────────────────────

class EconomicLineItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line_item_id: str
    category: Literal[
        "land", "drilling", "connection_routing", "road_crossing", "grid_connection",
        "permitting", "exploration", "workover", "decommissioning", "risk", "other",
    ]
    value: float
    currency: str
    price_year: int
    unit_basis: str
    source: str
    approval_status: ApprovalStatus
    uncertainty_range: tuple[float, float] | None = None
    inclusion_note: str

    @model_validator(mode="after")
    def _validate(self) -> "EconomicLineItem":
        if not self.currency:
            raise ValueError("currency must not be empty")
        if not (1900 <= self.price_year <= 2100):
            raise ValueError(f"price_year {self.price_year!r} is not plausible")
        if self.uncertainty_range is not None and self.uncertainty_range[0] > self.uncertainty_range[1]:
            raise ValueError("uncertainty_range must be (low, high) with low <= high")
        return self


# ── Decisions/policy ─────────────────────────────────────────────────────────

class StudyDecisionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ranking_policy: str
    objective_weights: dict[str, float] | None = None


# ── The full package ─────────────────────────────────────────────────────────

class StudyPackage(BaseModel):
    """DATA-001's full study package -- geography layers are represented
    entirely via `manifest.spatial_layers` (module docstring, "Spatial
    layers, deliberately metadata-only")."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: StudyPackageManifest
    network: NetworkDataPackage | None = None
    geothermal_scenarios: list[GeothermalScenarioRecord] = Field(default_factory=list)
    economics: list[EconomicLineItem] = Field(default_factory=list)
    decisions: StudyDecisionPolicy | None = None
