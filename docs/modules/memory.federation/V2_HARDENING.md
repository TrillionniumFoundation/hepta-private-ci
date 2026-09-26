# memory.federation V2 hardening and product composition

**Module:** `memory.federation`<br>
**Canonical source:** `codex-rs/hepta-memory-federation`<br>
**Product caller:** `codex-rs/hepta-memory::CognitiveRuntime::AvailableFederatedV2`<br>
**Host composition:** `codex-rs/hepta-agentd`<br>
**Status:** candidate implementation; activation/release remain governed by qualification evidence.

This document records the security and product-composition contract introduced by the V2 hardening wave. It supplements `TECHNICAL.md`; it does not grant deployment, promotion or release authority.

## 1. Remote response integrity

`RemoteFederatedResponseV2` carries `query_binding_digest` and a domain-separated `response_digest`.

The response digest is recomputed by the V2 engine from the canonical response fields before any item can become eligible:

- peer identity;
- exact query binding;
- scope digest;
- purpose digest;
- generation-vector digest;
- observed frontier;
- response expiry;
- ordered evidence items, including owner, record identity/revision, record/support/validity digests. Item order is semantic because bounded selection keeps the leading `maximum_results` items; a permutation must therefore change the response digest;
- completeness;
- terminal-observation bit.

A caller-supplied non-zero digest is insufficient. Any field drift after sealing returns `DigestMismatch("response")`. A response sealed for another query returns `DigestMismatch("response_query_binding")` even when peer/scope/purpose happen to match.

## 2. Authority lifetime ceiling

A successful result cannot extend the authority that admitted the read.

The effective result expiry is:

```text
min(remote_response_expiry, capability_lease_expiry, query_deadline, live_authority_expiry)
```

Post-I/O authority observation must also occur before each of those horizons. A response that finishes after the query deadline, capability expiry or remote response expiry is rejected rather than cached under a longer remote TTL.

## 3. Preflight and post-I/O authority revalidation

`execute_once` accepts a `FederationAuthorityV2` observer and uses it twice. Before transport dispatch, the engine requires a fresh authority observation bound to the exact query binding and lease epoch. Only `Current` may reach the transport; `Revoked` or `StaleGeneration` fails closed before any remote I/O is invoked.

After transport returns a terminal response and before evidence is admitted, the engine obtains a second fresh authority observation bound to:

- exact query binding;
- lease epoch;
- observation time;
- current authority state.

States are `Current`, `Revoked` and `StaleGeneration`. Every observation also carries the live authority expiry. A `Current` observation is invalid if already expired, and the engine rejects any lease whose expiry exceeds the live authority horizon. The post-I/O observation time may not regress behind the preflight observation.

A post-I/O `Revoked` or `StaleGeneration` state remains terminally observable for provenance, but all remote evidence items are suppressed. The final result expiry is additionally capped by the post-I/O live authority expiry. The authority-observation digest binds that expiry and the state, so downstream code cannot replace the final live horizon without invalidating the result.

## 4. Interruptible single-attempt transport

`FederationTransportV2::send_once` returns a `Send` future. `execute_once` races the preflight authority observation, transport, and post-I/O authority revalidation against `FederationAttemptControlV2`.

The product-host contract is:

- one transport attempt per query nonce;
- no engine-owned retry queue;
- a dropped transport future is the cancellation boundary and must stop further adapter I/O;
- transport may not start until preflight live authority is `Current`;
- the in-flight product stop horizon is `min(query_deadline, capability_lease_expiry)`;
- deadline/cancellation wins before a pending transport or authority future can complete;
- a retry, if ever authorized by an outer policy, requires a new nonce/attempt identity.

This removes the old synchronous trait limitation where a blocked `send_once` could outlive the engine deadline, and prevents an earlier lease expiry from being treated as a later query deadline.

## 5. Product caller composition

Production Agentd composition uses `CognitiveRuntime::AvailableFederatedV2`. The runtime stores the consumer Agent identity and bounded owner-layout candidates, not an inherited credential or writable peer handle.

For each physical federated recall:

1. concurrently rediscover currently active capabilities from the bounded owner-candidate set;
2. deterministically sort/deduplicate and cap admitted sources at the existing federation source limit, while recording peer truncation and owner-candidate omission;
3. build a query and lease bound to consumer, peer, scope, purpose, capability generation/revision, query digest, nonce and deadline;
4. perform canonical live-authority preflight and require `Current` before dispatch;
5. execute the owner read through `FederationTransportV2`, interruptible at `min(query_deadline, lease_expiry)`;
6. seal and verify the remote response digest;
7. rediscover the current owner capability after I/O;
8. admit evidence only if the final live authority observation is current;
9. deterministically aggregate requested/completed/failed peers, peer truncation, owner-candidate omission, item truncation and typed discovery/deadline-authority/integrity/transport failure counts;
10. batch-revalidate the prepared attachment at physical model-request assembly: bindings from the same owner/capability share one SQLite read snapshot, the whole batch shares one bounded product deadline, and different owners remain independent federation snapshots; after the batch completes, read the wall clock again and reject if any capability crossed its expiry or the clock regressed; timeout, stale generation, revocation, expiry crossing or owner unavailability drops the federated proposal fail-closed. This fence is evaluated after provider-attempt admission and before transport entry; under the repository-wide dispatch contract it does not claim retroactive cancellation authority over an already admitted effect.

The product adapter is read-only. It does not enroll peers, mint capability grants, mutate remote memory, inherit owner credentials or retry unknown operations. Admitted peer attempts are polled concurrently under the same total deadline; completion order never controls result ordering.

