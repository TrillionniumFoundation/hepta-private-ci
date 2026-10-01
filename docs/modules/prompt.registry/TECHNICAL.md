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

`existing_bound` is a source-location fact: the declared roots above are materialized. Executed checks belong to an exact source candidate and are recorded in the [2026-10-01 audit](ADVERSARIAL_AUDIT_2026-10-01.md). Focused tests, all-target compilation, strict lint and source/merge qualification remain separate evidence obligations; a successful focused test does not imply that a later blocked lint step executed. This status does not activate `prompt.registry`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

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

### Native API and mutation sequence

The native store is `DurablePromptRegistry`; `PromptRegistry` is its deterministic
in-memory state image. Use the durable API for owner publication. The internal
`register_realization_v2` metadata helper is not a production payload writer.

| Component | Implemented surface | Invariant |
| --- | --- | --- |
| `lib.rs` | Factor identity, lifecycle, relations, graph-source image | Immutable factor semantics; terminal retirement/revocation; one revision per change |
| `admission.rs` | Reviewer signature verification and final-use binding | Exact factor/scope/evidence; separately configured trust; expiring single-use mutation grants |
| `v2.rs` | Model tuple, snapshot, compatible set | Exact model ID/version and all profile digests; canonical bounded set; required factor coverage |
| `delivery.rs` | Payload registration, supersession, dereference | Exact stored bytes/digest; one active realization per complete profile; current snapshot/lifecycle |
| `durable.rs` / `durable_payloads.rs` | V1/V2 migration, V3 publication and reopen | Single owner lock; semantic replay validation; immutable committed extents |
| `durable_recovery.rs` | Exact-cut recovery anchor and anchored reopen | Independently supplied current cut must match before migration or payload-tail cleanup |
| `protocol.rs` | `PromptFactorV1` / `PromptRealizationV1` JSON codecs | Bounded input, canonical dimensions, unknown/duplicate critical member rejection |

1. Register an immutable draft factor. Validate bounded semantics before insertion;
   registration alone grants no instruction or selection authority.
2. Call `admit_factor_final_use` with an independently provisioned
   `FinalUseAuthority`, a matching signed grant, factor ID, reviewed scope and
   evidence digest. The reviewer identity is bound by the signed grant;
   `FinalUseAdmissionAuthority` verifies the operation inside this call. A reused
   admission identity with changed semantics conflicts.
3. Call `register_realization_payload_final_use_v2` with the complete binding and
   bytes. An existing active profile requires an explicit predecessor; registration
   atomically deactivates that predecessor without deleting its history.
4. Freeze `snapshot_v2` using the host generation-vector digest and exact model
   tuple. `read_compatible_v2` canonicalizes required factor IDs and checks current
   snapshot, lifecycle, expiry, profile and result capacity. Rehashed containers
   must still satisfy every semantic invariant.
5. Dereference selected IDs with `dereference_realization_v2` against that same
   current snapshot immediately before compiling bytes. Digest equality alone is
   neither an authenticated source nor selection authority.
6. Retire/revoke through the final-use durable APIs. Cascaded realization
   deactivation and lifecycle publication share one owner revision. Optimizers
   cannot mutate these records.

Native ceilings are 16,384 total records, 128 compatible realizations and required
factor IDs, and 64 KiB per payload. V3 metadata and payload extent files each have
a 32 MiB ceiling. A smaller configured record ceiling is persisted and cannot
silently change on reopen. These bounds are enforcement, not latency measurements.

`register_factor_relation` and `factor_graph_source_v1` belong to the in-memory
image. The current durable schema has no relation records or governed relation
write port. Durable publication rejects a relation-bearing image before changing
selected files; a graph-source export does not establish persistent KG integration.

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

Native factor semantics bound purpose to 4,096 bytes, authority class to 64 bytes
and the canonical JSON eligible-dimension array to 8,192 bytes. Stable identifiers
use the ASCII grammar and a 128-byte ceiling. Dimension validation accounts for
the exact array brackets, commas and quoted identifiers with checked arithmetic,
rejects excess before serialization, and scans canonical order without cloning
the full dimension vector. Complete canonical protocol input is capped at
262,144 bytes. Admission identifier validation likewise checks borrowed input
before creating owned IDs; signed-grant shapes and public wire versions remain
unchanged. Shape failures retain `InvalidField` / `InvalidGrant` semantics.

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

