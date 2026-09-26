# utility.ndu technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `utility.ndu`

**Owner:** `intelligence-platform`

**Deputy:** `learning-platform`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `NDU-0-PREFERENCE-UTILITY-CONTRACTS`

This stable document is the implementation guide for `utility.ndu`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Maintain bounded preference and recursive-utility projections for system, domain, agent and episode subjects.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `learning-platform` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `preference_utility_runtime`, state model `stateful_projection` and architecture role `preference_utility_controller` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-ndu`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-ndu`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `utility.ndu`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `cognitive.read`
- `learning.ledger`
- `learning.artifacts`

Authoritative write domains:

- `ndu_preference_projection`
- `ndu_utility_projection`

Explicitly denied capabilities:

- `hard_constraint_mutation`
- `authority_issuance`
- `physical_effect`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `preference-state reader`
- `bounded state updater`
- `recursive utility evaluator`
- `boundary-condition cache`
- `immutable numeric-registry admission adapter`
- `authenticated owner with registry-frozen production-policy identity`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Own NDU recursive-value and preference semantics plus scoped organ/cell learning boundaries. System 2 guides both actions and candidate parameter updates; it need not run a full FBSDE per cell. Provide a declared utility-to-gradient/advantage interface without becoming the tensor trainer or effect executor.

Treat circuit routing/termination and nested duration/cost as explicit control inputs. Optimize policies as well as cells without a mandatory central solve per signal or a fixed reward per visited node. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: known-value gradient direction, nonlinear-utility profile rejection, resource attribution and parent/peer version drift.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Allocate admitted additional computation against supported continuation benefit and actual cost. Separate inference and learning time; start field analysis with declared optimizer/state conditions and multidriver uncertainty. Projection, backward value and parameter gradient remain distinct.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Allocate admitted Recall/Replay/collection budgets by expected task value and coverage rather than upload count or novelty alone. Keep source truth, read/train/derived-use rights and privacy floors outside learned utility. Use actual independent outcomes, not a collector self-score.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `ModulePort::utility.ndu::control.runtime`
- `ModulePort::utility.ndu::intelligence.control`
- `ModulePort::utility.ndu::intuition.policy`
- `ModulePort::utility.ndu::prompt.optimizer`
- `NduBoundaryConditionV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`

Consumed contracts:

- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `ModulePort::cognitive.read::utility.ndu`
- `ModulePort::learning.artifacts::utility.ndu`
- `ModulePort::learning.ledger::utility.ndu`
- `ModulePort::platform.types::utility.ndu`
- `ContractRegistryV1`
- `RegisteredNumericConversionReceiptV1`
- `NduBoundaryConditionV1`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Critical protocol schemas:

- `NduBoundaryConditionV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `ndu_preference_projection`
- `ndu_utility_projection`

Read-only data dependencies:

- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `operator_sensor_core_registry`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/utility.ndu.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. `NduNumericRegistryV1` freezes one immutable platform.types registry generation and computes its canonical digest. `NduAuthenticatedOwnerV1::open_with_numeric_registry` incorporates that digest into the production-policy identity before any utility-signal admission or durable mutation. `admit_utility_signal` returns `NduRegisteredUtilitySignalV1`; an owner opened without a registry fails closed with `RegistryNotConfigured`. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/utility.ndu.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `parent_child_NDU_oscillation`
- `preference_state_goal_drift`
- `recursive_utility_instability`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-ndu/src/lib.rs](../../../codex-rs/hepta-ndu/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Embed the deterministic evaluator under a frozen objective and versioned policy. A real request-local read-only caller is established through `runtime.agentd cognitive_context -> control plan_observed_context -> evaluate_prepared_plan_with_ndu -> NDU V2 evaluator`; this does not establish the authenticated production NDU owner/caller or activate global adaptive reconfiguration. The authenticated owner now has a source-composed registered numeric-admission path: the provisioning caller supplies one immutable `NduNumericRegistryV1`, the owner freezes its digest, and each admitted utility signal carries a distinct registry-admission receipt. A plain `NumericConversionReceiptV1` is never treated as registry admission. `NduProjectionJournalV1` remains the semantic journal, while `NduProjectionStoreV1` is a crash-bounded durable-writer source candidate with exclusive writer locking, complete-image temp write + file sync, atomic rename, Unix parent-directory sync, indeterminate-handle fencing and monotonic backup restore. Neither source existence nor local qualification substitutes for governed production writer selection, registry authentication, host enrollment, retention/off-host backup policy, monitoring or target-host acceptance.

Current operating and state-format references:

- [docs/readiness/NDU_SYSTEM_EXECUTION.md](../../readiness/NDU_SYSTEM_EXECUTION.md).
- [codex-rs/hepta-ndu/RECURSIVE_UTILITY.md](../../../codex-rs/hepta-ndu/RECURSIVE_UTILITY.md).
- [codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md](../../../codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-ndu/src/covariance_tests.rs](../../../codex-rs/hepta-ndu/src/covariance_tests.rs); named case: `scaled_covariance_recovers_three_instead_of_six_and_converts_microseconds`.
- [codex-rs/hepta-ndu/src/evaluator_tests.rs](../../../codex-rs/hepta-ndu/src/evaluator_tests.rs); named case: `hard_violation_is_filtered_before_utility`.
- [codex-rs/hepta-ndu/src/projection_store_tests.rs](../../../codex-rs/hepta-ndu/src/projection_store_tests.rs); durable reopen/restore, single-writer and indeterminate-fencing cases.
- [codex-rs/hepta-ndu/src/z_conversion_tests.rs](../../../codex-rs/hepta-ndu/src/z_conversion_tests.rs); whitening-coordinate and signed-Q24 ties-to-even cases.
- [codex-rs/hepta-ndu/src/numeric_admission_tests.rs](../../../codex-rs/hepta-ndu/src/numeric_admission_tests.rs); registry-generation, normalization, axis-order and distinct-admission-receipt cases.
- [codex-rs/hepta-ndu/src/owner_tests.rs](../../../codex-rs/hepta-ndu/src/owner_tests.rs); registry-frozen authenticated owner and missing-registry rejection cases.
- [codex-rs/hepta-control-plane/src/planner_context_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_context_tests.rs) and [planner_ndu_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_ndu_tests.rs); real request-local Control caller regressions.

In `codex-rs`, run `just test -p codex-hepta-ndu`. The dedicated NDU qualification workflow also runs focused `codex-hepta-control-plane` planner-context/planner-NDU regressions so the established read-only caller cannot drift independently of the evaluator. These commands are test invocations, not stored results. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `NDU-2-AGENT-DOMAIN-HIERARCHY`

The bootstrap package is `NDU-0-PREFERENCE-UTILITY-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Current source already contains a named request-local read-only caller through Agentd and Control. Production activation is a stronger state: it composes an authenticated production NDU owner/caller through registered ports, selects the durable writer, and verifies current authority/revocation, configuration, resource, recovery and failure behavior on the target host. Read-only, shadow and qualification callers are not production activation. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion now includes the registered numeric-admission adapter and authenticated-owner integration. Request-local composition requires a named bounded caller; authenticated production composition additionally requires authenticated registry provisioning, the production owner/caller, selected writer and current authority/revocation fences. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `utility.ndu`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `NDU-0-PREFERENCE-UTILITY-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-ndu/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- Activation predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
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

#### `NDU-1-DETERMINISTIC-UTILITY-BASELINE`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-ndu/**`
- Development predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-1-OBJECTIVE-COMPILER`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- Activation predecessors:
- `OBJ-1-OBJECTIVE-COMPILER`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
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

#### `NDU-2-AGENT-DOMAIN-HIERARCHY`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-ndu/**`
- `codex-rs/hepta-control-plane/**`
- Development predecessors:
- `LONG-1-TEMPORAL-HOLDOUT`
- `RCP-1-RUNTIME-CONTROL-PLANE`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- Activation predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `RCP-1-RUNTIME-CONTROL-PLANE`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
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
- `system_domain_agent_episode_only`
- `boundary_condition_receipts`
- `resource_conservation`
- `weak_coupling_stability`
- `no_central_hot_path_rpc`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `utility.ndu` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `ModulePort::utility.ndu::control.runtime`
- `ModulePort::utility.ndu::intelligence.control`
- `ModulePort::utility.ndu::intuition.policy`
- `ModulePort::utility.ndu::prompt.optimizer`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`

**Consumed contracts:**
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `GoldenFixtureManifestV1`
- `ModulePort::cognitive.read::utility.ndu`
- `ModulePort::learning.artifacts::utility.ndu`
- `ModulePort::learning.ledger::utility.ndu`
- `ModulePort::platform.types::utility.ndu`
- `NduBoundaryConditionV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

**Typed protocols:**
- `GoldenFixtureManifestV1`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

**Owned data domains:**
- `ndu_coefficient_manifest_v1`
- `ndu_preference_projection`
- `ndu_update_receipt_v1`
- `ndu_utility_projection`

**Read data domains:**
- `golden_fixture_manifest_v1`
- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `ndu_well_posedness_certificate_v1`
- `operator_sensor_core_registry`
- `outcome_watermark_v1`
- `random_stream_manifest_v1`

**Work packages:**
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `NDU-2-AGENT-DOMAIN-HIERARCHY`

**Owned threats:**
- `parent_child_NDU_oscillation`
- `preference_state_goal_drift`
- `recursive_utility_instability`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `utility.ndu` to primary lane `LANE-D-OBJECTIVE-VALUE`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)

Owned readiness protocols:

- `NduIterationReceiptV1`
- `UtilityContributionV1`

Consumed readiness protocols:

- `NduConvergenceCertificateV1`
- `ObjectiveCompileReceiptV1`
- `ObjectiveConstraintSetV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `utility.ndu` is implemented by work package `NDU-0-PREFERENCE-UTILITY-CONTRACTS` in:

- `codex-rs/hepta-ndu`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

### Configured owner numeric admission before ordinary evaluation

The existing `NduAuthenticatedOwnerV1::evaluate` path uses the frozen
`NduNumericRegistryV1` whenever the owner was opened with a numeric registry.
Utility contribution axes are checked against the exact policy order and admitted
as signed-Q32 utility values through `rescale_signal_registered`. A versioned
canonical support digest binds original evidence and the registry-admission digest;
the existing V2 evaluation receipt therefore commits to the admitted evidence.
The source contribution limit is checked before admission work. Missing source
support cannot be replaced with a generated nonzero digest. The owner tests cover
normal deterministic evaluation, missing registry definition and invalid axes.
The ordinary registry-less owner retains compatibility semantics and does not
claim registered admission or activated product bootstrap.
