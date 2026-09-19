# learning.plasticity current implementation boundary

This document is the current-state companion to `TECHNICAL.md`. `TECHNICAL.md`
contains both target architecture and stable requirements; this file states what is
implemented now. A claim listed as **Implemented** is a source capability, not an
activation, acceptance, promotion or release claim.

<!-- BEGIN GENERATED IMPLEMENTATION STATUS -->
## Generated implementation status

This block is generated only from `IMPLEMENTATION_MAP.json`. Run
`python3 scripts/hepta-implementation-maps.py sync-plasticity-status` after
changing the map. Hand-written sections below explain semantics but do not
override these machine status facts.

- Product caller: `agentd_host_adapter_entrypoint_source_implemented_not_runtime_executed_or_target_host_qualified`
- Production writer: `agentd_parameter_and_topology_external_anchor_fence_source_implemented_not_target_host_qualified`
- Production implementation: `false`
- Product execution proved: `false`
- Independent acceptance: `false`
- Activation: `false`
- Release: `false`

| Operation | State | Source | Tests |
| --- | --- | --- | ---: |
| `propose_v2` | `source_implemented_product_and_agentd_host_composed_not_target_host_qualified` | `codex-rs/hepta-plasticity/src/parameter_v2.rs` | 1 |
| `verify_parameter_proposal_v2` | `source_implemented_product_and_agentd_host_composed_not_target_host_qualified` | `codex-rs/hepta-plasticity/src/parameter_v2.rs` | 1 |
| `generate_parameter_candidates_v3` | `source_implemented_agentd_host_composed_not_target_host_qualified` | `codex-rs/hepta-plasticity/src/generator_v3.rs` | 1 |
| `verify_generated_parameter_candidates_v3` | `source_implemented_agentd_host_composed_not_target_host_qualified` | `codex-rs/hepta-plasticity/src/generator_v3.rs` | 1 |
| `propose_topology_v2` | `source_implemented_governed_durable_host_composed_not_applied` | `codex-rs/hepta-plasticity/src/topology_v2.rs` | 1 |
| `verify_topology_proposal_v2` | `source_implemented_governed_durable_host_composed_not_applied` | `codex-rs/hepta-plasticity/src/topology_v2.rs` | 1 |
| `durableproposalregistry` | `source_implemented_agentd_host_composed_not_target_host_qualified` | `codex-rs/hepta-plasticity/src/durable_registry.rs` | 1 |
| `authenticated_product_composition` | `adapter_implemented_called_by_agentd_host_entrypoint_pairwise_roles_not_target_host_qualified` | `codex-rs/hepta-intelligence/src/plasticity_product.rs` | 5 |
| `anchored_product_writer` | `adapter_implemented_agentd_external_anchor_host_not_target_host_qualified` | `codex-rs/hepta-intelligence/src/plasticity_product.rs` | 2 |
| `parameter_mutation_policy` | `source_implemented_authority_free_typed_parameter_allowlist_protected_surfaces` | `codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs` | 1 |
| `agentd_parameter_host` | `host_adapter_entrypoint_source_implemented_owner_evidence_required_not_runtime_executed_or_target_host_qualified` | `codex-rs/hepta-agentd/src/plasticity_host.rs` | 2 |
| `agentd_owner_evidence_resolution` | `host_enforced_typed_owner_evidence_resolution_concrete_deployment_adapters_required` | `codex-rs/hepta-agentd/src/plasticity_host.rs` | 3 |
| `topology_governed_admission` | `source_implemented_typed_writer_handoff_validated` | `codex-rs/hepta-plasticity/src/topology_governance.rs` | 2 |
| `durable_topology_registry` | `source_implemented_anchored_governed_topology_registry` | `codex-rs/hepta-plasticity/src/topology_registry.rs` | 1 |
| `authenticated_topology_product_composition` | `adapter_implemented_called_by_agentd_host_entrypoint_not_target_host_qualified` | `codex-rs/hepta-intelligence/src/topology_product.rs` | 2 |
| `agentd_topology_host` | `host_adapter_entrypoint_source_implemented_external_anchor_not_runtime_executed_or_target_host_qualified` | `codex-rs/hepta-agentd/src/topology_plasticity_host.rs` | 2 |
| `structural_canary_controller` | `source_implemented_durable_candidate_plan_history_bound_observation_only_no_topology_apply_authority` | `codex-rs/hepta-plasticity/src/topology_canary.rs` | 6 |