### Native storage V3: immutable payload extents

`DurablePromptRegistry` publishes storage V3 through the existing single writer.
`registry.json` contains the V2 semantic metadata image plus bounded payload
references; `registry.payloads` holds immutable, digest-checked byte extents.
New extents and their directory entry are synchronized before atomic metadata
publication. A failed publication leaves the predecessor selected; an uncertain
post-rename outcome poisons the writer until reopen and reconciliation. Recovery
validates the complete semantic image before trimming only an unselected trailing
write. Missing, shortened or modified committed extents are rejected, not healed.
V1/V2 storage migrates on open without changing domain digests, lifecycle or grants.
A validated V3 reopen does not rewrite its metadata snapshot. Backup/restore must
capture both files from a quiesced owner; copying metadata alone is not a backup.
Old binaries reject the new storage version; downgrade requires an explicitly
reviewed owner migration, not restoring revoked state. Metadata and raw extents
have separate 32 MiB limits. Payload clones share immutable `Arc<[u8]>` storage,
while delivery still returns owned bounded bytes. Metadata serialization, semantic
hashing and the full in-memory registry remain size-dependent; this change reduces
payload copy/write amplification, not unlimited-history recovery or retention cost.

The owner locks its Unix directory descriptor before creating `registry.lock`,
then retains both locks for its lifetime. Every successful open synchronizes the
parent directory entry, including retries after a failed initial parent sync.
It obtains the actual parent with descriptor-relative `openat("..")` from the
validated owner directory, so `.` or `owner/child/..` aliases cannot redirect the
durability fence to a lexical parent of the input path.
Invalid zero capacity fails before creating owner state. If the
first metadata publication fails before rename, only the newly created marker
belonging to that opener is removed and the owner directory is synchronized,
allowing a fresh retry. Existing-owner and migration markers are retained;
uncertain post-rename durability also retains the marker. This cleanup addresses
observed pre-publication failures, not automatic repair after an arbitrary crash.
Missing committed metadata behind an existing owner marker remains corrupt.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/prompt.registry.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/prompt.registry.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

For native recovery, `Corrupt` rejects malformed/duplicate JSON members, invalid
lifecycle replay, missing payload extents and digest/profile inconsistencies.
`StateLocked` rejects a concurrent owner. A failure before metadata rename preserves
the predecessor; `IndeterminateDurability` after rename makes `requires_reopen()`
true and all subsequent reads/writes fail with `ReopenRequired`. Reopen reconciles
the selected manifest before discarding an unselected extent tail. Do not retry a
consumed final-use grant as if an uncertain commit had failed.

Native Unix file opening rejects symlinks and non-regular files without blocking
on a FIFO. Non-Unix durable owner opening currently fails closed. Backup integrity
checks prove the copied image's internal consistency; they do not prove freshness
against an independently pinned current revision. Restoring a valid older complete
owner image through ordinary `open_state_dir` can roll back revocation.

For anchored recovery, call `recovery_anchor()` on an available committed owner
and independently retain and authenticate the returned
`PromptRegistryRecoveryAnchor`. It binds the exact `revision`,
`lifecycle_frontier`, `revocation_frontier` and semantic `registry_digest`.
`open_state_dir_with_recovery_anchor(directory, maximum_records, expected)`
requires an existing selected state, validates it under the owner lock and rejects
any different cut before metadata migration or payload-tail cleanup. An invalid
anchor returns `InvalidRecoveryAnchor`; missing selected state returns
`RecoveryStateMissing`; a valid but different cut returns
`RecoveryAnchorMismatch`. Anchor shape and capacity validation precede filesystem
access. A matching V1/V2 image may migrate; a matching V3 image may discard its
unselected payload tail only after comparison. A missing owner directory or
selected metadata cannot create an owner directory or marker. Opening an existing
legacy image can create its missing owner-lock marker before cut comparison;
cut rejection still leaves metadata and payload bytes unchanged.

