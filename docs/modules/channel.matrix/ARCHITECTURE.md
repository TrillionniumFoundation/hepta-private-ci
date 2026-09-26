# channel.matrix architecture

Status: source-composed, exact-candidate qualification pending. This document describes the executable composition; it grants no deployment, acceptance, promotion, or release authority.

## 1. Runtime ownership

`channel.matrix` is one per-Agent Matrix plane. It has one durable writer, `MatrixDurableStore`, and one real daemon, `hepta-matrixd`. The former in-memory send observer is only a compatibility re-export and owns no state.

The source composition is:

```text
hepta-supervisor
  └─ start_matrix_companion / spawn_matrixd
       └─ hepta-matrixd::run
            ├─ MatrixFinalUseBroker
            ├─ MatrixDurableStore (SQLite, per Agent)
            ├─ MatrixSdkClient (authenticated user/device/session)
            ├─ MatrixIngress + durable /sync
            ├─ MatrixRuntime inbox dispatcher
            ├─ App Server event projector
            ├─ authorized durable outbox sender
            └─ matrixd control server + health monitor
```

The supervisor owns process lifecycle, release binding, process lease, restart budget and orphan adoption. `matrixd` owns local composition. The Matrix SDK owns homeserver transport/session mechanics. `MatrixDurableStore` owns Matrix ingress projection, sync cursor, room/thread binding, outbox, dispatch ledger, observations and authority-claim evidence. Agentd owns Agent execution state; Matrix code may call its registered boundary but never write Agentd state directly.

## 2. Startup order

The daemon must execute the following order and fail closed at any step:

1. Canonicalize the private Matrix root and acquire the per-Agent process lock.
2. Open and verify the SQLite store and migrations.
3. Open final-use verifier state and probe the independently operated grant broker.
4. Fence stale pending approvals and bind the configured rooms.
5. Connect to the exact Agentd generation.
6. Login or restore the exact Matrix user/device/session.
7. Complete one durable `/sync` batch.
8. Resume exact current App Server threads and recover pending inbox work.
9. Expose readiness, then start continuous sync, inbox dispatch, event projection, outbox dispatch and health monitoring.

Initial sync precedes recovery so content redacted while the daemon was offline cannot be recovered into a turn before the redaction frontier reaches the local store.

## 3. Ingress sequence

```text
homeserver /sync
  -> Matrix SDK validates enrolled user/device/session and room
  -> build typed mutation with event identity and optional transaction id
  -> MatrixDurableStore BEGIN IMMEDIATE
       - validate room binding revision + Matrix-plane generation
       - apply timeline/correction/redaction mutation
       - deduplicate by source event identity
       - reconcile outbound transaction when transaction id is present
       - advance sync checkpoint in the same owner transaction
  -> commit
  -> bounded MatrixRuntime inbox dispatcher
  -> registered Agentd/App Server boundary
```

A cursor cannot advance past the only terminal send observation because outbound reconciliation and cursor advancement share the same owner transaction.

## 4. Egress sequence

```text
outbox row with stable Matrix transaction id
  -> claim bounded batch with lease/attempt fence
  -> prepare durable dispatch identity
  -> read authenticated transport identity
  -> derive canonical final-use request and payload/scope digests
  -> obtain independently signed short-lived grant
  -> kernel FinalUseAuthority validates signature and burns nonce
  -> persist immutable authority claim for this transaction + attempt
  -> refresh authenticated revocation frontier
  -> exact-frontier enter_verified_use
  -> poll lazy Matrix transport future under deadline < claim lease
  -> append transport observation
  -> wait for trusted /sync event observation
  -> atomically mark dispatch Confirmed and settle outbox Sent
```

`TransportAccepted` is not terminal success. Timeout, connection loss or an ambiguous response remains `Indeterminate` and retains the same stable transaction identity until homeserver reconciliation.

## 5. Concurrency model

- One `matrixd` process is admitted per Agent by an OS file lock and supervisor process lease.
- SQLite is the only durable Matrix writer; logical mutations use explicit transactions.
- Outbox claim attempt is the current fencing epoch. State changes reject a mismatched attempt.
- The final-use nonce is single-use and durable in `kernel.authority`; the Matrix authority claim is append-only evidence, not authority.
- Continuous runtime tasks share one cancellation token. Any unexpected task exit drains and stops the process.
- No unbounded queue, retry loop or history scan is allowed.

## 6. Trust boundaries

The Matrix adapter does not mint authority. The grant broker is separately operated and sees a canonical request. `FinalUseAuthority` verifies the signed grant, expiry, exact binding, revocation head and nonce uniqueness. Credentials remain in private Matrix secret/session storage and must not enter receipts, prompts, logs or learning data.

## 7. Source anchors

- Lifecycle caller: `codex-rs/hepta-supervisor/src/matrix.rs`
- Product composition: `codex-rs/hepta-matrixd/src/runner.rs`
- Ingress runtime: `codex-rs/hepta-matrixd/src/runtime.rs`
- Authorized sender: `codex-rs/hepta-matrix-sdk/src/outbound.rs`
- Final-use request: `codex-rs/hepta-matrix-sdk/src/authority.rs`
- Durable state: `codex-rs/hepta-matrix-store/src/store.rs` and `dispatch.rs`
- Sync reconciliation: `codex-rs/hepta-matrix-store/src/sync_v2.rs`
- Schema: `codex-rs/hepta-matrix-store/migrations/`
