# learning.plasticity: implementation design

Parent: `docs/modules/learning.plasticity/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: bounded parameter generation/verification, authenticated composition boundary, production-safe durable parameter registry, topology V2 proposal construction/verification and a named Lane-F caller are implemented in source. Production activation, external trust-root operation, independent acceptance and topology/parameter application remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-plasticity`.
Packages: `PLS-1-PARAMETER-PLASTICITY`, `PLS-2-TOPOLOGY-PROPOSAL`, `PLS-3-BOUNDED-STRUCTURAL-CANARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`propose_parameter_delta(selected_artifact, eligibility, modulator, trust_region) -> PlasticityProposalV1`; `propose_topology(body_graph, typed_operation, unmet_capability) -> TopologyProposalV1`; `validate_candidate(candidate, constraints, rollback_design) -> CandidateDisposition`. The module can produce candidates, not apply them to its current runtime or select itself.

The current composed parameter path is stricter than the compatibility V2 constructor: the caller supplies bounded learning signals, the native generator constructs the candidate set, host-owned evidence/evaluator verifiers authenticate external facts, and only then may a production-safe registry append the proposal. A durable receipt remains a proposal acknowledgement only.

## 3. State records and transaction design

`plasticity_proposal_registry` is append-only: candidate/content ID, exact predecessor, source/objective/body, generator, supported dataset and update-rule digests, parameter/topology delta, bounds, test/evaluation references, rollback and state. Generated candidate state never doubles as selected production state. Current selected weights and graph are read-only.

The production parameter writer is `ProductionProposalRegistry`: a new enrolled file may be initialized once; acknowledged history may be reopened only with an independently retained external anchor. The raw unanchored `DurableProposalRegistry::open` remains a compatibility/test/bootstrap surface and is not sufficient for acknowledged production history.

## 4. Deterministic algorithm and scheduling

Parameter generation starts with explicit no-change and deterministic ranked learning signals, then emits bounded prefix candidates under a configured maximum step/count. The existing V2 verifier enforces per-layer/global trust regions and canonical integrity. The composed caller requires an empty incoming candidate list so a caller cannot substitute a final candidate set while claiming native generator completeness.

Topology V2 starts with no-change and bounded mutation candidates. Structural candidates contain at most one operation and bind predecessor, candidate, migration, rollback and evidence digests. Type-specific runtime graph application, writer handoff and activation remain later operations.

Apply any parameter/topology candidate only through a separately selected later generation.

## 5. Capacity and performance profile

Canonical <=32 candidates, <=8 sandboxes, per-layer relative parameter delta<=0.5%, global<=0.25%, and one durable parameter proposal per artifact/window unless stricter profile. Initial structural candidates contain one operation. Duplicate ratio>=50%, unsupported evaluation or rollback failure ends search.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. The selected host must supply actual SLO measurements and overload behavior before activation.

## 6. Concrete verification cases

- PLS-01: parameter deltas beyond any trust region reject even when visible reward improves.
- PLS-02: structural candidates bind migration and rollback and cannot duplicate writers or erase supported lineage.
- PLS-03: topology candidate cannot self-activate or grant authority.
- PLS-04: production reopen requires a compatible external anchor after acknowledged history.
- PLS-05: missing, stale, wrong-scope or verifier-rejected evidence prevents composed append.
- PLS-06: independent evaluator verification is required in addition to unequal role IDs.
- PLS-07: composed parameter caller generates candidates natively and rejects preconstructed incoming candidates.

Focused source identities are listed in section 8. GitHub Actions/current-head results are execution receipts and must be inspected separately from this document.

## 7. Integration, rollback and capability ceiling

`codex_hepta_intelligence::run_plasticity_proposal_cycle_v1` is the named repository caller for the composed proposal path. It delegates generation/authentication/append to `learning.plasticity` and cannot select, activate, train, install, promote or release the proposal.

The selected host owns registered trust roots, revocation/freshness inputs, path enrollment, writer-fence issuance, and the external anti-rollback anchor store. The anchor MUST live in a rollback domain independent from the registry file and normal backups. See `docs/modules/learning.plasticity/THREAT_MODEL.md` and `OPERATIONS.md`.

The organ loader/supervisor still consumes independent decisions and a formal handoff packet for any later application. Rollback of selected runtime state is an authorized new transition, not an implication of a proposal record.

## 8. Current native implementation

- **Implemented entrypoints:** `propose_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `verify_parameter_proposal_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `generate_parameter_proposal_v2` in [codex-rs/hepta-plasticity/src/generator.rs](../../../codex-rs/hepta-plasticity/src/generator.rs); `propose_authenticated_v1` in [codex-rs/hepta-plasticity/src/trusted.rs](../../../codex-rs/hepta-plasticity/src/trusted.rs); `generate_authenticate_and_append_v1` in [codex-rs/hepta-plasticity/src/engine.rs](../../../codex-rs/hepta-plasticity/src/engine.rs); `ProductionProposalRegistry` in [codex-rs/hepta-plasticity/src/production_registry.rs](../../../codex-rs/hepta-plasticity/src/production_registry.rs); `DurableProposalRegistry` in [codex-rs/hepta-plasticity/src/durable_registry.rs](../../../codex-rs/hepta-plasticity/src/durable_registry.rs); `propose_topology_v2` in [codex-rs/hepta-plasticity/src/topology_v2.rs](../../../codex-rs/hepta-plasticity/src/topology_v2.rs); `verify_topology_proposal_v2` in [codex-rs/hepta-plasticity/src/topology_v2.rs](../../../codex-rs/hepta-plasticity/src/topology_v2.rs).
- **Named caller:** `run_plasticity_proposal_cycle_v1` in [codex-rs/hepta-intelligence/src/plasticity_host.rs](../../../codex-rs/hepta-intelligence/src/plasticity_host.rs). This is source composition evidence, not deployed product-execution evidence.
- **Trust boundary:** compatibility V2 remains integrity-only. The composed path requires host-owned `EvidenceVerifier` and `IndependentEvaluatorVerifier` grants after exact artifact/window/freshness binding.
- **State and recovery:** `ProductionProposalRegistry` permits fresh initialization or anchored reopen. `DurableProposalRegistry` owns bounded, locked, generation/fence-scoped checksum-chain frames, sync-before-publication, exact replay and incomplete-tail repair after anchor reconciliation.
- **Topology:** Topology V2 proposal construction/verification is implemented and deny-all; durable topology storage/application and graph mutation are not implemented.
- **Source tests:** [codex-rs/hepta-plasticity/src/lib_tests.rs](../../../codex-rs/hepta-plasticity/src/lib_tests.rs), [codex-rs/hepta-plasticity/src/durable_registry_tests.rs](../../../codex-rs/hepta-plasticity/src/durable_registry_tests.rs), [codex-rs/hepta-plasticity/src/closeout_tests.rs](../../../codex-rs/hepta-plasticity/src/closeout_tests.rs). These are test identities, not a substitute for current CI receipts.
- **Status/operations references:** [CURRENT_IMPLEMENTATION.md](../../../docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md), [OPERATIONS.md](../../../docs/modules/learning.plasticity/OPERATIONS.md), [THREAT_MODEL.md](../../../docs/modules/learning.plasticity/THREAT_MODEL.md), [docs/learning/NEURAL_BIOMIMICRY_SPEC.md](../../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md).
- **Remaining external/target work:** bind concrete deployed trust-root implementations and independently retained anchor service; obtain target-host execution evidence and independent semantic/operator acceptance; implement separately governed parameter training/install and topology durable application/handoff before any activation claim.
