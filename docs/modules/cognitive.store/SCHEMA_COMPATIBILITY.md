# Schema migration and binary compatibility

The physical schema is owned by `codex-rs/hepta-memory/migrations` and verified on every open against the required schema-object oracle. SQLx migration checksums are immutable; editing an applied migration is forbidden.

## Compatibility matrix

| Database state | Binary action | Writable? | Required evidence |
|---|---|---:|---|
| Empty/new | apply all embedded migrations, verify schema/integrity | only after external authority | migration command record and initial cut |
| Exact current migration set | verify objects, owner and integrity | yes after fenced recovery/bootstrap | exact current-cut and authority receipts |
| Older supported set | migrate a private/controlled generation, verify, then publish | not until migration succeeds | pre/post anchors, migration checksums, reopen test |
| Newer unknown set | fail closed | no | operator upgrade decision |
| Missing/modified object | classify corrupt/indeterminate | no | forensic copy and recovery ceremony |
| Older valid backup | reject for writer recovery unless independently current | no | current external witness |
| Candidate generation after ambiguous pointer publish | reconcile active pointer; preserve files | no automatic fallback | recovery reconciliation receipt |

## Migration rules

1. Every migration is forward-only and deterministic.
2. Append-only tables and no-update/no-delete triggers retain historical meaning.
3. New nullable/additive fields require explicit default semantics; authority-critical absence fails closed.
4. Digest domains, stable-id construction and existing enum meanings never change in place.
5. A migration that changes canonical semantics creates a new schema/versioned contract and compatibility adapter.
6. Migration, source/Memory/fact mutation and product activation are separate events.

## Upgrade procedure

1. Quiesce writes and reconcile outstanding outbox/indeterminate operations.
2. Capture and externally authenticate the exact pre-upgrade cut.
3. Copy retained database/WAL/journal descriptors into a private generation.
4. Apply embedded migrations to the private generation.
5. Verify required objects, migration checksums, foreign/key/count invariants and `integrity_check`.
6. Reconstruct the semantic cut and validate declared migration transforms.
7. Checkpoint, fsync and atomically publish the active-generation pointer.
8. Reopen, compare the post-upgrade cut, run a capability-bound canary and capture a new signed witness.

## Rollback

Rollback is permitted only when the rollback binary declares the resulting schema compatible. It uses the same current data, a fresh external authority state and a strictly newer writer generation. Restoring a pre-upgrade backup without a current witness is forbidden. If downgrade compatibility is absent, keep the migrated generation read-only and roll forward.

## Required qualification

- empty, current and every supported predecessor migration path;
- crash before/after each migration transaction and pointer publication boundary;
- reopen with WAL and checkpointed images;
- semantic head/fact/projection oracle before and after migration;
- rollback-binary compatibility test;
- maximum retained profile and migration-space budget.
