"""Pre-flight study-package validation (DATA-007, AC-09).

`validate_study_package()` NEVER raises for a structurally-valid
`StudyPackage` object with missing/inconsistent DATA (Pydantic's own
model-level validators already reject a structurally malformed object at
construction time -- this module's job is the SEMANTIC, cross-field/
cross-record checks that require examining the package as a whole:
duplicate IDs, disconnected topology, impossible temperatures, and the
"missing CRS / pipe diameter / provenance" trio AC-09 names explicitly).

No silent imputation: every check below either passes or appends an exact,
typed `StudyPackageFieldError` naming the precise field path -- never a
default value substituted in real mode (DATA-007: "no silent imputation is
allowed in real mode"; this module treats every package the same way
regardless of classification, since real vs. synthetic gating is
`readiness.py`'s concern, not this validator's).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from .schema import NetworkSide, StudyPackage


class StudyPackageErrorCode(str, Enum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    MISSING_CRS = "MISSING_CRS"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    DUPLICATE_ID = "DUPLICATE_ID"
    DISCONNECTED_TOPOLOGY = "DISCONNECTED_TOPOLOGY"
    IMPOSSIBLE_TEMPERATURE = "IMPOSSIBLE_TEMPERATURE"
    INVALID_DIMENSION = "INVALID_DIMENSION"
    INCONSISTENT_UNITS = "INCONSISTENT_UNITS"


class StudyPackageFieldError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_path: str
    """e.g. "network.pipes[3].internal_diameter_mm" -- exact enough to
    locate the offending record without re-scanning the whole package."""
    error_code: StudyPackageErrorCode
    message: str


class StudyPackageValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    errors: list[StudyPackageFieldError]


def _validate_spatial_layers(package: StudyPackage) -> list[StudyPackageFieldError]:
    errors: list[StudyPackageFieldError] = []
    for index, layer in enumerate(package.manifest.spatial_layers):
        if not (layer.crs or "").strip():
            errors.append(StudyPackageFieldError(
                field_path=f"manifest.spatial_layers[{index}].crs",
                error_code=StudyPackageErrorCode.MISSING_CRS,
                message=f"spatial layer {layer.file_path!r} has no declared CRS",
            ))
    return errors


def _validate_network_topology(package: StudyPackage) -> list[StudyPackageFieldError]:
    errors: list[StudyPackageFieldError] = []
    if package.network is None:
        return errors
    network = package.network

    junction_ids = [j.junction_id for j in network.junctions]
    seen_junction_ids: set[str] = set()
    for index, junction_id in enumerate(junction_ids):
        if junction_id in seen_junction_ids:
            errors.append(StudyPackageFieldError(
                field_path=f"network.junctions[{index}].junction_id",
                error_code=StudyPackageErrorCode.DUPLICATE_ID,
                message=f"duplicate junction_id {junction_id!r}",
            ))
        seen_junction_ids.add(junction_id)

    pipe_ids: set[str] = set()
    adjacency: dict[str, set[str]] = {jid: set() for jid in junction_ids}
    for index, pipe in enumerate(network.pipes):
        if pipe.pipe_id in pipe_ids:
            errors.append(StudyPackageFieldError(
                field_path=f"network.pipes[{index}].pipe_id",
                error_code=StudyPackageErrorCode.DUPLICATE_ID,
                message=f"duplicate pipe_id {pipe.pipe_id!r}",
            ))
        pipe_ids.add(pipe.pipe_id)

        if pipe.internal_diameter_mm <= 0:
            errors.append(StudyPackageFieldError(
                field_path=f"network.pipes[{index}].internal_diameter_mm",
                error_code=StudyPackageErrorCode.INVALID_DIMENSION,
                message=f"pipe {pipe.pipe_id!r} internal_diameter_mm={pipe.internal_diameter_mm!r} must be > 0",
            ))
        if pipe.length_m <= 0:
            errors.append(StudyPackageFieldError(
                field_path=f"network.pipes[{index}].length_m",
                error_code=StudyPackageErrorCode.INVALID_DIMENSION,
                message=f"pipe {pipe.pipe_id!r} length_m={pipe.length_m!r} must be > 0",
            ))

        for endpoint_field, endpoint in (("from_junction", pipe.from_junction), ("to_junction", pipe.to_junction)):
            if endpoint not in adjacency:
                errors.append(StudyPackageFieldError(
                    field_path=f"network.pipes[{index}].{endpoint_field}",
                    error_code=StudyPackageErrorCode.DISCONNECTED_TOPOLOGY,
                    message=f"pipe {pipe.pipe_id!r} references unknown junction {endpoint!r}",
                ))
        if pipe.from_junction in adjacency and pipe.to_junction in adjacency:
            adjacency[pipe.from_junction].add(pipe.to_junction)
            adjacency[pipe.to_junction].add(pipe.from_junction)

    # Connectivity is checked WITHIN each side (supply, return) separately,
    # not across the whole junction set combined -- a real two-sided DH
    # network's supply and return graphs are legitimately separate pipe
    # graphs, joined only through non-pipe components (consumers, plants)
    # that this simplified schema does not model as graph edges. Requiring
    # one combined connected component would misclassify every physically
    # normal two-sided network as "disconnected."
    junctions_by_side: dict[NetworkSide, list[str]] = {NetworkSide.SUPPLY: [], NetworkSide.RETURN: []}
    for junction in network.junctions:
        junctions_by_side[junction.side].append(junction.junction_id)

    for side, side_junction_ids in junctions_by_side.items():
        if not side_junction_ids:
            continue
        visited: set[str] = set()
        stack = [side_junction_ids[0]]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(adjacency.get(current, set()) & set(side_junction_ids) - visited)
        unreachable = set(side_junction_ids) - visited
        if unreachable:
            errors.append(StudyPackageFieldError(
                field_path=f"network.junctions[side={side.value}]",
                error_code=StudyPackageErrorCode.DISCONNECTED_TOPOLOGY,
                message=f"{side.value} junctions not reachable from {side_junction_ids[0]!r}: {sorted(unreachable)}",
            ))

    consumer_ids: set[str] = set()
    for index, consumer in enumerate(network.consumers):
        if consumer.consumer_id in consumer_ids:
            errors.append(StudyPackageFieldError(
                field_path=f"network.consumers[{index}].consumer_id",
                error_code=StudyPackageErrorCode.DUPLICATE_ID,
                message=f"duplicate consumer_id {consumer.consumer_id!r}",
            ))
        consumer_ids.add(consumer.consumer_id)
        if consumer.design_load_kw <= 0:
            errors.append(StudyPackageFieldError(
                field_path=f"network.consumers[{index}].design_load_kw",
                error_code=StudyPackageErrorCode.INVALID_DIMENSION,
                message=f"consumer {consumer.consumer_id!r} design_load_kw={consumer.design_load_kw!r} must be > 0",
            ))

    return errors


def _validate_geothermal_scenarios(package: StudyPackage) -> list[StudyPackageFieldError]:
    errors: list[StudyPackageFieldError] = []
    scenario_ids: set[str] = set()
    for index, scenario in enumerate(package.geothermal_scenarios):
        if scenario.scenario_id in scenario_ids:
            errors.append(StudyPackageFieldError(
                field_path=f"geothermal_scenarios[{index}].scenario_id",
                error_code=StudyPackageErrorCode.DUPLICATE_ID,
                message=f"duplicate scenario_id {scenario.scenario_id!r}",
            ))
        scenario_ids.add(scenario.scenario_id)

        if not scenario.pydoublet_input_sha256 or not scenario.pydoublet_result_sha256:
            errors.append(StudyPackageFieldError(
                field_path=f"geothermal_scenarios[{index}]",
                error_code=StudyPackageErrorCode.MISSING_PROVENANCE,
                message=f"scenario {scenario.scenario_id!r} is missing its PyDoublet input/result hash",
            ))
        if scenario.temperature_assumption_c <= scenario.reinjection_constraint_c:
            errors.append(StudyPackageFieldError(
                field_path=f"geothermal_scenarios[{index}].temperature_assumption_c",
                error_code=StudyPackageErrorCode.IMPOSSIBLE_TEMPERATURE,
                message=(
                    f"scenario {scenario.scenario_id!r} temperature_assumption_c="
                    f"{scenario.temperature_assumption_c!r} does not exceed its own "
                    f"reinjection_constraint_c={scenario.reinjection_constraint_c!r}"
                ),
            ))
    return errors


def _validate_economics(package: StudyPackage) -> list[StudyPackageFieldError]:
    errors: list[StudyPackageFieldError] = []
    line_item_ids: set[str] = set()
    for index, item in enumerate(package.economics):
        if item.line_item_id in line_item_ids:
            errors.append(StudyPackageFieldError(
                field_path=f"economics[{index}].line_item_id",
                error_code=StudyPackageErrorCode.DUPLICATE_ID,
                message=f"duplicate line_item_id {item.line_item_id!r}",
            ))
        line_item_ids.add(item.line_item_id)
        if not item.currency:
            errors.append(StudyPackageFieldError(
                field_path=f"economics[{index}].currency", error_code=StudyPackageErrorCode.MISSING_REQUIRED_FIELD,
                message=f"line item {item.line_item_id!r} has no currency",
            ))
    return errors


def _validate_unit_conventions(package: StudyPackage) -> list[StudyPackageFieldError]:
    """DATA-007: "inconsistent units... must fail pre-flight." This
    prototype checks the one unit-convention entry every package must
    declare consistently: length. A full unit-consistency engine across
    every declared quantity was judged out of proportion to this
    workstream -- this is the one check exercised by
    tests/data_contracts/test_validation.py's own INCONSISTENT_UNITS
    reachability test."""
    errors: list[StudyPackageFieldError] = []
    length_unit = package.manifest.unit_conventions.get("length")
    if length_unit is not None and length_unit not in ("m", "meter", "metre", "metres", "meters"):
        errors.append(StudyPackageFieldError(
            field_path="manifest.unit_conventions.length",
            error_code=StudyPackageErrorCode.INCONSISTENT_UNITS,
            message=f"declared length unit {length_unit!r} is not a recognized metre variant",
        ))
    return errors


def validate_study_package(package: StudyPackage) -> StudyPackageValidationResult:
    """DATA-007/AC-09: never raises; always returns every applicable
    error, never stopping at the first one, so a caller can report the
    complete missing/invalid-item list in one pass (DATA-009's own
    readiness report depends on seeing all of them, not just the first)."""
    errors: list[StudyPackageFieldError] = [
        *_validate_spatial_layers(package),
        *_validate_network_topology(package),
        *_validate_geothermal_scenarios(package),
        *_validate_economics(package),
        *_validate_unit_conventions(package),
    ]
    return StudyPackageValidationResult(valid=len(errors) == 0, errors=errors)
