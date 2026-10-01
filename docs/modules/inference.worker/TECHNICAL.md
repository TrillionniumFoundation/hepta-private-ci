# inference.worker technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

The native App Server worker now calls the same durable control owner for explicit local-slot admission, persisted dispatch identity, cancellation intent and actual observed settlement. Optional observed tokens remain unknown when absent; restarting a possibly dispatched request never replays it. Reopened requests can reconcile exact terminal App Server history without a new turn; unavailable ephemeral history and missing usage remain unresolved. This does not close economic quota, local weights/device or independent target-host qualification gaps. The [native host guide](../../readiness/LANE_B_NATIVE_HOST.md#durable-inference-journal) specifies journal limits, CLI requirements and recovery semantics.

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

`existing_bound` is a source-location fact. The declared root is materialized and has focused test, compilation, lint and source-inventory entrypoints. A named hosted caller and controlled-provider product composition exist in source; their presence is not a current test-pass receipt. Source mapping does not activate `inference.worker`, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `inference.control`
- `kernel.authority`

These are the canonical registered module dependencies. The hosted implementation composes the existing Agentd owner/generation protocol and delegates thread/turn execution and exact request correlation to `runtime.codex`; optional cognitive context and intelligence handoff remain owned by their existing Agentd ports. This host composition does not create another execution spine, expand these registered dependencies or transfer their durable-domain ownership.

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

### 4.1. Current source components

| Component | Entry point and source | Current responsibility |
| --- | --- | --- |
| Boundary validation | `lib.rs` | Pure typed validation and receipt primitives; no provider invocation |
| Hosted CLI | `src/bin/hepta-infer-worker.rs`, `native_cli.rs` | Parse required flags, complete intelligence grouping and absolute journal before configuration/journal/input I/O; select one explicit profile and read one bounded prompt; runtime owners validate business limits |
| Native input | `native_input.rs` | Validate borrowed admission/handoff identifiers and digests before hashing or control admission; stream the established request digest without an encoded-payload copy; preserve the existing version profile and cap service diagnostics while formatting at 1024 Unicode characters (at most 4096 UTF-8 bytes) |
| Durable run wrapper | `native_run_control.rs`, `AppServerModelDriver::run` / `run_intelligence` | Reserve through `inference.control`; return completed historical records, reconcile uncertain records or start one new admitted attempt |
| App Server driver | `native_app_server.rs`, `run_once` / `reconcile_existing` | Freeze exact request/correlation, obtain final-use authority and perform one effect entry or exact retained-history recovery |
| Observation and intelligence helpers | `native_observation.rs`, `native_recovery.rs`, `native_intelligence.rs`, `native_intelligence_receipt.rs`, `native_denial.rs` | Bound live/recovered observations, preserve monotonic evidence and cancellation intent, persist denied boundaries before external cancellation/interrupt awaits, and publish matching live/recovered Agentd outcomes through the existing owner revision CAS |
| Authority bridge | `final_use_authorizer.rs`, `native_authority_port.rs`, `UnixFinalUseAuthorizer` | Request an independently signed exact-binding grant and claim it through the shared kernel authority; never own a signing key |
| Local component | `model_worker.rs`, `model_worker_validation.rs`, `InferenceWorker<D>` | Validate manifest/resource/request tuples, account driver-reported allocations and retain uncertain-resource ownership; the injected driver owns physical load/run/drain |

Paths in this table are relative to `codex-rs/hepta-infer-worker-host`. Hosted execution and the local model component are separate interfaces. The CLI selects hosted execution; it does not instantiate a physical local weights/device driver. The source-bound operating and authority protocol is described in [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md#native-worker-authority-configuration) and [the final-use authority port](../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md).

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

Registered wire contracts must preserve their canonical JSON semantics and reject unknown critical fields. The local driver interfaces are Rust component types, not a newly deployed wire protocol. Source verification covers the applicable bounds, authority/request digests and outcome distinctions; round-trip and schema requirements apply to the registered serialization boundary. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes. Native admission/handoff identities use borrowed Stable V1 and canonical nonzero Digest32 validation before hashing or control admission. The issuer bridge validates final-use identifiers and its three nonzero digests before copying/serialization. Streaming SHA-256 preserves the exact existing feature v1 and source JSON v1/v2 byte encodings; it adds no new wire format or authorization coverage. The private authority-port extraction preserves the existing public API re-exports.

`NativeIntelligenceRunBinding` adds `run_id`, `expected_revision`, `context_digest` and `envelope_digest` to the admission digest. The CLI requires all four `--intelligence-*` arguments together. Agentd must already report the exact handoff as `ContextAttached`; the worker cannot manufacture or replace that envelope. In the intelligence mode, the worker checks the exact dispatched receipt immediately before effect entry, including owner cancellation, and polls it with the existing 500 ms owner-health tick during observation. Only an exact matching owner cancellation may advance the tracked revision; unexpected phase, revision or binding drift fails closed. Cancellation can stop the pending effect or interrupt an entered turn, and late provider completion cannot publish Agentd success for a cancelled/deadline-denied local boundary.

The current profile supports a cognitive query or an intelligence envelope separately. Supplying both is rejected before admission/provider I/O, and the CLI rejects the combination before configuration/journal/stdin I/O. No current owner port attests both cuts together; sequencing their separate awaits can stale one while checking the other. Combined support requires that owner final-use port. With `--context-query` alone, cognitive context is independently retrieved and revalidated immediately before effect entry; this freshness check is not an atomic lease over future owner writes.

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

The hosted request ID is idempotent only for identical Agent/generation/model, prompt, context-query, socket, timeout and optional intelligence binding. Payload drift is a conflict. `DurableInferenceControl` owns the journal, exclusive writer lock, dispatch/slot state and settlement; the worker calls its ports instead of writing those facts directly. A completed duplicate is a historical observation and does not reacquire authority or invoke the provider.

The local component serializes calls through `&mut self`. It checks aggregate resident allocation, request and feature limits, then treats the injected driver as a physical boundary. Failed or indeterminate driver run/feature work and malformed observations retain a cleanup fence. For owned handles, new load/run/feature calls remain denied until explicit driver unload confirms draining and resource release. A load unwind before returning a handle or a duplicate opaque handle ID leaves worker-wide load uncertainty: no new execution or load is admitted, and cleanup of known handles cannot clear that fence. Recovery requires physical cleanup and a fresh driver generation. Unload can release known resources after grant expiry/revocation; it does not authorize new execution.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

A definitely-unsent hosted request may release its local slot only through the owning control port and, after durable prepare, the live one-shot pre-effect abort proof. The proof is bound to the exact issuing control instance, request and dispatch revision; a different journal or reopened instance cannot consume it. Process loss destroys that proof. After effect entry, cancellation, deadline, transport loss and lost acknowledgements remain accepted-or-unknown until matching terminal evidence arrives; interrupt acknowledgement alone does not establish terminality.

A recorded pre-dispatch stop or proven pre-effect abort remains definitely unsent: later nonterminal or terminal settlement is rejected before append and cannot resurrect it. Later observation refinement remains available for actually dispatched runs.

An observation denial attempts to persist the observed prefix, denied boundary and cancellation intent through the control owner before awaiting Agentd cancellation or provider interruption. A journal failure still leads to a physical interrupt attempt before the error returns. Neither denial nor cancellation intent releases capacity without exact provider terminal evidence.

`reconcile_existing` uses the same Agent generation and exact App Server home/version/provider plus the original stable client-message identity and user input. It can settle an exact terminal `thread/read` observation without a new `turn/start`. Missing ephemeral history remains indeterminate and retains the slot. Recovery preserves earlier observed usage, cancellation/deadline boundary outcomes and owner-authority loss; current readiness cannot erase a lost authority fact. Missing token usage remains unknown and does not become zero. Historical dispatches missing the claim-time authority epoch/revocation frontier retain provider terminal truth but normalize to a quarantined local boundary before owner reconciliation.

Recovered terminal text above the 1 MiB output budget retains a bounded UTF-8 prefix and a quarantined boundary, subject to preserved earlier denial. Physical status, correlation and terminal truth remain intact; prior usage stays effective. Settlement may release the local slot while success stays denied. Live cancellation is sampled and durably recorded before and after the recovery await, including its error exits; an already completed historical duplicate returns its recorded fact directly.

For an intelligence-bound recovered terminal, `native_intelligence.rs::reconcile_intelligence_terminal` reads the exact Agentd run target and uses its observed current revision with `run_observe_terminal`. Only matching `Dispatched`, `Cancelling` or `Indeterminate` targets can receive this CAS update; an already exact terminal owner receipt is historical truth only when its phase matches the preserved local boundary, and does not require an unexpired execution deadline. Cancellation, deadline and prior denied boundaries remain effective. A concurrent revision/CAS conflict or terminal-phase mismatch retains the owner state, adds a bounded diagnostic and denies local success; recovery never overwrites the target or creates another turn. Missing/mixed owner targets, lost generation or unavailable provider history remain unresolved.

A live pre-effect abort can safely release the local inference slot after Agentd recorded `Dispatched`, but that local proof does not establish an Agentd terminal outcome. The owner ledger remains conservative pending an explicit owner-side no-effect reconciliation.

The local component registers rejected post-load handles before automatic cleanup, so an unload panic retains ownership for explicit retry. An opaque ID colliding with an already tracked handle is a separate ambiguity: it admits no second record and never automatically unloads the alias, which could release the existing resource. Distinct concurrent opaque IDs are a driver obligation; the ambiguity fence survives known-handle cleanup and requires physical driver-wide cleanup followed by a fresh isolated worker generation. It retains handles when unload fails and fences malformed/nonterminal driver run/feature work. A propagated driver panic with a known handle leaves the pre-invocation fence in place; explicit driver-confirmed unload can recover that resource state and only then clear stale active-request bookkeeping. A driver-reported allocation is not proof that a real accelerator stayed within the grant. Restart/quarantine, physical resource enforcement and loss of local driver state still require a qualified host implementation.

Use the [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.worker.md#8-current-native-implementation) and [module-specific fault cases](../../../qualification/module-execution-dossiers/detail/inference.worker.md). A source library or fixture cannot stand in for missing external reconciliation or target-host evidence.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Hosted effect authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

The local `ModelManifest`, `ResourceGrant` and `WorkerRequest` are public caller-constructed component records. Validation checks fields and tuple equality; it does not prove an independent signature, issuer provenance, live revocation distribution or actual model bytes. The existing Neuron feature payload v1 binds feature/model digests and vectors but does not seal authorization request/reservation IDs or token/deadline terms. A versioned issuer/control contract and qualified physical driver are required before presenting this local interface as independently authorized inference.

Required negative coverage includes denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Section 12 identifies current source cases; requirements and test identities do not prove every physical-host case has executed. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Pure validation/receipt limits belong to [lib.rs](../../../codex-rs/hepta-infer-worker-host/src/lib.rs); hosted prompt/output/deadline and event-channel limits belong to [native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs); local model/request/feature ceilings belong to [model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs). Local allocation values remain driver observations, not measured physical capacity.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Build `hepta-infer-worker` and explicitly select `--profile native-app-server`. Supply the owning Agentd socket, Agent ID/generation, exact configured model, private journal, stable request ID, pinned `--maximum-in-flight` and mandatory `--final-use-authority-config` as documented. Hosted execution uses the owning App Server; it does not establish local model weights, device grants or GPU isolation.

Current operating and state-format references:

- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).
- [codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md](../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-infer-worker-host/src/native_cli_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_cli_tests.rs): the production binary's pure parser, required flags and complete intelligence grouping before configuration/journal/stdin I/O; not a full executable E2E.
- [codex-rs/hepta-infer-worker-host/src/lib_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/lib_tests.rs); named case: `terminal_success_requires_exact_authority_binding`.
- [codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs); named case: `loads_runs_and_unloads_exact_model_tuple`.
- [codex-rs/hepta-infer-worker-host/src/native_input_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_input_tests.rs): borrowed input bounds, canonical identity/digest rejection, parity with the established JSON digest encodings, version-profile compatibility and bounded multi-chunk Unicode diagnostics.
- [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs): durable duplicate/no-replay and pre-dispatch stop semantics.
- [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [native_observation_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_observation_tests.rs), [native_recovery_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_recovery_tests.rs) and [native_intelligence_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_intelligence_tests.rs): exact matching outcomes, bounded terminal recovery, monotonic evidence, owner loss, usage, cancellation/deadline and final-use freshness.
- [native_intelligence_receipt_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_intelligence_receipt_tests.rs) and [native_denial_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_denial_tests.rs): historical terminal-phase matching and reopened denied-boundary preservation before external cancellation/interrupt awaits.
- [codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs): signed grants, denial, peer identity and revocation rollback.
- [codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs): real Agentd/App Server composition with an independently signed test grant and controlled mock Responses provider; not real-provider or deployment proof.

The product E2E calls the driver library and constructs its authority configuration directly. It does not spawn `hepta-infer-worker` or exercise its protected configuration file, stdin/stdout, exit status or signal handling. Executable-caller coverage remains separate from this source composition.

The worker's in-process Agentd composition passes its helper-capable test executable explicitly to `CognitiveTestHost::start`. `core_test_support` installs the real Codex arg0 helper dispatch in that harness; the fixture does not rely on an unconfigured executable path or qualify the worker CLI lifecycle.

In `codex-rs`, run `just test -p codex-hepta-infer-worker-host`. For the cross-owner hosted composition, also run `just test -p codex-hepta-agentd --test runtime_codex_product_e2e`. These commands are invocations, not stored results. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `INFER-V4-T4`
- `INFER-V4-T5`
- `MEM-READ-1-SNAPSHOT-PORT` (co-owned cognitive final-use revalidation)
- `NEU-1-LOCAL-MODEL-BAKEOFF`

The bootstrap package is `INFER-V4-T4`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Ordinary source implementation review requires the declared root, public surfaces consistent with registries and applicable affected-package tests. Exact-head, merge-candidate and independent evidence apply when their qualification/runtime boundary is exercised; the package deliverable list is not a separate approval gate for ordinary source-only work. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

| Completion dimension | Source state | Remaining proof or implementation |
| --- | --- | --- |
| Developer documentation | Stable guide, implementation map, dossier and authority/operations references exist | Keep source behavior and canonical package state synchronized; a documentation pass is not execution evidence |
| Hosted source execution | CLI and named App Server driver implement durable admission, signed final-use entry, exact observations and retained-history recovery | Combined cognitive/intelligence owner final-use port; applicable source tests; selected-provider and target-host fault evidence remain separate |
| Product source composition | Existing Agentd/App Server path and controlled-provider library E2E are source-composed | Executable CLI input/configuration/output/signal coverage; real provider, selected target host and independently operated authority qualification |
| Local model component | Manifest/grant/request validation, driver-reported aggregate accounting and cleanup fencing exist | Versioned independently issued local authorization, real verified weights/tokenizer/runtime/device driver, physical memory enforcement and OOM/reset/load-kill evidence |
| Persistence and recovery | Control owner retains uncertain slots, output/correlation and optional usage; exact retained App Server history can refine outcomes | Authenticated archival, missing-usage reconciliation, owner-side no-effect recovery and qualified resolution when the exact owner/provider witness is unavailable |
| Activation and acceptance | No activation, independent acceptance, promotion or release is established by this guide | External owner decisions and exact-candidate evidence at each corresponding gate |

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

The affected inference lane in `.github/workflows/hepta-architecture-convergence.yml` also invokes `just test --locked -p codex-hepta-infer-worker-host` and retains a separate command record requiring observed passing tests. This includes the executable's parser tests; it is not a full CLI/provider E2E or a stored pass receipt. Inspect the exact candidate's CI result and any skips or failures.
