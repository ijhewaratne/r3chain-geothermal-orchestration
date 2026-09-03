"""R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md Phase 5:
enforce_real_data_readiness() -- the mandatory gate any future real-data
entry point must call before connection- or drilling-location
optimisation against a `classification=="real"` StudyPackage.

Builds entirely on generate_readiness_report() (DATA-009, already
tested in test_validation_and_readiness.py) -- no new validation logic
is introduced here, only the named-requirement enumeration and the
discriminated ready/DATA_REQUIREMENTS_NOT_MET boundary result.
"""
from __future__ import annotations

from r3chain_geothermal.data_contracts import (
    ApprovalStatus,
    DataOwnerReference,
    DataRequirementsNotMet,
    DatasetClassification,
    EconomicLineItem,
    LicenceReference,
    RealDataReadinessGranted,
    RealDataRequirement,
    StudyDecisionPolicy,
    StudyPackage,
    enforce_real_data_readiness,
    parse_real_data_readiness_result_json,
)
from r3chain_geothermal.data_contracts.sample_packages import (
    build_intentionally_incomplete_real_package,
    build_synthetic_sample_package,
)


def _complete_approved_real_package() -> StudyPackage:
    """The AC-09 intentionally-incomplete fixture, with all three named
    gaps fixed plus economics/decisions supplied and the manifest
    approved -- the ONE genuinely "ready" real package this test file
    constructs, to prove the granted path is reachable for a real
    (not merely synthetic) package too."""
    incomplete = build_intentionally_incomplete_real_package()
    manifest = incomplete.manifest.model_copy(update={"approval_status": ApprovalStatus.APPROVED})
    spatial_layers = [layer.model_copy(update={"crs": "EPSG:25832"}) for layer in manifest.spatial_layers]
    manifest = manifest.model_copy(update={"spatial_layers": spatial_layers})
    network = incomplete.network.model_copy(update={
        "pipes": [pipe.model_copy(update={"internal_diameter_mm": 200.0}) for pipe in incomplete.network.pipes],
    })
    scenarios = [
        s.model_copy(update={"pydoublet_input_sha256": "a" * 64, "pydoublet_result_sha256": "b" * 64})
        for s in incomplete.geothermal_scenarios
    ]
    economics = [
        EconomicLineItem(
            line_item_id="e1", category="drilling", value=1.0, currency="EUR", price_year=2026,
            unit_basis="lump_sum", source="test fixture", approval_status=ApprovalStatus.APPROVED,
            inclusion_note="test fixture only",
        ),
    ]
    decisions = StudyDecisionPolicy(ranking_policy="feasibility_first_then_lowest_annualised_cost")
    return StudyPackage(
        manifest=manifest, network=network, geothermal_scenarios=scenarios, economics=economics, decisions=decisions,
    )


def test_synthetic_package_is_always_granted():
    package = build_synthetic_sample_package()
    result = enforce_real_data_readiness(package, requested_optimization="connection")
    assert isinstance(result, RealDataReadinessGranted)
    assert result.readiness.classification == DatasetClassification.SYNTHETIC


def test_complete_approved_real_package_is_granted_for_connection():
    package = _complete_approved_real_package()
    result = enforce_real_data_readiness(package, requested_optimization="connection")
    assert isinstance(result, RealDataReadinessGranted), result
    assert result.readiness.classification == DatasetClassification.REAL


def test_complete_approved_real_package_is_granted_for_drilling_location():
    package = _complete_approved_real_package()
    result = enforce_real_data_readiness(package, requested_optimization="drilling_location")
    assert isinstance(result, RealDataReadinessGranted), result


def test_incomplete_real_package_returns_data_requirements_not_met():
    package = build_intentionally_incomplete_real_package()
    result = enforce_real_data_readiness(package, requested_optimization="connection")
    assert isinstance(result, DataRequirementsNotMet)
    assert result.failure_code == "DATA_REQUIREMENTS_NOT_MET"
    assert RealDataRequirement.SPATIAL_CRS in result.missing_requirements
    assert RealDataRequirement.PIPE_ATTRIBUTES in result.missing_requirements
    assert RealDataRequirement.PROVENANCE_OR_LICENSING in result.missing_requirements
    assert RealDataRequirement.APPROVAL_STATUS in result.missing_requirements
    assert RealDataRequirement.ECONOMICS_AND_PLANNING in result.missing_requirements
    # Sorted, deduplicated -- never one entry per individual field error.
    assert result.missing_requirements == sorted(set(result.missing_requirements), key=lambda r: r.value)


def test_incomplete_real_package_never_silently_falls_back_to_synthetic():
    """The failure result must echo the package's OWN classification
    (via readiness.classification) unchanged -- never silently relabel a
    real package as synthetic to make it pass."""
    package = build_intentionally_incomplete_real_package()
    result = enforce_real_data_readiness(package, requested_optimization="connection")
    assert isinstance(result, DataRequirementsNotMet)
    assert result.readiness.classification == DatasetClassification.REAL


def test_missing_geothermal_scenarios_denies_a_real_package_for_both_optimization_kinds():
    """geothermal_scenarios is one of generate_readiness_report()'s own
    required top-level sections for ANY real package (missing_datasets),
    not only a drilling-specific requirement -- so an empty list denies
    BOTH 'connection' and 'drilling_location' for a real package, each
    naming GEOTHERMAL_SCENARIOS. (A synthetic package is unaffected: it is
    always granted regardless, per generate_readiness_report()'s own
    OPT-006 policy -- see test_synthetic_package_is_always_granted.)"""
    complete = _complete_approved_real_package()
    package = complete.model_copy(update={"geothermal_scenarios": []})
    for kind in ("connection", "drilling_location"):
        result = enforce_real_data_readiness(package, requested_optimization=kind)
        assert isinstance(result, DataRequirementsNotMet), (kind, result)
        assert RealDataRequirement.GEOTHERMAL_SCENARIOS in result.missing_requirements


def test_json_round_trip_for_both_outcomes():
    granted = enforce_real_data_readiness(build_synthetic_sample_package(), requested_optimization="connection")
    denied = enforce_real_data_readiness(
        build_intentionally_incomplete_real_package(), requested_optimization="connection",
    )
    round_tripped_granted = parse_real_data_readiness_result_json(granted.model_dump_json())
    round_tripped_denied = parse_real_data_readiness_result_json(denied.model_dump_json())
    assert isinstance(round_tripped_granted, RealDataReadinessGranted)
    assert isinstance(round_tripped_denied, DataRequirementsNotMet)
