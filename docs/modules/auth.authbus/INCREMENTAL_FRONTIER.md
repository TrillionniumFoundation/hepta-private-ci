# AuthBus incremental authority frontier

## Status and purpose

Migration `0006_incremental_frontier.sql` replaces history-sized checkpoint
recomputation on the normal mutation path with a bounded, transactionally
recorded change journal and a persisted hash accumulator. It does not create a
second authority store. SQLite policy, issuer, trusted-time, quota, reservation,
settlement and archive rows remain the only authoritative facts.

An existing database is seeded once from the exact ordered
`hepta.authbus.authority-frontier.v1` snapshot. This preserves the checkpoint
digest already retained outside SQLite. After the seed transaction commits,
normal checkpoint publication folds only changes committed since the previous
accumulator position.

## Durable objects

`authbus_frontier_accumulator` contains one row:

- `schema_version`: currently `1`;
- `root_digest`: the last durable authority frontier root, or `NULL` before the
  one-time seed;
- `applied_change_id`: the greatest journal row already covered by
  `root_digest`.

`authbus_frontier_change` is an append-only same-database journal:

- `change_id`: strictly increasing SQLite identity;
- `domain`: bounded authority domain name;
- `operation`: `upsert` or `delete`;
- `record_key`: stable row identity;
- `canonical_record`: a complete canonical after-image or deleted image.

Triggers append a journal row in the same SQLite transaction as every covered
trusted-time, policy, policy-history, policy-archive, quota, reservation,
reservation-archive and issuer mutation. Pending rows cannot be updated or
deleted, including by a direct SQL caller. History/archive tables retain their
separate immutable triggers.

## Hash transition

For each pending row in `change_id` order, the owner computes:

```text
H(
  "hepta.authbus.authority-frontier.change.v2\0" ||
  previous_root ||
  u64_be(change_id) ||
  len(domain) || domain ||
  len(operation) || operation ||
  len(record_key) || record_key ||
  len(canonical_record) || canonical_record
)
```

The new root and the greatest applied change ID are committed atomically. Only
rows at or below that durable applied ID are then pruned in the same
transaction. The checkpoint dirty bit is cleared only after the corresponding
external witness has been published and the local checkpoint generation has
been promoted.

The fold is bounded to 32,768 pending changes per checkpoint reconciliation.
Each encoded event is bounded to 64 KiB. Because the host serializes every
authority mutation with checkpoint publication, normal requests generate only
the changes from one logical operation. Exceeding the bound fails closed and
requires operator reconciliation; it never silently drops events or falls back
to an unbounded scan.

## Seed and compatibility

The first call after migration performs one complete ordered v1 snapshot under
`BEGIN IMMEDIATE`, stores that exact digest as the accumulator root, advances
past any migration-time journal rows, and prunes those covered rows. The
external witness therefore does not change merely because the binary learned
the new accumulator representation.

A predecessor binary must not open a database after migration `0006` unless an
explicit downgrade contract has been qualified. Application rollback uses a
matched pre-migration database and witness pair.

## Crash and rollback behavior

| Crash point | Durable state | Recovery |
| --- | --- | --- |
| authority mutation rolls back | no authority row and no journal row | no checkpoint work |
| authority mutation commits | authority row, journal row and dirty bit commit together | fold journal before publication |
| accumulator transaction rolls back | journal remains pending | retry the same ordered fold |
| accumulator commits before external publish | new root durable, journal pruned, dirty bit still set | propose the same successor root |
| external publish commits before local promotion | external is exactly one generation ahead | verify the durable accumulator root and promote locally |
| old database restored with newer witness | old accumulator/root cannot match newer witness | `RollbackDetected` |
| pending journal tampered or deleted | immutable/delete trigger or sequence/content validation fails | isolate the store |

## Verification

`recovery_tests.rs` proves:

- the complete snapshot is used only for the one-time seed;
- later checkpoints use the incremental chain;
- applied journal rows are pruned;
- pending rows survive close/reopen and fold idempotently;
- pending rows cannot be deleted before accumulation;
- a newer external witness still rejects a real old-database restore.

The exact-head receipt binds the ordered migration digest, Rust source and test
logs. Target-host power-loss qualification remains a separate activation gate.
