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

- Product caller: `agentd_process_bootstrap_and_named_learning_producer_source_composed_self_iteration_trigger_not_product_composed_or_target_host_qualified`
- Production writer: `agentd_append_only_parameter_and_topology_anchor_fence_journal_plus_final_use_runtime_topology_executor_source_implemented_target_host_unproved`
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
| `durableproposalregistry` | `source_implemented_anchored_plus_explicit_zero_complete_frame_unacknowledged_bootstrap_recovery` | `codex-rs/hepta-plasticity/src/durable_registry.rs` | 2 |
| `authenticated_product_composition` | `adapter_implemented_called_by_long_lived_agentd_owner_pairwise_roles_and_durable_no_change_terminal_not_target_host_qualified` | `codex-rs/hepta-intelligence/src/plasticity_product.rs` | 6 |
| `anchored_product_writer` | `adapter_implemented_agentd_external_anchor_host_not_target_host_qualified` | `codex-rs/hepta-intelligence/src/plasticity_product.rs` | 2 |
| `parameter_mutation_policy` | `source_implemented_typed_parameter_projection_bound_to_control_engineering_mutation_grammar` | `codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs` | 2 |
| `agentd_process_bootstrap` | `source_implemented_child_process_reconstructs_owner_native_stores_from_independent_receipts_not_target_host_qualified` | `codex-rs/hepta-agentd/src/plasticity_process_bootstrap.rs` | 3 |
| `agentd_plasticity_runtime_owner` | `named_agentd_runtime_bootstrap_creates_long_lived_owner_and_state_held_producer_generation_fenced_bounded_queue_restart_reconcile_tested_not_target_host_qualified` | `codex-rs/hepta-agentd/src/plasticity_runtime.rs` | 2 |
| `agentd_named_parameter_submission` | `named_non_test_agentd_learning_producer_source_implemented_calls_state_submission_final_owner_revalidation_not_target_host_executed_or_qualified` | `codex-rs/hepta-agentd/src/plasticity_learning_producer.rs` | 1 |
| `agentd_named_topology_submission` | `named_non_test_agentd_learning_topology_producer_source_implemented_calls_state_submission_final_owner_revalidation_not_target_host_executed_or_qualified` | `codex-rs/hepta-agentd/src/plasticity_learning_producer.rs` | 1 |
| `agentd_parameter_host` | `host_entrypoint_called_by_long_lived_agentd_owner_with_real_append_ack_crash_registry_only_rollback_rejection_not_target_host_qualified` | `codex-rs/hepta-agentd/src/plasticity_host.rs` | 4 |
| `agentd_owner_evidence_resolution` | `host_enforced_live_frontier_exact_signal_value_owner_allowlist_and_dynamic_ndu_neuron_broadcast_resolution` | `codex-rs/hepta-agentd/src/plasticity_host.rs` | 5 |
| `concrete_owner_evidence_adapters` | `dataset_policy_ndu_neuron_broadcast_and_parameter_signal_adapters_bind_live_frontiers_and_exact_values_fail_closed` | `codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs` | 5 |
| `topology_governed_admission` | `source_implemented_typed_writer_handoff_validated` | `codex-rs/hepta-plasticity/src/topology_governance.rs` | 2 |
| `durable_topology_registry` | `source_implemented_anchored_plus_explicit_zero_complete_frame_unacknowledged_bootstrap_recovery` | `codex-rs/hepta-plasticity/src/topology_registry.rs` | 2 |
| `authenticated_topology_product_composition` | `adapter_implemented_called_by_agentd_host_entrypoint_not_target_host_qualified` | `codex-rs/hepta-intelligence/src/topology_product.rs` | 2 |
| `agentd_topology_host` | `host_entrypoint_called_by_long_lived_agentd_owner_external_anchor_not_target_host_qualified` | `codex-rs/hepta-agentd/src/topology_plasticity_host.rs` | 3 |
| `agentd_anchor_fence_journal` | `source_implemented_append_only_checksum_journal_crash_tail_repair_monotonic_generation_fences_and_safe_bootstrap_resume` | `codex-rs/hepta-agentd/src/plasticity_anchor_journal.rs` | 3 |
| `structural_canary_controller` | `source_implemented_durable_candidate_plan_history_bound_observation_only_no_topology_apply_authority` | `codex-rs/hepta-plasticity/src/topology_canary.rs` | 6 |
| `authenticated_structural_canary_observation` | `source_implemented_observer_signature_binds_exact_plan_and_observation_no_topology_apply_authority` | `codex-rs/hepta-intelligence/src/topology_canary_product.rs` | 1 |
| `runtime_topology_execution` | `source_implemented_external_final_use_exact_handoff_migration_owner_and_live_cns_replacement_not_target_host_qualified` | `codex-rs/hepta-runtime/src/lib.rs` | 3 |
| `runtime_topology_recovery` | `source_implemented_external_recovery_final_use_exact_handoff_migration_owner_and_stopped_quarantined_forward_recovery_not_target_host_qualified` | `codex-rs/hepta-runtime/src/lib.rs` | 1 |
| `runtime_structural_canary_fault_rollback` | `qualification_composed_live_apply_with_migration_forced_stopped_host_fault_distinct_recovery_final_use_with_migration_rollforward_and_authenticated_observer_receipt_not_target_host_qualified` | `codex-rs/hepta-runtime/src/lib.rs` | 1 |

