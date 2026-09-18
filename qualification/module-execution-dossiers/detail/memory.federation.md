# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: hardened single-attempt generation-bound federated read boundary and an Agentd in-process product composition are implemented as a candidate; current exact-candidate execution and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

The canonical contract implementation remains owned by `codex-rs/hepta-memory-federation`. Product composition uses existing memory-owner capability and read surfaces in `codex-rs/hepta-memory`, is hosted by `codex-rs/hepta-agentd`, and reaches model input through `codex-rs/ext/hepta-memory`. These consumer/host paths do not become alternate owners of the `memory.federation` contract and do not create another authority or memory store.

## 2. Public operations and contract details

Target operations remain `query_peer(peer_enrollment, scoped_query, snapshot_policy, lease) -> RemoteEvidenceResult`; `revalidate_remote(result, grant_epoch) -> RemoteValidity`; `cancel_query(query_id) -> QueryDisposition`.

The implemented V2 source surface is `execute_once(transport, authority, attempt_control, now, query, lease)` plus `observe_cancellation`. `RemoteFederatedResponseV2` binds its exact query, peer, scope, purpose, generation vector, frontier, expiry, canonical evidence items, completeness and terminal observation into a domain-separated response digest. A non-zero opaque digest is not accepted as evidence of those fields.

Remote results retain source owner, observed frontier, scope/purpose binding, effective expiry, completeness, validity and uncertainty. No remote mutation, host enrollment, authority minting or inherited credentials are implied by a query.

## 3. State records and transaction design

No authoritative remote facts, remote writer or peer-consent store are owned by this module. Peer enrollment and permissions remain owned by fleet/authority and memory-owner capability state. Product Agentd stores only bounded owner-layout enrollment candidates; each physical federated recall rediscovers currently active capabilities.

The canonical V2 engine is stateless across attempts. It binds query/lease/remote response/post-I/O authority observation into result evidence. The current product composition does not add a federation cache or retry queue. If a future cache is admitted, it remains a non-authoritative projection and must bind peer identity, grant/principal, query digest, remote frontier, effective expiry and deletion/revocation cutoff.

## 4. Deterministic algorithm and scheduling

For one V2 attempt:

1. validate the exact bounded query and capability lease;
2. race one authenticated/read-only transport future against deadline/cancellation control;
3. verify the terminal remote response shape and recomputed response digest;
4. verify peer, exact query binding, scope and purpose;
5. perform a fresh post-I/O authority observation before evidence admission;
6. reject an observation outside the query, lease or response time horizon;
7. suppress evidence when authority is revoked or generation-stale;
8. cap result expiry to `min(response_expiry, lease_expiry, query_deadline)`;
9. bind the post-I/O authority observation into the final result digest.

There is no blind retry. Dropping the transport future is the in-flight cancellation boundary; a production transport must stop further adapter I/O when that future is dropped. Any separately authorized retry requires a new nonce/attempt identity.

Product `CognitiveRuntime::AvailableFederatedV2` applies this boundary per currently enrolled owner. Aggregate coverage preserves requested, completed, failed and truncated counts. A scope/transport failure is not relabeled as a successful empty result.

## 5. Capacity and performance profile

Canonical V2 accepts at most 512 remote evidence items in one response. Product federation retains the existing `MAX_FEDERATION_SOURCES_PER_AGENT` source ceiling and the memory retrieval result ceiling. Agentd product composition uses a bounded total recall horizon and no engine-owned retry queue.

Pilot <=16 queried peers per request and <=512 result IDs total remain architecture ceilings rather than production latency measurements. The selected host still requires exact-candidate timing/resource evidence before activation or release.

## 6. Concrete verification cases

Source tests now include identities for:

- FED-01: peer/scope/query-binding/lease drift and cross-query replay reject;
- FED-02: non-terminal transport remains explicit indeterminate and bounded truncation remains partial;
- FED-03: response-field tampering invalidates the recomputed response digest;
- FED-04: result expiry cannot exceed response, lease or query horizon;
- FED-05: post-I/O revoke/generation drift suppresses remote items;
- FED-06: cancellation/deadline interrupts a pending transport future;
- FED-07: duplicate remote record identity rejects;
- FED-08: final result digest binds the post-I/O authority observation;
- FED-09: product runtime keeps explicit requested/completed/failed/truncated coverage and revalidates an attachment against current owner capability state.

Test source identity is not an execution receipt. Exact-head/merge-candidate outputs determine pass/fail for the candidate revision.

## 7. Integration, rollback and capability ceiling

Agentd product composition uses `CognitiveRuntime::AvailableFederatedV2`. The host passes the consumer Agent identity and bounded owner-layout candidates. The physical in-process owner read is adapted to the canonical V2 transport; post-I/O authority revalidation rediscoveries bind the current durable capability state. The memory extension performs another capability/memory revalidation at physical model-request assembly.

The legacy `CognitiveRuntime::AvailableFederated` / `FederatedRecallSet` surface remains for compatibility-focused callers and tests. It is not the intended Agentd product path after this candidate. Rollback may restore the legacy caller only as an explicit compatibility rollback; it must not convert failed/unavailable peer observations into claims that the canonical V2 path executed.

Remote evidence retains provenance and cannot become trusted instructions. No-writer capability and immediate revoke/stop behavior remain mandatory. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Canonical entrypoints:** `execute_once` and `observe_cancellation` in [codex-rs/hepta-memory-federation/src/v2.rs](../../../codex-rs/hepta-memory-federation/src/v2.rs).
- **Canonical contract state:** `FederatedQueryV2`/`FederatedLeaseV2` bind peer, principal, scope, purpose, generation, epoch, nonce and deadline. `RemoteFederatedResponseV2` is query-bound and digest-verified. `FederationAuthorityV2` supplies the post-I/O authority observation. `FederationAttemptControlV2` provides the interruptible deadline/cancellation boundary. Results distinguish valid, stale-generation, revoked and indeterminate outcomes while granting no authority.
- **Product caller:** `CognitiveRuntime::AvailableFederatedV2` in `codex-rs/hepta-memory/src/cognitive_runtime.rs`, composed by `codex-rs/hepta-agentd/src/runtime.rs` and consumed by `codex-rs/ext/hepta-memory/src/cognitive/federation.rs`.
- **Owner authority source:** existing `CognitiveStore` federation capability grant/revoke records and `FederatedMemoryReader` read-only owner access; the canonical module does not become a writer of those facts.
- **Source tests:** [codex-rs/hepta-memory-federation/src/v2_tests.rs](../../../codex-rs/hepta-memory-federation/src/v2_tests.rs), plus product composition tests in `codex-rs/hepta-memory/src/cognitive_runtime_tests.rs`. These remain test identities until current candidate execution receipts pass.
- **Implementation and operating references:** [docs/modules/memory.federation/TECHNICAL.md](../../../docs/modules/memory.federation/TECHNICAL.md) and [docs/modules/memory.federation/V2_HARDENING.md](../../../docs/modules/memory.federation/V2_HARDENING.md).
- **Remaining repository-controlled work:** obtain exact-candidate package/product execution receipts, update the implementation-map head attestation from those receipts, and close any compilation or integration defect they expose.
- **Remaining external gates:** independent semantic/security review, genuine multi-host authenticated transport qualification if federation crosses process/host boundaries, target-host/operator acceptance, canary, promotion and release.
