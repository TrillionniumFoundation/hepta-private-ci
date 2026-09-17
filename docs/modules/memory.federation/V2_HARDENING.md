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

## 3. Post-I/O authority revalidation

`execute_once` accepts a `FederationAuthorityV2` observer. After transport returns a terminal response and before evidence is admitted, the engine obtains a fresh authority observation bound to:

- exact query binding;
- lease epoch;
- observation time;
- current authority state.

States are `Current`, `Revoked` and `StaleGeneration`.

`Revoked` and `StaleGeneration` remain terminally observable results for provenance, but their remote evidence items are suppressed. The result digest binds the authority-observation digest so downstream code cannot replace the post-I/O observation without invalidating the result.

## 4. Interruptible single-attempt transport

`FederationTransportV2::send_once` now returns a `Send` future. `execute_once` races both transport and post-I/O authority revalidation against `FederationAttemptControlV2`.

The product-host contract is:

- one transport attempt per query nonce;
- no engine-owned retry queue;
- a dropped transport future is the cancellation boundary and must stop further adapter I/O;
- deadline/cancellation wins before a pending transport or authority future can complete;
- a retry, if ever authorized by an outer policy, requires a new nonce/attempt identity.

This removes the old synchronous trait limitation where a blocked `send_once` could outlive the engine deadline.

## 5. Product caller composition

Production Agentd composition uses `CognitiveRuntime::AvailableFederatedV2`. The runtime stores the consumer Agent identity and bounded owner-layout candidates, not an inherited credential or writable peer handle.

For each physical federated recall:

1. rediscover currently active capabilities from owner stores;
2. cap enrolled sources at the existing federation source limit;
3. build a query and lease bound to consumer, peer, scope, purpose, capability generation/revision, query digest, nonce and deadline;
4. execute the owner read through `FederationTransportV2`;
5. seal and verify the remote response digest;
6. rediscover the current owner capability after I/O;
7. admit evidence only if post-I/O authority is current;
8. aggregate explicit requested/completed/failed/truncated coverage;
9. revalidate each attached memory again at physical model-request assembly.

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

A failed peer is not converted into a successful empty result. Partial coverage remains visible in the prepared federated attachment and is bound into the source-binding digest supplied to the model-input proposal.

Discovery only turns a source into a requested peer after an active capability has been observed. Owner layouts without an active grant are enrollment candidates, not failed requests.

## 8. Verification matrix

The focused V2 suite includes adversarial cases for:

- response-field tampering after digest sealing;
- cross-query response replay;
- result expiry capped by lease/query horizon;
- revocation observed after transport;
- generation drift observed after transport;
- deadline interrupting a pending transport;
- cancellation interrupting a pending transport;
- authority observation after lease expiry;
- non-terminal transport remaining indeterminate;
- stale response generation suppressing items;
- peer/lease drift;
- duplicate remote record identity;
- result digest binding the post-I/O authority observation;
- cancellation receipts carrying no success assumption.

Required product qualification additionally includes Agentd composition, owner capability grant/revoke behavior, extension attachment coverage binding, exact-head tests, merge-candidate tests and target-host execution evidence.

## 9. Remaining external gates

This hardening wave does not by itself establish:

- independent semantic/security acceptance;
- multi-host network federation or a remote credential exchange protocol;
- deployment canary or operator acceptance;
- promotion/release authority.

Those remain separate gates in the module qualification framework.
