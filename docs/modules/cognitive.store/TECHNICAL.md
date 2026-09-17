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

The declared root remains the semantic/conformance owner. The current production integration deliberately reuses cross-owner durable/runtime components rather than creating a second database:

- `codex-rs/hepta-memory/src/authoritative_store.rs` — canonical production authority façade over the existing SQLite backend.
- `codex-rs/hepta-memory/src/cognitive_store.rs` — durable `cognitive_1.sqlite3` backend.
- `codex-rs/hepta-agentd/src/runtime.rs` — named product/runtime open caller.
- `codex-rs/hepta-agentd/src/production_writer_host.rs` — externally-authorized production-writer caller.
- root `CALLERS.toml` — closed-world callsite policy for those privileged boundaries.

These are integration evidence roots, not a silent expansion of the declared module root. The module registry remains authoritative for root ownership.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish operator acceptance, selection, promotion or release. Any declared source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs). It is now explicitly documented as a bounded in-memory semantic/conformance model rather than production persistence. Its V2 authorization, writer-fence, intent-idempotency, revision, tombstone, snapshot and image-reopen semantics remain useful as a deterministic oracle.

The canonical production entry point is [AuthoritativeCognitiveStore](../../../codex-rs/hepta-memory/src/authoritative_store.rs), which wraps the existing SQLite `hepta-memory::CognitiveStore`. Product code must not treat the V2 `BTreeMap` state or `export_image`/`reopen` helpers as a second durable authority.

Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) and the [implementation map](./IMPLEMENTATION_MAP.json) for the current candidate claim boundary.

## 3. Boundary, responsibilities and non-goals

Current durable integration has one physical owner database: `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`. `AuthoritativeCognitiveStore` is the canonical product/runtime façade over that database. `codex-rs/hepta-memory/src/lane_c_snapshot.rs` projects one authorized SQLite transaction into cognitive snapshot/read types; it does not synchronize a second database. The in-memory V2 store is a conformance model only.

Agentd startup holds its per-Agent writer lock for the process lifetime. `AgentdConfig::load` fails closed if another Agentd already owns the registered Agent writer lock. The production outbox/effect writer has an additional externally-authorized lease and OS writer lock. SQLite revision/predecessor CAS remains the mutation-level conflict boundary. Together these prevent a second product runtime from becoming a parallel cognitive writer while preserving deterministic retry/conflict semantics.

See `codex-rs/hepta-memory/LANE_C_SQLITE.md` for exact ID/frontier mapping, bounded materialization, correction/deletion propagation and reopen/rollback-witness behavior.

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

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never creates a second durable store to mirror the SQLite authority. Cross-owner mutation follows local transaction, durable intent, destination deduplication, acknowledgement and fenced reconciliation where the owning protocol requires it.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, treating an in-memory image as disk durability, or converting qualification evidence into deployment authority.

## 4. Internal architecture and component decomposition

The bounded components are:

- `semantic/conformance model` — `hepta-cognitive-store` V1/V2; no production persistence.
- `authoritative production façade` — `hepta-memory::AuthoritativeCognitiveStore`.
- `SQLite schema and migration owner` — existing `hepta-memory::CognitiveStore`.
- `transactional writer` — revision/source/fact/tombstone mutations in one SQLite boundary.
- `snapshot read port` — `lane_c_snapshot` and retrieval/read adapters.
- `integrity and lineage verifier` — schema/object checks, revision/citation constraints, current-cut witness and read-only recovery admission.

Ingress validates identity, version, size, scope and revision before domain logic. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues, implicit store fallback and dual writes into the V2 conformance model are prohibited.

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

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `memory_ledger`
- `knowledge_fact_ledger`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

### Memory authority

Memory/source revisions, corrections and tombstones are durable SQLite records. Mutations are revision-bound, identical retries are idempotent where the owning operation defines an identity, and changed semantics under a reused identity conflict. Citations and predecessor/revision relationships preserve lineage and prevent resurrection.

### Knowledge-fact authority

The production knowledge-fact ledger is **not an independently writable second database or table family detached from memory authority**. It is an immutable revision-scoped fact set attached to an authoritative memory revision:

- `kg_revision_fact_sets` is keyed by `(memory_id, memory_revision)` and binds extractor contract, fact-set digest, source citation and declared entity/relation counts.
- `kg_revision_entities` and `kg_revision_relations` are immutable rows foreign-keyed to that exact revision fact set and its citations.
- no-update/no-delete triggers make revision fact rows append-only evidence.
- `kg_projection*` tables are rebuildable generation projections; they are not source authority.

V2 `MemoryKind::Fact` and `knowledge_fact_frontier` model these semantics in memory. They do not define a second durable production ledger.

### Migration and cutover

The current authority-closure candidate intentionally performs **no database-format migration**. The durable SQLite database remains unchanged. Cutover is only a call-path change: Agentd runtime and production-writer construction cross `AuthoritativeCognitiveStore`; V2 remains a non-durable oracle. Therefore there is no copy/backfill/dual-write window and no second-store count/hash reconciliation to perform for this change.

Rollback of this call-path cutover reverts the caller routing only. It must not restore an old `cognitive_1.sqlite3` image, because no data transformation occurred. Future schema migrations still require deterministic checksums, stop/drain/fence, off-route validation, count/digest/frontier reconciliation and a validated reverse or forward-compatible rollback path.

## 7. Runtime, concurrency and transaction model

There are three complementary fences:

1. **Agentd process ownership:** `AgentdConfig::load` obtains the Agent-local `writer_lock()` and rejects a second live Agentd writer. `run()` retains that file for its lifetime.
2. **Production durable-writer ownership:** `ProductionDurableWriter` verifies an external authority lease and obtains its own OS writer lock before mutation/effect dispatch.
3. **SQLite mutation correctness:** revision/predecessor CAS, transactions, immutable revision/fact rows and tombstone lineage reject stale/conflicting mutations.

