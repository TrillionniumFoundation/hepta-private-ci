# kernel.evidence: implementation design

Parent: `docs/modules/kernel.evidence/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: signed exact-candidate qualification append/query/chain verification and SQLite provider-effect evidence are source implemented; production composition, exact-candidate execution receipts and independent acceptance remain separate gates listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `append_receipt` in [codex-rs/hepta-evidence/src/qualification_store.rs](../../../codex-rs/hepta-evidence/src/qualification_store.rs); `verify_chain` in [codex-rs/hepta-evidence/src/qualification_store.rs](../../../codex-rs/hepta-evidence/src/qualification_store.rs); `query_claim` in [codex-rs/hepta-evidence/src/qualification_store.rs](../../../codex-rs/hepta-evidence/src/qualification_store.rs); `append_provider_effect_intent` and `reconcile_provider_effect_lookup` remain implemented in [codex-rs/hepta-evidence/src/provider_effect_store.rs](../../../codex-rs/hepta-evidence/src/provider_effect_store.rs). The qualification operations are exposed through `HeptaEvidenceStore::qualification()` so the existing governance `append_receipt` API is not broken.
- **State and recovery:** migration `0011_qualification_evidence.sql` adds one append-only qualification evidence domain with immutable triggers, exact candidate commit/tree binding, registered protocol binding, authenticated issuer principal/controller/key-chain binding, Ed25519 signature verification, predecessor/revocation/supersession links and bounded traversal/query limits. Store reopen verifies canonical JSON, record digests, embedded signatures, indexed projections and link integrity. Provider-effect uncertainty remains distinct from provider acknowledgement.
- **Source tests:** [codex-rs/hepta-evidence/src/qualification_store_tests.rs](../../../codex-rs/hepta-evidence/src/qualification_store_tests.rs) implements EVID-01 through EVID-04 plus reopen and idempotency-conflict coverage; provider-effect tests remain in [provider_effect_tests.rs](../../../codex-rs/hepta-evidence/src/provider_effect_tests.rs) and [provider_claim_tests.rs](../../../codex-rs/hepta-evidence/src/provider_claim_tests.rs). Test source is not an execution receipt.
- **Implementation and operating references:** [STORE_V1.md](../../../docs/lane-a-foundation/kernel.evidence/STORE_V1.md), [ANTI_ROLLBACK_V1.md](../../../docs/lane-a-foundation/kernel.evidence/ANTI_ROLLBACK_V1.md), and [TRACEABILITY.md](../../../docs/lane-a-foundation/kernel.evidence/TRACEABILITY.md).
- **Remaining work / non-claims:** the repository now contains the target source API and independent-decision projection, but it does not self-issue independent acceptance. An authenticated production caller must execute the façade for an exact candidate, CI must publish current exact-head and synthetic-merge receipts, and an independently controlled signer/operator must produce the external acceptance receipt. The external monotonic checkpoint anchor and managed retention/restore service are operational dependencies, not locally fabricated evidence.
