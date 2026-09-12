# learning.plasticity technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.plasticity`

**Owner:** `learning-platform`

**Deputy:** `architecture`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `PLS-1-PARAMETER-PLASTICITY`

This stable document is the implementation guide for `learning.plasticity`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Generate governed parameter and topology proposals without runtime topology mutation or self-promotion.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `architecture` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `qualification`, kind `proposal_engine`, state model `stateful_shadow` and architecture role `slow_learner` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-plasticity`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-plasticity`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `learning.plasticity`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `learning.eval`
- `learning.artifacts`
- `kernel.evidence`

Authoritative write domains:

- `plasticity_proposal_registry`

Explicitly denied capabilities:

- `runtime_topology_mutation`
- `authority_mutation`
- `self_promotion`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `evidence loader`
- `candidate generator`
- `constraint filter`
- `proposal registry writer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::plasticity_proposal_registryV1`
- `PlasticityProposalV1`
- `TopologyProposalV1`

Consumed contracts:

- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `ModulePort::kernel.evidence::learning.plasticity`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.eval::learning.plasticity`

Critical protocol schemas:

- `TopologyProposalV1`

### Internal proposal version boundary

The crate's historical `hepta.plasticity.proposal.v1` record is not the canonical JSON `PlasticityProposalV1`. Explicit version dispatch preserves it for bounded read-only inspection only. Its stored shape omitted a value that participated in its digest, so readers cannot claim full digest reconstruction. Legacy proposal creation, registry append and automatic migration fail closed. Version/payload mismatch and unknown versions are rejected; no V1 record is relabeled or synthesized as V2.

All new writes use the internal, parameter-only `ParameterProposalV2` profile registered in `docs/learning/LEARNING_SYSTEM.json` and specified in `docs/learning/NEURAL_BIOMIMICRY_SPEC.md`. It binds proposal/proposer/evaluator ID strings, the selected artifact digest, window ID and digest, exact-successor generations, dataset, update rule, modulator, modulator broadcast, eligibility, evaluation and rollback-predecessor digests, the artifact-bound norm profile, every caller-supplied candidate and computed metric. These are deterministic integrity bindings over supplied values, not authentication of the external facts those values name. The record contains no topology delta, chosen-candidate field, activation, selection or promotion claim.

Each bounded caller-supplied candidate set contains `1..32` candidates, at most 4,096 total deltas and exactly one explicit no-change candidate. The crate proves only structural completeness of that supplied set; it cannot prove that the set is complete relative to a generator or search space. The set is one proposal envelope, not several final proposals. Parameter IDs are unique within a candidate, updates are nonzero and bounded, and candidate/delta/layer order is canonical. Norm profiles contain `1..256` layers. The registry reserves one slot per `(selected_artifact_digest, window_id)` and caps configured capacity at 4,096 records; a changed window digest or other semantic drift in an occupied slot conflicts, while an identical replay is idempotent and consumes no additional capacity.

The norm profile uses squared L2 Q64 numerators and nonzero per-layer baseline squared L2 Q64 denominators. The checked sum of every declared layer denominator is the global denominator. Per-layer relative norm is limited to `5000 ppm` and aggregate relative norm to `2500 ppm`, using exact squared-ratio comparisons. Because the aggregate is energy-weighted across the complete profile, a small layer may pass the global gate while failing its own gate; both checks are required. The crate binds but cannot authenticate the caller-supplied artifact profile; artifact/window/dataset/update/modulator/eligibility/evaluation/per-delta evidence digest provenance, freshness or completeness; or independent identities merely from unequal proposer/evaluator ID strings. Independent consumers must verify all of those facts before selection or acceptance, neither of which this record authorizes.

Golden fixtures `PLASTICITY-V1-GV-001` and `PLASTICITY-V2-GV-001` fix, respectively, the 307-byte legacy digest `a143a54a94d60d2734237612f1c2e0af4b4d986ea52efa6099765b83442dedb4` and the 898-byte V2 digest `e2ecdc9e0fd3278865665a2b0b168a3048919e86e8979e2e90bc6e5db9ab357c`. The V2 artifact norm-profile digest is `d31bd6f69d36817557272d747e5209d431e3ef3058e6f415dc57da4f8f98fb97`. Tests use these as hard-coded independent oracles and assert deny-all authority.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `plasticity_proposal_registry`

Read-only data dependencies:

- `learning_artifact_registry`
- `operator_sensor_core_registry`
- `qualification_evidence`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `topology_self_activation`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Candidate-only parameter/topology library with a durable proposal registry. Preserve the proposal version and exact predecessor; V1 read compatibility is not permission to emit new V1 writes. Structural split/merge/rewire needs an admitted state-migration and writer-handoff implementation before any production application.

Current operating and state-format references:

- [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs).
- [codex-rs/hepta-plasticity/src/durable_registry.rs](../../../codex-rs/hepta-plasticity/src/durable_registry.rs).
- [docs/readiness/SELF_ITERATION_EXECUTION.md](../../readiness/SELF_ITERATION_EXECUTION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-plasticity/src/durable_registry_tests.rs](../../../codex-rs/hepta-plasticity/src/durable_registry_tests.rs); named case: `append_reopen_and_anchor_preserve_exact_record`.
- [codex-rs/hepta-plasticity/src/lib_tests.rs](../../../codex-rs/hepta-plasticity/src/lib_tests.rs); named case: `legacy_v1_is_explicit_read_only_and_never_upconverted`.

In `codex-rs`, run `just test -p codex-hepta-plasticity`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `PLS-1-PARAMETER-PLASTICITY`
- `PLS-2-TOPOLOGY-PROPOSAL`
- `PLS-3-BOUNDED-STRUCTURAL-CANARY`

The bootstrap package is `PLS-1-PARAMETER-PLASTICITY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `learning.plasticity`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `PLS-1-PARAMETER-PLASTICITY`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-plasticity/**`
- Development predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`
- Activation predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- `bounded_parameter_delta`
- `trust_region`
- `no_current_run_mutation`
- `signed_artifact`
- `rollback`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `PLS-2-TOPOLOGY-PROPOSAL`

- State: `planned`; priority: `4`; parallel class: `serial_governance`.
- Owner/deputy: `learning-platform` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-plasticity/**`
- `qa/learning/topology/**`
- Development predecessors:
- `PLS-1-PARAMETER-PLASTICITY`
- `PIM-3-FACTOR-EVOLUTION`
- `ECP-1-ENGINEERING-CONTROL-PLANE`
- Activation predecessors:
- `PLS-1-PARAMETER-PLASTICITY`
- `PIM-3-FACTOR-EVOLUTION`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- `add_split_merge_retire_rewire`
- `capability_typing`
- `lesion_and_ablation`
- `resource_and_security_review`
- `no_runtime_graph_mutation`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `PLS-3-BOUNDED-STRUCTURAL-CANARY`

- State: `planned`; priority: `4`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-plasticity/**`
- `qa/learning/structural-canary/**`
- Development predecessors:
- `PLS-2-TOPOLOGY-PROPOSAL`
- `P0.9-EXTERNAL-GATES`
- `PLS-1-PARAMETER-PLASTICITY`
- Activation predecessors:
- `PLS-2-TOPOLOGY-PROPOSAL`
- `P0.9-EXTERNAL-GATES`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- `signed_topology_snapshot`
- `shadow`
- `bounded_canary`
- `kill_switch`
- `operator_acceptance`
- `rollback_rehearsal`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.plasticity` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `DomainRead::plasticity_proposal_registryV1`
- `IterationCandidateV1`
- `PlasticityProposalV1`
- `TopologyProposalV1`

**Consumed contracts:**
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `IterationEnvelopeV1`
- `ModulePort::kernel.evidence::learning.plasticity`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.eval::learning.plasticity`
- `NeuronCheckpointV1`
- `RandomStreamManifestV1`

**Typed protocols:**
- `IterationCandidateV1`
- `IterationEnvelopeV1`
- `NeuronCheckpointV1`
- `PlasticityProposalV1`
- `RandomStreamManifestV1`
- `TopologyProposalV1`

**Owned data domains:**
- `iteration_candidate_v1`
- `plasticity_proposal_registry`
- `plasticity_proposal_v1`
- `topology_proposal_v1`

**Read data domains:**
- `iteration_envelope_v1`
- `learning_artifact_registry`
- `neuron_checkpoint_v1`
- `operator_sensor_core_registry`
- `qualification_evidence`
- `random_stream_manifest_v1`

**Work packages:**
- `PLS-1-PARAMETER-PLASTICITY`
- `PLS-2-TOPOLOGY-PROPOSAL`
- `PLS-3-BOUNDED-STRUCTURAL-CANARY`

**Owned threats:**
- `topology_self_activation`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.plasticity` to primary lane `LANE-F-ADAPTIVE-POLICY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `CandidateLineageV1`
- `MutationGrammarManifestV1`
- `RetentionSliceReceiptV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.plasticity` is implemented by work package `PLS-1-PARAMETER-PLASTICITY` in:

- `codex-rs/hepta-plasticity`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
