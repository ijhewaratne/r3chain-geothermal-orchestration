"""Dedicated unit tests for hashing.normalize_for_scientific_hash() (T2.4B2)
-- the versioned rule that distinguishes byte_sha256 from scientific_sha256
in workflow/artifacts.py. Everything else in hashing.py (canonical_raw_result_*)
is already covered indirectly by parsers/test_pydoublet_parser.py and
contracts/test_coupling_result.py."""
from __future__ import annotations

from r3chain_geothermal.hashing import (
    SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES,
    SCIENTIFIC_NORMALIZATION_RULE_VERSION,
    canonical_raw_result_sha256,
    normalize_for_scientific_hash,
)


def test_removes_top_level_created_at():
    assert normalize_for_scientific_hash({"created_at": "2026-01-01T00:00:00Z", "value": 1}) == {"value": 1}


def test_removes_created_at_at_every_nesting_depth():
    payload = {
        "created_at": "top",
        "outer": {
            "created_at": "mid",
            "inner": {"created_at": "deep", "value": 42},
        },
        "list_of_objects": [
            {"created_at": "a", "x": 1},
            {"created_at": "b", "x": 2},
        ],
    }
    normalized = normalize_for_scientific_hash(payload)
    assert normalized == {
        "outer": {"inner": {"value": 42}},
        "list_of_objects": [{"x": 1}, {"x": 2}],
    }


def test_does_not_remove_fields_with_different_names():
    payload = {
        "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
        "source_timestamp": "2026-01-01T00:00:00Z",
        "source_provenance": {
            "source_pydoublet_commit": "0" * 40,
            "source_format_hint": "known_repaired",
            "calculation_mode": "deterministic",
            "scenario_identifier": None,
        },
        "warnings": ["some warning"],
        "assumptions": {"minimum_hx_approach_k": 5.0},
        "results": {"geothermal_thermal_power_kw": 4345.417312},
    }
    assert normalize_for_scientific_hash(payload) == payload


def test_does_not_mutate_input():
    payload = {"created_at": "x", "nested": {"created_at": "y", "value": 1}}
    original_repr = dict(payload)
    normalize_for_scientific_hash(payload)
    assert payload == original_repr
    assert payload["nested"]["created_at"] == "y"


def test_scalars_and_none_pass_through_unchanged():
    for value in (None, 1, 1.5, "text", True, False):
        assert normalize_for_scientific_hash(value) == value


def test_bare_list_of_scalars_is_unchanged():
    assert normalize_for_scientific_hash([1, "a", None, 2.5]) == [1, "a", None, 2.5]


def test_key_named_created_at_nested_inside_a_list_inside_a_list_is_removed():
    payload = [[{"created_at": "x", "value": 1}], [{"value": 2}]]
    assert normalize_for_scientific_hash(payload) == [[{"value": 1}], [{"value": 2}]]


# ── The behavior artifacts.py actually relies on: hashing changing only
#    when scientific content changes, not when only created_at changes. ──
def test_changing_only_created_at_preserves_the_hash():
    payload_1 = {"created_at": "2026-01-01T00:00:00Z", "value": 1, "nested": {"created_at": "a"}}
    payload_2 = {"created_at": "2027-06-15T12:30:00Z", "value": 1, "nested": {"created_at": "b"}}
    hash_1 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_1))
    hash_2 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_2))
    assert hash_1 == hash_2


def test_changing_a_scientific_value_changes_the_hash():
    payload_1 = {"created_at": "2026-01-01T00:00:00Z", "value": 1}
    payload_2 = {"created_at": "2026-01-01T00:00:00Z", "value": 2}
    hash_1 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_1))
    hash_2 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_2))
    assert hash_1 != hash_2


def test_changing_a_timestamp_field_not_named_created_at_changes_the_hash():
    """source_timestamp, /metadata/timestamp and every SourceProvenance
    field are genuine provenance content (module docstring) -- unlike
    created_at, changing them MUST change the scientific hash."""
    payload_1 = {"source_timestamp": "2026-01-01T00:00:00Z", "value": 1}
    payload_2 = {"source_timestamp": "2027-01-01T00:00:00Z", "value": 1}
    hash_1 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_1))
    hash_2 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_2))
    assert hash_1 != hash_2


def test_normalization_rule_version_is_a_non_empty_string_constant():
    assert isinstance(SCIENTIFIC_NORMALIZATION_RULE_VERSION, str)
    assert SCIENTIFIC_NORMALIZATION_RULE_VERSION


# ── Phase 2 (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md, release
#    blocker): cross-platform floating-point-noise quantization. See
#    SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES's own docstring for the
#    full macOS/Linux diagnosis this addresses. ──
def test_a_sub_ulp_scale_float_difference_produces_the_same_hash():
    """Simulates the diagnosed macOS-vs-Linux BLAS/LAPACK noise directly:
    two floats that are "the same" converged physical value but differ
    far beyond SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES significant
    figures (here, at the 15th) must hash identically after
    normalization."""
    value = 4345.417312083
    noisy_value = value + 1e-9  # perturbs only the 13th+ significant figure
    assert value != noisy_value  # the raw floats really are different
    payload_1 = {"geothermal_thermal_power_kw": value}
    payload_2 = {"geothermal_thermal_power_kw": noisy_value}
    hash_1 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_1))
    hash_2 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_2))
    assert hash_1 == hash_2


def test_a_genuinely_different_float_value_still_changes_the_hash():
    """The quantization must never mask a REAL result change -- a
    difference at the 5th significant figure (far coarser than even this
    project's loosest 2% gate tolerance) must still change the hash."""
    payload_1 = {"geothermal_thermal_power_kw": 4345.417312}
    payload_2 = {"geothermal_thermal_power_kw": 4345.517312}
    hash_1 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_1))
    hash_2 = canonical_raw_result_sha256(normalize_for_scientific_hash(payload_2))
    assert hash_1 != hash_2


def test_float_quantization_never_touches_integers_or_booleans():
    """Only `float` values are quantized -- `int` is always numerically
    exact and `bool` (an `int` subclass in Python) must never be treated
    as a float."""
    payload = {"count": 5, "enabled": True, "disabled": False}
    assert normalize_for_scientific_hash(payload) == payload
    normalized = normalize_for_scientific_hash(payload)
    assert type(normalized["count"]) is int
    assert type(normalized["enabled"]) is bool


def test_float_quantization_preserves_values_within_the_significant_figure_budget():
    """A value with exactly SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES (or
    fewer) significant figures must round-trip unchanged -- quantization
    only ever discards noise beyond the budget, never legitimate
    precision within it."""
    assert SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES >= 10  # the budget this test relies on
    payload = {"value": 4345.417312}  # exactly 10 significant figures
    assert normalize_for_scientific_hash(payload) == payload


def test_scientific_hash_float_significant_figures_is_documented_and_stable():
    assert isinstance(SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES, int)
    assert SCIENTIFIC_HASH_FLOAT_SIGNIFICANT_FIGURES == 12
