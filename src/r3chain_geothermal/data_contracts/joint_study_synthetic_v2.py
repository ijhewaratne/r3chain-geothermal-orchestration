"""The committed, ready-to-run synthetic v2 joint study package (S8,
WF-001, docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
Phase 2).

`build_synthetic_v2_study_package()` constructs the ONE `JointStudyPackage`
this Phase-2 demonstration evaluates, derived from the single golden PyDoublet
result (real per-site PyDoublet runs remain out of scope, CLAUDE.md). Every
transformation is a DECLARED `SyntheticDerivation` field_change (S8.2) --
never hidden logic -- and `apply_synthetic_derivation()` is the ONE function
that actually applies those declared changes to produce the coupling input a
scenario is evaluated with, so the derivation record is not merely
descriptive metadata sitting beside the real computation; it IS the
computation.

## Formula reuse, not reinvention (GOV-010)

`_recompute_raw_power_kw()` and `_scale_pump_power_kw()` are the SAME two
formulas `workflow/joint_optimization.py`'s own (private, unexported)
`_recompute_raw_power_kw()`/`_scale_pump_power_kw()` already use --
mass_flow*cp*(T_prod-T_brine_outlet)/1000 (the same energy-consistency
formula T1.5B's own check applies) and pump power linear in mass-flow ratio
(PyDoublet's own `calc_power_data()` relationship). Reimplemented here as
small, independent, public functions rather than imported from that module,
because those two are module-private there and this is a genuinely separate
v2 contract-construction concern -- not a claim that v1's own formulas were
wrong or need replacing.

## Site geometry (S8.1, AC-J04)

Four sites are placed so that trunk_2 is reachable, within the routing
policy's own length limit, from BOTH site_alpha (via a longer route) and
site_beta (via a shorter one) -- the concrete AC-J04 proof: the SAME
attachment evaluated from two different sites has two different geometry-
derived route lengths, not one shared global distance re-labelled by site."""
from __future__ import annotations

from datetime import datetime, timezone

from ..contracts.coupling_result import NormalizedQuantity, PyDoubletCouplingResult
from .joint_study import (
    AssumptionStatus,
    AttachmentEligibilityStatus,
    ConnectionDesignOption,
    CoordinateReference,
    DecisionPolicy,
    DecisionPolicyMode,
    ExclusionAppliesTo,
    ExclusionDefinition,
    GeologicalMetadata,
    GeothermalResourceScenario,
    JointEconomicPolicy,
    JointStudyPackage,
    NetworkAttachment,
    NetworkReference,
    NetworkSourceKind,
    ObjectiveDefinition,
    ObjectiveDirection,
    OperatingPolicyReference,
    ResourceInputReference,
    ResourceInputSourceKind,
    RouteKind,
    RoutingPolicy,
    ShortfallMode,
    SiteAvailabilityStatus,
    SiteEconomicInputs,
    StudyApprovalStatus,
    StudyProvenance,
    SurfaceSite,
    SyntheticCoordinate,
    SyntheticDerivation,
    SyntheticDerivationFieldChange,
    TemporalBasis,
)
from .schema import DatasetClassification

SYNTHETIC_V2_STUDY_ID = "r3chain-joint-study-synthetic-v2-demo"


def _recompute_raw_power_kw(mass_flow_kg_s: float, specific_heat_j_kg_k: float, t_prod_c: float, t_brine_outlet_c: float) -> float:
    """Reused formula -- see module docstring. Identical to
    adapter/heat_exchanger.py's own energy-consistency check and
    workflow/joint_optimization.py's private v1 equivalent."""
    return mass_flow_kg_s * specific_heat_j_kg_k * (t_prod_c - t_brine_outlet_c) / 1000.0


def _scale_pump_power_kw(mass_flow_kg_s: float, golden_mass_flow_kg_s: float, golden_pump_power_kw: float) -> float:
    """Reused formula -- see module docstring. Identical to
    workflow/joint_optimization.py's private v1 equivalent, itself
    reusing PyDoublet's own calc_power_data() linear-in-flow
    relationship."""
    return golden_pump_power_kw * (mass_flow_kg_s / golden_mass_flow_kg_s)


def apply_synthetic_derivation(golden: PyDoubletCouplingResult, derivation: SyntheticDerivation | None) -> PyDoubletCouplingResult:
    """The declared field_changes ARE the computation -- not descriptive
    metadata alongside a separately-hard-coded transformation (S8.2's
    own corrective intent). `derivation=None` means: use golden
    unchanged (S7.5's own rule)."""
    if derivation is None:
        return golden
    updates: dict[str, NormalizedQuantity] = {}
    for change in derivation.field_changes:
        current: NormalizedQuantity = getattr(golden, change.field_name)
        updates[change.field_name] = current.model_copy(update={"value": change.transformed_value})
    return golden.model_copy(update=updates)


