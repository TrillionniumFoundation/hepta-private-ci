# learning.plasticity: implementation design

Parent: `docs/modules/learning.plasticity/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: parameter-only V2 construction/verification and durable proposal registry implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-plasticity`.
Packages: `PLS-1-PARAMETER-PLASTICITY`, `PLS-2-TOPOLOGY-PROPOSAL`, `PLS-3-BOUNDED-STRUCTURAL-CANARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`propose_parameter_delta(selected_artifact, eligibility, modulator, trust_region) -> PlasticityProposalV1`; `propose_topology(body_graph, typed_operation, unmet_capability) -> TopologyProposalV1`; `validate_candidate(candidate, constraints, rollback_design) -> CandidateDisposition`. The module can produce candidates, not apply them to its current runtime or select itself.

## 3. State records and transaction design

`plasticity_proposal_registry` is append-only: candidate/content ID, exact predecessor, source/objective/body, generator, supported dataset and update-rule digests, parameter/topology delta, bounds, test/evaluation references, rollback and state. Generated candidate state never doubles as selected production state. Current selected weights and graph are read-only.

## 4. Deterministic algorithm and scheduling

Start with no-change and one bounded operation; map low-dimensional modulation to explicit parameter groups; enforce per-layer/global trust regions; reject protected authority/evaluator/deletion surfaces; type-check topology; simulate/fault-test; compare utility, stability, old tasks, complexity and resources; request independent evaluation. Add/split/merge/rewire/retire follow the shared ownership/handoff obligations. Apply only through a separately selected later generation.

## 5. Capacity and performance profile

Canonical <=32 candidates, <=8 sandboxes, per-layer relative parameter delta<=0.5%, global<=0.25%, and one proposal per artifact/window unless stricter profile. Initial structural candidates contain one operation. Duplicate ratio>=50%, unsupported evaluation or rollback failure ends search.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- PLS-01: parameter deltas beyond any trust region reject even when visible reward improves.
- PLS-02: split/merge cannot duplicate writers or erase supported lineage.
- PLS-03: topology candidate cannot self-activate or alter its evaluator/hidden tests.
- PLS-04: canary abort fences new work and verifies a compatible non-revoked predecessor after reconciling outstanding effects.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

The organ loader/supervisor consumes independent decisions and a formal handoff packet; this proposal engine cannot mint those records. Biomimicry and long-term evolution require future/ablation evidence, not merely a valid delta. Rollback is an authorized new transition.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `propose_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `verify_parameter_proposal_v2` in [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs); `DurableProposalRegistry` in [codex-rs/hepta-plasticity/src/durable_registry.rs](../../../codex-rs/hepta-plasticity/src/durable_registry.rs). Parameter-only V2 construction/verification and durable proposal registry implemented.
- **State and recovery:** V2 verifies supplied parameter deltas and norm arithmetic. DurableProposalRegistry owns bounded, locked, generation/fence-scoped checksum-chain frames, syncs before publication and supports an independently retained anchor.
- **Source tests:** [codex-rs/hepta-plasticity/src/lib_tests.rs](../../../codex-rs/hepta-plasticity/src/lib_tests.rs), [codex-rs/hepta-plasticity/src/durable_registry_tests.rs](../../../codex-rs/hepta-plasticity/src/durable_registry_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/modules/learning.plasticity/TECHNICAL.md](../../../docs/modules/learning.plasticity/TECHNICAL.md), [docs/learning/NEURAL_BIOMIMICRY_SPEC.md](../../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md).
- **Remaining work:** Authenticate generator-relative completeness/current lineage and independent decisions. This parameter-only path neither trains/installs weights nor implements the full target topology-application lifecycle.
