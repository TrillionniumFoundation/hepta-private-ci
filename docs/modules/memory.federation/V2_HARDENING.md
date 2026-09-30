# memory.federation V2 hardening and product composition

**Module:** `memory.federation`  
**Canonical source:** `codex-rs/hepta-memory-federation`  
**Product caller:** `codex-rs/hepta-memory::CognitiveRuntime::AvailableFederatedV2`  
**Host composition:** `codex-rs/hepta-agentd`  
**Status source:** `CAPABILITY_STATE.json`

This document records the security and product-composition contract introduced
by the V2 hardening waves. It supplements `TECHNICAL.md`; it does not grant
deployment, promotion or release authority.

<!-- BEGIN GENERATED MEMORY FEDERATION STATUS -->
## Generated capability status

This block is generated from `CAPABILITY_STATE.json`. It separates source,
execution, independent acceptance, activation, promotion, and release; prose
outside this block cannot widen those claims.

| Capability or gate | Canonical state |
| --- | --- |
| In-process V2 engine | `source_hardened_candidate_pending_execution` |
| Agentd product caller | `composed_candidate_pending_execution` |
| Discovery/read budgeting | `half_budget_reserved_for_admitted_reads` |
| Authenticated wire | `source_hardened_protocol_candidate_pending_execution` |
| Verified-frame boundary | `private_fields_read_only_accessors` |
| Replay admission | `bounded_fail_closed_monotonic_clock_per_credential_partition` |
| Cross-host product transport | `transport_neutral_host_boundary_source_candidate_not_agentd_composed` |
| Durable attempt/replay recovery | `host_store_snapshot_source_candidate_pending_selected_backend` |
| Exact-head execution | `pending_current_head_qualification` |
| Deterministic merge execution | `pending_current_base_merge_qualification` |
| Product execution proved | `false` |
| Independent acceptance | `false` |
| Activation | `false` |
| Promotion | `false` |
| Release | `false` |

<!-- END GENERATED MEMORY FEDERATION STATUS -->

## 1. Remote response integrity

`RemoteFederatedResponseV2` carries an exact `query_binding_digest` and a
domain-separated `response_digest`. The V2 engine recomputes the response digest
before any item is eligible. The digest binds:

- peer identity;
- exact query binding;
- scope and purpose;
- generation-vector digest;
- observed frontier;
- response expiry;
- ordered evidence items, including owner, record identity/revision and
  record/support/validity digests;
- completeness;
- terminal-observation bit.

Item order is semantic because bounded selection retains the leading
`maximum_results` items. A permutation must change the response digest. A
caller-supplied nonzero digest is never treated as proof. A response sealed for a
different query is rejected even when peer, scope and purpose happen to match.

## 2. Authority lifetime ceiling

The effective successful-result expiry is:

```text
min(remote_response_expiry,
    capability_lease_expiry,
    query_deadline,
    live_authority_expiry)
```

Preflight and post-I/O observations must occur before all applicable horizons. A
response completing after the query, lease or response expiry is rejected rather
than cached under a longer remote TTL. A caller-provided lease wider than the
observed live authority is rejected before transport dispatch.

## 3. Preflight and post-I/O authority revalidation

`execute_once` calls `FederationAuthorityV2` twice. Before transport dispatch it
requires a fresh observation bound to exact query and lease epoch. Only
`Current` may dispatch; `Revoked`, `StaleGeneration`, an expired current
observation or a widened lease fails closed.

After a terminal response and before evidence admission, it obtains another
fresh observation. Observation time may not regress. Post-I/O revoke or
generation drift remains terminally observable for provenance, but all remote
items are suppressed. The final authority-observation digest binds state and
live expiry, preventing downstream replacement of the final horizon.

## 4. Interruptible single-attempt transport

`FederationTransportV2::send_once` returns a future. The engine races preflight,
transport and post-I/O authority work against `FederationAttemptControlV2`.

The product contract is:

- one transport attempt per query nonce;
- no engine-owned retry queue;
- a dropped transport future is the in-process cancellation boundary;
- transport cannot start until live authority is current;
- the stop horizon is the earlier of query deadline and lease expiry;
- deadline/cancellation wins before pending transport or authority completion;
- any separately authorized retry requires a new nonce and attempt identity.

