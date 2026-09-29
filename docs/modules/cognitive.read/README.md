# cognitive.read development entry point

## Current source candidate, 2026-09-29

The ordinary owner and Agentd selected-cut integration is materialized in
commit `fb6d8dc76579ac2b00e23c15cc4508e684c335b8`. It is not waiting for a source
repair script to create the product caller. This is a source candidate, not a
successful Rust, exact-merge, production or release receipt.

Read the documents together:

- `TECHNICAL.md`: stable module identity, ownership, contracts and historical
  compatibility APIs. The legacy full-scope owner API still exists.
- `FINAL_USE_CLOSURE.md`: publication-plan integrity, fresh final-use evaluation,
  cancellation/error metrics, opaque-binding compatibility and delivery gaps.
- `SELECTED_OWNER_CUT.md`: bounded selected-ID owner materialization, ordinary
  Agentd composition, supplementary global currentness witness and capacity
  limits that remain.
- `STRUCTURAL_REUSE.md` and `CONTRACT_LIMITS.md`: unchanged request-local reuse,
  exact-ID all-or-error semantics and full construction budgets.
- `CONSUMER_EXECUTION.json`: distinct states of the seven registered consumers;
  these are not upgraded by this source change.
- `QUALIFICATION_CLOSURE.md` and `OPERATIONS.md`: required execution evidence and
  operating contract. The new phase/outcome metric details are in
  `FINAL_USE_CLOSURE.md`.

The previous whole-scope Agentd path description in the stable guide is
superseded for this candidate by the explicit selected-owner supplement. The
full-scope and page APIs themselves are not removed or reinterpreted. Runtime
currentness and authorization are not cached; native unknown-send handling is
unchanged and remains reconciliation-only.

## What changed and what did not

| Area | Current candidate |
| --- | --- |
| Planning | Publication fields and owner/generation are bound; physical use evaluates a fresh plan after current owner checks. |
| Selected owner reads | Normal Agentd read and final-use paths call the existing owner's exact-ID materializer. |
| Capacity | Whole unselected history is not materialized; selected ancestry and output remain bounded. Global counters/head metadata scanning remain. |
| Observability | Rejected and abandoned attempts contribute to latency and bounded final-use failure counters. |
| Delivery learning | The legacy assignment row is explicitly preparation evidence; a complete downstream delivery/model-use join is still open. |
| Consumers | No blanket V2 migration, activation or independent acceptance claim. |
| Verification | New Rust tests exist; current Rust/format/lint/source-map/source-and-merge execution remains pending. |

## Executed local checks

The four integrated files were reconstructed from exact remote blobs before
applying the reviewed transformation. Their resulting remote blob identities
were compared with the local expected identities:

| Source | Original blob | Integrated blob |
| --- | --- | --- |
| `hepta-memory/src/lane_c_snapshot.rs` | `af66a5195f8a65635abe6c2abaf7b8e265bb6e9d` | `7e22de724d00b0fec2157a73eb659aaddc71ff8c` |
| `hepta-memory/src/lib.rs` | `8d70d05e03095908d324be4bdac396ec681991b4` | `7ed2932d7204cadb27c54029a965ad00c49974e7` |
| `hepta-agentd/src/cognitive_context.rs` | `e5f584c42a1c9cfff13d9b856aab9c4be8e5c125` | `21901ebde09d1e38fbddb2e2316c67749ead7bce` |
| `hepta-agentd/src/cognitive_context_final_use.rs` | `099087299d8275db7344db46a55bff3b310e2180` | `92228bdc7e7b2eaacc649ecd71e93a07696a61fb` |

All paths in that table are below `codex-rs/`. The application transformation
was also checked for idempotence and the Python authoring scripts were syntax
checked. These checks are not Rust compilation.

The capacity fixture SQL was separately exercised using local Python/SQLite
with the relevant ancestry/citation foreign-key structure: 17,001 revision rows,
17,001 citation rows, no foreign-key violations, one row for the small selected
record, and detection of the oversized selected history. This validates fixture
SQL and row-bound behavior only, NOT execution of the Rust owner or product E2E.

## Evidence boundary

The original qualification run `36533405154` failed; inspected logs showed
locked-dependency and formatting blockers. No historical run is reused as a
pass for this candidate. The explicitly scoped source-preparation workflow may
make ordinary lock/format/map commits; it is not the read-only qualification
workflow and cannot certify product execution. Its queue entry is not a pass.

The implementation map must be refreshed to the exact prepared source parent
and checked before acceptance. Full package/Clippy/golden/product suites, both
source-head and deterministic-merge receipts, target-host qualification,
independent review, acceptance and release remain required. All production,
execution-proof, independent-acceptance, activation and release flags remain
false until their own gates are satisfied.
