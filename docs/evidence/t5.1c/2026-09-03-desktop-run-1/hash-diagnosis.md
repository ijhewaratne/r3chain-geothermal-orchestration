# T5.1C Desktop run — hash/run-ID diagnosis

`run_id = r3chain-run-efdb9cd8625c4b61`. Full machine-readable version: `hash-diagnosis.json`.

## Finding: a third distinct input hash, same root cause, same conclusion

This Desktop run's `pydoublet_input.json` hashes to `02530b29...` — **different from both** the
pinned golden reference (`6c42d336...`) **and** the preliminary Claude Code run (`34deec7c...`).
20 RFC 6901 pointer-level differences against the canonical fixture, applying the exact same
diff methodology as `../2026-08-31-preliminary-code-run/hash-diagnosis.md`:

- 18 int-vs-float representation differences (bare integers where the fixture has a decimal
  point — e.g. `/surface_installations/pump/pressure_difference_bar`: `40.0` vs `40`)
- 2 array-length differences: `/simulation_results/producer_well/salinity_profile_kg_per_kg`
  (55 vs 54, same direction as the Code run) **and**
  `/simulation_results/injector_well/environment_temperature_c` (54 vs 55 — a *new* length
  difference not present in the Code run's transcription, in the opposite direction)

**This means the drift is not specific to me (Claude Code) hand-typing a payload.** An
independent Claude Desktop conversation, generating its own tool-call arguments for the same
`geo_validate_pydoublet_result`/`geo_run_workflow` calls, produced a *third*, differently-drifted
transcription of the same underlying file. The most defensible reading: because
`geo_validate_pydoublet_result`'s MCP tool schema requires the raw PyDoublet result as an inline
JSON object argument (not a file path or content hash), **any LLM-mediated call to this tool —
regardless of which Claude surface originates it — requires the calling model to reproduce a
large numeric payload token-by-token as part of its own function-call output**, and that
reproduction is not guaranteed to preserve int/float literal formatting or exact array length for
very long numeric arrays. This looks like a structural property of the current tool schema
design, not a one-off transcription mistake.

## Same rigorous verification as the Code run — repeated in full, same result

- **1 of 12 consumed pointers differs**: `/surface_installations/heat_exchanger/exit_temperature_c`
  (`35.0` vs `35`) — representation only.
- **Parser normalization confirmed**: `parse_pydoublet_result()` run directly on both inputs;
  the typed field is `35.0`/`float` on both sides.
- **Typed `PyDoubletCouplingResult` objects equal on every field except `result_identifier`**
  (expected — derived from the differing raw-byte hash, not a scientific quantity).
- **Full downstream `run_workflow()` comparison**: 46 raw diff entries, **all classified, zero
  left over** — 24 timestamps, 12 hash/identifier bookkeeping, 10 instances of the known
  unconsumed array-length differences surfacing in the embedded raw-result copy.
- **Every candidate's `economics` object and `feasible` flag (C1–C4) is dict-equal** between the
  fixture and this Desktop run's actual input.
- **Conclusion: scientifically equivalent under the current parser — zero value-changing
  differences on any consumed pointer.** Identical to the Code run's conclusion, independently
  re-derived from a different (and differently-drifted) input.

## `config_sha256` / `source_provenance_sha256` — unchanged across all three runs

Both are byte-identical to the golden reference and to the preliminary Code run
(`config_sha256 = 2bdfd11d...`, `source_provenance_sha256 = 58190a4a...`) — confirmed directly
from `audit.json`. `input_sha256` is the only one of the four run-ID inputs that varies, which is
why `run_id` differs across all three runs while every computed result is identical.
