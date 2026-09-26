# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: hardened single-attempt generation-bound federated read boundary and an Agentd in-process product composition are implemented as a candidate; current exact-candidate execution and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

The canonical contract implementation remains owned by `codex-rs/hepta-memory-federation`. Product composition uses existing memory-owner capability and read surfaces in `codex-rs/hepta-memory`, is hosted by `codex-rs/hepta-agentd`, and reaches model input through `codex-rs/ext/hepta-memory`. These consumer/host paths do not become alternate owners of the `memory.federation` contract and do not create another authority or memory store.

## 2. Public operations and contract details

Target operations remain `query_peer(peer_enrollment, scoped_query, snapshot_policy, lease) -> RemoteEvidenceResult`; `revalidate_remote(result, grant_epoch) -> RemoteValidity`; `cancel_query(query_id) -> QueryDisposition`.

The implemented V2 source surface is `execute_once(transport, authority, attempt_control, now, query, lease)` plus `observe_cancellation`. `RemoteFederatedResponseV2` binds its exact query, peer, scope, purpose, generation vector, frontier, expiry, ordered evidence items, completeness and terminal observation into a domain-separated response digest. A non-zero opaque digest is not accepted as evidence of those fields.

Remote results retain source owner, observed frontier, scope/purpose binding, effective expiry, completeness, validity and uncertainty. No remote mutation, host enrollment, authority minting or inherited credentials are implied by a query.

## 3. State records and transaction design

No authoritative remote facts, remote writer or peer-consent store are owned by this module. Peer enrollment and permissions remain owned by fleet/authority and memory-owner capability state. Product Agentd stores only bounded owner-layout enrollment candidates; each physical federated recall rediscovers currently active capabilities.

The product reader resolves the owner active generation under an operation-scoped shared fence, which recovery takes exclusively during publication. Both retained reader use and attachment revalidation bind `owner_generation_sha256`; changing the active generation invalidates old bindings. The recovered writer retains its separate writer-exclusive lock.

The canonical V2 engine is stateless across attempts. It binds query/lease/remote response/post-I/O authority observation into result evidence. The current product composition does not add a federation cache or retry queue. If a future cache is admitted, it remains a non-authoritative projection and must bind peer identity, grant/principal, query digest, remote frontier, effective expiry and deletion/revocation cutoff.

## 4. Deterministic algorithm and scheduling

For one V2 attempt:

1. validate the exact bounded query and capability lease;
2. obtain a live preflight authority observation, require unexpired `Current`, and reject a lease whose expiry exceeds the observed durable authority expiry before any transport dispatch;
3. race one authenticated/read-only transport future against cancellation and the `min(query_deadline, lease_expiry)` authority horizon;
4. acquire/verify the exact-scope owner memory frontier from the same read snapshot as the candidate set, then verify the terminal remote response shape and recomputed response digest;
5. verify peer, exact query binding, scope and purpose;
6. perform a second fresh post-I/O authority observation before evidence admission and reject observation-time regression;
6a. preserve `Partial + []` as partial coverage and bind evidence-item order because bounded selection is prefix-sensitive;
7. reject an observation outside the query, lease or response time horizon;
8. suppress evidence when post-I/O authority is revoked or generation-stale;
9. cap result expiry to `min(response_expiry, lease_expiry, query_deadline, live_authority_expiry)`;
10. bind the post-I/O authority state, observation time and durable authority expiry into the final result digest.

There is no blind retry. Dropping the transport future is the in-flight cancellation boundary; a production transport must stop further adapter I/O when that future is dropped. Any separately authorized retry requires a new nonce/attempt identity.

Product `CognitiveRuntime::AvailableFederatedV2` applies this boundary per currently enrolled owner. Capability discovery collects completed owners under a one-second sub-budget, retaining healthy results when another owner stalls; admitted peer attempts run under the remainder of one two-second request horizon, while deterministic sorting/deduplication before admission and after collection prevents completion order from changing output order. Aggregate coverage preserves requested/completed/failed peers, peer truncation, owner-candidate omission, item truncation and typed discovery/deadline-authority/integrity/transport failure counts. A scope/transport failure is not relabeled as a successful empty result. A clean discovery with no active grant consumes no request slot. An active grant for a different consumer-workspace digest is filtered before enrollment and never triggers transport. An owner store whose enrollment state cannot be observed contributes a bounded failed slot. Post-I/O revoked/stale terminal attempts also contribute failed aggregate coverage because they produced no admissible evidence.

Ownership is intentionally split at this boundary: `memory.federation::execute_once` is a **one-peer checked engine** and every native `FederatedResultV2` has `requested_peers = 1`. The `<=16` peer discovery/fan-out/aggregation policy is owned by the product orchestrator in `codex-hepta-memory::CognitiveRuntime::AvailableFederatedV2`, which invokes the canonical engine once per admitted peer under one total request horizon. The canonical crate must not grow a second peer registry or product scheduler; the product orchestrator must not reimplement response integrity or authority admission.

## 5. Capacity and performance profile

Canonical V2 accepts at most 512 remote evidence items for one peer and never performs multi-peer orchestration internally. Product federation retains the existing `MAX_FEDERATION_SOURCES_PER_AGENT = 16` source ceiling and the memory retrieval result ceiling. Agentd product composition owns bounded peer iteration/aggregation under one total recall horizon and no engine-owned retry queue.

The <=16-peer / <=512-final-ID values are enforced architecture bounds. The current in-process product path now exercises bounded concurrent fan-out under one two-second total horizon, but this is still not target-host latency/backpressure evidence and is not evidence that a future network transport can meet the same budget; cross-host activation still requires measured fan-out, overload and cancellation behavior on the selected host.

