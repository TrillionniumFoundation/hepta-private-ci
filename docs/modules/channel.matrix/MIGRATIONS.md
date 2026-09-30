# channel.matrix migration and rollback manual

Status: executable operator contract. This document describes repository-owned
SQLite transitions; it is not a migration execution, restore, deployment,
activation or release receipt.

## 1. Ownership and compatibility floor

`MatrixDurableStore` is the only writer for the per-Agent Matrix database. The
current schema floor is migration **13**. A binary that understands only
migrations 1–12 is not a valid rollback target because it cannot preserve
migration-13 inbox recovery scheduling and quarantine. Migrations 6–13 also add
dispatch, authority, canonical-content, entered-use and legacy-hold semantics
that older binaries must not ignore.

The database, WAL, SHM, Matrix session store, final-use authority state and
revocation frontier form one recovery unit. Never delete one member to make a
startup check pass.

## 2. Preconditions before upgrade

Before starting a candidate binary:

1. Stop the previous Matrix writer and verify that its supervisor process lease
   is no longer live.
2. Preserve the exact database/WAL/SHM and session/authority files as an
   authenticated, immutable backup.
3. Record candidate commit/tree, binary digest, `Cargo.lock` digest, current
   migration inventory digest, SQLite version and host identity.
4. Verify private root ownership, mode, canonical path and available disk space.
5. Require a fresh authenticated revocation frontier and Matrix session before
   work is admitted.
6. Do not perform an in-place manual SQL repair. A repair must be implemented as
   a reviewed migration or executed against a copied recovery candidate.

The startup process lock and supervisor fence must be held for the entire open,
migration, schema verification and initial-sync sequence.

## 3. Migration inventory

| Version | SQL source | Durable contract introduced |
|---:|---|---|
| 1 | `0001_matrix_durable.sql` | Initial room, inbox, outbox and owner-local durable state. |
| 2 | `0002_matrix_sync_checkpoint.sql` | Durable `/sync` checkpoint and cursor continuity. |
| 3 | `0003_outbox_logical_stream.sql` | Stable logical outbox stream and transaction identity. |
| 4 | `0004_matrix_control.sql` | Matrix control and pending-approval ownership. |
| 5 | `0005_matrix_sync_mutations_v2.sql` | Atomic typed sync mutations, corrections and redactions. |
| 6 | `0006_matrix_dispatch_ledger.sql` | Immutable dispatch ledger, observations and authority claims. |
| 7 | `0007_matrix_claim_fencing.sql` | Random-capability attempt fencing and append-only attempt history. |
| 8 | `0008_matrix_content_binding.sql` | Immutable canonical content/scope binding. |
| 9 | `0009_matrix_legacy_content_holds.sql` | Sealed inherited unknown-effect identities. |
| 10 | `0010_matrix_entered_use_proofs.sql` | Durable non-constructible entered-use proof. |
| 11 | `0011_matrix_legacy_hold_remediation.sql` | Stale-claim closure and non-runnable legacy queue parking. |
| 12 | `0012_matrix_terminal_any_entered_attempt.sql` | Delayed terminal echo qualification against an earlier entered attempt. |
| 13 | `0013_matrix_inbox_recovery.sql` | Durable fair recovery scheduling, failure class and monotone quarantine. |

The inventory is closed and ordered. Renaming, removing, reordering or changing
bytes under an already-applied version is corruption, not a new migration.

## 4. Transaction and interruption rules

Each migration runs through the owner connection and must either commit fully or
leave the previous schema readable. Startup subsequently verifies exact table,
index, view and trigger SQL, foreign keys, integrity and semantic invariants.
A process crash, I/O error, disk-full result or lost acknowledgement during
migration therefore has one permitted response: stop the writer, preserve the
image and restart verification against the same files. Do not infer that an
unacknowledged step was absent.

For migrations that materialize rows from historical work:

- logical send, stable transaction, attempt, event and claim identities remain
  unchanged;
- unknown effects remain unresolved;
- terminal observations and audit rows are never deleted;
- migration replay must be idempotent under SQLite transaction rollback;
- capacity applies to active/unresolved work, not permission to erase retained
  evidence.

## 5. Post-migration verification

Before readiness is exposed, require all of the following:

- `PRAGMA integrity_check` and foreign-key verification succeed;
- the applied migration table exactly matches committed versions 1–13;
- exact canonical SQL for required tables, indexes, views and triggers matches
  the candidate;
- no legacy hold is runnable;
- qualified success/redaction has a matching entered-use proof;
- active claim attempt, lease epoch and capability digest agree;
- inbox recovery rows refer to retained pending events and quarantine is not
  silently cleared;
- one durable `/sync` completes before recovery or background dispatch begins;
- source-head and deterministic-merge qualification receipts bind this exact
  candidate and report a clean checkout.

Operators should retain the startup log, schema report, database image digest
and candidate receipt together. A successful schema open is not target-host or
homeserver qualification.

## 6. Rollback decision

Binary rollback is allowed only when the target binary understands every
committed migration and record. For a migration-13 store, the normal recovery is
**roll forward** with a corrected binary. Restoring an older authenticated backup
is a data recovery operation, not a binary rollback; it must also restore the
matching session, authority and revocation state and then run the full restore
qualification matrix.

Never roll back by:

- deleting the database, WAL, SHM, audit rows, entered-use proof or legacy hold;
- editing the migration table;
- assigning a new transaction ID to an unresolved send;
- converting `Indeterminate` to `Failed` because evidence is inconvenient;
- clearing quarantine or attempts by inference from process death;
- copying only the SQLite main file while omitting live WAL state.

## 7. Recovery drill

A qualified recovery drill uses a copy of the failed image and records:

1. original file identities and hashes;
2. injected failure point, including ENOSPC, permission loss, WAL/SHM damage or
   stale snapshot restoration;
3. exact candidate and recovery-tool identities;
4. integrity/schema findings before any change;
5. authenticated backup identity and matching authority/session frontier;
6. reopened durable state, unresolved sends, quarantines and sync checkpoint;
7. proof that no old generation, claim, session or authority can commit;
8. real `/sync` reconciliation and redaction behavior after restore.

The drill must fail closed when any component is missing or inconsistent.

## 8. Capacity and retention

Completed dispatch history is append-only evidence. Retention/archival may move
an authenticated closed history segment only after an independent policy proves
that anti-replay, investigation and rollback requirements remain satisfied.
Active, accepted, indeterminate, legacy-held or quarantined work is never an
archival candidate. Monitor database/WAL size, oldest unresolved age, pending
physical erase bytes, checkpoint duration and archive verification failures.

## 9. Required receipts

A production migration or restore receipt must bind:

- candidate commit/tree and binary digest;
- migration and implementation-map hashes;
- pre/post database, WAL, session and authority-state identities;
- SQLite/toolchain/host identity;
- exact fault parameters for drills;
- startup/schema/integrity output;
- source-head, deterministic-merge and target-host results;
- independent operator/security signatures.

Receipts do not grant activation, promotion or release. Those remain distinct
externally governed decisions.
