# secrets.heptabao technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `secrets.heptabao`

**Owner:** `secrets-platform`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `HEPTABAO-1-SECRET-BOUNDARY`

This stable document is the implementation guide for `secrets.heptabao`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Bridge governed secret leases and metadata to the external HeptaBao authority without returning raw secrets in receipts.

The primary owner `secrets-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `external_control`, kind `service`, state model `stateful_external` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

Existing declared roots at this exact source snapshot:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The executable adapter is split between [https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs) for exact-version KV v2 consumption and [lease_lifecycle.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs) for provider-native dynamic lease issue/renew/revoke/reconcile. Durable lease metadata and transition rules live in [secret_lease.rs](../../../codex-rs/hepta-contracts/src/secret_lease.rs) and the SQLite CAS owner in [secret_lease_store.rs](../../../codex-rs/hepta-evidence/src/secret_lease_store.rs). This remains a source navigation binding, not production activation or acceptance. Read [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) for executable truth and [SECRET_LEASE_DESIGN.md](SECRET_LEASE_DESIGN.md) for the lifecycle contract.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `kernel.authority`
- `auth.authbus`

Authoritative write domains:

- `secret_metadata`
- `secret_lease`

Explicitly denied capabilities:

- `raw_secret_receipt`
- `self_issued_operator_acceptance`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `typed ingress`
- `policy core`
- `transactional writer`
- `bounded read projection`
- `outbox adapter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::secret_leaseV1`
- `DomainRead::secret_metadataV1`

Consumed contracts:

- `DomainRead::auth_policyV1`
- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::quota_registryV1`
- `DomainRead::quota_reservationV1`
- `ModulePort::auth.authbus::secrets.heptabao`
- `ModulePort::kernel.authority::secrets.heptabao`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `secret_lease`
- `secret_metadata`

Read-only data dependencies:

- `auth_policy`
- `authority_lease`
- `capability_revocation`
- `quota_registry`
- `quota_reservation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The executable state owners and transaction boundaries are specified in [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md), [SECRET_LEASE_DESIGN.md](SECRET_LEASE_DESIGN.md) and [HA_AND_STORAGE.md](HA_AND_STORAGE.md). Lease mutation serialization is owned by `SecretLeaseStore` compare-and-swap, not an in-process mutex. The current SQLite implementation coordinates handles/processes sharing one database; it does not claim multi-host consensus. FinalUse filesystem state remains single-active per private state directory.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use [FAILURE_RECOVERY.md](FAILURE_RECOVERY.md) for the executable crash/timeout matrix. Lease intents become durable before provider mutation. Ambiguous issuance/renew/revoke outcomes enter a quarantine state and are never converted into blind retries. Generic issuance that loses the response before a provider lease ID is observed requires provider-specific or operator reconciliation; source code must not invent evidence that the credential was or was not created.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `secret_value_in_receipt`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Raw credentials never enter general logs, learning datasets, prompt factors, lifecycle records or cross-module receipts. Dynamic value SHA-256 fingerprints are deliberately not persisted because low-entropy values can be enumerable. The trusted synchronous consumer callback is a privileged host capability rather than a sandbox. Application-owned buffers are zeroized on drop, but TLS/HTTP/parser/allocator internals may create temporary plaintext copies. See [SECURITY_INVARIANTS.md](SECURITY_INVARIANTS.md).

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

[CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) and [HA_AND_STORAGE.md](HA_AND_STORAGE.md) specify current limits. FinalUse schema 2 appends fixed-width nonce claims instead of rewriting the complete replay set and no longer has the former 16,384-claim logical ceiling. Revoked grant IDs remain separately bounded, and a long authority epoch still consumes memory/disk. Dynamic request/response field and body limits are enforced by the adapter. These are implementation bounds, not throughput measurements or a distributed-HA claim.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Use the host-enrolled `BaoClient` behind a registered trusted callback. The current integration supports both exact-version KV v2 reads and provider-native dynamic lease issue/renew/revoke/reconcile. Configure CA, issuer, epoch and persistent authority state through the host, pass the provider token through the dedicated channel, and retain ambiguous provider/consumer outcomes without blind retry. A distributed deployment must additionally supply a strongly consistent lease-state backend; the checked-in SQLite implementation is not a multi-host consensus service.

Current operating and state-format references:

- [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md).
- [SECRET_LEASE_DESIGN.md](SECRET_LEASE_DESIGN.md).
- [FAILURE_RECOVERY.md](FAILURE_RECOVERY.md).
- [HA_AND_STORAGE.md](HA_AND_STORAGE.md).
- [SECURITY_INVARIANTS.md](SECURITY_INVARIANTS.md).
- [codex-rs/hepta-bao-adapter/README.md](../../../codex-rs/hepta-bao-adapter/README.md).
- [codex-rs/hepta-contracts/FINAL_USE.md](../../../codex-rs/hepta-contracts/FINAL_USE.md).
- [external/HeptaBao/README.md](../../../external/HeptaBao/README.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs); exact-version KV v2 TLS/final-use cases.
- [codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs); duplicate-issuance winner and ambiguous-response recovery cases.
- [codex-rs/hepta-contracts/src/final_use_tests.rs](../../../codex-rs/hepta-contracts/src/final_use_tests.rs); nonce-journal durability/migration/revocation cases.
- [codex-rs/hepta-evidence/src/secret_lease_store_tests.rs](../../../codex-rs/hepta-evidence/src/secret_lease_store_tests.rs); exact-idempotent create and multi-handle CAS cases.

In `codex-rs`, run `cargo test --locked -p codex-hepta-contracts -p codex-hepta-bao-adapter -p codex-hepta-evidence`. The command is a test invocation, not a stored result. The dedicated exact-candidate workflow emits a commit/tree/source-digest receipt only after its checks pass.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `HEPTABAO-1-SECRET-BOUNDARY`

The bootstrap package is `HEPTABAO-1-SECRET-BOUNDARY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `secrets.heptabao`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `HEPTABAO-1-SECRET-BOUNDARY`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `secrets-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-bao-adapter/**`
- Development predecessors:
- `AUTHBUS-P1.3-V12`
- `P0.7B-B3-BOUNDARIES`
- Activation predecessors:
- `AUTHBUS-P1.3-V12`
- `P0.7B-B3-BOUNDARIES`
- Required deliverables:
- `exact_source_identity`
- `static_verification`
- `focused_tests`
- `clean_worktree`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `secrets.heptabao` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `secrets.heptabao` is implemented by work package `HEPTABAO-1-SECRET-BOUNDARY` in:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. `.github/workflows/hepta-consolidated-source.yml` still verifies the repository-wide gap inventory, but its selected Rust package set is not the `secrets.heptabao` compilation receipt. These receipts are source implementation evidence only. They grant no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
