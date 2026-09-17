# learning.plasticity current implementation

Status: **source implementation overlay for PR #624**  
Base: `main@d7af096f28fa9989388939efa0e6600b52a43952`  
Source branch: `codex/plasticity-governed-engine-closure`  

This document is the current-source companion to `TECHNICAL.md`. The technical guide remains the full target/development envelope; this file states what is implemented in the source overlay, what remains target-only, and what the host must provide. Nothing here claims target-host product execution, operator acceptance, activation, promotion, or release. The exact source commit is recorded in `IMPLEMENTATION_OVERLAY.json` only after the candidate has stabilized; do not infer qualification from this prose.

## Status legend

- **[Implemented]** — native source exists in this PR and is reachable from a non-test product crate when stated.
- **[Target]** — specified design or later work package; no completion claim.
- **[Host responsibility]** — must be supplied by the deployment/trust domain and is not synthesized by this crate.
- **[External evidence gate]** — requires execution/acceptance evidence outside source inspection.

## 1. Parameter candidate generation

**[Implemented]** `generate_parameter_candidates_v3` in `codex-rs/hepta-plasticity/src/governed_v3.rs` is an in-crate generator. The caller supplies a bounded, evidence-bound parameter opportunity snapshot and generation policy, not a prebuilt candidate delta set.

The local deterministic update is:

```text
local_delta = eligibility * projected_modulator * learning_rate
candidate_delta = scale_ppm(local_delta)
```

The generator then applies per-parameter bounds and a conservative deterministic projection into the existing V2 per-layer/global trust region. Exactly one no-change candidate is generated. Update candidates are generated from the configured scale profile; semantic duplicates after projection are removed. Candidate IDs use fixed-width scale encoding so generator order matches V2 lexical canonicalization.

**[Implemented]** The complete generated candidate bytes are hashed and the candidate-set identity is content-addressed as `plasticity:set:<candidate_set_digest>`. The generated set is represented by `CandidateSetCompletenessReceiptV1` with `complete_for_generator=true` and `omitted_count_bound=0`; the independent evaluator must bind to that content-addressed set identity. A caller-selected set ID cannot transfer evaluation eligibility to another candidate set.

**[Implemented]** The module rejects duplicate parameter opportunities, opportunities outside the declared norm profile, zero norm denominators, inverted bounds, invalid evidence digests, non-positive learning rates, duplicate scales, and scale values outside `(0, 1_000_000] ppm`.

**[Target]** Richer grammars, learned candidate families, sparse/group update policies, or alternate projection algorithms may be added only behind new generator-code/grammar/filter/truncation bindings. They must not silently change V3 semantics.

## 2. Evidence existence, provenance and freshness

**[Implemented]** Governed V3 does not treat update/modulator/eligibility/per-parameter evidence as merely non-zero digests. `PlasticityEvidencePortV3` is a mandatory active-resolution boundary with no permissive/no-op production implementation in this crate.

Before governed admission, the module actively resolves and rechecks:

1. update-rule evidence;
2. modulator evidence;
3. modulator-broadcast evidence;
4. eligibility evidence;
5. every parameter-opportunity evidence digest.

Each `PlasticityEvidenceQueryV3` binds the requested kind and digest to objective, selected artifact, window ID/digest, dataset, baseline generation, optional layer/parameter identity and current time. The host resolver must look up the authoritative owner record, authenticate its producer and return `VerifiedPlasticityEvidenceV3`. The module then independently rejects context substitution, stale receipts, missing producer-credential/source-receipt digests, and malformed per-parameter context. Canonical verification receipts are hashed into one `evidence_verification_digest`, which is included in generator state and final governed admission.

**[Implemented]** Other owner facts are also actively checked:

- the selected artifact is looked up in `learning.artifacts::ArtifactRegistry` and must have matching content digest, objective, generation, allowed kind and eligible lineage;
- `DatasetSnapshotReceiptV3` is self-verified at the supplied current time and must match the proposal objective and dataset digest;
- the exact artifact/window/dataset/update-rule/modulator/eligibility/norm/opportunity binding is signed by an authenticated `Observer` role and verified by `LearningEvidenceVerifierV1`;
- generator completeness is signed by an authenticated `Generator` role;
- signed learning evidence must carry the same objective as the proposal binding.

