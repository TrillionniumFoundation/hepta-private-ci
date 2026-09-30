# memory.federation technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `memory.federation`  
**Owner:** `cognitive-platform`  
**Deputy:** `security-authority`  
**Lifecycle:** `target`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `MEM-3-FEDERATION`

This stable document is the implementation and operating guide for
`memory.federation`. Normative identity, ownership, contract, data-authority and
delivery facts remain in the canonical JSON registries. The generated block
below is the only capability-status projection; detailed prose explains the
semantics but cannot turn source presence into execution, acceptance, activation
or release.

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

## 1. Identity, mission and ownership

The module reads remote or separately owned cognitive evidence under scoped,
current grants. It must not perform blind retry, remote mutation, credential
minting, grant issuance, training-consent inference or database merging.

The primary owner `cognitive-platform` controls the declared implementation root
and is accountable for compatibility, bounded behavior, evidence and rollback.
The deputy `security-authority` independently reviews public contracts,
authority checks, wire authentication, persistence, cancellation, migrations,
resource limits and activation behavior. Cross-owner changes require an explicit
co-owner or a separate integration package.

Plane `adapter`, kind `service`, state model `read_only_remote` and architecture
role `checked_adapter` define placement. A façade may sequence owners but may not
absorb their durable facts or claim global optimality.

## 2. Source binding and implementation status

Declared exclusive target root:

- `codex-rs/hepta-memory-federation`

The registered target root exists. The hardened one-peer V2 surface lives in
`src/v2.rs`; compatibility V1 is behind the explicit `legacy-v1` feature. The
current in-process product composition is
`codex-hepta-memory::CognitiveRuntime::AvailableFederatedV2`, assembled by
Agentd and consumed by the Memory extension through V2-only product methods.

The separately qualified cross-host candidate lives in:

- `codex-rs/hepta-memory-federation-wire`

That second crate is a protocol and host-integration candidate, not a transfer
of module ownership, an Agentd network caller or an activated service. Its
presence is tracked by `WIRE_IMPLEMENTATION_MAP.json` and by the exact source
manifest in the module qualification receipt.

`existing_bound` means that declared source exists. It does not mean that the
current head compiled, that a product call succeeded, that a real transport was
selected, or that an operator accepted or released the capability. Source moves
must update `MODULES.json`, `SOURCE_BINDINGS.json`, implementation maps and this
guide together.

## 3. Boundary, responsibilities and non-goals

Architectural consumed ports:

- `cognitive.read`
- `kernel.authority`

The canonical in-process crate depends only on `codex-hepta-types`; product
composition is caller-side in `codex-hepta-memory`, `codex-hepta-agentd` and
`codex-hepta-memory-extension`. Those callers do not become alternate contract
owners.

Authoritative write domains: none.

Explicitly denied capabilities:

- `write_authority`
- `blind_retry`

The module accepts bounded typed inputs and fails closed on missing authority,
stale generations, scope or purpose mismatch, response-digest drift, replay,
clock regression and deadline/cancellation boundaries. Future mutation remains
outside this module and must use the owning system's durable intent, outbox and
reconciliation protocol.

Non-goals include becoming a general state store, bypassing the Codex execution
spine, interpreting model prose as authority, enrolling peers from untrusted
payloads, treating a MAC as certificate validation, using federation reads as
training consent, or converting qualification evidence into deployment
authority.

## 4. Internal architecture and component decomposition

### 4.1 In-process V2 checked adapter

The one-peer engine consists of:

- `FederatedQueryV2` and `FederatedLeaseV2`, binding peer, principal, scope,
  purpose, generation, nonce, deadline and authority horizon;
- `FederationAuthorityV2`, observed before dispatch and after I/O;
- `FederationTransportV2`, one asynchronous interruptible attempt;
- `RemoteFederatedResponseV2`, whose domain-separated digest is recomputed over
  all security-relevant fields and ordered evidence items;
- `FederationAttemptControlV2`, racing authority/transport against the earlier of
  query deadline and lease expiry;
- `FederatedResultV2`, a deny-all provenance-bearing result with explicit
  completeness, validity, coverage and effective expiry;
- the product adapter in `CognitiveRuntime::AvailableFederatedV2`, which performs
  bounded discovery, current-grant enrollment, canonical one-peer execution and
  deterministic aggregation;
- the Memory-extension physical-send revalidator, which checks the exact
  prepared binding set immediately before provider transport entry.

### 4.2 Product orchestration and budget isolation

The product caller stores only a consumer identity, bounded owner-layout
candidates and a validated host profile. It does not retain writable peer
handles or inherited credentials.

