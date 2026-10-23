# auth.authbus recovery

## Recovery principles

Recovery never guesses whether an external effect happened. It never recreates a missing checkpoint for an existing database, lowers a generation, rewrites an issuer epoch or releases an indeterminate reservation without authenticated terminal evidence.

## State classification

| Observation | Action |
| --- | --- |
| local checkpoint equals external and local frontier clean | open normally |
| local checkpoint equals external and local frontier dirty | publish exactly one successor, then promote locally |
| external is exactly one generation ahead and digest equals recomputed dirty frontier | promote external successor locally |
| external older, more than one generation ahead, wrong owner or wrong digest | `RollbackDetected`; isolate |
| dispatch-attempted reservation after restart | convert to `Indeterminate` in a bounded batch |
| held reservation expired before dispatch | refund and mark `Expired` |
| dispatch-attempted reservation expired | retain quota and mark `Indeterminate` |

## Standard restart

1. Stop duplicate owners and confirm the process-lifetime owner fence is free.
2. Preserve copies of the database, WAL/SHM files, owner-lock database and external checkpoint.
3. Start the exact qualified binary with the original immutable paths and owner identity.
4. Verify database integrity, migration ledger, live schema and external witness.
5. Run bounded restart reconciliation. Write admission remains blocked while rows remain.
6. Run bounded expiration sweep with fresh trusted time.
7. Publish/promote the checkpoint and verify a clean operational snapshot.
8. Re-enable traffic only after critical alerts clear.

## Checkpoint publication failure

A failure before rename leaves the external witness unchanged and local state dirty. Remove only a proven temporary file created by the failed generation, then retry reconciliation through the host. A failure after rename but before local promotion may leave the external witness one generation ahead; the next reconciliation must recompute the frontier and promote only on exact digest equality.

Never edit checkpoint JSON manually. Never copy the database over the checkpoint domain. Never call bootstrap to repair an existing store.

## Database corruption or schema drift

Quarantine the host. Preserve all files and exact binary/source identity. Restore a matched database-and-witness backup into isolated paths, run integrity and exact-schema checks, then perform a dry open with no product traffic. If no matched pair exists, escalate to independent recovery review; do not synthesize a witness.

## Indeterminate provider effects

Query the provider using the immutable operation identity and provider reconciliation protocol. Accept only authenticated terminal evidence bound to reservation ID, operation ID, issuer purpose/epoch, observed cost and terminal digest. Until then, retain quota and keep the state indeterminate.

## Fault-injection matrix

Qualification covers owner collision, process kill, write failure, file-sync failure, rename failure, directory-sync ambiguity, restored old database, missing witness, foreign owner and provider timeout. Target-host ENOSPC and power-loss tests remain deployment acceptance evidence and must use the same qualified binary.
