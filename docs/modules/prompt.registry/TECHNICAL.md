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

- `deterministic registry core`
- `signed admission verifier`
- `durable schema and migration owner`
- `transactional writer`
- `snapshot read port`
- `payload dereference and integrity verifier`
- `immutable lifecycle lineage journal`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::prompt_factor_lifecycleV1`
- `DomainRead::prompt_factor_registryV1`
- `DomainRead::prompt_realization_registryV1`
- `ModulePort::prompt.registry::intelligence.control`
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

Migrations are deterministic and checksum-bound. The current source implementation stores a schema-versioned owner snapshot under a single-writer lock, verifies file ownership/mode/link count, writes `registry.next`, fsyncs it, atomically renames it to `registry.json`, and fsyncs the state directory before publishing the new in-process image. Reopen validates record relationships, lifecycle-event digests and the whole-registry digest. The v1 compatibility migration preserves lifecycle/revocation state and emits explicit imported-lineage events; migration never resets a revoked factor to an admitted state. Rollback across a schema boundary must restore state compatible with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/prompt.registry.md#8-current-native-implementation) keeps `PromptRegistry` as a deterministic in-memory domain core and makes `DurablePromptRegistry` the authoritative source-level writer. A mutation is applied to a cloned core, durably committed, and only then published to the live process image, so storage failure cannot expose an uncommitted state. The state directory admits one writer through a lock file. Runtime activation must instantiate this durable wrapper rather than the raw core.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/prompt.registry.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `prompt_instruction_confusion`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Use the registry owner for immutable factor/realization revisions and lifecycle updates. Optimizers receive read-only views. Revalidate revocation, context profile and exact model/tokenizer/template/tool-schema compatibility at actual payload dereference; an inserted factor is not automatically selected. Signed admission binds signer, reviewer, exact factor content, reviewed scope, evidence and a short validity interval, and admission lineage is retained in the lifecycle journal.

Current operating and state-format references:

- [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs) — deterministic factor/realization core and immutable lifecycle journal.
- [codex-rs/hepta-prompt-registry/src/admission.rs](../../../codex-rs/hepta-prompt-registry/src/admission.rs) — signed admission grants and opaque verified admission.
- [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs) — single-writer durable owner, reopen validation and schema migration.
- [codex-rs/hepta-prompt-registry/src/delivery.rs](../../../codex-rs/hepta-prompt-registry/src/delivery.rs) — payload-backed realization registration, supersession and dereference.
- [codex-rs/hepta-prompt-registry/src/protocol.rs](../../../codex-rs/hepta-prompt-registry/src/protocol.rs) — native canonical JSON codecs for `PromptFactorV1` and `PromptRealizationV1`.
- [codex-rs/hepta-prompt-registry/src/v2.rs](../../../codex-rs/hepta-prompt-registry/src/v2.rs) — context-profile-bound exact compatibility snapshots.
- [codex-rs/hepta-intelligence/src/prompt_delivery.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery.rs) — source-level consumer that dereferences actual bytes before creating trusted `context.compiler` candidates.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-prompt-registry/src/lib_tests.rs](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs); named cases include `external_material_cannot_admit_itself`, signed admission lineage and expiry-at-use.
- [codex-rs/hepta-prompt-registry/src/v2_tests.rs](../../../codex-rs/hepta-prompt-registry/src/v2_tests.rs); named cases cover one-revision mutations, exact tuples, required-factor starvation, canonical filter ordering, active-profile conflicts, explicit supersession and exact payload dereference.
- [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); unit cases cover schema migration and restart/non-resurrection of revocation.
- [codex-rs/hepta-prompt-registry/src/protocol.rs](../../../codex-rs/hepta-prompt-registry/src/protocol.rs); unit cases cover canonical JSON round trips and unknown-field rejection.
- [codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs); cross-crate cases bind the stored payload bytes and admission lineage into `context.compiler`.

In `codex-rs`, run `just test -p codex-hepta-prompt-registry`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

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

Status axes are intentionally separate and must not be collapsed into one label:

- `PIM-0-PROMPT-INTERVENTION-CONTRACTS` is `source_implemented` in the canonical work-package registry.
- `PIM-1-PROMPT-FACTOR-REGISTRY` remains `planned` at the package/DAG level because its declared development predecessor `MEM-1-STORE` is still open; this does not erase the source-level durable registry slice already present in this candidate.
- `PIM-3-FACTOR-EVOLUTION` remains `planned`; split/merge/evolution and causal-ablation deliverables are not claimed by the registry source implemented here.
- `productionImplementation`, runtime activation, product execution, independent acceptance, promotion and release remain false/open until their separate gates are satisfied.

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. The current source tree contains a named source-level caller in `hepta-intelligence::compile_prompt_registry_v2`; it carries selected registry bytes through context compilation, serialization and attachment receipts, but it does not establish a running product host, model dispatch or terminal provider observation. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `prompt.registry`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `PIM-0-PROMPT-INTERVENTION-CONTRACTS`

- State: `source_implemented`; priority: `1`; parallel class: `contract_first_parallel`.
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

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. The source now contains the durable owner, authenticated admission, payload-backed realization delivery, canonical contract codecs and a named source-level composition caller; these facts advance source implementation only. They grant no running-host, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
