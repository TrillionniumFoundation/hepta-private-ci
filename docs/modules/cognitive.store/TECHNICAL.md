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

Own the Memory ledger and its memory-revision-bound authoritative knowledge-fact subledger with citation, correction, deletion and lineage semantics. Knowledge facts are committed with a specific Memory revision; they do not form a second independently writable fact-history authority.

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

The registered primary source is [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs). The semantic V2 surface includes `AdmittedCognitiveStoreV2`, exact-cut snapshot paging, and shadow-only canonical `MemoryEventV1` co-observation through `append_admitted_with_canonical_shadow`; the canonical production façade re-exports `DurableCognitiveStore` and production writer/recovery types from [durable.rs](../../../codex-rs/hepta-cognitive-store/src/durable.rs) without creating a second database. The physical implementation remains [hepta-memory::CognitiveStore](../../../codex-rs/hepta-memory/src/cognitive_store.rs), and the named product caller is [AgentdProductionWriterHost](../../../codex-rs/hepta-agentd/src/production_writer_host.rs). These are source bindings; exact-candidate execution, independent acceptance, activation and release remain separate evidence states.

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
- `knowledge_fact_ledger` — a memory-revision-bound fact-set subledger stored atomically with the owning Memory revision, not an independently writable second ledger

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

### Shared experience target: publish through the existing owner

Extend the existing source/Memory owner with scoped contribution admission, not
another shared fact store. The physical source writer and Memory-revision-bound
fact subledger retain their current atomicity. Producer Agent identity, durable
shard identity, owner epoch, source revision, publication audience and training
purpose are distinct. The current AgentPrivate/WorkspacePrivate scope encoding is
unchanged; any new shared audience/export metadata needs registered versioned
contracts and migrations before product use. Do not erase AgentId from existing
stable IDs or reinterpret an old private scope as common data.

The target ingress validates exact policy/current source, content bounds, provenance,
allowed raw-read/training/derived-use scopes and expected predecessor before
idempotent admission. Store a permitted derived copy or a resolvable owner reference
with original lineage; that publication is not an independent corroboration. Export
intent and local state commit atomically where the existing owner permits; remote
apply/ack uses the existing cross-owner protocol, never a pretend multi-DB transaction.
Contribution attempts cannot replace another owner or open their writable file.

