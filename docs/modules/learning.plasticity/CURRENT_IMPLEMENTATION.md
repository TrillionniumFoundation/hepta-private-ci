# learning.plasticity current implementation boundary

This document is the current-state companion to `TECHNICAL.md`. `TECHNICAL.md`
contains both target architecture and stable requirements; this file states what is
implemented now. A claim listed as **Implemented** is a source capability, not an
activation, acceptance, promotion or release claim.

## Status matrix

| Capability | Status | Native / composed surface |
| --- | --- | --- |
| Parameter V2 canonical proposal envelope | **Implemented** | `codex-rs/hepta-plasticity/src/parameter_v2.rs` |
| Deterministic generator-relative candidate completeness | **Implemented** | `generate_parameter_candidates_v3` in `generator_v3.rs` |
| Content-derived update candidate identity | **Implemented** | `generator_v3.rs` |
| Per-layer/global parameter trust regions | **Implemented** | V2 verifier and V3 generator |
| Durable append-only proposal registry | **Implemented** | `DurableProposalRegistry` |
| Production-path anchored reopen | **Implemented seam** | `AnchoredPlasticityWriterV1` in `codex-rs/hepta-intelligence` |
| Signed generator authentication | **Implemented composition** | `propose_authenticated_parameter_plasticity_v1` |
| Signed current artifact/evidence-frontier witness | **Implemented composition** | `PlasticityAdmissionEvidenceV1` |
| Cryptographically independent evaluator admission | **Implemented composition** | existing `LearningEvidenceVerifierV1` + signed evaluation path |
| Evaluation coverage for every generated update | **Implemented composition** | product adapter rejects missing/duplicate/unexpected evaluations |
| Product-workspace proposal writer | **Implemented composition** | `codex-rs/hepta-intelligence/src/plasticity_product.rs` |
| Typed topology proposal generation | **Implemented, proposal-only** | `propose_topology_v2` in `topology_v2.rs` |
| Topology application / writer handoff execution | **Target / not implemented** | intentionally no apply API |
| Weight training / installation | **Target outside this proposal engine** | no authority granted |
| Selection / activation / promotion / release | **External gate / not implemented** | explicitly denied |
| Host deployment qualification and canary | **External evidence required** | no source-only claim |

## Parameter generator semantics

V2 remains byte/digest compatible and still accepts caller-supplied candidate sets for
compatibility. New product composition does not use that as its trust boundary. It
passes a `ParameterGeneratorProfileV3` to the deterministic V3 generator and verifies
that the submitted generated set can be reproduced exactly.

The V3 search is bounded to at most 31 update scales, 32 total candidates, 4,096
signal/scale evaluations and 256 norm layers. For every declared scale, it computes
`eligibility * modulator * learning_rate * scale` using checked Q32 arithmetic, clamps
to explicit parameter bounds, removes zero deltas, applies the same 0.5% per-layer and
0.25% global relative-L2 trust regions, then emits every unique admissible result plus
one explicit no-change candidate. Update candidate IDs are derived from canonical
candidate content. Therefore an evaluator's candidate ID binds the exact generated
parameter change rather than an arbitrary caller label.

This proves completeness only relative to the declared V3 generator profile. It does
not claim that the profile spans every useful update in the model's full search space.

## Authenticated product composition

`codex-rs/hepta-intelligence/src/plasticity_product.rs` is the product-workspace
consumer. It requires, before any durable proposal append:

1. exact regeneration of the V3 candidate set;
2. a `Generator` signature over the generator digest under host-owned current trust;
3. an `Observer` signature over the selected artifact, artifact-registry binding/head,
   qualification-evidence head, window, generations, dataset/update/modulator/
   eligibility digests and generator digest;
4. signed independent evaluation for every generated update candidate;
5. one consistent authenticated evaluator identity across those evaluations;
6. exact artifact/window/generation lineage and exact durable predecessor.

The existing learning-evidence verifier enforces signer trust, signature validity,
validity window, revocation, role assignment and generator/evaluator controller
separation. The product adapter derives proposer/evaluator IDs from authenticated
principals instead of trusting caller-supplied role strings.

## Rollback protection

The raw proposal crate retains `DurableProposalRegistry::open` for isolated bootstrap
and compatibility. It is not accepted by the product composition path.
`AnchoredPlasticityWriterV1::bootstrap_new` accepts only a zero-length newly enrolled
file. Any reopen of acknowledged history must use `reopen_anchored` with a host-retained
`DurableRegistryAnchorV1`. The host MUST persist the returned current anchor in an
independent rollback domain after each successful append and MUST issue a nonzero,
monotonic writer fence. A registry file and its anchor stored in the same rollback
domain do not satisfy this requirement.

## Topology boundary

Topology V2 creates typed Add/Remove/Replace/Split/Merge/Rewire/Retire proposals. Every
change carries migration, rollback, writer-handoff and evidence digests and is emitted
as one bounded structural update candidate plus the no-change candidate. There is no
API that applies a topology change. Runtime graph mutation remains gated on an
independently accepted migration/writer-handoff implementation and host canary.

## Remaining external gates

Source implementation does not establish independent semantic review, target-host
qualification, operator acceptance, canary promotion, activation or release. Those
states must stay false until their own evidence exists. CI receipts must refer to the
exact source/merge candidate; source test names are not pass receipts.