### Repository-controlled gaps

- Compose a real non-test control.engineering/self-iteration coordinator that submits frozen, independently evaluated next-generation parameter/topology requests through AgentdLearningPlasticityProducerV1; the repository now has process bootstrap, the named producer and lifetime E2E, but IterationEnvelopeV1 still has no production caller.
- Run exact-head and deterministic synthetic-merge compilation, tests, strict lint, document verification, Agentd process qualification, Lane F qualification and the live-runtime structural-canary regression for this final source/document head.
- Execute exact unified-candidate descriptor recovery, proposal lifetime and independent live-topology canary tests.

### External evidence gates

- independent semantic and security review
- target-host execution with the anchor/fence journal placed in a rollback domain physically independent from each proposal registry, plus crash/recovery telemetry
- operator acceptance and incident-recovery exercise
- target-host topology application with production telemetry and a forced-fault rollback/reconciliation canary; the repository now contains a live-runtime source qualification but not deployment evidence
- promotion, activation and release

<!-- END GENERATED IMPLEMENTATION STATUS -->

## Status matrix

| Capability | Status | Native / composed surface |
| --- | --- | --- |
| Parameter V2 canonical proposal envelope | **Implemented** | `codex-rs/hepta-plasticity/src/parameter_v2.rs` |
| Deterministic generator-relative candidate completeness | **Implemented** | `generate_parameter_candidates_v3` in `generator_v3.rs` |
| Typed parameter mutation policy / protected surfaces | **Implemented; canonical grammar-bound** | `ParameterMutationPolicyV1` binds the control.engineering-owned `MutationGrammarManifestV1.semanticDigest` |
| Artifact/window-bound content candidate identity | **Implemented** | `generator_v3.rs` and `topology_v2.rs` |
| Per-layer/global parameter trust regions | **Implemented** | V2 verifier and V3 generator |
| Durable append-only proposal registry | **Implemented** | `DurableProposalRegistry` |
| Production-path anchored reopen | **Implemented seam** | `AnchoredPlasticityWriterV1` in `codex-rs/hepta-intelligence` |
| External anchor commit before adapter success | **Implemented fail-closed seam** | `PlasticityAnchorCommitterV1` |
| Append-only host anchor/fence journal | **Implemented source composition** | shared Agentd `AdaptiveAnchorJournalV1`; checksum frames, crash-tail repair, monotonic generation fences |
| Signed generator authentication | **Implemented adapter** | `propose_authenticated_parameter_plasticity_v1` |
| Signed current artifact/evidence-frontier witness | **Implemented adapter** | `PlasticityAdmissionEvidenceV1` |
| Typed owner-evidence resolution boundary | **Implemented with live-frontier/value binding across Dataset, Policy, NDU modulator, broadcast policy, neuron eligibility and exact parameter signals** | `ConcretePlasticityOwnerEvidenceResolverV1`, `PlasticityDynamicOwnerEvidenceResolverV1` and `PlasticityOwnerEvidencePolicyV1` in Agentd |
| Cryptographically independent evaluator admission | **Implemented adapter** | existing `LearningEvidenceVerifierV1` + signed evaluation path |
| Evaluation coverage for every generated update | **Implemented adapter** | product adapter rejects missing/duplicate/unexpected evaluations |
| Product-workspace proposal adapter | **Implemented; update and independently-attested no-admissible-update terminal paths are durable** | `codex-rs/hepta-intelligence/src/plasticity_product.rs` |
| Agentd parameter host adapter entrypoint | **Implemented and called by the long-lived Agentd plasticity owner; not target-host executed/qualified** | `codex-rs/hepta-agentd/src/plasticity_host.rs` |
| Typed topology proposal generation | **Implemented, proposal-only** | `propose_topology_v2` in `topology_v2.rs` |
| Typed topology writer-handoff governance | **Implemented** | `topology_governance.rs` |
| Authenticated topology product admission | **Implemented** | `codex-rs/hepta-intelligence/src/topology_product.rs` |
| Durable anchored topology proposal registry | **Implemented** | `DurableTopologyProposalRegistryV1` |
| Agentd topology host adapter + external anchor/fence | **Implemented and called by the long-lived Agentd plasticity owner; not target-host executed/qualified** | `topology_plasticity_host.rs` |
| Process-safe Agentd plasticity bootstrap | **Implemented source composition; child process reconstructs owner-native stores from independent receipts; target-host execution unproved** | `load_plasticity_process_bootstrap_v1` + `--plasticity-bootstrap-descriptor` |
| Long-lived Agentd plasticity owner | **Implemented source composition; bounded queue, generation/readiness fenced, no ambient writer fallback** | `PlasticityRuntimeOwnerV1` in `hepta-agentd/src/plasticity_runtime.rs` |
| Named Agentd parameter submission | **Implemented named non-test producer source boundary; target-host execution still unproved** | `AgentdLearningPlasticityProducerV1::submit_parameter` → `AgentdState::submit_parameter_plasticity_v1` |
| Named Agentd topology submission | **Implemented through the same state-held producer/long-lived owner; target-host execution still unproved** | `AgentdLearningPlasticityProducerV1::submit_topology` → `AgentdState::submit_topology_plasticity_v1` |
| Bounded structural canary controller | **Implemented durable-candidate/plan/history-bound observation state machine; explicit finish required; no executed canary evidence** | `StructuralCanaryControllerV1` |
| Authenticated structural-canary observation | **Implemented source boundary; every safety/lineage/rollback/health assertion is Observer-signed before state transition** | `observe_authenticated_structural_canary_v1` in `hepta-intelligence` |
| Topology application / migration / writer handoff execution | **Implemented in the external runtime owner; plasticity itself remains proposal-only** | `codex-hepta-runtime::HeptaRuntime::apply_governed_topology` requires exact governed handoff + plan-bound `RuntimeTopologyMigrationOwnerV1` + single-use `FinalUseAuthority` |
| Weight training / installation | **Target outside this proposal engine** | no authority granted |
| Selection / activation / promotion / release | **External gate / not implemented** | explicitly denied |
| Live-runtime forced-fault rollback canary | **Repository source qualification implemented; target-host evidence still external** | actual CNS cutover → forced stopped-host fault → separately authorized recovery generation → Observer-signed canary receipt |
| Host deployment qualification and canary | **External evidence required** | no source-only claim |

