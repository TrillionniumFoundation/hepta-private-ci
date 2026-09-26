# learning.artifacts backup, withdrawal and erasure policy

## Backup set

A recoverable backup includes immutable payload objects, registry snapshots, signed witnesses and CURRENT chain, transaction checkpoints, withdrawal and lifecycle state, reservation/refcount state, candidate-bound receipts, audit receipts and the independently retained restart anchor. The independent restart anchor must live in a separate trust and failure domain from the artifact root.

Signing private keys are excluded from artifact backups. Retain only public verification material and key/epoch metadata required to verify historical records.

## Backup creation

1. Hold or coordinate with the unique writer fence so the backup point is explicitly defined.
2. Capture the exact CURRENT head, generation, authority epoch, withdrawal head, lifecycle head and transaction state.
3. Copy immutable objects and bounded state snapshots.
4. Verify every file against its independently retained receipt.
5. Record the source commit/tree, filesystem profile, backup identity and complete manifest digest.
6. Sync the backup manifest and its containing directory before declaring the backup complete.

A copied directory without a verified manifest and independent CURRENT anchor is not an admissible backup.

## Withdrawal propagation

Logical withdrawal/revocation is append-only evidence. After a withdrawal:

- all online readers revalidate against a new authenticated current view;
- descendants of the withdrawn dependency remain ineligible;
- the withdrawal head is included in every new backup;
- older backups are catalogued as predating the withdrawal and are never restored directly to mutable readiness;
- restore admission first applies the newest independent withdrawal/tombstone set.

No backup may be used to make an old but revoked candidate appear current.

## Physical erasure

Logical revocation and physical erasure are separate operations. Physical erasure requires an authenticated deletion policy and proof that:

- retention/legal holds permit deletion;
- no live registry, transaction, selected rollback, audit requirement or admissible backup references the object;
- all backup replicas and caches are included in the deletion plan;
- the object identity and expected digest match before deletion.

Deletion follows mark → independently verify → delete → sync parent directory → append erasure receipt. Never overwrite or truncate an immutable artifact to represent erasure.

## Tombstones and keys

Tombstones and withdrawal evidence are retained at least as long as any backup or artifact they can invalidate. Deleting a tombstone while an older object remains restorable is prohibited.

Private signing keys are destroyed through the external key-management system. Historical public keys, signer identity, validity interval, revocation time and authority epoch remain available for audit verification. Reusing an epoch with a different key is prohibited.

## Garbage collection

GC is a separately authorized maintenance action under the writer fence. Its closed-world root set includes current registry/head chains, nonterminal transactions, selected rollback predecessors, withdrawal/lifecycle evidence, admissible backups and audit retention. An object is deletable only when absent from the complete root set and past retention.

GC records the examined root-set digest, candidate object digest, decision, actor and prior audit-event digest. Any uncertainty or unavailable root source is fail-closed.

## Restore gate

Restore begins read-only. Verify all receipts, replay state, compare the recovered head to the independently retained anchor, apply the newest withdrawal/tombstone evidence, and run target-host directory synchronization. Mutable readiness requires explicit operator acceptance. A restored root below the independent anchor, with missing erasure evidence, or with a different same-epoch key remains quarantined.
