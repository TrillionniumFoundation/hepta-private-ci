# `kernel.evidence` current implementation

## Current executable contract

`codex-rs/hepta-evidence` is a SQLite-backed evidence store with canonical JSON
hashing, governance validation, historical evidence, provider claims,
provider intent/terminal/effect records, bounded summaries and integrity-aware
open paths. Equal content is idempotent; reused identity with different content
conflicts.

The checked-in migration lineage is exactly `0001` through `0011`.
Migration `0011` implements the append-only exact-candidate qualification
lineage.

The native qualification facade is
`HeptaEvidenceStore::qualification()`. It exposes:

- `QualificationEvidenceStore::append_receipt`;
- `QualificationEvidenceStore::query_claim`;
- `QualificationEvidenceStore::verify_chain`.

Append authenticates the issuer with the existing AuthBus Ed25519 contract,
binds candidate/tree/role to the signed subject, and advances durable replay
state in the same SQLite transaction as the evidence insert. Verification
preserves claim classes, evidence expiry, correction/revocation lineage and
requires both distinct authenticated principals and distinct signing identities
for required independent roles. Positive verification is revalidated against a
fresh host-supplied current issuer/key/role snapshot; removed, revoked or
key-rotated issuers cannot continue satisfying a supported claim. Corrections and ordinary
revocations are owner-principal/role scoped; only a currently trusted `security`
issuer may cross that boundary for emergency revocation. AuthBus message expiry
controls admission freshness and is not reused as durable evidence expiry.

A named product caller is composed in Agentd when the operator explicitly
provides `--evidence-trust-file`. Agentd advertises `kernel.evidence@1.0`
only when that host is attached and exposes append/query/verify through its
bounded control socket. The trust registry supports multiple issuer principals,
role allowlists, key epochs and current revocation; it is reloaded immediately
before physical evidence append and again before positive chain verification.

## Public symbols and source bindings

- qualification records, authentication, chain verification and query:
  `src/qualification.rs`;
- store open/legacy governance append/query and migration verification:
  `src/store.rs`;
- public evidence records and `EvidenceError`: `src/lib.rs`;
- provider effect storage and verification: `src/provider_effect_store.rs`;
- schema/integrity checks: `src/schema_validation.rs`;
- physical schema: `migrations/*.sql`;
- Agentd product host: `codex-rs/hepta-agentd/src/evidence_host.rs`;
- Agentd multi-issuer trust boundary:
  `codex-rs/hepta-agentd/src/evidence_trust.rs`;
- deterministic migration/qualification/AuthBus recovery snapshot:
  `codex-rs/hepta-evidence/src/recovery_frontier.rs`;
- independent signed startup/restore verifier:
  `codex-rs/hepta-agentd/src/evidence_frontier.rs`.

The pre-existing governance `HeptaEvidenceStore::append_receipt` remains for
backward compatibility. The target qualification operation is the
`QualificationEvidenceStore::append_receipt` method; these two same-named
methods have different typed receivers and cannot be confused by callers.

## Durability and activation

The store uses the repository SQLite durability configuration and validates
quick-check, migration ledger, schema manifest, provider projections/effect
rows, canonical qualification rows and foreign keys on open. A read-only
diagnostic open neither creates nor migrates.

Agentd product composition is source implemented and explicitly configuration
gated. It does not grant selection, promotion or release authority. When the
operator supplies both recovery-frontier files, Agentd verifies an Ed25519-signed
external snapshot of the migration set, qualification high-water/hash frontier,
AuthBus replay frontier and immutable store identity before attaching the
evidence host. A valid older complete SQLite image therefore fails
`recovery_required` against a newer signed frontier. The durable external
CAS/checkpoint service that publishes the latest frontier, independent
acceptance and operator activation remain separate gates.

## Target-only design

The following remain external/target-only rather than current repository
claims:

- a concrete independently retained signed monotonic checkpoint backend;
- distributed replication;
- production operator backup/restore ceremony evidence;
- independent external acceptance of the exact candidate;
- promotion/release authority.

Authenticated evaluator/reviewer roles, independent-principal enforcement and
`IndependentDecisionReceiptV1` storage are no longer target-only source
designs; they are implemented by the qualification facade and Agentd host.

## Known limits and non-claims

A mutex serializes provider-effect boundaries only among clones of one opened
store; separate opens/processes still require database transactions and
provider-owned idempotency. SQLite integrity and migration checks are not an
external anti-rollback oracle.

Agentd's evidence host authenticates evidence writers; it does not authenticate
or manufacture promotion/release decisions. Repository-authored tests cannot
self-issue an **independent** acceptance receipt. An external principal must
review the exact source/merge candidate and sign that decision.

## Verification

Native tests in `src/qualification_tests.rs` cover EVID-01 through EVID-04,
shared-signing-key independence rejection, current trust/key-rotation
invalidation, authenticated replay/idempotency, correction/revocation
non-resurrection, reopen corruption, query/traversal ceilings, concurrent
writers and transactional replay rollback under injected insert failure. The
real Agentd process test `tests/kernel_evidence_product.rs` covers named
product composition, wrong tree/role, replay, expiry, stale/revoked keys,
terminal-observer evidence, current-trust verification and signed
recovery-frontier startup including valid-old-database rejection.

The dedicated qualification workflow runs the evidence package, Agentd product
test, Lane-A truth verifier and documentation/implementation-map gates on both
the exact PR head and deterministic synthetic merge candidate. Workflow output
is execution evidence, not independent acceptance.

## Integration prerequisites

Production activation requires a private multi-issuer evidence trust registry,
a qualified external monotonic frontier backend, backup/restore procedures and
an independently signed exact-candidate acceptance receipt. Writers must use
the Agentd or typed store API, preserve issuer/source provenance and bind
records to the exact candidate and payload digests.

See [RECOVERY_FRONTIER_V1.md](RECOVERY_FRONTIER_V1.md) and
[`qualification/kernel-evidence/TRACEABILITY.md`](../../../qualification/kernel-evidence/TRACEABILITY.md).
