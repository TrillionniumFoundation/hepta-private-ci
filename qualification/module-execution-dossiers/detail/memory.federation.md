# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: V2 remains the compatibility surface; authenticated capability-scoped V3 is implemented on the candidate branch and requires exact-head/merge-candidate qualification before any activation claim. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining external integration. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

V2 compatibility operations remain `execute_once` and `observe_cancellation`.

V3 native operations are:

- `execute_once_v3(...) -> FederatedResultV3`
- `execute_once_v3_async(...) -> FederatedResultV3`
- `execute_federation_v3(...) -> FederatedAggregateV3`
- `FederationServiceV3::query_peer(...)`
- `FederationServiceV3::revalidate_remote(...)`
- `FederationServiceV3::{purge_grant,purge_key,purge_peer}(...)`

V3 responses bind peer, principal, grant, query binding digest, request nonce, response nonce, scope, purpose, generation, lease epoch, observed frontier, expiry, canonical payload digest and Ed25519 signature. No remote mutation or host enrollment is implied by a query.

## 3. State records and transaction design

No authoritative remote facts or remote writer are owned by this module. `FederatedResultCacheV3` is a bounded non-authoritative projection indexed by grant, authority key and peer for revocation-directed purge. Cache entries retain the originating query and signed capability envelope and are revalidated against the current revocation source before reuse. Effective result expiry is capped by the minimum of remote response expiry, authority lease expiry and query deadline.

Peer enrollment and permissions remain owner-supplied facts. `FederationServiceV3` refuses an unenrolled peer before transport. Cached consent is never renewable by this module.

## 4. Deterministic algorithm and scheduling

V3 performs the following fail-closed sequence:

1. Read a fresh clock value and validate the bounded query.
2. Verify the signed authority envelope and fetch a current signed revocation observation.
3. Reject a pre-cancelled request before transport.
4. Execute exactly one cancellation/deadline-aware transport attempt.
5. Re-read the clock and re-run live authority/revocation verification after I/O.
6. Reject deadline, lease, revocation or capability-generation drift observed during I/O.
7. Verify strong remote query/nonce/grant binding, recompute the canonical payload digest and verify the peer Ed25519 signature.
8. Preserve `Partial` even when zero items are returned, apply deterministic truncation, cap TTL and seal the local result digest with `DENY_ALL` authority.

Multi-peer execution is bounded to <=16 peers and <=512 aggregate items. Child results are deterministically ordered before aggregation. Any child partial, indeterminate, failed coverage or truncation keeps the aggregate partial; an incomplete federation cannot collapse to a fabricated global empty/complete result.

## 5. Capacity and performance profile

Hard V3 limits:

- <=16 queried peers per aggregate request.
- <=512 remote items per peer envelope.
- <=512 items in the final deterministic aggregate.
- one transport attempt per peer per query identity.
- explicit caller deadline and cancellation token on both sync and async transport contracts.

These are enforcement limits, not latency or throughput measurements. Target-host measurements remain an external qualification requirement.

## 6. Concrete verification cases

V2 source tests remain in `src/v2_tests.rs`.

V3 source tests are in `src/v3_tests.rs` and cover:

- partial + zero items remains `Partial`;
- result TTL is authority-bounded;
- remote payload tampering is rejected by canonical digest/signature verification;
- a transport that returns after deadline is rejected using a fresh post-I/O clock;
- revocation occurring during I/O is observed by the second live authority check;
- a response from a different query/nonce cannot be replayed;
- pre-cancellation exposes no remote data;
- cached results are revalidated and revocation-addressable;
- unenrolled peers are rejected before transport.

Exact pass/fail receipts must come from the candidate CI run; this document is not an execution receipt.

## 7. Integration, rollback and capability ceiling

V3 introduces no writer authority. All local and aggregate results remain `AuthorityPosture::DENY_ALL`. Rollback is source-compatible because V2 remains exported unchanged; V3 caches are non-authoritative and may be discarded.

The async transport contract requires an implementation to observe both deadline and cancellation while I/O is in flight. The federation layer independently revalidates after await/return, so a late transport cannot promote stale authority into usable evidence.

No generator self-acceptance, self-merge or self-release is implied.

## 8. Current native implementation

- **Compatibility entrypoints:** `execute_once`, `observe_cancellation` in `src/v2.rs`.
- **Hardened V3 entrypoints:** `execute_once_v3`, `execute_federation_v3` in `src/v3.rs`; `execute_once_v3_async` in `src/v3_ext.rs`; product-facing `FederationServiceV3` in `src/v3.rs`.
- **Authority boundary:** `CapabilityAuthorityEnvelopeV3` + `CapabilityRevocationObservationV3` use canonical digests and Ed25519 verification through `FederationKeyResolverV3`; `SignedCapabilityVerifierV3` performs fresh revocation reads before and after I/O.
- **Remote authenticity:** `RemoteFederatedResponseV3` binds query/grant/nonce/peer/principal/scope/purpose/generation/epoch/frontier/expiry/items and verifies canonical payload digest plus peer signature.
- **Transport:** sync and async cancellation/deadline-aware contracts are source implemented; a concrete selected-host network transport remains host-owned.
- **Federation:** bounded multi-peer fan-out and deterministic aggregate coverage are source implemented.
- **Cache/revalidation:** local bounded cache, TTL capping, revalidation and grant/key/peer purge surfaces are source implemented.
- **Peer composition:** `PeerEnrollmentRegistryV3` and `FederationServiceV3` enforce enrollment before transport. A concrete fleet/network registry adapter remains selected-host integration.
- **Qualification:** V3 source tests exist; exact-head and synthetic-merge CI receipts must be current before changing production/activation/release claims.

## 9. Remaining external gates

Repository source closure does not itself establish a deployed federation. Remaining gates are concrete selected-host adapters (network transport, trust-key resolver, revocation source and peer registry), target-host fault/latency qualification, independent semantic/security review, operator acceptance, canary, promotion and release evidence.