The final V2 `evaluation_digest` is a governed admission digest binding artifact-registry head, active evidence-verification set, source authentication, generator authentication, completeness, evaluation evidence and trust snapshot.

**[Host responsibility — MUST]** A `PlasticityEvidencePortV3` implementation MUST resolve against the owning evidence store and MUST authenticate the producer before returning a verified receipt. Copying the query into a receipt without owner-store lookup violates the port contract. The selected deployment must define producer authorization by evidence kind and retain the authoritative source receipt independently of this proposal record.

**[Target/host adapter]** `kernel.evidence` remains a deployment integration target. The current `hepta-evidence` crate is not treated as a generic arbitrary-learning-digest verifier where its registered semantics do not match these learning facts; a host adapter must bind the appropriate owner stores rather than pretending an unrelated evidence schema proves them.

## 3. Independent evaluator trust boundary

**[Implemented]** Governed V3 does not derive evaluator independence from `proposer_id != evaluator_id`.

`propose_governed_v3` consumes `SignedEvaluationEvidenceV1` through `decide_with_signed_evidence_v2`. The existing trust verifier checks registered keys, trust digest, scope/objective, authority epoch, validity interval, revocation, signature and role. Signed role separation rejects generator/evaluator identity, credential-chain/signing-key or controller collapse. The V2 `evaluator_id` is populated from the authenticated evaluation principal rather than a free caller label.

The evaluation bundle must bind the content-addressed generated candidate-set identity, selected baseline artifact ID, objective, dataset and authenticated generator principal. `EligibleForIndependentSelection` is required before the proposal is persisted, but it is still not candidate selection, activation or promotion.

The structural inequality check remains in raw V2 as a compatibility invariant; it is not the production trust boundary.

## 4. Two-phase governed workflow and product composition

**[Implemented]** Candidate generation must precede generator signing and independent evaluation, so the product API is explicitly two-phase rather than pretending the caller can possess signatures over an object that has not been generated yet.

Phase A — `prepare_plasticity_v3` / `prepare_governed_parameter_candidates_v3`:

```text
artifact + dataset + active owner-evidence resolution
                  |
                  v
        authenticated Observer binding
                  |
                  v
       governed in-crate candidate generation
                  |
                  v
 content-addressed candidate set + completeness
                  |
                  v
       generator signing payload + set ID
```

The authenticated Generator signs the returned completeness payload and the independent evaluator evaluates the returned content-addressed set.

Phase B — `propose_and_persist_plasticity_v3` / `propose_governed_v3`:

```text
same owner state + generator signature + signed evaluation
                  |
                  v
       recompute every preparation input
                  |
             drift => reject
                  v
        ParameterProposalV2 (deny-all)
                  |
                  v
       ProductionProposalRegistry append
                  |
                  v
       next external rollback anchor
```

**[Implemented]** `codex-rs/hepta-intelligence/src/plasticity_host.rs` is a non-test product-side composition surface. `codex-hepta-plasticity` and `codex-hepta-learning-artifacts` are normal dependencies of `codex-hepta-intelligence`, not dev-only dependencies.

The product caller does not install weights, choose an update candidate, activate a snapshot, promote or release.

**[External evidence gate]** A non-test product-side call path is source composition, not proof that a selected target host executed or accepted it. Target-host execution receipts, operator acceptance and canary evidence remain required before the published implementation map may claim production implementation.

## 5. Topology plasticity

**[Implemented]** `TopologyProposalV2` and `propose_topology_v2` provide a new-write structural proposal path. The proposal binds:

- exact baseline/candidate generation successor;
- predecessor topology digest;
- add/remove/replace operation;
- typed nodes/edges digest;
- candidate topology digest;
- compatibility plan;
- resource delta;
- security review;
- lesion plan;
- rollback plan;
- evidence digest;
- deny-all authority and `RequiresIndependentAcceptance` status.

**[Target]** Topology V2 is proposal construction/verification only. It is not yet wired into a durable topology registry, authenticated governed topology admission, topology product caller, PLS-3 structural-canary execution or runtime topology application. Those remain explicit later work; this PR does not claim topology activation closure.

## 6. Rollback protection

