# memory.federation authenticated wire V1

This document specifies the transport-neutral authenticated cross-host candidate
implemented by `codex-rs/hepta-memory-federation-wire`. It does not activate a
network service and does not change the current SQLite-backed Agentd product
caller into a cross-host product.

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

## 1. Registered schema and message admission

The only admitted payload schema is
`hepta-memory-federation-authenticated-frame-v1`, registered through
`codex-hepta-wire` at wire version V2. Encoding is canonical, length-delimited
and versioned. It rejects unknown message tags, invalid booleans, trailing bytes,
invalid identities, empty or oversized frames and noncanonical enum values.

The schema carries four separate message classes:

- scoped query;
- terminal response with an authenticated owner-cut witness;
- cancellation request;
- cancellation acknowledgement with a typed disposition.

A cancellation acknowledgement proves only that the peer observed the request.
It never claims that an already completed external effect was undone.

## 2. Peer identity and credential lifecycle

Authentication uses directional 256-bit credentials. Each credential binds:

- sender peer;
- receiver peer;
- key identity;
- strictly positive generation;
- effective time and expiry;
- secret key bytes.

Enrollment, strict-generation rotation and revocation are explicit operations. A
frame is rejected when the exact directional credential is missing, not yet
effective, expired or revoked. A rotated generation revokes all older
generations for the same directional key identity.

`FederationWireHostV1` adds the transport identity seam. A selected mutually
authenticated transport must pass its independently authenticated peer identity
to `admit`; the host requires exact equality with the frame sender. The frame
MAC is not a substitute for endpoint routing, certificate validation, channel
confidentiality or secure key distribution.

The source host exposes credential enrollment, rotation and revocation methods,
but it does not persist secrets. A production host must bind those operations to
an independently reviewed secret store and operator recovery procedure.

## 3. Frame integrity and immutable verification result

Every frame uses an OS-generated 256-bit nonce and HMAC-SHA-256 over:

- protocol domain;
- sender and receiver;
- key identity and generation;
- issue and expiry times;
- nonce;
- canonical message digest.

Frame lifetime is capped at five minutes and may not exceed credential expiry.
The receiver validates shape, exact receiver, current directional credential,
MAC and replay admission before returning `VerifiedFederationFrameV1`.

`VerifiedFederationFrameV1` has private fields. External callers may inspect
sender, receiver, key, lifetime, nonce, message and digest only through read-only
accessors. They cannot construct a fake verified value or alter a verified
message afterward. Qualification runs compile-fail doctests for both attempted
struct construction and field mutation.

## 4. Replay resistance, time monotonicity and isolation

The live replay cache admits a nonce exactly once under the directional
credential. It removes only expired entries and fails closed rather than
evicting a live nonce when full.

Two additional invariants close overload and clock-rollback gaps:

- one directional credential has its own bounded partition and cannot consume the
  entire host-wide cache;
- the cache records the greatest host observation time and rejects any later
  call whose time regresses, even if the old replay entry was already removed as
  expired.

The durable host state maintains an independent restart-surviving replay key,
per-peer partition and time high-water mark. A frame is not exposed to a handler
until authenticated replay admission has been stored successfully.

The durable client uses the same staged-commit rule for inbound responses and
cancellation acknowledgements. Frame verification runs against a cloned live
replay cache, semantic correlation runs against cloned attempt/frontier state,
and the client installs those clones only after the recovery store atomically
accepts the new snapshot. A store failure therefore leaves the same authenticated
frame retryable in the same process as well as after restart; failed persistence
cannot poison the live replay cache.

## 5. Authenticated owner-cut witness

A response carries:

- owner peer;
- generation;
- monotone frontier;
- state digest;
- parent witness digest;
- observation time.

The witness is covered by the frame MAC. A successor must preserve owner,
not regress generation/frontier/clock and bind the exact predecessor digest.

The transport-neutral host requires the read handler to supply the witness. It
checks that the witness owner equals the local host and that observation time is
between query admission and terminal completion. The protocol does not
manufacture source truth from a row count. The selected owner store must define
how generation, state digest and parent relation derive from a durable committed
cut.

## 6. Two-stage read-only host and correlated client admission

`FederationWireHostV1` separates admission from completion:

1. decode the registered frame;
2. compare secure-channel peer identity with frame sender;
3. preflight durable replay capacity and host time;
4. verify receiver, credential, lifetime, MAC and live replay;
5. record verified replay state and persist it;
6. for a query, record and persist a pending attempt;
7. return an `AdmittedFederationQueryV1` token with private fields;
8. allow the caller to execute only the read-only owner handler;
9. validate the handler's result digests and owner-cut witness;
10. persist terminal state before response bytes are sealed and returned.

`FederationWireClientV1` provides the corresponding outbound and inbound half:

