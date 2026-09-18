# learning.plasticity: implementation design

Parent: `docs/modules/learning.plasticity/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: Parameter V2 remains the stable record/verifier boundary; deterministic V3 generation, typed mutation policy, authenticated parameter admission, explicit anchor-acknowledgement writer state, a non-test Agentd selected-host surface, host anti-rollback anchor/fence journal, typed topology V2 proposals, typed protected-surface policy, per-candidate writer-handoff validation, durable topology proposal storage and authenticated topology admission are implemented in source. PLS-3 has a bounded source qualification fixture. No parameter installation, topology application, activation, promotion or release authority is implemented. Exact-candidate CI and external acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-plasticity`.
Packages: `PLS-1-PARAMETER-PLASTICITY`, `PLS-2-TOPOLOGY-PROPOSAL`, `PLS-3-BOUNDED-STRUCTURAL-CANARY`.

Operation signatures below describe the target contract. Section 8 identifies the current source implementation across the owner core, authenticated product composition and selected-host seam. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

Target operations remain `propose_parameter_delta(selected_artifact, eligibility, modulator, trust_region) -> PlasticityProposalV1`; `propose_topology(body_graph, typed_operation, unmet_capability) -> TopologyProposalV1`; `validate_candidate(candidate, constraints, rollback_design) -> CandidateDisposition`. The module can produce candidates, not apply them to its current runtime or select itself.

The source implementation uses versioned internal records instead of relabeling those target JSON contracts. Parameter V2 remains compatibility-stable. Parameter V3 defines a bounded deterministic generator whose output can be regenerated exactly and then admitted only through typed mutation policy and authenticated product composition. Topology V2 creates typed structural candidates and can be durably retained as proposals, but deliberately has no apply path.

## 3. State records and transaction design

`plasticity_proposal_registry` remains append-only. Parameter and topology proposal stores bind proposal/content identity, selected artifact/window, exact predecessor, generation, evaluation/lineage and rollback state. Generated candidate state never doubles as selected production state. Current selected weights and graph are read-only.

The parameter and topology product writers enroll new stores only through a lock-scoped physical-empty check, then expose explicit anchor acknowledgement. After a successful durable append they enter `AppendPendingAnchor`; product success is returned only after an independent anchor committer durably acknowledges the exact registry head. Anchor failure or indeterminate durability poisons the handle. A selected deployment must place the Agentd anchor/fence journal outside the proposal-file rollback domain.

## 4. Deterministic algorithm and scheduling

Parameter V3 starts with no-change and evaluates every declared positive scale over explicit parameter signals. Each signal maps eligibility, modulator and learning rate to one parameter, uses checked Q32 arithmetic, clamps to explicit bounds, rejects unknown norm layers and duplicate parameter identities, applies the canonical per-layer/global trust regions, removes duplicate semantic candidates, and derives update candidate IDs from the selected artifact, exact window and canonical content. The source therefore proves generator-relative completeness for the declared bounded V3 profile rather than accepting an arbitrary caller candidate list as complete.

`MutationGrammarManifestV1` is the executable mutation policy for the governed parameter path. It binds the selected artifact, revision, explicit layer/parameter allowlist, maximum/minimum deltas and protected parameter classes. Protected authority/evaluation/deletion/privacy/secret/runtime-topology/provider-tool surfaces cannot enter governed generation, and a signal may narrow but not widen grammar bounds.

For authenticated composition, the Generator signs the generated-set digest. A trusted Observer signs the selected artifact, exact artifact/evidence frontiers, typed grammar digest, window, generation and dataset/update/modulator/eligibility lineage. Every update candidate must then carry a signed independent evaluation under the existing host-owned learning-evidence trust snapshot. Proposer and evaluator IDs are derived from verified principals, not caller-supplied role labels.

Topology V2 starts with no-change and one candidate per typed operation. Add/remove/replace/split/merge/rewire/retire changes carry migration, rollback, writer-handoff and evidence digests. `TopologyMutationPolicyV1` binds protected authority/evaluator/evidence/deletion/privacy/secret/release/runtime-host modules to the selected artifact and is signed by the Observer admission; governed topology rejects any protected target before evaluation or persistence. `TopologyWriterHandoffV1` binds the exact topology operation plus distinct source/destination writers and domains to the same exact generations, migration and rollback design, and handoffs are matched per candidate by their exact handoff digest rather than only by module ID. Application remains outside this module.

