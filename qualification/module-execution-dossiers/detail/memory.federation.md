# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: canonical V2 boundary hardened and composed into the existing product cognitive-federation read path; exact-candidate CI, independent acceptance, activation/release, and a genuinely remote cross-host transport profile remain separate gates listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`query_peer(peer_enrollment, scoped_query, snapshot_policy, lease) -> RemoteEvidenceResult`; `revalidate_remote(result, grant_epoch) -> RemoteValidity`; `cancel_query(query_id) -> QueryDisposition`. Remote results include source owner, observed frontier, scope, expiry, completeness and uncertainty. No remote mutation or host enrollment is implied by a query.

## 3. State records and transaction design

No authoritative remote facts, remote writer or peer-consent store. A local bounded result cache is a non-authoritative projection with peer identity, grant/principal, query digest, remote frontier, expiry and deletion/revocation cutoff. Peer enrollment and permissions come from fleet/authority owners. Cached consent is not renewable by this module.

## 4. Deterministic algorithm and scheduling

Validate enrolled destination, exact query/lease binding and current read authority before dispatch. `execute_once` owns the attempt deadline and cancellation race around the async transport future; the transport cannot silently widen the retry policy.

The remote response is sealed with a domain-separated digest over query binding, peer, scope, purpose, generation, frontier, expiry, completeness and every evidence identity/digest. Re-observe authority after transport completion before releasing evidence. Revocation, authority expiry or generation drift after dispatch strips remote items and returns the corresponding non-current validity. Successful result expiry is the minimum of remote response expiry, query deadline, lease expiry and current authority expiry.

The composed product adapter in `codex-rs/hepta-memory/src/cognitive_federation_v2.rs` reuses the existing SQLite capability owner and cognitive memory store. It converts the owner retrieval into digest-only V2 evidence, retains raw payload only in request-local state, and releases that payload only after V2 admission matches the exact evidence set. The multi-reader product path preserves requested/completed/failed source coverage instead of collapsing a failed peer into a valid empty result.
## 5. Capacity and performance profile

Pilot <=16 queried peers per request, <=512 result IDs total, fixed per-peer deadlines and bounded retry only for operations whose read/idempotency profile permits it. Record remote latency, coverage, truncation, lease expiry and cache invalidation.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- FED-01: remote principal/scope mismatch and stale grant are rejected.
- FED-02: one peer timeout yields explicit partial coverage, not zero utility or fabricated empty data.
- FED-03: deletion/revocation invalidates caches and blocks restored stale results.
- FED-04: a discovered peer is not automatically enrolled or sent credentials.

These cases now have source-level implementations in `codex-rs/hepta-memory-federation/src/v2_tests.rs` and `codex-rs/hepta-memory/src/cognitive_federation_tests.rs`, including tamper/replay, timeout/cancellation, post-I/O revocation/generation drift, genuine empty-frontier and partial multi-peer coverage cases. They remain test identities until exact-candidate CI receipts and independent review are attached; source presence is not an execution receipt.

## 7. Integration, rollback and capability ceiling

Provide a read-only peer adapter contract and no-writer capability test. Remote evidence retains provenance and cannot become trusted instructions. Rollback discards incompatible caches; it never restores a revoked enrollment or remote data authority.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Canonical entrypoints:** `execute_once` and `observe_cancellation` in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs). `execute_once` is async, owns timeout/cancellation admission, verifies the sealed remote-response digest, caps result expiry, and performs pre/post authority observations.
- **Product composition:** [codex-rs/hepta-memory/src/cognitive_federation.rs](../../../codex-rs/hepta-memory/src/cognitive_federation.rs) routes `FederatedMemoryReader::retrieve` through [codex-rs/hepta-memory/src/cognitive_federation_v2.rs](../../../codex-rs/hepta-memory/src/cognitive_federation_v2.rs). The existing `CognitiveStore` remains the only durable memory/capability owner; no second database or grant authority was introduced.
- **Physical consumer:** [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs) carries V2 coverage and admission expiry into the federated model-input payload/source binding, rechecks expiry, capability and memory currentness immediately before physical model input.
- **State and recovery:** V2 itself owns no peer registry, remote writer, cache database or retry queue. Product authority observations come from the existing persisted federation capability heads/events. Raw owner retrieval payload is request-local and is not released to the caller until its digest-only evidence set is admitted by V2.
- **Failure semantics:** timeout/cancellation are explicit indeterminate outcomes; revocation, generation drift and authority expiry observed after transport cannot expose remote items. Multi-peer aggregation reports requested/completed/failed coverage rather than silently turning a failed source into an empty success.
- **Source tests:** [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs), [codex-rs/hepta-memory/src/cognitive_federation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_federation_tests.rs), and the extension tests in [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs). These are test identities, not pass receipts for this documentation revision.
- **Current code-candidate attestation:** `docs/modules/memory.federation/IMPLEMENTATION_MAP.json` records the module code candidate immediately before documentation-only updates. The shared map `sourceBase` remains the repository-wide generation baseline and must stay identical across all module maps.
- **Remaining work / claim boundary:** exact-candidate and synthetic-merge CI receipts, independent semantic/security review, target-host qualification, activation and release remain unproved. The composed product adapter uses the existing owner-store boundary; a genuinely remote authenticated cross-host transport must be separately qualified before claiming cross-host federation.