1. persist the exact outbound query attempt before returning query bytes;
2. persist cancellation intent before returning cancellation bytes;
3. bind the secure-channel peer identity to the authenticated response sender;
4. verify the response or acknowledgement against staged replay state;
5. correlate it with the exact durable peer/query/query-binding attempt;
6. validate owner-cut continuity or cancellation identity;
7. atomically persist recovery, attempt and frontier state;
8. install staged replay state only after persistence succeeds;
9. return an immutable verified frame to the read-only product adapter.

Failure to store replay or pending intent blocks the handler. Failure to persist
client correlation exposes neither a terminal result nor an acknowledgement and
leaves live state retryable. Neither host nor client owns a memory writer,
remote grant, blind retry queue, socket or provider invocation.

## 7. Cancellation and late-terminal fencing

Cancellation requests bind query identity, query digest, cancellation identity
and typed reason. A peer replies with one of:

- `observed_before_terminal`;
- `terminal_already_observed`;
- `unknown_attempt`.

Both request and acknowledgement are authenticated and replay-protected.
Cancellation is persisted before the acknowledgement is emitted. If
cancellation wins, later query completion returns `Cancelled` and no success
response can be produced. The durable snapshot preserves that fence across host
and client restart.

Repeated identical cancellation is idempotent and returns the first observation
time. A conflicting cancellation or conflicting terminal result fails closed.
Observation time cannot predate attempt start or regress behind the host
high-water mark.

## 8. Durable host and client recovery snapshots

`DurableFederationStateV1` serializes a canonical integrity-bound snapshot of:

- local host identity;
- configured global and per-peer capacities;
- host time high-water mark;
- live replay keys, peer partitions and expiries;
- live pending, cancelled and terminal attempts.

The client snapshot wraps that durable state together with outbound attempt
metadata and the last accepted authenticated frontier for each peer. Correlated
inbound state is replaced atomically through the same recovery-store seam.

Restore rejects:

- noncanonical JSON;
- digest mismatch;
- host or limit mismatch;
- malformed identities or state;
- duplicate or unsorted records;
- entries exceeding configured global/per-peer capacity;
- host time rollback.

Expired records are dropped at restore. Credential secrets, memory contents and
authority grants never enter the snapshot. `FederationRecoveryStoreV1` is the
host-owned persistence seam. The included in-memory implementation exists for
fault/restart tests only; a selected product host must supply a crash-safe,
permission-hardened backend.

## 9. Capacity and overload semantics

The wire candidate has explicit ceilings for frame size, frame lifetime, replay
entries, per-credential live replay entries, durable replay/attempt entries,
per-peer durable partitions and outbound peer bindings.

Capacity exhaustion is typed and fail-closed. One peer or key cannot displace
another peer's live safety records. The current implementations use bounded
retention scans and per-peer counts; deployment qualification must measure:

- cleanup cost under expiry churn;
- replay and attempt rejection rate;
- snapshot encoding and durable-store latency;
- restart recovery time;
- cancellation tail;
- overload/backpressure behavior.

A hard bound proves finite resource use, not an acceptable SLO.

## 10. Qualification boundary

Repository tests cover:

- canonical codec round trip and schema rejection;
- field tamper and wrong receiver;
- immutable verified-frame compile-fail contracts;
- duplicate replay;
- rotation and revocation during logical in-flight delivery;
- expired-entry cleanup followed by host-clock rollback;
- per-credential and per-peer capacity isolation;
- frontier owner, parent, rollback and clock checks;
- secure transport peer mismatch;
- durable replay across restart;
- cancellation acknowledgement;
- cancel-before-terminal fencing a late completion after restart;
- terminal-before-cancel and unknown attempt;
- recovery snapshot digest, identity, capacity and clock semantics;
- a complete logical two-host query/response path with a handler-supplied owner
  cut;
- client inbound recovery-store failure followed by successful retry both in the
  same process and after restart.

The exact-head and deterministic-current-base-merge lanes run the same format,
library test, doctest and strict Clippy commands. The execution guard pins source
and command manifests before and after the matrix. Qualification receipts bind
the canonical capability state and uploaded artifact digest.

The following remain external release gates:

- selected mutually authenticated transport and certificate/peer binding in the
  actual Agentd host;
- secure credential enrollment, storage, rotation, revocation and recovery;
- selected crash-safe recovery-store backend and migration/rollback procedure;
- two independently provisioned real hosts;
- partition, timeout, replay, rollback, clock-skew, revoke-during-I/O,
  cancellation, restart and overload tests over the selected network;
- measured latency, capacity, backpressure, recovery and cancellation tail;
- independent review, operator acceptance, canary, promotion and release.

Until those gates pass, the correct label is **authenticated cross-host
protocol/host source candidate**, not **production cross-host memory
federation**.