### Repository-controlled gaps

- Run exact-head and deterministic synthetic-merge compilation, tests, lint, document verification and Lane F qualification for this final source/document head.
- Bind PlasticityOwnerEvidenceResolverV1 to concrete authoritative owner-store adapters in the selected deployment and exercise freshness/provenance failures before changing productionImplementation or productExecutionProved.

### External evidence gates

- independent semantic and security review
- target-host product execution, concrete owner-evidence adapter qualification and telemetry
- operator acceptance and incident-recovery exercise
- real bounded structural canary execution, promotion, activation and release

<!-- END GENERATED IMPLEMENTATION STATUS -->

## Status matrix

| Capability | Status | Native / composed surface |
| --- | --- | --- |
| Parameter V2 canonical proposal envelope | **Implemented** | `codex-rs/hepta-plasticity/src/parameter_v2.rs` |
| Deterministic generator-relative candidate completeness | **Implemented** | `generate_parameter_candidates_v3` in `generator_v3.rs` |
| Typed parameter mutation policy / protected surfaces | **Implemented** | `ParameterMutationPolicyV1` in `parameter_mutation_policy_v1.rs` |
| Artifact/window-bound content candidate identity | **Implemented** | `generator_v3.rs` and `topology_v2.rs` |
| Per-layer/global parameter trust regions | **Implemented** | V2 verifier and V3 generator |
| Durable append-only proposal registry | **Implemented** | `DurableProposalRegistry` |
| Production-path anchored reopen | **Implemented seam** | `AnchoredPlasticityWriterV1` in `codex-rs/hepta-intelligence` |
| External anchor commit before adapter success | **Implemented fail-closed seam** | `PlasticityAnchorCommitterV1` |
| Signed generator authentication | **Implemented adapter** | `propose_authenticated_parameter_plasticity_v1` |
| Signed current artifact/evidence-frontier witness | **Implemented adapter** | `PlasticityAdmissionEvidenceV1` |
| Typed owner-evidence resolution boundary | **Implemented host-enforced seam; concrete deployment adapters required** | `PlasticityOwnerEvidenceResolverV1` in Agentd |
| Cryptographically independent evaluator admission | **Implemented adapter** | existing `LearningEvidenceVerifierV1` + signed evaluation path |
| Evaluation coverage for every generated update | **Implemented adapter** | product adapter rejects missing/duplicate/unexpected evaluations |
| Product-workspace proposal adapter | **Implemented** | `codex-rs/hepta-intelligence/src/plasticity_product.rs` |
| Agentd parameter host adapter entrypoint | **Implemented source composition; not runtime-executed/target-host qualified** | `codex-rs/hepta-agentd/src/plasticity_host.rs` |
| Typed topology proposal generation | **Implemented, proposal-only** | `propose_topology_v2` in `topology_v2.rs` |
| Typed topology writer-handoff governance | **Implemented** | `topology_governance.rs` |
| Authenticated topology product admission | **Implemented** | `codex-rs/hepta-intelligence/src/topology_product.rs` |
| Durable anchored topology proposal registry | **Implemented** | `DurableTopologyProposalRegistryV1` |
| Agentd topology host adapter + external anchor/fence | **Implemented source composition; not runtime-executed/target-host qualified** | `topology_plasticity_host.rs` |
| Bounded structural canary controller | **Implemented durable-candidate/plan/history-bound observation state machine; explicit finish required; no executed canary evidence** | `StructuralCanaryControllerV1` |
| Topology application / writer handoff execution | **Target / not implemented** | intentionally no apply API |
| Weight training / installation | **Target outside this proposal engine** | no authority granted |
| Selection / activation / promotion / release | **External gate / not implemented** | explicitly denied |
| Host deployment qualification and canary | **External evidence required** | no source-only claim |