This is exact equality, not a minimum-prefix proof: every newly acknowledged
mutation requires a newly independently retained cut. The host must establish
the anchor's authentication and currentness in a separate rollback domain;
deriving it from the suspect backup proves neither. The ordinary constructor
remains available for bootstrap and unanchored local reopening, and Agentd does
not yet supply a trusted recovery anchor. Production restore still requires that
host composition and an approved acknowledgement/recovery procedure.

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
- [codex-rs/hepta-prompt-registry/src/durable_restore_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_restore_tests.rs) covers adversarial storage restore and bootstrap recovery.
- [codex-rs/hepta-prompt-registry/src/durable_recovery_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_recovery_tests.rs) covers missing state, old backups, equal-revision forks, mismatch-before-trim/migration and parent-sync retry.
- [codex-rs/hepta-prompt-registry/src/protocol_bounds_tests.rs](../../../codex-rs/hepta-prompt-registry/src/protocol_bounds_tests.rs) covers exact 8,191/8,192/8,193-byte dimension-array boundaries and canonical ordering.
- [codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs) and [prompt_delivery_multirole_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery_multirole_tests.rs) cover sealed compilation and exact selected realization identity.
- [codex-rs/hepta-prompt-optimizer/src/canonical_integrity_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_integrity_tests.rs) covers rehashed pricing/portfolio tampering and candidate semantic integrity.
- [codex-rs/hepta-prompt-optimizer/src/canonical_signed_pricing_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_signed_pricing_tests.rs) follows actual durable enumeration and independent signed completeness/pricing through expiry and known-revocation selection boundaries.
- [codex-rs/hepta-learning-ledger/src/signed_evidence_horizon_tests.rs](../../../codex-rs/hepta-learning-ledger/src/signed_evidence_horizon_tests.rs) covers the optimizer dependency's exclusive evidence horizon, known revocation and saturating boundary.
- [codex-rs/hepta-agentd/src/prompt_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/prompt_runtime_tests.rs) covers exact model and deadline checks at the Agentd staging seam.
- [codex-rs/hepta-agentd/src/prompt_runtime_integrity_tests.rs](../../../codex-rs/hepta-agentd/src/prompt_runtime_integrity_tests.rs) covers dispatch deadline and terminal-order rejection at commit and reopen.

In `codex-rs`, run `just test -p codex-hepta-prompt-registry`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/prompt.registry.md) separately labels target acceptance designs.

The integration checks use `just test --locked --lib -p codex-hepta-intelligence -E 'test(prompt_)'` and `just test --locked --lib -p codex-hepta-agentd -E 'test(prompt_)'`. The audit records source/merge identities, suite counts and remaining gate failures; changing this guide does not refresh execution evidence.

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

Current Agentd bootstrap opens the durable owner in `state.rs` and installs the
prompt runtime host in `app_runtime.rs`. `enumerate_candidates` and
`compile_and_stage` currently have no live turn-ingress caller. Governed durable
mutation APIs likewise have no authenticated product ingress or configured trust.
The compiler now seals its verified delivery set, exact stored bytes, portfolio
validity and profile; Agentd accepts only the same model identifier and caps the
staged deadline by portfolio and realization expiry. Model aliases require an
explicit validated adapter rather than implicit prefix conversion. Already-staged
attachments still need current registry/revocation revalidation at physical send
before activating a live mutation pipeline. Source safety repairs do not close
that integration gate.

Canonical optimizer enumeration, pricing and selected portfolios also carry
private process provenance. Build them through `enumerate_factors_v1`,
`price_factors_v1` and `select_portfolio_v1`;
`PricedPromptCandidatesV1::validate()` and
`SelectedPromptPortfolioV1::validate()` reject changed public fields even when
their public receipt hashes are recomputed. Candidate validation binds the
complete registry snapshot, model tuple, factor/realization identities, ordering
and receipt semantics. The enumeration seal binds its recorded omission count and
snapshot, so rehashing public receipts cannot hide omissions or invent a new
enumeration source. Pricing also requires the verifier's objective to match.
The pricing seal retains the original verifier trust digest; selection requires
the same objective and trust snapshot, so another objective or trust epoch cannot
be mixed into pair evidence for an already priced set.
The optimizer consumes
[`VerifiedLearningEvidenceV1::valid_until_unix_ms`](../../../codex-rs/hepta-learning-ledger/src/signed_evidence.rs)
as an exclusive evidence deadline. Signed-envelope and authenticated-principal
expiries are inclusive at verification, so the deadline is one millisecond after
their minimum, capped by any revocation time already known to that trust snapshot.
Saturation conservatively excludes `u64::MAX` if an exclusive successor cannot be
represented. Pricing seals its verification time and the earliest completeness/
pricing evidence deadline. Selection rejects time before verification with
`InvalidTime`, and time at or beyond the evidence deadline with `PortfolioExpired`,
even without pair evidence. Portfolio validity is capped by requested validity,
pricing/completeness evidence, every verified pair-evidence horizon and selected
realization expiry. Selection time is privately sealed; exercise before that time
returns `RejectStale`. These are bounded dependency facts from learning.ledger,
not a registry-owned evidence authority.
Selection, exercise and registry compilation validate the corresponding sealed
inputs before use. Integrity failures are `CandidateIntegrity`,
`PricingIntegrity` or `PortfolioIntegrity`. These objects have no serialized
reconstruction path for their private seals; the seals grant no final-use or
provider authority.

