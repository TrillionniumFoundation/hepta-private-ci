# inference.control technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

The native App Server worker now calls the same durable control owner for explicit local-slot admission, persisted dispatch identity, cancellation intent and actual observed settlement. Optional observed tokens remain unknown when absent; restarting a possibly dispatched request never replays it. This does not close economic quota, local weights/device or trusted post-crash provider-reconciliation gaps. The [native host guide](../../readiness/LANE_B_NATIVE_HOST.md#durable-inference-journal) specifies journal limits, CLI requirements and recovery semantics.

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
- `codex-rs/hepta-inferd`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-infer-core`
- `codex-rs/hepta-inferd`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-infer-core/src/lib.rs](../../../codex-rs/hepta-infer-core/src/lib.rs); observed identifiers include `InferenceLedger`, `InferenceRequest`, `RequestRecord`, `submit`, `reserve`, `complete`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.control.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.control.md) for the implemented subset and remaining product work.

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

The [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.control.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.control.md).

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

The native worker retains one `DurableInferenceControl` per private journal. `open` acquires `<journal>.writer.lock` before opening or replaying the data file and holds it for the owner's entire lifetime, including model execution and checkpoint replacement. The data inode is also locked to exclude an already-running pre-maintenance owner. A second owner fails with `WriterUnavailable`; callers must share the retained owner, not repeatedly open independent handles. Never unlink the writer sidecar while an owner may exist. Stop older binaries before enabling checkpoint publication; mixed-version writers and old-inode handles are not a supported upgrade protocol.

Ordinary mutations stage only their affected record, append and sync, then publish the record and derived counters. Write/sync uncertainty poisons that owner; no result is published to memory and reopening must reconcile the persisted source. Native admission reserves one maximum encoded terminal frame plus bounded metadata per non-released request. Metadata liability decreases through dispatch, start and cancellation. A provider terminal releases the execution slot exactly once; when observed usage is still absent it retains a separate 4 KiB first-usage liability. A matching usage-only observation consumes that liability through a small `RefineUsage` frame bound to the exact predecessor revision, rather than re-appending the immutable terminal body. Other terminal fields are compared in full and retain normal conflict validation. Subsequent known-usage refinements remain subject to ordinary capacity admission; this is not an unlimited billing log. New work cannot spend another request's terminal reserve. Legacy journals already overcommitted under the former fixed threshold reopen in drain-only capacity posture: liability-reducing transitions may proceed within the physical byte limit, but new admissions remain blocked until enough responsibility is released. This is not a retroactive guarantee for legacy admissions.

`journal_capacity_status()` reports physical bytes, reserved future bytes, admissible bytes and retained record counts. `compact_journal()` validates one current-state checkpoint per retained legacy/native identity, fsyncs a same-directory replacement, renames it under the stable writer lock and fsyncs the parent directory on Unix. Admission/append can compact superseded frames before rejecting capacity. A pre-rename crash retains the old journal; a post-rename crash recovers the new complete image. Failed directory sync fences the owner. Stale unpublished temporary files are removed only after acquiring writer ownership. Checkpoint framing declares the retained identity count and requires an end marker, so truncation at a complete row cannot silently become a smaller valid state. These structural checks are not signatures or rollback authority. Checkpoint replay validates state shape once without allocating work proportional to the historical revision. Checkpoint serialization borrows retained bodies. Recovery rejects an already oversized file before parsing and batches state-free newline runs while retaining the total-byte and per-line bounds. An expanded snapshot cannot consume the future bytes already reserved for active work.

The 64 MiB file, 8 MiB encoded-line and configured identity limits remain hard bounds. Compaction reclaims superseded events, not retained request identities or final output text. The pinned slot limit is an upper bound, further constrained by byte liability. Unknown execution retains its slot; absent usage remains unknown. Content-addressed external archives, terminal-identity garbage collection, trusted backup anti-rollback, provider billing/economic quota, hardware authority and a standalone control daemon remain separate, unproved obligations. Local checkpoint tests must not be described as deployed-provider acceptance or full long-horizon storage qualification.

Current operating and state-format references:

- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-infer-core/src/durable_control_tests.rs](../../../codex-rs/hepta-infer-core/src/durable_control_tests.rs); named case: `reopens_exact_committed_state`.
- [codex-rs/hepta-infer-core/src/lib_tests.rs](../../../codex-rs/hepta-infer-core/src/lib_tests.rs); named case: `request_lifecycle_is_fenced_and_authority_free`.

In `codex-rs`, run `just test -p codex-hepta-infer-core -p codex-hepta-inferd`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.control.md) separately labels target acceptance designs.

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

## Incremental commit staging and history measurements

The exclusive-writer journal stages only the affected request before append,
fsync and in-memory publication. It does not clone the complete request history
for each mutation. Active reservations are maintained by the event reducer and
rebuilt during replay; terminal refinements do not release capacity twice.
Exact retries retain the original record and journal bytes.

The shared architecture/maintenance recipe is
`scripts/hepta_inference_owner_checks.py`. It runs real history growth, exclusive
owner handoff and process-loss recovery through `just test`, with zero retries
and at least one observed passing test per command. Later diagnostics still run
when an earlier command fails.

The growth measurement retains 64/256/1024/4096 requests and real durable
transitions. It records RSS, disk bytes, append percentiles, lookup and recovery.
Its bounded test watchdog is not a deployment latency SLO. Total history remains
retained: the checkpoint crash/capacity tests qualify superseded-frame reclamation,
not identity deletion, multi-writer delta replay or million-record operation.
The owner recipe executes the checkpoint, migration, capacity and cross-process
writer regressions independently; a failed command does not hide later results.

### Native qualification runtime prerequisite

The cross-crate Agentd/worker test uses the real embedded App Server, a real Unix socket and SQLite owner, with an HTTP model fixture; it does not qualify a deployed model provider. Build the same candidate's dispatch-capable `codex-app-server` binary with `cargo build --locked --manifest-path codex-rs/Cargo.toml -p codex-app-server --bin codex-app-server`, then pass its absolute path as `HEPTA_TEST_CODEX_EXE` to `just test --locked --retries 0 -p codex-hepta-infer-worker-host --lib -E 'test(native_) | test(final_use_authorizer::)'`. The fixture rejects missing/non-file runtime paths rather than supplying the test harness as a fake executable. Maintenance CI records that build, binary digest and the actual tests independently for source-head and prospective merge. All root-level commands use the toolchain selected by `codex-rs/rust-toolchain.toml`, not the runner default. The real Agentd/SQLite/Unix-socket witness also has its own required execution record, so unrelated passing tests cannot mask its absence or failure. Its structural ordering test follows the authorized observed-send helper and is not a substitute for the executed revocation races.

The first-usage reserve is reconstructed after reopen and checkpoint. The regression matrix includes a maximum terminal body at the physical byte boundary, exact retry without another append, stale predecessor, decreasing usage, terminal body/identity mutation, failed append without in-memory publication, and replay of older full-observation usage frames. State-format upgrades require stopping old writers: older binaries may reject the new usage-delta event and are not a supported rollback reader.