This prevents a blocked synchronous operation from outliving the engine deadline
and prevents a short lease from being widened to the query deadline.

## 5. Product caller composition

Agentd composes `CognitiveRuntime::AvailableFederatedV2`. The runtime stores the
consumer Agent identity, bounded owner-layout candidates and a validated
`MemoryFederationHostProfile`; it stores neither a writable peer handle nor an
inherited remote credential.

For each physical recall:

1. start bounded concurrent capability discovery from a deterministic owner set;
2. stop discovery after at most one half of the total product budget;
3. preserve completed discoveries and represent unfinished owners as typed failed
   discovery slots;
4. deterministically sort/deduplicate and cap admitted sources, recording peer
   truncation and pre-discovery owner omission;
5. reserve the remaining global budget for admitted reads and authority fences;
6. apply the capability's exact owner scope inside the owner SQLite snapshot
   before FTS/recency ranking and graph expansion, then derive `Complete` or
   `Empty` only from explicit same-snapshot channel exhaustion;
7. build query and lease bindings over consumer, peer, scope, purpose,
   capability generation/revision, query digest, nonce and deadline;
8. require current preflight authority before dispatch;
9. execute one interruptible owner read;
10. seal and recompute the response digest;
11. rediscover current owner capability after I/O and timestamp the authority
    observation only after that asynchronous owner-store read completes;
12. admit evidence only if final authority is current;
13. convert capability-local setup failures into typed failed-peer coverage
    without discarding other valid peers;
14. deterministically aggregate candidates and structured coverage;
15. batch-revalidate exact owner/capability/memory bindings at physical
    model-request assembly under one bounded final-use deadline;
16. take a fresh post-batch wall-clock observation and reject clock regression,
    capability expiry, or any selected memory crossing its own validity window
    before provider transport entry.

The discovery/read split closes the starvation case in which a fast owner was
successfully discovered but a second permanently pending owner consumed the
entire global horizon before any read started. It does not let completion order
choose peers and it does not extend the original total budget.

The product adapter remains read-only. It does not enroll peers, mint grants,
mutate remote memory, inherit owner credentials or blindly retry unknown
operations.

## 6. Legacy compatibility boundary

`CognitiveRuntime::AvailableFederated` and `FederatedRecallSet` remain available
only to explicit compatibility callers and tests. Agentd product composition uses
`AvailableFederatedV2`.

Product model-input registration requires `has_product_federation()`, and the
Memory extension calls `retrieve_product_federated` and
`revalidate_product_federated`. Those APIs reject the legacy runtime. The
compatibility `with_federation()` helper preserves an already composed V2 runtime
rather than downgrading it. The V1 crate surface is absent by default and is
available only with the explicit `legacy-v1` feature.

## 7. Coverage and completeness semantics

Product aggregation preserves:

```text
requested_peers
completed_peers
failed_peers
partial_peers
truncated_peers
omitted_peer_candidates
truncated_items
failures.discovery_unavailable
failures.deadline_or_cancelled
failures.authority_rejected
failures.integrity_rejected
failures.transport_unavailable
```

A failed peer is not a successful empty result. `Partial + []` remains partial.
Peer-cap truncation and owner-candidate omission are distinct from failure.
Typed failure counts bind into the result or final prepared attachment.

A successfully observed owner with no active matching grant is not enrolled and
does not consume a requested-peer slot. A grant for another workspace never
forms a query. An unobservable capability store is indeterminate and consumes a
bounded failed slot. A post-I/O revoke/stale terminal contributes failed
aggregate coverage even when the transport completed.

A nonempty owner result below the retrieval ceiling can be complete. Reaching
the top-K ceiling is conservatively partial unless an authenticated
`has_more=false`-equivalent witness exists. Post-merge item truncation is reported
separately.

## 8. Frontier semantics

The in-process product adapter obtains `observed_frontier` from the same SQLite
read snapshot that produces candidates. In the current local implementation it
is the exact-scope count of append-only `memory_revisions` rows. Zero is valid for
an actually empty scope; nonempty evidence may not fabricate zero.

This count is a local monotone observation, not an equality cut digest,
independently retained rollback witness or remote authentication. Capability
generation/revision is bound independently through query, lease and authority
observations.