The seal records verified construction under that trust snapshot; it does not
refresh producer trust at exercise or physical send. Live host composition still
needs current trust/revocation checks at the corresponding effect boundary.

Registry compilation and compiled-output validation reject any selected fragment
whose declared `token_cost` exceeds 10,000, returning
`PromptRegistryCompilationErrorV2::PromptFragmentTokenLimit`. The boundary applies
to each individual fragment, even when the total budget would allow more. The
signed fixture covers 10,000 accepted and 10,001 rejected. This enforces a declared
cost only; the registry/compiler does not independently run the exact tokenizer.
Fragments declared above 1,000 tokens fall under the repository's P0 manual
review rule. Actual tokenizer attestation and the applicable manual-review receipt
remain qualification work; a passing declared-bound test establishes neither.

Agentd's runtime journal rejects a dispatch whose `dispatched_unix_ms` is equal
to or after the staged deadline. A terminal observation must be at or after its
dispatch timestamp; equality is allowed. Commit validation and recovery checks
use the same time-order rules. Recovery can recheck a dispatch deadline where
the corresponding staged record remains; terminal-versus-dispatch ordering is
also checked after the stage has been cleared.
Completion after a valid dispatch is not inferred to be a new dispatch. These
timestamp checks enforce recorded deadline/order semantics and do not refresh
current registry revocation or authenticate a journal timestamp as wall-clock
evidence.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

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

This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product composition, deployment, or external effect authority.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `durablepromptregistry` | `DurablePromptRegistry` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `register_factor` | `register_factor` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `admit_factor_final_use` | `admit_factor_final_use` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `register_realization_payload_final_use_v2` | `register_realization_payload_final_use_v2` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `retire_factor_final_use` | `retire_factor_final_use` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `revoke_factor_final_use` | `revoke_factor_final_use` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `snapshot_v2` | `snapshot_v2` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/v2_tests.rs` |
| `read_compatible_v2` | `read_compatible_v2` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/v2_tests.rs` |
| `dereference_realization_v2` | `dereference_realization_v2` | `codex-rs/hepta-prompt-registry/src/durable.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `promptfactorv1` | `PromptFactorV1` | `codex-rs/hepta-prompt-registry/src/protocol.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `promptrealizationv1` | `PromptRealizationV1` | `codex-rs/hepta-prompt-registry/src/protocol.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `factor_graph_source_v1` | `factor_graph_source_v1` | `codex-rs/hepta-prompt-registry/src/lib.rs` | `codex-rs/hepta-prompt-registry/src/durable.rs` |
| `promptregistryrecoveryanchor` | `PromptRegistryRecoveryAnchor` | `codex-rs/hepta-prompt-registry/src/durable_recovery.rs` | `codex-rs/hepta-prompt-registry/src/durable_recovery_tests.rs` |
| `recovery_anchor` | `recovery_anchor` | `codex-rs/hepta-prompt-registry/src/durable_recovery.rs` | `codex-rs/hepta-prompt-registry/src/durable_recovery_tests.rs` |
| `open_state_dir_with_recovery_anchor` | `open_state_dir_with_recovery_anchor` | `codex-rs/hepta-prompt-registry/src/durable_recovery.rs` | `codex-rs/hepta-prompt-registry/src/durable_recovery_tests.rs` |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.
- Consumer callsites and durable owner stores remain explicit follow-up evidence when not listed above.
- Production implementation, runtime composition, independent acceptance, activation, and release remain false until their separate evidence gates pass.
