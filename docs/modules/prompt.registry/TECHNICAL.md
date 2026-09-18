# prompt.registry technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `prompt.registry`

**Owner:** `intelligence-platform`

**Deputy:** `cognitive-platform`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `PIM-0-PROMPT-INTERVENTION-CONTRACTS`

This stable document is the implementation guide for `prompt.registry`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own admitted PromptFactor and PromptRealization identity, lifecycle and compatibility facts.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `cognitive-platform` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `store`, state model `stateful` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-prompt-registry`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-prompt-registry`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `prompt.registry`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `kernel.operations`

Authoritative write domains:

- `prompt_factor_registry`
- `prompt_realization_registry`
- `prompt_factor_lifecycle`

Explicitly denied capabilities:

- `external_content_instruction_promotion`
- `self_activation`

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

- `DomainRead::prompt_factor_lifecycleV1`
- `DomainRead::prompt_factor_registryV1`
- `DomainRead::prompt_realization_registryV1`
- `ModulePort::prompt.registry::knowledge.graph`
- `ModulePort::prompt.registry::prompt.optimizer`
- `PromptFactorV1`
- `PromptRealizationV1`

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::kernel.operations::prompt.registry`
- `ModulePort::platform.types::prompt.registry`

Critical protocol schemas:

- `PromptFactorV1`
- `PromptRealizationV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `prompt_factor_lifecycle`
- `prompt_factor_registry`
- `prompt_realization_registry`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The native core is split between an in-memory deterministic domain engine and a durable owner adapter. `PromptRegistry` owns factor, admission, lifecycle, realization, payload and revision semantics; `DurablePromptRegistry` in [`store.rs`](../../../codex-rs/hepta-prompt-registry/src/store.rs) owns one filesystem writer lock and publishes mutations only after the next registry image has been encoded, synced and committed.

Durable replacement uses a bounded `current / temporary / backup` protocol. Reopen recovers an interrupted current-to-backup rename without resurrecting a revoked predecessor. Before every authoritative mutation, the store decodes the persisted generation and requires it to equal the in-memory generation; divergence fails closed instead of allowing a stale process to overwrite a newer disk state. Schema V0 draft-only images migrate deterministically to V1; V0 state that would require inventing admission authority is rejected.

Admission is a final-use boundary. [`registry_mutation.rs`](../../../codex-rs/hepta-prompt-registry/src/registry_mutation.rs) binds factor identity and digest, reviewer, evidence digest and reviewed-scope digest into a `FinalUseBinding`. `admit_factor_authorized` consumes an independently claimed, revocation-aware `VerifiedUseToken`; the legacy unauthenticated admission entrypoint fails closed.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the owner boundary. This source implementation is still not a runtime activation or a production service composition.

## 8. Failure semantics, recovery and rollback

Registry mutation is clone-before-publish: a failed domain mutation leaves the current image unchanged, and a failed durable publication does not publish the candidate image in memory. Store open validates canonical decoding, registry digest, lifecycle replay, admission lineage, payload digests, active-realization uniqueness and revision/frontier consistency.

Reopen resolves interrupted replacement using the last durable predecessor when the current file is absent and a backup exists. A valid current file wins over stale backup debris; malformed or tampered current state fails closed rather than silently rolling back. A live writer also refuses mutation when the persisted generation differs from its in-memory generation.

Revocation is terminal for a factor, disables its realizations, advances the revocation frontier and invalidates frozen V2 snapshots. Retirement and revocation require reason digests; revocation also records a non-zero cutoff. Migration never fabricates admission or lifecycle authority.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory. Provider/model delivery reconciliation remains outside this store and must not be inferred from registry persistence.

## 9. Security, privacy and threat controls

Owned threat entries:

- `prompt_instruction_confusion`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md) defines the pilot read ceiling and payload bounds. Current native enforcement includes a 16,384 record ceiling, at most 128 compatible V2 realizations per read, at most 64 KiB per realization payload and a bounded aggregate payload store. Token cost remains an explicit exact-tokenizer binding rather than a character-count estimate.

Durable persistence currently rewrites one canonical bounded registry image per logical mutation. This favors correctness, reopen verification and simple rollback over high write throughput; it is not a measured production-storage profile. Before product composition, benchmark mutation latency, state-image growth, reopen/recovery time, exact-profile lookup and revocation propagation on the selected host.

Current limit and algorithm sources are [`registry.rs`](../../../codex-rs/hepta-prompt-registry/src/registry.rs), [`v2_types.rs`](../../../codex-rs/hepta-prompt-registry/src/v2_types.rs), [`v2_registry.rs`](../../../codex-rs/hepta-prompt-registry/src/v2_registry.rs) and [`store.rs`](../../../codex-rs/hepta-prompt-registry/src/store.rs).

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement and overload obligations for a selected host.

