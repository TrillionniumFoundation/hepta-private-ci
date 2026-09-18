# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: single-attempt generation-bound federated read boundary implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`query_peer(peer_enrollment, scoped_query, snapshot_policy, lease) -> RemoteEvidenceResult`; `revalidate_remote(result, grant_epoch) -> RemoteValidity`; `cancel_query(query_id) -> QueryDisposition`. Remote results include source owner, observed frontier, scope, expiry, completeness and uncertainty. No remote mutation or host enrollment is implied by a query.

## 3. State records and transaction design

No authoritative remote facts, remote writer or peer-consent store. A local bounded result cache is a non-authoritative projection with peer identity, grant/principal, query digest, remote frontier, expiry and deletion/revocation cutoff. Peer enrollment and permissions come from fleet/authority owners. Cached consent is not renewable by this module.

## 4. Deterministic algorithm and scheduling

Validate enrolled destination and short-lived read grant; apply outbound payload limits; perform one bounded read; verify response producer/scope/digest/frontier; merge only via the cognitive read/retrieval contracts. Distinguish unavailable peer, partial result, stale result and valid empty result. Partial answers remain partial; a remote timeout cannot trigger an unrestricted fallback query.

## 5. Capacity and performance profile

Pilot <=16 queried peers per request, <=512 result IDs total, fixed per-peer deadlines and bounded retry only for operations whose read/idempotency profile permits it. Record remote latency, coverage, truncation, lease expiry and cache invalidation.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- FED-01: remote principal/scope mismatch and stale grant are rejected.
- FED-02: one peer timeout yields explicit partial coverage, not zero utility or fabricated empty data.
- FED-03: deletion/revocation invalidates caches and blocks restored stale results.
- FED-04: a discovered peer is not automatically enrolled or sent credentials.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Provide a read-only peer adapter contract and no-writer capability test. Remote evidence retains provenance and cannot become trusted instructions. Rollback discards incompatible caches; it never restores a revoked enrollment or remote data authority.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `execute_once` in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs); `observe_cancellation` in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs). The canonical engine is asynchronous, single-attempt and generation-bound.
- **Remote integrity:** `RemoteFederatedResponseV2` carries the exact query binding and a canonical response digest over peer/scope/purpose/generation/frontier/expiry/items/completeness/terminality. The engine recomputes this digest and rejects response-field drift and cross-query replay.
- **Authority and lifetime:** Result expiry is capped by response expiry, lease expiry and query deadline. `execute_once` requires a current authority observation before dispatch and after transport completion, closing the revocation/generation TOCTOU window before evidence admission.
- **Deadline/cancellation:** `FederationTransportV2` returns a cancellation-safe future. The engine applies one hard timeout to preflight + transport + postflight and races it against caller cancellation. Blind retry remains outside this module and requires a new authorized attempt identity.
- **Product-composition candidate:** [codex-rs/hepta-memory/src/cognitive_federation.rs](../../../codex-rs/hepta-memory/src/cognitive_federation.rs) routes `FederatedRecallSet` through the canonical V2 engine. `CanonicalReaderAuthority` reads the existing durable cognitive federation capability head; `CanonicalReaderTransport` adapts the existing read-only per-agent cognitive store and requires the append-only owner memory-revision frontier to remain stable across the read before sealing the canonical response. [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs) is the current model-input caller. This is a candidate composition, not activation evidence.
- **Partial coverage:** Legacy reader failures and dynamic-owner discovery failures are no longer indistinguishable from valid empty federation. `FederatedRetrievalCoverage` carries requested/completed/failed/discovery-failure counts. The extension exposes coverage in schema-v2 federated input, binds it into the final ephemeral source digest, and preserves it in the compact combined path. A valid empty result or an all-failed configured federation emits coverage-only evidence; an unconfigured federation with no discovery uncertainty emits no attachment.
- **Consumer compatibility:** New coverage-aware proposals use `hepta_cognitive_federation_v2` / `hepta_cognitive_combined_v2`; the provider-policy host still admits the legacy v1 source identifiers. The v2 schema therefore adds completeness semantics without silently changing v1 bytes.
- **Source tests:** [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs) covers response tampering/replay, expiry ceiling, post-I/O revocation/generation drift, hard timeout, cancellation, completeness and restored-result coverage. [codex-rs/hepta-memory/src/cognitive_federation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_federation_tests.rs) exercises the durable capability owner, explicit failed-source coverage and dynamic-discovery uncertainty. These are test identities until exact-candidate CI receipts complete.
- **Candidate provenance:** PR #693 is based on `d7af096f28fa9989388939efa0e6600b52a43952`; frozen code candidate `a27de7b0a6e269187f0254751e2b469b719cfdba` is recorded separately from the repository-wide generated `sourceBase`.
- **Remaining work:** exact-head/synthetic-merge qualification, independent semantic review and target-host evidence remain required. Any future network/fleet `FederationTransportV2` must independently prove authenticated peer identity, cancellation safety, deadline enforcement and revocation/currentness. The local product bridge does not establish deployment qualification for a network federation service.
