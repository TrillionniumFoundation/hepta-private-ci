# inference.worker technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

The native App Server worker uses durable local-slot admission plus a persistent private App Server thread and stable client message identity; reopen reconciles provider history and may recover the same logical turn instead of blindly replaying it. Missing token usage remains unknown and cannot authorize success. The Unix local-process profile consumes a kernel-verified single-use resource grant, verifies exact model/runtime/device/isolation artifacts, and delegates physical load/infer/unload to a private bounded runtime socket. Repository-controlled source-boundary gaps are closed by this candidate; real-model/hardware/sandbox evidence, independent acceptance and activation remain separate external gates. The [native host guide](../../readiness/LANE_B_NATIVE_HOST.md#durable-inference-journal) specifies shared journal limits and hosted operating requirements.

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

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.worker.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.worker.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md). Hosted reopen reconciles the stable request/client-message identity against App Server history before any retry; persisted turns are read or recovered in place, and only a provider-proved Missing state with unchanged frozen context permits same-thread redispatch. Missing usage is never inferred as zero. Local load/run/unload fail closed on artifact/device/isolation digest drift or resource-grant mismatch. A source fixture still cannot stand in for target-host hardware or deployed sandbox qualification.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware. A serialized local `ResourceGrant` is policy data, not authority: every field that can change lifetime or capacity is bound into the existing kernel `FinalUseAuthority`, the signed grant is consumed once, and only the resulting non-serializable `VerifiedResourceGrant` can construct the local worker. Future IPC adapters must preserve that verifier boundary rather than exposing a deserializable capability constructor.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-infer-worker-host/src/lib.rs](../../../codex-rs/hepta-infer-worker-host/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Build `hepta-infer-worker` and select an explicit profile. `--profile native-app-server` requires the owning Agentd socket, Agent ID/generation, exact configured model, private journal and stable request ID. `--profile local-process` requires the request/lease/reservation envelope, kernel-signed resource grant plus pinned verifier/revocation state, exact manifest and absolute weights/tokenizer/preprocessor/quantization/runtime/device/isolation paths, and a private Unix runtime socket. Hosted execution relies on App Server's durable thread/reconcile/recover primitives. Local execution proves the supplied isolation receipt and device descriptor match the manifest; it does not self-certify that the host actually installed cgroups, namespaces, seccomp or device ACLs.

Current operating and state-format references:

- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-infer-worker-host/src/lib_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/lib_tests.rs); named case: `terminal_success_requires_exact_authority_binding`.
- [codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs); named case: `loads_runs_and_unloads_exact_model_tuple`.
- [codex-rs/hepta-infer-worker-host/src/local_process_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/local_process_tests.rs); verifies exact artifact hashing and a real Unix-socket load/infer/unload protocol fixture.
- [codex-rs/hepta-infer-worker-host/tests/local_product.rs](../../../codex-rs/hepta-infer-worker-host/tests/local_product.rs); signs a real kernel final-use grant and proves request/lease/reservation -> verified grant -> local runtime composition.

In `codex-rs`, run `just test -p codex-hepta-infer-worker-host`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `INFER-V4-T4`
- `INFER-V4-T5`
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

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
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


## 18. Production readiness and runbook

This section is the single operator-facing closure view for this module; it intentionally consolidates the previously scattered readiness facts instead of creating a second competing implementation guide.

### 18.1 Guarantees and non-guarantees

Repository source guarantees bounded/typed ingress, exact model/payload binding, signed single-use local resource admission, generation fencing, durable hosted dispatch identity, provider reconciliation before retry, monotonic usage observation, bounded local Unix transport, exact artifact/device/isolation-receipt hashing, and cleanup after authority expiry. The word **isolated** at source level means authority/execution ownership is isolated and the selected host isolation receipt is cryptographically bound to the manifest.

Repository source alone does **not** prove an OS sandbox is active. A deployment may claim process/device isolation only when independent target-host evidence identifies the exact worker binary, runtime binary, cgroup or equivalent memory/CPU controls, namespace/container boundary, seccomp or equivalent syscall policy where applicable, GPU/device ACL, private socket ownership/mode, and the digest of the isolation receipt consumed by the worker.

### 18.2 Admission checklist

Before hosted dispatch, verify exact Agent identity/generation, private journal ownership, stable request ID, configured model, deadline and in-flight bound. Before local dispatch, additionally verify the request/lease/reservation envelope, current authority epoch/revocation head, one-use signed resource grant, manifest digest tuple, absolute non-symlink artifact files, device descriptor, isolation receipt, private direct Unix socket, and runtime timeout. Any mismatch is a hard reject; no fallback model/runtime/device is allowed.

### 18.3 Recovery decision table

- **No durable dispatch:** fail/retry is safe only through normal admission because provider execution is proven not to have started.
- **Durable thread, provider says Missing:** retry only on the same thread with the same stable client message ID and only when the frozen context digest matches.
- **Provider says Persisted/InProgress:** continue observing or recover the same logical turn; never start a fresh turn for that request identity.
- **Provider says Persisted/terminal:** reconstruct the persisted output/status and reconcile token usage. Missing usage stays unknown and the run is not authorized success.
- **Provider history contradicts a previously bound turn/model/provider:** quarantine/error; do not repair by replay.
- **Local runtime disconnect after physical dispatch:** report indeterminate unless the runtime protocol supplies a trustworthy terminal observation; never fabricate success or zero usage.

### 18.4 Required target-host qualification before activation

Run the exact release candidate with identified real weights/tokenizer/preprocessor/quantization/runtime/device. Record cold/warm load and unload, peak resident and device memory, token throughput, p95/p99 latency, concurrency at the selected grant ceiling, repeated cancellation, OOM before and during generation, runtime process kill, worker kill at each load/dispatch/settlement boundary, device reset, socket disconnect, cancellation during unload, and repeated restart/reconciliation. Verify no leaked model/device handles and no duplicate provider turn for one stable request identity.

The hardware/sandbox evidence must bind the exact candidate commit/tree, worker and runtime binaries, model/artifact digests, device identity, isolation receipt, authority epoch/revocation revision and test configuration. A later source or deployment change invalidates that receipt.

### 18.5 Rollback and stop conditions

Rollback first stops new admission, then drains or cancels admitted runs, reconciles every hosted durable request, unloads local handles, and only then replaces the binary/runtime/model generation. Never delete the durable journal to clear an indeterminate run and never reuse an old signed resource grant with a new generation. Stop activation on authority drift, provider identity drift, unreconciled terminal usage, artifact/device/isolation digest mismatch, memory overrun, leaked handles, duplicate turn evidence, or any sandbox control missing from the claimed isolation receipt.

### 18.6 Activation boundary

Passing repository CI closes source-boundary work; it does not by itself set `productionImplementation`, `deploymentQualificationComplete`, independent acceptance, activation, promotion or release. Those claims require fresh exact-candidate target-host receipts and the designated external decisions. The implementation map therefore keeps deployment/activation/release false until those gates are actually evidenced.