## 11. Observability and operations

Use `DurablePromptRegistry` as the single-writer owner adapter when durability is required; direct `PromptRegistry` construction remains appropriate for deterministic pure-core tests and explicitly non-durable fixtures. Admission records and immutable lifecycle events preserve reviewer, evidence, scope, actor, reason, cutoff and revision lineage. Realization records bind exact model/tokenizer/template/tool-schema/context-profile/locale/role identity, payload digest, bounded payload bytes, token cost, expiry and predecessor supersession.

Readers freeze one registry snapshot. `read_compatible_v2` canonicalizes required-factor filters, reserves every required factor before result truncation and rejects stale snapshots. `resolve_payload_v2` revalidates the frozen snapshot, exact profile, lifecycle/active state, expiry and payload digest immediately before returning bytes.

The read-only `prompt.optimizer` source consumer lives in [`hepta-prompt-optimizer/src/registry_source.rs`](../../../codex-rs/hepta-prompt-optimizer/src/registry_source.rs). It establishes a concrete module-to-module source consumer, but it is not a named production runtime caller and does not advance activation.

Current operating and state-format references:

- [`registry_mutation.rs`](../../../codex-rs/hepta-prompt-registry/src/registry_mutation.rs)
- [`v2_registry.rs`](../../../codex-rs/hepta-prompt-registry/src/v2_registry.rs)
- [`protocol.rs`](../../../codex-rs/hepta-prompt-registry/src/protocol.rs)
- [`store.rs`](../../../codex-rs/hepta-prompt-registry/src/store.rs)

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [`lib_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs): unauthenticated/external admission denial, immutable admission/lifecycle lineage and mutation atomicity.
- [`v2_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/v2_tests.rs): exact context profile, required-factor reservation before truncation, canonical filter/digest stability, explicit supersession, payload resolution and payload bounds.
- [`protocol_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/protocol_tests.rs): canonical JSON round trips, unknown-field rejection, ordering and durable-state integrity.
- [`store_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/store_tests.rs): restart/reopen, revocation non-resurrection, authenticated durable admission, tamper rejection, deterministic migration, single-writer exclusion, interrupted replacement recovery and stale-writer fencing.
- [`integration_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/integration_tests.rs): registry payload resolution through context compilation, serialization, attachment and terminal delivery-observation digest binding.
- [`hepta-prompt-optimizer/src/registry_source_tests.rs`](../../../codex-rs/hepta-prompt-optimizer/src/registry_source_tests.rs): the optimizer consumes a frozen registry snapshot instead of caller-invented admission state.

In `codex-rs`, run `just test -p codex-hepta-prompt-registry` and the prompt-optimizer package tests. The commands are invocations, not stored pass receipts. Exact-head and merge-candidate CI remain the evidence boundary; unrelated repository-wide external blockers must not be reclassified as prompt-registry evidence.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain compilation, strict-lint, source/merge, failure and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `PIM-1-PROMPT-FACTOR-REGISTRY`
- `PIM-3-FACTOR-EVOLUTION`

The bootstrap package is `PIM-0-PROMPT-INTERVENTION-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

Current status must be read by layer: the registry owner source now contains durable persistence/reopen, authenticated admission, audit lineage, exact-profile payload realization, canonical codecs and a read-only optimizer consumer. A named production runtime caller, target-host execution evidence, independent acceptance, activation, promotion and release remain separate and are not implied by those source capabilities.

For `prompt.registry`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `PIM-0-PROMPT-INTERVENTION-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `intelligence-platform` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-prompt-registry/**`
- `codex-rs/hepta-prompt-optimizer/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- Activation predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
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

#### `PIM-1-PROMPT-FACTOR-REGISTRY`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-prompt-registry/**`
- Development predecessors:
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `MEM-1-STORE`
- Activation predecessors:
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
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

#### `PIM-3-FACTOR-EVOLUTION`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-prompt-registry/**`
- `codex-rs/hepta-prompt-optimizer/**`
- `qa/learning/prompt-factor-evolution/**`
- Development predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`
- `PIM-1-PROMPT-FACTOR-REGISTRY`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- Activation predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `PIM-1-PROMPT-FACTOR-REGISTRY`
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
- `factor_discovery_from_residual`
- `split_merge_retire`
- `model_specific_realization`
- `causal_ablation`
- `next_snapshot_only`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `prompt.registry` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `prompt.registry` is implemented by work package `PIM-0-PROMPT-INTERVENTION-CONTRACTS` in:

- `codex-rs/hepta-prompt-registry`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
