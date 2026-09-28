# `auth.authbus` current implementation

## Candidate status

The current branch is a source candidate under exact-head and synthetic-merge qualification. It is not activated and does not claim release evidence. The normative activation state remains in `docs/modules/auth.authbus/ACTIVATION_DECISION.md`.

The candidate contains two deliberately separate durable owners:

1. signed-message replay and outbox state in the Evidence SQLite owner;
2. policy, issuer, trusted-time, quota, reservation, settlement and anti-rollback state in `AuthBusAuthorityHost`.

Authentication, policy evaluation and queue acceptance do not grant provider authority. Final-use authority remains payload-bound, operation-bound and verified immediately before the registered effect boundary.

## Closed public boundary

`IssuerRegistration` and `SettlementIssuerRegistration` are sealed handles. External callers cannot mutate issuer identity, purpose, epoch, verification key or revocation state. Settlement reloads the exact durable issuer row inside the settlement transaction and applies current revocation state before signature verification.

`AuthBusAuthorityStore` is crate-private. The public durable mutation boundary is `AuthBusAuthorityHost`; the raw SQLite writer is not exported. The generated closed-world inventory is `docs/modules/auth.authbus/PUBLIC_API_INVENTORY.json`, enforced by `scripts/check-authbus-closed-world.py` and exact-head CI.

## Owner and capability lifetime

`AuthBusAuthorityHost` owns all of the following as one capability:

- the crate-private SQLite store;
- the independently retained checkpoint handle;
- the process-local and cross-process owner fence;
- the mutation/checkpoint serialization gate;
- bounded runtime diagnostics.

`AuthBusAuthorityWorker` holds `Arc<AuthBusAuthorityHost>`. Therefore a worker cannot outlive the owner fence while retaining store capability. Releasing the caller's original `Arc` does not permit a replacement owner until the worker is also dropped.

On supported Unix hosts, owner acquisition proceeds in this order:

1. validate the immutable absolute database path and private parent directory;
2. reserve the lock path in a process-local RAII registry **before opening the lock inode**;
3. open the deployed lock pathname with `O_NOFOLLOW`, private mode and close-on-exec;
4. validate regular-file identity, ownership, link count and pathname/inode stability;
5. acquire a non-blocking exclusive descriptor-lifetime `flock`;
6. revalidate the locked inode before exposing the host.

The pre-open process reservation keeps same-process uniqueness explicit instead of relying on platform-specific `flock` behavior. Cross-process exclusion is attached to the live lock-file description, so closing an unrelated descriptor for the same inode cannot release the owner fence. Tests cover both rejected duplicate initialization and unrelated-descriptor close before probing from a third process. Unsupported non-Unix, Solaris and illumos targets fail closed rather than silently degrading to process-local exclusion.

## One authority-use and transaction boundary

All durable mutations, bounded recovery maintenance, checkpoint publication and authority-bearing reads pass through one host-owned async gate. The gate is held from checkpoint preflight through SQLite work and independent checkpoint publication. A caller cannot begin a second operation against a dirty or divergent frontier.

The SQLite store uses WAL, `synchronous=FULL`, foreign keys, ordered checksum-bound migrations, schema comparison, `quick_check` and foreign-key validation. Authoritative mutations mark the semantic frontier dirty in the same database commit. The host then publishes exactly one successor checkpoint using write, file fsync, atomic rename and directory fsync before locally promoting the checkpoint.

Some logical APIs may internally advance trusted time before their main domain row; a storage error at such a boundary is deliberately classified as outcome-unknown. A deterministic domain rejection means the requested domain mutation did not commit, but it does not claim that a separately authenticated trusted-time observation was rolled back. The public contract does not pretend every failure occurred before all durable work.

## Mutation result contract

`AuthBusAuthorityError::mutation_disposition()` gives callers a stable failure interpretation:

| Result | Durable meaning | Caller rule |
| --- | --- | --- |
| `Ok(value)` | SQLite mutation and independent checkpoint are durable. | Continue. |
| deterministic domain error | Requested domain mutation did not commit; a separately authenticated trusted-time observation may already be durable. | Correct or stop; disposition is `NotCommitted` for the requested mutation. |
| `AuthorityUseBlocked` | Checkpoint/recovery admission failed before the requested operation was polled. | Stop authority use and reconcile. |
| `CheckpointReconciliationRequired` | SQLite mutation committed but checkpoint publication/promotion did not complete. | Query by stable identity and reconcile before retry; disposition is `CommittedNeedsReconciliation`. |
| `MutationOutcomeUnknown` | Commit status cannot be inferred safely after a storage failure. | Never blindly retry; query/reconcile by stable identity. |

This contract is uniform for issuer enrollment, rotation, revocation and retirement, and is used by the other host mutations. A failed checkpoint publication is not collapsed into a generic immediately-retryable storage error.

## Signed ingress and durable replay

`SignedMessage::authenticate` binds issuer/key epoch, message, subject, scope, payload, sequence and expiry with Ed25519. Authentication alone consumes no durable replay state. Evidence-owned `admit_authbus_message` and `enqueue_authbus_message` advance durable replay state and insert immutable outbox records under the Evidence SQLite owner.

Agentd reloads its protected issuer registry at admission and delivery boundaries. Production-configured ingress uses a separately retained replay witness. A restored old Evidence database with a newer witness fails closed. The legacy in-process `PreverifiedAuthEnvelope`/`ReplayWindow` surface remains compatibility-only; it does not authenticate a signature, survive restart, reserve quota or grant effect authority.

## Trusted time, policy, quota and settlement

`TrustedTimeSample` is opaque outside the crate and is produced by verification of a signed attestation from an active `TrustedTime` issuer. Policy decisions bind policy identity/revision, principal, action, scope and trusted time while retaining `AuthorityPosture::DENY_ALL`.

Quota accounting preserves checked `available + reserved + consumed == limit` semantics. A reservation binds stable operation identity, quota, amount, effect digest, policy identity/revision and decision digest. The lifecycle is:

```text
Held -> DispatchAttempted -> {Indeterminate, Settled, Released}
Held -> {Cancelled, Expired}
```

`DispatchAttempted` is durable immediately before the external effect boundary. Timeout, response loss or crash after that fence never proves `NotApplied`; restart converts unresolved attempts to `Indeterminate`, and quota remains held until authenticated terminal evidence arrives.

## Bounded recovery and maintenance

Startup executes one bounded restart-reconciliation batch and one bounded expiration batch. If work remains, durable `recovery_required` keeps write admission fail-closed. The periodic `AuthBusAuthorityWorker` is the named maintenance owner. Each tick obtains freshly verified trusted time, runs bounded recovery and expiry reconciliation through the same host gate, publishes the checkpoint, then emits a snapshot and SLO evaluation. Missed intervals are skipped rather than accumulated; observer/export failure terminates the loop.

## Actionable diagnostics

`AuthBusOperationalSnapshot` includes durable authority state plus process-lifetime cumulative runtime diagnostics:

- owner acquisition failures grouped into active-owner, unsafe-path and storage classes;
- checkpoint synchronization failures split into rollback conflicts and storage failures;
- blocked authority use;
- deterministic mutation rejection, committed-but-reconcile and unknown-outcome counts;
- replay rejection count;
- maintenance failures and incomplete bounded-recovery ticks;
- complete mutation and maintenance latency summaries (`count`, `p50`, `p95`, `p99`, `max`).

Mutation latency is measured from request entry across gate wait, checkpoint preflight, SQLite work and checkpoint publication. `blocking_reasons()` reports whether the owner is blocked on checkpoint reconciliation, restart recovery, expired reservation reconciliation, indeterminate settlement, reservation capacity, quota capacity or oldest-active age. Exporters compute rates/deltas from cumulative counters and use bounded non-secret labels.

The Evidence SQLite owner now exposes `HeptaEvidenceStore::authbus_outbox_operational_snapshot()`. Its bounded, read-only projection reports queued, leased and terminal counts; active depth; oldest unsettled age; retained claim attempts and retries; active rows that exhausted the claim limit; and retained enqueue-to-ack latency percentiles. These are retained-window values because terminal history may be pruned; they are not represented as process-lifetime counters. The query neither claims nor renews a lease, acknowledges an effect, nor advances replay state.