## Dependency placement

The target guide names `learning.eval`, `learning.artifacts` and `kernel.evidence` as
module-level dependencies. They are not all native Rust dependencies of the small
proposal crate, and that distinction is intentional and now explicit:

| Boundary | Implemented dependency / responsibility |
| --- | --- |
| `codex-rs/hepta-plasticity` native crate | `codex-hepta-types` only; deterministic proposal/generator/topology/registry mechanics stay authority-free |
| product-workspace adapter | `codex-hepta-intelligence-eval` and `codex-hepta-learning-ledger` authenticate generator/evaluator evidence and independent decisions |
| Agentd process bootstrap | `--plasticity-bootstrap-descriptor` reconstructs the long-lived owner from independently witnessed artifact/ledger/neuron/NDU/trust/registry inputs; absence of the explicit descriptor leaves plasticity disabled |
| selected self-iteration coordinator | **Not product-composed yet.** A future non-test `control.engineering`/self-iteration caller must submit already frozen and independently evaluated next-generation requests through `AgentdLearningPlasticityProducerV1`; turn/automation paths must not synthesize this trigger |
| selected host / learning owner | `AgentdLearningPlasticityProducerV1` exposes the bounded parameter/topology submission boundary; the long-lived owner MUST read current `learning.artifacts` and qualification/evidence frontiers, resolve every dataset/update/modulator/eligibility/mutation-policy/per-parameter evidence digest through `PlasticityOwnerEvidenceResolverV1`, and verify short-lived trusted Observer/Evaluator evidence before durable append |
| selected host rollback domain | MUST implement `PlasticityAnchorCommitterV1` and monotonic writer-fence issuance outside the registry rollback domain |

