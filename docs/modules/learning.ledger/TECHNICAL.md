# learning.ledger technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.ledger`

**Owner:** `learning-platform`

**Deputy:** `cognitive-platform`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `LRN-0-CAUSAL-LEARNING-CONTRACTS`

This stable document is the implementation guide for `learning.ledger`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own causal episode, credit and unlearning lineage facts while preventing self-labelled success.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `cognitive-platform` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `store`, state model `stateful_append_only` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-learning-ledger`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-learning-ledger`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `learning.ledger`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `cognitive.types`
- `kernel.operations`

Authoritative write domains:

- `learning_episode_ledger`
- `learning_credit_ledger`
- `learning_unlearning_lineage`

Explicitly denied capabilities:

- `memory_ledger_mutation`
- `prompt_registry_mutation`
- `self_labeled_success`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `schema and migration owner`
- `transactional writer`
- `snapshot read port`
- `integrity and lineage verifier`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `ModulePort::learning.ledger::learning.eval`
- `ModulePort::learning.ledger::learning.operator`
- `ModulePort::learning.ledger::utility.ndu`
- `OutcomeReceiptV1`

Consumed contracts:

- `ContextCompilationReceiptV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `IntuitionDecisionReceiptV1`
- `LegalActionCandidateSetV1`
- `ModulePort::cognitive.types::learning.ledger`
- `ModulePort::kernel.operations::learning.ledger`
- `ModulePort::platform.types::learning.ledger`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `PromptExerciseDecisionV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`
- `RunStartSnapshotV1`

Critical protocol schemas:

- `ContextCompilationReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `IntuitionDecisionReceiptV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LegalActionCandidateSetV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `OutcomeReceiptV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `PromptExerciseDecisionV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.ledger.md#8-current-native-implementation) identifies the actual state owner, persistent surfaces and lock/transaction boundary. Product composition uses `LedgerWriter`; it consumes either `DurableLedger` or `SegmentedLedger`, one `ActivatedLearningTrustV1`, and a separately durable `LedgerWitnessStore`. The writer owns the backend handle while composed, so the same caller cannot bypass authenticated V2 admission through a raw append surface.

One append transaction prepares and validates the full semantic event, compares the exact predecessor, writes one canonical frame, syncs the ledger, publishes the in-memory state, then advances and syncs the independent witness before returning success. Atomic conserved credit is one `CreditBatchV2` event. Outcome correction accepts only the current same-episode predecessor head, so a fork, stale branch or cycle cannot commit. Segment rotation runs through `LedgerWriter::rotate_segment` and witnesses the new topology before reporting success.

Legacy `LearningLedger`, `DurableLedger`, `SegmentedLedger` and `DurableLearningJournal` APIs remain readable compatibility/testing surfaces. New composed callers use `LedgerWriter`; compatibility availability is not permission to create a second production writer.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.ledger.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.ledger.md).

Semantic rejection writes no bytes. Ledger I/O uncertainty poisons the backend. If the ledger frame is durable but independent witness persistence is uncertain, `LedgerWriter` returns `IndeterminateAfterLedgerCommit`; reconciliation reuses the original identity, predecessor and digest. A failed anchored recovery never falls back to an unanchored open. A verified rebuildable index may accelerate lookup, but mismatch discards the index and falls back to canonical replay.

Logical revocation and `UnlearningLineageEventV1` preserve audit bytes while excluding the source and causal descendants from the active projection. They do not prove physical erasure, backup deletion or parameter unlearning. A source library or fixture cannot stand in for host-owned physical durability, backup erasure or external reconciliation.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `candidate_set_omission`
- `credit_double_count`
- `delayed_reward_misattribution`
- `policy_self_labels_outcome`
- `prompt_delivery_misattribution`
- `propensity_falsification`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.ledger.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-learning-ledger/src/lib.rs](../../../codex-rs/hepta-learning-ledger/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Use `LedgerWriter` for composed writes. The writer combines the native durable backend, activated signer distribution and independently retained `LedgerWitnessStore`. Inspect and reopen existing state before admitting new records; failure of anchored recovery is not permission to fall back to unanchored opening. Segment rotation, retention and backup must preserve both record and topology frontiers. Host directory synchronization, witness isolation, encryption and physical durability remain deployment-owner obligations.

`LedgerIndexCheckpointV1` is rebuildable acceleration state. It binds the exact ledger anchor, record index, active projection, correction heads and revocation/unlearning frontier and is verified by full deterministic regeneration before use.

Current operating and state-format references:

- [codex-rs/hepta-learning-ledger/DURABLE.md](../../../codex-rs/hepta-learning-ledger/DURABLE.md).
- [codex-rs/hepta-learning-ledger/LOCK_OWNERSHIP.md](../../../codex-rs/hepta-learning-ledger/LOCK_OWNERSHIP.md).
- [codex-rs/hepta-learning-ledger/INSPECTION.md](../../../codex-rs/hepta-learning-ledger/INSPECTION.md).
- [codex-rs/hepta-learning-ledger/NATIVE_MAPPING.md](../../../codex-rs/hepta-learning-ledger/NATIVE_MAPPING.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-learning-ledger/src/durable_tests.rs](../../../codex-rs/hepta-learning-ledger/src/durable_tests.rs); durable commit/recovery and legacy compatibility.
- [codex-rs/hepta-learning-ledger/src/ledger_tests.rs](../../../codex-rs/hepta-learning-ledger/src/ledger_tests.rs); correction-head, atomic-credit and unlearning non-resurrection invariants.
- [codex-rs/hepta-learning-ledger/src/production_tests.rs](../../../codex-rs/hepta-learning-ledger/src/production_tests.rs); signed production writer, independent witness, derived dataset freeze and reopen.
- [codex-rs/hepta-learning-ledger/src/witness_tests.rs](../../../codex-rs/hepta-learning-ledger/src/witness_tests.rs); independent witness recovery and monotonic frontier checks.
- [codex-rs/hepta-learning-ledger/src/trust_distribution_tests.rs](../../../codex-rs/hepta-learning-ledger/src/trust_distribution_tests.rs); monotonic signer-distribution rotation.
- [codex-rs/hepta-learning-ledger/src/protocol_tests.rs](../../../codex-rs/hepta-learning-ledger/src/protocol_tests.rs); registered protocol round trips and deny-unknown decoding.
- [codex-rs/hepta-learning-ledger/src/checkpoint_tests.rs](../../../codex-rs/hepta-learning-ledger/src/checkpoint_tests.rs); content-addressed index verification and bounded lookup.
- [codex-rs/hepta-learning-ledger/src/causal_v2_tests.rs](../../../codex-rs/hepta-learning-ledger/src/causal_v2_tests.rs); pure V2 validation compatibility.

In `codex-rs`, run `just test -p codex-hepta-learning-ledger`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.ledger.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`