Owner discovery uses bounded `buffer_unordered` concurrency and is limited to
one half of the total operation budget. Every discovery completed before that
phase deadline is retained; unfinished owners become typed discovery failures.
The other half of the total budget is reserved for the already discovered,
deterministically sorted/deduplicated peers and their preflight, read and
post-I/O authority checks. This closes the prior phase-barrier counterexample in
which one permanently pending owner consumed the entire request and made a fast,
valid owner fail before its read began.

The split does not let completion order select peers. Candidate ordering,
deduplication and the admitted-peer cap remain deterministic. All admitted
attempts then run with bounded `buffer_unordered` concurrency under the original
single global horizon; the split narrows discovery rather than extending the
request.

For an admitted capability, the owner scope is part of retrieval selection, not
a post-processing filter. Memory FTS, entity/projection FTS and recency queries
apply the exact capability scope inside the same SQLite read transaction before
channel ranking, reciprocal-rank fusion and the final top-K. Graph and typed
relation expansion inherit only seeds from that exact projection scope. This
prevents higher-ranked memories from another authorized local scope from
crowding the federated scope out before selection.

Completeness is also owner-observed rather than inferred from response length.
Each retrieval channel reports whether its bounded query was exhausted in the
same owner snapshot. The owner resolves the bounded fused candidate set before
the product top-K and reports exhaustion only when every channel is exhausted
and no candidate lies beyond the product result ceiling. `Complete` and
`Empty` therefore require this same-snapshot exhaustion witness; otherwise the
response is `Partial`, even when fewer than K items are returned.

A capability-local query/lease construction failure is recorded as a failed peer
with integrity coverage and does not discard already valid peers. Authority
observation timestamps are sampled after the asynchronous owner-store
observation completes. At physical provider entry, the final-use guard samples
the clock again and requires both the capability window and every selected
memory's own validity window to remain current; clock regression or expiry
crossing suppresses the attachment.

### 4.3 Authenticated wire and host boundary candidate

The wire crate provides:

- registered canonical query, response, cancel and cancel-ack encoding;
- directional credential enrollment, rotation, expiry and revocation;
- HMAC-SHA-256 frames with OS CSPRNG nonces and bounded lifetime;
- an immutable `VerifiedFederationFrameV1`: all fields are private and can be
  inspected only through read-only accessors after successful verification;
- bounded replay admission with a host clock high-water mark and a per-directional
  credential partition, failing closed rather than evicting live nonces;
- authenticated chained owner-frontier witnesses;
- live attempt cancellation semantics;
- `FederationWireHostV1`, a transport-neutral two-stage host boundary;
- a canonical, integrity-bound durable replay/attempt snapshot and a host-owned
  `FederationRecoveryStoreV1` interface.

A selected secure transport must authenticate a peer identity and pass that
identity separately to the host. The host requires equality with the frame
sender, verifies the frame, durably records replay admission, durably records a
pending attempt, and only then exposes a read-only admitted query token. A
cancel request is persisted before its acknowledgement. Query completion is
persisted before response bytes can be emitted; a cancellation persisted first
causes a late completion to fail, including after host restart.

The host does not implement a socket, TLS stack, certificate authority, secret
store or Agentd service. It is the repository-controlled seam into which a
selected mutually authenticated transport can be attached without bypassing the
protocol invariants.

## 5. Contracts, ports and compatibility

Consumed registered contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `ModulePort::cognitive.read::memory.federation`
- `ModulePort::kernel.authority::memory.federation`

Native in-process V2 surface:

- `FederatedQueryV2`, `FederatedLeaseV2`;
- `FederationAuthorityV2`, `FederationTransportV2`,
  `FederationAttemptControlV2`;
- `RemoteFederatedResponseV2`, `FederatedResultV2`;
- `FederationCancellationRequestV2`, `FederationCancellationReceiptV2`.

Registered cross-host candidate schema:

- `hepta-memory-federation-authenticated-frame-v1`, carried at
  `codex-hepta-wire` wire version V2.

The registered schema is a source fact. It does not imply that Agentd currently
opens a network listener or that the transport has passed real-host acceptance.
Rust in-process V2 structs are not serialized by convention across a host
boundary; only the registered wire schema is eligible there.

`CognitiveRuntime::AvailableFederated` and `FederatedRecallSet` remain explicit
compatibility surfaces. Product attachment registration requires
`has_product_federation()` and the V2-only retrieval/revalidation APIs. The
legacy helper preserves an already composed V2 runtime instead of downgrading
it.

## 6. Data authority, persistence and migrations