`codex-hepta-plasticity` itself still does not query owner stores. The source-selected
host is now a long-lived `PlasticityRuntimeOwnerV1` supervised by the real Agentd
`runtime.rs` task set. It exclusively retains the proposal writers, external
anchor/fence stores, learning-evidence verifier, ArtifactRegistry, DurableLedger and
owner-evidence resolver behind a bounded typed channel. `AgentdLearningPlasticityProducerV1` is the named non-test in-process learning producer retained by `AgentdState`. It holds only the bounded `PlasticityRuntimeHandleV1`; it never receives a writer, anchor store, trust root or owner-evidence store. `AgentdState::submit_parameter_plasticity_v1` and `submit_topology_plasticity_v1` both route through this producer, and the lifetime E2E exercises first-write plus anchored-restart idempotence for both paths. Target-host execution remains unproved. Every proposal is fenced on
the current Running/ready Agentd generation before it reaches the parameter or topology
host entrypoint. There is no public Agentd wire method and no ambient/default writer:
if the owner is not explicitly attached to `AgentdConfig`, plasticity remains absent.

Immediately before admission, Agentd recomputes the current `ArtifactRegistry` and
durable learning-ledger heads. Every owner-evidence query binds those heads, the exact
artifact/window/dataset context and, for `ParameterSignal`, the actual eligibility,
modulator, learning-rate and bound values consumed by the generator. The concrete
resolver verifies `DatasetSnapshotReceiptV3` against the live DurableLedger head and
eligible `Policy` artifacts against the live ArtifactRegistry head. Dynamic modulator/modulator-broadcast/eligibility/parameter-signal facts now resolve through NDU, immutable broadcast-policy artifacts and the neuron journal with exact numeric-value binding. They fail closed on stale, unavailable, rolled-back or wrong-owner state and are not reclassified as generic artifacts. A correctly signed/context-bound receipt from the wrong owner is rejected.
This source composition is not proof that a deployed target host executed or accepted
the path, so `productionImplementation` and `productExecutionProved` remain false until
exact target-host evidence exists.

## Parameter mutation-policy ownership

The Rust `ParameterMutationPolicyV1` is an authority-free, parameter-specific
executable projection consumed by the V3 generator. Canonical readiness protocol
`MutationGrammarManifestV1` remains owned by `control.engineering`; plasticity does
not mint or redefine it. Every parameter policy now carries the canonical manifest's
non-zero semantic digest, and that grammar digest participates in the policy digest,
the generated-set digest and the authenticated admission chain. The local typed rules
therefore enforce learnable-parameter allowlists/protected surfaces while preserving
one grammar authority. Constructing a local projection still grants no authority by
itself.

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
4. signed independent evaluation for every generated update candidate; if the deterministic generator produces no admissible update, a distinct Evaluator must instead sign the exact `NoAdmissibleUpdate` terminal payload and that no-change proposal is durably recorded;
5. one consistent authenticated evaluator identity across update evaluations or the authenticated no-change terminal disposition;
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
is poisoned and rejects all further reads/appends through that handle.

Agentd now persists parameter and topology fences/anchors through one shared append-only
checksum-framed journal implementation rather than overwriting the last trusted record
in place. Reopen replays every complete frame, rejects any complete invalid frame, and
repairs only an incomplete crash tail. A new registry generation advances the fence
exactly once; repeated advancement while that generation is still unacknowledged fails
closed.

