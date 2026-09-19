# kernel.evidence independent acceptance ceremony

This ceremony converts exact-candidate execution evidence into an externally
reviewed `IndependentDecisionReceiptV1`. It intentionally cannot be completed
by the source-producing workflow or by the same principal that generated the
candidate.

## Inputs

The reviewer receives, without mutation:

- exact PR/source commit and tree;
- deterministic synthetic-merge commit/tree and its two parents;
- exact-head and merge execution records from the dedicated
  `kernel-evidence-qualification-*` workflow artifacts;
- canonical registry/document digests used by the candidate;
- the requirement traceability matrix;
- source/test patches and failure logs;
- any applicable external recovery/operator evidence.

The reviewer must independently recompute candidate/tree identity and the
evidence-set digest before signing.

## Independence rules

- A repository source generator cannot satisfy the independent reviewer role
  merely by using another display name.
- Each required decision role is bound to an authenticated principal and key
  epoch. When multiple roles are required by a qualification profile, the
  verifier requires distinct principals.
- The review signing key is not stored in the repository, CI secret set or
  local evidence database.
- Repository CI may verify an externally supplied receipt, but it may not mint
  the independent acceptance it is verifying.

## Receipt

The reviewer creates `IndependentDecisionReceiptV1` with:

- `decisionId`;
- exact `candidateId` matching the evidence envelope;
- the applicable qualification role;
- authenticated `principalId`;
- digest of the actual Ed25519 signing identity;
- digest of the exact evidence references reviewed;
- `accept`, `reject`, or `abstain`;
- bounded conditions;
- explicit expiry.

The receipt is wrapped in a `QualificationEvidenceEnvelopeV1` whose
`candidate.source_commit` and `candidate.source_tree` bind the exact object.
The reviewer signs the canonical envelope using the AuthBus qualification
scope/subject produced by `kernel_evidence_claims` or the equivalent native
helper.

## Admission

A production/qualification Agentd with an owner-installed evidence trust
registry admits the signed receipt through `KernelEvidenceAppend`.
`kernel.evidence` verifies current issuer/key/role registration, signature,
candidate/tree/role subject, replay sequence, expiry and decision identity in
the same durable append transaction.

An accepted storage append means only that the independent decision record is
authentic and durably bound. The decision itself may be reject/abstain and does
not grant merge, promotion or release authority.

## Current candidate status

For PR #936, the repository provides the executable receipt path and exact-head
workflow. **No independent external acceptance is claimed by this document.**
The implementation map must keep `independentAcceptance=false` until an
authorized external reviewer supplies a valid receipt for the final exact
candidate and the required profile roles are satisfied.
