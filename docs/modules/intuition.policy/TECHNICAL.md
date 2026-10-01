# intuition.policy technical development guide

<!-- intuition-source-state:begin -->
## Canonical source-state projection

Source: `docs/modules/intuition.policy/CURRENT_STATE.json`; content SHA-256: `bb2b3368640c49f81356bb762e0795965ff399192da112705fce4071de319798`.

These are inspected source facts, not compilation, runtime, independent acceptance or release receipts.
All four production completion predicates remain false. Current execution identity belongs only to immutable command artifacts.

| Requirement | Source state | Scope |
| --- | --- | --- |
| `native_policy` | `source_present` | Explicit native profile risk routing and 1..128 candidate preflight before commitment hashing; historical encoding preserves prior receipt digests. |
| `authenticated_roles` | `source_present` | Generator, evaluator and observer signatures; pairwise verified controller separation. |
| `host_commit` | `source_present` | At most 127 product candidates plus abstain; complete pins, fresh owner clock and retained three-party/root-signed trust-lease revalidation under sole LedgerWriter lock. |
| `admission_receipt` | `source_partial` | All canonical dispositions recheck seven-owner currentness and RunStart authority after writer waits; selected runs also recheck evaluation leases; complete receipt survives in process; outward V1 is unchanged. |
| `authority_read` | `source_present` | Canonical signed owner files use one checked handle and at most 64 KiB plus one byte before JSON or cryptography; actual size and Unix path/handle, symlink and permission checks fail closed. |
| `startup_profile` | `source_present` | Strict typed profile resolved at AgentdState startup, included in configuration identity and enforced before compatibility returns. |
| `telemetry` | `source_partial` | Existing Codex metrics and tracing with bounded static reason codes; no deployed audit/exporter acceptance. |
| `source_qualification` | `source_present` | Read-only qualification workflows; source/merge/independent lanes validate source-state and all plans retain final-use and trust-distribution tests. |
| `source_projection` | `source_present` | Canonical source state generates document blocks, implementation-map projection and contract/requirement traceability. |

Remaining closure requirements:

- **durable_handoff**: Persist prepare, policy commit, run start, context attachment and delivery progress through the Agentd owner; tracing and an in-process receipt are not a durable transaction journal.
- **transport_receipt**: Introduce and migrate a versioned outward admission/acknowledgement contract that binds the policy receipt; do not silently redefine ObjectiveRunAdmission V1.
- **generation_recovery**: Implement and execute restart reconciliation, current-authority revalidation, monotonic generation fences and process-kill/concurrent/disk/corruption cases.
- **typed_domains**: Complete distinct sequence, wall-clock, assignment-counter and generation types at all owner boundaries without changing historical wire meanings.
- **legacy_consumers**: Migrate and qualify remaining V1/V2 advisory consumers; native V4 routing does not itself retire them.
- **exact_execution**: Obtain complete real source-head, deterministic merge, independent and ledger passes and current artifact agreement; a source-authoring or portability run is insufficient.
- **operator_acceptance**: Exercise real identity/entitlement, audit/exporter delivery, combined request p50/p95/p99/capacity/witness lag and backup/restore/rotation/rollout/rollback; obtain external evaluator and operator approval.

Version and requirement-to-test/artifact mappings: `docs/modules/intuition.policy/CONTRACTS.md`.
<!-- intuition-source-state:end -->


**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `intuition.policy`

**Owner:** `intelligence-platform`

**Deputy:** `learning-platform`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `INT-1-CALIBRATED-INTUITION-POLICY`

This stable document is the implementation guide for `intuition.policy`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

**Current source boundary:** V4 product semantics, V2 owner-separated commitments, authenticated V3 admission, complete Agentd pins, the canonical serving hook and in-process receipt binding exist in source. Final-use `commit_v4` retains the original signed qualification and samples the owner clock only after acquiring the sole learning-writer lock; it revalidates the root-signed trust lease, current trust generation, signatures, controller separation, lifetime and host pins before append. A workflow definition or a queued run is not a passing execution receipt. Use the current implementation dossier and exact command artifacts to distinguish source, execution and production acceptance; no production acceptance or promotion is asserted here.

The canonical Agentd composition also rechecks its frozen seven-owner snapshot and current RunStart authority for every disposition after the writer wait, before policy append. Selected runs additionally recheck their evaluation trust lease. The sink samples time again and revalidates policy qualification after the reject-only callback; callback I/O cannot reuse an earlier qualification time. Currentness is repeated before final run/context admission. These checks do not constitute a durable cross-owner transaction or restart journal.

