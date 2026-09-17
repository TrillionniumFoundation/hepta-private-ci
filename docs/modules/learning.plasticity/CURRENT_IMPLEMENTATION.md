# learning.plasticity current implementation

Status: **source implementation overlay for PR #624**  
Base: `main@d7af096f28fa9989388939efa0e6600b52a43952`  
Source-code overlay: `0941c20155b0f51af273e78211f237f66e61adbb`  

This document is the current-source companion to `TECHNICAL.md`. The technical guide remains the full target/development envelope; this file states what is implemented in the source overlay, what remains target-only, and what the host must provide. Nothing here claims product execution, operator acceptance, activation, promotion, or release.

## Status legend

- **[Implemented]** — native source exists in this PR and is reachable from a non-test product crate when stated.
- **[Target]** — specified design or later work package; no completion claim.
- **[Host responsibility]** — must be supplied by the deployment/trust domain and is not synthesized by this crate.
- **[External evidence gate]** — requires execution/acceptance evidence outside source inspection.

## 1. Parameter candidate generation

**[Implemented]** `generate_parameter_candidates_v3` in `codex-rs/hepta-plasticity/src/governed_v3.rs` is an in-crate generator. The caller supplies bounded parameter opportunities and a generation policy, not a prebuilt candidate delta set.

The local deterministic update is:

```text
local_delta = eligibility * projected_modulator * learning_rate
candidate_delta = scale_ppm(local_delta)
```

The generator then applies per-parameter bounds and a conservative deterministic projection into the existing V2 per-layer/global trust region. Exactly one no-change candidate is generated. Update candidates are generated from the configured scale profile. Candidate and canonical-order digests are computed by the module.

**[Implemented]** The generated set is represented by `CandidateSetCompletenessReceiptV1` with `complete_for_generator=true` and `omitted_count_bound=0`. A generator signature is verified over the completeness digest before admission.

**[Target]** Richer grammars, learned candidate families, sparse/group update policies, or alternate projection algorithms may be added only behind new generator-code/grammar digests. They must not silently change V3 semantics.

## 2. Evidence and freshness

**[Implemented]** The governed path no longer treats every evidence field as merely a non-zero digest:

1. The selected artifact is looked up in `learning.artifacts::ArtifactRegistry` and must have matching content digest, objective, generation, and eligible lineage.
2. `DatasetSnapshotReceiptV3` is self-verified at the supplied current time and must match the proposal objective and dataset digest.
3. The exact artifact/window/dataset/update-rule/modulator/eligibility/norm/opportunity binding is signed by an authenticated `Observer` role and verified by `LearningEvidenceVerifierV1`.
4. Every parameter opportunity evidence digest is included in that signed binding.
5. Generator completeness is independently signed by an authenticated `Generator` role.
6. The final V2 `evaluation_digest` is replaced by a governed admission digest binding artifact-registry head, source authentication, generator authentication, completeness, evaluation evidence, and trust snapshot.

**[Host responsibility]** The Observer must verify the underlying source records before signing the binding. Signature verification proves attribution, scope, freshness window, authority epoch, revocation state, and exact payload binding; it does not magically prove semantics that the authorized Observer failed to inspect.

**[Target]** A deployment may additionally retain/query source evidence through `kernel.evidence`, but `hepta-evidence` is not made a native crate dependency merely to turn opaque learning evidence into governance-receipt semantics. The implemented trust primitive for learning facts is the existing `learning-ledger` signed-evidence contract.

## 3. Independent evaluator trust boundary

**[Implemented]** Governed V3 does not derive evaluator independence from `proposer_id != evaluator_id`.

`propose_governed_v3` consumes `SignedEvaluationEvidenceV1` through `decide_with_signed_evidence_v2`. The existing trust verifier checks registered keys, trust digest, scope/objective, authority epoch, validity interval, revocation, signature, and role. Signed role separation rejects generator/evaluator identity, credential-chain/signing-key, or controller collapse. The V2 `evaluator_id` is populated from the authenticated evaluation principal rather than a free caller label.