The cognitive remember/correct/forget tools execute inside the one Agentd-owned App Server runtime and mutate the one SQLite authority. They do not dual-write the V2 conformance model. Repository closed-world caller policy prevents Agentd production files from reintroducing raw `CognitiveStore::open` or direct `ProductionDurableWriter::open` construction where the authoritative façade is required.

The [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) contains exact call paths and remaining recovery limits.

## 8. Failure semantics, recovery and rollback

Normal canonical open performs schema/migration/integrity checks and fails closed on corrupt/unavailable state. It does **not** claim to prove that a cold database is the newest acknowledged image after external rollback/restore.

The implemented recovery boundary is intentionally split:

- authenticated exact-current-cut **read-only** cold-image admission is available through `CognitiveStore::open_read_only_recovery`, exposed by `AuthoritativeCognitiveStore::open_recovered_read_only`;
- writable corruption/rollback recovery remains fail-closed because descriptor-backed SQLite/VFS connection ownership and an independently current writer-fence/currentness witness are not yet implemented;
- ordinary reopen, V2 image reopen or comparing a witness retained inside the suspect database must not be described as writable recovery admission.

A source library or fixture cannot stand in for those missing durable recovery prerequisites. The stronger recovery blocker remains explicitly visible in the implementation map and qualification dossier.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) specifies the algorithm, pilot ceilings and capacity fixtures. V2 in-memory limits are conformance-model limits, not SQLite production capacity claims. Production measurements must use the selected Agentd/SQLite host and include WAL growth, transaction latency, snapshot retention, fact materialization and reopen behavior.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The physical authority is `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`; `AuthoritativeCognitiveStore` is the canonical product façade. The `hepta-cognitive-store` crate supplies in-memory semantic/conformance models and must never be monitored or backed up as if it were production persistence.

Operational signals should distinguish normal open, schema/integrity failure, Agentd writer-lock rejection, stale revision/CAS conflict, production authority rejection, read-only recovery admission and writable-recovery-unavailable. Do not collapse these into one generic store error.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md)
- [qualification cognitive.store implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md)
- [implementation map](./IMPLEMENTATION_MAP.json)

## 12. Verification and qualification

Current focused source tests include:

- `codex-rs/hepta-memory/src/authoritative_store.rs::authoritative_open_reopens_real_sqlite_state` — writes durable SQLite state, closes the pool, reopens it and compares the exact current-cut witness.
- `codex-rs/hepta-memory/src/authoritative_store.rs::authoritative_writer_fails_closed_on_second_live_owner` — proves a second live production writer is fenced.
- `codex-rs/hepta-agentd/src/config_tests.rs` duplicate-writer case — proves a second Agentd for the same registered home is rejected by the Agent-local writer lock.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs) — real SQLite snapshot/reopen/frontier behavior.
- [codex-rs/hepta-cognitive-store/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs) — semantic authorization/fence/idempotency/revision/tombstone/image checks.
- `codex-rs/hepta-agentd/examples/h4_persistent_writer.rs` and its process harness — persistent prepare/recover qualification across a new pool/process generation, including indeterminate dispatch replay behavior.

These names are test identities, not pass receipts. Exact-candidate and synthetic-merge Actions must finish successfully before `productExecutionProved` can become true.

In `codex-rs`, the focused package command remains `just test -p codex-hepta-memory -p codex-hepta-cognitive-store -p codex-hepta-agentd`. The repository Actions remain authoritative for exact-head/merge qualification.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-1-STORE`
- `MEM-8-PRODUCTION-WRITER`

The bootstrap package remains `MEM-1-STORE`. The authority-closure integration changes the product call path without changing the durable database format. Work-package registry states below remain canonical planning data and are not rewritten merely because a candidate branch implements integration work.

Source implementation completes only when public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Production implementation and product composition are recorded separately from independent acceptance, activation, promotion and release.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. The current candidate names Agentd runtime startup and Agentd production-writer host as product call sites, enforced by root `CALLERS.toml`.

Compatibility adapters are temporary. The V2 conformance model is not a compatibility database and is never synchronized with SQLite. Retirement of any old production call path requires closed-world caller proof, exact-candidate qualification and rollback rehearsal. Historical durable records remain interpretable because this authority cutover does not change their schema.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code and candidate tests. Production-path implementation requires one canonical durable authority and named product callers. Qualification requires current exact-candidate evidence. Writable recovery qualification, independent acceptance, selection, promotion and release are separate states.

For the current authority-closure candidate:

- one durable production database: implemented;
- one explicit production authority façade: implemented;
- Agentd runtime/product open composition: implemented candidate;
- single Agentd process writer fence: implemented and source-tested;
- production durable-writer fence: implemented and source-tested;
- knowledge-fact durable representation: implemented as immutable revision-scoped fact sets;
- real SQLite close/reopen evidence: implemented as source test;
- dual-write migration/backfill: not applicable because no second database is introduced;
- descriptor-safe writable corruption/rollback recovery: **not yet qualified/implemented**;
- exact-candidate CI, independent acceptance, activation and release: separate gates.

This document itself grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

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

The bootstrap declared-root obligation for `cognitive.store` remains implemented by `MEM-1-STORE` in:

- `codex-rs/hepta-cognitive-store`

The current authority-closure candidate additionally composes the already-existing durable owner/runtime through `hepta-memory`, `hepta-agentd` and closed-world `CALLERS.toml`; it does not create a new durable root or database.

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. The Agentd process qualification and blocking CI supply additional runtime evidence. These receipts grant no independent acceptance, selection, promotion, merge or release authority.
