# learning.artifacts observability contract

## Principles

Observability must describe the exact owner state without becoming a second authority path. Metrics and events never contain payload bytes, private keys, bearer credentials, complete signatures or unbounded diagnostic strings. Every mutable event is emitted only after the corresponding owner transition result is known.

## Required metrics

Counters:

- `learning_artifacts_publication_total{result,phase}`;
- `learning_artifacts_recovery_total{result,last_durable_phase}`;
- `learning_artifacts_admission_rejection_total{reason}`;
- `learning_artifacts_signature_rejection_total{reason}`;
- `learning_artifacts_generation_conflict_total`;
- `learning_artifacts_indeterminate_io_total{operation}`;
- `learning_artifacts_lock_contention_total{mode}`;
- `learning_artifacts_snapshot_fallback_rejection_total{reason}`;
- `learning_artifacts_ranker_abstention_total{reason}`;
- `learning_artifacts_orphan_reconciliation_total{result}`;
- `learning_artifacts_key_rotation_total{result}`;
- `learning_artifacts_backup_restore_total{phase,result}`.

Gauges:

- `learning_artifacts_ready`;
- `learning_artifacts_writer_fence_held`;
- `learning_artifacts_recovery_required`;
- `learning_artifacts_current_generation`;
- `learning_artifacts_current_authority_epoch`;
- `learning_artifacts_registry_records`;
- `learning_artifacts_lifecycle_records`;
- `learning_artifacts_withdrawal_records`;
- `learning_artifacts_pending_reservations`;
- `learning_artifacts_oldest_pending_reservation_seconds`;
- `learning_artifacts_gc_backlog_objects`;
- `learning_artifacts_audit_sink_available`.

Histograms:

- writer lock wait;
- read lock wait;
- publication phase latency;
- payload write plus file sync;
- containing-directory sync;
- owner startup and recovery;
- registry/withdrawal/lifecycle replay;
- authenticated CURRENT verification;
- backup verification and restore admission.

Concrete alert thresholds are deployment-profile data and must not be hard-coded into the crate.

## Structured audit event

Each event binds:

```text
schema/version
service instance and boot identity
operation/request identity
authenticated principal digest and authority epoch
scope digest
action
result and bounded reason code
prior/new generation
prior/new head digest
publication phase
source commit/tree and configuration digest
timestamp and monotonic sequence
previous audit-event digest
event digest
```

The audit stream is append-only and hash chained. The sink is independently retained from the artifact root. Failure of the required audit sink closes mutable readiness; it must not silently drop publication or key-rotation events.

## Alerts

Immediate pages:

- writer fence lost or duplicated;
- CURRENT head, epoch or independent restart anchor rollback;
- corrupt or forked registry/head chain;
- indeterminate publication I/O;
- recovery loop or unresolved nonterminal publication;
- audit sink unavailable while a mutable route is enabled;
- backup restored below the independent current anchor;
- refcount/receipt/object digest inconsistency.

Warnings:

- sustained lock contention;
- reservation age or count approaching capacity;
- registry or snapshot size approaching supported ceiling;
- repeated ranker abstention or current-view rejection;
- orphan or GC backlog growth;
- key or writer lease nearing expiry.

Ranker fail-soft behavior must be visible by reason. A missing, revoked, tombstoned, corrupt or stale candidate must not collapse into one generic “no signal” metric.
