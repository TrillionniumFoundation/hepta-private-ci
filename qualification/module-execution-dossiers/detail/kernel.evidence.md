# kernel.evidence: implementation design

Parent: `docs/modules/kernel.evidence/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: authenticated exact-candidate qualification receipt storage, bounded
query/chain verification, typed `IndependentDecisionReceiptV1`, external
checkpoint rollback verification and a checkpoint-guarded writer are
source-implemented. Independent exact-candidate acceptance and target-host
operator acceptance remain external gates. Common requirements:
`../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `codex-rs/hepta-evidence`.
Packages: `P0.9-EXTERNAL-GATES`.

The implementation extends the existing `HeptaEvidenceStore`; it does not
create another authority or execution spine. Qualification evidence shares the
same migration ledger and store-open integrity boundary as governance,
provider-effect and AuthBus evidence.

## 2. Public operations and contract details

Native target-aligned operations are exposed through
`HeptaEvidenceStore::qualification()`:

- `append_receipt(envelope, authenticated_issuer) -> AppendDisposition | EvidenceError`;
- `verify_chain(candidate, required_roles, now) -> EvidenceDisposition`;
- `query_claim(candidate, claim_class) -> bounded evidence references`.

`provision_trust_policy` pins one immutable Ed25519 trust policy into the owner SQLite lineage before the first qualification receipt. `EvidenceTrustPolicy::authenticate` converts an issuer proof into the non-constructible authenticated issuer consumed by `append_receipt`; append then re-checks that authenticated issuer against the store-pinned policy. Authentication binds the canonical envelope, registered principal, verifying key, role set, credential validity and exact trust-policy digest. Arbitrary issuer strings or caller-supplied replacement policies cannot satisfy this contract.

`prepare_independent_decision` emits the typed
`IndependentDecisionReceiptV1` and exact signing envelope without signing on
behalf of the reviewer. `append_prepared_independent_decision` verifies the
external reviewer signature and commits the authoritative evidence row plus
typed projection in one transaction.

## 3. State records and transaction design

`qualification_evidence` is append-only and contains receipt identity,
candidate/source/tree, evidence class, issuer role/principal/key, trust-policy
digest, payload digest, predecessor, observation/expiry, revocation links,
canonical envelope/issuer material, record digest and the previous/current
global chain digests.

`independent_decision_receipts` is an immutable typed projection owned by
`kernel.evidence`. Large evidence assets remain content-addressed references;
the receipt stores bounded references plus integrity metadata rather than
unbounded logs.

Every qualification append uses `BEGIN IMMEDIATE`, validates any predecessor
or revocation target before publication, derives the new global chain digest,
and commits atomically. Corrections supersede a predecessor; they do not
rewrite it. Security-authority revocation appends a permanent fact.

## 4. Deterministic algorithm and scheduling

1. Validate exact candidate id/source commit/source tree and all encoded bounds.
2. Authenticate the issuer over canonical envelope bytes against a reviewed
   trust policy.
3. Validate role membership, credential interval and signing identity.
4. Validate predecessor/revocation lineage inside the write transaction.
5. Append the immutable record and advance the hash-chain frontier.
6. Query exact candidate/claim projections with a 512-reference bound.
7. Resolve expiry, revocation and supersession without deleting history.
8. For `verify_chain`, require each requested role and reject reuse of one
   principal or signing identity across multiple required independent roles.

A green fixture cannot be upgraded to hardware, production caller, future
efficacy or independent acceptance evidence.

## 5. Capacity and performance profile

Enforced native qualification bounds:

- canonical envelope + authenticated issuer <= 256 KiB;
- external evidence asset references <= 64 per receipt;
- predecessor traversal <= 256 edges;
- query result <= 512 references;
- required independent roles <= 32;
- issuer role set <= 32.

Traversal exhaustion, cycles, missing predecessors, oversized inputs and result
overflow fail closed.

