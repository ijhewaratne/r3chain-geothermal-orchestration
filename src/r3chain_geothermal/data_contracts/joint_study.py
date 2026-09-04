"""Corrected joint site/connection study-package contracts (v2.0.0,
docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 1, S7/TERM/DATA/GOV-015..019).

## Relationship to the existing v1.0.0 StudyPackage (schema.py)

This is a NEW, PARALLEL contract -- not a replacement for `schema.py`'s
`StudyPackage` (used by `readiness.py`'s real-data gate for the canonical
single-scenario workflow). `JointStudyPackage` describes a structurally
different thing: multiple synthetic/real geothermal SITES, each with its
own linked resource scenarios, and site-specific connection routes to a
district-heating network -- fields `schema.py`'s `StudyPackage` has no
concept of at all (ARCH-002: contracts stay independently testable).

## What Phase 1 delivers, and what it deliberately does not

Phase 1 implements the TYPED CONTRACTS (S7.1-7.17), their structural/
relationship validation (DATA-001..022, so far as checkable at the
schema level -- before any file is resolved or any route generated),
and active-dimension reporting (TERM-003..005, AC-J02). It does NOT wire
this contract into any running enumeration, evaluation, MCP tool, or the
existing `data_contracts.readiness` real-mode gate -- those are Phase 2+
integration work. `workflow/joint_optimization.py` (the v1 module) is
untouched; nothing here changes its behaviour.

## S7.9's SiteConnectionRoute is a GENERATED type, not a package field

S7.1's own field list has no `routes` key -- routes are produced by
site-origin-aware route generation (S9, ROUTE-001) from `routing_policy`
+ `sites` + `network_attachments`, a Phase-2 concern
(`network/site_routing.py`). `SiteConnectionRoute` is still defined here
(S7.9 requires the type), and its own self-consistency (declared length
vs geometry-derived length) is validated at construction, but
route-to-site/attachment relationship checks live in the standalone
`validate_route_against_site_and_attachment()` below, not inside
`validate_joint_study_package()` -- there is nothing to check a route
against until Phase 2 actually generates one.
"""
from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .schema import DatasetClassification

JOINT_STUDY_CONTRACT_SCHEMA_VERSION: Literal["2.0.0"] = "2.0.0"
"""Versioned independently of every other layer's own contract schema --
deliberately 2.0.0, not 1.0.0: this is a structurally distinct contract
from data_contracts.schema's own 1.0.0 StudyPackage, not a revision of
it."""

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_Sha256Hex = Annotated[str, Field(pattern=_SHA256_HEX_PATTERN)]

_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
"""allow_inf_nan=False on every model in this module structurally
satisfies DATA-009 ("forbid non-finite numeric values") for every float
field without a separate manual scan."""


def _is_safe_package_relative_path(path: str) -> bool:
    """DATA-022: resolve and validate every package-relative path against
    the package root before opening it; reject absolute paths and
    traversal. Deliberately conservative -- only a clean set of
    non-empty, non-'..' path segments passes."""
    if not path:
        return False
    normalized = path.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    if len(normalized) >= 2 and normalized[1] == ":":  # e.g. "C:/..." drive-letter absolute path
        return False
    segments = normalized.split("/")
    return all(segment not in ("", "..") for segment in segments)


# ── S7.2: coordinate reference and the coordinate discriminated union ───────

class SyntheticCoordinate(BaseModel):
    model_config = _MODEL_CONFIG
    kind: Literal["synthetic_cartesian"] = "synthetic_cartesian"
    x_m: float
    y_m: float


class ProjectedCoordinate(BaseModel):
    model_config = _MODEL_CONFIG
    kind: Literal["projected"] = "projected"
    easting_m: float
    northing_m: float


class GeographicCoordinate(BaseModel):
    model_config = _MODEL_CONFIG
    kind: Literal["geographic"] = "geographic"
    longitude_deg: float
    latitude_deg: float

    @model_validator(mode="after")
    def _validate(self) -> "GeographicCoordinate":
        if not (-180.0 <= self.longitude_deg <= 180.0):
            raise ValueError(f"longitude_deg={self.longitude_deg!r} out of [-180, 180]")
        if not (-90.0 <= self.latitude_deg <= 90.0):
            raise ValueError(f"latitude_deg={self.latitude_deg!r} out of [-90, 90]")
        return self


Coordinate = Annotated[
    Union[SyntheticCoordinate, ProjectedCoordinate, GeographicCoordinate],
    Field(discriminator="kind"),
]
"""Same discriminated-union idiom as readiness.py's
RealDataReadinessBoundaryResult (Annotated[Union[...],
Field(discriminator=...)]). DATA-012: a synthetic_cartesian coordinate is
never converted into latitude/longitude, and nothing here performs such
a conversion."""
_coordinate_adapter: TypeAdapter = TypeAdapter(Coordinate)


def parse_coordinate_json(json_str: str) -> SyntheticCoordinate | ProjectedCoordinate | GeographicCoordinate:
    return _coordinate_adapter.validate_json(json_str)


def _planar_xy(coord: SyntheticCoordinate | ProjectedCoordinate | GeographicCoordinate) -> tuple[float, float]:
    if isinstance(coord, SyntheticCoordinate):
        return coord.x_m, coord.y_m
    if isinstance(coord, ProjectedCoordinate):
        return coord.easting_m, coord.northing_m
    raise ValueError(
        "a geographic (longitude/latitude) coordinate has no Euclidean planar position in metres -- "
        "no geodesic-distance formula is implemented in this prototype"
    )


def compute_polyline_length_m(
    geometry: list[SyntheticCoordinate | ProjectedCoordinate | GeographicCoordinate],
) -> float:
    """S9's formula: sum of consecutive Euclidean distances. Valid only
    for planar, metre-based coordinates (synthetic_cartesian/projected)
    -- a geographic (lon/lat) polyline's length is NOT computed here
    (GOV-012: never silently substitute a wrong number); the caller sees
    a ValueError instead of a bogus Euclidean distance over degrees."""
    if len(geometry) < 2:
        raise ValueError("route_geometry must contain at least two points")
    total = 0.0
    for a, b in zip(geometry, geometry[1:]):
        ax, ay = _planar_xy(a)
        bx, by = _planar_xy(b)
        total += math.hypot(bx - ax, by - ay)
    return total