**[Implemented]** `ProductionProposalRegistry` makes the external-anchor open posture executable:

- `BootstrapEmpty` calls `DurableProposalRegistry::open_bootstrap_empty`;
- the physical-empty check occurs only after the registry has acquired the exclusive file lock, eliminating the prior metadata-check-to-lock TOCTOU window for cooperating writers;
- every acknowledged reopen must use `ProductionAnchorStateV1::Acknowledged(anchor)`, which delegates to `DurableProposalRegistry::open_anchored`;
- after an append, the product caller obtains the exact next anchor and verifies that it matches the durable append receipt.

**[Host responsibility — MUST]** The returned anchor MUST be durably retained outside the proposal-registry file rollback domain before the append is treated as externally acknowledged. Loss of the separately trusted anchor cannot be repaired by the registry file itself.

**[Host responsibility — MUST]** Fence issuance, path enrollment, directory durability, permissions, backup, anchor retention, anchor revocation and disaster-recovery ownership remain host responsibilities.

**[Operational edge]** A crash after empty bootstrap writes/syncs the registry header but before the first externally acknowledged append leaves a non-empty, unanchored header-only file. Production recovery must use an explicit host enrollment/recovery procedure; `BootstrapEmpty` deliberately does not silently reinterpret such a file as a new enrollment.

## 7. Native dependency truth

**[Implemented]** The plasticity crate now has direct native dependencies on:

- `codex-hepta-intelligence-eval` — signed independent evaluation;
- `codex-hepta-learning-artifacts` — current artifact/lineage lookup;
- `codex-hepta-learning-ledger` — dataset receipt, generator completeness, signed learning evidence and role separation;
- `codex-hepta-types` — canonical shared primitives.

This replaces the previous mismatch where the technical architecture named evidence/evaluation/artifact components while the native crate depended only on `codex-hepta-types`.

**[Host adapter]** Active arbitrary learning-evidence resolution is expressed through `PlasticityEvidencePortV3`; the deployment binds that port to the authoritative owner stores, including `kernel.evidence` where its registered contract applies.

## 8. Current vs target architecture

**[Implemented/current]** Governed parameter V3 preparation/generation/admission, active owner-evidence verification boundary, raw parameter V2 verification, parameter durable registry, production external-anchor open gate, non-test product-side prepare/write composition, and topology V2 proposal construction.

**[Target]** Durable governed topology storage, topology product caller, structural-canary lifecycle, runtime application/rollback adapters, deployment-specific observability backend, externally persisted anchor-ack service, and activation/promotion/release processes.

**[Host responsibility]** Trust enrollment, key/controller separation, authoritative evidence-store adapters and producer policy, external anchor retention, operator procedures and target-host telemetry backend.

`TECHNICAL.md` is the complete development/target guide. This companion controls the current-source interpretation for PR #624 where the target guide intentionally describes later architecture.

## 9. CI and qualification truth

**[External evidence gate]** A source file or test identity is not an execution receipt. PR #624 must be evaluated at its exact head. Repo-wide failures must not be attributed to `learning.plasticity` without a failing job/test that establishes that relationship.

Required branch checks for this change include at minimum:

```text
cargo fmt --check
cargo check -p codex-hepta-plasticity -p codex-hepta-intelligence
cargo test -p codex-hepta-plasticity -p codex-hepta-intelligence --lib
cargo clippy -p codex-hepta-plasticity -p codex-hepta-intelligence --all-targets -- -D warnings
repository integrity / implementation-map verification
Lane F qualification affected by the product dependency change
```

The branch also uses a temporary exact-branch Rust probe to refresh only workspace path-dependency lock metadata and run these checks. The temporary workflow is development scaffolding and must be removed before the PR is declared ready.

Do not mark this document as product-qualified merely because these invocations are listed here.

## 10. Operations and observability

### 10.1 Required metric/event surface

**[Host responsibility]** A production host must emit at least the following measurements from the product adapter boundary:

