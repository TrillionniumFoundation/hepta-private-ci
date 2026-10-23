# auth.authbus schema compatibility

## Compatibility rule

The compiled migration set is the sole schema source. Store open applies forward migrations, then compares the complete live SQLite schema with a transient database built from the same migration set. Post-migration `quick_check`, foreign-key validation and schema digest qualification are required before readiness.

## Change classes

- **Additive compatible:** new table/index/trigger or nullable/defaulted column whose old semantics remain unchanged.
- **Coordinated compatible:** new non-null field, state or invariant requiring a writer/read rollout plan and explicit mixed-version tests.
- **Breaking:** changed meaning, removed state, rewritten identity, changed digest scope or migration that an old binary can misinterpret. Breaking changes require a new contract/schema generation and offline migration plan.

Migrations are append-only after merge. Editing a released migration is prohibited. Every migration has a stable filename, bytes digest and ordered aggregate schema digest.

## Binary/store matrix

| Binary | Store | Result |
| --- | --- | --- |
| current | predecessor | migrate forward, verify, open |
| current | current | verify, open |
| current | newer unknown | fail closed |
| predecessor | current | unsupported unless explicit downgrade compatibility was qualified |
| any | schema drift with unchanged ledger | fail closed |

## Rollback

Application rollback across a schema boundary is permitted only with a matched pre-migration database and external checkpoint backup, or with an explicitly qualified backward-compatible binary. SQL down-migrations are not assumed. Restoring only the database or only the witness is invalid.

## Qualification evidence

The exact-head receipt records ordered migration-file SHA-256 values, aggregate schema digest, candidate commit/tree, Cargo lock digest and test-artifact digest. Schema qualification also exercises clean migration, reopen, drift injection, integrity failure and predecessor restore.