The bootstrap package is `LRN-0-CAUSAL-LEARNING-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition, qualification, host establishment and release are separate dimensions and must not be collapsed into one status.

At the source level, the module now contains the production-facing writer, authenticated durable decision/outcome/credit/unlearning facts, ledger-derived dataset freeze, versioned trust activation, independent witness, canonical protocol adapters and verifiable index checkpoint. The existing evaluated-shadow qualification consumer is source-composed through `LedgerWriter`.

This does **not** establish a live product caller or production writer deployment. The selected host must still provide current trust-distribution transport/key custody, exclusive physical file/directory ownership, independent witness placement, live outcome observers and target-host measurements. Exact-candidate CI is qualification evidence only when the corresponding run passes; independent acceptance, activation, canary, selection, promotion and release remain externally governed.

For `learning.ledger`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `LRN-0-CAUSAL-LEARNING-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `learning-platform` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-learning-ledger/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- Activation predecessors:
- `DOC-2-DEFAULT-BRANCH-SELECTION`
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
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `LRN-1-DURABLE-EPISODE-LEDGER`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-learning-ledger/**`
- Development predecessors:
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `MEM-1-STORE`
- Activation predecessors:
- `MEM-1-STORE`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
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
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.ledger` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `CandidateSetCompletenessReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `ModulePort::learning.ledger::learning.eval`
- `ModulePort::learning.ledger::learning.operator`
- `ModulePort::learning.ledger::utility.ndu`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`

**Consumed contracts:**
- `ContextCompilationReceiptV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `IntuitionDecisionReceiptV1`
- `LegalActionCandidateSetV1`
- `ModulePort::cognitive.types::learning.ledger`
- `ModulePort::kernel.operations::learning.ledger`
- `ModulePort::platform.types::learning.ledger`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `PromptExerciseDecisionV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`
- `RunStartSnapshotV1`

**Typed protocols:**
- `CandidateSetCompletenessReceiptV1`
- `ContextCompilationReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `IntuitionDecisionReceiptV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LegalActionCandidateSetV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `PromptExerciseDecisionV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`
- `RunStartSnapshotV1`

**Owned data domains:**
- `candidate_set_completeness_receipt_v1`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `outcome_watermark_v1`

**Read data domains:**
- `cross_owner_outbox`
- `ndu_update_receipt_v1`
- `operation_ledger`

**Work packages:**
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`

**Owned threats:**
- `candidate_set_omission`
- `credit_double_count`
- `delayed_reward_misattribution`
- `policy_self_labels_outcome`
- `prompt_delivery_misattribution`
- `propensity_falsification`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.ledger` to primary lane `LANE-E-LEARNING`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-OBJ`](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)
- [`RDY-NEU`](../../readiness/NEURON_RUNTIME_EXECUTION.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `EvaluationPlanV1`
- `NduIterationReceiptV1`
- `NeuronTickReceiptV1`
- `ObjectiveCompileReceiptV1`
- `ObjectiveConflictReceiptV1`
- `ParallelLaneEnvelopeV1`
- `UtilityContributionV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.ledger` is implemented by work package `LRN-0-CAUSAL-LEARNING-CONTRACTS` in:

- `codex-rs/hepta-learning-ledger`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml` and the ledger/Lane-E/Lane-F workflows, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. The native source now includes `LedgerWriter`, `LedgerWitnessStore`, `ActivatedLearningTrustV1`, registered protocol adapters and `LedgerIndexCheckpointV1`. This receipt is source implementation evidence only; the exact PR head must still pass current CI before source qualification is claimed. It grants no live product-writer deployment, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
