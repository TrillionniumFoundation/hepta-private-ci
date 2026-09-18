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

The registered primary source is [codex-rs/hepta-memory-federation/src/lib.rs](../../../codex-rs/hepta-memory-federation/src/lib.rs). The hardened generation-bound surface is implemented in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs) and is summarized in [V2_HARDENING.md](V2_HARDENING.md). The V2 boundary recomputes remote response bindings, caps result lifetime by response/lease/query horizons, requires live authority before dispatch and after I/O, and supports interruptible single-attempt transport.

The named product composition is [`CognitiveRuntime::AvailableFederatedV2`](../../../codex-rs/hepta-memory/src/cognitive_runtime.rs), composed by Agentd and consumed by the Memory extension. `CognitiveRuntime::AvailableFederated`/`FederatedRecallSet` remain compatibility surfaces and are not the Agentd product path. This is still a source/composition fact, not proof of exact-current-head execution, independent acceptance, activation or release. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.federation.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.federation.md) for the exact claim boundary and remaining external gates.

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

The hardened V2 boundary has no writer or outbox. Its bounded components are:

- `FederatedQueryV2` / `FederatedLeaseV2`: exact peer, principal, scope, purpose, generation, nonce, deadline and authority-horizon binding;
- `FederationAuthorityV2`: live authority observation before transport dispatch and again after I/O, including the durable authority expiry used to reject widened leases;
- `FederationTransportV2`: one asynchronous, read-only, interruptible attempt; retries belong to a separately authorized outer caller and require new attempt identity;
- `RemoteFederatedResponseV2`: query-bound response whose domain-separated digest is recomputed over all security-relevant fields before admission;
- `FederationAttemptControlV2`: cancellation/deadline boundary; the product adapter stops at the earlier of query deadline and lease expiry;
- `FederatedResultV2`: deny-all, provenance-bearing result with explicit completeness, validity, coverage and effective expiry;
- product adapter/aggregator in `hepta-memory::CognitiveRuntime::AvailableFederatedV2`: discovers scoped grants, invokes the canonical V2 boundary per admitted peer and preserves aggregate coverage;
- physical-send revalidator in the Memory extension: rechecks capability and exact memory binding immediately before model-input delivery.

No component in this module enrolls peers, mutates a remote store, owns credentials, issues grants, writes cognitive facts or maintains a retry queue. Current owner/capability facts stay in their existing owners. Hidden mutable singletons, unbounded queues, blind retries and implicit fallback to the legacy federation path are prohibited on the Agentd product composition.

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
- the existing owner cognitive store and exact memory/source revision bindings used by the product adapter.

`memory.federation` owns no database, migration, remote fact, enrollment registry, credential store or durable retry state. The current product adapter opens existing owner cognitive state through the established read-only federation reader and never creates a second memory database. Durable capability grant/revoke history remains owned by the cognitive store/authority boundary.

Any future cache is non-authoritative and must bind peer/principal/scope/query/frontier-or-snapshot witness/expiry/deletion-revocation cutoff. Restore may discard such a cache; it may never renew consent, revive a revoked grant or become a source of truth. A future cross-host profile that introduces persisted transport metadata or a new wire schema requires its own owner-reviewed migration and rollback contract before composition.

## 7. Runtime, concurrency and transaction model

The canonical V2 engine is stateless across attempts. One call performs:

1. query and lease shape/binding validation;
2. live-authority preflight, which must be unexpired `Current` and must prove that the supplied lease does not extend past the live authority expiry;
3. one transport future raced against attempt control;
4. response shape, digest and exact query binding verification;
5. a second live-authority observation;
6. final validity/completeness/expiry calculation and result-digest sealing.

The engine holds no global lock across I/O and owns no transaction. Product `CognitiveRuntime::AvailableFederatedV2` keeps only bounded owner-layout candidates plus the consumer identity, rediscovers current read-only grants for each physical retrieval, and caps total source slots at the existing federation bound. The product budget includes discovery; individual attempts share the request's global horizon rather than each receiving a fresh unbounded timeout.

The local in-process adapter may temporarily hold the retrieved batch in request-local memory until canonical V2 admission completes. Stale/revoked/failed results never release that captured batch to downstream attachment. Final model-input revalidation is another bounded read and drops the federated proposal on timeout or drift.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply to the underlying owner stores; this adapter must not widen their transaction or lock boundaries.

## 8. Failure semantics, recovery and rollback

Failures are not collapsed into a successful empty read:

- response digest/query/peer/scope/purpose mismatch rejects the attempt;
- non-current preflight authority prevents transport dispatch;
- timeout, cancellation or transport nonterminal outcome is indeterminate/failed coverage and never triggers blind retry;
- post-I/O revoke or generation drift suppresses all remote items and contributes failed aggregate coverage;
- an unobservable owner capability store contributes a bounded failed discovery slot, while a successfully observed owner with no active matching grant is simply not enrolled;
- a grant for a different consumer workspace is filtered before a query is formed;
- final physical-send revalidation timeout, capability drift, memory drift or secret-like content removes the federated proposal rather than blocking the turn or sending stale evidence.

The module has no durable local state to replay after restart. Rollback may stop using the V2 product caller and discard ephemeral results, but it must not restore revoked authority or reinterpret stale cached evidence as current. The compatibility `AvailableFederated` path is not an automatic product fallback.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware. A caller-provided lease is not itself the authority ceiling: live authority observation supplies the durable expiry, and a longer lease is rejected before transport dispatch.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The canonical V2 result bound is `MAX_FEDERATED_RESULTS_V2 = 512`. The product caller preserves the existing `MAX_FEDERATION_SOURCES_PER_AGENT = 16` bound; owner-layout enrollment candidates are additionally bounded before discovery. The current in-process product read uses one total bounded federation budget that includes capability discovery and physical attempts, so adding peers does not multiply an unbounded per-peer wall-clock allowance. Result aggregation is deterministic and final candidate selection is capped again by the existing memory retrieval result bound.

These are enforced source limits, not deployment latency/SLO measurements. A cross-host profile still requires measured transport budgets, authenticated peer limits and target-host overload evidence.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The native federation contract validates scoped remote observations; its result does not enroll a peer or establish a general network service. The current Agentd product caller supplies bounded owner-layout candidates, rediscovers active grants, filters the exact consumer workspace before enrollment, and adapts the local owner read through canonical V2. Unobservable owner capability stores remain explicit bounded failed coverage; revoked or generation-stale post-I/O observations cannot contribute admissible evidence.

The Memory extension preserves requested/completed/failed/truncated coverage through pure federated and combined local+federated model-input payloads, and revalidates capability plus memory again under a bounded timeout at physical model-request assembly.

The current in-process adapter's `observed_frontier` is the durable capability revision used for provenance; it is not a coherent memory-ledger snapshot frontier. A multi-process or multi-host profile must authenticate its real remote data frontier/snapshot witness. Preserve partial coverage/unavailable on timeout and invalidate evidence on revocation, generation drift or deletion.

Current operating and state-format references:

- [codex-rs/hepta-memory-federation/src/lib.rs](../../../codex-rs/hepta-memory-federation/src/lib.rs).
- [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs).
- [codex-rs/hepta-memory/src/cognitive_runtime.rs](../../../codex-rs/hepta-memory/src/cognitive_runtime.rs).
- [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs).
- [V2_HARDENING.md](V2_HARDENING.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-memory-federation/src/lib_tests.rs](../../../codex-rs/hepta-memory-federation/src/lib_tests.rs).
- [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs), covering response-binding tamper/replay, expiry ceilings, preflight/post-I/O authority drift, true in-flight cancellation/deadline interruption, duplicate identities and bounded partial results.
- [codex-rs/hepta-memory/src/cognitive_runtime_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_runtime_tests.rs), covering product composition, explicit discovery failure coverage and wrong-workspace non-enrollment.
- [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs), whose focused tests cover physical-send revalidation and coverage-preserving combined model input.

The candidate also carries a read-only focused workflow at [`.github/workflows/memory-federation-v2-final-verify.yml`](../../../.github/workflows/memory-federation-v2-final-verify.yml). Commands and workflow definitions are not pass receipts: inspect exact-current-head and merge-candidate outputs before changing `productExecutionProved` or any activation/release claim. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.federation.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-3-FEDERATION`

The bootstrap package is `MEM-3-FEDERATION`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

The named source-level product caller is `CognitiveRuntime::AvailableFederatedV2`, wired through Agentd/App Server and the Memory extension. This satisfies composition identity but does not by itself prove product execution, activation or release; those states remain gated on exact-candidate evidence and external acceptance.

`CognitiveRuntime::AvailableFederated` and `FederatedRecallSet` are retained as compatibility/test surfaces. Product Agentd registration must not automatically fall back to them. Retirement requires remaining compatibility callers migrated, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

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