## Dependency placement

The target guide names `learning.eval`, `learning.artifacts` and `kernel.evidence` as
module-level dependencies. They are not all native Rust dependencies of the small
proposal crate, and that distinction is intentional and now explicit:

| Boundary | Implemented dependency / responsibility |
| --- | --- |
| `codex-rs/hepta-plasticity` native crate | `codex-hepta-types` only; deterministic proposal/generator/topology/registry mechanics stay authority-free |
| product-workspace adapter | `codex-hepta-intelligence-eval` and `codex-hepta-learning-ledger` authenticate generator/evaluator evidence and independent decisions |
| selected host | MUST call the product adapter, read the current `learning.artifacts` and qualification/evidence frontiers, resolve every dataset/update/modulator/eligibility/mutation-policy/per-parameter evidence digest through `PlasticityOwnerEvidenceResolverV1`, then issue the short-lived trusted Observer attestation bound by `PlasticityAdmissionEvidenceV1` |
| selected host rollback domain | MUST implement `PlasticityAnchorCommitterV1` and monotonic writer-fence issuance outside the registry rollback domain |

`codex-hepta-plasticity` itself still does not query owner stores. The source-selected
host seam is now `codex-hepta-agentd`: it recomputes the current `ArtifactRegistry`
and durable learning-ledger frontiers immediately before calling the authenticated
product adapters, requires context-bound owner evidence for every opaque learning digest and the typed mutation-policy digest, and owns separate parameter/topology anchor-fence stores. The resolver trait
has no permissive default; a selected deployment must bind it to the actual owner
stores rather than echoing caller inputs. This is a source-selected host adapter entrypoint that calls the product adapter; it is not proof that the Agentd runtime or a deployed target host has actually executed or accepted it. `productionImplementation` and `productExecutionProved` therefore remain false
until exact target-host evidence exists.

## Parameter mutation-policy ownership

The Rust `ParameterMutationPolicyV1` is an authority-free, parameter-specific
allowlist consumed by the V3 generator. It deliberately does **not** reuse the name or
claim the semantics of canonical readiness protocol `MutationGrammarManifestV1`,
which remains owned by `control.engineering`. The parameter policy becomes admissible
in the product path only because its digest is inside the generated-set digest that is
bound by current Generator and Observer attestations; constructing a local policy in
the core crate grants no authority by itself.

## Parameter generator semantics

V2 remains byte/digest compatible and still accepts caller-supplied candidate sets for
compatibility. The authenticated product adapter does not use that as its completeness
trust boundary. It passes a `ParameterGeneratorProfileV3` to the deterministic V3
generator and verifies that the submitted generated set can be reproduced exactly.

The V3 search is bounded to at most 31 update scales, 32 total candidates, 4,096
signal/scale evaluations and 256 norm layers. For every declared scale, it computes
`eligibility * modulator * learning_rate * scale` using checked Q32 arithmetic, clamps
to explicit parameter bounds, removes zero deltas, applies the same 0.5% per-layer and
0.25% global relative-L2 trust regions, then emits every unique admissible result plus
one explicit no-change candidate. Parameter and topology candidate IDs bind the
selected artifact and exact window as well as canonical candidate content, preventing
a same-delta ID from being replayed across artifact/window contexts.

This proves completeness only relative to the declared V3 generator profile. It does
not claim that the profile spans every useful update in the model's full search space.

## Authenticated product adapter

`codex-rs/hepta-intelligence/src/plasticity_product.rs` is an implemented
product-workspace adapter. It requires, before any durable proposal append:

1. exact regeneration of the V3 candidate set;
2. a `Generator` signature over the generator digest under host-owned current trust;
3. an `Observer` signature over the selected artifact, artifact-registry binding/head,
   qualification-evidence head, the canonical host-resolved owner-evidence set,
   window, generations, dataset/update/modulator/eligibility digests and generator digest;
4. signed independent evaluation for every generated update candidate;
5. one consistent authenticated evaluator identity across those evaluations;
6. exact artifact/window/generation lineage and exact durable predecessor;
7. a governed V2 `evaluation_digest` that durably binds candidate-evaluation evidence,
   Generator/Observer authentication, the owner-evidence set, generator identity and
   the current trust snapshot without changing the V2 wire schema.

The existing learning-evidence verifier enforces signer trust, signature validity,
validity window, revocation and role assignment. Product admission now requires
pairwise Generator/Observer/Evaluator separation across the verifier's principal,
credential, signing-key and controller boundaries. The ledger exposes a generic
pairwise verifier for Observer/Evaluator separation while retaining the legacy
Generator-specific verifier for compatibility. The adapter derives proposer/evaluator IDs from authenticated principals
instead of trusting caller-supplied role strings.

The durable V2 proposal now carries the governed-admission digest in its existing
`evaluation_digest` field, so registry recovery retains the authenticated admission
context instead of only the candidate-evaluation subset. The integration regression
suite exercises the complete signed adapter path with
deterministic Ed25519 fixtures and asserts rejection of a tampered artifact-frontier
witness, generator/evaluator and observer/evaluator controller collisions, owner-evidence
context substitution, and failed external-anchor persistence. These fixtures establish source behavior only; they are not proof that an
actual production host invokes the adapter or deployment evidence.

## Rollback protection

The raw proposal crate retains `DurableProposalRegistry::open` for isolated bootstrap
and compatibility. It is not accepted by the authenticated product adapter.
`AnchoredPlasticityWriterV1::bootstrap_new` accepts only a zero-length newly enrolled
file. Any reopen of acknowledged history must use `reopen_anchored` with a host-retained
`DurableRegistryAnchorV1`.

After a durable append, the adapter obtains the current registry anchor and calls the
host-owned `PlasticityAnchorCommitterV1`. **No successful adapter receipt is returned
until that external anchor commit succeeds.** If the external commit fails, the writer
is poisoned and rejects all further reads/appends through that handle. Recovery
requires reopening against independently retained acknowledged history. The host still
owns the physical independent rollback domain and monotonic writer-fence issuance;
storing the registry file and its anchor in the same rollback domain does not satisfy
this requirement.

## Topology boundary

Topology V2 creates typed Add/Remove/Replace/Split/Merge/Rewire/Retire proposals. Every
change carries migration, rollback, writer-handoff and evidence digests and is emitted
as one bounded structural update candidate plus the no-change candidate. There is no
API that applies a topology change. Runtime graph mutation remains gated on an
independently accepted migration/writer-handoff implementation and host canary.

The structural-canary source controller is constructed through a durable-bound builder that
verifies the exact governed proposal, durable append receipt and selected structural candidate.
Its plan content-binds the admission, durable sequence/frame, candidate ID, rollback,
writer-handoff set, baseline health and thresholds, and it maintains
a rolling observation-chain digest. Reaching the minimum successful-step threshold
does not auto-accept: an explicit `finish()` transition is required. This prevents a
last-observation-only receipt from being replayed across a different plan or truncated
history.

## Remaining external and composition gates

The repository now contains an Agentd source host-adapter entrypoint that supplies current owner
frontiers and independent anchor/fence services for parameter and topology proposal
persistence. The generic owner-evidence seam is source-complete, but the selected deployment must
still bind it to concrete authoritative owner-store adapters. Remaining gates are
deployment/execution evidence rather than permission to weaken that boundary:
independent semantic/security review, target-host qualification, operator recovery
exercise, real structural-canary execution, activation, promotion and release. Those
states must stay false until their own evidence exists. CI receipts must refer to the
exact source/merge candidate; source test names are not pass receipts.