The registry side has a separate unacknowledged-bootstrap recovery mode. It accepts
only a physically empty file, the exact expected header with zero complete frames, or
an incomplete first-frame crash tail. An incomplete first frame is truncated only
after the exact scope/fence/capacity header validates. Any complete unacknowledged
proposal frame returns `UnacknowledgedHistoryPresent` and leaves the bytes untouched
for explicit reconciliation. Agentd rollover/resume uses this restricted mode rather
than the raw unanchored registry open, preventing fence skipping without converting
complete unacknowledged history into accepted state. The host still owns the physical
independent rollback domain; storing the registry and journal in the same rollback
domain does not satisfy this requirement.

## Topology boundary

Topology V2 creates typed Add/Remove/Replace/Split/Merge/Rewire/Retire proposals. Every
change carries migration, rollback, writer-handoff and evidence digests and is emitted
as one bounded structural update candidate plus the no-change candidate. The
`codex-hepta-plasticity` crate itself remains proposal-only and has no apply authority.
The external `codex-hepta-runtime` owner now exposes FinalUse-gated healthy apply and
separately authorized stopped/quarantined recovery transitions that revalidate the exact
governed handoff/migration plan before replacing the live CNS generation.

The structural-canary source controller is constructed through a durable-bound builder that
reads the governed proposal and original append receipt from `DurableTopologyProposalRegistryV1`
by proposal ID, then verifies the selected structural candidate. External callers cannot
construct `StructuralCanaryPlanV1` fields directly. Its plan content-binds the admission,
durable sequence/frame, candidate ID, rollback, writer-handoff set, baseline health and
thresholds, and it maintains
a rolling observation-chain digest. Reaching the minimum successful-step threshold
does not auto-accept: an explicit `finish()` transition is required. This prevents a
last-observation-only receipt from being replayed across a different plan or truncated
history.

The product-facing observation boundary is now
`observe_authenticated_structural_canary_v1`. Its signed payload binds the exact plan
digest plus sequence, health/evidence digests, regression count, safety violation,
lineage mismatch and rollback-verification result. The host-owned
`LearningEvidenceVerifierV1` must authenticate an `Observer` before the observation is
forwarded to the controller. This removes caller-authored booleans from the plasticity product trust boundary. The
repository qualification now composes this Observer-authenticated receipt with the
external runtime owner for a source-level live cutover, forced stopped-host fault and
separately authorized recovery generation. That proves repository composition only;
target-host telemetry, rollback-domain independence and operator evidence remain external.

## Remaining external and composition gates

The named `AgentdLearningPlasticityProducerV1` now drives both `AgentdState::submit_parameter_plasticity_v1` and `submit_topology_plasticity_v1` in source, the lifetime E2E enters through that producer for both durable proposal classes, and the Agentd binary can reconstruct its owner from an explicit process bootstrap descriptor. This closes the Agentd-side caller/owner seam, but it does **not** close the upstream product trigger: `IterationEnvelopeV1` and the current `control.engineering` implementation still have no non-test production coordinator that invokes this producer after frozen independent evaluation. The repository now contains a long-lived Agentd plasticity owner that calls the
parameter/topology host entrypoints, supplies current owner frontiers and retains
independent anchor/fence seams. Dataset and immutable Policy owner adapters are concrete; NDU owns current modulator projections, neuron.runtime owns eligibility checkpoints, broadcast policy binds the low-dimensional mapping, and exact ParameterSignal evidence recomputes the consumed numeric values. These source adapters still require the selected target host to open the corresponding authoritative owner stores. The registry/anchor fault fixtures prove that a retained
external acknowledgement rejects a rolled-back proposal file, but only a target host
can prove that the journal and registry are physically placed in independent rollback
domains. Remaining gates are deployment/execution evidence rather than permission to
weaken those boundaries:
independent semantic/security review, target-host qualification, operator recovery
exercise, target-host structural-canary execution with production telemetry and operator evidence, activation, promotion and release. Those
states must stay false until their own evidence exists. CI receipts must refer to the
exact source/merge candidate; source test names are not pass receipts.
