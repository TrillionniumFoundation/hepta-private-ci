# kernel.evidence operations runbook

## Normal startup

1. Verify owner-only configuration and role-distinct control files.
2. Perform read-only migration/schema/integrity preflight.
3. Load monotonic issuer trust and signer trust; reject revoked or stale policy.
4. Verify external backend identity and rollback-domain separation.
5. Under the backend store lock, replay sealed segments from genesis, verify each
   record transition, then verify the archive-to-active boundary and latest
   index projection.
6. Verify frontier signatures, source/build/qualification, backup and local
   snapshot.
7. Atomically accept the exact frontier at the authenticated database snapshot.
8. Attach the Agentd host only after every preceding check succeeds.

## Publication and reconciliation

Prepare one bounded batch, then publish the exact proposed frontier. Never create
a second batch after an uncertain CAS. The backend rereads and classifies the
current durable frontier while holding the same exclusive lock used for the
write. Only `IncomingWins` can append a new ordinary audit record.

First attempt durable acknowledgement recovery; otherwise compare authenticated
latest/history with the exact proposed digest. A conflicting latest value is an
incident. Lease expiry or policy change after external I/O leaves the same batch
unresolved for a newly authorized operator.

## Recovery

- `ExactDuplicate`: no-op only after exact canonical verification.
- `IncomingStale`: reject and preserve current state.
- `IncomingWins`: strict next-generation CAS only.
- `ConflictSameOrderDifferentIdentity`: freeze publication and investigate both
  identities; never overwrite either at the same generation.
- `InvalidIncoming`: quarantine the input.
- `InvalidCurrent`: stop attachment and recover from independently retained
  history/backup.
- `RepairRequired`: stop normal publication. Verify the exact signed repair
  authorization, but do not send it through ordinary CAS. A separately
  qualified repair publisher must durably consume the nonce, retain the full
  authorization/current/target audit subject and execute only that one new-
  generation transition. Agentd does not currently compose that service.

A repair document by itself is not a runnable administrative capability. Until
the external repair publisher and ceremony are independently deployed and
accepted, leave the host in `recovery_required`.

## Crash qualification

The hosted workflow retains machine receipts for process kill, WAL/rollback,
fsync/rename/torn-tail, disk full, damaged state, stale frontier, legacy import,
combined rollback, backup/restore, multiprocess contention and concurrent
repair/append tests. The damaged/stale cases include lock-time reclassification,
rehash-resistant journal replay and the production segmented archive-to-active
boundary.

Each receipt binds source commit/tree, immutable base, workflow SHA, run ID and
attempt, runner image, target triple, command, timestamps, exit status and log
digest. The four required candidate receipts and crash summary must come from
the same identity tuple. Hosted-runner success is not target-host acceptance;
execute the same matrix on the selected filesystem/volume and retain a distinct
operator receipt.

## Incident stop conditions

Stop writes and production attachment on identity conflict, unexplained epoch or
policy jump, backend replacement, corrupt/torn history, non-automatic history
transition, database/frontier mismatch, unknown external result without exact
reconciliation, receipt hash mismatch, source/build drift or any missing
required readiness artifact.

## Backup and restore

Backups must be content-addressed, immutable and bound to source, executable,
qualification receipts, trust, backend and ledger root. Restore into an isolated
location, verify bytes and schema, replay the independently retained frontier
history, then obtain a restore witness. A valid old database is still a rollback
and must be rejected.
