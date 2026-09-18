# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: canonical V2 single-attempt federation boundary is implemented and composed into the existing product cognitive read path through a read-only compatibility adapter; external-network qualification, exact-candidate execution evidence and independent acceptance remain separate gates listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`query_peer(peer_enrollment, scoped_query, snapshot_policy, lease) -> RemoteEvidenceResult`; `revalidate_remote(result, grant_epoch) -> RemoteValidity`; `cancel_query(query_id) -> QueryDisposition`. Remote results include source owner, observed frontier, scope, expiry, completeness and uncertainty. No remote mutation or host enrollment is implied by a query.

## 3. State records and transaction design

No authoritative remote facts, remote writer or peer-consent store. A local bounded result cache is a non-authoritative projection with peer identity, grant/principal, query digest, remote frontier, expiry and deletion/revocation cutoff. Peer enrollment and permissions come from fleet/authority owners. Cached consent is not renewable by this module.

## 4. Deterministic algorithm and scheduling

Validate the enrolled destination and short-lived read grant, then observe current authority immediately before dispatch. Bind the query to peer, principal, scope, purpose, generation, epoch, nonce, deadline and maximum result count. Race the one transport future against engine-owned deadline/cancellation, validate the remote response digest over its exact query binding and all security-relevant response fields, then observe current authority again before admitting evidence. The admitted expiry is the minimum of query deadline, original lease expiry, live authority expiry and remote response expiry. Revocation or generation drift after I/O strips remote items. Distinguish unavailable peer, partial result, stale/revoked result and valid empty result; partial answers remain partial and a timeout cannot trigger an unrestricted fallback query.

## 5. Capacity and performance profile

Pilot <=16 queried peers per request, <=512 result IDs total, fixed per-peer deadlines and bounded retry only for operations whose read/idempotency profile permits it. Record remote latency, coverage, truncation, lease expiry and cache invalidation.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- FED-01: remote principal/scope mismatch and stale grant are rejected.
- FED-02: one peer timeout yields explicit partial coverage, not zero utility or fabricated empty data.
- FED-03: deletion/revocation invalidates caches and blocks restored stale results.
- FED-04: a discovered peer is not automatically enrolled or sent credentials.
- FED-05: changing a response field without recomputing its domain-separated response digest is rejected.
- FED-06: a response from one query/nonce cannot be replayed into another query binding.
- FED-07: a remote TTL cannot extend evidence beyond the query, lease or live-authority ceiling.
- FED-08: revoke/generation drift observed after transport prevents returned items from being admitted.
- FED-09: engine deadline or cancellation drops an in-flight transport future instead of waiting for a blocking completion.
- FED-10: a legitimate empty owner store may report frontier zero and remains distinct from an unavailable peer.

These are required product test designs. The native test identities below exercise these cases; CI execution receipts remain candidate-specific rather than implied by this document. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Provide a read-only peer adapter contract and no-writer capability test. Remote evidence retains provenance and cannot become trusted instructions. Rollback discards incompatible caches; it never restores a revoked enrollment or remote data authority.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented canonical entrypoints:** `execute_once` and `observe_cancellation` in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs). `execute_once` is asynchronous, invokes exactly one transport future, owns deadline/cancellation racing, and requires live authority observations before and after terminal I/O.
- **Response integrity:** `RemoteFederatedResponseV2` carries the exact `query_binding_digest`; `compute_response_digest` domain-separates and binds peer, query binding, scope, purpose, generation, frontier, expiry, canonicalized evidence items, completeness and terminal observation. Admission recomputes and compares that digest.
- **Authority and lifetime:** `FederationAuthorityV2` supplies current lease/generation/revocation observations. A post-I/O revoke or generation change prevents evidence items from being admitted. Result lifetime is clamped to the minimum remote/query/lease/live-authority horizon.
- **Product composition:** [codex-rs/hepta-memory/src/cognitive_federation.rs](../../../codex-rs/hepta-memory/src/cognitive_federation.rs) is the current product compatibility adapter. Its `FederatedMemoryReader::retrieve` builds the canonical query/lease, exposes the existing read-only owner SQLite retrieval as `FederationTransportV2`, observes the live capability owner as `FederationAuthorityV2`, invokes canonical `execute_once`, and releases the raw retrieval batch only when the canonical result matches its digest-only evidence projection. The App Server memory extension therefore no longer bypasses the V2 engine.
- **Legacy convergence:** `FederatedRecallSet` remains a compatibility API, not an independent federation authority. It records requested/completed/failed source coverage instead of silently treating a failed source as an empty result. [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs) binds that coverage into federated ephemeral input schema V2 and its physical-send source binding.
- **Source tests:** [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs), [codex-rs/hepta-memory/src/cognitive_federation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_federation_tests.rs), and the tests embedded in [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs).
- **Implementation and operating references:** [docs/modules/memory.federation/TECHNICAL.md](../../../docs/modules/memory.federation/TECHNICAL.md).
- **Remaining work:** the checked-in product path is a native read-only owner-store transport, not evidence of an authenticated cross-host network deployment. External peer enrollment/transport identity, target-host qualification, explicit host cancellation-token plumbing where required, independent semantic acceptance, canary/promotion and release remain separate gates.