## 6. Legacy compatibility boundary

`CognitiveRuntime::AvailableFederated` and `FederatedRecallSet` remain available for compatibility-focused tests and callers. Agentd product composition is migrated to `AvailableFederatedV2`.

This distinction is enforced in source, not only by convention: product model-input registration requires `CognitiveRuntime::has_product_federation()`, and the extension calls `retrieve_product_federated` / `revalidate_product_federated`. Those APIs reject `AvailableFederated`; the legacy variant remains reachable only through explicit compatibility surfaces and therefore cannot silently stand in for the canonical module contract. In addition, the compatibility `with_federation()` helper preserves an already-composed `AvailableFederatedV2` runtime instead of downgrading it to the legacy variant.

## 7. Coverage semantics

Product aggregation preserves bounded structured coverage:

```text
requested_peers
completed_peers
failed_peers
truncated_peers
omitted_peer_candidates
truncated_items
failures.discovery_unavailable
failures.deadline_or_cancelled
failures.authority_rejected
failures.integrity_rejected
failures.transport_unavailable
```

A failed peer is not converted into a successful empty result. `Partial + []` also remains `Partial`; an incomplete peer response with zero returned items must not be relabeled as a valid empty result. Peer-cap truncation and pre-discovery owner-candidate omission are reported separately from failures. Typed failure counts remain bound into the canonical result digest where a result exists and into the prepared product attachment/source binding at aggregation. Partial coverage remains visible in the combined local+federated model-input payload.

A successfully observed owner layout with no active grant remains only an enrollment candidate and does not consume a requested-peer slot. An active grant is enrolled only when its consumer-workspace digest exactly matches the requesting `FederationConsumerAccess`; a grant for another workspace never becomes a queried peer and no transport attempt is made. If the owner capability store cannot be observed at all, enrollment status is indeterminate rather than equivalent to "no grant": the product caller reserves a bounded failed slot from the same <=16 peer budget. Likewise, a terminal transport whose post-I/O authority becomes revoked or generation-stale contributes failed aggregate coverage even though the transport itself completed.

## 8. Verification matrix

The focused V2 suite includes adversarial cases for:

- response-field tampering after digest sealing;
- item-order permutation changing the bounded selected subset;
- `Partial + []` preservation rather than relabeling as `Empty`;
- self-consistent result digests with contradictory completeness/items/truncation state;
- cross-query response replay;
- result expiry capped by response/lease/query/live-authority horizons;
- forged or widened lease expiry rejected against live authority;
- expired `Current` authority observations rejected;
- preflight revocation blocking transport dispatch entirely;
- revocation observed after transport;
- generation drift observed after transport;
- deadline interrupting a pending transport;
- cancellation interrupting a pending transport;
- authority/lease horizon enforcement before and after I/O;
- non-terminal transport remaining indeterminate;
- stale response generation suppressing items;
- peer/lease drift;
- duplicate remote record identity;
- result digest binding the post-I/O authority observation;
- owner capability discovery failure remaining explicit bounded failed coverage;
- wrong-workspace grants never entering queried coverage or transport dispatch;
- revoked/stale terminal attempts contributing failed aggregate coverage;
- combined local+federated model input preserving the federation coverage vector;
- bounded fail-closed physical-send revalidation, including same-owner/capability batch coherence under one SQLite snapshot, one total final-use deadline, and a fresh post-batch clock check that rejects expiry crossing or clock regression before provider transport entry;
- concurrent bounded peer orchestration under one global horizon with deterministic post-aggregation ordering;
- peer truncation, owner-candidate omission and typed failure coverage propagation into the final attachment;
- legacy compatibility composition cannot downgrade an already-composed V2 product runtime;
- cancellation receipts carrying no success assumption;
- exact-scope owner memory frontier acquired from the same SQLite snapshot, including legitimate empty frontier zero.

Required product qualification additionally includes Agentd composition, owner capability grant/revoke behavior, extension attachment coverage binding, exact-head tests, merge-candidate tests and target-host execution evidence.

## 9. Frontier semantics and remaining external gates

The in-process product adapter acquires `observed_frontier` from the **same SQLite read snapshot** that produces the candidate set. In the current local adapter this value is the exact-scope count of immutable `memory_revisions` rows. Because those rows are append-only under the owner schema, the count is a bounded local monotone observation and correctly permits `0` for an actually empty scope; a non-empty response may not fabricate a zero frontier. It is **not** an exact equality cut digest, an independently retained rollback witness, or remote-host authentication. Capability generation/revision remains independently bound through the query/lease and live authority observations.

For cross-process or multi-host federation, transport qualification must carry and authenticate a canonical owner cut witness (for example the existing Lane-C cut-digest semantics or an explicitly registered successor) together with remote peer identity. The local revision count must not be promoted into that role.

This hardening wave does not by itself establish:

- independent semantic/security acceptance;
- multi-host network federation, authenticated remote credential exchange, or a coherent remote data-frontier protocol;
- deployment canary or operator acceptance;
- promotion/release authority.

Those remain separate gates in the module qualification framework.

### Target-host profile and degradation contract

The V2 product runtime binds a validated target-host profile into runtime
identity. Owner discovery, peer attempts, and final revalidation have separate
bounded concurrency. Retrieval may degrade per failed peer with explicit
coverage, while provider dispatch remains all-current for the exact selected
binding set. `partial_peers` records unproven peer completeness separately from
known `truncated_items`. Reaching the top-K ceiling is conservatively partial,
not an assertion that no additional matching evidence exists.

V1 compatibility is feature-gated behind `legacy-v1` and is absent from the
default product dependency surface.
