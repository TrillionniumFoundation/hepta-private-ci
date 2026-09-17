# cognitive.store technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `cognitive.store`

**Owner:** `cognitive-platform`

**Deputy:** `durability-kernel`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-1-STORE`

This stable document is the implementation guide for `cognitive.store`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own Memory and knowledge-fact ledgers with revision, citation, correction, deletion and lineage semantics.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `durability-kernel` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `store`, state model `stateful` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-cognitive-store`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-cognitive-store`

Durable implementation package already Cargo-bound to this module:

- `codex-rs/hepta-memory`

The Cargo binding does not create a second authoritative store or change the declared primary module root. It records the existing physical owner implementation that the semantic crate and Lane C read contracts are converging on.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs); observed identifiers include `CognitiveStore`, hardened `AdmittedCognitiveStoreV2`, `append`, `get`, `snapshot_records` and `StoreReceipt`. This crate is the semantic oracle/type boundary and is not the physical database.

The real durable owner remains [codex-rs/hepta-memory/src/cognitive_store.rs](../../../codex-rs/hepta-memory/src/cognitive_store.rs), with durable memory/KG mutations in [cognitive_intelligence_writer.rs](../../../codex-rs/hepta-memory/src/cognitive_intelligence_writer.rs), provisional/verified/tombstone admission in [memory_admission.rs](../../../codex-rs/hepta-memory/src/memory_admission.rs), Lane C snapshot projection in [lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs), and exact-cut lineage paging in [lane_c_paging.rs](../../../codex-rs/hepta-memory/src/lane_c_paging.rs).

Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Current durable integration: the physical memory/source writer remains the existing SQLx `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`. Existing memory/source/KG write APIs remain the only durable writers. The in-memory V2 store in this module is not a durable backend and must not be introduced as a second database.

`codex-rs/hepta-memory/src/lane_c_snapshot.rs` projects one authorized SQLite transaction into the new cognitive snapshot and read types. `codex-rs/hepta-memory/src/lane_c_paging.rs` traverses long immutable history from that same owner in whole-memory pages bound to one exact logical owner cut; it adds no database and authorizes no pruning. See [LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) for exact ID/frontier mapping, bounded materialization, lineage paging, correction/deletion propagation, reopen/rollback-witness behavior and the PERF-DURABLE measurement source.

The separate descriptor-safe `open_with_recovery` prerequisites remain unresolved. An ordinary reopen plus independently retained cut comparison must not be reported as full recovery admission. Writable recovery remains fail-closed until SQLite can retain descriptor-safe main/WAL/SHM identity across the writable connection, bind a current writer fence, and prevent an unfenced pathname reconnect.

Direct dependencies:

- `cognitive.types`
- `kernel.operations`

Authoritative write domains:

- `memory_ledger`
- `knowledge_fact_ledger`

Explicitly denied capabilities:

- `federated_network_read`
- `model_call`
- `learning_policy_write`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `schema and migration owner`
- `transactional writer`
- `snapshot read port`
- `integrity and lineage verifier`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

The hardened V2 semantic boundary rejects contradicted candidates and rejects an unverified inference before it can become a live `Fact`. Ordinary live admissions cannot consume the record or idempotency-journal capacity reserved for terminal tombstones. Image export/reopen cross-validates intent identity, receipt/record binding, sequence, memory frontier, tombstone frontier, fact frontier and final snapshot state in addition to the existing image checksum.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::knowledge_fact_ledgerV1`
- `DomainRead::memory_ledgerV1`
- `ModulePort::cognitive.store::knowledge.graph`

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::cognitive.types::cognitive.store`
- `ModulePort::kernel.operations::cognitive.store`
- `OperationIntentV1`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

The semantic and durable mutation contracts are not yet identical. V2 distinguishes `Episode`, `Fact`, `Preference` and `Procedure`, while the current durable `memory_revisions` schema does not persist that kind and eligible owner memories are projected to Lane C as `Fact`. Production write convergence therefore requires an explicit compatible schema/contract decision, global expected-cut CAS in the same durable transaction, and a durable intent-identity journal. Any durable schema migration also updates and independently verifies the recovery schema oracle; an adapter must not hide this mismatch.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `knowledge_fact_ledger`
- `memory_ledger`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

The physical SQLite owner stores immutable sources, memory revisions, citations, current heads, structured fact sets, KG projection receipts and deletion lineage. `remember_with_kg`, `correct_with_kg` and `forget_with_kg` mutate cited source, memory revision, structured facts and complete projection inside one SQLite transaction. `memory_admission.rs` persists model/compaction candidates as provisional state and requires explicit content-bound evidence plus CAS before verification; a provisional candidate is not silently promoted to an authoritative fact.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary. Because recovery hashes the registered logical schema, migration changes and recovery-oracle changes are one reviewed compatibility boundary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

Exact-cut lineage paging is source-implemented without deleting authoritative rows. Physical archive/pruning retention remains separate work: removed segments require a durable predecessor anchor and tombstone/deletion-frontier continuity proof before any authoritative row can be discarded.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, transaction boundary, paging boundary and product read caller. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md).

The read side already has a named source-level product composition. `hepta-agentd/src/cognitive_context.rs` acquires a durable owner cut, executes the bounded cognitive read path, intersects results with the existing SQLite retrieval provider, exact-matches record identity/revision/content digest, and revalidates the owner cut before publication. `hepta-infer-worker-host/src/native_app_server.rs` consumes that path before model execution. This is source-level I3 read composition, not target-host acceptance or production-write activation.

The product write side remains uncomposed. Qualification write paths and qualification-only local memory sagas do not grant production caller authority. A production write adapter must reuse the existing SQLite writer and an externally verified authority/fence; it must not route durable facts through the in-memory V2 oracle.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

The current recovery code can bind DB/WAL/SHM filesystem identity and compare an independently retained exact logical current-cut witness. Writable recovery intentionally remains unavailable because the current SQLite stack cannot yet prove descriptor-backed writable identity, current writer fencing and reconnect safety. `open_with_recovery` must continue failing closed until those prerequisites are implemented and fault-tested; ordinary `CognitiveStore::open` is not a recovery fallback.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API.

The full Lane C snapshot remains bounded to 16,384 immutable revisions, 65,536 citations and 65,536 source rows in one exact scope. Long-history traversal uses [lane_c_paging.rs](../../../codex-rs/hepta-memory/src/lane_c_paging.rs), which pages complete memory histories and is bounded to 256 memory identities and 4,096 revisions per page. It fails rather than splitting one ancestry chain.

[cognitive_store_perf.rs](../../../codex-rs/hepta-memory/examples/cognitive_store_perf.rs) is the executable PERF-DURABLE measurement source for the canonical SQLite owner. It measures real durable write latency distribution, DB+WAL+SHM byte growth, owner snapshot materialization, reopen and exact-cut revalidation, and emits a machine-readable measurement record. The harness is not a target-host performance receipt; exact source, binary/artifact and host identity must be retained with each run.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The physical writer remains `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`. The new crate supplies an in-memory semantic oracle and V2 types, not a replacement durable backend. Use the existing owner snapshot adapter, exact-cut lineage pager and independent cut witness; descriptor-safe `open_with_recovery` still requires its unimplemented writable VFS/currentness/fence prerequisites.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- [codex-rs/hepta-memory/examples/cognitive_store_perf.rs](../../../codex-rs/hepta-memory/examples/cognitive_store_perf.rs).

The product read path is composed through Agentd and the inference worker host. That source composition does not change the production write, recovery, independent acceptance, activation or release state.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-cognitive-store/src/lib_tests.rs](../../../codex-rs/hepta-cognitive-store/src/lib_tests.rs); named case: `append_and_correction_are_predecessor_fenced`.
- [codex-rs/hepta-cognitive-store/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs); admission, deletion, retry and image/reopen semantics.
- [codex-rs/hepta-cognitive-store/src/hardening_tests.rs](../../../codex-rs/hepta-cognitive-store/src/hardening_tests.rs); verification gating, terminal capacity reserve, bounded intent journal and image cross-link checks.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs); named case: `existing_sqlite_writes_are_readable_by_new_lane_c_after_reopen` plus correction/deletion/cut tests.
- [codex-rs/hepta-memory/tests/lane_c_paging.rs](../../../codex-rs/hepta-memory/tests/lane_c_paging.rs); whole-history paging, tombstone-frontier continuity and stale-cut rejection.
- [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs) and [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs); named product read composition and qualification-gated write behavior.

In `codex-rs`, run `just test -p codex-hepta-memory -p codex-hepta-cognitive-store -p codex-hepta-agentd`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) separately labels target acceptance designs.

For target-host durable measurements, run the measurement source rather than copying design ceilings into evidence:

```sh
cargo run --locked -p codex-hepta-memory --example cognitive_store_perf -- 1000
```

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-1-STORE`
- `MEM-8-PRODUCTION-WRITER`

