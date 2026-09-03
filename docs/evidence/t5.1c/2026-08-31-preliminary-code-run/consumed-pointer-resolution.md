# Resolution: the one consumed-pointer difference

This document resolves the correction noted in `hash-diagnosis.md`: my planning-stage statement
that "zero of the 20 diff pointers intersect any consumed pointer" was **incorrect**. One does.
This is verified directly against the running code (not asserted), per each required point below.
Machine-readable version: `consumed-pointer-resolution.json`.

## 1. Exact RFC 6901 pointer
`/surface_installations/heat_exchanger/exit_temperature_c`

## 2. Fixture value and Python type
`35.0` — `float` (as loaded by `json.load` from `fixtures/pydoublet/repaired_result.json`)

## 3. Run-input value and type
`35` — `int` (as loaded by `json.load` from the preserved run's `pydoublet_input.json`)

## 4. Parser field classification
**Primary, unconditional, no fallback.** `parsers/pydoublet_parser.py` resolves this pointer at
line 571 under the comment "Remaining required quantities (all fixed pointers, no legacy path)"
— unlike `producer_wellhead_temperature_c`, which has a primary/legacy-fallback pair, this field
has exactly one source pointer and no conditional branch. Its `FieldProvenance.extraction_mode`
is hard-coded to `"primary"`.

## 5. Does Pydantic (the parser) normalize both to the same value?
**Yes — verified directly.** `_require_finite_number()` (`pydoublet_parser.py:251`) executes
`numeric = float(value)` unconditionally, before any Pydantic validation runs. Calling
`parse_pydoublet_result()` on both raw inputs and reading the resulting typed field:

| | value | type |
|---|---|---|
| fixture (parsed) | `35.0` | `float` |
| run_input (parsed) | `35.0` | `float` |

Values equal: **True**. Types equal: **True**.

## 6. Are the normalized `PyDoubletCouplingResult` objects equal?
**Yes, on every field except one bookkeeping field.** Calling `parse_pydoublet_result()` directly
on both raw inputs (same `SourceProvenance`) and comparing the two resulting objects field-by-field
(excluding `raw_result`, `raw_result_sha256`, `created_at`, `field_provenance` — all definitionally
tied to the raw bytes or wall-clock, not to physics): **every remaining field is equal**, with one
exception — `result_identifier` (`pydoublet-result-6c42d336...` vs `pydoublet-result-34deec7c...`).
This is expected and correct: `result_identifier` is literally derived from `raw_result_sha256`, a
truncated hash of the raw bytes — a provenance/bookkeeping identifier, not a scientific quantity.
It is *supposed* to differ whenever the raw byte hash differs, independent of whether any
scientific value differs.

## 7. Do all downstream HX, network, economics, and ranking results remain identical?
**Yes — verified exhaustively, not sampled.** Called `run_workflow()` directly (the deterministic
core, not through MCP) on both raw inputs with the identical committed config and provenance, then
recursively diffed the two complete `WorkflowBoundaryResult` objects. **41 raw diff entries found,
all classified, zero left over**:

| Classification | Count |
|---|---:|
| Wall-clock `created_at` timestamps (two separate calls, expected) | 24 |
| Hash/identifier bookkeeping directly derived from the differing raw bytes (`result_identifier`, `raw_result_sha256`, `run_id`, `input_sha256`) | 12 |
| The already-known unconsumed `salinity_profile_kg_per_kg` array-length difference, surfacing inside the embedded raw-result copy carried along for audit purposes | 5 |
| **Unclassified / unexplained** | **0** |

Explicitly confirmed on top of the classification: every candidate's `economics` sub-object and
`feasible` flag is dict-equal between the two runs (C1, C2, C3, C4 — all `True`). No computed
temperature, pressure, velocity, mass/energy-balance residual, heat-delivery, CAPEX/OPEX,
annualised-cost, LCOH, or rank value differs anywhere in the full result tree.

## 8. Correction of every prior statement
- `hash-diagnosis.md` already carries the correction (added when this was first noticed): the
  original "zero of the 20 diff pointers intersect any consumed pointer" claim is marked
  incorrect in place, with the corrected statement immediately following it.
- `hash-diagnosis.json`'s `consumed_pointer_diff_hits` / `consumed_pointer_VALUE_CHANGING_diff_hits`
  fields already reflect the corrected 1-hit / 0-value-changing-hit finding.
- No other file in this evidence directory (`run-summary.md`, `desktop-replay-instructions.md`,
  `test-suite-result.md`) ever asserted the "zero intersect" claim — checked directly (`grep`),
  confirmed clean.
- This document is the exhaustive, code-verified resolution requested: the earlier statement was
  imprecise (a pointer-existence check, not a value-equality check); the corrected and now fully
  verified statement is **one consumed pointer differs in raw JSON representation only, the
  parser's own `float()` coercion normalizes it to an identical value before it reaches any
  physics or economics calculation, the two normalized `PyDoubletCouplingResult` objects are
  equal on every scientific field, and the two complete downstream workflow results are equal on
  every computed value with zero exceptions.**

## 9. General principle confirmed
An integer-versus-float difference in a consumed field **can** be scientifically equivalent —
`35` and `35.0` do normalize to the same float here — but that equivalence must be demonstrated
by tracing the actual coercion code and object-level equality, not assumed from the fact that the
numbers are mathematically equal. That tracing is what this document (and its `.json` companion)
now records.
