# compact.engine technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `compact.engine`

**Owner:** `cognitive-platform`

**Deputy:** `durability-kernel`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-5-COMPACT`

This stable document is the implementation guide for `compact.engine`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Create bounded compaction checkpoints without rewriting source facts.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `durability-kernel` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `engine`, state model `stateful` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-compact-engine`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-compact-engine`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source remains [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs). The current crate exports the canonical `CompactCheckpointV1` / `CompactionProofV2` contracts plus `build_qualified_candidate` and `prove_compaction`; the historical `NATIVE_BINDINGS.json` observation that named the removed `CompactCheckpoint` / `compact` surface is not an exact-head API claim. Exact-head source and test identity comes from the CI-generated implementation evidence described in section 12. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/compact.engine.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `cognitive.read`
- `kernel.operations`

Authoritative write domains:

- `compact_checkpoint`

Explicitly denied capabilities:

- `source_fact_mutation`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bounded input stage`
- `deterministic deletion/lineage core`
- `record + byte + token budget selector`
- `snapshot/tokenizer-bound semantic-payload binder`
- `independent qualification/proof binder`
- `generation publisher`
- `checkpoint and recovery layer`

The canonical checkpoint path is now composed through
`AgentdProductionWriterHost::publish_compaction_checkpoint`. The engine itself
remains a pure authority-free kernel: semantic content is produced by an
approved external generator and arrives only as a snapshot/tokenizer-bound
payload digest plus generator receipt and exact byte/token accounting.
`prove_compaction` binds the independent evaluator identity, evaluator
implementation, evaluation artifact, attestation, signature digest and the
external signature-verification receipt before the production writer may
publish the checkpoint.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::compact_checkpointV1`
- native `CompactionProofV2` qualification evidence binding

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::cognitive.read::compact.engine`
- `ModulePort::kernel.operations::compact.engine`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `compact_checkpoint`

The canonical checkpoint metadata is physically persisted by the existing
cognitive SQLite owner in
`cognitive_qualified_compact_checkpoints` (migration
`0011_qualified_compact_checkpoints.sql`). Publication holds an externally
authorized production lease, opens `BEGIN IMMEDIATE`, revalidates the live
lease/fence inside that transaction, performs generation/predecessor CAS, and
inserts one immutable checkpoint/proof image. Reopen reconstructs the complete
Lane C contracts, recomputes all checkpoint/proof/publication digests and
validates predecessor continuity. The table has immutable update/delete
triggers; source facts remain in their existing ledgers.

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/compact.engine.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/compact.engine.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. The canonical checkpoint path now enforces all three retention dimensions—record count, encoded bytes and tokenizer-counted tokens—and separately enforces semantic-payload byte/token ceilings. The semantic payload must bind the exact source-snapshot digest and that snapshot's tokenizer digest. These are enforced contract limits, not performance measurements; host throughput/latency qualification remains separate.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Checkpoint/projection library. Keep source lineage, omissions, resource accounting and deletion frontiers with every compact result and retain the prior complete generation on failed construction. The production checkpoint path is explicitly composed; replay and learned-skill targets remain separate capabilities.

Current operating and state-format references:

- [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs).
- [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs).
- `codex-rs/hepta-memory/src/qualified_compact_store.rs` — atomic canonical publication/reopen.
- `codex-rs/hepta-memory/migrations/0011_qualified_compact_checkpoints.sql` — immutable owner table.
- `codex-rs/hepta-agentd/src/production_writer_host.rs` — named authorized product caller.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs): deletion non-resurrection, protected-reference retention/missing-reference failure, deterministic ordering, record/byte/token budgets, 4,096-record bounded regression, semantic snapshot/tokenizer binding, payload budget and evaluator/attestation proof binding.
- `codex-rs/hepta-memory/src/qualified_compact_store_tests.rs`: idempotent publish, predecessor CAS, concurrent same-generation winner, crash-before-commit rollback/reopen and corrupt-row fail-closed recovery.
- `codex-rs/hepta-agentd/src/production_writer_host_tests.rs`: authorized Agentd host -> qualified engine -> durable SQLite publication -> reopen round trip.
- `codex-rs/hepta-cognitive-types/src/lane_c_tests.rs`: V2 proof digest/provenance binding.

Exact-head test identities are generated at CI runtime by
`scripts/hepta-implementation-maps.py evidence` for both the source head and
deterministic synthetic merge; tracked implementation maps are documentation
generation artifacts and do not attempt the impossible self-reference of
containing their own commit SHA.

In `codex-rs`, run `just test -p codex-hepta-compact-engine`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-5-COMPACT`

The bootstrap package is `MEM-5-COMPACT`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. The checkpoint publication path has a named Agentd product caller and the existing cognitive SQLite owner writer. It remains inactive unless the caller has explicitly opened the externally verified `AgentdProductionWriterHost`; default Agentd startup does not mint this capability. Other target capabilities remain inactive until their own activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `compact.engine`, this document grants no runtime, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority. The only production write path described here is the explicit externally-authorized Agentd production-writer capability; the pure compaction kernel and its proof artifacts remain `DENY_ALL`.

### Work-package execution envelopes

#### `MEM-5-COMPACT`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-compact-engine/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-1-STORE`
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

The canonical readiness overlay binds `compact.engine` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `compact.engine` is implemented by work package `MEM-5-COMPACT` in:

- `codex-rs/hepta-compact-engine`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
