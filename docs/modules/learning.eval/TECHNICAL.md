# learning.eval technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.eval`

**Owner:** `learning-platform`

**Deputy:** `qualification-plane`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `LRN-2-CAUSAL-EVALUATION`

This stable document is the implementation guide for `learning.eval`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

**Normative production API and ownership contract:** [`codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md`](../../../codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md). Default builds expose the recorded product runner with an independently anchored journal capability and signature-verified qualification ingress. The raw runner is crate-private unless the explicit `trusted-inprocess-eval` compatibility feature is selected. Multi-writer final-holdout ownership requires the fenced CAS contract defined there. The [recovery contract](../../../codex-rs/hepta-intelligence-eval/RECOVERY_CONTRACT.md) defines intent, publication, anchoring and restart boundaries.

## 1. Identity, mission and ownership

Perform support-aware causal and longitudinal evaluation independently from the production writer.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `qualification-plane` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `qualification`, kind `engine`, state model `stateful_shadow` and architecture role `qualification` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-intelligence-eval`

Existing declared roots at this source snapshot:

- `codex-rs/hepta-intelligence-eval`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots are materialized and have configured closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification workflows. Their presence does not prove those commands passed for the current commit. The immutable execution artifact must identify the exact commit, source tree, ordered merge parents, commands, exit codes and log/output digests. This status does not activate `learning.eval`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

The canonical delivery path is PR #1011. PR #1051 remains unmerged comparison/history material; divergent commits and checkpoint designs are not silently declared accepted. The generated source-status projection below separates lexical materialization from compiler reachability, product invocation, exact-tree execution, target-host evidence and independent acceptance.

The [Lane E matrix](../../lane-e/LANE_E_IMPLEMENTATION_MATRIX.json) retains its original closed-world `operations` source inventory: raw runner entries are classified as compatibility-only, and signed V2/V3 decisions are crate-internal primitives. These source symbols must not be interpreted as default public exports. Its `productCallsites` records identify the public recorded evaluation and archived qualification paths; the full current API and recovery mapping remains in [NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md). Source composition does not establish deployed invocation or independent acceptance.

The [implementation map](IMPLEMENTATION_MAP.json) binds its source observation to an ancestor commit and that commit's exact tree. The status verifier checks the complete fixed `codex-rs/hepta-intelligence-eval` root, including unmapped source, tests, fixtures, `Cargo.toml`, `BUILD.bazel`, new tracked files and non-ignored untracked files, together with every mapped source, test and external product caller. Any change in that scope requires a new source observation; a map-only descendant may retain the observation when all observed paths remain unchanged. The canonical archived entry `RecordedProductEvaluationRunnerV1::qualify_and_persist_with_artifacts` is mandatory in the map. These checks establish source identity without granting runtime authority or issuing acceptance.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `learning.ledger`
- `learning.artifacts`
- `kernel.evidence`

Qualification write-domain declarations in [DATA_AUTHORITY.json](../../data/DATA_AUTHORITY.json):

- `algorithm_fault_receipt_v1`
- `candidate_evaluation_receipt_v1`
- `conformance_receipt_v1`
- `ndu_well_posedness_certificate_v1`
- `operator_applicability_certificate_v1`
- `regularity_profile_v1`
- `support_audit_receipt_v1`

These are declared qualification-domain ownership responsibilities, not permission to mutate another owner's store or the production writer. Registry ownership does not prove every target operation is implemented or activated.

Explicitly denied capabilities:

- `production_write`
- `production_writer_dependency`
- `self_issued_acceptance`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bounded input stage`
- `deterministic algorithm core`
- `generation publisher`
- `checkpoint and recovery layer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Evaluate node specialization and organ cooperation on fixed external objectives and interference-safe episode/cluster units. Compare the four registered cooperation arms at equal information and total lifecycle budget; evaluate retention and structural lifecycle separately from model accuracy.

Compare no-change, cell-only, routing-only and joint updates on reusable circuits. Independently test legacy compatibility, effect-free crash recovery, unknown effects and future task benefit. See the [Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: cross-fit separation, selection/holdout leakage, sequential support, interaction ablations and future-window retention.

The shared contract and record design are in [DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md); [organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary. This target does not change the current native implementation, source status or product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Separate expressivity, stability, learning, unseen-task adaptation and scaling hypotheses. Use withheld tasks/scales, matched search and lifecycle cost, richer-state closure controls and retained failed/plateau runs. Do not import LLM exponents or count replay steps as independent data.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md) and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Run no-sharing, Recall-only, artifact-only and both with a clean receiver and matched lifecycle budgets. Exclude test answers and all derived leakage, account for source/task interference, and measure negative transfer, poisoning, privacy and retention separately.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and [migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners) retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

The following bootstrap contract lists are retained for design lineage. The complete current registry contract, protocol and domain inventory is the exact generated registry projection below; the bootstrap subset must not be interpreted as exhaustive.

Produced bootstrap contracts:

- `EvaluationReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::learning.eval::intelligence.control`
- `ModulePort::learning.eval::learning.plasticity`
- `UnlearningComplianceReceiptV1`

Consumed bootstrap contracts:

- `BellmanOperatorArtifactV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `ModulePort::kernel.evidence::learning.eval`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.ledger::learning.eval`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `PlasticityProposalV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RegularityProfileV1`
- `TopologyProposalV1`

Critical bootstrap protocol schemas:

- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RegularityProfileV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

### Temporal evaluation digest compatibility

The internal `TemporalEvaluationPlan` composite digest follows the canonical machine-readable profile in `docs/learning/LEARNING_SYSTEM.json` and the normative algorithm text in `docs/learning/CAUSAL_LONGITUDINAL_SPEC.md`. The plan preimage is SHA-256 over the unframed `hepta.ope.temporal-evaluation-plan.v1` domain followed, in order, by the framed evaluation ID, objective digest, every fold field, every OPE field and every confidence field. The stored top-level digest is excluded from its own preimage. The fold, OPE and confidence child plan digests remain independent values; the composite binds them without aliasing them.

Evaluation rejects zero or stale composite plan digests before fitting or estimation. `usize` counts are checked before canonical `u64` big-endian encoding; fixed Q32 values use signed raw `i64` big-endian bytes; IDs use `u32` big-endian UTF-8 byte length followed by exact UTF-8 bytes; digests use raw 32 bytes.

`TemporalEvaluationReceipt.evidence_digest` uses the unframed `hepta.ope.temporal-holdout-pipeline.v2` domain and binds, in order, evaluation ID, composite plan digest, objective digest, fitted model digest, fitted predictions digest and cluster-estimate evidence digest. Version 2 is not wire-compatible with the previous v1 digest preimage: historical v1 evidence stays version-tagged and cannot be reinterpreted as v2. These internal digest profiles do not create a published contract or alter the authority of `EvaluationReceiptV1` and `LongitudinalEvaluationReceiptV1`.

Canonical vector `TEMPORAL-PLAN-DIGEST-GV-001` fixes the complete 293-byte composite preimage and expected digest `dba5b45f87d6a8ef08dccfc9b2108a1456d94b226c3315777c3de2f15f4219b3`; source tests must compare against that hard-coded oracle rather than a value emitted by the implementation under test.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics where the codec is defined. Required codec tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes. Internal sealed evaluation objects are not presumed serializable merely because their digests exist.

## 6. Data authority, persistence and migrations

[DATA_AUTHORITY.json](../../data/DATA_AUTHORITY.json) declares `learning.eval` as schema owner and authoritative writer of the seven qualification domains in Section 3. [MODULES.json](../MODULES.json) simultaneously declares `writes: []` for this module. Neither registry encodes a supersession or a baseline-to-target relationship between these lists; their relation remains an explicit registry alignment obligation. The data-authority declarations do not establish an activated writer, a backing-store capability or permission to write to production or another owner's store.

Bootstrap read-only data dependencies:

- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `operator_sensor_core_registry`
- `qualification_evidence`

The complete read inventory is in the generated registry projection. Persistence implementing the data-authority declarations requires revision- or generation-bound mutations, idempotence for identical semantics and conflict rejection for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation. Actual backing stores and deployed writer bindings require their own implementation and host evidence.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

### Canonical product evaluation composition

The default product composition is `RecordedProductEvaluationRunnerV1` with `DurableProductEvaluationAttemptJournalV1`. It persists `IntentPersisted` before provider manifest lookup or final-holdout CAS, consumes through `FencedFinalHoldoutOwnerV1`, acknowledges `HoldoutConsumed`, and only then releases observations. Candidate and baseline intervals come from sealed temporal/cluster estimator receipts; product callers do not submit final `MetricGateV1` values. `ComparisonSealed` binds the complete execution before return.

Public qualification first persists the canonical typed archive and acknowledges `QualificationArtifactsPersisted`, then verifies current V2/V3 signed evidence and persists `QualificationDecided` and `PublicationPending` before publication. It records `Published` only after observing the exact durable nonzero publication result. The raw `ProductEvaluationRunnerV1` and the unarchived recorded qualification helper are not default public alternatives; the raw runner's explicit compatibility feature must be absent from the selected production build.

`LockedFileFinalHoldoutCasStoreV1` is the repository concrete cross-process CAS/replay backend. Recovery is bounded by an independently retained `FinalHoldoutCasAnchorV1`; `HoldoutFenceIssuerV1` resumes monotonic fence generation from that anchor. Cross-host deployment additionally requires a shared filesystem with qualified linearizable lock and fsync semantics.

`AnchoredProductEvaluationAttemptJournalV1` separately binds the complete attempt history to an independent anchor authority. An old complete backup is rejected, not accepted merely because its frame checksums are valid. Uncertain file or anchor acknowledgements poison the handle; recovery validates the retained prefix before adopting a committed tail. It never erases final-holdout use.

For the single-outcome receipt, `qualify_and_persist_with_artifacts` create-only persists the complete temporal receipt, qualification context, signed evidence and timing evidence before the durable `QualificationArtifactsPersisted` transition. The selected-host single- and multi-outcome methods share the module-owned canonical archive codec and bind the artifact and publication namespaces to one host identity. Public selected-host final use requires root-issued `ActivatedLearningTrustV1` and a host-sampled clock; recovery resolves current trust for each attempt. Recovery rejects a substituted host identity, reloads exact bytes, re-verifies current V2/V3 evidence and performs the first publication write only from the exact archived prewrite state. `reconcile_selected_host_publication` reads and validates an existing publication without repeating a writer call. These source APIs and their fixtures do not authenticate a real anchor authority or qualify a deployment topology.

The evaluated-shadow caller consumes the sealed `ProductQualificationReceiptV1`, rechecks current trust/dataset/candidate bindings and does not rerun low-level signed admission. Agentd also contains a request-bound consumer of the additive `ProductOutcomeQualificationReceiptV1`. Both are source compositions, not demonstrated deployment or activation.

### Measured outcome channels

`freeze_product_outcome_plan_v1` adds a complete typed measurement contract for each metric: channel identity, schema, unit, normalization, subgroup, time window, provenance commitment, input digest and both temporal plans. A maximum of 32 channels and 100,000 aggregate batch input rows is enforced before composition. Each temporal estimator retains its smaller stage-specific limits.

`FinalOutcomeHoldoutProviderV1` releases one complete channel batch after the same single authoritative final-holdout consumption. `evaluate_outcome_comparison` checks each payload and paired logged measurements, estimates channels separately, and seals the multi-outcome execution. A renamed metric cannot substitute for a new measured channel. Missing, duplicate or swapped payloads do not yield a partial qualified result. The internal carrier is not publicly extractable.

The public `qualify_outcomes_and_persist_on_selected_host` path archives the complete outcome receipt and signed context before deriving and verifying the full outcome bundle; `qualify_outcomes_and_persist` is a crate-internal composition helper. Both receipt families use the same archive and durable publication lifecycle. The signed E2E binds multi-outcome, privacy, retention and unlearning evidence; Agentd consumes the resulting sealed receipt with current owner state and signed exact-use context. A schema/provenance digest is still only a commitment, not proof of independent observation or correct normalization. Complete single- and multi-outcome selected-host archive/restart recovery is present in source. Authenticating the real measurement custodian and executing and qualifying that path on the declared target host remain separate obligations.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.eval.md#8-current-native-implementation) identifies the state owner, in-memory versus persistent surfaces, and lock/transaction boundary. The current API and recovery changes are mapped in [NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md) and the generated source inventory; an older dossier statement must not override current code. Target state-machine operations remain identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

`reconcile_pending_page` supplies bounded lexicographic discovery and advances past unresolved attempts. `recover_selected_host_pending_page` adds the persistent bounded controller and host-bound cursor; it resolves current root-activated trust and host time for each attempt. These source operations do not supply a background scheduling service or prove deployed invocation. The selected host must bind the cursor store, schedule bounded sweeps, preserve fairness and exclude concurrent recovery of a live attempt. An indeterminate journal or trust/cursor failure stops the sweep rather than continuing to mutate a poisoned handle.

## 8. Failure semantics, recovery and rollback

Use the [recovery contract](../../../codex-rs/hepta-intelligence-eval/RECOVERY_CONTRACT.md), the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.eval.md#8-current-native-implementation), and module-specific fault cases in the [implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md). A source library or fixture cannot stand in for an unimplemented durable recovery service or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

Recovery validates the complete per-attempt history, including identity, sequence, legal phases, predecessor digests, plan/holdout binding and the latest pointer. It reads authoritative holdout/publication records and mutates only the attempt journal. These operations are external-owner-read-only reconciliation, not literally read-only diagnostics.

A `QualificationArtifactsPersisted` or `QualificationDecided` attempt can resume through `recover_selected_host_qualification` or `recover_selected_host_outcome_qualification` only when its original canonical archive is recoverable. The module reconstructs the exact bundle and re-verifies current trust, expiry, revocation, scope and V3 timing before deriving the canonical publication request. A recorded decision/request must match that request exactly. The generic typed `resume_decided_qualification` and `resume_decided_outcome_qualification` methods also reverify the original receipt and signed evidence with host-owned trust; they do not authenticate a selected host or replace its root-activated clock/archive boundary. The raw post-verification publication helper stays crate-private. `PublicationPending` or `Published` is never submitted again through this path. A missing publication record for a Pending attempt may represent an unknown write and remains unresolved until authoritative submission state is known.

The attempt journal stores digests and transitions rather than duplicating large sealed objects. The host-bound artifact store persists canonical typed archives for both single- and multi-outcome receipts after `ComparisonSealed` and before decision. The selected-host restart fixtures inject acknowledgement loss, restart from the independent anchor, reject wrong host bindings, re-verify signed evidence, publish once, perform read-only publication reconciliation and restart again to validate the seven-phase history. The module-owned archive codec and cold recovery paths are source implementations; fixture presence does not establish target-host qualification or execution on the final candidate. Recovery after computation but before a recoverable archive has been durably sealed still cannot invent a result or re-release final-holdout data.

## 9. Security, privacy and threat controls

Owned threat entries:

- `catastrophic_forgetting`
- `deleted_data_resurrection`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Required negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics. Test-source existence and current execution coverage are separate facts.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [temporal_evaluation.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs), outcome contracts and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

Attempt append updates only the addressed history; replay is streaming within configured event/file limits. The repository includes the earlier 1,024-attempt/512-fence storage profile and a sustained source profile configured for 4,096 attempts, 28,672 lifecycle events and anchored close-and-reopen recovery every 128 attempts. The profile writes a checkpoint 64 attempts before each restart so recovery includes a nonempty append-only tail. Attempt checkpoint/tail recovery and holdout copy-compaction are distinct source operations and preserve their independently retained anchors. Neither source fixture is a measured qualification until it passes on the exact candidate and its logs, exit status, manifest digest and runner/toolchain identity are retained. Selected-host startup, backlog, fsync latency, memory and recovery measurements remain required on the declared topology.

## 11. Observability and operations

Independent evaluation library. Freeze the estimand, split, thresholds, nuisance-model profile and evaluator identity before final outcomes. Persist results through their declared evidence owner. A supported analytic or offline estimate does not create real future calendar windows or authorize selection.

Current operating and state-format references:

- [NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md).
- [EVIDENCE_ADMISSION.md](../../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md).
- [RECOVERY_CONTRACT.md](../../../codex-rs/hepta-intelligence-eval/RECOVERY_CONTRACT.md).
- [LEARNING_EVALUATION_EXECUTION.md](../../readiness/LEARNING_EVALUATION_EXECUTION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [closure_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/closure_tests.rs); named case: `eval_03_intersects_superiority_safety_retention_and_unlearning`.
- [lib_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/lib_tests.rs); named case: `eligible_is_not_promotion`.
- [outcome_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/outcome_tests.rs); independent per-channel intervals, complete payload binding and semantic mutation tests.
- [attempt_recovery_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/attempt_recovery_tests.rs); whole-history validation, decided recovery, cursor fairness and bounds.
- [recorded_runner_process_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/recorded_runner_process_tests.rs); seven actual child-process termination cuts.
- [selected_host_recovery_e2e.rs](../../../codex-rs/hepta-intelligence-eval/tests/selected_host_recovery_e2e.rs); complete signed artifact persistence, independent-anchor acknowledgement loss, host-binding rejection, current-signature re-verification, exactly-once publication, read-only reconciliation and second restart.
- [long_running_profile.rs](../../../codex-rs/hepta-intelligence-eval/tests/long_running_profile.rs); sustained source profile, whose execution is qualified separately.

The seven process cuts are committed consume before attempt record, consumed before release, computed before sealing, sealed before qualification, decided before pending, pending before publication, and publication committed before acknowledgement. The selected-host integration fixture adds the exact signed artifact/restart chain that the isolated publication half intentionally did not cover. Fixture presence still does not replace exact-source execution evidence or a real host.

In `codex-rs`, run `just test -p codex-hepta-intelligence-eval`. The command is a test invocation, not a stored result. Inspect exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md) separately labels target acceptance designs.

The read-only `Hepta learning.eval exact trees` workflow addresses exact source and ordered-parent merge trees. It preserves commands, exit codes, logs and artifact digests on failure and retains the 85% library coverage threshold. `Hepta learning.eval convergence` runs focused composition, API and recovery checks. `Hepta learning.eval sustained selected-host profile` executes the 4,096-attempt source profile without issuing production claims. `hepta-learning-eval-status.py verify` checks inventory/map and digest-bound technical/native projections without repairing source. Explicit authoring uses `write`; qualification must never invoke it. Python projection tests do not prove Rust compilation, source qualification, target-host acceptance or production use.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `LRN-2-CAUSAL-EVALUATION`
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`

