# kernel.evidence current implementation

## Current executable contract

`codex-rs/hepta-evidence` is a SQLite-backed evidence implementation with
canonicalization, governance validation, historical evidence, provider claims,
provider intent/terminal/effect records, summaries and integrity-aware stores.
The checked-in migration lineage is exactly:

1. `0001_governance.sql`
2. `0002_provider_evidence.sql`
3. `0003_provider_host_binding.sql`
4. `0004_memory_mutation_shadow.sql`
5. `0005_channel_ingress_evidence.sql`
6. `0006_provider_ephemeral_input.sql`
7. `0007_provider_effect_evidence.sql`
8. `0008_provider_effect_ack_source.sql`

Evidence identities are idempotent for equal content and conflicting for reused
identity with different content. Stored evidence and generated summaries do not
become authority to execute, select, promote or release.

## Target-only design

An external monotonic checkpoint, signed Merkle frontier, distributed evidence
replication and cryptographic detection of complete database replacement are
not current capabilities. They require a separate trust root and operational
ceremony.

## Known limits and non-claims

SQLite integrity, migration checksums and immutable-row controls detect the
qualified classes of local corruption and schema drift; they are not an
external anti-rollback oracle. The module cannot self-issue independent review,
operator acceptance, promotion or release.

## Verification

The Lane A verifier checks the first and eighth migration anchors and the public
store/error exports. Native evidence tests remain responsible for migration,
reopen, foreign keys, immutable records, idempotency, corruption and query
bounds.
