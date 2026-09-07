# kernel.evidence: implementation design

Parent: `docs/modules/kernel.evidence/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-evidence`.
Packages: `P0.9-EXTERNAL-GATES`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
