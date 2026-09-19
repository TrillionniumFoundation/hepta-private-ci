# channel.matrix: implementation design

Parent: `docs/modules/channel.matrix/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable Matrix runtime and dispatch ledger are integrated under MatrixDurableStore; remaining external qualification and final-use authority integration are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `process_event` and `recover_pending` in [codex-rs/hepta-matrixd/src/runtime.rs](../../../codex-rs/hepta-matrixd/src/runtime.rs); durable `prepare_send`/`observe_send` façade methods in [codex-rs/hepta-matrixd/src/send_observer.rs](../../../codex-rs/hepta-matrixd/src/send_observer.rs); the canonical ledger lives in `MatrixDurableStore`.
- **State and recovery:** `MatrixDurableStore` owns inbox/thread/outbox plus the durable dispatch ledger, append-only send observations and terminal archive. `stable_txn_id` is the canonical Matrix transaction identity. SDK/HTTP acceptance records an indeterminate transport observation; only a trusted homeserver event observation settles success. Retry/restart reuses the same transaction identity. Terminal rows leave the bounded unresolved working set, and redaction evidence is stored separately from the original send observation.
- **Source tests:** [codex-rs/hepta-matrix-store/tests/dispatch_ledger.rs](../../../codex-rs/hepta-matrix-store/tests/dispatch_ledger.rs), [codex-rs/hepta-matrix-sdk/tests/durable_transport.rs](../../../codex-rs/hepta-matrix-sdk/tests/durable_transport.rs), [codex-rs/hepta-matrixd/src/runtime/tests.rs](../../../codex-rs/hepta-matrixd/src/runtime/tests.rs), [codex-rs/hepta-matrixd/src/send_observer_tests.rs](../../../codex-rs/hepta-matrixd/src/send_observer_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Qualification path:** `.github/workflows/hepta-matrix-real-synapse.yml` binds a manually dispatched qualification run to an exact candidate SHA/tree and seals the pinned Synapse fixture artifacts. A workflow definition is not a pass receipt.
- **Implementation and operating references:** [docs/modules/channel.matrix/IMPLEMENTATION_MAP.json](../../../docs/modules/channel.matrix/IMPLEMENTATION_MAP.json), [docs/readiness/LANE_B_RUNTIME_COMPOSITION.md](../../../docs/readiness/LANE_B_RUNTIME_COMPOSITION.md).
- **Remaining work:** bind a live final-use authority/grant and revocation caller to the already persisted authority fields, then obtain exact-candidate qualification for enrolled homeserver/device transport, encryption, rate limiting, reconnect/redaction and restore. Production activation and independent acceptance remain separate.