The authenticated cross-host candidate instead carries owner peer, generation,
monotone frontier, state digest, parent witness digest and observation time. The
transport-neutral host requires the read handler to provide this owner-cut
witness and checks exact owner and admitted time bounds before completing the
response. The selected remote store must still define how the state digest and
generation derive from a durable committed cut.

## 9. Cross-host host boundary without activation

`codex-hepta-memory-federation-wire` now includes a two-stage source candidate:

- the secure transport adapter supplies its authenticated peer identity;
- `FederationWireHostV1::admit` requires identity equality with the frame sender;
- verified replay admission is written to the injected recovery store before a
  query can be exposed;
- a pending attempt intent is persisted before the read-only handler runs;
- an admitted query token has private fields and cannot be forged externally;
- cancellation is persisted before its authenticated acknowledgement;
- terminal state is persisted before response bytes can be emitted;
- cancellation before terminal fences a late completion even after restart;
- the host seals responses only with an explicitly bound reverse directional
  credential;
- result and owner-cut witness come from the read handler, not from transport
  metadata or a row count invented by the protocol.

This is not Agentd network composition. The crate opens no socket and selects no
TLS implementation, certificate authority, secret store or production recovery
backend. Those remain explicit external gates.

## 10. Replay, verified-frame and recovery hardening

`VerifiedFederationFrameV1` has private fields and read-only accessors. External
callers cannot use a struct literal or mutate identity, message, key, nonce or
lifetime after verification. Compile-fail doctests are executed by the module
qualification lane.

The live replay cache:

- is globally bounded;
- partitions capacity per directional credential;
- removes only expired entries;
- fails closed when global or partition capacity is full;
- remembers the greatest observed host time;
- rejects a later admission whose time regresses, even if an old nonce was
  already purged as expired.

The durable host recovery snapshot separately binds local host identity,
configured global/per-peer limits, replay keys, attempt state and a monotonic
time high-water mark under an integrity digest. Restore rejects noncanonical
encoding, digest drift, identity/limit mismatch, duplicates, capacity violations
and clock rollback. Credential secrets are deliberately absent and remain the
selected secret store's responsibility.

## 11. Verification matrix

Focused V2 and product tests include:

- response-field tampering and cross-query replay;
- item-order permutation changing the bounded prefix;
- `Partial + []` preservation;
- result digests with contradictory completeness/items/truncation;
- response/lease/query/live-authority expiry ceilings;
- forged or widened lease expiry;
- preflight revoke blocking dispatch;
- post-I/O revoke and generation drift;
- pending transport deadline and cancellation;
- duplicate remote record identity;
- owner discovery failure as explicit bounded coverage;
- wrong-workspace grant exclusion;
- final physical-send revalidation, expiry crossing and clock regression;
- bounded concurrent orchestration with deterministic final order;
- fast completed discovery plus a permanently pending owner while read budget
  remains available;
- peer truncation, owner omission and typed failure propagation;
- exact-scope same-snapshot local frontier;
- legacy composition non-downgrade;
- private verified-frame compile-fail contracts;
- replay after expiry cleanup plus clock rollback;
- per-credential/per-peer capacity isolation;
- transport identity mismatch;
- durable replay across restart;
- cancel-before-terminal fencing late completion after restart;
- owner-cut witness owner/time validation.

Qualification runs the same matrix on the exact head and deterministic merge
against the then-current base. The execution guard compares SHA, tree, complete
qualified source manifest and command manifest before and after all commands.
Capability state is copied and hashed into the receipt. A generated wire lockfile
is retained when available; it must be promoted to tracked locked input before a
locked production qualification claim.

## 12. Remaining external gates

This hardening does not establish:

- a selected mutually authenticated network transport;
- certificate-to-frame peer identity operations in Agentd;
- production credential enrollment/storage/rotation/recovery;
- a selected crash-safe recovery-store backend;
- two independently provisioned real-host fault qualification;
- target-host latency, capacity, backpressure, replay pressure or cancellation
  tail evidence;
- independent semantic/security acceptance;
- operator acceptance, canary, promotion or release.

Until those gates pass, the accurate labels remain **in-process read-only product
candidate** and **authenticated cross-host protocol/host source candidate**.
