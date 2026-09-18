# kernel.evidence: implementation design

Parent: `docs/modules/kernel.evidence/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: target qualification append/query/chain verification, authenticated issuer roles,
independent-decision projection, durable revocation and logical anti-rollback
checkpoint are implemented and composed through the existing governance product
host. Exact-candidate execution evidence and independent acceptance remain
separate as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-evidence`.
Packages: `P0.9-EXTERNAL-GATES`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`append_receipt(envelope, authenticated_issuer) -> EvidenceId | EvidenceError`; `verify_chain(candidate, required_roles, now) -> EvidenceDisposition`; `query_claim(candidate, claim_class) -> bounded evidence references`. Verification checks exact candidate/tree, schema, evidence digests, issuer role, signature/key chain, expiry and revocation; arbitrary different issuer strings do not establish independence.

## 3. State records and transaction design

`qualification_evidence` is append-only: receipt ID, candidate/source/tree, evidence class, issuer principal/key reference, payload digest, predecessor, observation time, expiry and revocation links. Large logs are content-addressed bounded external evidence assets; the store contains references and integrity metadata. Corrections supersede rather than rewrite prior receipts.

## 4. Deterministic algorithm and scheduling

Authenticate the producer at the host boundary; canonicalize the envelope; validate signatures and role separation; append durably; publish a rebuildable index. Claim resolution returns missing, conflicting, expired or supported evidence per class. A green fixture cannot be upgraded to hardware, production caller, future efficacy or independent acceptance evidence.

## 5. Capacity and performance profile

Pilot receipt <= 256 KiB, referenced assets <= 64 per receipt, chain traversal <= 256 edges and query result <= 512 references. Reject cycles and traversal exhaustion rather than treating an incomplete chain as valid.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- EVID-01: one principal with two display names cannot satisfy generator/evaluator independence.
- EVID-02: evidence for a different tree or expired candidate is unavailable.
- EVID-03: corrupted payload and broken predecessor fail integrity checks after reopen.
- EVID-04: fixture/hardware/effect/longitudinal claim-class substitution is rejected.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

The evaluator, reviewer, selector and loader retain separately authorized identities. Evidence storage is not permission to select or release. Rollback keeps append-only history and the current revocation frontier; it does not resurrect invalid evidence.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `append_receipt` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `verify_chain` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `query_claim` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `append_independent_decision_receipt` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `append_issuer_key_revocation` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `capture_external_checkpoint` in [codex-rs/hepta-evidence/src/checkpoint.rs](../../../codex-rs/hepta-evidence/src/checkpoint.rs); `verify_external_checkpoint` in [codex-rs/hepta-evidence/src/checkpoint.rs](../../../codex-rs/hepta-evidence/src/checkpoint.rs). Target qualification persistence, verification, revocation and logical checkpoint boundaries are implemented.
- **Target contract entrypoints:** `HeptaEvidenceStore::append_receipt`,
  `HeptaEvidenceStore::verify_chain` and `HeptaEvidenceStore::query_claim` in
  [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs).
  The former governance receipt append was renamed
  `append_governance_receipt` so the two meanings cannot be confused.
- **Independent verification records:** `append_independent_decision_receipt`
  persists the registered `IndependentDecisionReceiptV1` projection only when
  candidate, registered role, principal, signing identity, evidence-set digest,
  expiry and the detached signed envelope agree. Same-principal or same-key
  identities cannot satisfy two required independent roles.
- **Issuer authentication and revocation:** host-created
  `AuthenticatedEvidenceIssuerV1` values require a certificate signed by a
  pinned root and a current external revocation head. Durable
  `append_issuer_key_revocation` facts invalidate subsequent chain
  verification without rewriting receipts.
- **State and recovery:** migration `0011_qualification_evidence.sql` stores
  canonical signed envelopes, predecessor/revocation lineage and independent
  decision projections append-only. Store reopen revalidates canonical bytes,
  projections and Ed25519 signatures. Existing provider-effect uncertainty
  remains separate from terminal provider acknowledgement.
- **Anti-rollback:** `capture_external_checkpoint`,
  `verify_external_checkpoint` and `open_with_external_checkpoint` in
  [codex-rs/hepta-evidence/src/checkpoint.rs](../../../codex-rs/hepta-evidence/src/checkpoint.rs)
  bind the migration prefix and complete qualification-evidence prefix. The
  checkpoint must be retained outside the SQLite failure domain.
- **Product composition:** the existing
  [codex-hepta-governance GovernanceState](../../../codex-rs/ext/hepta-governance/src/state.rs)
  exposes the qualification writer, query verifier, terminal-observer path and
  checkpoint boundary. Issuer authentication requires a host-pinned
  `EvidenceIssuerAuthorityV1` installed through
  `install_with_mode_and_qualification_authority`; an incoming request cannot
  choose a trust root. The default product installation intentionally has no
  qualification authority until the external trust-root ceremony supplies it.
- **Source tests:** [qualification_tests.rs](../../../codex-rs/hepta-evidence/src/qualification_tests.rs)
  implements EVID-01..04 plus revocation, independent-decision, corruption and
  rollback-checkpoint cases; [qualification_product_tests.rs](../../../codex-rs/ext/hepta-governance/src/qualification_product_tests.rs)
  proves the named product host composition. Test sources are not execution
  receipts.
- **Execution evidence:** Lane A CI emits exact-source and deterministic
  synthetic-merge source/native receipts. See
  [kernel.evidence traceability](../../kernel-evidence/TRACEABILITY.md) for the
  requirement-to-receipt mapping.
- **Remaining external gates:** an independently controlled actor must still
  supply a current signed independent decision for the exact candidate.
  Operator acceptance, physical target qualification, trust-root ceremony,
  promotion and release remain external. The provider-effect dispatch facade
  remains qualification-only and is not promoted into a production effect
  authority by this module.