## 6. Concrete verification cases

Source tests now include identities for:

- FED-01: peer/scope/query-binding/lease drift and cross-query replay reject;
- FED-02: non-terminal transport remains explicit indeterminate and bounded truncation remains partial;
- FED-03: response-field tampering and item-order permutation invalidate the recomputed response digest;
- FED-03A: `Partial + []` remains partial rather than becoming a valid empty result;
- FED-04: result expiry cannot exceed response, lease or query horizon;
- FED-05: a revoked/stale live authority observation fails before transport dispatch;
- FED-06: post-I/O revoke/generation drift suppresses remote items;
- FED-07: cancellation/deadline or an earlier lease expiry interrupts a pending transport future;
- FED-07A: a widened caller lease or already-expired `Current` authority observation rejects before transport dispatch;
- FED-08: duplicate remote record identity rejects;
- FED-09: final result digest binds the post-I/O authority observation;
- FED-10: product runtime keeps explicit requested/completed/failed/truncated coverage and revalidates an attachment against current owner capability state;
- FED-11: unobservable owner capability discovery and post-I/O revoked/stale attempts remain failed aggregate coverage instead of disappearing;
- FED-12: a grant for another consumer workspace never enters queried coverage or transport dispatch;
- FED-13: combined local+federated model input preserves the exact federation coverage vector;
- FED-14: physical-send revalidation is bounded and fails closed on timeout/unavailability;
- FED-15: the owner memory frontier is read from the same exact-scope SQLite snapshot as candidates; an empty scope may truthfully report frontier zero, while non-empty evidence cannot;
- FED-16: product aggregation preserves peer truncation, owner-candidate omission and typed failure coverage rather than collapsing those states into `failed_peers`;
- FED-17: admitted peer attempts are concurrently polled under one global horizon and deterministic aggregation does not depend on completion order.

- FED-18: real owner recovery cannot revive predecessor grants, records or prepared bindings; corrected/forgotten evidence becomes stale.
- FED-19: an active read operation fences generation publication; an idle retained reader is rejected after publication; a missing fence never causes legacy fallback.
- FED-20: missing and stalled owner discovery preserves healthy evidence with deterministic bounded failure coverage.

Test source identity is not an execution receipt. Exact-head/merge-candidate outputs determine pass/fail for the candidate revision.

## 7. Integration, rollback and capability ceiling

Agentd product composition uses `CognitiveRuntime::AvailableFederatedV2`. The host passes the consumer Agent identity and bounded owner-layout candidates. The physical in-process owner read is adapted to the canonical V2 transport; preflight/post-I/O authority rediscoveries bind the current durable capability state. The memory extension performs another capability/memory revalidation at physical model-request assembly, bounded by the product read timeout and fail-closed on timeout/unavailability. Repository-wide dispatch semantics define this as a final-use source-currentness fence before transport entry, not retroactive cancellation authority over a provider attempt that has already been admitted.

The legacy `CognitiveRuntime::AvailableFederated` / `FederatedRecallSet` surface remains for compatibility-focused callers and tests. Product model-input registration requires `has_product_federation()` and calls the V2-only `retrieve_product_federated` / `revalidate_product_federated` APIs, which reject the legacy variant. Rollback may restore a legacy caller only as an explicit compatibility rollback; it cannot silently enter the canonical product attachment path or convert failed/unavailable peer observations into claims that V2 executed.

Remote evidence retains provenance and cannot become trusted instructions. No-writer capability and immediate revoke/stop behavior remain mandatory. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Canonical entrypoints:** `execute_once` and `observe_cancellation` in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs).
- **Canonical contract state:** `FederatedQueryV2`/`FederatedLeaseV2` bind peer, principal, scope, purpose, generation, epoch, nonce and deadline. `RemoteFederatedResponseV2` is query-bound and digest-verified. `FederationAuthorityV2` supplies both preflight and post-I/O live authority observations; only preflight `Current` may dispatch. `FederationAttemptControlV2` provides the interruptible cancellation and query/lease horizon boundary. Results distinguish valid, stale-generation, revoked and indeterminate outcomes while granting no authority.
- **Product caller:** `CognitiveRuntime::AvailableFederatedV2` in `codex-rs/hepta-memory/src/cognitive_runtime.rs`, composed by `codex-rs/hepta-agentd/src/runtime.rs` and consumed by `codex-rs/ext/hepta-memory/src/cognitive/federation.rs`.
- **Owner authority source:** existing `CognitiveStore` federation capability grant/revoke records and `FederatedMemoryReader` read-only owner access; the canonical module does not become a writer of those facts.
- **Source tests:** [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs), plus product composition tests in `codex-rs/hepta-memory/src/cognitive_runtime_tests.rs`. These remain test identities until current candidate execution receipts pass.
- **Implementation and operating references:** [docs/modules/memory.federation/TECHNICAL.md](../../../docs/modules/memory.federation/TECHNICAL.md) and [docs/modules/memory.federation/V2_HARDENING.md](../../../docs/modules/memory.federation/V2_HARDENING.md).
- **Remaining repository-controlled work:** obtain exact-candidate package/product execution receipts, update the implementation-map head attestation from those receipts, and close any compilation or integration defect they expose.
- **Current frontier semantics:** the in-process adapter reads the exact-scope memory frontier from the same owner SQLite snapshot used for candidate retrieval. A true empty scope may produce frontier `0`; non-empty evidence requires a non-zero frontier. Capability revision remains a separate authority identity and is never substituted for the data frontier.
- **Remaining external gates:** independent semantic/security review, genuine multi-host authenticated transport plus coherent remote data-frontier qualification if federation crosses process/host boundaries, target-host/operator acceptance, canary, promotion and release.