def _make_scenario(
    *, scenario_id: str, site_id: str, label: str, resource_input_id: str,
    t_prod_c: float, mass_flow_kg_s: float, golden: PyDoubletCouplingResult,
    doublet_capex_multiplier: float, rationale: str, source_fixture_sha256: str,
) -> GeothermalResourceScenario:
    golden_mass_flow = golden.geothermal_brine_mass_flow_kg_s.value
    golden_pump_kw = golden.doublet_pump_electric_power_kw.value
    specific_heat = golden.geothermal_brine_specific_heat_capacity_j_kg_k.value
    t_brine_outlet = golden.geothermal_brine_hx_outlet_temperature_c.value

    raw_power_kw = _recompute_raw_power_kw(mass_flow_kg_s, specific_heat, t_prod_c, t_brine_outlet)
    pump_power_kw = _scale_pump_power_kw(mass_flow_kg_s, golden_mass_flow, golden_pump_kw)

    field_changes = [
        SyntheticDerivationFieldChange(
            field_name="producer_wellhead_temperature_c", original_value=golden.producer_wellhead_temperature_c.value,
            transformed_value=t_prod_c, transformation_formula="declared target producer temperature",
        ),
        SyntheticDerivationFieldChange(
            field_name="geothermal_brine_mass_flow_kg_s", original_value=golden_mass_flow,
            transformed_value=mass_flow_kg_s, transformation_formula="declared target brine mass flow",
        ),
        SyntheticDerivationFieldChange(
            field_name="raw_geothermal_thermal_power_kw", original_value=golden.raw_geothermal_thermal_power_kw.value,
            transformed_value=raw_power_kw, transformation_formula="mass_flow_kg_s * cp * (T_prod_c - T_brine_outlet_c) / 1000",
            is_recomputed_consequence=True,
        ),
        SyntheticDerivationFieldChange(
            field_name="doublet_pump_electric_power_kw", original_value=golden_pump_kw,
            transformed_value=pump_power_kw, transformation_formula="golden_pump_kw * (mass_flow_kg_s / golden_mass_flow_kg_s)",
            is_recomputed_consequence=True,
        ),
    ]
    derivation = SyntheticDerivation(
        source_fixture_sha256=source_fixture_sha256,
        field_changes=field_changes, doublet_capex_multiplier=doublet_capex_multiplier,
        rationale=rationale, author_or_decision_reference="R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md Phase 2",
    )
    return GeothermalResourceScenario(
        scenario_id=scenario_id, site_id=site_id, scenario_label=label, classification=DatasetClassification.SYNTHETIC,
        resource_input_id=resource_input_id, temporal_basis=TemporalBasis.LIFETIME_AVERAGE_STEADY,
        geological_metadata=GeologicalMetadata(),
        economic_inputs=SiteEconomicInputs(
            doublet_capex_eur=8_000_000.0 * doublet_capex_multiplier,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
        ),
        derivation=derivation,
    )


