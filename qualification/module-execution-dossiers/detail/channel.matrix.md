# channel.matrix: implementation design

Parent: `docs/modules/channel.matrix/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable Matrix runtime and dispatch observation now share MatrixDurableStore and the existing stable transaction identity; remaining authority composition and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-matrix-sdk`, `codex-rs/hepta-matrixd`.
Packages: `MATRIX-1-CHANNEL-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`admit_event(room, event, sync_generation, principal) -> IngressObservation`; `prepare_send(room, message_digest, operation_id, grant) -> SendIntent`; `observe_send(transaction_id, server_evidence) -> DeliveryDisposition`. Room, homeserver, authenticated user/device and encryption/session generation are explicit. Message text is untrusted evidence, not an administrative command.

## 3. State records and transaction design

`matrix_ingress_projection` keys homeserver+room+event ID and retains source digest, sync position, sender evidence, redaction/correction and scope. `matrix_dispatch_ledger` keys operation ID and Matrix transaction ID with payload, room/session generation, grant epoch and observed server event. Persist dedupe and sync-watermark advancement atomically or through a recoverable staged watermark.

## 4. Deterministic algorithm and scheduling

Validate enrolled room and session; dedupe by server event identity; apply source correction/redaction; publish bounded ingress. For sending, consume final room/payload-bound authority; preserve the same transaction identity across a permitted reconciliation; treat HTTP acceptance, server persistence and downstream user reading as different claims. Reconnect resumes a durable watermark without replaying revoked content.

## 5. Capacity and performance profile

Pilot ingress batch <= 512 events, payload <= the registered Matrix boundary limit, per-room queue <= 2048 and reconnect attempts bounded by host policy. Report sync lag, queue age, redaction propagation and unresolved send count.

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

- **Implemented entrypoints:** `process_event` and `recover_pending` remain in [codex-rs/hepta-matrixd/src/runtime.rs](../../../codex-rs/hepta-matrixd/src/runtime.rs); `prepare_send` and `observe_send` in [codex-rs/hepta-matrixd/src/send_observer.rs](../../../codex-rs/hepta-matrixd/src/send_observer.rs) are compatibility seams over the durable owner. The real SDK sender prepares the same `stable_txn_id` before transport and `/sync` supplies terminal observation.
- **State and recovery:** `MatrixDurableStore` owns inbox/thread/outbox plus `matrix_dispatch_ledger` and append-only `matrix_dispatch_observations`. Operation, authority and optional grant identities are frozen before the first effect and must match exactly on every retransmission. HTTP/API acceptance records `accepted` only and parks that known event ID; timeout or response loss records `indeterminate`. After crash/reopen, an uncertain attempt can be reclaimed only by retransmitting the exact same `stable_txn_id`, matching Matrix transaction-idempotency semantics; it can never allocate a fresh transaction identity. The configured attempt budget bounds retransmission, then leaves the effect durably indeterminate and parked instead of inventing failure. `/sync` reconciles the stable transaction to `observed_succeeded`; terminal send evidence and later redaction evidence use separate immutable digests. The 4096 ceiling applies only to unresolved ledger rows; terminal rows remain durable and can be archive-marked.
- **Source tests:** [codex-rs/hepta-matrixd/src/runtime/tests.rs](../../../codex-rs/hepta-matrixd/src/runtime/tests.rs), [codex-rs/hepta-matrixd/src/send_observer_tests.rs](../../../codex-rs/hepta-matrixd/src/send_observer_tests.rs), [codex-rs/hepta-matrix-sdk/tests/durable_transport.rs](../../../codex-rs/hepta-matrix-sdk/tests/durable_transport.rs) and [codex-rs/hepta-matrix-sdk/src/sync_tests.rs](../../../codex-rs/hepta-matrix-sdk/src/sync_tests.rs). These are source test identities; workflow receipts are still required for the exact candidate.
- **Implementation and operating references:** [docs/modules/channel.matrix/IMPLEMENTATION_MAP.json](../../../docs/modules/channel.matrix/IMPLEMENTATION_MAP.json), [docs/readiness/LANE_B_RUNTIME_COMPOSITION.md](../../../docs/readiness/LANE_B_RUNTIME_COMPOSITION.md).
- **Remaining work:** compose an independently issued final-use grant immediately at the live sender boundary and persist its identity in the already grant-aware dispatch ledger. Real enrolled homeserver/device transport, encryption, reconnect/redaction/restore and independent acceptance remain qualification gates.