## 1. Identity, mission and ownership

Select or abstain over a complete legal candidate set without bypassing deterministic validation.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `learning-platform` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `fast_policy`, state model `stateless_runtime` and architecture role `intervention_policy` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-intuition`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-intuition`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate. Dedicated inventory, focused tests, all-target compilation, strict lint and exact-head qualification remain execution requirements, not facts implied by source presence. This status does not activate `intuition.policy`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `utility.ndu`
- `neuron.runtime`
- `learning.artifacts`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `hard_veto_override`
- `direct_model_dispatch`
- `direct_tool_dispatch`
- `memory_write`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded target components are:

- `legal-candidate validator`
- `scoring head`
- `confidence calibrator`
- `OOD and abstention router`

The current native policy crate authenticates and selects over owner-produced scores and calibration/OOD artifacts. It does not itself train or execute the scorer or produce calibration artifacts. The target component list is retained as an integration design, not a claim that those upstream owners have been absorbed.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Turn cell outputs into the actual legal behavior policy, including masks, exploration, abstention and escalation. Keep prediction q, critic value and behavior mu separate. Bind the complete candidate set/order and report conditional/joint propensity where multiple cells cooperate; a raw Laya score is not final behavior evidence.

Routing, activation and termination may be DecisionCell policies. Record actual behavior after candidate admission, guards and budget selection; runtime event eligibility, joins and authority stay deterministic. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: candidate-order mapping, omitted candidates, policy after masking, unsupported joint propensity and OOD fallback.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Preserve actual post-mask route/action probabilities and nondifferentiable boundaries. Prediction scores are not behavior probabilities. Hard-branch approximation needs margin or mistake-risk analysis, not a continuous-layer error bound; unsupported credit does not justify a policy update.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

## 5. Contracts, ports and compatibility

Produced contracts:

- `IntuitionDecisionReceiptV1`
- `ModulePort::intuition.policy::context.compiler`
- `ModulePort::intuition.policy::intelligence.control`

Consumed contracts:

- `CandidateSetCompletenessReceiptV1`
- `DomainRead::eligibility_trace_checkpointV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `DomainRead::neuron_state_checkpointV1`
- `DomainRead::operator_sensor_core_registryV1`
- `LegalActionCandidateSetV1`
- `ModulePort::learning.artifacts::intuition.policy`
- `ModulePort::neuron.runtime::intuition.policy`
- `ModulePort::platform.types::intuition.policy`
- `ModulePort::utility.ndu::intuition.policy`
- `NduPreferenceStateV1`
- `NeuronCheckpointV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `RegularityProfileV1`
- `RunStartSnapshotV1`

Critical protocol schemas:

- `CandidateSetCompletenessReceiptV1`
- `IntuitionDecisionReceiptV1`
- `LegalActionCandidateSetV1`
- `NduPreferenceStateV1`
- `NeuronCheckpointV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `RegularityProfileV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

The V2 scorer and assignment commitment payloads have separate fields, but the historical generator completeness signing payload V1 includes the V1 candidate-set digest, which also binds utility, confidence, OOD and assignment probability. Generator completeness is therefore still coupled to those values at this compatibility boundary. Keep historical signed bytes stable; fully separating that signing contract requires a new version and qualified producer/consumer migration.

Rust types and canonical JSON must represent identical semantics. Required tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes. The current deterministic V2 commitment fixture additionally has an independently implemented Python encoder; it does not establish coverage for every protocol or assignment mode.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `candidate_set_completeness_receipt_v1`
- `eligibility_trace_checkpoint`
- `learning_artifact_registry`
- `ndu_preference_projection`
- `ndu_utility_projection`
- `neuron_checkpoint_v1`
- `neuron_state_checkpoint`
- `operator_applicability_certificate_v1`
- `operator_sensor_core_manifest_v1`
- `operator_sensor_core_registry`
- `regularity_profile_v1`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/intuition.policy.md#8-current-native-implementation-and-claim-boundary) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/intuition.policy.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/intuition.policy.md#8-current-native-implementation-and-claim-boundary) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/intuition.policy.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `intuition_propensity_omission`
- `intuition_unsupported_action`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/intuition.policy.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-intuition/src/lib.rs](../../../codex-rs/hepta-intuition/src/lib.rs) and the linked implementation components.

