# Follow-up: original-owner cold handoff admission

## Status and exact source

This is a read-only bridge audit of `d95c8993b5a80d1636aa74f369586e5b75ef420e` (#6081), not an implemented reader or an admission grant. The execution environment was unavailable; no new code execution, process retirement or original acknowledgement is asserted.

Accepted complete ordinary **Adopt = 0**, **NoUpdate = 0**, **daemon-plus-Root cold recovery = 0**.

The concrete TaskLedger producer, retained Dataset and historical Source reader are real. The missing bridge joins the original Objective acknowledgement, original Automation history, original Cell receipt and a genuinely admitted new recipient after A exits.

## 1. The actual Objective acknowledgement point

- [`DurableRunStartJournal::append_outcome`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-learning-ledger/src/run_start.rs#L347) writes the frame and calls `sync_all` at lines 401–405 before returning `RunStartAppendReceipt { sequence, record_digest, chain_digest }` at lines 411–415. This is where the complete original acknowledgement tuple exists.
- [`ObjectiveRuntimeHost::submit_for`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/objective_submission.rs#L194) receives that publication under the original journal mutex. Its outward `ObjectiveRunAdmission` at lines 287–295 retains record/chain digests but omits publication sequence. The [wire struct](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agent-protocol/src/authbus.rs#L61) confirms this. The signed ingress message sequence and Source-journal sequence are different domains.
- [`publication` and `verify_anchor`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-learning-ledger/src/run_start_publication.rs#L18) only read the active journal owner's cached records. They neither reread physical bytes nor retain an independent acknowledgement.
- [`ObjectiveHostState::read_publication`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/objective_history.rs#L35) can return the complete tuple and check an optional caller-retained anchor against that cache. This path does not durably retain that anchor for Root or a later process.
- [`open_run_start_journal`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/objective_runtime.rs#L279) uses read/write/create and `RunStartRecovery::Unacknowledged`. [`recover`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-learning-ledger/src/run_start.rs#L281) may truncate an incomplete tail. Reopening that writer cannot be represented as a cold read.
- [`RootHistoricalSourceInputsV1` / `SourcePin`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/authority_host_historical_source_pin.rs#L28) retain Source journal/witness descriptors, Source sequence/checkpoint and Source publication. They contain no Objective journal descriptor, Objective publication tuple or independent Objective acknowledgement. [`capture_initial_source_pin`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/authority_host_historical_source_pin.rs#L299) observes the Source domain and cannot substitute its pin for Objective ACK.

**Finding:** the inspected ordinary production route has no independently retained durable Objective acknowledgement usable by a cold reader. Default-branch search was only a file locator, not evidence of exact-branch absence; this conclusion follows from the exact owner/receipt/Root data flow above.

## 2. Smallest honest Objective bridge

The following are proposed changes, not existing capabilities.

1. At `objective_submission.rs::submit_for`, retain the complete receipt returned by the successful original append, together with original profile digest, run identity, journal binding and original file custody. Do not accept a tuple reconstructed from the same cold file or supplied as free-form caller data.
2. Send that owner-originated observation through an actual authenticated Root lane bound to the registered old publisher, PID/boot/start identity and exact task scope. Extend the concrete historical-capture owner/session or add a real purpose-specific lane. Root must durably retain the tuple and custody before acknowledging handoff. A conflicting or uncertain capture refuses; reconciliation reads only that same operation.
3. Retain a distinct read-only open description of the original journal and its actual file identity/profile/binding. Keep the acknowledged cut independent of the bytes later checked. The per-run publication's sequence/record/chain must match its exact position in that retained acknowledged prefix.
4. Add a bounded read-only RunStart implementation beside `run_start.rs`, sharing frame validation where possible. Verify header/binding/checksums/sequence/chain/payload and retained tuple. Never create, append, recover, truncate, synthesize an ACK or treat an incomplete suffix as repair permission. In a closed final-cut mode, unacknowledged suffixes refuse.
5. Only the actual Root retirement/new-Starting admission may construct the cross-incarnation capability. Opening a pin or parsing a record proves neither old-publisher retirement nor new-recipient authority. Preserve real PID/boot/start and registration checks.
6. Reuse [`authenticate_learning_source_at`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/objective_learning_source.rs): today's AuthBus trust/revocation validates the original signature at its immutable admission time, rejecting future admission. This does not re-admit the expired task. Recheck physical cut/custody across asynchronous joins. If this route requires durable refusal after observed corruption/withdrawal, the real Root owner must persist and enforce it across reader recreation.

Adding a sequence to the public reply alone still leaves the independent persistent receiver and Root authority route missing. Passing the private receipt to its real owner lane does not by itself require a public wire change.

## 3. Automation: existing read checks versus writer opening

| Existing function | Actual behavior | Cold-handoff implication |
| --- | --- | --- |
| [`AutomationStore::open` / `open_root`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-automation/src/store.rs#L39) | Creates the private directory, opens the evidence pool, reconciles migration IDs, runs migrations, protects the file and inserts metadata if absent. | This is not a read-only reopen and cannot fabricate the old owner. |
| [`read_bounded_circuit_task`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-automation/src/circuit_task_readback.rs#L16) | In one read transaction, replays exact original Created bytes, verifies definition/create-command digests and loads committed history. | Reuse this bounded query only after proving original DB custody. |
| [`circuit_learning_delivery`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-automation/src/circuit_learning_outbox.rs#L108) | Reads the existing outbox row in a transaction. | Preserve exact operation/source/completion/objective comparison and before/after reads. |
| [`enqueue_circuit_learning`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-automation/src/circuit_learning_outbox.rs#L53) | Writes original terminal intent before ordinary ingress acknowledges its result. | A real original event, but not an Objective publication ACK. |
| [`require_database`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/cell_q24_retained_learning_source.rs#L224) | Compares original descriptor and current path's regular-file, link-count, device and inode identity; mismatch fences the live retained source. | Preserve this identity and establish cold custody through actual Root. A connection or copied DB is not ownership. |

A cold observer needs a dedicated constructor that cannot create or migrate, verifies original owner/schema and the retained DB identity, and uses consistent original SQLite/WAL read semantics. Check custody before/after the transaction. Missing WAL/history must not cause reconstruction or import. Alternatively, a surviving actual Automation owner can serve authenticated scoped reads.

Claim/ack mutations still require the original Automation owner's actual authority. A historical reader does not acquire it from seeing the row. `CircuitLearningDeliveryV1::acknowledged_head` acknowledges a learning checkpoint, not the Objective RunStart sequence/chain.

## 4. Cell: useful guarded reader, but the existing recovery route depends on C

[`recover_predecessor`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/circuit_feature_current_recovery.rs#L46) uses `CellOwnerJournalReadbackV1::open_guarded`, but requires an authenticated published successor and live `LiveGenerationCurrent` before/after reading. Using it before Dataset creates a circular dependency on future C.

Its exact checks at lines 78–137 are reusable: original Source before/after; original task/manifest/scope/frontier and writer epoch; canonical request digest; no pending inference; original-operation receipt lookup; `publication.require_decision`; revision 1; checkpoint equality; and real authority before/after. Retain all of them.

The proposed BeforeDataset guard must come from the actual Root admission proving old-publisher retirement and binding the new Starting recipient to this recorded original scope. It must not return unconditional Active/Current and must not create a Cell writer. The guarded Sparse header/binding, independent witness and original receipt can then be read without C.

[`CellQ24DatasetTaskV1::capture`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/cell_q24_dataset_materializer.rs#L148) currently requires `PublishedCircuitCellOwnerV1`; [`committed`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/circuit_feature_current_owner.rs#L100) checks the live task before/after. Add a separate owner-controlled historical constructor only after genuine cold Source/Cell capabilities exist. Do not accept caller-authored publication/decision vectors or weaken the live constructor.

## 5. Retained handoff is concrete, but currently in-process

[`retained_learning_source`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/cell_q24_retained_learning_source.rs#L48) verifies accepted Decision/terminal Outcome, the original prepared Dataset, exact Automation owner/path and terminal trace. It shares the same producer state, Ledger and Source readers through `Arc`, with Retained custody instead of Cell writer locks.

This supports runtime reassembly while original process-owned capabilities survive. It is not a cross-process decoder: [`OriginalCellQ24TaskLedgerProducerV1::capture`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/cell_q24_task_ledger.rs#L446) refuses Retained custody if original capture was not saved. A cold host must reacquire actual readers and accepted Ledger facts through real Root admission; it cannot deserialize an Arc or reopen the active constructor as a retired writer.

[`require_registered_retained_source`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95c8993b5a80d1636aa74f369586e5b75ef420e/codex-rs/hepta-agentd/src/objective_retained_learning_source.rs#L7) gives the useful join order: original outbox identity; readiness; current trust on original record; exact intent; committed trace; accepted task before/after; intent reread and authentication recheck. Preserve that order in any admitted cold variant.

## 6. Implementation order and evidence required

1. Connect original append receipt to actual Root durable capture, with exact replay/conflict/uncertain controls. This is the first missing boundary.
2. Establish actual retirement and new-Starting admission; only then expose cold Objective/Source/Automation/Cell readers for that retained scope.
3. Join physical original reads and trusted Decision/terminal Outcome into frozen Dataset, retaining independent Dataset authorization and every materializer rule.
4. Execute real A exit, recover delivery/Dataset, then independent B, Adopt/NoUpdate and C. Qualify daemon and Root cold restart separately.

Negative controls need missing/mismatched independent ACK; tuple copied from current file; wrong original profile/binding/FD; incomplete or changed Objective history; restored bytes after observed durable fencing; current key withdrawal; replaced/copied DB or missing WAL/history; changed intent; pending/wrong Cell receipt/checkpoint; live old publisher; wrong/unregistered new Starting identity; unavailable original owner. None may initialize or repair a missing predecessor.

No implementation or acceptance follows from this audit. Complete ordinary counts remain **0 / 0 / 0**.
