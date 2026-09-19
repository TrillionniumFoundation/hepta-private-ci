# channel.matrix: implementation design

Parent: `docs/modules/channel.matrix/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable Matrix runtime and dispatch ledger are integrated under MatrixDurableStore; transport acceptance is non-terminal and homeserver sync observation settles send success. Remaining external qualification and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-matrix-sdk`, `codex-rs/hepta-matrixd`, `codex-rs/hepta-matrix-store`, `codex-rs/hepta-matrix-protocol`.
Packages: `MATRIX-1-CHANNEL-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`admit_event(room, event, sync_generation, principal) -> IngressObservation`; `prepare_send(room, message_digest, operation_id, grant) -> SendIntent`; `observe_send(transaction_id, server_evidence) -> DeliveryDisposition`. Room, homeserver, authenticated user/device and encryption/session generation are explicit. Message text is untrusted evidence, not an administrative command.

## 3. State records and transaction design

`matrix_ingress_projection` keys homeserver+room+event ID and retains source digest, sync position, sender evidence, redaction/correction and scope. `matrix_dispatch_ledger` is durable SQLite state keyed by canonical `stable_txn_id` and immutable operation/logical-outbox/room/generation/payload identity; optional authority epoch/grant identity is payload-bound. Transport, homeserver-send and redaction observations are append-only records with separate digests. Ingress dedupe, egress terminal observation and sync-watermark advancement commit under the owner transaction so a crash cannot advance the cursor past unrecorded terminal evidence.

## 4. Deterministic algorithm and scheduling

Validate enrolled room and session; dedupe by server event identity; apply source correction/redaction; publish bounded ingress. For sending, persist the dispatch identity before transport, preserve the same transaction identity across retries, record HTTP/SDK success only as `accepted`, and settle `succeeded` only when `/sync` observes the matching homeserver event with `unsigned.transaction_id`. Retry exhaustion parks the unresolved transaction instead of converting uncertainty into failure. Server persistence and downstream user reading remain different claims. Reconnect resumes a durable watermark without replaying revoked content.

## 5. Capacity and performance profile

Pilot ingress batch <= 512 events, payload <= the registered Matrix boundary limit, per-room queue <= 2048, unresolved dispatch working set <= 4096 and reconnect attempts bounded by host policy. Terminal dispatch history remains durable and does not consume the unresolved working-set ceiling. Report sync lag, queue age, redaction propagation and unresolved send count.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- MATRIX-01: duplicate events across reconnect append no duplicate learning/source event.
- MATRIX-02: room/session generation or payload drift is rejected before send.
- MATRIX-03: lost acknowledgement preserves transaction identity and indeterminate state until observed.
- MATRIX-04: deleted/redacted content does not re-enter context or replay after reconnect/restore.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Matrix is a digital sensory/effect organ, not a source of user authority beyond authenticated enrolled scope. No direct agent-store writes. Rollback must retain sync and dispatch identities and current revocation/redaction frontiers.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Ingress/App Server entrypoint:** `process_event` and `recover_pending` in [codex-rs/hepta-matrixd/src/runtime.rs](../../../codex-rs/hepta-matrixd/src/runtime.rs).
- **Egress preparation and transport:** [codex-rs/hepta-matrix-sdk/src/outbound.rs](../../../codex-rs/hepta-matrix-sdk/src/outbound.rs) claims the canonical outbox row, calls `prepare_outbox_dispatch` before the network boundary and records transport acceptance/uncertainty without marking the outbox sent.
- **Durable dispatch truth:** [codex-rs/hepta-matrix-store/src/dispatch.rs](../../../codex-rs/hepta-matrix-store/src/dispatch.rs) owns the SQLite dispatch ledger and append-only observations. The former `MatrixSendObserver` BTreeMap is retired; [send_observer.rs](../../../codex-rs/hepta-matrixd/src/send_observer.rs) is compatibility re-export only.
- **Crash-safe terminal observation:** [codex-rs/hepta-matrix-sdk/src/sync.rs](../../../codex-rs/hepta-matrix-sdk/src/sync.rs) carries `unsigned.transaction_id` into `MatrixSyncMutationV2`; [sync_v2.rs](../../../codex-rs/hepta-matrix-store/src/sync_v2.rs) settles the dispatch and advances the sync checkpoint in the same SQLite transaction.
- **Retention/evidence:** only unresolved `dispatched|accepted|indeterminate` records count against the 4096 active ceiling. Successful-send and later-redaction evidence use different digest fields and immutable observation rows, so redaction cannot erase the original send evidence.
- **Source tests:** [codex-rs/hepta-matrix-sdk/tests/durable_transport.rs](../../../codex-rs/hepta-matrix-sdk/tests/durable_transport.rs), [codex-rs/hepta-matrix-store/tests/sync_mutation_v2.rs](../../../codex-rs/hepta-matrix-store/tests/sync_mutation_v2.rs), and [codex-rs/hepta-matrixd/src/runtime/tests.rs](../../../codex-rs/hepta-matrixd/src/runtime/tests.rs). Test identities are not execution receipts for this documentation revision.
- **Qualification path:** [hepta-lane-b-matrix-real-synapse.yml](../../../.github/workflows/hepta-lane-b-matrix-real-synapse.yml) is deliberately manual and main-only on the trusted Mac runner. It requires the requested SHA to equal exact main HEAD and uploads the existing hermetic Synapse completion receipt.
- **Remaining external work:** execute the exact-head real Synapse qualification after merge and retain its receipt; independently accept rate-limit/reconnect/redaction/restore behavior on the selected enrolled homeserver/device. No production promotion or release claim is made here.
