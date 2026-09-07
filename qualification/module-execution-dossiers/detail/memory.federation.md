# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
