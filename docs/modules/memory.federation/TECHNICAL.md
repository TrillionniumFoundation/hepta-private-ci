# memory.federation technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `memory.federation`

**Owner:** `cognitive-platform`

**Deputy:** `security-authority`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-3-FEDERATION`

This stable document is the implementation guide for `memory.federation`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Read remote cognitive evidence under scoped grants without blind retry or remote mutation.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `adapter`, kind `service`, state model `read_only_remote` and architecture role `checked_adapter` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-memory-federation`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-memory-federation`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-memory-federation/src/lib.rs](../../../codex-rs/hepta-memory-federation/src/lib.rs); observed identifiers include `FederatedReadRequest`, `FederatedReadLease`, `RemoteObservation`, `FederatedReadReceipt`, `observe`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.federation.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.federation.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `cognitive.read`
- `kernel.authority`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `write_authority`
- `blind_retry`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The implementation is intentionally split so the canonical federation contract does not become another memory or authority owner:

- `FederatedQueryV2` / `FederatedLeaseV2`: exact peer, consumer, scope, purpose, generation, query, nonce, epoch and deadline binding.
- `FederationAuthorityV2`: pre- and post-transport current-authority observations. Enrollment, revocation and capability lifetime remain owned by the existing authority/cognitive-store boundary.
- `FederationTransportV2`: one async attempt represented as a cancellable future. The engine owns the timeout/cancellation race and does not contain a retry queue.
- `RemoteFederatedResponseV2`: terminal digest-only evidence sealed over the exact query binding and every security-relevant response field.
- `FederatedResultV2`: validated complete/partial/empty/indeterminate output with explicit validity, coverage, effective expiry and authority-observation digest.
- Product adapter: `codex-rs/hepta-memory/src/cognitive_federation_v2.rs` maps the existing SQLite federation capability owner and cognitive-store retrieval into these canonical V2 contracts. Raw retrieval payload is request-local and is released only after the V2 evidence set is admitted.
- Physical model-input consumer: `codex-rs/ext/hepta-memory/src/cognitive/federation.rs` binds source coverage and V2 admission expiry into the prepared attachment and revalidates before physical model input.

The product adapter does not create a second peer registry, capability database, remote fact store or writer. The existing `CognitiveStore` remains the durable fact and federation-capability owner. A future cross-host transport must implement the same canonical interface without inheriting credentials or weakening the authority checks.

## 5. Contracts, ports and compatibility

Produced contracts:

None.

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `ModulePort::cognitive.read::memory.federation`
- `ModulePort::kernel.authority::memory.federation`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

`execute_once` is asynchronous. It validates query/lease state, observes current authority, derives an attempt cutoff from the minimum of query deadline, lease expiry and authority expiry, then races the transport future against cancellation and an engine-owned timeout. No module lock is held across transport I/O and no detached retry/background queue is permitted by this boundary.

After transport completion the engine obtains a second authority observation. Only then can a terminal remote response be admitted. The product adapter reads the persisted federation capability head for both observations. The owner retrieval already executes all channels and candidate resolution inside one SQLite read transaction; that same transaction records the append-only owner-memory frontier used as the V2 remote observation witness, so no second read is used to guess coherence.

The product multi-reader aggregator is deterministic: successful batches contribute candidates; failures increment explicit failed-source coverage; ranking is stable and bounded before truncation. The aggregate admission expiry is the minimum successful-peer V2 expiry.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

The canonical boundary distinguishes:

- terminal valid/empty/partial responses;
- nonterminal unavailable/timed-out/cancelled/no-terminal-observation outcomes, returned as indeterminate;
- response-generation drift;
- post-transport revocation;
- post-transport authority expiry;
- malformed, replayed or tampered response digests.

A non-current result never exposes remote evidence items. Successful result expiry is capped by remote response expiry, query deadline, lease expiry and current authority expiry. The product model-input path carries that admitted expiry into its source binding and refuses a federated attachment after expiry even if the raw memory record still exists.

A failed peer in a multi-peer read is counted as failed coverage; it is not converted into a valid empty peer. The module has no retry queue, and a timeout cannot widen scope or trigger unrestricted fallback.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Remote responses are domain-separated and cryptographically bound to the exact query plus peer/scope/purpose/generation/frontier/expiry/completeness and evidence digests; replay across query bindings or payload mutation fails closed. Authority is observed both before dispatch and after transport completion to close the in-flight revocation/generation TOCTOU window. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The canonical V2 contract enforces at most 512 evidence items in one peer response/query. The composed product memory retrieval retains its existing stricter product result bound and uses a two-second single-attempt transport deadline, additionally capped by capability expiry. Multi-peer product coverage is explicit and aggregate admission lifetime is the minimum successful-peer lifetime. These are enforced code bounds, not throughput or latency measurements. Target-host performance measurements remain qualification evidence rather than documentation claims.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The canonical federation contract validates scoped remote observations and still does not enroll peers or mint grants. The currently composed product caller uses the existing persisted federation capability records and existing owner cognitive store as its authority/transport substrate. It reports requested/completed/failed source coverage and carries V2 admission expiry to the physical model-input boundary. This composition does not by itself establish a cross-host network federation service; any network transport must separately authenticate the peer and satisfy the same V2 response/authority checks.

Current operating and state-format references:

- [codex-rs/hepta-memory-federation/src/lib.rs](../../../codex-rs/hepta-memory-federation/src/lib.rs).
- [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-memory-federation/src/lib_tests.rs](../../../codex-rs/hepta-memory-federation/src/lib_tests.rs); named case: `missing_terminal_observation_is_indeterminate`.
- [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs); cases cover response tamper/replay, canonical digest ordering, expiry ceiling, timeout/cancellation, pre/post revocation and generation drift, duplicate identity and empty zero-frontier semantics.
- [codex-rs/hepta-memory/src/cognitive_federation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_federation_tests.rs); cases cover the real persisted grant/revoke owner, product V2 routing and explicit partial multi-peer coverage.
- [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs); extension tests cover the physical model-input proposal and revalidation boundary.

In `codex-rs`, run `just test -p codex-hepta-memory-federation`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.federation.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-3-FEDERATION`

The bootstrap package is `MEM-3-FEDERATION`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

A named product caller candidate is now composed: `FederatedMemoryReader::retrieve` routes through the canonical V2 product adapter and the extension consumes the admitted result at the model-input boundary. This is composition evidence, not activation or release. Exact-candidate CI, independent semantic/security review, target-host qualification and the activation predecessors remain mandatory before changing activation/release claims.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `memory.federation`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-3-FEDERATION`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-memory-federation/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-2-RETRIEVAL`
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

The canonical readiness overlay binds `memory.federation` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-4-FEDERATED-ORGAN-ENROLLMENT`

## 17. Source implementation receipt

The bootstrap source-location obligation for `memory.federation` is implemented by work package `MEM-3-FEDERATION` in:

- `codex-rs/hepta-memory-federation`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

The current composed code candidate is additionally identified by `currentHeadAttestation` in `IMPLEMENTATION_MAP.json`; it binds the canonical V2 source to the `hepta-memory` product adapter and extension physical consumer without changing the repository-wide shared map `sourceBase`. The attestation is provenance metadata, not a CI pass or release receipt.