class CoordinateReference(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal["synthetic_cartesian", "epsg"]
    identifier: str
    horizontal_unit: Literal["m", "degree"]
    axis_order: list[str]
    epsg_code: int | None = None

    @model_validator(mode="after")
    def _validate(self) -> "CoordinateReference":
        errors: list[str] = []
        if not self.identifier:
            errors.append("identifier must not be empty")
        if not self.axis_order:
            errors.append("axis_order must not be empty")
        if self.kind == "epsg" and self.epsg_code is None:
            errors.append("epsg_code is required when kind=='epsg' (real mode requires an explicit EPSG code)")
        if self.kind == "synthetic_cartesian" and self.epsg_code is not None:
            errors.append("epsg_code must be null when kind=='synthetic_cartesian'")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Shared status/kind enums (reused across several S7 records) ─────────────

class AssumptionStatus(str, Enum):
    SYNTHETIC_ASSUMPTION = "synthetic_assumption"
    APPROVED_SOURCE = "approved_source"


class SiteAvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


class AttachmentEligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


class RouteKind(str, Enum):
    SYNTHETIC_POLYLINE = "synthetic_polyline"
    NETWORK_GRAPH = "network_graph"
    EXTERNAL_GIS = "external_gis"


class RouteScreeningStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RouteRejectionCode(str, Enum):
    """ROUTE-008/009: typed, stable route-screening rejection vocabulary
    -- every screened-out route is preserved with one of these, never
    silently dropped (same spirit as
    network/candidate_generation.py::CandidateGenerationFailureReason)."""

    SITE_UNAVAILABLE = "SITE_UNAVAILABLE"
    ATTACHMENT_INELIGIBLE = "ATTACHMENT_INELIGIBLE"
    EXCLUSION_CONFLICT = "EXCLUSION_CONFLICT"
    LENGTH_EXCEEDS_LIMIT = "LENGTH_EXCEEDS_LIMIT"
    ROUTE_KIND_UNSUPPORTED = "ROUTE_KIND_UNSUPPORTED"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"


class DecisionPolicyMode(str, Enum):
    PARETO_ONLY = "pareto_only"
    PRIMARY_OBJECTIVE_RANKING = "primary_objective_ranking"


class ObjectiveDirection(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class ResourceInputSourceKind(str, Enum):
    PRIMARY_RUNTIME_INPUT = "primary_runtime_input"
    PACKAGE_RELATIVE_FILE = "package_relative_file"


class WellGeometryStatus(str, Enum):
    ABSENT = "absent"
    SYNTHETIC_ASSUMPTION = "synthetic_assumption"
    APPROVED_SOURCE = "approved_source"


class DataStatus(str, Enum):
    ABSENT = "absent"
    SYNTHETIC_ASSUMPTION = "synthetic_assumption"
    APPROVED_SOURCE = "approved_source"


class TemporalBasis(str, Enum):
    LIFETIME_AVERAGE_STEADY = "lifetime_average_steady"
    REPRESENTATIVE_STEADY_STATE = "representative_steady_state"


class ExclusionAppliesTo(str, Enum):
    SITES = "sites"
    ROUTES = "routes"
    BOTH = "both"


class ShortfallMode(str, Enum):
    AUXILIARY = "auxiliary"
    STRICT = "strict"


class NetworkSourceKind(str, Enum):
    COMMITTED_BLUEPRINT = "committed_blueprint"
    APPROVED_DATASET = "approved_dataset"


class StudyApprovalStatus(str, Enum):
    """Distinct from data_contracts.schema.ApprovalStatus (a different
    three-value vocabulary for the existing v1.0.0 StudyPackage) --
    S7.17's own named values."""

    SYNTHETIC_DEMO_APPROVED = "synthetic_demo_approved"
    REAL_STUDY_APPROVED = "real_study_approved"
    NOT_APPROVED = "not_approved"


# ── S7.3: SurfaceSite ────────────────────────────────────────────────────────

class SurfaceSite(BaseModel):
    model_config = _MODEL_CONFIG

    site_id: str
    label: str
    classification: DatasetClassification
    coordinate: Coordinate
    elevation_m: float | None = None
    availability_status: SiteAvailabilityStatus
    exclusion_reason: str | None = None
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "SurfaceSite":
        errors: list[str] = []
        if not self.site_id:
            errors.append("site_id must not be empty")
        if not self.label:
            errors.append("label must not be empty")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if self.availability_status == SiteAvailabilityStatus.EXCLUDED and not self.exclusion_reason:
            errors.append("exclusion_reason is required when availability_status=='excluded'")
        if self.classification == DatasetClassification.SYNTHETIC and not isinstance(self.coordinate, SyntheticCoordinate):
            errors.append("a synthetic site must use SyntheticCoordinate, never a projected/geographic coordinate")
        if self.classification == DatasetClassification.REAL and isinstance(self.coordinate, SyntheticCoordinate):
            errors.append("a real site must use a projected or geographic coordinate, never SyntheticCoordinate")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.4: ResourceInputReference ─────────────────────────────────────────────

class ResourceInputReference(BaseModel):
    model_config = _MODEL_CONFIG

    resource_input_id: str
    source_kind: ResourceInputSourceKind
    package_relative_path: str | None = None
    expected_raw_sha256: _Sha256Hex
    expected_file_byte_sha256: _Sha256Hex | None = None
    provenance_reference: str
    classification: DatasetClassification

    @model_validator(mode="after")
    def _validate(self) -> "ResourceInputReference":
        errors: list[str] = []
        if not self.resource_input_id:
            errors.append("resource_input_id must not be empty")
        if not self.provenance_reference:
            errors.append("provenance_reference must not be empty")
        if self.source_kind == ResourceInputSourceKind.PACKAGE_RELATIVE_FILE:
            if not self.package_relative_path:
                errors.append("package_relative_path is required when source_kind=='package_relative_file'")
            elif not _is_safe_package_relative_path(self.package_relative_path):
                errors.append(f"package_relative_path {self.package_relative_path!r} is not a safe package-relative path (DATA-022)")
            if self.expected_file_byte_sha256 is None:
                errors.append("expected_file_byte_sha256 is required when source_kind=='package_relative_file' (DATA-021)")
        if self.source_kind == ResourceInputSourceKind.PRIMARY_RUNTIME_INPUT and self.package_relative_path is not None:
            errors.append("package_relative_path must be null when source_kind=='primary_runtime_input'")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.6: GeologicalMetadata ──────────────────────────────────────────────────

class GeologicalMetadata(BaseModel):
    """Every field optional and nullable by design -- S7.6: 'Missing
    fields remain null. Do not fabricate values to populate the
    schema.'"""
    model_config = _MODEL_CONFIG

    target_depth_m: float | None = None
    reservoir_temperature_c: float | None = None
    transmissivity_m2_s: float | None = None
    expected_mass_flow_kg_s: float | None = None
    pressure_drawdown_bar: float | None = None
    producer_injector_subsurface_separation_m: float | None = None
    resource_location_reference: str | None = None
    well_geometry_status: WellGeometryStatus = WellGeometryStatus.ABSENT
    data_status: DataStatus = DataStatus.ABSENT
    source_reference: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "GeologicalMetadata":
        errors: list[str] = []
        if self.target_depth_m is not None and self.target_depth_m <= 0:
            errors.append("target_depth_m must be > 0 when set")
        if self.transmissivity_m2_s is not None and self.transmissivity_m2_s <= 0:
            errors.append("transmissivity_m2_s must be > 0 when set")
        if self.expected_mass_flow_kg_s is not None and self.expected_mass_flow_kg_s < 0:
            errors.append("expected_mass_flow_kg_s must be >= 0 when set")
        if self.pressure_drawdown_bar is not None and self.pressure_drawdown_bar < 0:
            errors.append("pressure_drawdown_bar must be >= 0 when set")
        if self.producer_injector_subsurface_separation_m is not None and self.producer_injector_subsurface_separation_m < 0:
            errors.append("producer_injector_subsurface_separation_m must be >= 0 when set")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── Synthetic derivation record (S8.2, TERM-008, ECON-001) ──────────────────

class SyntheticDerivationFieldChange(BaseModel):
    model_config = _MODEL_CONFIG

    field_name: str
    original_value: float
    transformed_value: float
    transformation_formula: str
    is_recomputed_consequence: bool = False
    """True for a field that changes ONLY as a mechanical consequence of
    another declared perturbation (e.g. raw_geothermal_thermal_power_kw
    recomputed from a perturbed mass flow/temperature via the SAME
    energy-consistency formula T1.5B's own check uses) rather than being
    independently set."""

    @model_validator(mode="after")
    def _validate(self) -> "SyntheticDerivationFieldChange":
        errors: list[str] = []
        if not self.field_name:
            errors.append("field_name must not be empty")
        if not self.transformation_formula:
            errors.append("transformation_formula must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class SyntheticDerivation(BaseModel):
    """S8.2's synthetic-derivation record: what the source fixture was
    transformed FROM and TO, why, and by whom/when -- never a hidden
    hard-coded perturbation (TERM-008, ECON-001). Field name is
    `doublet_capex_multiplier`, per TERM-008's explicit rename ("An
    aggregate multiplier shall be named doublet_capex_multiplier") --
    workflow/joint_optimization.py's own v1 field
    (`GeothermalSiteScenario.drilling_capex_multiplier`) keeps its old
    name unchanged there (that module is untouched in this phase); this
    is the corrected v2 name."""
    model_config = _MODEL_CONFIG

    source_fixture_sha256: _Sha256Hex
    field_changes: list[SyntheticDerivationFieldChange]
    doublet_capex_multiplier: float = Field(gt=0)
    rationale: str
    assumption_status: Literal[AssumptionStatus.SYNTHETIC_ASSUMPTION] = AssumptionStatus.SYNTHETIC_ASSUMPTION
    author_or_decision_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "SyntheticDerivation":
        errors: list[str] = []
        if not self.field_changes:
            errors.append("field_changes must not be empty")
        if not self.rationale:
            errors.append("rationale must not be empty")
        if not self.author_or_decision_reference:
            errors.append("author_or_decision_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.7: SiteEconomicInputs ──────────────────────────────────────────────────

class SiteEconomicInputs(BaseModel):
    model_config = _MODEL_CONFIG

    doublet_capex_eur: float | None = None
    drilling_producer_well_capex_eur: float | None = None
    drilling_injector_well_capex_eur: float | None = None
    well_completion_capex_eur: float | None = None
    surface_plant_capex_eur: float | None = None
    contingency_capex_eur: float | None = None
    price_year: int | None = None
    currency: Literal["EUR"] = "EUR"
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "SiteEconomicInputs":
        errors: list[str] = []
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        component_fields = {
            "drilling_producer_well_capex_eur": self.drilling_producer_well_capex_eur,
            "drilling_injector_well_capex_eur": self.drilling_injector_well_capex_eur,
            "well_completion_capex_eur": self.well_completion_capex_eur,
            "surface_plant_capex_eur": self.surface_plant_capex_eur,
            "contingency_capex_eur": self.contingency_capex_eur,
        }
        has_aggregate = self.doublet_capex_eur is not None
        has_any_component = any(v is not None for v in component_fields.values())
        has_every_component = all(v is not None for v in component_fields.values())
        if has_aggregate and has_any_component:
            errors.append(
                "doublet_capex_eur (aggregate) and a component CAPEX field are both set -- use EITHER the "
                "aggregate OR a complete non-overlapping breakdown, never both (ECON-014)"
            )
        if has_any_component and not has_every_component:
            errors.append("a partial component CAPEX breakdown is not allowed -- supply every component field or none")
        for name, value in {"doublet_capex_eur": self.doublet_capex_eur, **component_fields}.items():
            if value is not None and value < 0:
                errors.append(f"{name}={value!r} must be >= 0")
        if self.price_year is not None and not (1900 <= self.price_year <= 2100):
            errors.append(f"price_year {self.price_year!r} is not plausible")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.5: GeothermalResourceScenario ──────────────────────────────────────────

class GeothermalResourceScenario(BaseModel):
    model_config = _MODEL_CONFIG

    scenario_id: str
    site_id: str
    scenario_label: str
    classification: DatasetClassification
    resource_input_id: str
    temporal_basis: TemporalBasis
    probability_label: str | None = None
    probability: float | None = None
    geological_metadata: GeologicalMetadata
    economic_inputs: SiteEconomicInputs
    derivation: SyntheticDerivation | None = None

    @model_validator(mode="after")
    def _validate(self) -> "GeothermalResourceScenario":
        errors: list[str] = []
        if not self.scenario_id:
            errors.append("scenario_id must not be empty")
        if not self.site_id:
            errors.append("site_id must not be empty")
        if not self.scenario_label:
            errors.append("scenario_label must not be empty")
        if not self.resource_input_id:
            errors.append("resource_input_id must not be empty")
        if self.probability is not None and not (0.0 <= self.probability <= 1.0):
            errors.append("probability must be in [0, 1] when set")
        if self.probability is not None and self.probability_label is None:
            errors.append("probability_label is required whenever probability is set -- no invented probabilities without a sourced label")
        if self.derivation is not None and self.classification != DatasetClassification.SYNTHETIC:
            errors.append("a non-null derivation is only allowed for a synthetic-classified scenario (TEST-008: real scenario cannot use a synthetic multiplier)")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.8: NetworkAttachment ────────────────────────────────────────────────────

class NetworkAttachment(BaseModel):
    """A network DESTINATION only -- it must not embed a site, route,
    pipe design or operating policy (S7.8)."""
    model_config = _MODEL_CONFIG

    attachment_id: str
    supply_junction_id: str
    return_junction_id: str
    pressure_zone_id: str
    eligibility_status: AttachmentEligibilityStatus
    exclusion_reason: str | None = None
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "NetworkAttachment":
        errors: list[str] = []
        if not self.attachment_id:
            errors.append("attachment_id must not be empty")
        if not self.supply_junction_id:
            errors.append("supply_junction_id must not be empty")
        if not self.return_junction_id:
            errors.append("return_junction_id must not be empty")
        if not self.pressure_zone_id:
            errors.append("pressure_zone_id must not be empty")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if self.eligibility_status == AttachmentEligibilityStatus.EXCLUDED and not self.exclusion_reason:
            errors.append("exclusion_reason is required when eligibility_status=='excluded'")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.9: SiteConnectionRoute (a GENERATED type -- module docstring) ────────

class SiteConnectionRoute(BaseModel):
    model_config = _MODEL_CONFIG

    route_id: str
    site_id: str
    attachment_id: str
    route_kind: RouteKind
    route_geometry: list[Coordinate]
    paired_trench_length_m: float
    supply_pipe_length_m: float
    return_pipe_length_m: float
    screening_status: RouteScreeningStatus
    rejection_code: RouteRejectionCode | None = None
    rejection_detail: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "SiteConnectionRoute":
        errors: list[str] = []
        if not self.route_id:
            errors.append("route_id must not be empty")
        if not self.site_id:
            errors.append("site_id must not be empty")
        if not self.attachment_id:
            errors.append("attachment_id must not be empty")
        if self.paired_trench_length_m < 0:
            errors.append("paired_trench_length_m must be >= 0")
        if self.supply_pipe_length_m < 0:
            errors.append("supply_pipe_length_m must be >= 0")
        if self.return_pipe_length_m < 0:
            errors.append("return_pipe_length_m must be >= 0")

        if self.screening_status == RouteScreeningStatus.REJECTED:
            if self.rejection_code is None:
                errors.append("rejection_code is required when screening_status=='rejected'")
            if not self.rejection_detail:
                errors.append("rejection_detail is required when screening_status=='rejected'")
        else:
            if self.rejection_code is not None:
                errors.append("rejection_code must be null when screening_status=='accepted'")

        if self.route_kind == RouteKind.SYNTHETIC_POLYLINE and self.screening_status == RouteScreeningStatus.ACCEPTED:
            try:
                geometry_length = compute_polyline_length_m(self.route_geometry)
            except ValueError as exc:
                errors.append(f"route_geometry: {exc}")
            else:
                # ROUTE-005/S9: pandapipes and economics must consume the SAME
                # route-length record -- never a separate "economic" length
                # that silently disagrees with simulated geometry.
                if not math.isclose(geometry_length, self.paired_trench_length_m, rel_tol=1e-6, abs_tol=1e-6):
                    errors.append(
                        f"paired_trench_length_m={self.paired_trench_length_m!r} does not match the length "
                        f"derived from route_geometry ({geometry_length!r} m)"
                    )
        elif self.route_kind in (RouteKind.NETWORK_GRAPH, RouteKind.EXTERNAL_GIS):
            errors.append(
                f"route_kind={self.route_kind.value!r} is not implemented in this prototype (ROUTE-010) -- "
                "only synthetic_polyline routes may be constructed as accepted"
            )

        if errors:
            raise ValueError("; ".join(errors))
        return self


def validate_route_against_site_and_attachment(
    route: SiteConnectionRoute, site: SurfaceSite, attachment: "NetworkAttachment",
) -> list["JointStudyFieldError"]:
    """DATA-004/005, ROUTE-003/004: a route's declared site_id/
    attachment_id must match the site/attachment it was generated for,
    and (for synthetic_cartesian geometry) its first point must coincide
    with the site's own coordinate. Standalone, not part of
    validate_joint_study_package() -- routes are a GENERATED output
    (module docstring), not a JointStudyPackage field, so there is
    nothing to check a route against until a caller (Phase 2's route
    generator) actually produces one."""
    errors: list[JointStudyFieldError] = []
    if route.site_id != site.site_id:
        errors.append(JointStudyFieldError(
            field_path="route.site_id", error_code=JointStudyErrorCode.ROUTE_SITE_MISMATCH,
            message=f"route {route.route_id!r} site_id={route.site_id!r} does not match site {site.site_id!r}",
        ))
    if route.attachment_id != attachment.attachment_id:
        errors.append(JointStudyFieldError(
            field_path="route.attachment_id", error_code=JointStudyErrorCode.ROUTE_ATTACHMENT_MISMATCH,
            message=f"route {route.route_id!r} attachment_id={route.attachment_id!r} does not match attachment {attachment.attachment_id!r}",
        ))
    if (
        route.route_geometry
        and isinstance(site.coordinate, SyntheticCoordinate)
        and isinstance(route.route_geometry[0], SyntheticCoordinate)
        and (route.route_geometry[0].x_m, route.route_geometry[0].y_m) != (site.coordinate.x_m, site.coordinate.y_m)
    ):
        errors.append(JointStudyFieldError(
            field_path="route.route_geometry[0]", error_code=JointStudyErrorCode.ROUTE_SITE_MISMATCH,
            message=f"route {route.route_id!r} geometry does not start at site {site.site_id!r}'s own coordinate",
        ))
    return errors


# ── S7.10: ConnectionDesignOption ─────────────────────────────────────────────

class ConnectionDesignOption(BaseModel):
    model_config = _MODEL_CONFIG

    design_option_id: str
    connection_pipe_inner_diameter_mm: float
    pipe_roughness_mm: float
    heat_transfer_coefficient_w_m2_k: float | None = None
    capex_eur_per_paired_trench_m: float
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "ConnectionDesignOption":
        errors: list[str] = []
        if not self.design_option_id:
            errors.append("design_option_id must not be empty")
        if self.connection_pipe_inner_diameter_mm <= 0:
            errors.append("connection_pipe_inner_diameter_mm must be > 0")
        if self.pipe_roughness_mm < 0:
            errors.append("pipe_roughness_mm must be >= 0")
        if self.heat_transfer_coefficient_w_m2_k is not None and self.heat_transfer_coefficient_w_m2_k < 0:
            errors.append("heat_transfer_coefficient_w_m2_k must be >= 0")
        if self.capex_eur_per_paired_trench_m < 0:
            errors.append("capex_eur_per_paired_trench_m must be >= 0")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.11: AlternativeIdentity (v2) ───────────────────────────────────────────

class AlternativeIdentity(BaseModel):
    """S7.11: the corrected six-typed-FK decision-entity identity.
    `alternative_id` is DERIVED deterministically from these six fields
    in this fixed, documented order -- nothing anywhere splits it back
    apart (ARCH-006). This is the v2 counterpart of
    workflow/joint_optimization.py's own (untouched) v1
    `AlternativeIdentity`, which used `connection_candidate_id` (a
    partly-composite string) instead of a typed `attachment_id`; see
    DATA-016 for the legacy-migration boundary, deferred to Phase 2."""
    model_config = _MODEL_CONFIG

    resource_scenario_id: str
    surface_site_id: str
    attachment_id: str
    route_id: str
    design_option_id: str
    operating_policy_id: str

    @model_validator(mode="after")
    def _validate(self) -> "AlternativeIdentity":
        errors: list[str] = []
        for name, value in (
            ("resource_scenario_id", self.resource_scenario_id), ("surface_site_id", self.surface_site_id),
            ("attachment_id", self.attachment_id), ("route_id", self.route_id),
            ("design_option_id", self.design_option_id), ("operating_policy_id", self.operating_policy_id),
        ):
            if not value:
                errors.append(f"{name} must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def alternative_id(self) -> str:
        return (
            f"{self.resource_scenario_id}|{self.surface_site_id}|{self.attachment_id}"
            f"|{self.route_id}|{self.design_option_id}|{self.operating_policy_id}"
        )


# ── S7.12: DecisionPolicy ──────────────────────────────────────────────────────

class ObjectiveDefinition(BaseModel):
    model_config = _MODEL_CONFIG

    name: str
    direction: ObjectiveDirection
    absolute_materiality: float
    relative_materiality_fraction: float
    unit: str
    rationale: str
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "ObjectiveDefinition":
        errors: list[str] = []
        if not self.name:
            errors.append("name must not be empty")
        if self.absolute_materiality < 0:
            errors.append("absolute_materiality must be >= 0")
        if not (0.0 <= self.relative_materiality_fraction < 1.0):
            errors.append("relative_materiality_fraction must be in [0, 1)")
        if not self.unit:
            errors.append("unit must not be empty")
        if not self.rationale:
            errors.append("rationale must not be empty")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class DecisionPolicy(BaseModel):
    model_config = _MODEL_CONFIG

    mode: DecisionPolicyMode
    objectives: list[ObjectiveDefinition]
    primary_objective: str | None = None
    tie_breakers: list[str] = Field(default_factory=list)
    allow_shared_rank: bool
    display_order_key: Literal["alternative_id"] = "alternative_id"

    @model_validator(mode="after")
    def _validate(self) -> "DecisionPolicy":
        errors: list[str] = []
        if not self.objectives:
            errors.append("objectives must not be empty")
        objective_names = [o.name for o in self.objectives]
        if len(objective_names) != len(set(objective_names)):
            errors.append("objective names must be unique (DEC-003: reject duplicate default objectives)")
        # DEC-003's ALGEBRAIC-dependency check (e.g. LCOH vs. its own cost/
        # heat components) needs domain knowledge of which named objectives
        # are dependent -- that is Phase 4's own concern (S14), not a
        # structural contract check; only the duplicate-NAME check above is
        # implemented here.
        if self.mode == DecisionPolicyMode.PRIMARY_OBJECTIVE_RANKING:
            if not self.primary_objective:
                errors.append("primary_objective is required when mode=='primary_objective_ranking' (DEC-009)")
            elif self.primary_objective not in objective_names:
                errors.append(f"primary_objective {self.primary_objective!r} is not one of the declared objectives")
        if self.mode == DecisionPolicyMode.PARETO_ONLY and self.primary_objective is not None:
            errors.append("primary_objective must be null when mode=='pareto_only' (DEC-008)")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.13: NetworkReference ────────────────────────────────────────────────────

class NetworkReference(BaseModel):
    model_config = _MODEL_CONFIG

    network_id: str
    network_schema_version: str
    source_kind: NetworkSourceKind
    package_relative_path: str
    source_sha256: _Sha256Hex
    topology_scientific_fingerprint: str
    classification: DatasetClassification
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "NetworkReference":
        errors: list[str] = []
        if not self.network_id:
            errors.append("network_id must not be empty")
        if not self.network_schema_version:
            errors.append("network_schema_version must not be empty")
        if not _is_safe_package_relative_path(self.package_relative_path):
            errors.append(f"package_relative_path {self.package_relative_path!r} is not a safe package-relative path (DATA-022)")
        if not self.topology_scientific_fingerprint:
            errors.append("topology_scientific_fingerprint must not be empty")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.14: RoutingPolicy, DetourDefinition, ExclusionDefinition ─────────────

class DetourDefinition(BaseModel):
    model_config = _MODEL_CONFIG

    detour_id: str
    site_id: str
    attachment_id: str
    via_coordinates: list[Coordinate]
    reason: str

    @model_validator(mode="after")
    def _validate(self) -> "DetourDefinition":
        errors: list[str] = []
        if not self.detour_id:
            errors.append("detour_id must not be empty")
        if not self.site_id:
            errors.append("site_id must not be empty")
        if not self.attachment_id:
            errors.append("attachment_id must not be empty")
        if not self.via_coordinates:
            errors.append("via_coordinates must not be empty")
        if not self.reason:
            errors.append("reason must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class ExclusionDefinition(BaseModel):
    model_config = _MODEL_CONFIG

    exclusion_id: str
    geometry: list[Coordinate]
    applies_to: ExclusionAppliesTo
    reason: str
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "ExclusionDefinition":
        """S7.14: 'a valid non-self-intersecting polygon with at least
        three distinct vertices.' Only vertex-count and distinctness are
        checked here -- a full simplicity (non-self-intersection) test
        is a real computational-geometry algorithm this prototype does
        not implement; stated as a limitation, not silently claimed."""
        errors: list[str] = []
        if not self.exclusion_id:
            errors.append("exclusion_id must not be empty")
        if len(self.geometry) < 3:
            errors.append("geometry must have at least three vertices to form a polygon")
        elif all(not isinstance(c, GeographicCoordinate) for c in self.geometry):
            planar = [_planar_xy(c) for c in self.geometry]
            if len(set(planar)) < 3:
                errors.append("geometry vertices must be distinct")
        if not self.reason:
            errors.append("reason must not be empty")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class RoutingPolicy(BaseModel):
    model_config = _MODEL_CONFIG

    route_kind: RouteKind
    maximum_paired_trench_length_m: float
    allowed_attachment_ids: list[str]
    detour_definitions: list[DetourDefinition] = Field(default_factory=list)
    exclusion_definitions: list[ExclusionDefinition] = Field(default_factory=list)
    shared_trench: bool
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "RoutingPolicy":
        errors: list[str] = []
        if self.maximum_paired_trench_length_m <= 0:
            errors.append("maximum_paired_trench_length_m must be > 0")
        if not self.allowed_attachment_ids:
            errors.append("allowed_attachment_ids must not be empty")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.15: OperatingPolicyReference ───────────────────────────────────────────

class OperatingPolicyReference(BaseModel):
    model_config = _MODEL_CONFIG

    operating_policy_id: str
    policy_schema_version: str
    package_relative_path: str
    source_sha256: _Sha256Hex
    shortfall_mode: ShortfallMode
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "OperatingPolicyReference":
        errors: list[str] = []
        if not self.operating_policy_id:
            errors.append("operating_policy_id must not be empty")
        if not self.policy_schema_version:
            errors.append("policy_schema_version must not be empty")
        if not _is_safe_package_relative_path(self.package_relative_path):
            errors.append(f"package_relative_path {self.package_relative_path!r} is not a safe package-relative path (DATA-022)")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.16: JointEconomicPolicy ────────────────────────────────────────────────

class JointEconomicPolicy(BaseModel):
    model_config = _MODEL_CONFIG

    economic_policy_id: str
    economic_schema_version: str
    base_assumptions_package_relative_path: str
    base_assumptions_sha256: _Sha256Hex
    annual_operating_hours: float
    discount_rate_fraction: float
    analysis_period_years: int
    electricity_price_eur_per_mwh: float
    auxiliary_heat_price_eur_per_mwh: float
    price_year: int
    currency: Literal["EUR"] = "EUR"
    assumption_status: AssumptionStatus
    source_reference: str

    @model_validator(mode="after")
    def _validate(self) -> "JointEconomicPolicy":
        errors: list[str] = []
        if not self.economic_policy_id:
            errors.append("economic_policy_id must not be empty")
        if not _is_safe_package_relative_path(self.base_assumptions_package_relative_path):
            errors.append("base_assumptions_package_relative_path is not a safe package-relative path (DATA-022)")
        if not (0 < self.annual_operating_hours <= 8784):
            errors.append("annual_operating_hours must be in (0, 8784] (a non-leap/leap year's hour count)")
        if not (0.0 <= self.discount_rate_fraction < 1.0):
            errors.append("discount_rate_fraction must be in [0, 1)")
        if self.analysis_period_years <= 0:
            errors.append("analysis_period_years must be > 0")
        if self.electricity_price_eur_per_mwh < 0:
            errors.append("electricity_price_eur_per_mwh must be >= 0")
        if self.auxiliary_heat_price_eur_per_mwh < 0:
            errors.append("auxiliary_heat_price_eur_per_mwh must be >= 0")
        if not (1900 <= self.price_year <= 2100):
            errors.append(f"price_year {self.price_year!r} is not plausible")
        if not self.source_reference:
            errors.append("source_reference must not be empty")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.17: StudyProvenance ─────────────────────────────────────────────────────

class StudyProvenance(BaseModel):
    model_config = _MODEL_CONFIG

    created_at_utc: datetime
    created_by: str
    repository_commit: str
    software_version: str
    parent_input_sha256: list[_Sha256Hex]
    classification: DatasetClassification
    approval_status: StudyApprovalStatus
    approval_reference: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "StudyProvenance":
        errors: list[str] = []
        if not self.created_by:
            errors.append("created_by must not be empty")
        if not self.repository_commit:
            errors.append("repository_commit must not be empty")
        if not self.software_version:
            errors.append("software_version must not be empty")
        if self.classification == DatasetClassification.REAL:
            if self.approval_status != StudyApprovalStatus.REAL_STUDY_APPROVED:
                errors.append("a real-classified study requires approval_status=='real_study_approved' (DATA-019)")
            if not self.approval_reference:
                errors.append("approval_reference is required for a real-classified study")
        if self.approval_status == StudyApprovalStatus.NOT_APPROVED and self.approval_reference:
            errors.append("approval_reference must be null when approval_status=='not_approved'")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S7.1: JointStudyPackage ────────────────────────────────────────────────────

class JointStudyPackage(BaseModel):
    model_config = _MODEL_CONFIG

    contract_schema_version: Literal["2.0.0"] = JOINT_STUDY_CONTRACT_SCHEMA_VERSION
    study_id: str
    classification: DatasetClassification
    coordinate_reference: CoordinateReference
    sites: list[SurfaceSite]
    resource_inputs: list[ResourceInputReference]
    resource_scenarios: list[GeothermalResourceScenario]
    network_reference: NetworkReference
    network_attachments: list[NetworkAttachment]
    routing_policy: RoutingPolicy
    design_options: list[ConnectionDesignOption]
    operating_policies: list[OperatingPolicyReference]
    economics: JointEconomicPolicy
    decision_policy: DecisionPolicy
    provenance: StudyProvenance

    @model_validator(mode="after")
    def _validate(self) -> "JointStudyPackage":
        errors: list[str] = []
        if not self.study_id:
            errors.append("study_id must not be empty")
        if not self.sites:
            errors.append("sites must not be empty")
        if not self.resource_inputs:
            errors.append("resource_inputs must not be empty")
        if not self.resource_scenarios:
            errors.append("resource_scenarios must not be empty")
        if not self.network_attachments:
            errors.append("network_attachments must not be empty")
        if not self.design_options:
            errors.append("design_options must not be empty")
        if not self.operating_policies:
            errors.append("operating_policies must not be empty")
        if self.classification != self.provenance.classification:
            errors.append("study classification and provenance.classification must agree (DATA-020)")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ── S12.1: runtime failure-code taxonomy (typed vocabulary only -- Phase 1) ──

class JointRunFailureCode(str, Enum):
    """S12.1's failure taxonomy -- defined here as a typed vocabulary
    (Phase 1) but not yet raised from any running pipeline (no
    enumeration/evaluation exists to call it from until Phase 2)."""

    JOINT_STUDY_PACKAGE_INVALID = "JOINT_STUDY_PACKAGE_INVALID"
    JOINT_RESOURCE_INPUT_MISSING = "JOINT_RESOURCE_INPUT_MISSING"
    PYDOUBLET_RAW_HASH_MISMATCH = "PYDOUBLET_RAW_HASH_MISMATCH"
    """Deliberately the SAME string value as r3chain_geothermal.errors
    .FailureCode.PYDOUBLET_RAW_HASH_MISMATCH -- the identical check (does
    a supplied raw PyDoublet result match its expected hash?) applied at
    this contract's own ResourceInputReference boundary instead of the
    canonical single-scenario workflow's boundary. Re-declared here
    rather than imported -- Python's str-Enum cannot extend another
    Enum's members -- the SAME precedent network/errors.py's
    CandidateFailureCode already established for re-declaring
    BaselineFailureCode's members by name (its own docstring: "Python's
    str-Enum does not support extending an existing Enum's members")."""
    JOINT_REAL_STUDY_NOT_READY = "JOINT_REAL_STUDY_NOT_READY"
    JOINT_SITE_UNAVAILABLE = "JOINT_SITE_UNAVAILABLE"
    JOINT_ROUTE_SITE_MISMATCH = "JOINT_ROUTE_SITE_MISMATCH"
    JOINT_ROUTE_ATTACHMENT_MISMATCH = "JOINT_ROUTE_ATTACHMENT_MISMATCH"
    JOINT_ROUTE_EXCLUSION_CONFLICT = "JOINT_ROUTE_EXCLUSION_CONFLICT"
    JOINT_ROUTE_TOO_LONG = "JOINT_ROUTE_TOO_LONG"
    JOINT_ROUTE_KIND_UNSUPPORTED = "JOINT_ROUTE_KIND_UNSUPPORTED"
    JOINT_DESIGN_INVALID = "JOINT_DESIGN_INVALID"
    JOINT_DESIGN_INCOMPATIBLE = "JOINT_DESIGN_INCOMPATIBLE"


# ── DATA-001..022: pre-flight relationship validation ────────────────────────

class JointStudyErrorCode(str, Enum):
    """DATA-001..022's checkable-at-schema-level violations -- distinct
    from JointRunFailureCode (S12.1, the RUNTIME evaluation taxonomy for
    a pipeline that does not exist until Phase 2). This is the
    StudyPackageErrorCode-style pre-flight vocabulary for
    JointStudyPackage, mirroring validation.py's own pattern exactly."""

    DUPLICATE_ID = "DUPLICATE_ID"
    SCENARIO_SITE_MISMATCH = "SCENARIO_SITE_MISMATCH"
    SCENARIO_RESOURCE_INPUT_MISMATCH = "SCENARIO_RESOURCE_INPUT_MISMATCH"
    ROUTE_SITE_MISMATCH = "ROUTE_SITE_MISMATCH"
    ROUTE_ATTACHMENT_MISMATCH = "ROUTE_ATTACHMENT_MISMATCH"
    COORDINATE_REFERENCE_MISMATCH = "COORDINATE_REFERENCE_MISMATCH"
    CLASSIFICATION_INCOMPATIBLE = "CLASSIFICATION_INCOMPATIBLE"


class JointStudyFieldError(BaseModel):
    model_config = _MODEL_CONFIG

    field_path: str
    """e.g. "resource_scenarios[2].site_id" -- exact enough to locate the
    offending record without re-scanning the whole package."""
    error_code: JointStudyErrorCode
    message: str


class JointStudyValidationResult(BaseModel):
    model_config = _MODEL_CONFIG

    valid: bool
    errors: list[JointStudyFieldError]


def validate_joint_study_package(package: JointStudyPackage) -> JointStudyValidationResult:
    """DATA-001..022, so far as checkable purely from JointStudyPackage's
    OWN declared fields (no file resolution, no route generation -- both
    Phase 2+). NEVER raises for a structurally-valid object; collects
    every violation in one pass, matching validate_study_package()'s own
    convention exactly (never stops at the first error)."""
    errors: list[JointStudyFieldError] = []

    site_ids: set[str] = set()
    for index, site in enumerate(package.sites):
        if site.site_id in site_ids:
            errors.append(JointStudyFieldError(
                field_path=f"sites[{index}].site_id", error_code=JointStudyErrorCode.DUPLICATE_ID,
                message=f"duplicate site_id {site.site_id!r}",
            ))
        site_ids.add(site.site_id)
        if site.classification != package.classification:
            errors.append(JointStudyFieldError(
                field_path=f"sites[{index}].classification", error_code=JointStudyErrorCode.CLASSIFICATION_INCOMPATIBLE,
                message=f"site {site.site_id!r} classification={site.classification.value!r} does not match study classification={package.classification.value!r}",
            ))
        if package.coordinate_reference.kind == "synthetic_cartesian" and not isinstance(site.coordinate, SyntheticCoordinate):
            errors.append(JointStudyFieldError(
                field_path=f"sites[{index}].coordinate", error_code=JointStudyErrorCode.COORDINATE_REFERENCE_MISMATCH,
                message=f"site {site.site_id!r} coordinate kind does not match the package's synthetic_cartesian coordinate_reference",
            ))
        if package.coordinate_reference.kind == "epsg" and isinstance(site.coordinate, SyntheticCoordinate):
            errors.append(JointStudyFieldError(
                field_path=f"sites[{index}].coordinate", error_code=JointStudyErrorCode.COORDINATE_REFERENCE_MISMATCH,
                message=f"site {site.site_id!r} uses a synthetic coordinate under an epsg coordinate_reference (DATA-012)",
            ))

    resource_input_ids: set[str] = set()
    for index, resource_input in enumerate(package.resource_inputs):
        if resource_input.resource_input_id in resource_input_ids:
            errors.append(JointStudyFieldError(
                field_path=f"resource_inputs[{index}].resource_input_id", error_code=JointStudyErrorCode.DUPLICATE_ID,
                message=f"duplicate resource_input_id {resource_input.resource_input_id!r}",
            ))
        resource_input_ids.add(resource_input.resource_input_id)

    scenario_ids: set[str] = set()
    for index, scenario in enumerate(package.resource_scenarios):
        if scenario.scenario_id in scenario_ids:
            errors.append(JointStudyFieldError(
                field_path=f"resource_scenarios[{index}].scenario_id", error_code=JointStudyErrorCode.DUPLICATE_ID,
                message=f"duplicate scenario_id {scenario.scenario_id!r}",
            ))
        scenario_ids.add(scenario.scenario_id)
        if scenario.site_id not in site_ids:
            errors.append(JointStudyFieldError(
                field_path=f"resource_scenarios[{index}].site_id", error_code=JointStudyErrorCode.SCENARIO_SITE_MISMATCH,
                message=f"scenario {scenario.scenario_id!r} references unknown site_id {scenario.site_id!r}",
            ))
        if scenario.resource_input_id not in resource_input_ids:
            errors.append(JointStudyFieldError(
                field_path=f"resource_scenarios[{index}].resource_input_id", error_code=JointStudyErrorCode.SCENARIO_RESOURCE_INPUT_MISMATCH,
                message=f"scenario {scenario.scenario_id!r} references unknown resource_input_id {scenario.resource_input_id!r}",
            ))
        if scenario.classification != package.classification:
            errors.append(JointStudyFieldError(
                field_path=f"resource_scenarios[{index}].classification", error_code=JointStudyErrorCode.CLASSIFICATION_INCOMPATIBLE,
                message=f"scenario {scenario.scenario_id!r} classification does not match study classification",
            ))

    attachment_ids: set[str] = set()
    for index, attachment in enumerate(package.network_attachments):
        if attachment.attachment_id in attachment_ids:
            errors.append(JointStudyFieldError(
                field_path=f"network_attachments[{index}].attachment_id", error_code=JointStudyErrorCode.DUPLICATE_ID,
                message=f"duplicate attachment_id {attachment.attachment_id!r}",
            ))
        attachment_ids.add(attachment.attachment_id)

    design_option_ids: set[str] = set()
    for index, design in enumerate(package.design_options):
        if design.design_option_id in design_option_ids:
            errors.append(JointStudyFieldError(
                field_path=f"design_options[{index}].design_option_id", error_code=JointStudyErrorCode.DUPLICATE_ID,
                message=f"duplicate design_option_id {design.design_option_id!r}",
            ))
        design_option_ids.add(design.design_option_id)

    operating_policy_ids: set[str] = set()
    for index, policy in enumerate(package.operating_policies):
        if policy.operating_policy_id in operating_policy_ids:
            errors.append(JointStudyFieldError(
                field_path=f"operating_policies[{index}].operating_policy_id", error_code=JointStudyErrorCode.DUPLICATE_ID,
                message=f"duplicate operating_policy_id {policy.operating_policy_id!r}",
            ))
        operating_policy_ids.add(policy.operating_policy_id)

    if package.network_reference.classification != package.classification:
        errors.append(JointStudyFieldError(
            field_path="network_reference.classification", error_code=JointStudyErrorCode.CLASSIFICATION_INCOMPATIBLE,
            message="network_reference classification does not match study classification",
        ))

    return JointStudyValidationResult(valid=len(errors) == 0, errors=errors)


# ── TERM-003/004/005, AC-J02/AC-J03: active-dimension reporting ─────────────

class ActiveDimensionReport(BaseModel):
    model_config = _MODEL_CONFIG

    active_dimensions: list[str]
    controlled_dimensions: list[str]
    cardinalities: dict[str, int]
    dependency_notes: list[str]


def compute_active_dimensions(package: JointStudyPackage) -> ActiveDimensionReport:
    """TERM-003/004/005, AC-J02/AC-J03: a dimension with exactly one
    distinct value is CONTROLLED, not optimised (TERM-004) -- this
    function reports which identity dimensions this package's OWN
    declared data actually varies, computed directly from typed fields,
    never guessed from naming or code comments (TERM-002: never call six
    stored identity fields "six active axes" without this check)."""
    site_ids = {s.site_id for s in package.sites}
    scenario_ids = {s.scenario_id for s in package.resource_scenarios}
    attachment_ids = {a.attachment_id for a in package.network_attachments}
    design_option_ids = {d.design_option_id for d in package.design_options}
    operating_policy_ids = {p.operating_policy_id for p in package.operating_policies}

    scenarios_per_site: dict[str, int] = {}
    for scenario in package.resource_scenarios:
        scenarios_per_site[scenario.site_id] = scenarios_per_site.get(scenario.site_id, 0) + 1
    max_scenarios_per_site = max(scenarios_per_site.values(), default=0)

    cardinalities = {
        "surface_site_id": len(site_ids),
        "resource_scenario_id": len(scenario_ids),
        "attachment_id": len(attachment_ids),
        "design_option_id": len(design_option_ids),
        "operating_policy_id": len(operating_policy_ids),
    }
    # route_id's cardinality is not reported here: routes are a Phase-2
    # generated output, not part of this static package (S7.1 has no
    # `routes` field) -- this function never fabricates a route count.

    active = sorted(name for name, count in cardinalities.items() if count > 1)
    controlled = sorted(name for name, count in cardinalities.items() if count <= 1)

    dependency_notes = [
        "resource_scenario_id depends on surface_site_id: every scenario references exactly one site "
        "(S7.5) -- it is reported as its own dimension only because at least one site MAY have more "
        "than one linked scenario (TERM-005), never as an independent free-standing axis.",
    ]
    if max_scenarios_per_site <= 1:
        dependency_notes.append(
            "No site in this package currently has more than one linked resource scenario -- "
            "resource_scenario_id and surface_site_id vary in lockstep here (TERM-005's many-to-one "
            "condition is not exercised by this package's own data)."
        )

    return ActiveDimensionReport(
        active_dimensions=active, controlled_dimensions=controlled,
        cardinalities=cardinalities, dependency_notes=dependency_notes,
    )