Bao/provider request latency remains owned by the Bao adapter and HTTP client, which are the only components that can observe it faithfully. AuthBus does not fabricate downstream observations; the qualification workflow executes Evidence, Agentd and Bao owner tests alongside the AuthBus crate.

## Product composition

`BaoClient::consume_kv_v2_with_authbus` is the current source-composed external-effect path. It combines durable operation identity, policy/quota reservation, exact final-use binding, durable dispatch fencing, final-use-protected HTTPS execution and independently signed settlement evidence. Ambiguous provider outcomes preserve the reservation as indeterminate.

Agentd is the named signed-ingress/outbox caller. Evidence outbox quarantine, claim, renew, retry and acknowledgement require a current sealed issuer handle. Wrong epoch and revoked registrations preserve queue state and cannot manufacture quarantine authority.

## Source bindings

- signed ingress and sealed message handles: `codex-rs/hepta-authbus/src/{signed,issuer_registry}.rs`;
- durable issuer and trusted-time registry: `codex-rs/hepta-authbus/src/{trust,trust_store}.rs`;
- owner, gate and checkpoint boundary: `codex-rs/hepta-authbus/src/{host,owner_fence}.rs`;
- policy/quota/reservation/settlement: `codex-rs/hepta-authbus/src/{authority_store,quota_store,settlement_store}.rs`;
- recovery/checkpoint/schema: `codex-rs/hepta-authbus/src/{recovery,authority_schema}.rs`;
- diagnostics and worker: `codex-rs/hepta-authbus/src/{operations,worker}.rs`;
- Evidence replay/outbox and delivery diagnostics: `codex-rs/hepta-evidence/src/authbus_{store,outbox,outbox_worker,recovery,operations}.rs`;
- Agentd composition: `codex-rs/hepta-agentd/src/{authbus_ingress,authbus_dispatch,authbus_trust,evidence_trust}.rs`;
- Bao composition: `codex-rs/hepta-bao-adapter/src/https_consumer.rs`.

## Failure-focused validation

The host and integration test suites prove, rather than merely assert in documentation, that:

- a failed same-process duplicate initialization does not release the live cross-process fence;
- closing an unrelated descriptor for the lock inode does not release the live cross-process fence;
- a worker retains the host and fence until the worker is dropped;
- `SIGKILL` releases the operating-system fence while restart recovery preserves ambiguous effects;
- checkpoint failures at write, file-sync, rename and directory-sync stages are classified as committed-needs-reconciliation and recover successfully;
- enrollment, rotation, revocation and retirement share the same checkpoint-failure contract;
- deterministic revision rejection is classified as not committed for the requested mutation while separately observed trusted time remains authoritative.

Evidence tests cover restart replay, outbox identity/lease behavior, retained claim/retry projection, oldest active delivery age, enqueue-to-ack latency and snapshot side-effect freedom. Bao tests retain ownership of dispatch/settlement ambiguity and provider-boundary behavior.

## Exact-candidate qualification

The detailed claim-to-source-to-test mapping is `docs/modules/auth.authbus/VERIFICATION_MATRIX.md`.

`.github/workflows/authbus-authority-qualification.yml` is read-only and validates both the exact PR head and deterministic synthetic merge candidate. It checks checkout identity, generated public API inventory, formatting, AuthBus/qualification/Evidence/Agentd/Bao tests, full workspace all-target regression, strict all-feature Clippy, clean tracked state and a receipt binding commit, tree, schema/migration digest, Cargo lock digest, test-log digests and build-artifact digest.

A skipped/cancelled/queued job, a run for another SHA, or a source-mutating workflow is not qualification evidence. Any source or documentation change invalidates prior receipts and requires a new terminal-success run for the final PR head.

## Remaining external gates and non-claims

The repository candidate does not prove production provisioning of independent checkpoint storage, non-exportable KMS/HSM keys, trusted-time service, target-host disk semantics or an external durable `kernel.operations` owner. Distributed multi-host consensus is not implemented; the supported model is one active authority owner per database on a qualified Unix target with supported descriptor-lifetime `flock` semantics.

Production activation remains blocked until one unchanged candidate obtains terminal-success exact-head and synthetic-merge receipts, target-host ENOSPC and power-loss evidence, KMS/operator acceptance and independent release approval. An indeterminate reservation is never automatically refunded merely to restore availability.