The in-process adapter owns no authoritative database, migration, remote fact,
enrollment registry, credential store or retry queue. It opens existing owner
cognitive state through the established read-only reader. Durable grant/revoke
history remains owned by cognitive store and authority owners.

The wire host recovery snapshot owns only protocol safety metadata:

- authenticated replay keys and expiries;
- pending/cancelled/terminal attempt identities and expiries;
- capacity partitions;
- a monotonic observation high-water mark;
- local host identity and an integrity digest.

It does not contain memory content, credential secrets, grant authority or
training state. The selected deployment supplies a crash-safe
`FederationRecoveryStoreV1`; the included in-memory store is a deterministic test
fixture, not production durability. Recovery rejects non-canonical snapshots,
digest drift, identity/limit mismatch, duplicates, over-capacity state and clock
rollback. Expired records may be discarded, but live replay/cancellation fences
may not be silently forgotten.

Credential secret persistence is intentionally outside the recovery snapshot.
A selected host must use an independently reviewed secret store and preserve
strict generation, expiry and revocation semantics across restart.

## 7. Runtime, concurrency and transaction model

One in-process V2 call performs:

1. query and lease shape/binding validation;
2. fresh current-authority preflight and live-expiry ceiling validation;
3. one transport future raced against attempt control;
4. response shape, exact-query and digest verification;
5. a second fresh authority observation;
6. final validity, completeness and effective-expiry calculation;
7. result-digest sealing.

The core engine holds no global lock across I/O and owns no transaction. Product
discovery and reads are bounded independently as described above. Result
aggregation sorts and deduplicates after completion, so scheduling order cannot
change the final candidate order. A temporarily captured batch is request-local
and is released only after canonical V2 admission.

The cross-host candidate uses two-phase admission. Replay and pending intent are
persisted before the read handler; cancellation/terminal state is persisted
before outbound acknowledgement/response. The handler may return only a
read-only result digest and an owner-cut witness. The module does not open or
widen a remote storage transaction.

## 8. Failure semantics, recovery and rollback

Failures are never collapsed into a successful empty read:

- response/query/peer/scope/purpose/generation mismatch rejects the attempt;
- non-current preflight authority blocks dispatch;
- timeout, cancellation and nonterminal transport produce failed or
  indeterminate coverage without blind retry;
- post-I/O revoke or generation drift suppresses all remote items;
- an unobservable capability store consumes a bounded failed discovery slot;
- a grant for a different consumer workspace is filtered before query creation;
- `Partial + []` remains partial, not a valid empty result;
- reaching the top-K ceiling is conservatively partial unless a trustworthy
  no-more-results witness exists;
- final-use timeout, drift, expiry crossing, clock regression or secret-like
  content removes the federated proposal before provider transport entry.

For the cross-host candidate:

- a secure-channel peer mismatch rejects before handler admission;
- MAC, lifetime, credential and replay failures reject the frame;
- the replay cache and durable recovery state both reject clock rollback;
- one credential or peer cannot consume all shared replay/attempt capacity;
- failure to persist verified replay or pending intent blocks handler exposure;
- cancel-before-terminal produces `observed_before_terminal` and fences late
  completion, including after restart;
- a terminal-before-cancel produces `terminal_already_observed`;
- an unknown attempt remains explicitly unknown.

Rollback may stop composing V2 and discard ephemeral results. It may not restore
revoked authority, revive expired recovery entries, forget a live replay fence or
reinterpret stale cached evidence as current. The legacy path is never an
automatic product fallback.

## 9. Security, privacy and threat controls

The posture is least authority, bounded input, typed contracts, digest binding,
current authority and independent evidence. Credentials never enter general
logs, prompt factors, learning datasets or receipts. A caller-supplied lease is
not an authority ceiling: live authority supplies the durable expiry and a wider
lease is rejected before dispatch.

`VerifiedFederationFrameV1` is an unforgeable-by-construction API boundary:
external code cannot construct it with a struct literal or mutate message,
identity, key or lifetime fields after verification. Rust compile-fail doctests
are part of the qualification matrix.

The durable replay design records a monotonic host-time high-water mark. Once the
host has observed a later time, an expired nonce cannot be purged and then
re-admitted after wall-clock rollback. Live in-memory admission is partitioned
per directional credential; durable admission and attempts are partitioned per
peer. Full partitions fail closed.

A frame MAC is not endpoint authentication. Production transport must bind its
mutually authenticated peer/certificate identity to the exact peer supplied to
`FederationWireHostV1::admit`. Secure enrollment and recovery of credentials
remain external gates.

## 10. Performance, capacity and hot-path policy

Reviewed architecture ceilings include:

