# prompt.registry technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0 ([canonical plan](../../DEVELOPMENT.md), selected by `docs/CURRENT.json`).

**Current implementation contracts:** [API and failure policy](API_CONTRACT.md), [operations and retention](OPERATIONS.md), [performance measurement](PERFORMANCE.md), [architecture and traceability](ARCHITECTURE.md), and [independent acceptance](ACCEPTANCE.md).

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

### V4 semantic core with V4/V5 payload envelope

`DurablePromptRegistry` publishes strict storage V4 through the existing single writer.
`registry.json` contains the V4 semantic metadata image, including relations, plus bounded payload
references; `registry.payloads` holds immutable, digest-checked byte extents.
New extents and their directory entry are synchronized before atomic metadata
publication. A failed publication leaves the predecessor selected; an uncertain
post-rename outcome poisons the writer until reopen and reconciliation. Recovery
validates the complete semantic image before trimming only an unselected trailing
write. Missing, shortened or modified committed extents are rejected, not healed.
V1/V2/V3 and transitional outer-V4/inner-V2 storage migrate on normal owner open
while preserving their validated semantic facts. A validated strict-V4 reopen
does not rewrite its metadata snapshot. Strict checkpoint verification is a
separate non-mutating path: it rejects legacy inputs instead of migrating them. Backup/restore must
capture both files from a quiesced owner; copying metadata alone is not a backup.
Old binaries reject the new storage version; downgrade requires an explicitly
reviewed owner migration, not restoring revoked state. Metadata and raw extents
have separate 32 MiB limits. Payload clones share immutable `Arc<[u8]>` storage,
while delivery still returns owned bounded bytes. Metadata serialization, semantic
hashing and the full in-memory registry remain size-dependent; this change reduces
payload copy/write amplification, not unlimited-history recovery or retention cost.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/prompt.registry.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md).

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

Use the registry owner for immutable factor/realization revisions and lifecycle updates. Optimizers receive read-only views. Revalidate revocation and model/tokenizer compatibility at actual delivery; an inserted factor is not automatically selected. A host must separately bind durable persistence rather than treating an in-memory registry image as a service.

Current operating and state-format references:

- [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs).
- [codex-rs/hepta-prompt-registry/src/v2.rs](../../../codex-rs/hepta-prompt-registry/src/v2.rs).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-prompt-registry/src/lib_tests.rs](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs); named case: `external_material_cannot_admit_itself`.
- [codex-rs/hepta-prompt-registry/src/v2_tests.rs](../../../codex-rs/hepta-prompt-registry/src/v2_tests.rs); named case: `every_state_change_allocates_one_revision_and_identical_retry_does_not`.

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

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `prompt.registry`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `PIM-0-PROMPT-INTERVENTION-CONTRACTS`

- State: `source_implemented_qualification_pending`; priority: `1`; parallel class: `contract_first_parallel`.
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

- State: `source_implemented_qualification_pending`; priority: `1`; parallel class: `contract_coordinated`.
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

- State: `source_implemented_qualification_pending`; priority: `3`; parallel class: `contract_coordinated`.
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


## Operational checkpoints, quotas and measurement

`DurablePromptRegistry` exposes a read-only operational metrics snapshot that
unifies logical-record, payload-record, selected/physical payload-byte,
single-payload and metadata ceilings. The metrics distinguish selected active
payload bytes from reclaimable inactive payload bytes and report a bounded
high-water value. These are owner-local facts, not acceptance or deployment
authority.

`export_consistent_checkpoint` writes the current committed V4 image to a fresh
private directory and reopens it before issuing a receipt.
`checkpoint_compacted` copy-compacts into another fresh directory, retaining
factor, realization, binding, relation, supersession and lifecycle history while
omitting payload bytes for inactive realizations. Neither operation rewrites or
switches the live owner. Activation of a verified checkpoint requires an
external quiescent owner protocol.

`verify_restore_checkpoint` performs a non-mutating strict-V4 read against a
required trusted exact revision and registry digest. It never initializes,
migrates, republishes metadata or trims an unselected tail. Checkpoint receipts
include equal source/checkpoint retained-history digests and explicitly report
`source_erased=false`; omitted destination bytes are not original-store erasure. `probe_fsync` measures a bounded
private temporary-file write, file synchronization and directory
synchronization, then removes the probe. The module qualification workflow runs
the named 1k/8k/16k logical-scale and bounded fsync profiles and binds their log
digest into the exact qualification receipt. A WAL, Merkle tree or incremental
digest remains unjustified until those measurements show a material bottleneck.

## Current-use and delivery-consistency update — 2026-09-28

The real factor lifecycle is Draft, Admitted, Retired and Revoked. Agentd
preparation and durable dispatch recording use the same typed current-use
contract. Cached ready contexts reconsult that owner and reject changed
attachments rather than silently replacing an injected payload. The dispatch
claim retains the registry lock through durable recording and uses the trusted
host clock, not a caller-provided past timestamp. Terminal provider facts remain
truthful; this does not claim cancellation of already admitted network I/O or
retraction of streamed output. See API_CONTRACT.md for the linearization boundary.

Metrics remain available diagnostically after poisoning with
`authoritative=false`; raw payloads and compiler diagnostics are not emitted in
final-use Display messages. Checkpoint retry is idempotent only for the exact
completed image. Partial/conflicting/symlink destinations are never overwritten.

The candidate builds checked-in Rust directly. Historical apply-prompt scripts
and source-mutating qualification workflows were retired. The implementation
map is explicitly authored using --write after a source commit; CI uses --check
only and records each check result, including missing tests and timeouts.


## Owner-local GC and failure contract update (2026-09-28)

The checked-in owner now supports a V5 outer payload-generation manifest while
retaining the strict V4 semantic schema and legacy migration paths. Existing
V4 stores remain V4 until the first nonempty owner-local garbage collection.
`durable_gc.rs` implements bounded two-slot publication/cleanup;
`durable_io.rs` records actual owner I/O observations; `failure.rs` centralizes
redacted errors and non-blind retry guidance. `durable_gc_tests.rs` exercises
revocation/audit preservation, idempotence, alternating generations, pre-rename
failure, unknown post-rename durability, corrupt selected extents, strict V5
restore and unsafe unselected-slot refusal. This is namespace reclamation of
inactive raw payload files, not secure erasure of devices or backups.

The API contract, operational runbook and performance guide define these new
interfaces. Qualification never applies source patches or writes a generated
map. Source authoring and formatting precede a separate map-only commit; both
exact-head and bound-base synthetic merge compile the committed source.
Native execution results live in exact-run artifacts, not this narrative.
