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

- **Candidate source identity:** `bd68a5c542546367417a053b26a4d9aa9112ba75`, tree `01879e5896cbea491745a1bdf52b714fbef4e942`. This is the immutable composed-code baseline; descendant documentation-only commits do not widen its code claim.
- **Implemented entrypoints:** `execute_once` and `observe_cancellation` in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs).
- **Remote integrity:** terminal responses bind the exact query and recompute a canonical domain-separated response digest before evidence admission. Query replay, response-field/item mutation, scope/purpose drift and duplicate identities fail closed.
- **Authority and lifetime:** query/lease checks occur before dispatch, live capability authority is revalidated before and after I/O, and result expiry is bounded by remote response, lease and query deadline. Post-I/O revocation/generation drift exposes no remote items.
- **Transport semantics:** `FederationTransportV2` is async and the engine enforces one bounded attempt with explicit cancellation/deadline races. Timeout or cancellation is indeterminate and never triggers a blind retry.
- **Product composition candidate:** [codex-rs/hepta-memory/src/cognitive_federation.rs](../../../codex-rs/hepta-memory/src/cognitive_federation.rs) routes the existing scoped owner-store federation read through the canonical V2 engine. Its authority adapter observes the durable capability head/revocation state, and its transport adapter performs the existing read-only owner `CognitiveStore` retrieval. Only exact V2-admitted candidate identities are returned.
- **Coverage semantics:** the recall-set aggregator preserves requested/completed/failed/indeterminate source coverage instead of silently dropping failed readers. [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs) includes that coverage in the federated model attachment and source-binding digest.
- **Source tests:** [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs), [codex-rs/hepta-memory/src/cognitive_federation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_federation_tests.rs), and the federation tests embedded in [codex-rs/ext/hepta-memory/src/cognitive/federation.rs](../../../codex-rs/ext/hepta-memory/src/cognitive/federation.rs). Test paths are identities until exact-candidate execution receipts pass.
- **Remaining qualification:** exact-head and deterministic synthetic-merge execution, independent semantic/security review, target-host evidence and operator acceptance remain required. A future fleet/network federation transport must satisfy the same authenticated, interruptible and live-authority contract; the current product composition is the existing same-host owner-store path.