## 5. Capacity and performance profile

Canonical parameter bounds remain <=32 candidates, <=4,096 total deltas, <=256 norm layers, per-layer relative parameter delta<=0.5%, global<=0.25%, and one proposal per artifact/window. V3 admits at most 31 update scales and caps signal/scale work at 4,096 deterministic evaluations. Initial structural candidates contain one operation and are capped at 31 updates plus no-change.

The current operating profile now lives in `docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md#9-operations-and-observability-profile`; `OPERATIONS.md` is a stable compatibility pointer. Thresholds remain host targets until target-host measurements exist.

## 6. Concrete verification cases

- PLS-01: parameter deltas beyond any trust region reject even when visible reward improves.
- PLS-02: split/merge cannot duplicate writers or erase supported lineage.
- PLS-03: topology candidate cannot self-activate or alter its evaluator/hidden tests.
- PLS-04: canary abort fences new work and verifies a compatible non-revoked predecessor after reconciling outstanding effects.
- PLS-05: regenerated V3 candidate set must exactly match the generator digest and artifact/window-bound content IDs.
- PLS-06: authenticated adapters reject unsigned/expired/revoked Generator or Observer evidence, generator/evaluator controller collision, missing candidate evaluation and stale/frontier mismatch.
- PLS-07: governed parameter generation rejects unknown/protected parameters and any signal bounds wider than `MutationGrammarManifestV1`.
- PLS-08: after durable append, external anchor failure moves the product writer to `Poisoned`; no normal read/append operation is permitted through that handle.
- PLS-09: topology durable storage preserves exact predecessor/checksum chain/slot conflict semantics and requires an external anchor for acknowledged-history recovery.
- PLS-10: topology admission requires the Observer-bound protected-surface policy, exactly one matching typed writer handoff and independent signed evaluation for every update candidate.
- PLS-11: the bounded structural canary persists only a proposal, anchored-reopens it, and aborts before persistence when rollback/handoff lineage drifts.

These are required product or qualification test designs unless a named exact-candidate receipt is attached. Source test identity is not an execution receipt.

## 7. Integration, rollback and capability ceiling

The deterministic owner core remains in `codex-rs/hepta-plasticity`. Authenticated parameter/topology product composition lives in `codex-rs/hepta-intelligence`; trust/evaluation and owner-store authentication are deliberately not pushed into the pure proposal core.

`AgentdPlasticityHostV1` in `codex-rs/hepta-agentd/src/plasticity_host.rs` is the non-test selected-host composition surface. It re-reads the authoritative artifact registry, resolves update/modulator/eligibility/per-parameter evidence through injected owner-store adapters, recomputes an exact query-context digest including dataset and layer/parameter identity, requires the returned owner receipt to bind that context and match an explicit kind-to-owner allow-policy, canonicalizes the verified receipts and owner policy into a `host_evidence_verification_digest`, requires one exact evidence frontier, and only then invokes authenticated parameter admission. The product proposal binds that host verification digest; verification clock time is excluded from semantic identity. `AgentdPlasticityAnchorFenceStoreV1` provides a locked append-only monotonic fence/anchor journal; deployment still owns the independent rollback domain in which that journal is placed.

This is source host composition, not proof that a deployed target host has enrolled the surface. Rollback of selected model/topology state and any graph/weight installation remain authorized transitions outside this proposal engine.

## 8. Current native implementation