The bootstrap package is `LRN-2-CAUSAL-EVALUATION`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Source product composition includes consumer-bound V2 admission, an evaluated-shadow consumer of the single-stream product receipt, an Agentd request-bound consumer of the multi-outcome receipt, typed outcome channels, the independently anchored recorded runner and a local selected-host source facade. These source facts do not establish deployed execution or a selected production host. Target-host composition requires an authenticated independent anchor authority, real provider, publication store, persistent recovery controller, qualified storage topology and complete host-sealed recovery for every accepted receipt family. Qualification requires current exact-candidate and ordered-parent merge execution evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `learning.eval`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `LRN-2-CAUSAL-EVALUATION`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-intelligence-eval/**`
- `qa/learning/evaluation/**`
- Development predecessors:
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- Activation predecessors:
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
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
- `support_coverage`
- `ess_ips_snips_dr`
- `cluster_or_bootstrap_ci`
- `candidate_lcb_gt_baseline_ucb`
- `subgroup_and_safety_floor`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `LONG-1-TEMPORAL-HOLDOUT`

- State: `planned`; priority: `2`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `qa/learning/longitudinal/**`
- Development predecessors:
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- Activation predecessors:
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
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
- `future_time_window`
- `distribution_shift`
- `delayed_outcome_watermark`
- `confidence_bounds`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `LONG-2-RETENTION-FORGETTING`

- State: `planned`; priority: `2`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `qa/learning/retention/**`
- Development predecessors:
- `LONG-1-TEMPORAL-HOLDOUT`
- Activation predecessors:
- `LONG-1-TEMPORAL-HOLDOUT`
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
- `old_task_holdout`
- `backward_transfer`
- `forgetting_bound`
- `adapter_retirement`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `LONG-3-UNLEARNING-NON-RESURRECTION`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `qa/learning/unlearning/**`
- `codex-rs/hepta-intelligence-eval/**`
- Development predecessors:
- `LONG-2-RETENTION-FORGETTING`
- `LRN-2-CAUSAL-EVALUATION`
- Activation predecessors:
- `LONG-2-RETENTION-FORGETTING`
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
- `lineage_complete`
- `artifact_revocation`
- `backup_restore_non_resurrection`
- `rebuild_excludes_deleted`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.eval` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `EvaluationReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::learning.eval::intelligence.control`
- `ModulePort::learning.eval::learning.plasticity`
- `NduWellPosednessCertificateV1`
- `OperatorApplicabilityCertificateV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `UnlearningComplianceReceiptV1`

**Consumed contracts:**
- `BellmanOperatorArtifactV1`
- `CandidateSetCompletenessReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `GoldenFixtureManifestV1`
- `IterationCandidateV1`
- `IterationEnvelopeV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `ModulePort::kernel.evidence::learning.eval`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.ledger::learning.eval`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NeuronCheckpointV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`
- `PlasticityProposalV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RandomStreamManifestV1`
- `TopologyProposalV1`

**Typed protocols:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `CandidateSetCompletenessReceiptV1`
- `ConformanceReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `GoldenFixtureManifestV1`
- `IterationCandidateV1`
- `IterationEnvelopeV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `NeuronCheckpointV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`
- `PlasticityProposalV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RandomStreamManifestV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

**Owned data domains:**
- `algorithm_fault_receipt_v1`
- `candidate_evaluation_receipt_v1`
- `conformance_receipt_v1`
- `ndu_well_posedness_certificate_v1`
- `operator_applicability_certificate_v1`
- `regularity_profile_v1`
- `support_audit_receipt_v1`

**Read data domains:**
- `candidate_set_completeness_receipt_v1`
- `golden_fixture_manifest_v1`
- `iteration_candidate_v1`
- `iteration_envelope_v1`
- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `ndu_coefficient_manifest_v1`
- `ndu_update_receipt_v1`
- `neuron_checkpoint_v1`
- `operator_sensor_core_manifest_v1`
- `operator_sensor_core_registry`
- `outcome_watermark_v1`
- `plasticity_proposal_v1`
- `qualification_evidence`
- `random_stream_manifest_v1`
- `topology_proposal_v1`

**Work packages:**
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `LRN-2-CAUSAL-EVALUATION`

**Owned threats:**
- `catastrophic_forgetting`
- `deleted_data_resurrection`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.eval` to primary lane `LANE-E-LEARNING`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)
- [`RDY-NEU`](../../readiness/NEURON_RUNTIME_EXECUTION.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)

Owned readiness protocols:

- `EvaluationPlanV1`
- `NduConvergenceCertificateV1`
- `RetentionSliceReceiptV1`

Consumed readiness protocols:

- `AssimilationProposalV1`
- `CandidateLineageV1`
- `EvaluatorIndependenceReceiptV1`
- `MutationGrammarManifestV1`
- `NduIterationReceiptV1`
- `NeuronRuntimeConfigV1`
- `NeuronTickReceiptV1`
- `SandboxExecutionReceiptV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-3-STATE-MIGRATION-QUALIFICATION`
- `EMB-3-HIL-SIM-TO-REAL-QUALIFICATION`

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.eval` is materialized by work package `LRN-2-CAUSAL-EVALUATION` in:

- `codex-rs/hepta-intelligence-eval`

The configured source checks include `.github/workflows/hepta-consolidated-source.yml`, the focused learning-eval convergence workflow, the exact-tree workflow and the sustained selected-host profile. Their configuration is not a passing execution receipt. Current qualification requires the final head's inventory, package tests, all-target compilation, strict Clippy, measured coverage and clean tracked state, as well as its ordered-parent merge result. Queued, cancelled, skipped or infrastructure-invalid jobs never count as passes. This source-location statement grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

<!-- BEGIN GENERATED LEARNING.EVAL SOURCE STATUS -->
### Current candidate source inventory

Canonical inventory: `docs/modules/learning.eval/CURRENT_STATUS.json`.
Inventory SHA-256: `75e4ad3b446a79674d258401ef2da2cd0de9e5512ce4c8b2f555e6ae7624ecf9`.

This block is generated from lexical source facts, not test results.
Default ingress: recorded runner with independently anchored journal capability.
Raw runner: explicit `trusted-inprocess-eval` compatibility feature only.
Recovery: durable intent, independently anchored full-history validation, bounded
cursor reconciliation and complete typed qualification artifacts.
Selected-host single- and multi-outcome artifact recovery and publication resume
are present in source, with signatures reverified before final use.
Process-kill fixture cuts: `7`; their execution is separately qualified.
Outcome source: at most `32` preregistered channels and
`100000` batch rows, with separate measured estimates.
A request-bound Agentd multi-outcome receipt consumer is present in source;
deployed execution, authenticated target-host qualification and measurement
provenance are not established by this source inventory.
Sustained profile source: `4096` attempts,
`28672` lifecycle events and anchored
restart every `128` attempts; a passing
exact-source artifact is still required.

Exact-head, ordered-parent merge, coverage and strict lint require immutable
execution artifacts. Real target-host, future-window and independent acceptance
evidence remain external. Production, activation and release claims remain false.
<!-- END GENERATED LEARNING.EVAL SOURCE STATUS -->
