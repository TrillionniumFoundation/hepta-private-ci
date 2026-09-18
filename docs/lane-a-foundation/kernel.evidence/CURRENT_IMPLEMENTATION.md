# `kernel.evidence` current implementation

## Current executable contract

`codex-rs/hepta-evidence` is a SQLite-backed evidence store with canonical JSON
hashing, governance validation, historical evidence, provider claims,
provider intent/terminal/effect records, signed exact-candidate qualification
receipts, independent-decision projections, durable issuer revocations, bounded
summaries and integrity-aware open paths. Equal content is idempotent; reused identity with different content
conflicts.

The checked-in migration lineage is exactly `0001` through `0011` as documented
in `STORE_V1.md`. Migration `0009` adds the AuthBus signed-admission replay
table; `0010` adds its bounded transactional message outbox, immutable payloads
and fenced leases; `0011` adds the qualification-evidence, independent-decision
and issuer-key-revocation stores.

## Public symbols and source bindings

- store open/append/query APIs and migration verification: `src/store.rs`;
- public evidence records and `EvidenceError`: `src/lib.rs`;
- provider effect storage and verification: `src/provider_effect_store.rs`;
- target qualification append/query/chain verification and issuer authentication:
  `src/qualification.rs`;
- external monotonic qualification-prefix checkpoint verification:
  `src/checkpoint.rs`;
- schema/integrity checks: `src/schema_validation.rs`;
- physical schema: `migrations/*.sql`.

## Durability and activation

The store uses the repository SQLite durability configuration and validates
quick-check, migration ledger, schema manifest, provider projections/effect
rows and foreign keys on open. A read-only diagnostic open neither creates nor
migrates. Bare store open verifies canonical qualification rows and receipt
signatures relative to the persisted issuer certificates; it does not turn a
certificate stored beside the database into an external trust anchor.

The target qualification API is composed through the existing
`codex-hepta-governance::GovernanceState` product host. Issuer authentication
uses a host-pinned `EvidenceIssuerAuthorityV1`; request payloads cannot select a
trust root. Every product qualification read, write and checkpoint operation
revalidates stored issuer certificates against that externally configured root.
Authority-aware query and chain verification also overlay the current external
issuer-revocation head, so a key revoked outside SQLite cannot continue to
support a product qualification claim merely because an older receipt remains
well-formed. The ordinary App Server installation has no default qualification
trust root, so the writer fails closed until an external trust-root ceremony
provides one through the protected host configuration seam. Activation,
independent acceptance, promotion and release remain separately gated.

## Target-only design

Signed Merkle frontiers, distributed replication, whole-database external
attestation and promotion/release authority remain target-only. Authenticated
issuer roles, independent-role collision checks, durable key/receipt revocation
and logical qualification-prefix anti-rollback checkpoints are implemented.
A checkpoint becomes an anti-rollback oracle only when retained outside the
SQLite failure domain.

## Known limits and non-claims

A mutex serializes provider-effect boundaries only among clones of one opened
store; separate opens/processes still require database transactions and
provider-owned idempotency. SQLite integrity and migration checks alone are not an external anti-rollback
oracle. `EvidenceExternalCheckpointV1` supplies the logical frontier, but an
operator must retain it independently. Evidence storage grants no execution,
selection, promotion or release authority.

## Verification

Native tests cover migration/reopen, immutable records, canonicalization,
idempotency conflict, foreign keys, corruption, provider uncertainty/effects,
EVID-01..04 qualification semantics, independent-decision bindings, durable and
external-head key revocation, pinned-root revalidation, wrong-root rejection,
external checkpoint rollback rejection and bounded queries. The
Lane A verifier pins the exact migration file set and emits exact-source plus
synthetic-merge execution receipts.

## Integration prerequisites

Writers must use typed store APIs, preserve issuer/source provenance and bind
records to exact candidates and payload digests. Operators must define backup,
restore, retention and checkpoint procedures before production activation.