- `MAX_FEDERATED_RESULTS_V2 = 512`;
- `MAX_FEDERATION_SOURCES_PER_AGENT = 16`;
- at most 128 owner-layout candidates before discovery;
- bounded discovery, attempt and final-revalidation concurrency;
- one total product horizon, with at most half consumed by discovery;
- `MAX_FEDERATION_REPLAY_ENTRIES = 16_384`;
- a default replay partition of at most 1,024 live entries per directional
  credential;
- explicit durable replay/attempt global and per-peer limits;
- at most 1,024 outbound host peer bindings.

These are source ceilings, not deployment SLOs. The replay and durable recovery implementations use derived expiry indexes and
incremental partition counts with bounded cleanup batches;
target-host qualification must measure cleanup cost, rejection rate, replay
pressure, cancellation tail, snapshot encode/store latency, restart recovery and
backpressure. Capacity limits prevent unbounded growth but do not themselves
prove acceptable performance.

Coverage reports admitted requested/completed/failed peers, partial peers, peer
truncation, pre-discovery owner omission, item truncation and typed discovery,
deadline, authority, integrity and transport failures.

## 11. Observability and operations

Safe product observations include aggregate typed coverage, selected host-profile
identity, source/result digests, authority posture and bounded failure classes.
Do not log memory contents, credential material, raw nonces or unredacted remote
errors.

The in-process adapter takes `observed_frontier` from the same exact-scope SQLite
snapshot that produces candidates. A truly empty scope may report zero; nonempty
evidence may not. This local append-only count is not promoted into a remote
truth witness.

The wire host instead requires the read handler to provide an authenticated
owner-cut witness containing owner, generation, frontier, state digest, parent
witness and observation time. The host verifies ownership and the admitted time
interval before response emission. A selected owner store still must define how
that witness derives from a durable committed cut.

Operational activation requires alerts for replay/peer partitions, clock
rollback, recovery-store failure, repeated transport identity mismatch,
credential expiry/revocation, cancellation-tail growth and frontier rollback.
Concrete thresholds belong to the selected host profile.

## 12. Verification and qualification

Focused source and tests cover:

- response tamper and cross-query replay;
- ordered-prefix integrity and duplicate identity;
- authority lifetime ceilings and pre/post-I/O revocation;
- pending transport deadline/cancellation races;
- `Partial + []` and conservative top-K completeness;
- bounded discovery with a fast completed owner plus a permanently pending owner;
- deterministic bounded peer aggregation;
- final physical-send batch revalidation;
- legacy V1 default-surface exclusion;
- private verified-frame compile-fail contracts;
- replay after expiry cleanup followed by clock rollback;
- per-credential and per-peer capacity isolation;
- transport-peer/frame-sender binding;
- durable replay across restart;
- cancel-before-terminal fencing a late completion after restart;
- owner-cut witness ownership and time checks.

The module qualification script:

1. captures exact HEAD/tree, qualified source manifest and command manifest;
2. verifies this module with the canonical implementation-map verifier under a
   module-scoped registry view;
3. verifies all status projections against `CAPABILITY_STATE.json`;
4. runs focused format, tests, product composition checks and strict Clippy;
5. runs standalone wire library and compile-fail doctests;
6. requires a clean tracked checkout;
7. recomputes and compares the execution guard after the matrix;
8. emits a machine-readable payload and artifact-digest envelope binding source,
   commands, conclusion, capability state and optional resolved wire lockfile.

Both the exact source head and a deterministic merge against the then-current
base must pass the same suite. A failure receipt remains diagnostic evidence and
cannot set `productExecutionProved=true`. Independent review, selected-host
acceptance, canary, promotion and release remain separate gates.

## 13. Shared long-term view without a federation writer

Contribution/export commits belong to `cognitive.store` and
`kernel.operations`; training views and candidate publication belong to
`learning.ledger` and `learning.artifacts`. Federation only reads permitted
source views. Same-owner Agents still require matching consumer, workspace,
purpose and current authority; read permission is not training consent.

A shared training snapshot may select multiple owner cuts with explicit causal
dependency validation. Federation does not invent a global total order. A timed
out peer is unavailable coverage, not zero records or a valid training empty
set. Denied record existence may not leak through dedup indexes or response
statistics.

## 14. Indexed admission and source freeze procedure

See [`INDEXED_ADMISSION.md`](INDEXED_ADMISSION.md) for authentication-before-staging,
derived-index invariants, conservative cleanup backpressure, unchanged durable
commit ordering, architecture-scale diagnostics and the author-only observation
sequence. This guide adds no execution, deployment or acceptance claim.