The structural inequality check remains in raw V2 as a compatibility invariant, but it is not the production trust boundary.

## 4. Product composition and durable writer

**[Implemented]** `codex-rs/hepta-intelligence/src/plasticity_host.rs` is a non-test product caller. `codex-hepta-plasticity` and `codex-hepta-learning-artifacts` are normal dependencies of `codex-hepta-intelligence`, not dev-only dependencies.

`propose_and_persist_plasticity_v3` performs:

```text
authenticated artifacts + dataset + signed source evidence
                  |
                  v
       governed in-crate candidate generation
                  |
                  v
        signed generator completeness
                  |
                  v
        signed independent evaluation
                  |
                  v
        ParameterProposalV2 (deny-all)
                  |
                  v
       ProductionProposalRegistry append
                  |
                  v
       next external rollback anchor
```

The product caller does not install weights, choose an update candidate, activate a snapshot, promote, or release.

**[External evidence gate]** Source composition is not the same as product execution proof. Target-host execution receipts, operator acceptance, and canary evidence remain required before the published implementation map may claim production implementation.

## 5. Topology plasticity

**[Implemented]** `TopologyProposalV2` and `propose_topology_v2` provide a new-write structural proposal path. The proposal binds:

- exact baseline/candidate generation successor,
- predecessor topology digest,
- add/remove/replace operation,
- typed nodes/edges digest,
- candidate topology digest,
- compatibility plan,
- resource delta,
- security review,
- lesion plan,
- rollback plan,
- evidence digest,
- deny-all authority and `RequiresIndependentAcceptance` status.

**[Target]** Topology V2 is proposal construction/verification only. It is not yet wired into a durable topology registry, authenticated governed topology admission, PLS-3 structural canary execution, or runtime topology application. Those remain explicit later work; this PR therefore does not claim topology activation closure.

## 6. Rollback protection

**[Implemented]** `ProductionProposalRegistry` makes the external-anchor posture executable:

- `BootstrapEmpty` succeeds only for a physically empty newly enrolled file.
- every acknowledged reopen must use `ProductionAnchorStateV1::Acknowledged(anchor)`, which delegates to `DurableProposalRegistry::open_anchored`.
- after an append, the product caller returns the exact next anchor and verifies that it matches the durable append receipt.

**[Host responsibility — MUST]** The returned anchor MUST be durably retained outside the proposal-registry file rollback domain before the append is treated as externally acknowledged. Loss of the separately trusted anchor cannot be repaired by the registry file itself.

**[Host responsibility — MUST]** Fence issuance, path enrollment, directory durability, permissions, backup, anchor retention, anchor revocation, and disaster-recovery ownership remain host responsibilities.

## 7. Native dependency truth

**[Implemented]** The plasticity crate now has direct native dependencies on:

- `codex-hepta-intelligence-eval` — signed independent evaluation;
- `codex-hepta-learning-artifacts` — current artifact/lineage lookup;
- `codex-hepta-learning-ledger` — dataset receipt, generator completeness, signed learning evidence and role separation;
- `codex-hepta-types` — canonical shared primitives.

This replaces the previous mismatch where the technical architecture named evidence/evaluation/artifact components while the native crate depended only on `codex-hepta-types`.

**[Target/host adapter]** `kernel.evidence` remains an optional host evidence-retention/query integration, not the native learning-signature verifier used by this source path.

## 8. Current vs target architecture

**[Implemented/current]** Governed parameter V3 generation/admission, raw parameter V2 verification, parameter durable registry, production external-anchor gate, non-test product caller/writer, and topology V2 proposal construction.

**[Target]** Durable governed topology storage, topology product caller, structural canary lifecycle, runtime application/rollback adapters, deployment-specific observability sinks, and activation/promotion/release processes.

**[Host responsibility]** Trust enrollment, key/controller separation, source evidence inspection, external anchor retention, operator procedures, and target-host telemetry backend.

`TECHNICAL.md` should be read as the complete development/target guide; when a statement there conflicts with this current-source status split, this companion controls the source-completion interpretation for PR #624.

