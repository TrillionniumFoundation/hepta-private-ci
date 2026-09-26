# automation.taskflow schema-v19 migration and recovery runbook

**Automation store schema: v19.** This runbook is operational guidance for the
single per-Agent `AutomationStore`; it does not authorize a provider, mint a
final-use grant, transfer ownership to a second scheduler or certify a host.

## Migration topology

| Store cut | Durable addition | Recovery rule |
|---|---|---|
| v16 | terminal-observer cursor | Preserve the exact opaque App Server cursor and resume by CAS. |
| v17 — `0017_kernel_operation_dedupe.sql` | `destination_operation_dedupe` | Immutable destination/scope/operation receipts are committed with the destination mutation. |
| v18 — `0018_timer_lifecycle.sql` | `automation_timer_lifecycle` | One writer epoch owns `active -> draining -> active/retired`; unresolved dispatches block epoch transfer. |
| v19 — `0019_converged_owner_schema.sql` | converged owner schema | Recognize only the reviewed displaced v17/v18 SQLx version/checksum pairs, remap those known histories, then validate normal migrations. |

`AUTOMATION_SCHEMA_VERSION`, the highest migration number and this document must
remain equal. Unknown checksums, duplicate semantic migrations, a dirty SQLx row,
missing triggers/tables, failed integrity checks or a non-positive writer epoch
fail the open before the process publishes readiness.

## Pre-upgrade procedure

1. Stop new automation admission and request timer draining.
2. Reconcile or explicitly retain every dispatch-unknown/provider-indeterminate
   attempt. Never convert an absent local receipt into provider absence.
3. Require no leased compatibility run and no unresolved dispatch before writer
   epoch handoff.
4. Stop the old process and take a crash-consistent copy of the database together
   with `-wal` and `-shm` when present. Record SHA-256, byte length, owner AgentId,
   writer epoch, schema version, binary commit, provider-host configuration digest,
   revocation frontier and filesystem permissions.
5. Copy the snapshot to protected storage before starting the v19 binary.

A live file copy without SQLite backup semantics is not a backup.

## Upgrade and verification

Start exactly one v19 owner. Opening performs legacy migration-ID reconciliation,
SQLx migration, private-file protection and full store verification before the
scheduler becomes ready. Then run the migration-convergence test matrix, open a
copy of every supported historical cut, verify the expected tables/triggers and
exercise one due occurrence, one dispatch-unknown reconciliation, one terminal
cursor continuation and one timer drain/resume cycle.

## Failure recovery

* Failure before migration commit: stop the candidate and reopen only after
  verifying the original snapshot and current files. Do not edit `_sqlx_migrations`.
* Ambiguous filesystem or SQLite error: fence the writer, retain all files and
  restore the complete pre-upgrade snapshot into a fresh private directory.
* Provider contact may have occurred: preserve the existing attempt and perform
  owner lookup with the same provider key. Never allocate a new external effect
  attempt until the registered owner proves absence.
* Cursor history exhausted without the bound turn: retain the durable
  indeterminate observation; do not infer success, failure or cancellation.

## Rollback and old binaries

Older binaries **MUST NOT** open, replace or write a schema-v19 database. Rollback
is not `UPDATE automation_meta SET schema_version = ...`; it is restoration of a
complete pre-upgrade snapshot with the exact matching binary, provider host,
revocation material and owner identity. New v17/v18/v19 rows must never be dropped
or projected into an older format.

## Cross-host boundary

Timer epoch handoff is a same-store ownership protocol, not cross-host replication.
A cross-host move is permitted only when admission is drained, the old writer is
stopped, an authenticated complete snapshot manifest is verified on the target,
exclusive filesystem/database ownership is established, target configuration and
revocation digests match, and the selected host re-runs recovery qualification.
Without those facts the target fails closed. Shared writable SQLite, concurrent
copy-and-run and treating a checkpoint receipt as distributed atomicity are
forbidden.
