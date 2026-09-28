# auth.authbus operations

## Deployment topology

Run one `AuthBusAuthorityHost` per authority database on a qualified Unix host. Place the SQLite database and its owner-lock file in a private local directory. Place the checkpoint in a separate private filesystem or independently retained volume so one rollback cannot restore both state domains. Agentd owns signed-message replay/outbox state; Bao is a product caller and never becomes an AuthBus writer.

The production topology has four named roles:

- **authority owner:** owns `AuthBusAuthorityHost`, its crate-private store, owner fence, serialization gate and checkpoint publication;
- **trusted-time verifier:** verifies signed monotonic time attestations before maintenance or time-dependent mutation;
- **settlement signer:** HSM/KMS-backed signer enrolled only for `Settlement` purpose;
- **observer/exporter:** exports bounded snapshots and cumulative runtime counters without write capability.

## Startup

1. Verify private directory ownership and modes.
2. Resolve immutable absolute database/checkpoint paths and owner identity.
3. For first installation only, call `bootstrap` when neither database nor checkpoint exists.
4. For every later start, call `open`; never reconstruct a missing witness.
5. Acquire the process-local claim before opening the owner-lock inode, then acquire and validate the cross-process POSIX lock.
6. Verify SQLite integrity, migrations, live schema and checkpoint generation/digest.
7. Run one bounded restart-reconciliation and expiration-maintenance batch.
8. Keep authority use fail-closed while checkpoint reconciliation or durable `recovery_required` remains outstanding.
9. Export the operational snapshot and evaluate blocking reasons before declaring ready.

Readiness requires: owner fence held, checkpoint clean, `recovery_required=false`, zero expired active holds, current trusted-time source, and no critical AuthBus alert.

## Mutation outcome handling

Never reduce every error to “retry now.” Use `AuthBusAuthorityError::mutation_disposition()` and the concrete error variant:

| Result | Operator/caller action |
| --- | --- |
| deterministic domain error / `NotCommitted` | Correct the request or stop. The requested operation did not commit. |
| `AuthorityUseBlocked` | Stop new authority use. Preserve database and witness; repair or reconcile the checkpoint/recovery condition before resuming. |
| `CheckpointReconciliationRequired` / `CommittedNeedsReconciliation` | Treat the domain mutation as committed. Run checkpoint reconciliation, then query the stable operation/issuer identity. Do not submit a duplicate mutation blindly. |
| `MutationOutcomeUnknown` / `OutcomeUnknown` | Freeze blind retries. Query durable state by stable identity and reconcile first; escalate if state cannot be proven. |
| `Ok(value)` | Both SQLite mutation and external checkpoint are durable. |

Issuer enrollment, rotation, revocation and retirement use the same contract. Host admission holds one gate from checkpoint preflight through SQLite work and checkpoint publication, so a dirty frontier blocks the next operation before its domain future is polled.

## Authority worker

The named authority worker is the only periodic maintenance path. Every tick receives a freshly verified `TrustedTimeSample`, performs bounded restart reconciliation, bounded expired-reservation sweep, checkpoint publication, operational snapshot generation and SLO evaluation. Batch size is `1..=1024`; missed ticks are skipped rather than accumulated. A worker or observer error is a readiness failure and pages the authority owner.

The worker holds `Arc<AuthBusAuthorityHost>`. Stopping the service must drop all workers before expecting the owner fence to release.

## Actionable diagnostics

Export every `AuthBusOperationalSnapshot`. Use `blocking_reasons()` as the operator-facing explanation of why work is stopped:

- `checkpoint_reconciliation`: database frontier and independent witness require reconciliation;
- `restart_recovery`: bounded crash recovery remains incomplete;
- `expired_reservation_reconciliation`: expired active holds need maintenance;
- `indeterminate_settlement`: provider outcome lacks authenticated terminal evidence;
- `active_reservation_capacity`: active reservation count is at the configured threshold;
- `quota_capacity`: aggregate quota utilization is at the configured threshold;
- `oldest_active_reservation`: the oldest active reservation exceeds the age objective.

