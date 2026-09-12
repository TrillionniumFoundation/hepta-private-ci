# `kernel.evidence` current implementation

## Current executable contract

`codex-rs/hepta-evidence` is a SQLite-backed evidence store with canonical JSON
hashing, governance validation, historical evidence, provider claims,
provider intent/terminal/effect records, bounded summaries and integrity-aware
open paths. Equal content is idempotent; reused identity with different content
conflicts.

The checked-in migration lineage is exactly `0001` through `0010` as documented
in `STORE_V1.md`. Migration `0009` adds the AuthBus signed-admission replay table; `0010` adds its bounded transactional message outbox, immutable payloads and fenced leases.

## Public symbols and source bindings

- store open/append/query APIs and migration verification: `src/store.rs`;
- public evidence records and `EvidenceError`: `src/lib.rs`;
- provider effect storage and verification: `src/provider_effect_store.rs`;
- schema/integrity checks: `src/schema_validation.rs`;
- physical schema: `migrations/*.sql`.

## Durability and activation

The store uses the repository SQLite durability configuration and validates
quick-check, migration ledger, schema manifest, provider projections/effect
rows and foreign keys on open. A read-only diagnostic open neither creates nor
migrates. Activation remains feature/caller gated.

## Target-only design

External monotonic checkpoints, signed Merkle frontiers, distributed
replication, complete-database replacement detection, authenticated evaluator
role/independence and promotion/release authority are target-only.

## Known limits and non-claims

A mutex serializes provider-effect boundaries only among clones of one opened
store; separate opens/processes still require database transactions and
provider-owned idempotency. SQLite integrity and migration checks are not an
external anti-rollback oracle. Evidence storage grants no execution, selection,
promotion or release authority.

## Verification

Native tests cover migration/reopen, immutable records, canonicalization,
idempotency conflict, foreign keys, corruption, provider uncertainty/effects
and bounded queries. The Lane A verifier pins the exact migration file set.

## Integration prerequisites

Writers must use typed store APIs, preserve issuer/source provenance and bind
records to exact candidates and payload digests. Operators must define backup,
restore, retention and checkpoint procedures before production activation.
