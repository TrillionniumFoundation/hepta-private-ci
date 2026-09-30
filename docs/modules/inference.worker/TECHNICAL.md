# inference.worker technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

The native App Server worker uses the existing durable inference-control owner for local-slot admission, dispatch identity, cancellation intent and observed settlement. Reopening a possibly dispatched request reconciles exact App Server history without issuing another turn. Missing history and missing token usage remain unknown. Economic quota, physical local-model execution and target-host recovery qualification remain open. The module-specific [runbook](../../../codex-rs/hepta-infer-worker-host/RUNBOOK.md) specifies current CLI and authority configuration; the [native host guide](../../readiness/LANE_B_NATIVE_HOST.md#durable-inference-journal) provides cross-module context.

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `inference.worker`

**Owner:** `inference-platform`

**Deputy:** `security-authority`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `INFER-V4-T4`

This stable document is the implementation guide for `inference.worker`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Execute a granted inference request in an isolated worker without minting authority or mutating fleet state.

The primary owner `inference-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `adapter`, kind `worker`, state model `ephemeral_isolated` and architecture role `checked_adapter` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-infer-worker-host`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-infer-worker-host`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `inference.worker`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `inference.control`
- `kernel.authority`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `grant_issuance`
- `fleet_mutation`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bounded ingress`
- `isolated execution cell`
- `resource guard`
- `terminal receipt reporter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### 4.1 Implemented profiles and component owners

| Surface | Implementation | Current meaning |
| --- | --- | --- |
| `execute` | `src/lib.rs` | Pure validation and receipt construction from supplied request/lease/reservation/observation; no provider call. |
| `AppServerModelDriver::run` / `run_intelligence` | `src/native_run_control.rs`, `src/native_app_server.rs` | Executable hosted profile through the owning Agentd and existing App Server. The CLI is `hepta-infer-worker --profile native-app-server`. |
| `InferenceWorker<D>` | `src/model_worker.rs` | In-memory manifest/grant/lifecycle state machine with injected `ModelDriver`; this repository does not supply a physical weights/device driver. |
| `NeuronFeatureDriver` | `src/model_worker.rs`, `src/model_worker_features.rs` | Optional typed feature port on that same loaded-model owner; fixture execution does not establish a local encoder or trained model. |
| `UnixFinalUseAuthorizer` | `src/final_use_authorizer.rs` | Requests an independently signed exact-binding grant and consumes it through the existing `kernel.authority` verifier. No signing key belongs to the worker. |

The hosted profile does not call `InferenceWorker::load_model`. It selects the exact model configured in the owning App Server. Consequently the hosted profile's local-slot limit is not the model-worker resource grant, and the manifest driver's memory/token ceilings do not constrain hosted provider billing.

The worker owns live client handles and ephemeral output projection. `inference.control` owns durable request/dispatch/observation records; Agentd owns run lifecycle and context access; App Server owns thread/turn execution; `kernel.authority` owns grant verification and persistent nonce/revocation state. Artifact/cache and fleet owners retain weights and physical resource allocation. Do not add a second journal writer, provider executor or credential store to close an integration gap.

## 5. Contracts, ports and compatibility

Produced contracts:

None.

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::inference_receiptV1`
- `DomainRead::inference_requestV1`
- `DomainRead::inference_reservationV1`
- `ModulePort::inference.control::inference.worker`
- `ModulePort::kernel.authority::inference.worker`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

### 5.1 Hosted request and final-use binding

`NativeAdmission` supplies a stable request ID and explicit local maximum-in-flight policy. Admission binds that ID to Agent identity, generation, exact model and a digest of prompt, optional context query, Agentd socket and timeout. A reused ID with different semantics conflicts before execution. `run_intelligence` additionally binds run ID, expected Agentd revision, context digest and compilation-envelope digest. Those fields identify an already attached Agentd run; they grant no authority.

Before physical `turn/start`, the final payload binds actual App Server thread/session, connection, version, protocol, model/provider, user input, optional untrusted cognitive context and absolute deadline. The worker obtains a `VerifiedUseToken` for that exact operation, persists the dispatch/correlation and claim-time authority witness, rechecks current owner/ingress/cancellation/deadline and optional context, then consumes the token at adapter entry. The independent authority may deny the operation. A digest or serializable receipt cannot replace that token.

The same stable request ID is sent as `client_user_message_id`. This is a recovery correlation field, not an assertion that the provider implements exactly-once execution. The final-use Unix port configuration and bounded wire exchange are documented in the [runbook](../../../codex-rs/hepta-infer-worker-host/RUNBOOK.md#independent-final-use-authority).

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `inference_receipt`
- `inference_request`
- `inference_reservation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

### 6.1 Hosted journal and compatibility

The hosted CLI opens the existing `DurableInferenceControl` journal through its public ports. One exclusive file lock protects replay and append. A candidate transition is validated before append, the append is synced before publishing in-memory state, and ambiguous write/sync failure fences that writer. Native admission requires a private journal; new Unix journals are mode `0600`. Prompt/output observations are private Agent data, even though the worker's public receipt primitives use digests.

Native records are versioned `native-v1` alongside replay-compatible legacy records. New dispatches include the exact runtime.codex correlation and authority frontier. Historical records missing those bindings cannot acquire modern qualified recovery semantics by filling in defaults. An older binary that cannot read native records must not replace the journal owner. Preserve a compatible binary/state pair for rollback; do not truncate or manually rewrite history.

The first native admission pins the journal's maximum-in-flight policy. Capacity is local to that journal and is not shared across independently created journals. The process holds its writer lock while awaiting a run, so the CLI itself executes one prompt per invocation rather than providing an asynchronous multi-request service.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.worker.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

### 7.1 Local driver lifecycle

`InferenceWorker<D>` receives one immutable `ResourceGrant` and one worker generation. It checks grant identity, generation, expiry/revoked flag, manifest digests, request/lease/reservation payload agreement, model and token limits before invoking the driver. The host must authenticate the supplied grant and bind the manifest to real artifact bytes; these ordinary Rust values do not perform signature verification, hardware discovery or immediate revocation distribution themselves.

Admission counts loaded models and aggregate per-model resident-memory high-water marks. A smaller later observation cannot refund retained model memory; only observed unload removes that model's charge. Neuron feature-buffer bytes additionally count against the observed peak. A driver handle rejected after load is unloaded before rejection is returned. An observed resource overrun stops further admission until all known idle models have been unloaded. Cleanup of those models remains available after grant expiry/revocation; cleanup does not authorize another run.

Ambiguous load or unload failure creates a separate driver fence; failed unload retains the loaded-model record and cannot be retried through that fence. Driver errors and nonterminal run/feature observations retain the request slot and prevent unloading that model. Only observed terminality releases a run slot. There is no local-driver reconciliation or reset API: process restart alone is not proof that device work or allocations stopped. A future physical driver needs an owner-controlled stop/reconciliation procedure before a new generation can safely reclaim those resources.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.worker.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

### 8.1 Hosted failure and recovery contract

| Boundary or fault | Current behavior | Recovery posture |
| --- | --- | --- |
| Validation, cancellation or connection failure while still `Reserved` | Durable pre-dispatch stop; local slot released; no provider terminality or zero-usage claim. | Return the recorded stop for that request identity. |
| Failure after durable dispatch but before effect entry | Only the live one-shot pre-effect abort proof can establish a definitive unsent stop. | Consume that proof; a restarted process cannot recreate it. |
| Exact pre-admission overload rejection | Durable rejection records the observed response and releases the local slot when marked safe-before-admission. | No automatic resubmission; the rejected identity remains recorded. |
| Other explicit rejection | Return the recorded rejection and never resubmit that identity. | Retain the owner's recorded state; do not treat it as provider completion. |
| Lost `turn/start` acknowledgement | Observe an exact same-connection `turn/started` if available; otherwise remain indeterminate. | Never send another `turn/start` for that identity. |
| Reopened possible dispatch | Query the exact current Agent generation/App Server using `thread/read(includeTurns=true)`. | Settle only exact authenticated response provenance plus stable client ID and original user input. Missing bindings/history remain indeterminate; mismatched or duplicate turns conflict. |
| Cancellation, timeout, event loss/disconnect or owner fencing after start | Record stop/cancel intent and issue actual `turn/interrupt`; interrupt acknowledgement is not terminality. | Keep the slot until matching terminal evidence arrives; late provider facts cannot authorize cancelled/timed-out/lost-owner success. |
| Corrupt/partial journal or ambiguous append/sync | Replay fails or writer fences; no history truncation. | Preserve the journal and use the owner's recovery procedure. |

Provider status, boundary status and owner authority are separate fields in `NativeRunOutput`. CLI success requires matching provider completion, a successful boundary and verified current owner authority. Observed usage is optional and monotonic; an absent event is `null`, not zero, and settlement is not payment authorization.

For an intelligence-bound run, durable inference settlement precedes terminal publication to Agentd. The [recovery helper](../../../codex-rs/hepta-infer-worker-host/src/native_recovery.rs) retries that publication from cached or recovered terminal records without replaying the model. Publication failure returns an error while preserving the durable provider observation. Publication validates exact run/generation/context/envelope and current revision; an already acknowledged matching terminal is idempotent. Recovery retains previously observed tokens and sticky cancellation/timeout/quarantine or lost-owner facts rather than replacing them with a successful-looking history read.

The source includes exact-owner post-reopen terminal reconciliation; it does not guarantee recovery after the owning App Server loses its ephemeral thread history or moves to a new generation. `thread/read` recovery does not itself produce missing token-usage events. Target-host retention, authenticated later usage, operational quarantine/release policy and cross-generation provider recovery remain separate work. See the shared [runtime.codex fault matrix](../runtime.codex/FAULT_MATRIX.md) for transport/authority correlation cases.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-infer-worker-host/src/lib.rs](../../../codex-rs/hepta-infer-worker-host/src/lib.rs) and the linked implementation components.

| Current source limit | Bound / owner |
| --- | --- |
| Hosted prompt / optional query | 32 KiB / 1–2048 bytes. |
| Complete cognitive context | Shared 8 KiB serialized budget; context remains untrusted additional context. |
| Hosted output | 1 MiB UTF-8 bytes; per-item projection also bounds output item count and identity size. |
| App Server event queue | 256 events for execution, 64 for reopened reconciliation. |
| Configured hosted timeout | Nonzero and at most one hour; default CLI 120 seconds. RPC calls have separate five-second bounds. |
| Journal policy | 1–256 local in-flight slots; 64 MiB journal, 8 MiB encoded line, at most 16384 records; dispatch/admission requires 16 MiB spare bytes. |
| Local model driver | At most 8 models, 256 active requests, 1000000 requested tokens, further reduced by the supplied grant/manifest. |
| Local Neuron feature request | At most 512 features with bounded Q24 values; exact inference-control tuple is revalidated. |

These are enforced source bounds, not throughput, memory, token-rate or tail-latency measurements. Measure the selected host and provider at maximum admissible prompt/output, slow authority response, event overload, repeated restarts and journal capacity. No hosted token or economic budget is enforced by the local-slot policy.

The durable journal has one exclusive writer and bounded append/replay. No compaction or alternating-writer implementation, or current executable history-growth qualification, is supplied. The legacy inference-maintenance and architecture-convergence CI scale filters currently select no tests; their minimum-test gates correctly fail and do not establish those capabilities.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Build `hepta-infer-worker` and explicitly select `--profile native-app-server`. Supply the owning Agentd socket, Agent ID/generation, exact configured model, private journal, stable request ID, maximum-in-flight policy and required `--final-use-authority-config`. The independent issuer must be supplied by the trusted host; the binary does not start an issuer or create a signing key. Hosted execution uses the owning App Server; it does not establish local model weights, device grants or GPU isolation.

Current operating and state-format references:

- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).
- [Worker runbook](../../../codex-rs/hepta-infer-worker-host/RUNBOOK.md): complete CLI, authority configuration, result interpretation and recovery.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-infer-worker-host/src/lib_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/lib_tests.rs); named case: `terminal_success_requires_exact_authority_binding`.
- [codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs); named case: `loads_runs_and_unloads_exact_model_tuple`.
- [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs): duplicate/reopen, explicit rejection and pre-dispatch stop.
- [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs): matching event/usage, owner health and final-use cognitive validation.
- [codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs): signed grant, issuer peer UID, denial and revocation rollback.
- [codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs): real supervisor/Agentd/App Server route with an independent test issuer and mock Responses provider. This establishes a product-route test design, not a paid provider run.

In `codex-rs`, run `just test -p codex-hepta-infer-worker-host`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `INFER-V4-T4`
- `INFER-V4-T5`
- `MEM-READ-1-SNAPSHOT-PORT` (co-owned cognitive final-use revalidation)
- `NEU-1-LOCAL-MODEL-BAKEOFF`

The bootstrap package is `INFER-V4-T4`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `inference.worker`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `INFER-V4-T4`

- State: `source_implemented`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-infer-worker-host/**`
- Development predecessors:
- `INFER-V4-T1`
- Activation predecessors:
- `INFER-V4-T3`
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

#### `INFER-V4-T5`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-infer-worker-host/**`
- Development predecessors:
- `INFER-V4-T4`
- Activation predecessors:
- `INFER-V4-T4`
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

#### `NEU-1-LOCAL-MODEL-BAKEOFF`

- State: `planned`; priority: `2`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `inference-platform`.
- Allowed write paths:
- `codex-rs/hepta-neuron/**`
- `codex-rs/hepta-infer-worker-host/**`
- Development predecessors:
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `INFER-V4-T5`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `INFER-V4-T4`
- Activation predecessors:
- `INFER-V4-T5`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
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

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `inference.worker` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `SensorCalibrationManifestV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `inference.worker` is implemented by work package `INFER-V4-T4` in:

- `codex-rs/hepta-infer-worker-host`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