## 6. Concrete verification cases

- EVID-01: one principal/signing identity with two roles cannot satisfy
  generator/evaluator independence — covered by
  `one_principal_cannot_satisfy_two_independent_roles`.
- EVID-02: evidence for a different tree is unavailable and expired evidence is
  non-active — covered by `exact_candidate_tree_and_expiry_are_enforced`.
- EVID-03: reopen re-verifies canonical record/signature/hash-chain integrity —
  covered by
  `qualification_receipt_is_authenticated_idempotent_queryable_and_reopen_safe`.
- EVID-04: security-authority revocation makes prior evidence non-active without
  deletion — covered by
  `security_authority_revocation_is_immediate_and_persistent`.
- EVID-05: a typed independent decision is signed, appended and projected
  atomically — covered by
  `independent_decision_is_typed_signed_and_projected_atomically`.
- EVID-06: external checkpoint verification rejects replacement/backward
  frontier — covered by
  `external_checkpoint_detects_database_replacement_and_backward_frontier`.

These source test identities become execution evidence only when the exact
candidate Lane A job records them after native test/clippy completion.

## 7. Integration, rollback and capability ceiling

The named `hepta-evidence-writer` binary is the authenticated product writer.
Every non-bootstrap write requires a prior independently retained checkpoint;
after commit it emits a successor checkpoint. Independent review preparation
emits exact bytes for an external reviewer to sign and never owns the reviewer's
private key.

An external checkpoint binds immutable store instance identity, pinned trust-policy digest, receipt count, sequence and chain digest. It detects replacement, rollback and divergent
history when retained separately from SQLite. The repository does not claim
that a checkpoint copied/restored beside the database is independent.

The evaluator, reviewer, selector and loader retain separately authorized
identities. Evidence storage is not permission to select or release. Immediate
revocation remains effective across frozen snapshots. Preserve every external
gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `append_receipt` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `verify_chain` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `query_claim` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `append_prepared_independent_decision` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `verify_external_checkpoint` in [codex-rs/hepta-evidence/src/qualification.rs](../../../codex-rs/hepta-evidence/src/qualification.rs); `append_provider_effect_intent` in [codex-rs/hepta-evidence/src/provider_effect_store.rs](../../../codex-rs/hepta-evidence/src/provider_effect_store.rs); `reconcile_provider_effect_lookup` in [codex-rs/hepta-evidence/src/provider_effect_store.rs](../../../codex-rs/hepta-evidence/src/provider_effect_store.rs).
- **Product caller/writer:** [codex-rs/hepta-evidence/src/bin/hepta-evidence-writer.rs](../../../codex-rs/hepta-evidence/src/bin/hepta-evidence-writer.rs) is the named checkpoint-guarded writer and independent-review ceremony adapter.
- **State and recovery:** migration `0011` owns the qualification hash chain,
  immutable store identity and independent-decision projection. Reopen
  re-verifies canonical bytes, signatures, projections, global chain and
  foreign keys.
- **Source tests:** [codex-rs/hepta-evidence/src/qualification_tests.rs](../../../codex-rs/hepta-evidence/src/qualification_tests.rs), [codex-rs/hepta-evidence/src/provider_effect_tests.rs](../../../codex-rs/hepta-evidence/src/provider_effect_tests.rs), [codex-rs/hepta-evidence/src/provider_claim_tests.rs](../../../codex-rs/hepta-evidence/src/provider_claim_tests.rs).
- **Exact-candidate execution evidence:** Lane A emits source-head and
  deterministic synthetic-merge receipts plus
  `kernel-evidence-source-head.json` /
  `kernel-evidence-merge-candidate.json` after native tests.
- **Remaining external work:** a distinct reviewer must sign the current exact
  candidate/evidence set; a target operator must independently retain
  checkpoint generations and execute target-host qualification. Operator
  acceptance, canary, promotion and release remain separate governed states.
