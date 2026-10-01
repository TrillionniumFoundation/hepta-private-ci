# auth.authbus recovery

## Recovery principles

Recovery never guesses whether an external effect happened. It never recreates
a missing checkpoint for an existing database, lowers a generation, rewrites an
issuer epoch or releases an indeterminate reservation without authenticated
terminal evidence.

The independently retained checkpoint and the SQLite authority database are
separate state domains. A usable recovery set always contains a matched pair and
its immutable backup manifest.

## State classification

| Observation | Action |
| --- | --- |
| local checkpoint equals external and local frontier clean | open normally |
| local checkpoint equals external and local frontier dirty | fold pending frontier changes, publish exactly one successor, then promote locally |
| external is exactly one generation ahead and digest equals the durable incremental root | promote external successor locally |
| external older, more than one generation ahead, wrong owner or wrong digest | `RollbackDetected`; isolate |
| pending frontier journal rows exist | fold in increasing `change_id`; never delete or edit them manually |
| pending frontier journal exceeds the bounded fold limit | keep authority use blocked and reconcile under operator control |
| dispatch-attempted reservation after restart | convert to `Indeterminate` in a bounded batch |
| held reservation expired before dispatch | refund and mark `Expired` |
| dispatch-attempted reservation expired | retain quota and mark `Indeterminate` |

## Incremental frontier recovery

Migration `0006_incremental_frontier.sql` seeds the accumulator once from the
legacy complete ordered frontier. Thereafter every authoritative mutation
commits its canonical change event and dirty bit in the same SQLite transaction.

The accumulator root, applied change ID and pruning of covered journal rows also
commit atomically. A crash before that transaction leaves the events pending. A
crash after it leaves the new root durable and the dirty bit set, so publication
retries the same successor without scanning all historical rows. An external
witness one generation ahead is accepted only when its digest equals that
durable root.

See `INCREMENTAL_FRONTIER.md` for the hash transition, limits and complete crash
matrix.

## Standard restart

1. Stop duplicate owners and confirm the process-lifetime owner fence is free.
2. Preserve copies of the database, WAL/SHM files, owner-lock database and
   external checkpoint.
3. Start the exact qualified binary with the original immutable paths and owner
   identity.
4. Verify database integrity, migration ledger, live schema, incremental
   accumulator and external witness.
5. Run bounded restart reconciliation. Write admission remains blocked while
   rows remain.
6. Run bounded expiration sweep with fresh trusted time.
7. Fold pending frontier changes, publish/promote the checkpoint and verify a
   clean operational snapshot.
8. Re-enable traffic only after critical alerts clear.

## Checkpoint publication failure

A failure before rename leaves the external witness unchanged and local state
dirty. Remove only a proven temporary file created by the failed generation,
then retry reconciliation through the host. A failure after rename but before
local promotion may leave the external witness one generation ahead; the next
reconciliation must verify the durable incremental root and promote only on
exact digest equality.

Never edit checkpoint JSON, accumulator rows or frontier journal rows manually.
Never copy the database over the checkpoint domain. Never call bootstrap to
repair an existing store.

## Backup and restore verification

Use `hepta-authbus-admin backup` while product traffic is stopped. The command
holds the production owner fence, synchronizes the checkpoint, validates SQLite,
truncates the WAL, and writes the database and witness into distinct private
directories together with a SHA-256 manifest.

Run `hepta-authbus-admin restore-check` on a staged copy, never on the only
retained backup. It verifies the manifest before opening the pair through the
production recovery path. See `ADMINISTRATION.md`.

## Database corruption or schema drift

Quarantine the host. Preserve all files and exact binary/source identity.
Restore a matched database-and-witness backup into isolated paths, verify its
manifest, run integrity and exact-schema checks, then perform restore-check with
no product traffic. If no matched pair exists, escalate to independent recovery
review; do not synthesize a witness.

## Indeterminate provider effects

Query the provider using the immutable operation identity and provider
reconciliation protocol. Accept only authenticated terminal evidence bound to
reservation ID, operation ID, issuer purpose/epoch, observed cost and terminal
digest. Until then, retain quota and keep the state indeterminate.

## Fault-injection matrix

Repository qualification covers owner collision, process kill, write failure,
file-sync failure, rename failure, directory-sync ambiguity, incremental
frontier crash/reopen, restored old database, missing witness, foreign owner and
provider timeout.

Target-host ENOSPC, permission-loss, real power-loss and old-snapshot tests
remain deployment acceptance evidence. They must run the unchanged candidate
through `.github/workflows/authbus-target-host-qualification.yml`; a hosted CI
simulation does not satisfy that gate.
