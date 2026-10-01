# inference.control technical development guide

Current operation, source and qualification facts come from [CURRENT_STATE_SOURCE.json](CURRENT_STATE_SOURCE.json) and its [generated implementation status](TECHNICAL_STATUS.generated.md). Use the [operator runbook](OPERATIONS.md), [writer boundaries](WRITER_BOUNDARIES.md) and [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md) for operating and integration details.

The V2 development candidate composes one durable writer actor with four execution authorities signed by distinct actual verification keys, final-use verification, protected-output settlement, signed recovery and checkpoint/archive maintenance. Provider execution runs outside the writer. Signed quota/resource declarations do not establish physical capacity, actual billing or independent acceptance. The earlier main baseline `a126987b` implements a smaller subset; source and CI evidence from these revisions cannot be interchanged.

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `inference.control`

**Owner:** `inference-platform`

**Deputy:** `runtime-control`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7B-B1A-PROVIDER-BOUNDARY`

This stable document is the implementation guide for `inference.control`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own provider requests, reservations and terminal receipts while preventing raw provider escape.

The primary owner `inference-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `runtime-control` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `service`, state model `stateful` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-infer-core`
- `codex-rs/hepta-infer-worker-host`
- `codex-rs/hepta-inferd`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-infer-core`
- `codex-rs/hepta-infer-worker-host`
- `codex-rs/hepta-inferd`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-infer-core/src/lib.rs](../../../codex-rs/hepta-infer-core/src/lib.rs). Its `InferenceLedger` is an in-memory compatibility state machine with authority-denied receipts. The durable state owner is [durable_control.rs](../../../codex-rs/hepta-infer-core/src/durable_control.rs), and the exact-plan product caller and writer actor live under `hepta-infer-worker-host`. Use [generated implementation status](TECHNICAL_STATUS.generated.md) and the [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.control.md#8-current-native-implementation) for actual symbols, caller boundaries and remaining work; target signatures in the [implementation design](../../../qualification/module-execution-dossiers/detail/inference.control.md) are not a second current API registry.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `kernel.authority`
- `kernel.operations`

Authoritative write domains:

- `inference_request`
- `inference_reservation`
- `inference_receipt`

Explicitly denied capabilities:

- `raw_provider_escape`
- `memory_write`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `typed ingress`
- `policy core`
- `transactional writer`
- `bounded read projection`
- `outbox adapter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Serve cell inference through bounded shared workers with exact code/weight/adapter/tokenizer identity. Separate logical cells from resident models, account for cache misses and training reservations, and reject expired or incompatible work before dispatch. Do not assume question-conditioned embeddings are reusable merely because state text matches.

Admit circuit-linked inference with exact activation, bundle, input and resource identity. A lost inference response follows the inference owner recovery contract, not a blind replay with new weights. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: mixed-adapter batches, principal isolation, deadline/cancellation, load failure and foreground contention.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Report unique resident tensors separately from repeated invocation compute, token/shape work and latency. Bind precision, adapter inventory and representation outputs; expose no presumed end-to-end gradient through an independent inference response.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Share immutable weights/serving capacity with isolated per-consumer/workspace/bundle KV, hidden and temporary buffers. Train candidate copies separately; never mutate selected tensors through a shared optimizer. Enforce artifact consumer scope and revocation at adoption/use boundaries.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::inference_receiptV1`
- `DomainRead::inference_requestV1`
- `DomainRead::inference_reservationV1`
- `ModulePort::inference.control::inference.worker`
- `ModulePort::inference.control::neuron.runtime`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::kernel.authority::inference.control`
- `ModulePort::kernel.operations::inference.control`
- `OperationIntentV1`
- `VerifiedUseTokenWitnessV1`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `inference_receipt`
- `inference_request`
- `inference_reservation`

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The implemented surfaces have different roles:

| Surface | Current implementation | Composition boundary |
| --- | --- | --- |
| `InferenceLedger` | In-memory request/reservation state machine with `DENY_ALL` authority | No durable owner or provider caller |
| Legacy durable/native compatibility | Historical journal transitions and compatibility receipts | Production actor denies legacy execution paths |
| V2 exact-plan owner and actor | Signed bindings, write-ahead dispatch, protected settlement, recovery, retirement and checkpoints | One durable writer; cloned handles submit bounded commands to its FIFO |
| `hepta-inferd::plan` | Pure digest/deadline planner | Real enrolled-worker scheduling and daemon composition remain required |
| Neuron feature contract | Exact bounded typed request/receipt; worker projection and neuron verification | Real control port, selected worker and Agentd lifecycle composition remain required |

The actor acquires a stable lifecycle sidecar lock before opening/replaying the active journal, and retains the active generation's inode lock for compatibility. The sidecar remains owned across checkpoint replacement; never delete it to force startup. Mutations validate, append and sync before publishing state. Uncertain storage or replacement failure poisons the owner.

For native record events, `commit_native` stages only the target record through the same replay reducer instead of cloning the complete `NativeJournal`. Reservation first validates identity, the pinned budget and held-slot capacity against the complete retained map. Event serialization, the complete candidate, its return receipt and insertion key are prepared before append; only after append, flush and `sync_all` succeed does the owner install that target and its maximum-in-flight value. Rejected staging leaves authoritative state and journal bytes unchanged; uncertain append failure poisons the owner without installing the candidate. `CheckpointReference` is rejected on this path: compaction still stages the complete checkpoint separately. Reserve retains an O(retained identities) capacity scan, and the 16384 distinct-record ceiling remains; this change does not make every mutation constant-time or establish a measured throughput improvement.

Provider execution runs outside the writer. Cloning an actor handle does not open another durable owner. Separate ordinary and completion quotas feed one FIFO, with one reserved shutdown barrier. Accepted response timeout/loss does not cancel an admitted command or authorize retry/release. Immutable published metrics expose observation age and remain non-authoritative. See [writer boundaries](WRITER_BOUNDARIES.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.control.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.control.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `provider_raw_escape`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.control.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-infer-core/src/lib.rs](../../../codex-rs/hepta-infer-core/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The native worker opens one `NativeJournalWriterActor` over an absolute private journal, stable request ID and explicit pinned in-flight budget. Its lifecycle owner lock remains held while provider execution runs outside the actor. Before new admission near the byte-headroom threshold, the owner checkpoints current state and preserves predecessor journal bytes in a content-addressed archive. Indeterminate capacity remains held across compaction and restart. Released request identities also remain retained: compaction recovers byte headroom but does not remove the 16384 distinct-record ceiling.

The native worker assembles assistant text by message item identity from streamed deltas and authoritative completed snapshots. A completion replaces that item's partial text and supplies missing suffixes without duplicating already streamed text. The collector keeps bounded item metadata and output bytes, ignores foreign thread/turn events, and rejects changes after item completion; it is shared with the interruption grace path.

Exact-plan production journals store protected-output metadata rather than plaintext. Historical compatibility records and predecessor archives may contain plaintext and retain their governed privacy/retention obligations. Signed recovery requires fresh independent evidence; exceptional retirement requires revision-bound dual control. Checkpoint replay validates checkpoint content and recorded archive bindings, but does not traverse and rehash the complete predecessor archive history. Archive retention/transfer, signed vault deletion confirmation, deployed issuers, telemetry delivery and target-host qualification remain separate work. Journal deletion or a new request ID is never recovery.

Verified reconciliation/retirement proofs are rechecked for expiry at durable consumption; the recovery actor samples its own current wall clock. Retirement requires distinct actual verification public keys as well as signer/key IDs. When exact binding and current output policy admit a matching terminal observation, tokens or reported signed cost above the pre-effect quota remain recorded, capacity releases and qualification becomes `Quarantined`; this is no excess-payment authorization. Monotonic late usage can lower qualification but cannot upgrade a previously denied success. A signed terminal receipt preserves historical owner authority, or `Unverified` when absent; it cannot mint `ObservedReady` or erase prior authority loss. Protected-output metadata is revalidated against signed policy, including required reference/cipher/key fields; metadata checks do not prove actual encryption or deletion. A poisoned owner refuses mutation and capability issuance, including idempotent calls.

The writer samples application time for exact-plan bind, authorized dispatch and settlement as well as recovery commands; a time captured before queue admission cannot preserve expired authority. Checkpoint loading validates state/observation/audit consistency and real release evidence, in addition to content hashes.

New checkpoints use schema 2; schema 1 remains readable. A schema-1 signed-reconciliation record whose `ObservedReady` was manufactured without independent host evidence is downgraded to `Unverified`, retaining provider terminality/usage/output and denying that success claim. New retirement audits retain domain-separated fingerprints of the actual verification public keys. Historical retirement audits lacking those fingerprints retain their audit but hold capacity as `Indeterminate` until a fresh revision-bound independent dual-control approval replaces them. If recovered held slots exceed the pinned budget, startup fails closed and requires independent reconciliation; never edit history to make it fit. Unsupported checkpoint schemas are rejected.

Current operating and state-format references:

- [OPERATIONS.md](OPERATIONS.md).
- [CURRENT_STATE.json](CURRENT_STATE.json).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

The four regressions in [native_record_staging_tests.rs](../../../codex-rs/hepta-infer-core/src/native_record_staging_tests.rs) cover full-map held-slot admission across compaction/reopen, a late reducer failure without publication, actual append failure for existing and first-admission candidates, and identity/checkpoint rejection before append. They are source cases, not performance measurements or candidate pass receipts.

- [codex-rs/hepta-infer-core/src/durable_control_tests.rs](../../../codex-rs/hepta-infer-core/src/durable_control_tests.rs); named case: `reopens_exact_committed_state`.
- [codex-rs/hepta-infer-core/src/lib_tests.rs](../../../codex-rs/hepta-infer-core/src/lib_tests.rs); named case: `request_lifecycle_is_fenced_and_authority_free`.

- [codex-rs/hepta-infer-core/src/native_control_v2_tests.rs](../../../codex-rs/hepta-infer-core/src/native_control_v2_tests.rs).
- [codex-rs/hepta-infer-core/tests/process_crash_recovery.rs](../../../codex-rs/hepta-infer-core/tests/process_crash_recovery.rs).
- [codex-rs/hepta-infer-worker-host/src/control_actor_boundary_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/control_actor_boundary_tests.rs).

The embedded Agentd/App Server regression uses a real local `codex-exec` helper with loopback mock Responses. First build it with `cargo build --locked -p codex-exec --bin codex-exec` in `codex-rs`; this compiles the helper without launching a provider. The inference CI command sets and consolidated owner lane perform the same prerequisite build. The fixture allows up to 120 seconds for complete cold startup and the normal initialize/home-binding probe, then checks control health separately within 10 seconds; the exact nextest case has a 180-second watchdog. Worker RPC and provider deadlines remain unchanged. Bazel splits the cognitive final-use fixture into a dedicated wrapper with the helper runfile; run both worker test wrappers (or the package `:all`) to retain complete coverage.

In `codex-rs`, run `just test -p codex-hepta-infer-core -p codex-hepta-infer-worker-host -p codex-hepta-inferd`. Explicitly select the ignored `post_compaction_multi_generation_curve` maintenance soak when checking compaction longevity; its exact nextest override permits up to 600 seconds for 1024 identities across 16 real compactions and reopens, without changing request latency budgets. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.control.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `INFER-V4-T1`
- `INFER-V4-T2`
- `INFER-V4-T3`
- `MEM-READ-1-SNAPSHOT-PORT` (co-owned pre-`TurnStart` durable-stop integration)
- `P0.7B-B1A-PROVIDER-BOUNDARY`

The bootstrap package is `P0.7B-B1A-PROVIDER-BOUNDARY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `inference.control`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `INFER-V4-T1`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `runtime-control`.
- Allowed write paths:
- `codex-rs/hepta-infer-core/**`
- `codex-rs/hepta-inferd/**`
- Development predecessors:
- `P0.7B-B0-VERIFIED-USE`
- `P0.7B-B1A-PROVIDER-BOUNDARY`
- Activation predecessors:
- `P0.7B-B1B-MODEL-BOUNDARY`
- `P0.7B-B1A-PROVIDER-BOUNDARY`
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

#### `INFER-V4-T2`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `runtime-control`.
- Allowed write paths:
- `codex-rs/hepta-infer-core/**`
- `codex-rs/hepta-inferd/**`
- Development predecessors:
- `INFER-V4-T1`
- `P0.7B-B1A-PROVIDER-BOUNDARY`
- Activation predecessors:
- `INFER-V4-T1`
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

#### `INFER-V4-T3`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `runtime-control`.
- Allowed write paths:
- `codex-rs/hepta-infer-core/**`
- `codex-rs/hepta-inferd/**`
- Development predecessors:
- `INFER-V4-T2`
- `P0.7B-B1A-PROVIDER-BOUNDARY`
- `INFER-V4-T1`
- Activation predecessors:
- `INFER-V4-T2`
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

#### `P0.7B-B1A-PROVIDER-BOUNDARY`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `runtime-control`.
- Allowed write paths:
- `codex-rs/hepta-infer-core/**`
- `codex-rs/hepta-inferd/**`
- Development predecessors:
- `P0.7B-B0-VERIFIED-USE`
- Activation predecessors:
- `P0.7B-B0-VERIFIED-USE`
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

The canonical readiness overlay binds `inference.control` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `inference.control` is implemented by work package `P0.7B-B1A-PROVIDER-BOUNDARY` in:

- `codex-rs/hepta-infer-core`
- `codex-rs/hepta-inferd`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

## 18. Current writer boundary and capacity revision

See [WRITER_BOUNDARIES.md](WRITER_BOUNDARIES.md) for the actual single-FIFO owner,
independent completion quota, admitted-response uncertainty, immutable metrics,
CLI limits, capacity calculations and explicitly scoped regression evidence.