The pure policy kernel and candidate commitment encoders admit 1..128 real candidates. The Agentd product host admits at most 127 real candidates because its learning Decision includes the reserved abstain entry within the existing 128-entry ledger bound. `prepare_v3` rejects larger product sets with `agentd.intuition.product_candidate_limit` before hashing, cloning or signature verification. It neither truncates the legal set nor changes the ledger bound. The product fixture exercises 127 real candidates plus abstain and rejects 128 real candidates at that boundary.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Read-only policy library; inject the complete legal candidate set and exact calibration/support profile. Preserve the returned action probability before observing outcomes. Route unsupported or uncalibrated decisions to the configured deterministic slow path; the policy output cannot dispatch a tool or mint an authority token.

Current operating and state-format references:

- [codex-rs/hepta-intuition/src/calibrated.rs](../../../codex-rs/hepta-intuition/src/calibrated.rs).
- `codex-rs/hepta-intuition/src/production.rs` for bounded product semantics and stable error codes.
- `codex-rs/hepta-agentd/src/intuition_policy.rs` for retained three-party qualification, prepared profile/time/trust fences and final-use `commit_v4` under the sole writer boundary.
- `codex-rs/hepta-agentd/src/intelligence_authority_read.rs` for bounded signed owner-file reads through one checked handle before JSON and signature validation.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-intuition/src/calibrated_tests.rs](../../../codex-rs/hepta-intuition/src/calibrated_tests.rs); named case: `v2_binds_same_outcome_to_its_actual_assignment_and_artifact_metadata`.
- [codex-rs/hepta-intuition/src/lib_tests.rs](../../../codex-rs/hepta-intuition/src/lib_tests.rs); named case: `hard_veto_cannot_be_overridden`.
- `codex-rs/hepta-agentd/tests/intuition_policy_product_v3.rs`: signed host append, idempotent replay and durable reopen.
- `codex-rs/hepta-agentd/tests/intuition_policy_commit_boundary.rs`: cross-profile prepared values, evidence expiry, clock rollback, writer-wait expiry, concurrent attempts and current-trust rotation fences before append.
- `codex-rs/hepta-agentd/src/intelligence_product_final_use_tests.rs`: changed signed owner generations or RunStart entitlement during writer wait, and expired evaluation distributions before prepared-product reuse.
- `scripts/intuition_golden_vectors.py`: five independent Python digest encodings and 512 seeded owner-separation mutations over the deterministic fixture.

In `codex-rs`, run `just test -p codex-hepta-intuition`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/intuition.policy.md) separately labels target acceptance designs.

`hepta-intuition-qualification.yml` has read-only permissions. `scripts/intuition_qualify_exact.py` writes records outside the checkout, captures actual exit codes and log hashes, retains interrupted/failed records, and verifies unchanged source. Its source and synthetic-merge lanes are independent. No qualification job formats, migrates, commits, pushes or signs acceptance. Registering its aggregate check in repository branch protection is a separate administration operation.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `INT-1-CALIBRATED-INTUITION-POLICY`