- preparation attempts, successes and rejection counts by stable rejection class;
- finalize/persist attempts, successes and rejection counts by stable rejection class;
- generated candidate count and total generated parameter-delta count;
- candidate-set digest/completeness digest as bounded identifiers;
- active evidence-resolution counts and rejections for missing, unauthorized, stale, context-mismatched and invalid receipts;
- trust/evidence rejection counts for scope, epoch, expiry, revocation, signature and role separation;
- dataset/artifact binding rejection counts;
- trust-region projection/rejection counts;
- prepare/finalize drift rejections;
- durable append latency and append disposition;
- durable conflicts, poisoned-handle and indeterminate-write counts;
- bootstrap rejection, anchor mismatch, acknowledged-history-missing and anchor-retention failures;
- current writer fence, proposal sequence, registry scope digest, trust digest, evidence-verification digest and admission digest as bounded identifiers, never secret payloads.

### 10.2 Alert policy

**[Host responsibility — MUST]** The following are paging/security events, not ordinary business metrics:

- anchor mismatch or acknowledged history missing;
- writer-fence/context mismatch;
- poisoned or indeterminate durable writer;
- unexpected BootstrapEmpty on a non-empty enrolled path;
- signature/trust-snapshot mismatch for traffic expected to be enrolled;
- active evidence resolver reporting unauthorized producer or current-context substitution;
- prepare/finalize content drift after evidence/signature collection;
- attempted authority grant or activation through this proposal-only path.

Repeated ineligible proposals, trust-region projection or no-change-only candidate sets are operational signals and should be rate/quality alerts rather than immediate security pages unless the host profile says otherwise.

**[Target]** Numeric latency/error-budget thresholds require the selected target-host profile and a measured baseline. This source PR intentionally does not invent deployment SLO numbers and then mislabel them as measured production limits.

## 11. Operator recovery runbook

1. **Anchor mismatch / acknowledged history missing:** stop writes; preserve the registry bytes; do not truncate or bootstrap; retrieve the independently retained anchor and reconcile enrolled scope/fence. Treat loss of the trusted anchor as a security/recovery incident.
2. **Poisoned/indeterminate append:** stop using the handle; reopen under the last externally acknowledged anchor; reconcile the durable tail before retrying an identical proposal.
3. **Header-only unacknowledged bootstrap:** do not use `BootstrapEmpty` to bypass the non-empty check. Follow the host enrollment recovery procedure, prove there was no externally acknowledged frame, then either recover or re-enroll the path under a new controlled lifecycle.
4. **Active evidence rejection:** do not downgrade to opaque digest binding. Resolve the authoritative owner record; verify producer enrollment, current context, freshness and source receipt; regenerate evidence only from the owning producer.
5. **Trust or signature rejection:** do not downgrade to raw V2. Verify trust snapshot, authority epoch, validity interval, revocation and controller enrollment.
6. **Artifact/dataset mismatch:** fail closed and refresh owner receipts. Do not rewrite proposal digests to fit stale owner state.
7. **Prepare/finalize drift:** discard the stale signatures/evaluation and repeat preparation from current owner state. Never transplant a prior evaluation onto a new content-addressed set.
8. **Independent evaluation ineligible/insufficient:** persist no governed proposal through the product caller. New evidence/evaluation requires a new authenticated admission attempt.
9. **Topology proposal rejection:** do not fall back to legacy V1 writes. Legacy topology remains read-only.
10. **Canary/activation:** this module does not perform it. Hand off only after independent acceptance and the separate activation authority path has satisfied its own gates.

## 12. Remaining closure items

- **[Target]** PLS-3 bounded structural-canary execution and evidence.
- **[Target]** durable/authenticated topology product composition equivalent to governed parameter V3.
- **[Host responsibility]** concrete authoritative `PlasticityEvidencePortV3` adapter(s) for the selected deployment and producer-enrollment policy.
- **[Host responsibility]** externally durable anchor-ack service and explicit header-only bootstrap recovery procedure.
- **[External evidence gate]** exact-head format/check/test/clippy/qualification receipts for PR #624.
- **[External evidence gate]** independent semantic/security review.
- **[Host responsibility]** target-host metric backend, numeric SLO profile, alert routing, anchor service ownership and incident exercises.
- **[External evidence gate]** operator acceptance, canary, promotion, activation and release.

Until those gates exist, the accurate label is: **governed parameter proposal engine with active evidence-resolution and product-side durable composition, plus source-level topology proposal construction; not an activated self-modifying runtime.**
