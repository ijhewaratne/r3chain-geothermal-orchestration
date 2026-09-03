# T5.1C — run-ID / hash divergence diagnosis (preliminary Code run)

Comparing `fixtures/pydoublet/repaired_result.json` (the canonical fixture) against the preserved
run's `pydoublet_input.json` (`bundle/pydoublet_input.json`), run `r3chain-run-160ff2195378cdc4`.
Full machine-readable version: `hash-diagnosis.json`.

## Root cause, precisely (not "using an inline tool parameter")

The MCP tool schema for `geo_validate_pydoublet_result`/`geo_run_workflow` requires the raw
PyDoublet result as an inline JSON object parameter, not a file path. When I supplied that
parameter, I hand-transcribed the fixture's JSON text rather than passing its exact bytes, and
introduced two classes of divergence in doing so:

1. **19 int-vs-float representation differences.** `src/r3chain_geothermal/hashing.py`'s
   canonical encoder is `json.dumps(raw_result, sort_keys=True, separators=(",", ":"))`. Python's
   `json` module serializes `int` and `float` differently even when numerically equal:
   `json.dumps(40.0) == "40.0"` but `json.dumps(40) == "40"`. Several source-file literals that
   are written with a decimal point (e.g. `"pressure_difference_bar": 40.0`) were typed by me as
   bare integers (`40`). `normalize_for_scientific_hash` (rule version `1.0.0`) does **not**
   correct for this — by its own docstring, it only ever strips keys literally named
   `created_at`; recomputing the scientific hash for either input changes nothing
   (`scientific_normalized_sha256_fixture == canonical_raw_result_sha256_fixture`, likewise for
   `run_input`).
2. **1 real structural difference.** `/simulation_results/producer_well/salinity_profile_kg_per_kg`
   has 55 elements in the fixture (matching `node_count: 55`) but only 54 in my typed payload —
   an actual dropped array element from manual transcription, not a representation artifact.

Recomputing the project's own hash function directly confirms this is the entire explanation —
no other mechanism is involved:

| | value |
|---|---|
| `canonical_raw_result_sha256(fixture)` | `6c42d3368883070cd177ecb02572480d3aab4238e4781357b78c742cec642762` |
| `canonical_raw_result_sha256(run_input)` | `34deec7c58480d59346adecfc15e17fd564c6648f6990843ebb6d5590caa11cf` |

The fixture's hash exactly matches the "pinned fixture canonical hash" already on record in
`CODEX_REPOSITORY_ASSESSMENT.md` §7 (an independent cross-check I did not engineer); the run
input's hash exactly matches the `raw_result_sha256` the live MCP server actually returned during
the calls — confirming both values are genuine, not transcribed by hand into this report.

## Why `run_id` and `bundle_scientific_sha256` differ

`workflow/core.py:compute_run_id()`:

```
run_id = "r3chain-run-" + canonical_raw_result_sha256({
    "input_sha256": <input hash>,
    "config_sha256": <config hash>,
    "source_provenance_sha256": <provenance hash>,
    "contract_schema_version": <schema version>,
})[:16]
```

`config_sha256` and `source_provenance_sha256` are identical between the two runs (same committed
`config/demo_assumptions.json`, same literal `config/demo_source_provenance.json` content) —
`input_sha256` is the only one of the four inputs to this formula that differs. That single
difference is sufficient to change `run_id` and, downstream, `bundle_scientific_sha256`, even
though every consumed physical/economic value is identical.

## Consumed-field check against the actual parser — corrected finding

`src/r3chain_geothermal/parsers/pydoublet_parser.py` resolves exactly 12 JSON Pointers. Checking
all 20 pointer-level diffs against that list:

- **1 of the 20 diffs lands on a consumed pointer**: `/surface_installations/heat_exchanger/exit_temperature_c`
  (`35.0` vs `35`) — an **int/float representation difference only**, not a value difference. The
  adapter's own typed field coerces both to the identical float `35.0`; this was independently
  confirmed live, since both `geo_validate_pydoublet_result` calls in the prior turn returned
  `geothermal_brine_hx_outlet_temperature_c: 35.0` identically regardless of which payload was
  sent.
- **The other 19 diffs (18 representation-only + the 1 structural salinity-array difference) all
  land outside the 12 consumed pointers** — including `temperature_profile_c/2` (the
  legacy-fallback pointer), which is untouched; only index 3 (unconsumed) differs.
- **Zero value-changing differences touch any consumed pointer.**

I stated during planning that "zero of the 20 diff pointers intersect any consumed pointer" —
that was imprecise. The corrected, code-verified statement is: **one consumed pointer has a
differing textual representation, but zero consumed pointers have a differing effective value.**

**Full resolution, verified against the running code — see `consumed-pointer-resolution.md`**:
exact pointer, both raw values/types, parser classification (primary/fallback/conditional),
proof that the parser's own `float()` coercion normalizes both to an identical typed value, proof
that the two full `PyDoubletCouplingResult` objects are equal on every scientific field, and proof
that the two complete downstream `run_workflow()` results are equal on every computed HX/network/
economics/ranking value with zero unexplained differences.

## Conclusion

The two inputs are **scientifically equivalent under the current parser**: no consumed field
resolves to a different effective value under either input. They are not byte- or
hash-identical, and the one real content difference (the truncated salinity array) happens to
fall outside every pointer the parser actually reads. This is the same "scientifically
equivalent, differently hashed" pattern already documented in this project's own prior assessment
(`CODEX_REPOSITORY_ASSESSMENT.md` §7) for a separate historical case — reproduced here exactly,
with the mechanism now pinned to specific code (`hashing.py`'s `json.dumps` int/float behavior)
rather than asserted.
