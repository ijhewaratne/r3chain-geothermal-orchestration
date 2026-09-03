# Issue: enforce input provenance for `geo_validate_pydoublet_result` / `geo_run_workflow`

**Status**: specification only, not implemented. Discovered during T5.1C acceptance evidence
(`docs/evidence/t5.1c/T5.1C-FINAL-ACCEPTANCE.md`, "Remaining open item").

## Problem

`geo_validate_pydoublet_result` and `geo_run_workflow` accept the raw PyDoublet result as an
inline JSON object argument, with no way to assert which file or prior artifact it is supposed to
be. Across three independent attempts to run the T5.1C acceptance sequence (one from a Claude
Code session, two from separate Claude Desktop conversations), every single one produced a raw
input that differs from the canonical `fixtures/pydoublet/repaired_result.json` — two by
transcription drift, one by apparently reusing a previously-preserved evidence artifact
(`pydoublet_input.json` from an earlier run) instead of a fresh read of the canonical fixture.
Every one of these instead-of-canonical inputs is scientifically equivalent under the current
parser and was correctly validated and accepted. Nothing in the system currently distinguishes
"the calling agent used the intended canonical file" from "the calling agent used something else
that happens to compute to the same answer" — and there is no mechanism to catch the second case
even when a caller *believes* it attached the canonical file.

This is not a physics or economics defect. The scientific result is unaffected in every case seen
so far. The gap is one of **auditable input provenance**: a workflow run's evidentiary value
partly depends on which file produced it, and that currently cannot be verified independently of
trusting the calling agent's own narration.

## Exact raw hash vs. scientific-equivalence hash — the distinction this issue is about

The project already has two different content identities for a raw PyDoublet result
(`src/r3chain_geothermal/hashing.py`):

- `canonical_raw_result_sha256` — a canonical-JSON hash of the *exact* raw structure as given,
  sensitive to int/float representation, key presence, and array length. Two inputs that are
  scientifically identical but differently transcribed hash differently here.
- `normalize_for_scientific_hash` — strips only literal `created_at` keys; it does **not**
  normalize numeric representation or unused-subtree differences, so in practice it produces the
  same value as the raw hash for the transcription-drift cases seen so far.

Neither of these answers "was this the file I meant to send." Both are hashes of *whatever was
sent*, not a comparison against *what should have been sent*. This issue proposes adding the
latter as an optional, explicit check — without changing either existing hash's meaning or
computation.

## Proposed change

Add an optional expected-hash field the caller can supply alongside the raw result, e.g.
`expected_raw_sha256: str | None` on `SourceProvenance` (or as a separate optional parameter on
`geo_validate_pydoublet_result` / `geo_run_workflow` — implementation detail, not decided here).
When present:

- The server computes `canonical_raw_result_sha256` on the actual raw payload received, exactly
  as today.
- If it does **not** match `expected_raw_sha256`, the call fails with a typed mismatch error
  (see below) instead of proceeding.
- If it matches, or if `expected_raw_sha256` is omitted, behavior is unchanged from today.

This lets a caller who *does* have a canonical reference hash (e.g. a workshop script, a CI
harness, or a careful human pinning the fixture's known hash in their prompt) get a hard
guarantee instead of a hopeful assumption — while callers who don't know or care about a specific
hash (the common case today) see no behavior change at all.

## Typed mismatch error

A new failure code, following the existing `FailureCode` pattern in
`src/r3chain_geothermal/contracts/coupling_result.py` / `src/r3chain_geothermal/parsers/pydoublet_parser.py`:

```
code: "PYDOUBLET_INPUT_PROVENANCE_MISMATCH"
message: "Raw result's canonical hash <actual> does not match expected_raw_sha256 <expected>."
stage: "parse_pydoublet_result"  (or a new dedicated stage, e.g. "provenance_check")
recoverable: false
```

`recoverable: false` because retrying with the *same* mismatched input will not help — the
caller needs to supply the correct file, not retry the call. Include both hash values in the
error detail so the caller can diagnose which artifact they actually sent.

## No silent substitution

The server must never attempt to "fix" a mismatch by substituting the expected canonical content,
falling back to a cached prior run, or silently proceeding with a warning instead of an error.
A provenance mismatch is a hard failure when `expected_raw_sha256` is supplied — the same
philosophy as the existing "no unexplained fallback" pattern already used for the legacy
temperature-pointer handling (ADR-002).

## Backward compatibility

- `expected_raw_sha256` is optional and absent by default. Every existing caller, test, and
  fixture that does not supply it sees byte-for-byte identical behavior to today.
- No existing contract field, error code, or hash computation changes meaning.
- No change to `config/demo_assumptions.json`, any fixture, or any pinned golden value.

## Security considerations for any future file-path-based input

If a future revision of this tool schema accepts a file path or URI instead of (or in addition
to) an inline JSON object — a natural follow-on to this issue, since it would let a caller
reference the canonical fixture without re-transcribing it — that change must separately address:

- **Path traversal**: reject any path escaping an explicitly configured allow-listed directory;
  no `..`-walking, no absolute-path escape.
- **Symlink following**: resolve and re-validate the real path before reading; do not trust a
  symlink inside an allow-listed directory to point outside it.
- **Size limits**: bound the maximum file size read, to avoid a pathological or malicious huge
  file being read into memory.
- **No arbitrary URL/network fetch**: file-path input must mean local filesystem only, not a
  general-purpose fetch primitive.

These are out of scope for *this* issue (which only adds an optional expected-hash check against
an inline payload) but should be designed together if file-path input is ever proposed.

## Required test coverage

- **Unit**: `expected_raw_sha256` present and matching → unchanged success. Present and
  mismatching → `PYDOUBLET_INPUT_PROVENANCE_MISMATCH`, `recoverable: false`, both hashes in the
  error detail. Absent → unchanged current behavior (regression guard).
- **Contract**: the new failure code is added to whatever enumerates/tests exhaustive
  `FailureCode` coverage today, so it can never silently drift out of sync with the schema.
- **End-to-end**: a full `geo_run_workflow` call with a deliberately mismatched
  `expected_raw_sha256` against the canonical fixture fails at the provenance-check stage before
  any pandapipes computation runs (no wasted solve, no partial run persisted).

## Explicit non-goal

This issue does not touch PyDoublet physics, the adapter's heat-exchanger logic, network
evaluation, economics, or ranking. It adds one optional, purely additive input-integrity check at
the parsing boundary. No scientific assumption, gate, formula, or default changes.
