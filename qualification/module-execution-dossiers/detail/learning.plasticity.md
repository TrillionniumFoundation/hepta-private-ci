# learning.plasticity: implementation design

Parent: `docs/modules/learning.plasticity/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: parameter V2 construction/verification and durable registry implemented; deterministic generator-relative parameter completeness, authenticated product-workspace composition, anchored production writer seam, and typed topology V2 proposal generation are implemented in source. Topology application, activation and independent/operator acceptance remain external gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-plasticity`.
Packages: `PLS-1-PARAMETER-PLASTICITY`, `PLS-2-TOPOLOGY-PROPOSAL`, `PLS-3-BOUNDED-STRUCTURAL-CANARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and current product composition. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

Target operations remain `propose_parameter_delta(selected_artifact, eligibility, modulator, trust_region) -> PlasticityProposalV1`; `propose_topology(body_graph, typed_operation, unmet_capability) -> TopologyProposalV1`; `validate_candidate(candidate, constraints, rollback_design) -> CandidateDisposition`. The module can produce candidates, not apply them to its current runtime or select itself.

The source implementation uses versioned internal records instead of relabeling those target JSON contracts. Parameter V2 remains compatibility-stable. Parameter V3 defines a bounded deterministic generator whose output can be regenerated exactly. Topology V2 creates typed structural candidates but deliberately has no apply path.

## 3. State records and transaction design

`plasticity_proposal_registry` is append-only: candidate/content ID, exact predecessor, source/objective/body, generator, supported dataset and update-rule digests, parameter/topology delta, bounds, test/evaluation references, rollback and state. Generated candidate state never doubles as selected production state. Current selected weights and graph are read-only.

The product writer can bootstrap only a zero-length newly enrolled file. Once any acknowledged history exists, product reopen requires an independently retained external anchor. The host owns serialized writer-fence issuance and persistence of that external anchor.

## 4. Deterministic algorithm and scheduling

Parameter V3 starts with no-change and evaluates every declared positive scale over explicit parameter signals. Each signal maps eligibility, modulator and learning rate to one parameter, uses checked Q32 arithmetic, clamps to explicit bounds, rejects unknown norm layers and duplicate parameter identities, applies the canonical per-layer/global trust regions, removes duplicate semantic candidates, and derives update candidate IDs from canonical content. The source therefore proves generator-relative completeness for the declared bounded V3 profile rather than accepting an arbitrary caller candidate list as complete.

For authenticated product composition, the generator signs the generated-set digest. A trusted Observer signs the selected artifact, current artifact/evidence frontiers, window, generation, dataset/update/modulator/eligibility lineage and generator digest. Every update candidate must then carry a signed independent evaluation under the existing host-owned learning-evidence trust snapshot. Proposer and evaluator IDs are derived from verified principals, not caller-supplied role labels.

Topology V2 starts with no-change and one candidate per typed operation. Add/remove/replace/split/merge/rewire/retire changes carry migration, rollback, writer-handoff and evidence digests. Application remains outside this module.

## 5. Capacity and performance profile

Canonical parameter bounds remain <=32 candidates, <=4,096 total deltas, <=256 norm layers, per-layer relative parameter delta<=0.5%, global<=0.25%, and one proposal per artifact/window. V3 admits at most 31 update scales and caps signal/scale work at 4,096 deterministic evaluations. Initial structural candidates contain one operation and are capped at 31 updates plus no-change.

Operational thresholds and recovery are now concrete in `docs/modules/learning.plasticity/OPERATIONS.md`; they remain host targets until exact deployment measurements exist.

## 6. Concrete verification cases

- PLS-01: parameter deltas beyond any trust region reject even when visible reward improves.
- PLS-02: split/merge cannot duplicate writers or erase supported lineage.
- PLS-03: topology candidate cannot self-activate or alter its evaluator/hidden tests.
- PLS-04: canary abort fences new work and verifies a compatible non-revoked predecessor after reconciling outstanding effects.
- PLS-05: regenerated V3 candidate set must exactly match the generator digest and content-derived IDs.
- PLS-06: product composition rejects unsigned/expired/revoked generator or Observer evidence, generator/evaluator controller collision, missing candidate evaluation and stale/frontier mismatch.
- PLS-07: any product reopen of acknowledged proposal history requires the externally retained registry anchor.

These are required product test designs unless a named exact-candidate receipt is attached. Source test identity is not an execution receipt.

## 7. Integration, rollback and capability ceiling

The product-workspace integration lives in `codex-rs/hepta-intelligence/src/plasticity_product.rs` and uses the existing signed learning-evidence/evaluation boundary. It can durably append an authenticated parameter proposal but cannot mint independent acceptance, selection, installation, runtime mutation, promotion or release authority.

Rollback of the proposal registry requires an independently retained anchor and a new host-issued writer fence. Rollback of selected model/topology state remains an authorized transition outside this proposal engine.

## 8. Current native implementation

- **Implemented entrypoints:** `propose_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `verify_parameter_proposal_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `generate_parameter_candidates_v3` in [codex-rs/hepta-plasticity/src/generator_v3.rs](../../../codex-rs/hepta-plasticity/src/generator_v3.rs); `verify_generated_parameter_candidates_v3` in [codex-rs/hepta-plasticity/src/generator_v3.rs](../../../codex-rs/hepta-plasticity/src/generator_v3.rs); `propose_topology_v2` in [codex-rs/hepta-plasticity/src/topology_v2.rs](../../../codex-rs/hepta-plasticity/src/topology_v2.rs); `verify_topology_proposal_v2` in [codex-rs/hepta-plasticity/src/topology_v2.rs](../../../codex-rs/hepta-plasticity/src/topology_v2.rs); `DurableProposalRegistry` in [codex-rs/hepta-plasticity/src/durable_registry.rs](../../../codex-rs/hepta-plasticity/src/durable_registry.rs).
- **Product composition:** `propose_authenticated_parameter_plasticity_v1` and `AnchoredPlasticityWriterV1` in [codex-rs/hepta-intelligence/src/plasticity_product.rs](../../../codex-rs/hepta-intelligence/src/plasticity_product.rs). This is a product-workspace caller/writer seam, not activation or release evidence.
- **State and recovery:** `DurableProposalRegistry` owns bounded, locked, generation/fence-scoped checksum-chain frames. The product writer allows unanchored open only for a brand-new zero-length registry; acknowledged history reopens through an external anchor.
- **Evidence boundary:** product composition uses the existing `LearningEvidenceVerifierV1` and signed evaluation path for trust-root, signature, expiry, revocation, role and controller-separation checks. The Observer attestation binds current artifact/evidence frontiers and all proposal lineage inputs.
- **Source tests:** existing [codex-rs/hepta-plasticity/src/lib_tests.rs](../../../codex-rs/hepta-plasticity/src/lib_tests.rs), [codex-rs/hepta-plasticity/src/durable_registry_tests.rs](../../../codex-rs/hepta-plasticity/src/durable_registry_tests.rs), plus inline V3 generator/topology/product-writer regressions. These are test identities, not execution receipts for this documentation revision.
- **Current-state reference:** [docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md](../../../docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md) separates implemented, composed, target and host-responsibility states.
- **Remaining external work:** exact-head/synthetic-merge qualification for this change, independent semantic review, selected-host canary/operator acceptance, topology application/writer-handoff implementation, activation, promotion and release. The parameter path still does not train or install weights.
