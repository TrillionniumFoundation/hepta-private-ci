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

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs). The semantic V2 surface includes `AdmittedCognitiveStoreV2` and exact-cut snapshot paging; the canonical production façade re-exports `DurableCognitiveStore` and production writer/recovery types from [durable.rs](../../../codex-rs/hepta-cognitive-store/src/durable.rs) without creating a second database. The physical implementation remains [hepta-memory::CognitiveStore](../../../codex-rs/hepta-memory/src/cognitive_store.rs), and the named product caller is [AgentdProductionWriterHost](../../../codex-rs/hepta-agentd/src/production_writer_host.rs). These are source bindings; exact-candidate execution, independent acceptance, activation and release remain separate evidence states.

## 3. Boundary, responsibilities and non-goals

Current durable integration: the physical memory/source writer remains the
existing SQLx `hepta-memory::CognitiveStore`. Its
`codex-rs/hepta-memory/src/lane_c_snapshot.rs` adapter projects one authorized
SQLite transaction into the new cognitive snapshot and read types; it does not
add a second writer or synchronize a second database. The in-memory V2 store in
this module is not a durable backend. See
`codex-rs/hepta-memory/LANE_C_SQLITE.md` for exact ID/frontier mapping, bounded
materialization, correction/deletion propagation, and reopen/rollback-witness
behavior. Writable `open_with_recovery` now uses retained file descriptors,
a shared/exclusive store fence, bounded database/WAL/journal copying into a fresh
private generation, exact current-cut comparison, SQLite integrity/checkpoint
verification, an externally verified production-authority fence, and atomic active-
generation publication. Ordinary `open` still has no independent current-cut
proof and must not be reported as equivalent recovery admission.

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

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `knowledge_fact_ledger`
- `memory_ledger`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md). Descriptor-bound writable recovery is source-implemented, but an independently authenticated current-cut witness and externally verified production authority remain mandatory host inputs; source fixtures cannot manufacture either fact or replace an external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) specifies the algorithm and pilot ceilings. Current native bounds are enforced in [hepta-cognitive-store](../../../codex-rs/hepta-cognitive-store/src/lib.rs) and [Lane C SQLite](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md). The durable measurement executable [cognitive_store_perf.rs](../../../codex-rs/hepta-memory/examples/cognitive_store_perf.rs) records cold-open, per-commit p50/p95/p99/max, database/WAL/journal bytes, snapshot materialization, recovery-anchor cost and reopen cost. Consolidated source CI runs both a 256-record latency sample and a 16,384-record maximum-retained profile when the durable owner changes. Measurements are exact-run artifacts, not prose claims or deployment thresholds.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The physical writer remains `hepta-memory::CognitiveStore` over `cognitive_1.sqlite3`; `hepta-cognitive-store::durable` is the canonical façade and does not duplicate state. Lane C exposes both bounded whole-scope snapshots and proof-bound durable pages that keyset-page current heads while reconstructing complete ancestry for each selected head. Writable `open_with_recovery` is descriptor-bound and fail-closed: it copies retained database/WAL/journal bytes into a private generation, verifies the independent exact current cut and production authority/fence, checkpoints the copy, and atomically publishes the active generation.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-cognitive-store/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs): verified-only admission, reserved tombstone capacity, bounded retry journal, cross-object image validation and exact-cut page cursors.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs): durable owner writes, correction/deletion ancestry, proof-bound paging, reopen and rollback-cut checks.
- [codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs): descriptor-bound writable recovery, exclusive fencing, current-cut rejection and hostile filesystem identities.
- [codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs](../../../codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs): named Agentd product host through the canonical cognitive-store façade.
- [codex-rs/hepta-cognitive-store/src/lib_tests.rs](../../../codex-rs/hepta-cognitive-store/src/lib_tests.rs); named case: `append_and_correction_are_predecessor_fenced`.

In `codex-rs`, run `just test -p codex-hepta-memory -p codex-hepta-cognitive-store`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-1-STORE`
- `MEM-8-PRODUCTION-WRITER`

The bootstrap package is `MEM-1-STORE`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `cognitive.store`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

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

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