The bootstrap package is `MEM-1-STORE`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

The current production-closure sequence is: harden semantic admission/deletion invariants; retain one SQLite owner; provide bounded exact-cut history traversal; measure that owner; then close descriptor-safe writable recovery and V2/durable mutation-contract convergence before activating a production write caller. Read composition may remain usable independently without widening write authority.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

The read path has named source-level product callers, but this does not activate the production writer. Production mutation activation additionally requires the durable schema/contract convergence, current writer fence, durable intent identity, descriptor-safe recovery, exact-candidate qualification and externally governed acceptance applicable to that effect boundary.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `cognitive.store`, the current repository contains a semantic oracle, a real SQLite owner, durable admission state, exact-cut snapshot/read composition, bounded lineage paging and a performance measurement source. It does **not** yet establish descriptor-safe writable recovery, fully converged V2/durable write semantics, an authenticated production memory-write caller, target-host PERF-DURABLE acceptance, independent acceptance, activation or release.

This document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-1-STORE`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-cognitive-store/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-0-TYPES`
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

#### `MEM-8-PRODUCTION-WRITER`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-cognitive-store/**`
- Development predecessors:
- `MEM-1-STORE`
- Activation predecessors:
- `MEM-1-STORE`
- `P0.7B-B4-CALLSITE-PROOF`
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

The canonical readiness overlay binds `cognitive.store` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `EMB-1-SENSOR-BUS-BODY-SCHEMA`

## 17. Source implementation receipt

The bootstrap source-location obligation for `cognitive.store` is implemented by work package `MEM-1-STORE` in:

- `codex-rs/hepta-cognitive-store`

The physical durable owner implementation is carried by the existing Cargo-bound `codex-rs/hepta-memory` package; this does not alter the declared primary source root or grant a second writer.

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
