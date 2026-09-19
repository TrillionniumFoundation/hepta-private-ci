# kernel.evidence: implementation design

Parent: `docs/modules/kernel.evidence/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: authenticated exact-candidate qualification storage/query/verification and
an Agentd named product caller are source implemented. Independent external
acceptance, external monotonic recovery frontier activation, operator acceptance,
promotion and release remain separate gates. Common requirements:
`../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `codex-rs/hepta-evidence`.
Product composition: `codex-rs/hepta-agentd`.
Packages: `P0.9-EXTERNAL-GATES`.

The native target contract is implemented through
`HeptaEvidenceStore::qualification() -> QualificationEvidenceStore`. This
separate typed facade preserves the pre-existing governance
`HeptaEvidenceStore::append_receipt(GovernanceReceipt)` without overloading its
semantics.

## 2. Public operations and contract details

Native operations are:

- `QualificationEvidenceStore::append_receipt(authenticated_issuer, signed_message, envelope) -> EvidenceId | EvidenceError`;
- `QualificationEvidenceStore::verify_chain(VerifyChainRequestV1) -> EvidenceDispositionV1`;
- `QualificationEvidenceStore::query_claim(candidate, claim_class) -> bounded EvidenceReferenceV1[]`.

The Agentd product path exposes the same semantic operations through bounded
control methods and reloads the owner-controlled multi-issuer trust registry
immediately before physical append.

Append verifies the exact canonical envelope signature, issuer/key epoch,
candidate/tree/role subject, replay sequence, expiry, role allowlist and
correction/revocation lineage. Durable replay advancement and the evidence
insert share one `BEGIN IMMEDIATE` transaction.

Verification checks exact candidate/tree and claim class, canonical envelope and
payload digests, expiry, correction/revocation lineage and required role
coverage. Multiple required independent roles must be satisfiable by distinct
authenticated principals; different display names or roles on one principal do
not establish independence.

## 3. State records and transaction design

Migration `0011_qualification_evidence.sql` owns
`qualification_evidence`. It is append-only and stores receipt ID,
candidate/source/tree, claim class, receipt kind, issuer role/principal/key epoch
and signing-key digest, AuthBus message/sequence/expiry, exact payload and
envelope digests, predecessor/target lineage, observation/expiry and bounded
asset references.

Corrections and revocations append lineage instead of rewriting prior receipts.
Same identity + same authenticated semantics is idempotent. Reusing an evidence
identity with changed semantics conflicts.

`IndependentDecisionReceiptV1` is stored as an
`independent_decision` qualification receipt and binds candidate, decision
role, authenticated principal, signing identity digest, evidence-set digest,
decision, conditions and expiry.

## 4. Deterministic algorithm and scheduling

1. Canonicalize and bound the complete envelope.
2. Resolve the current issuer registration/role at the host boundary.
3. Authenticate the AuthBus signature over that exact envelope.
4. Bind subject to exact candidate commit/tree and role.
5. In one `BEGIN IMMEDIATE` transaction, verify idempotency/lineage, advance
   replay high-water and insert the immutable receipt.
6. Query by exact candidate/tree + claim class only.
7. Reconstruct canonical rows on read/open and fail closed on projection/digest
   drift.
8. Resolve active evidence after corrections, revocations and expiry.
9. Satisfy multiple independent roles only with distinct authenticated
   principals.

A fixture cannot be upgraded to hardware, provider effect, longitudinal,
production-caller or independent-acceptance evidence.

## 5. Capacity and performance profile

Native/store ceilings:

- receipt canonical envelope <= 256 KiB;
- referenced assets <= 64 per receipt;
- predecessor traversal <= 256 edges;
- query result <= 512 references;
- required independent roles <= 32.

The current Agentd control transport imposes the stricter product-wire ceiling
of 48 KiB for one envelope/result so it remains below the existing bounded
control frame. Larger evidence assets remain content-addressed references.

These are enforced source bounds, not throughput measurements. Production
capacity evidence remains required before activation.

## 6. Concrete verification cases

- **EVID-01:** one authenticated principal cannot satisfy
  generator/evaluator or other multi-role independence; distinct principals can.
- **EVID-02:** evidence for a different tree is missing and expired evidence is
  expired/unavailable.
- **EVID-03:** canonical payload/projection corruption and broken predecessor
  lineage fail closed on reopen.
- **EVID-04:** fixture/hardware and other claim classes are not substitutable.
- Exact signed retry is idempotent; payload drift conflicts.
- Correction/revocation history survives reopen without resurrection.
- Real Agentd product test exercises append -> query -> verify, two independent
  decision principals, terminal-observer evidence and revocation reload.

Source test identities are not independent acceptance receipts. Exact-head and
synthetic-merge execution receipts are produced by the dedicated workflow.

## 7. Integration, rollback and capability ceiling

Agentd is the named product caller/writer host for qualification evidence when
explicitly configured with `--evidence-trust-file`. It authenticates evidence
writers; it does **not** gain selection, merge, promotion or release authority.

The evaluator, reviewer, terminal observer, selector and loader retain separate
identities. Repository-authored code/tests cannot self-issue an independent
external acceptance. The exact candidate must be reviewed and signed by an
external authorized principal.

Local SQLite verification is not an external anti-rollback oracle. Production
backup/restore must satisfy
`docs/lane-a-foundation/kernel.evidence/RECOVERY_FRONTIER_V1.md`; a concrete
independently retained frontier backend remains an activation prerequisite.

## 8. Current native implementation

- **Qualification entrypoints:** `append_receipt`, `query_claim` and
  `verify_chain` in
  [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs).
- **Durable state:** migration
  [0011_qualification_evidence.sql](../../../codex-rs/hepta-evidence/migrations/0011_qualification_evidence.sql)
  plus canonical startup row/lineage verification.
- **Product caller/writer:** Agentd
  [evidence_host.rs](../../../codex-rs/hepta-agentd/src/evidence_host.rs) with
  [evidence_trust.rs](../../../codex-rs/hepta-agentd/src/evidence_trust.rs) and
  control/client operations.
- **Terminal observer boundary:** `terminal_observer` is a separately
  registered evidence role; the real Agentd product test persists a
  provider-effect terminal observation from a distinct principal.
- **Provider-effect journal:** existing intent/ACK/uncertainty reconciliation in
  [provider_effect_store.rs](../../../codex-rs/hepta-evidence/src/provider_effect_store.rs)
  remains separate from qualification acceptance.
- **Source tests:**
  [qualification_tests.rs](../../../codex-rs/hepta-evidence/src/qualification_tests.rs),
  [provider_effect_tests.rs](../../../codex-rs/hepta-evidence/src/provider_effect_tests.rs),
  and
  [kernel_evidence_product.rs](../../../codex-rs/hepta-agentd/tests/kernel_evidence_product.rs).
- **Operating references:**
  [STORE_V1.md](../../../docs/lane-a-foundation/kernel.evidence/STORE_V1.md) and
  [RECOVERY_FRONTIER_V1.md](../../../docs/lane-a-foundation/kernel.evidence/RECOVERY_FRONTIER_V1.md).
- **Remaining external gates:** exact-candidate independent acceptance,
  concrete external monotonic frontier backend/restore ceremony, operator
  acceptance, canary, promotion and release. None may be inferred from source
  implementation or CI success.