def build_synthetic_v2_study_package(
    golden: PyDoubletCouplingResult, *, resource_input_expected_raw_sha256: str, repository_commit: str,
    network_source_sha256: str, network_topology_fingerprint: str,
    operating_policy_source_sha256: str, base_assumptions_sha256: str,
) -> JointStudyPackage:
    """Every `*_sha256`/`*_fingerprint` argument is a REAL hash the
    caller computes from the actual referenced file bytes (GOV-011: no
    fabricated provenance) -- never a placeholder/zero digest baked into
    this module. See `scripts/build_joint_study_synthetic_v2_fixture.py`
    for how each is computed."""
    resource_input_id = "pydoublet-golden-repaired"

    sites = [
        SurfaceSite(
            site_id="site_alpha", label="Site alpha (near trunk_1/trunk_2)", classification=DatasetClassification.SYNTHETIC,
            coordinate=SyntheticCoordinate(x_m=250.0, y_m=-60.0), availability_status=SiteAvailabilityStatus.AVAILABLE,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
        ),
        SurfaceSite(
            site_id="site_beta", label="Site beta (near trunk_2)", classification=DatasetClassification.SYNTHETIC,
            coordinate=SyntheticCoordinate(x_m=600.0, y_m=-90.0), availability_status=SiteAvailabilityStatus.AVAILABLE,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
        ),
        SurfaceSite(
            site_id="site_gamma", label="Site gamma (near trunk_3/trunk_4)", classification=DatasetClassification.SYNTHETIC,
            coordinate=SyntheticCoordinate(x_m=750.0, y_m=-70.0), availability_status=SiteAvailabilityStatus.AVAILABLE,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
        ),
        SurfaceSite(
            site_id="site_delta", label="Site delta (protected-geometry demonstration, excluded)",
            classification=DatasetClassification.SYNTHETIC, coordinate=SyntheticCoordinate(x_m=1000.0, y_m=-60.0),
            availability_status=SiteAvailabilityStatus.EXCLUDED,
            exclusion_reason="synthetic protected-geometry demonstration example (S8.1: at least one excluded site)",
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
        ),
    ]

    resource_inputs = [ResourceInputReference(
        resource_input_id=resource_input_id, source_kind=ResourceInputSourceKind.PRIMARY_RUNTIME_INPUT,
        expected_raw_sha256=resource_input_expected_raw_sha256, provenance_reference="fixtures/pydoublet/repaired_result.json",
        classification=DatasetClassification.SYNTHETIC,
    )]

    resource_scenarios = [
        _make_scenario(
            scenario_id="scenario_alpha_golden", site_id="site_alpha", label="Site alpha, golden PyDoublet result",
            resource_input_id=resource_input_id, t_prod_c=golden.producer_wellhead_temperature_c.value,
            mass_flow_kg_s=golden.geothermal_brine_mass_flow_kg_s.value, golden=golden, source_fixture_sha256=resource_input_expected_raw_sha256,
            doublet_capex_multiplier=1.0, rationale="golden result, unmodified (baseline scenario)",
        ),
        _make_scenario(
            scenario_id="scenario_alpha_reduced_flow", site_id="site_alpha", label="Site alpha, reduced brine flow",
            resource_input_id=resource_input_id, t_prod_c=golden.producer_wellhead_temperature_c.value,
            mass_flow_kg_s=golden.geothermal_brine_mass_flow_kg_s.value * 0.7, golden=golden, source_fixture_sha256=resource_input_expected_raw_sha256,
            doublet_capex_multiplier=1.15, rationale="declared, illustrative reduced-flow/deeper-reservoir sensitivity case for site_alpha (AC-J03: a second scenario on the same site)",
        ),
        _make_scenario(
            scenario_id="scenario_beta_low_temperature", site_id="site_beta", label="Site beta, low producer temperature",
            resource_input_id=resource_input_id, t_prod_c=60.0,
            mass_flow_kg_s=golden.geothermal_brine_mass_flow_kg_s.value, golden=golden, source_fixture_sha256=resource_input_expected_raw_sha256,
            doublet_capex_multiplier=0.85, rationale="declared, illustrative low-temperature scenario -- deliberately below dh_supply_temperature_c + minimum_hx_approach_k, demonstrating HX_SUPPLY_TEMPERATURE_INFEASIBLE (AC-J06)",
        ),
        _make_scenario(
            scenario_id="scenario_gamma_higher_flow", site_id="site_gamma", label="Site gamma, higher brine flow",
            resource_input_id=resource_input_id, t_prod_c=golden.producer_wellhead_temperature_c.value,
            mass_flow_kg_s=golden.geothermal_brine_mass_flow_kg_s.value * 1.1, golden=golden, source_fixture_sha256=resource_input_expected_raw_sha256,
            doublet_capex_multiplier=1.05, rationale="declared, illustrative higher-flow sensitivity case for site_gamma",
        ),
    ]

    network_attachments = [
        NetworkAttachment(
            attachment_id="trunk_1", supply_junction_id="trunk_1", return_junction_id="ret_trunk_1",
            pressure_zone_id="zone_1", eligibility_status=AttachmentEligibilityStatus.ELIGIBLE,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="network/geometry.py",
        ),
        NetworkAttachment(
            attachment_id="trunk_2", supply_junction_id="trunk_2", return_junction_id="ret_trunk_2",
            pressure_zone_id="zone_1", eligibility_status=AttachmentEligibilityStatus.ELIGIBLE,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="network/geometry.py",
        ),
        NetworkAttachment(
            attachment_id="trunk_3", supply_junction_id="trunk_3", return_junction_id="ret_trunk_3",
            pressure_zone_id="zone_1", eligibility_status=AttachmentEligibilityStatus.ELIGIBLE,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="network/geometry.py",
        ),
        NetworkAttachment(
            attachment_id="trunk_4", supply_junction_id="trunk_4", return_junction_id="ret_trunk_4",
            pressure_zone_id="zone_1", eligibility_status=AttachmentEligibilityStatus.ELIGIBLE,
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="network/geometry.py",
        ),
    ]

    routing_policy = RoutingPolicy(
        route_kind=RouteKind.SYNTHETIC_POLYLINE, maximum_paired_trench_length_m=300.0,
        allowed_attachment_ids=["trunk_1", "trunk_2", "trunk_3", "trunk_4"],
        exclusion_definitions=[ExclusionDefinition(
            exclusion_id="protected_zone_east", geometry=[
                SyntheticCoordinate(x_m=950.0, y_m=-120.0), SyntheticCoordinate(x_m=1050.0, y_m=-120.0),
                SyntheticCoordinate(x_m=1050.0, y_m=0.0), SyntheticCoordinate(x_m=950.0, y_m=0.0),
            ],
            applies_to=ExclusionAppliesTo.SITES, reason="synthetic protected-geometry demonstration polygon (S7.14)",
            assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
        )],
        shared_trench=True, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION, source_reference="demo",
    )

    design_options = [ConnectionDesignOption(
        design_option_id="standard", connection_pipe_inner_diameter_mm=200.0, pipe_roughness_mm=0.1,
        capex_eur_per_paired_trench_m=1000.0, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="config/demo_assumptions.json",
    )]
    operating_policies = [OperatingPolicyReference(
        operating_policy_id="standard", policy_schema_version="1.0.0",
        package_relative_path="config/demo_assumptions.json", source_sha256=operating_policy_source_sha256,
        shortfall_mode=ShortfallMode.AUXILIARY, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="config/demo_assumptions.json",
    )]

    network_reference = NetworkReference(
        network_id="r3chain-synthetic-network-v1", network_schema_version="1.0.0",
        source_kind=NetworkSourceKind.COMMITTED_BLUEPRINT, package_relative_path="src/r3chain_geothermal/network/geometry.py",
        source_sha256=network_source_sha256, topology_scientific_fingerprint=network_topology_fingerprint,
        classification=DatasetClassification.SYNTHETIC, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
        source_reference="network/geometry.py",
    )

    economics = JointEconomicPolicy(
        economic_policy_id="demo-econ-v2", economic_schema_version="1.0.0",
        base_assumptions_package_relative_path="config/demo_assumptions.json", source_reference="config/demo_assumptions.json",
        base_assumptions_sha256=base_assumptions_sha256, annual_operating_hours=8000.0, discount_rate_fraction=0.04,
        analysis_period_years=25, electricity_price_eur_per_mwh=180.0, auxiliary_heat_price_eur_per_mwh=90.0,
        price_year=2026, assumption_status=AssumptionStatus.SYNTHETIC_ASSUMPTION,
    )

    decision_policy = DecisionPolicy(
        mode=DecisionPolicyMode.PARETO_ONLY,
        objectives=[
            ObjectiveDefinition(
                name="indicative_system_lcoh_eur_per_mwh", direction=ObjectiveDirection.MINIMIZE,
                absolute_materiality=0.5, relative_materiality_fraction=0.01, unit="EUR/MWh",
                rationale="primary cost signal (S14.2)", source_reference="R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md S14.2",
            ),
            ObjectiveDefinition(
                name="geothermal_coverage_fraction", direction=ObjectiveDirection.MAXIMIZE,
                absolute_materiality=0.01, relative_materiality_fraction=0.02, unit="dimensionless",
                rationale="resource utilisation signal (S14.2)", source_reference="R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md S14.2",
            ),
            ObjectiveDefinition(
                name="total_pumping_electric_energy_mwh_per_a", direction=ObjectiveDirection.MINIMIZE,
                absolute_materiality=0.05, relative_materiality_fraction=0.02, unit="MWh/a",
                rationale="electrical energy, not cost, since cost is already in LCOH (DEC-004)", source_reference="R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md S14.2",
            ),
        ],
        allow_shared_rank=True,
    )

    provenance = StudyProvenance(
        created_at_utc=datetime(2026, 9, 4, tzinfo=timezone.utc), created_by="R3-CHAIN Phase 2 synthetic-v2 fixture builder",
        repository_commit=repository_commit, software_version="0.1.0", parent_input_sha256=[resource_input_expected_raw_sha256],
        classification=DatasetClassification.SYNTHETIC, approval_status=StudyApprovalStatus.SYNTHETIC_DEMO_APPROVED,
    )

    return JointStudyPackage(
        study_id=SYNTHETIC_V2_STUDY_ID, classification=DatasetClassification.SYNTHETIC,
        coordinate_reference=CoordinateReference(
            kind="synthetic_cartesian", identifier="r3chain-synthetic-network-v1", horizontal_unit="m", axis_order=["x", "y"],
        ),
        sites=sites, resource_inputs=resource_inputs, resource_scenarios=resource_scenarios,
        network_reference=network_reference, network_attachments=network_attachments, routing_policy=routing_policy,
        design_options=design_options, operating_policies=operating_policies, economics=economics,
        decision_policy=decision_policy, provenance=provenance,
    )
