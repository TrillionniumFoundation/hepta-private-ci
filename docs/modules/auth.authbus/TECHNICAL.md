# auth.authbus technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `auth.authbus`

**Owner:** `identity-access`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `AUTHBUS-P1.3-V12`

This stable document is the implementation guide for `auth.authbus`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own policy, quota and reservation facts while separating authorization from external secret effects.

The primary owner `identity-access` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `service`, state model `stateful` and architecture role `immutable_kernel` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-authbus`
- `codex-rs/hepta-authbus-p1-3-qualification`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-authbus`
- `codex-rs/hepta-authbus-p1-3-qualification`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-authbus/src/lib.rs](../../../codex-rs/hepta-authbus/src/lib.rs). The current candidate exports the signed-ingress compatibility surface plus `AuthBusAuthorityHost`, durable policy/quota/reservation types, issuer/trusted-time verification and rollback/recovery checkpoints. Cross-owner source composition is anchored in Agentd signed-text ingress and `BaoClient::consume_kv_v2_with_authbus`; those callsites do not transfer ownership of AuthBus facts. Read the [current native implementation](../../lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md) and [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/auth.authbus.md) together. Exact-candidate execution, activation and acceptance remain separate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `kernel.authority`
- `kernel.operations`

Authoritative write domains:

- `auth_policy`
- `quota_registry`
- `quota_reservation`

Explicitly denied capabilities:

- `provider_call`
- `openbao_mutation_without_grant`
- `learned_authority`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `signed typed ingress and replay fence`
- `checkpointed authority owner host`
- `revisioned policy and issuer core`
- `conservation-safe quota/reservation writer`
- `restart/rollback reconciler and terminal archive`
- `bounded read projection`
- `Agentd outbox adapter`
- `Bao final-use/quota integration adapter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::auth_policyV1`
- `DomainRead::quota_registryV1`
- `DomainRead::quota_reservationV1`
- `ModulePort::auth.authbus::secrets.heptabao`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::kernel.authority::auth.authbus`
- `ModulePort::kernel.operations::auth.authbus`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `auth_policy`
- `quota_registry`
- `quota_reservation`

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

`AuthBusAuthorityHost` is the production-shaped mutation façade for policy/quota/trust state. Its SQLite store uses WAL, FULL synchronous writes and `BEGIN IMMEDIATE`; mutating owner calls must not bypass the host because successful or failed mutations can advance trusted time and every dirty frontier must be published to the independently retained checkpoint before returning. Replay/delivery remains owned by `HeptaEvidenceStore`, with Agentd separately publishing the replay frontier checkpoint. `DispatchAttempted` is committed before the registered effect boundary; restart converts unresolved attempts to `Indeterminate` before new reservation issuance.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Both durable owners use an external anti-rollback witness. A local mutation first commits a dirty semantic frontier; publication then CAS-replaces the external checkpoint with fsync/rename/directory-sync and finally promotes the local checkpoint. A newer external witness with an older restored database is `RollbackDetected`. A crash after dispatch but before terminal settlement retains quota as `Indeterminate`; a timeout never proves `NotApplied`. Terminal reservation compaction is allowed only after the state is settled/released/expired/cancelled and preserves immutable operation identity in the archive.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory. Independently operated checkpoint/trusted-time services and target-host power-loss evidence are activation gates, not facts created by repository source.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/auth.authbus.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-authbus/src/lib.rs](../../../codex-rs/hepta-authbus/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Agentd is a named source-composed caller of durable signed-text admission and requires protected trust plus an external replay checkpoint. `AuthBusAuthorityHost` is the named durable owner façade for policy/quota/trust mutations. The bounded Bao KV-v2 path source-composes that owner with an exact operation identity, reservation/effect digest, kernel `FinalUseBinding`, provider observation and independently signed settlement evidence. These source callsites do not establish production enrollment, operator activation or target-host qualification.

Current operating and state-format references:

- [codex-rs/hepta-authbus/SIGNED_ADMISSION.md](../../../codex-rs/hepta-authbus/SIGNED_ADMISSION.md).
- [codex-rs/hepta-agentd/AUTHBUS_TEXT.md](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-authbus/src/quota_store_tests.rs](../../../codex-rs/hepta-authbus/src/quota_store_tests.rs): concurrent last-unit reservation and idempotency/conflict cases;
- [codex-rs/hepta-authbus/src/settlement_store_tests.rs](../../../codex-rs/hepta-authbus/src/settlement_store_tests.rs): dispatch fence, signed settlement, cancellation, DB invariant bypass and compaction;
- [codex-rs/hepta-authbus/src/recovery_tests.rs](../../../codex-rs/hepta-authbus/src/recovery_tests.rs): old-database rollback and restart reconciliation;
- [codex-rs/hepta-evidence/src/authbus_recovery_tests.rs](../../../codex-rs/hepta-evidence/src/authbus_recovery_tests.rs): replay checkpoint/retirement recovery;
- [codex-rs/hepta-agentd/tests/authbus_text_product.rs](../../../codex-rs/hepta-agentd/tests/authbus_text_product.rs): daemon/App Server signed-text product path;
- [codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs): TLS AuthBus/final-use/settlement product path and timeout hold.

In `codex-rs`, run the focused AuthBus, evidence, Agentd and Bao packages, followed by strict Clippy and the repository exact-head/synthetic-merge workflows. Test names are source anchors only until the unchanged candidate has terminal-success execution receipts.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `AUTHBUS-P1.3-V12`

The bootstrap package is `AUTHBUS-P1.3-V12`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `auth.authbus`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `AUTHBUS-P1.3-V12`

- State: `source_implemented_semantic_review_pending`; priority: `1`; parallel class: `independent_qualification_source`.
- Owner/deputy: `identity-access` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-authbus/**`
- `codex-rs/hepta-authbus-p1-3-qualification/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- Activation predecessors:
- `P0.7B-B0-VERIFIED-USE`
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

The canonical readiness overlay binds `auth.authbus` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `auth.authbus` is implemented by work package `AUTHBUS-P1.3-V12` in:

- `codex-rs/hepta-authbus`
- `codex-rs/hepta-authbus-p1-3-qualification`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

## Correctness continuation: enforced owner boundaries

The raw `AuthBusAuthorityStore` is crate-private. Public mutations enter
`AuthBusAuthorityHost`, with an async permit and stable database/checkpoint
file locks covering predecessor recovery, local mutation, external publication
and local promotion. An alternate witness filename cannot bypass the database
lock. A visible witness is re-fsynced before acknowledging a previously
uncertain publication. `OwnerBusy` and publication failure do not prove that a
prior operation did not commit; preserve its operation identity when querying.

Settlement resolves the `Settlement`-purpose issuer inside the owner write
transaction, not from a caller-provided registration. New results require an
active epoch at admission; exact retries of already committed results remain
readable after revocation. The immutable `dispatched_at_ms` is distinct from
`updated_at_ms`, so later uncertainty cannot invalidate a legitimate earlier
observation. Migration 0005 never invents missing legacy dispatch boundaries.
Migration retains the old frontier dialect through an interrupted v4 witness
handshake, then separately publishes the dispatch-bound v2 digest. Once migrated,
the owner rejects legacy-digest downgrades.

Focused regression sources are `hepta-authbus/src/host_tests.rs`,
`settlement_boundary_tests.rs`, `migration_tests.rs`, and the evidence owner's
`authbus_outbox_tests.rs` / `authbus_recovery_tests.rs`. They cover independent
process exclusion, external publication failure/lost ACK, writer-lock trust
races, late success/no-effect after restart, legacy terminal/archive migration,
and signed enqueue through checkpoint recovery, ACK and a second reopen.
Source presence, executable pass results and production qualification remain
separate facts; see `CURRENT_IMPLEMENTATION.md` for the precise contracts.


### Live owner-lock fencing

Stable lock handles are revalidated against the current canonical path, inode,
owner, single-link count and private file/directory permissions at every lock
admission and around checkpoint synchronization. An observed identity failure
permanently fences that handle; recreating a pathname or restoring permissions
does not revive it. A fresh host must reconcile the existing durable frontier.
A post-commit identity failure is an unacknowledged result, not a rollback or a
reason to repeat an external effect. The local OS and private directory owner
remain trusted; this protocol does not claim distributed lock fencing.

The four `host_lock_tests.rs` regressions add live deletion/replacement,
metadata drift, stale-handle rejection and post-commit reopening to the
existing concurrent-owner, migration and checkpoint fault cases.
