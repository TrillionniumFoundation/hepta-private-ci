# channel.matrix technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `channel.matrix`  
**Owner / deputy:** `channels-platform` / `security-authority`  
**Lifecycle / source status:** `existing` / `existing_bound`  
**Bootstrap work package:** `MATRIX-1-CHANNEL-BOUNDARY`

This is the stable implementation guide. Canonical registry facts remain in the repository JSON registries; current native source composition and claim limits are recorded in `IMPLEMENTATION_MAP.json`. Documentation and source composition grant no activation, operator acceptance, promotion or release authority.

Executable companion documents:

- [Architecture](ARCHITECTURE.md)
- [Durable state machine](STATE_MACHINE.md)
- [Storage schema](STORAGE_SCHEMA.md)
- [Matrix protocol](MATRIX_PROTOCOL.md)
- [Configuration](CONFIGURATION.md)
- [Failure and recovery](FAILURE_AND_RECOVERY.md)
- [Operations runbook](OPERATIONS_RUNBOOK.md)
- [Security model](SECURITY_MODEL.md)
- [Qualification matrix](QUALIFICATION_MATRIX.md)

## 1. Identity, mission and ownership

`channel.matrix` translates enrolled Matrix ingress into the existing Agent execution path and performs governed Matrix sends. It is a checked adapter, not a source of Agent authority and not a general state store.

The supervisor owns lifecycle only. `hepta-matrixd` owns one per-Agent runtime generation. `MatrixDurableStore` is the sole Matrix state writer. Agentd retains Agent execution/private-state ownership. The independent final-use broker owns signing policy/key; Matrixd holds verifier material and consumes grants but cannot mint them.

## 2. Source binding and implementation status

Declared roots:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`

Supporting owner roots:

- `codex-rs/hepta-matrix-store`
- `codex-rs/hepta-matrix-protocol`
- `codex-rs/hepta-supervisor`
- `codex-rs/state` for the existing OS-seeded UUIDv4 source used to mint local claim capabilities

The product source path is composed: supervisor starts the Matrix companion, runner opens the durable store and final-use broker, the SDK runs durable sync and `outbound_v2`, and the store reconciles trusted `/sync` observations. This is `source_composed_unqualified`, not production qualification.

`IMPLEMENTATION_MAP.sourceBase` is an immutable provenance ancestor. A commit cannot contain its own future SHA/tree. Current candidate identity is instead enforced by `scripts/verify_channel_matrix_candidate.py --expected-sha <HEAD>`, whose receipt binds the exact commit, tree, map and inspected source/document blobs.

## 3. Boundary, responsibilities and non-goals

Direct dependencies are `runtime.agentd`, `kernel.authority`, `kernel.operations`, the Matrix SDK and the supervisor lifecycle path.

Authoritative Matrix domains are:

- `matrix_ingress_projection`
- `matrix_dispatch_ledger`
- sync frontier, outbox, random-capability attempt claims, authority witnesses and append-only attempt history

Denied capabilities include direct Agent-store writes, self-issued send authority, interpreting message prose as authority, a second durable sender/observer, and converting CI or documentation into deployment authority.

## 4. Internal architecture and component decomposition

The runtime chain is:

```text
hepta-supervisor
  -> exact release/binding/process lease
  -> hepta-matrixd
       -> MatrixDurableStore
       -> Matrix SDK durable /sync
       -> ingress dispatcher -> Agentd/App Server
       -> final-use broker/verifier
       -> outbound_v2 -> Matrix transport
       -> /sync terminal reconciliation
```

Startup obtains the process lock, opens/verifies SQLite, fences stale approvals, validates room bindings, connects to Agentd, logs in/restores the exact Matrix session, performs one durable sync, resumes exact threads and recovers pending inbox work before exposing readiness or starting background loops.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::matrix_dispatch_ledgerV1`
- `DomainRead::matrix_ingress_projectionV1`

