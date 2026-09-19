# `kernel.evidence` current implementation

## Current executable contract

`codex-rs/hepta-evidence` is a SQLite-backed evidence store with canonical JSON
hashing, governance validation, historical evidence, provider claims,
provider intent/terminal/effect records, authenticated exact-candidate
qualification evidence, typed independent-decision projections, bounded
queries and integrity-aware open paths. Equal content is idempotent; reused
identity with different content conflicts.

The checked-in migration lineage is exactly `0001` through `0011` as
documented in `STORE_V1.md`. Migration `0011` adds the append-only
qualification evidence hash chain, immutable store identity and
`independent_decision_receipts` projection.

## Public symbols and source bindings

- store open/append/query APIs and migration verification: `src/store.rs`;
- qualification `append_receipt`, `query_claim`, `verify_chain`, issuer
  authentication and checkpoint verification: `src/qualification.rs`;
- checkpoint-guarded production writer/independent-review ceremony CLI:
  `src/bin/hepta-evidence-writer.rs`;
- public evidence records and `EvidenceError`: `src/lib.rs`;
- provider effect storage and verification: `src/provider_effect_store.rs`;
- schema/integrity checks: `src/schema_validation.rs`;
- physical schema: `migrations/*.sql`.

## Durability and activation

The store uses the repository SQLite durability configuration and validates
quick-check, migration ledger, schema manifest, provider projections/effect
rows, qualification canonical JSON/signatures/hash chain, independent decision
projections and foreign keys on open. A read-only diagnostic open neither
creates nor migrates.

Qualification writers first require one immutable trust policy to be provisioned into the owner SQLite store before any qualification receipt exists. They then authenticate every Ed25519 issuer against that pinned, bounded, versioned trust policy before append. Every receipt binds candidate id, source
commit, source tree, claim class, payload digest, issuer role/principal/key,
credential validity and signature. An external checkpoint binds the immutable store instance id, the pinned trust-policy digest and an observed chain frontier. `open_with_checkpoint` and
its read-only counterpart reject rollback, replacement and frontier divergence.

The named `hepta-evidence-writer` caller requires the previous external
checkpoint for every production evidence mutation, writes only through the
typed store API, and emits the successor checkpoint after commit. Initial
checkpoint bootstrap is allowed only while the qualification evidence chain is
empty.

## Target-only or externally governed work

Distributed replication and signed Merkle-frontier federation are not
implemented. Durable retention/rotation of the external checkpoint remains an
operator-owned external boundary; storing the checkpoint beside the SQLite
database is not rollback protection. Independent semantic acceptance of a
specific exact candidate, target-host qualification, operator acceptance,
promotion and release remain external gates.

## Known limits and non-claims

A mutex serializes provider-effect boundaries only among clones of one opened
store; separate opens/processes still require database transactions and
provider-owned idempotency. SQLite integrity and the internal hash chain are
not an external anti-rollback oracle without an independently retained
checkpoint.

Trust-policy provisioning is configuration authority outside this store. A
caller able to replace both the configured trust policy and the external
checkpoint is outside the protection boundary. Qualification evidence grants
no execution, selection, promotion or release authority.

## Verification

Native tests cover migration/reopen, immutable records, canonicalization,
idempotency conflicts, exact candidate/tree matching, cryptographic issuer
authentication, expiry, security-authority revocation, independent-role
collision, typed `IndependentDecisionReceiptV1`, external checkpoint
replacement/rollback rejection, provider uncertainty/effects and bounded
queries. Lane A pins the exact migration file set and emits exact source-head
and synthetic-merge traceability receipts after native test/clippy execution.

## Integration prerequisites

Production operators must provision a reviewed trust policy, keep signing keys
outside the evidence store, retain checkpoint generations independently from
SQLite, define backup/restore/retention procedures, and obtain a real
independent exact-candidate signature before claiming independent acceptance.
Promotion/release consumers must continue to enforce their own separately
authorized gates.
