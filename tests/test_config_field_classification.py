"""Mechanical evidence for docs/config-field-classification.md (Phase 6):
removing every field that document classifies as DESCRIPTIVE must leave
config/demo_assumptions.json still structurally valid (validate_config_
structure() must not raise) -- proving these fields genuinely have no
executable effect, rather than merely asserting it in prose.

Deliberately NOT a test that the canonical config's own descriptive
fields still exist (that would just re-assert the file's own content);
this test proves the STRUCTURAL claim -- that the config loader has no
dependency on them -- by actually deleting them and re-validating.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from r3chain_geothermal.workflow import validate_config_structure

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _ROOT / "config" / "demo_assumptions.json"


def _config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _delete_path(config: dict, dotted_path: str) -> None:
    """Deletes dotted_path from config in place, raising KeyError if any
    segment is absent (a canary against this test silently no-op'ing on a
    path that no longer matches the config's own structure)."""
    parts = dotted_path.split(".")
    node = config
    for part in parts[:-1]:
        node = node[part]
    del node[parts[-1]]


_DESCRIPTIVE_PATHS = [
    # _meta: entirely descriptive.
    "_meta.description",
    "_meta.pressure_convention",
    "_meta.changelog",
    # pydoublet: only energy_consistency_tolerance_fraction is executable.
    "pydoublet.example_config",
    "pydoublet.producer_wellhead_temperature",
    "pydoublet.scenario_identity",
    "pydoublet.calculation_mode_policy",
    "pydoublet.legacy_run_count_correction",
    "pydoublet.reinjection_temperature_relocation_note",
    # network: several fields that look configurable but are not read.
    "network.atmospheric_pressure_bar",
    "network.fluid",
    "network.min_pressure_bar_abs",
    "network.min_pressure_note",
    "network.mirrored_return_network",
    "network.pressure_reference",
    "network.total_demand_kw",
    "network.geometry",
    # candidates.list: the predefined C1-C4 topology is hardcoded elsewhere.
    "candidates.list",
    "candidates._note",
    "candidates._status",
    # gates: descriptive duplicates/unused toggles.
    "gates.pressure_reference",
    "gates.pydoublet_energy_consistency_tolerance_fraction",
    "gates.require_sequential_thermal_convergence",
    # coupling_assumptions: descriptive duplicates of the gates.* values.
    "coupling_assumptions.velocity_limit_m_s",
    "coupling_assumptions.pump_dp_limit_bar",
    "coupling_assumptions.consumer_supply_drop_limit_k",
    "coupling_assumptions.mass_balance_tolerance_fraction",
    "coupling_assumptions.energy_balance_tolerance_fraction",
    "coupling_assumptions.auxiliary_policy_options",
    # economics: descriptive-only ranking policy fields.
    "economics.ranking_rule",
    "economics.tie_breakers",
]


def test_canonical_config_is_valid_before_any_deletion():
    """A sanity baseline -- if this ever fails, every test below is
    meaningless (it would mean the canonical config is already broken,
    unrelated to this test file)."""
    validate_config_structure(_config())  # must not raise


def test_removing_every_descriptive_field_at_once_leaves_the_config_valid():
    config = _config()
    for path in _DESCRIPTIVE_PATHS:
        _delete_path(config, path)
    validate_config_structure(config)  # must not raise


def test_each_descriptive_field_is_individually_removable():
    """Isolates the claim per-field (rather than only the bulk-removal
    claim above), so a future regression names the exact field that
    turned out to be executable after all."""
    for path in _DESCRIPTIVE_PATHS:
        config = _config()
        _delete_path(config, path)
        try:
            validate_config_structure(config)
        except Exception as exc:  # noqa: BLE001 -- re-raised with the offending path attached
            raise AssertionError(f"removing {path!r} unexpectedly broke config validation: {exc}") from exc


def test_removing_an_executable_field_does_break_validation():
    """The mirror-image control: proving _delete_path()/validate_config_
    structure() actually detect a REAL dependency, not merely never
    raising for anything -- otherwise the two tests above would be
    vacuous."""
    config = _config()
    _delete_path(config, "gates.max_pipe_velocity_m_s")
    raised = False
    try:
        validate_config_structure(config)
    except Exception:
        raised = True
    assert raised, "removing an EXECUTABLE field (gates.max_pipe_velocity_m_s) must break validation"