A share/read view may select many owner shards while each mutation has one fenced
writer. Stable shard data outlives a temporary Agent; retirement transfers/archives
it with current-cut and ownership evidence rather than copying an active SQLite/WAL
into a new identity. Snapshot references are bounded by count/bytes/frontier and
freshness. Incomplete, revoked, schema-incompatible and unreachable sources retain
explicit dispositions. Corrections and deletion flow to derived views/artifacts;
retained audit links never justify retaining prohibited payload. Full semantics:
[shared HNMF](../../hnmf/TECHNICAL.md#authorized-contribution-and-shared-view-publication).
These are planned extensions; current source/product states below remain unchanged.

### Implemented same-host shared-use subset

`CognitiveStore::{grant_shared_experience,read_shared_experience,
revalidate_shared_experience,revoke_shared_experience}` uses the existing SQLite
owner, exact Memory revision and separately bound Recall/Replay purposes.
Replay also binds parameter scope and artifact consumer. This is a local owner
API, not a new cross-host protocol or public Memory scope.

Migration `0016_shared_experience_active_capacity.sql` adds a current-head quota
projection inside the same SQLite owner. Immutable policy events remain the
source of authority and predecessor identity; expiry or revocation does not delete
that history. `MAX_ACTIVE_POLICY_IDENTITIES` limits currently unrevoked, unexpired
grants, not every identity ever observed. A new identity or an expired/revoked
identity returning to use must acquire a slot; renewing an already-live identity
uses its existing slot. Withdrawal and exact retries remain available at the active-slot limit.
The admission transaction samples expiry after acquiring the writer, so waiting
behind another writer cannot admit an already-expired request.

The partial expiry index bounds each admission count by the live quota. A trigger
updates the projection with the event in the same transaction; direct deletion or
substitution is rejected. Startup/recovery checks the projection against the
latest immutable event for every identity and rejects mismatches rather than
silently accepting an undercount. The migration backfills existing history.
This removes the historical-identity admission limit, not historical disk cost:
retained history and startup verification still grow with the owner history;
checkpoint/archival and a sustained-history SLO are not claimed by this change.

The immutable policy log permits 1024 ordinary revisions and reserved terminal
revision 1025. Renewal exhaustion cannot prevent withdrawal; the final slot cannot
contain an active grant. Repeated withdrawal and reopening preserve rejection.
`SharedExperienceUseV1::source_support_digest` binds owner, Memory identity,
revision and content: equal text in another record is not the same training source.
Permission and source currentness are checked again at consumer use. This subset
accepts current verified evidence, not general historical Replay eligibility.

Source: [shared_experience.rs](../../../codex-rs/hepta-memory/src/shared_experience.rs).
Tests: [shared_experience_tests.rs](../../../codex-rs/hepta-memory/src/shared_experience_tests.rs).
Capacity/recovery regressions: [shared_experience_capacity_tests.rs](../../../codex-rs/hepta-memory/src/shared_experience_capacity_tests.rs).
These tests do not establish OS isolation, cross-host enrollment or model unlearning.

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

Production semantic mutations additionally bind the live authority grant digest, authority epoch, owner epoch, writer lease generation, semantic input digest, expected predecessor revision, authoritative source revision, and final write digest into the existing append-only local event/outbox journal. Admission, the source/Memory/fact/projection mutation, and the terminal committed provenance marker share one `BEGIN IMMEDIATE` transaction. A failure after admission but before semantic commit therefore rolls back the provenance rows together with the domain mutation; a successful production receipt is queryable as a terminal committed occurrence and carries no external-effect authority.

`knowledge_fact_ledger` is physically the immutable `kg_revision_fact_sets` / `kg_revision_entities` / `kg_revision_relations` subledger keyed by the owning `(memory_id, memory_revision)`. A correction creates a successor Memory revision and its complete successor fact set; a forget creates the tombstoned Memory revision and an empty fact set. There is no independent fact revision head, CAS domain, or writer. `knowledge.graph` consumes this authoritative subledger and publishes `knowledge_graph_projection`, which is rebuildable and never becomes the fact source of truth.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

### Live use and deterministic operation results

Production mutations now acquire a verifier-owned `ProductionAuthorityUseGuard`
after the SQLite writer lock and retain it through durable commit. The default
`ProductionAuthorityVerifier::enter_use` rejects point-in-time-only verifiers.
Revocation acknowledgement drains earlier holds; queued requests cannot reuse a
stale preflight check. A cancelled response waiter does not release the hold
before the owner commit task finishes. Receipt validation precedes commit.

`ProductionDurableWriter::cognitive_mutation_result` and the matching Agentd host
method observe the original operation and compact committed-result metadata.
Identical retries return typed `ObservedResult`, not another mutation. Released
or expired execution authority does not itself erase the historical result;
owner, occurrence integrity and successor fence checks still apply. Full normal
bootstrap/witness coordination and recoverable history archival are not claimed.
See [production convergence](PRODUCTION_CLOSURE.md) for ordering, current API,
qualification commands and remaining requirements.

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

### Canonical MemoryEvent shadow migration

`append_admitted_with_canonical_shadow` validates canonical `MemoryEventV1`, the legacy admission candidate, verification-state correspondence, and the exact source ID/digest/observed-time set before invoking the existing admitted append. The deny-all sidecar binds canonical event digest, legacy candidate digest, final record digest, snapshot-vector digest and write disposition. This folds the useful #970 source work into the canonical #694 line without creating another writer. The production path additionally emits `ProductionCognitiveMutationReceiptV1`, which is committed in the same SQLite transaction as the source/Memory/fact/projection mutation and carries the authoritative `SourceRevisionId`, source-content SHA-256 and observation time. `bind_canonical_event_to_durable_receipt` therefore proves source-ID/digest/revision/time equivalence for production composition without trusting caller assertions; the legacy shadow alone still makes no source-revision claim.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-cognitive-store/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs): verified-only admission, reserved tombstone capacity, bounded retry journal, cross-object image validation and exact-cut page cursors.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs): durable owner writes, correction/deletion ancestry, proof-bound paging, reopen and rollback-cut checks.
- [codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs): descriptor-bound writable recovery, exclusive fencing, current-cut rejection and hostile filesystem identities.
- [codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs](../../../codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs): named Agentd product host through the canonical cognitive-store façade.
- [codex-rs/hepta-memory/src/production_writer.rs](../../../codex-rs/hepta-memory/src/production_writer.rs): same-transaction production provenance, semantic-validation rollback, live-authority rejection, and response-loss/restart duplicate rejection (`semantic_response_loss_restart_rejects_duplicate_and_preserves_committed_cut`).
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

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `contract_coordinated`.
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

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `contract_coordinated`.
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

### Bounded production request identity

Production semantic request hashing preserves the canonical JSON identity while
streaming into SHA-256. The existing 1 MiB source bound is checked before encoding;
the encoded request has an 8 MiB hard budget, independent of semantic validation.
Oversize serialization stops before transaction admission, rather than first
allocating an unbounded duplicate payload. See `production_cognitive_digest.rs`
and `production_cognitive_digest_tests.rs` in the existing hepta-memory owner.
Live writer acquisition obtains an external authority use hold before creating or
taking over a lease; missing hold support leaves the exact database cut unchanged.
