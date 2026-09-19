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

The registered primary source is [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs); its public checkpoint surface is the single canonical Lane C `CompactCheckpointV1`, with `build_qualified_candidate` and `prove_compaction` implemented in [qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs). The weaker legacy `compact()/CompactCheckpoint` API is removed. Durable owner-store publication/reload is implemented in [codex-rs/hepta-memory/src/production_compact.rs](../../../codex-rs/hepta-memory/src/production_compact.rs), and the explicit product consumer is [AgentdProductionWriterHost::qualify_and_publish_compaction](../../../codex-rs/hepta-agentd/src/production_writer_host.rs). These cross-owner files are covered by the explicit co-owner paths in `MEM-5-COMPACT`; they do not transfer their owning modules' wider authority.

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

- `bounded input and lineage normalizer`;
- `deterministic count/byte/token retention core`;
- `independent qualification/proof binder`;
- `owner-store generation publisher`;
- `checkpoint reload and corruption-verification layer`.

The retention core binds the exact tokenizer from the coherent Lane C snapshot. Every input carries caller-observed canonical serialized bytes and tokenizer-derived token count. Protected live references must fit all policy budgets; optional references are selected deterministically by protected status, retention priority, stable ID and revision. The support manifest binds record digest, priority, retention-reason digest, byte cost and token cost.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::compact_checkpointV1`

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::cognitive.read::compact.engine`
- `ModulePort::kernel.operations::compact.engine`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and the durable publication DTO represent identical checkpoint/proof semantics. `CompactionProofV2` binds evaluator identity, evaluation artifact, evaluator implementation, attestation and signature digests in addition to retained-query, reconstruction, contradiction and deletion obligations. The proof remains authority-free: attestation/signature digests are provenance bindings and authentication still belongs to the independent evidence/host gate. Tests cover deterministic ordering, tombstone non-resurrection, resource budgets, proof binding, owner-store replay/CAS, restart reload and corruption rejection.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `compact_checkpoint`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For the `compact_checkpoint` domain, semantic authorship remains with `compact.engine`; physical durability is delegated to the existing cognitive owner store through `ProductionDurableWriter`. No parallel database or authority spine is introduced. The dedicated production compact journal reuses the immutable `cognitive_compact_events` table and binds every row to the externally verified production lease/head, authority and owner epochs, checkpoint generation, predecessor row digest and a lease/event binding digest.

Publication is generation/predecessor-CAS protected and idempotent for identical same-generation semantics. A changed replay conflicts. Store reload verifies the complete row chain, canonical checkpoint/proof digests and publication artifact digest before returning a current checkpoint. A failed construction or failed transaction leaves the prior committed generation current.

Existing migrations and store-open integrity checks remain authoritative for the physical table. Retention and deletion preserve lineage and the qualified builder rejects any `Live -> Tombstone -> Live` resurrection.

## 7. Runtime, concurrency and transaction model

Candidate construction and proof binding are pure deterministic functions. Production publication is composed only through `AgentdProductionWriterHost::qualify_and_publish_compaction`, which builds and proves the candidate before crossing the owner-store boundary. The host still requires an externally verified `ProductionAuthorityLease`; default Agentd startup does not silently acquire this capability.

The physical linearization point is the owner-store `BEGIN IMMEDIATE` transaction. The current production lease is revalidated inside that transaction before any compact row is appended. Concurrent same-generation publications therefore have one winner; the other observes a CAS conflict. Reload is read-only but revalidates the current production lease and complete compact chain.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

The qualified builder fails closed on broken lineage, resurrection, tokenizer drift, invalid resource costs, protected-reference overflow/loss, digest mismatch or failed qualification obligations. Production publication fails closed on stale/revoked authority, generation/predecessor conflict, malformed/corrupt durable rows, invalid lease/event binding or canonical checkpoint/proof mismatch.

Restart recovery reopens the same WAL/FULL cognitive store and calls `load_current_compaction`; no in-memory checkpoint is trusted as the durable head. Rollback means selecting/revalidating a compatible predecessor generation, never restoring deleted source material. A corrupt chain is quarantined by returning an error rather than skipping damaged rows.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The native candidate builder enforces at most 65,536 input records and 4,096 protected references. Policy-bound retained limits must also be non-zero and no larger than 64 MiB serialized bytes or 16,777,216 tokens; callers may choose stricter budgets. The policy tokenizer digest must exactly match the coherent source snapshot tokenizer digest.

The source suite includes a deterministic 10,000-record batch fixture and bounded retained set. This proves algorithmic boundedness/order stability, not target-host latency, CPU, memory or foreground-interference SLOs. Those measurements remain qualification work for the selected host.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Checkpoint/qualification library plus explicit owner-store publication. Keep source snapshot lineage, support manifest, omissions, deletion frontier, resource accounting, independent proof provenance and predecessor generation with every durable publication. The owner store retains the prior complete generation when a new transaction fails.

Semantic compaction responsibility is explicit: the current engine performs deterministic selection/checkpoint compaction, not unregistered generative summarization. A future semantic merge/summary revision must carry a registered algorithm digest, canonical byte/token observations, source support/citations and contradiction preservation, and must pass the same independent reconstruction/holdout proof before publication.

Current operating and state-format references:

- [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs).
- [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs).
- [codex-rs/hepta-memory/src/production_compact.rs](../../../codex-rs/hepta-memory/src/production_compact.rs).
- [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs).
- [CALLERS.toml](../../../CALLERS.toml).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs): tombstone non-resurrection, protected references, count/byte/token budgets, tokenizer binding, payload/omission cross-checks, proof V2 provenance, input-order invariance and the 10,000-record deterministic batch.
- [codex-rs/hepta-memory/src/production_compact.rs](../../../codex-rs/hepta-memory/src/production_compact.rs): durable publish/replay, restart reload, generation/predecessor CAS, concurrent same-generation publication and deliberate durable-row corruption.

In `codex-rs`, run `just test -p codex-hepta-compact-engine` and the `codex-hepta-memory` focused production-compaction tests. The exact source-head and deterministic synthetic-merge jobs generate `hepta.module-implementation-exact-head-evidence.v1`, binding every declared source/test path to the checked-out commit/tree and git blob identities. Commands and source identities are not acceptance receipts until CI executes them.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-5-COMPACT`

The bootstrap package is `MEM-5-COMPACT`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

The source candidate now includes the canonical builder/proof, owner-store publisher/reloader and explicit Agentd product callsite. This document records that source composition, but the repository-level production implementation fact is promoted only after focused/package/all-target/lint checks and exact source-head plus merge-candidate evidence pass. Later activation/acceptance/release gates remain independent.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `compact.engine`, this source composition consumes an externally verified production-writer lease at the owner-store boundary; the document itself grants no runtime, model, provider, external-effect, selection, acceptance, promotion or release authority. The product callsite being present is not independent semantic acceptance or activation.

### Work-package execution envelopes

#### `MEM-5-COMPACT`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`; explicit co-owner modules for this integration revision: `cognitive.types`, `cognitive.store`, `runtime.agentd`.
- Allowed write paths:
- `codex-rs/hepta-compact-engine/**`
- `codex-rs/hepta-cognitive-types/src/lane_c.rs`
- `codex-rs/hepta-memory/Cargo.toml`
- `codex-rs/hepta-memory/src/lib.rs`
- `codex-rs/hepta-memory/src/production_writer.rs`
- `codex-rs/hepta-memory/src/production_compact.rs`
- `codex-rs/hepta-agentd/Cargo.toml`
- `codex-rs/hepta-agentd/src/production_writer_host.rs`
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
