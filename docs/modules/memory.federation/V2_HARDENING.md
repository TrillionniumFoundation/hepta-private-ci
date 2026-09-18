# memory.federation V2 hardening and product composition

**Module:** `memory.federation`  
**Canonical source:** `codex-rs/hepta-memory-federation`  
**Product caller:** `codex-rs/hepta-memory::CognitiveRuntime::AvailableFederatedV2`  
**Host composition:** `codex-rs/hepta-agentd`  
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
- canonicalized evidence items, including owner, record identity/revision, record/support/validity digests;
- completeness;
- terminal-observation bit.

A caller-supplied non-zero digest is insufficient. Any field drift after sealing returns `DigestMismatch("response")`. A response sealed for another query returns `DigestMismatch("response_query_binding")` even when peer/scope/purpose happen to match.

## 2. Authority lifetime ceiling

A successful result cannot extend the authority that admitted the read.

The effective result expiry is:

```text
min(remote_response_expiry, capability_lease_expiry, query_deadline)
```

Post-I/O authority observation must also occur before each of those horizons. A response that finishes after the query deadline, capability expiry or remote response expiry is rejected rather than cached under a longer remote TTL.

## 3. Preflight and post-I/O authority revalidation

`execute_once` accepts a `FederationAuthorityV2` observer and uses it twice. Before transport dispatch, the engine requires a fresh authority observation bound to the exact query binding and lease epoch. Only `Current` may reach the transport; `Revoked` or `StaleGeneration` fails closed before any remote I/O is invoked.

After transport returns a terminal response and before evidence is admitted, the engine obtains a second fresh authority observation bound to:

- exact query binding;
- lease epoch;
- observation time;
- current authority state.

States are `Current`, `Revoked` and `StaleGeneration`. The post-I/O observation time may not regress behind the preflight observation.

A post-I/O `Revoked` or `StaleGeneration` state remains terminally observable for provenance, but all remote evidence items are suppressed. The result digest binds the post-I/O authority-observation digest so downstream code cannot replace the final live observation without invalidating the result.

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

1. rediscover currently active capabilities from owner stores;
2. cap enrolled sources at the existing federation source limit;
3. build a query and lease bound to consumer, peer, scope, purpose, capability generation/revision, query digest, nonce and deadline;
4. perform canonical live-authority preflight and require `Current` before dispatch;
5. execute the owner read through `FederationTransportV2`, interruptible at `min(query_deadline, lease_expiry)`;
6. seal and verify the remote response digest;
7. rediscover the current owner capability after I/O;
8. admit evidence only if the final live authority observation is current;
9. aggregate explicit requested/completed/failed/truncated coverage;
10. revalidate each attached memory again at physical model-request assembly under the same bounded product read horizon; timeout or owner unavailability drops the federated proposal fail-closed.

The product adapter is read-only. It does not enroll peers, mint capability grants, mutate remote memory, inherit owner credentials or retry unknown operations.

## 6. Legacy compatibility boundary

`CognitiveRuntime::AvailableFederated` and `FederatedRecallSet` remain available for compatibility-focused tests and callers. Agentd product composition is migrated to `AvailableFederatedV2`.

This distinction is deliberate: legacy APIs are not allowed to silently stand in for the canonical module contract. Product model-input federation is registered from `CognitiveRuntime`; when the V2 variant is active, retrieval and final attachment revalidation use the canonical path.

## 7. Coverage semantics

Product aggregation preserves four counters:

```text
requested_peers
completed_peers
failed_peers
truncated_items
```

A failed peer is not converted into a successful empty result. Partial coverage remains visible in the prepared federated attachment, in the combined local+federated model-input payload, and in the source-binding digest supplied to the model-input proposal.

A successfully observed owner layout with no active grant remains only an enrollment candidate and does not consume a requested-peer slot. An active grant is enrolled only when its consumer-workspace digest exactly matches the requesting `FederationConsumerAccess`; a grant for another workspace never becomes a queried peer and no transport attempt is made. If the owner capability store cannot be observed at all, enrollment status is indeterminate rather than equivalent to "no grant": the product caller reserves a bounded failed slot from the same <=16 peer budget. Likewise, a terminal transport whose post-I/O authority becomes revoked or generation-stale contributes failed aggregate coverage even though the transport itself completed.

## 8. Verification matrix

The focused V2 suite includes adversarial cases for:

- response-field tampering after digest sealing;
- self-consistent result digests with contradictory completeness/items/truncation state;
- cross-query response replay;
- result expiry capped by lease/query horizon;
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
- bounded fail-closed physical-send revalidation;
- cancellation receipts carrying no success assumption.

Required product qualification additionally includes Agentd composition, owner capability grant/revoke behavior, extension attachment coverage binding, exact-head tests, merge-candidate tests and target-host execution evidence.

## 9. Frontier semantics and remaining external gates

The current in-process product adapter sets `RemoteFederatedResponseV2.observed_frontier` from the durable capability revision observed for that owner/capability. This is a non-zero monotone capability observation used for provenance; it is **not** a claim that one coherent remote memory-ledger snapshot frontier was acquired. Admissible items remain bound independently by exact owner, record identity/revision, content/support/validity digests, capability generation/revision, preflight/post-I/O authority observation, and final physical-send memory revalidation.

A future multi-process or multi-host transport that needs a coherent remote data cut must carry and authenticate the real owner data frontier/snapshot witness rather than reinterpret the capability revision as that frontier.

This hardening wave does not by itself establish:

- independent semantic/security acceptance;
- multi-host network federation, authenticated remote credential exchange, or a coherent remote data-frontier protocol;
- deployment canary or operator acceptance;
- promotion/release authority.

Those remain separate gates in the module qualification framework.