## 9. CI and qualification truth

**[External evidence gate]** A source file or test identity is not an execution receipt. PR #624 must be evaluated at its exact head. Repo-wide failures must not be attributed to `learning.plasticity` without a failing job/test that establishes that relationship.

Required branch checks for this change include at minimum:

```text
cargo fmt --check
cargo test -p codex-hepta-plasticity
cargo test -p codex-hepta-intelligence
cargo clippy -p codex-hepta-plasticity --all-targets -- -D warnings
cargo clippy -p codex-hepta-intelligence --all-targets -- -D warnings
repository integrity / implementation-map verification
Lane F qualification affected by the product dependency change
```

Do not mark this document as product-qualified merely because these invocations are listed here.

## 10. Operations and observability

### 10.1 Required metric/event surface

**[Host responsibility]** A production host must emit at least the following measurements from the product adapter boundary:

- governed proposal attempts, successes, and rejection counts by stable rejection class;
- generated candidate count and total generated parameter-delta count;
- trust/evidence rejection counts (scope, epoch, expiry, revocation, signature, role separation);
- dataset/artifact binding rejection counts;
- trust-region projection/rejection counts;
- durable append latency and append disposition;
- durable conflicts/poisoned-handle/indeterminate-write counts;
- bootstrap rejection, anchor mismatch, acknowledged-history-missing and anchor-retention failures;
- current writer fence, proposal sequence, registry scope digest, trust digest and admission digest as bounded identifiers, never secret payloads.

### 10.2 Alert policy

**[Host responsibility — MUST]** The following are paging/security events, not ordinary business metrics:

- anchor mismatch or acknowledged history missing;
- writer-fence/context mismatch;
- poisoned or indeterminate durable writer;
- signature/trust-snapshot mismatch for traffic expected to be enrolled;
- attempted authority grant or activation through this proposal-only path.

Repeated ineligible proposals, trust-region projection, or no-change-only candidate sets are operational signals and should be rate/quality alerts rather than immediate security pages unless the host profile says otherwise.

**[Target]** Numeric latency/error-budget thresholds require the selected target-host profile and measured baseline. This source PR intentionally does not invent deployment SLO numbers and then mislabel them as measured production limits.

## 11. Operator recovery runbook

1. **Anchor mismatch / acknowledged history missing:** stop writes; preserve the registry bytes; do not truncate or bootstrap; retrieve the independently retained anchor and reconcile the enrolled scope/fence. Treat loss of the trusted anchor as a security/recovery incident.
2. **Poisoned/indeterminate append:** stop using the handle; reopen under the production anchor posture; reconcile the last externally acknowledged anchor before retrying an identical proposal.
3. **Trust or signature rejection:** do not downgrade to raw V2. Verify trust snapshot, authority epoch, validity interval, revocation and controller enrollment; regenerate evidence only from the owning producer.
4. **Artifact/dataset mismatch:** fail closed and refresh owner receipts. Do not rewrite proposal digests to fit stale owner state.
5. **Independent evaluation ineligible/insufficient:** persist no governed proposal through the product caller. New evidence/evaluation requires a new authenticated admission attempt.
6. **Topology proposal rejection:** do not fall back to legacy V1 writes. Legacy topology remains read-only.
7. **Canary/activation:** this module does not perform it. Hand off only after independent acceptance and the separate activation authority path has satisfied its own gates.

## 12. Remaining closure items

- **[Target]** PLS-3 bounded structural canary execution and evidence.
- **[Target]** durable/authenticated topology product composition equivalent to governed parameter V3.
- **[External evidence gate]** exact-head test/clippy/qualification receipts for PR #624.
- **[External evidence gate]** independent semantic/security review.
- **[Host responsibility]** target-host metric backend, numeric SLO profile, alert routing, anchor service ownership and incident exercises.
- **[External evidence gate]** operator acceptance, canary, promotion, activation and release.

Until those gates exist, the accurate label is: **governed parameter proposal engine with product-side durable composition, plus source-level topology proposal construction; not an activated self-modifying runtime.**