Consumed contracts include authority/revocation, operation ledger, runtime health, `OperationIntentV1`, `VerifiedUseTokenWitnessV1` and the registered module ports for authority, operations and Agentd.

Wire and storage identities are versioned and bounded. Unknown critical fields, missing authority, stale revision/generation, scope drift and digest mismatch fail closed. Semantic IDs never change meaning in place. Compatibility observations without current final-use evidence are recorded as `observed_unqualified`, never silently promoted to qualified success.

## 6. Data authority, persistence and migrations

`MatrixDurableStore` owns one private per-Agent SQLite database. Migrations 1-5 own the existing room/inbox/outbox/sync/control surfaces. Migration 6 adds the immutable dispatch ledger, observations and authority claims. Migration 7 adds random-capability attempt claims, active claim phases, verified-use/revocation-head witnesses and append-only attempt events.

Operation ID, stable transaction ID and event IDs are independently unique. Logical identity columns are immutable; audit rows cannot be deleted. Store open validates migration history, schema objects, constraints, triggers, foreign keys and integrity before work.

## 7. Runtime, concurrency and transaction model

One process lock and one supervisor process lease fence the per-Agent writer. Outbox claims are bounded and carry monotonic attempt/lease epoch plus an opaque random capability. Only its SHA-256 digest is durable; the raw 32-byte value remains process-private.

Active-claim transitions require the exact transaction, attempt, lease epoch and capability digest. The dispatch ledger also uses attempt CAS. Physical send deadline is shorter than remaining lease. A clean shutdown releases only pre-entry claims; post-entry cancellation becomes an indeterminate effect.

Trusted `/sync` confirmation/redaction, dispatch terminal mutation, outbox settlement, change record and cursor advancement share one owner transaction.

## 8. Failure semantics, recovery and rollback

`TransportAccepted` is not terminal success. Only an authenticated matching homeserver observation produces `succeeded`; redaction is a later monotonic observation.

DNS, TLS, connect timeout/failure, read timeout, connection reset, response loss, server unavailable and rate limiting are distinct durable classes. Any post-entry outcome not proven absent remains `indeterminate` under the same transaction identity. Retry exhaustion parks unknown effects for reconciliation rather than producing false failure.

Crash/recovery rules and exact cuts are defined in [Failure and recovery](FAILURE_AND_RECOVERY.md) and [Durable state machine](STATE_MACHINE.md). Rollback must preserve transaction, claim, witness, observation and redaction lineage.

## 9. Security, privacy and threat controls

The final-use path binds subject, destination, homeserver, Matrix user/device/session, room, binding revision, plane generation, transaction, attempt and canonical payload. After the authority witness is durable, Matrixd records `dispatching`, refreshes authenticated revocations, consumes the exact verified-use token, and immediately polls the lazy transport future. No await or persistence intervenes.

Credentials, session keys, raw grants/tokens, signing material, raw claim capabilities and message content are excluded from general logs and receipts. See [Security model](SECURITY_MODEL.md) for mandatory negative tests and residual external gates.

## 10. Performance, capacity and hot-path policy

Current enforced bounds include unresolved dispatch capacity 4,096, claim batch 1-256, attempts 1-64, bounded broker frames/timeouts, bounded sync timeline and physical deadline below lease. Backoff is exponential and capped. Matrix `Retry-After` delay/date hints are normalized and receive stable transaction-derived jitter; hints outside policy park for reconciliation.

Target-host latency, throughput, queue-age, database-growth and sustained-recovery SLOs require measured receipts; design ceilings are not measurements.

## 11. Observability and operations

Structured attempt history records claimed, prepared, authorized, dispatching, accepted, indeterminate, retry, confirmed, redacted, rejected, revoked, canceled and expired outcomes with safe identifiers/digests. Operators monitor sync lag, aged unresolved sends, rate limiting, typed network failures, claim expiry, capacity, redaction propagation and supervisor restart/adoption.

The operational procedures are in [Operations runbook](OPERATIONS_RUNBOOK.md). `send_observer.rs` is a compatibility/read projection over durable state and must never regain a `BTreeMap`, independent sender or state writer.

