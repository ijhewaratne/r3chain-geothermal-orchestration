# ADR-002 — Producer wellhead temperature source and fallback policy

- **Status:** Accepted for the prototype. Domain-owner (Dr. Jan Niederau)
  confirmation pending.
- **Date:** 2026-08-20
- **Decider:** Ishantha Hewaratne
- **Informed by:** Phase-0 Q2 (`docs/decisions/phase0-questions.md`); the
  T1.4C2 temperature-field investigation and its evidence trail; PyDoublet
  commits `afdb036f9b78d8597319ae22eecb3ffc0e2d689f` (metadata correction),
  `4b29d1a0b37094543a436e33aba459558fbeb9eb` (named field added),
  `0d649c3e6930d342dac03654d57776e134c2d0b9` (explicit-path test coverage),
  all on `repos/PyDoublet` branch `feature/pydoublet-integration`.

## Context

Phase-0 Q2 asked which explicit PyDoublet variable is the producer wellhead/
surface temperature. Before the repair, no named field existed — the value
was only reachable at `/simulation_results/temperature_profile_c/2`
(RFC 6901 JSON Pointer), an undocumented array position. The T1.4C2 investigation traced this value from its physical
source to export and found converging, verifiable evidence (see below). The
PyDoublet packaging repair then added an additive, explicitly named field
sourced directly from that evidence, not by copying the legacy index.

This ADR records the resulting source-of-truth and fallback policy for any
code (the future geothermal adapter, in a later task) that needs the producer
wellhead temperature from a PyDoublet result.

## Decision

### Primary source

- **Field path (RFC 6901 JSON Pointer):** `/simulation_results/producer_wellhead_temperature_c`
- **Unit:** °C
- **Physical meaning:** the producer wellhead/surface temperature — the
  brine temperature at the top of the producer well (depth 0 m), after
  conductive heat loss along the well tubing has been solved for, and
  **before** the surface heat exchanger.
- **Source evidence:**
  1. Sourced directly from `/simulation_results/producer_well/temperature_profile_c/0`
     (`well_tubing.temperature_node[0]`) — the producer well's own
     temperature profile at its own node 0 — not derived from
     `/simulation_results/temperature_profile_c/2`.
  2. `/simulation_results/producer_well/depth_profile_m/0 == 0.0` — a direct,
     non-inferential depth-coordinate proof that node 0 is the surface/wellhead.
  3. `doc/examples.rst` independently documents the identical convention
     elsewhere in this project ("Producer wellhead pressure:
     `profiles['producer_pressure_profile'][0]`").
  4. Numerically cross-checked bit-identical against the committed golden
     fixture and against the legacy `/simulation_results/temperature_profile_c/2`
     value.
- **PyDoublet commit that introduced this field:**
  `4b29d1a0b37094543a436e33aba459558fbeb9eb`.

### Legacy source (fallback only)

- **Field path (RFC 6901 JSON Pointer):** `/simulation_results/temperature_profile_c/2`
- Present in every PyDoublet result, pre- and post-repair (additive change —
  nothing was removed). Numerically identical to the primary field wherever
  both exist, by construction of the repair.

### Fallback policy

1. **Primary preferred:** if `producer_wellhead_temperature_c` is present,
   use it. No fallback logic runs.
2. **Legacy fallback — allowed only for recognized pristine/legacy results:**
   if the primary field is absent **and** the input is recognizable as a
   pristine/pre-repair PyDoublet result (no `producer_wellhead_temperature_c`
   key, and the rest of the schema matches the documented pre-repair
   structure — see `fixtures/pydoublet/raw_result.json` /
   `fixtures/pydoublet/provenance.md` for the reference shape), the adapter
   may fall back to `/simulation_results/temperature_profile_c/2`.
3. **Every fallback must emit an audit warning** with code
   `LEGACY_PYDOUBLET_TEMPERATURE_INDEX_FALLBACK`, and must retain the
   original, unmodified raw PyDoublet result alongside the extracted value —
   never silently substitute without a traceable record.
4. **A post-repair result missing the named field is a validation failure,
   not a fallback candidate.** If the input is expected to come from the
   repaired PyDoublet (i.e., not recognized as the pristine/legacy shape) but
   lacks `producer_wellhead_temperature_c`, this indicates something
   unexpected (a corrupted export, a regressed PyDoublet version, or a
   caller error) and must be rejected, not quietly patched over by reading
   the legacy index.

This two-branch policy — legacy-recognized vs. repaired-but-broken — exists
specifically so a genuine defect in a supposedly-repaired PyDoublet never
gets masked by the fallback meant only for genuinely old inputs.

## Consequences

- The future geothermal adapter (a later, separately-approved task) must
  implement this exact primary/fallback/validation-failure logic rather than
  inventing its own index-based extraction. `config/demo_assumptions.json`
  records this policy as data (`pydoublet.producer_wellhead_temperature`) for
  the adapter to read.
- The committed pristine fixture
  (`fixtures/pydoublet/raw_result.json`) is a permanent, correct example of
  the "recognized legacy result" case — it has no primary field and must
  continue to trigger the fallback path (with its warning) if ever run
  through the adapter, not a validation failure.
- Dr. Jan's confirmation, once received, will either close Q2 outright or
  require a correction to this ADR — this document does not claim that
  confirmation has occurred.
- This ADR does not amend ADR-001; it is additive documentation of a data
  contract detail, consistent with ADR-001 D8 (assumptions live in
  configuration, replaceable without code changes).