- **Implemented entrypoints:** `propose_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `verify_parameter_proposal_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `MutationGrammarManifestV1` in [codex-rs/hepta-plasticity/src/mutation_grammar_v1.rs](../../../codex-rs/hepta-plasticity/src/mutation_grammar_v1.rs); `generate_parameter_candidates_v3` in [codex-rs/hepta-plasticity/src/generator_v3.rs](../../../codex-rs/hepta-plasticity/src/generator_v3.rs); `verify_generated_parameter_candidates_v3` in [codex-rs/hepta-plasticity/src/generator_v3.rs](../../../codex-rs/hepta-plasticity/src/generator_v3.rs); `DurableProposalRegistry` in [codex-rs/hepta-plasticity/src/durable_registry.rs](../../../codex-rs/hepta-plasticity/src/durable_registry.rs); `propose_topology_v2` in [codex-rs/hepta-plasticity/src/topology_v2.rs](../../../codex-rs/hepta-plasticity/src/topology_v2.rs); `verify_topology_proposal_v2` in [codex-rs/hepta-plasticity/src/topology_v2.rs](../../../codex-rs/hepta-plasticity/src/topology_v2.rs); `TopologyMutationPolicyV1` and `TopologyWriterHandoffV1` in [codex-rs/hepta-plasticity/src/topology_governance_v1.rs](../../../codex-rs/hepta-plasticity/src/topology_governance_v1.rs); `DurableTopologyProposalRegistryV2` in [codex-rs/hepta-plasticity/src/durable_topology_registry_v2.rs](../../../codex-rs/hepta-plasticity/src/durable_topology_registry_v2.rs).
- **Authenticated product composition:** `propose_authenticated_parameter_plasticity_v1`, `PlasticityWriterStateV1` and `AnchoredPlasticityWriterV1` in [codex-rs/hepta-intelligence/src/plasticity_product.rs](../../../codex-rs/hepta-intelligence/src/plasticity_product.rs); `propose_authenticated_topology_plasticity_v1` and `AnchoredTopologyPlasticityWriterV1` in [codex-rs/hepta-intelligence/src/plasticity_topology_product.rs](../../../codex-rs/hepta-intelligence/src/plasticity_topology_product.rs).
- **Selected-host source surface:** `AgentdPlasticityHostV1`, `PlasticityOwnerEvidencePolicyV1`, canonical owner-evidence query binding and `AgentdPlasticityAnchorFenceStoreV1` in [codex-rs/hepta-agentd/src/plasticity_host.rs](../../../codex-rs/hepta-agentd/src/plasticity_host.rs). Source presence does not prove target-host enrollment or execution.
- **Evidence boundary:** product adapters use the existing `LearningEvidenceVerifierV1` and signed evaluation path for trust-root, signature, expiry, revocation, role and controller-separation checks. Agentd obtains current owner-state frontiers; it does not mint owner evidence.
- **Source tests:** [codex-rs/hepta-plasticity/src/lib_tests.rs](../../../codex-rs/hepta-plasticity/src/lib_tests.rs), [codex-rs/hepta-plasticity/src/durable_registry_tests.rs](../../../codex-rs/hepta-plasticity/src/durable_registry_tests.rs), inline generator/mutation/topology/handoff tests, [codex-rs/hepta-intelligence/src/plasticity_product_tests.rs](../../../codex-rs/hepta-intelligence/src/plasticity_product_tests.rs), [codex-rs/hepta-intelligence/src/plasticity_topology_product_tests.rs](../../../codex-rs/hepta-intelligence/src/plasticity_topology_product_tests.rs), [codex-rs/hepta-agentd/tests/plasticity_host.rs](../../../codex-rs/hepta-agentd/tests/plasticity_host.rs), and [qualification/lane-f-shadow/tests/plasticity_structural_canary.rs](../../lane-f-shadow/tests/plasticity_structural_canary.rs). These are test identities, not pass receipts.
- **Current-source truth:** [docs/modules/learning.plasticity/CURRENT_STATE.json](../../../docs/modules/learning.plasticity/CURRENT_STATE.json) is the machine current-state manifest; [CURRENT_IMPLEMENTATION.md](../../../docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md) contains its generated projection and the single current operations/recovery narrative.
- **Remaining work:** exact-head/synthetic-merge CI for the final candidate; deployment binding for real owner-evidence adapters and an independently rolled-back anchor/fence store; independent semantic/security review; target-host recovery/telemetry qualification and operator acceptance. Parameter installation, topology application, activation, promotion and release remain outside this source claim.