## 12. Verification and qualification

Focused source checks include:

- `codex-rs/hepta-matrix-sdk/tests/durable_transport.rs`
- `codex-rs/hepta-matrixd/src/runtime/tests.rs`
- `codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs`
- supervisor Matrix lifecycle/orphan tests
- migration and store reopen/integrity tests

Run candidate binding, focused package tests, applicable all-target compilation, strict lint, clean-tree, exact source-head and deterministic synthetic-merge lanes. Retain structured receipts and logs as immutable artifacts. The full scenario table and receipt schema are in [Qualification matrix](QUALIFICATION_MATRIX.md).

Real encrypted-room rotation, authenticated restore, sustained capacity/rate-limit and independent operator/security acceptance remain external gates.

## 13. Implementation sequence and work packages

The canonical work-package registry currently retains `MATRIX-1-CHANNEL-BOUNDARY` as its planning-envelope fact. Actual source progress is not inferred from that label; it is recorded separately in `IMPLEMENTATION_MAP.json` and exact-candidate receipts.

Repository implementation order is:

1. durable single-writer state and terminal observation;
2. random claim fencing and final-use authority;
3. typed uncertainty/retry and restart reconciliation;
4. real homeserver qualification;
5. independent acceptance and externally governed activation.

Cross-owner changes require their registered owners and may not widen Matrix authority.

## 14. Activation, compatibility and retirement

Supervisor and runner are named source callers, but source composition is not activation. Activation requires the selected product configuration, protected authority/time/frontier composition, real credentials/session provisioning, target-host resource limits and passing current qualification evidence.

Legacy observer compatibility is read-only. Retirement requires all callers on the durable owner, no old-path writes, migration/reopen proof and retained historical interpretability.

## 15. Definition of module completion

Documentation completion requires the stable guide, executable companion documents, implementation map and closed-world validation. Source completion requires the unique durable owner, current callsites, tests and exact-head plus merge receipts. Deployment qualification, independent acceptance, canary, promotion and release are separate states.

For the current candidate, `productionImplementation`, `productExecutionProved`, `deploymentQualificationComplete`, `independentAcceptance`, `activation` and `release` remain false until their named evidence gates pass.

## 16. V8.2 pre-coding implementation-readiness overlay

The module remains bound to `LANE-B-RUNTIME` and the shared source-baseline, parallel-development and embodied-runtime requirements. Those overlays constrain coding and evidence; they grant no additional permission or deployment authority.

Current runtime context is described by [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md) and [Lane B runtime composition](../../readiness/LANE_B_RUNTIME_COMPOSITION.md).

## 17. Source implementation receipt

This navigation receipt identifies the current native surfaces; execution claims require a retained exact-candidate receipt.

| Operation | Native owner | Product callsite / terminal observer |
|---|---|---|
| `admit_event` | `codex-rs/hepta-matrixd/src/runtime.rs` — `process_event` | runner recovery/inbox dispatcher |
| `prepare_send` | `codex-rs/hepta-matrix-store/src/dispatch.rs` — `prepare_outbox_dispatch` | `codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs` |
| claim/authorize/dispatch | `codex-rs/hepta-matrix-store/src/claim/store.rs` | `outbound_v2` final-use sequence |
| transport classification | `codex-rs/hepta-matrix-sdk/src/sdk.rs` | typed `MatrixTransportError` and retry policy |
| `observe_send` | `codex-rs/hepta-matrix-store/src/dispatch.rs` | `sync_v2.rs` authenticated `/sync` reconciliation |
| lifecycle composition | `codex-rs/hepta-supervisor/src/matrix.rs` | `codex-rs/hepta-matrixd/src/runner.rs` |

Use [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) and run [`scripts/verify_channel_matrix_candidate.py`](../../../scripts/verify_channel_matrix_candidate.py) with the exact candidate SHA. A passing navigation receipt is not a real homeserver, encryption, restore, acceptance or release receipt.
