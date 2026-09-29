# auth.authbus schema compatibility

## Compatibility rule

The compiled migration set is the sole schema source. Store open applies forward
migrations, then compares the complete live SQLite schema with a transient
database built from the same migration set. Post-migration `quick_check`,
foreign-key validation and schema digest qualification are required before
readiness.

## Change classes

- **Additive compatible:** new table/index/trigger or nullable/defaulted column
  whose old semantics remain unchanged.
- **Coordinated compatible:** new non-null field, state or invariant requiring a
  writer/read rollout plan and explicit mixed-version tests.
- **Breaking:** changed meaning, removed state, rewritten identity, changed
  digest scope or migration that an old binary can misinterpret. Breaking
  changes require a new contract/schema generation and offline migration plan.

Migrations are append-only after merge. Editing a released migration is
prohibited. Every migration has a stable filename, bytes digest and ordered
aggregate schema digest.

## Migration 0006: incremental frontier

`0006_incremental_frontier.sql` is a coordinated-compatible storage upgrade for
the current binary and a downgrade boundary for predecessor binaries. It adds:

- one singleton `authbus_frontier_accumulator`;
- one append-only `authbus_frontier_change` journal;
- immutable/pending-delete guards;
- same-transaction canonical change triggers for every authority domain.

The first current-binary open seeds the accumulator from the exact legacy v1
full-state digest. Therefore the external checkpoint does not change merely
because the representation was upgraded. Later roots are a versioned
domain-separated hash chain over committed changes. A predecessor binary does
not understand that chain and must not open the migrated store unless an
explicit backward-compatibility qualification exists.

Migration-time rows are covered by the seed and pruned only after the seed root
and applied ID commit together. Existing databases with a newer external
witness still fail closed.

## Binary/store matrix

| Binary | Store | Result |
| --- | --- | --- |
| current | predecessor through 0005 | migrate through 0006, seed legacy root, verify, open |
| current | current 0006 | verify accumulator/journal/schema, open |
| current | newer unknown | fail closed |
| predecessor | current 0006 | unsupported; restore a matched pre-0006 pair |
| any | schema drift with unchanged ledger | fail closed |

## Rollback

Application rollback across a schema boundary is permitted only with a matched
pre-migration database and external checkpoint backup, or with an explicitly
qualified backward-compatible binary. SQL down-migrations are not assumed.
Restoring only the database or only the witness is invalid.

## Qualification evidence

The exact-head receipt records ordered migration-file SHA-256 values, aggregate
schema digest, candidate commit/tree, Cargo lock digest and test-artifact
digest. Schema qualification exercises clean migration, reopen, drift
injection, integrity failure, incremental seed/fold/prune behavior and
predecessor restore.

See `INCREMENTAL_FRONTIER.md`, `RECOVERY.md` and `ADMINISTRATION.md`.