Export cumulative runtime counters as rates/deltas:

- owner acquisition failures by active-owner, unsafe-path and storage class;
- checkpoint sync failures by rollback conflict and storage class;
- blocked authority use;
- deterministic mutation rejections, committed-needs-reconciliation and unknown outcomes;
- replay rejections;
- maintenance failures and incomplete recovery ticks.

Export complete-operation mutation and maintenance latency (`count`, `p50`, `p95`, `p99`, `max`). Mutation timing begins at public host request entry and includes gate wait, checkpoint preflight, SQLite work and checkpoint publication. Do not compare these numbers with older measurements that timed only a local transaction.

Use only bounded, non-secret labels such as result class, issuer purpose, reservation state and operation class. Never label metrics with principal, policy, message, reservation, operation or secret identifiers.

Evidence outbox claim retry and Agentd/Bao acknowledgement latency are emitted by those owning components. Correlate their bounded operation classes in the service dashboard; do not synthesize downstream observations inside AuthBus.

## Routine procedures

### Enroll or rotate an issuer

Follow `KEY_ROTATION.md`. Enroll one explicit purpose. Do not enable the signer until the mutation returns `Ok`. If it returns `CheckpointReconciliationRequired`, reconcile and inspect the exact `(issuer_id, purpose, key_epoch)` record before taking any further action. Revoke the predecessor before retirement. Never edit public-key bytes in place.

### Reconcile a dirty checkpoint

1. Stop new authority calls and keep the current owner process alive when safe.
2. Preserve the database, WAL, SHM and external checkpoint; do not copy one domain over the other.
3. Record current commit SHA, database path, checkpoint path, generations and digests.
4. Call the host checkpoint reconciliation path under the existing owner fence.
5. Require a clean snapshot and query the stable identity of the operation that returned an ambiguous result.
6. Resume only after blocking reasons are empty and the observer has exported the recovered state.

### Compact terminal reservations

Compact only `Settled`, `Released`, `Expired` or `Cancelled` rows older than the approved retention window. Keep operation identity and terminal evidence digest in the archive. Run bounded batches and require successful checkpoint publication after each batch.

### Backup

Take a consistent SQLite backup and capture the current external checkpoint separately. Label both with authority store identity, source SHA, schema digest, checkpoint generation and timestamp. A backup without its matching witness is not restorable.

## Incident classes

- **Owner collision:** do not steal or unlink the lock. Identify the live service generation and stop the duplicate deployment. Repeated same-process open failures must not release the live cross-process lock.
- **Unsafe owner/checkpoint path:** stop startup. Correct ownership, mode, symlink/hard-link or path identity; do not bypass validation.
- **Checkpoint reconciliation required:** preserve both state domains and follow the reconciliation procedure above.
- **Mutation outcome unknown:** freeze blind retry and resolve by stable identity before any compensating action.
- **Expired-active growth:** verify worker health and trusted time; increase tick frequency, not unbounded batch size.
- **Indeterminate reservation:** do not refund automatically. Reconcile with authenticated terminal provider evidence.
- **Issuer verification spike:** revoke the affected epoch if compromise is suspected and preserve rejected digest evidence.
- **Schema/integrity failure:** isolate the store; never auto-recreate or migrate around a failed check.

## Shutdown

Stop new admission, fence in-flight owner calls, stop and drop all authority workers, run one final bounded maintenance tick when safe, require a clean checkpoint, close the SQLite pool and then release the owner fence. Forced termination releases the OS lock; restart reconciliation preserves ambiguous external effects as indeterminate.

## Evidence binding

Operational claims are mapped to source and tests in `VERIFICATION_MATRIX.md`. Production change approval must reference the terminal-success exact-head and synthetic-merge receipts attached to the final PR head. A receipt for an earlier source or documentation commit is stale.