The bootstrap package is `INT-1-CALIBRATED-INTUITION-POLICY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `intuition.policy`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `BIO-0-NEURON-INTUITION-CONTRACTS`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `learning-platform` / `inference-platform`.
- Allowed write paths:
- `codex-rs/hepta-neuron/**`
- `codex-rs/hepta-intuition/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- Activation predecessors:
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

#### `INT-1-CALIBRATED-INTUITION-POLICY`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-intuition/**`
- Development predecessors:
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `NEU-2-TEMPORAL-SIGNAL-RUNTIME`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- Activation predecessors:
- `NEU-2-TEMPORAL-SIGNAL-RUNTIME`
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
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## Current production qualification candidate (2026-09-26)

Updated on 2026-09-27 without discarding the target design above. The current product selector is `decide_calibrated_v4`; its authenticated entrance is `decide_authenticated_intuition_v3`. Historical V1/V2 and qualified V3 remain compatibility substrates, not independent product authority. Default-feature retirement is not complete merely because a root re-export is gated; internal legacy consumers must also be inventoried and migrated.

`Ppm` admits only `[0, 1_000_000]`; `PolicyGeneration` is nonzero. Product receipts retain original risk and an explicit profile-rule reason. Candidate identity, scored outputs and assignment distribution have separate V2 encodings; scoring and assignment commitments compose those owner-bound digests rather than mixing assignment probabilities into scorer output.

Generator evidence binds completeness; evaluator evidence binds profile/calibration/OOD qualification; observer evidence binds scoring and assignment. `AgentdIntuitionPolicyPinsV2` fixes the full profile, policy, generation, objective class, model, scorer, artifacts, risk rule and optional RNG owner. `commit_v4` revalidates the complete original request and signed generator/evaluator/observer records against writer-owned current trust while holding the sole writer lock. It recomputes the full host binding, rejects changed trust distribution/generation and pin drift, and samples a fresh clock after lock acquisition. Prepared time rollback or the earliest original qualification expiry rejects, even when a later Decision signature remains valid. The prepared digest uses `hepta.agentd.prepared-intuition.v3` and includes its preparation/expiry times and trust generation/distribution; the service digest uses `hepta.agentd.committed-intuition.v2` and binds final-use time. Historical durable Decision encodings are unchanged. The deprecated `commit_v3` name preserves its historical call signature but ignores its time argument and delegates to this boundary.

The service preserves its durable receipt when the post-commit admission check returns either `false` or an error. A committed Decision is not execution authorization. The selected host delegates persistence to one `IntuitionPolicyLearningSink`/`LedgerWriter`; exact replay must retain the original record, signed evidence and predecessor. An indeterminate result cannot be downgraded to an uncommitted failure or interpreted as permission to dispatch.

The intended canonical product sequence is:

```text
signed ObjectiveStart / durable RunStart
  -> bounded canonical invocation
  -> authenticated V3 qualification and V4 policy semantics
  -> complete current host pins and prepared lifetime checks
  -> selected-only durable Decision through the sole LedgerWriter
  -> current-run/generation revalidation
  -> downstream admission under its own effect authority
```

A direct host test does not prove this entire sequence. Materializing `start_canonical_intelligence` calls, compiling the resulting module tree, invoking the real Agentd process, testing revocation/rollback and interruption recovery, and measuring combined signature-plus-ledger latency are distinct obligations. Until their exact-source receipts exist, these remain unqualified rather than inferred complete.

Independent evaluator acceptance, operator target-host acceptance, canary authorization, promotion and release remain unsigned external gates. `qualification/intuition.policy/ACCEPTANCE_TEMPLATE.json` is a template, not a valid acceptance receipt.

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `intuition.policy` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `IntuitionDecisionReceiptV1`
- `ModulePort::intuition.policy::context.compiler`
- `ModulePort::intuition.policy::intelligence.control`

**Consumed contracts:**
- `CandidateSetCompletenessReceiptV1`
- `DomainRead::eligibility_trace_checkpointV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `DomainRead::neuron_state_checkpointV1`
- `DomainRead::operator_sensor_core_registryV1`
- `LegalActionCandidateSetV1`
- `ModulePort::learning.artifacts::intuition.policy`
- `ModulePort::neuron.runtime::intuition.policy`
- `ModulePort::platform.types::intuition.policy`
- `ModulePort::utility.ndu::intuition.policy`
- `NduPreferenceStateV1`
- `NeuronCheckpointV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `RegularityProfileV1`
- `RunStartSnapshotV1`

**Typed protocols:**
- `CandidateSetCompletenessReceiptV1`
- `IntuitionDecisionReceiptV1`
- `LegalActionCandidateSetV1`
- `NduPreferenceStateV1`
- `NeuronCheckpointV1`
- `NeuronSignalReceiptV1`
- `ObjectiveFunctionV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `RegularityProfileV1`
- `RunStartSnapshotV1`

**Owned data domains:**
- None.

**Read data domains:**
- `candidate_set_completeness_receipt_v1`
- `eligibility_trace_checkpoint`
- `learning_artifact_registry`
- `ndu_preference_projection`
- `ndu_utility_projection`
- `neuron_checkpoint_v1`
- `neuron_state_checkpoint`
- `operator_applicability_certificate_v1`
- `operator_sensor_core_manifest_v1`
- `operator_sensor_core_registry`
- `regularity_profile_v1`

**Work packages:**
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `INT-1-CALIBRATED-INTUITION-POLICY`

**Owned threats:**
- `intuition_propensity_omission`
- `intuition_unsupported_action`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `intuition.policy` to primary lane `LANE-F-ADAPTIVE-POLICY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)
- [`RDY-NEU`](../../readiness/NEURON_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `NeuronRuntimeConfigV1`
- `NeuronTickInputV1`
- `NeuronTickReceiptV1`
- `ObjectiveConstraintSetV1`
- `UtilityContributionV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `intuition.policy` is implemented by work package `INT-1-CALIBRATED-INTUITION-POLICY` in:

- `codex-rs/hepta-intuition`

The source candidate has qualification definitions in `.github/workflows/hepta-consolidated-source.yml` and the independent `.github/workflows/hepta-intuition-qualification.yml`. Actual closed-world inventory, package tests, all-target compilation, strict Clippy and clean-tree results must be read from an exact-source execution artifact, not inferred from these filenames. This section records the source location and evidence requirements only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
