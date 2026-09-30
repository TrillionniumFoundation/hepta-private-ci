# kernel.evidence operations runbook

## Normal startup

1. Verify owner-only configuration and role-distinct control files.
2. Perform read-only migration/schema/integrity preflight.
3. Load monotonic issuer trust and signer trust; reject revoked or stale policy.
4. Verify external backend identity and rollback-domain separation.
5. Read the latest external frontier and its immutable history link.
6. Verify signatures, source/build/qualification, backup and local snapshot.
7. Atomically accept the exact frontier at the authenticated snapshot.
8. Attach the Agentd host only after every preceding check succeeds.

## Publication and reconciliation

Prepare one bounded batch, then publish the exact proposed frontier. Never create
a second batch after an uncertain CAS. First attempt durable acknowledgement
recovery; otherwise compare authenticated latest/history with the exact proposed
digest. A conflicting latest value is an incident. Lease expiry or policy change
after external I/O leaves the same batch unresolved for a newly authorized
operator.

## Recovery

- `ExactDuplicate`: no-op after verification.
- `IncomingStale`: reject and preserve current state.
- `IncomingWins`: strict next-generation CAS only.
- `ConflictSameOrderDifferentIdentity`: freeze publication and investigate both
  identities; never overwrite either at the same generation.
- `InvalidIncoming`: quarantine the input.
- `InvalidCurrent`: stop attachment and recover from independently retained
  history/backup.
- `RepairRequired`: require exact signed repair authorization and a new target
  generation. Record the complete transition and authority receipt.

## Crash qualification

The hosted workflow retains machine receipts for process kill, WAL/rollback,
fsync/rename/torn-tail, disk full, damaged state, stale frontier, legacy import,
combined rollback, backup/restore, multiprocess contention and concurrent
repair/append tests. Each receipt binds tested SHA, target triple, command,
timestamps, exit status and log digest. Hosted-runner success is not target-host
acceptance; execute the same matrix on the selected filesystem/volume and retain
a distinct operator receipt.

## Incident stop conditions

Stop writes and production attachment on identity conflict, unexplained epoch or
policy jump, backend replacement, corrupt/torn history, database/frontier
mismatch, unknown external result without exact reconciliation, receipt hash
mismatch, source/build drift or any missing required readiness artifact.

## Backup and restore

Backups must be content-addressed, immutable and bound to source, executable,
qualification receipts, trust, backend and ledger root. Restore into an isolated
location, verify bytes and schema, compare against independently retained
frontier history, then obtain a restore witness. A valid old database is still a
rollback and must be rejected.
