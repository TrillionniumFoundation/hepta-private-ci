# Indexed admission and immutable qualification inputs

## Scope and authority

This development increment retains the canonical V2 engine, Agentd and Memory
extension callers, current authority owners, `legacy-v1` opt-in boundary,
single-attempt semantics and final physical-send revalidation. It introduces no
network service, new credential issuer, alternative database or acceptance
owner. `CAPABILITY_STATE.json` remains the only capability-status source.

## Authentication before transaction preparation

Both `FederationWireHostV1::admit` and `FederationWireClientV1::admit` now perform
bounded decode, secure-channel peer equality, frame shape/lifetime/recipient
validation, current directional credential selection and MAC verification before
cloning replay state or staging durable recovery. The request-local proof borrows
the immutable frame and cannot produce `VerifiedFederationFrameV1` until replay
admission succeeds. It is crate-private and is not an authorization cache.

The public `AuthenticatedFederationFrameV1::verify` still requires replay
admission. No MAC-only public verified-frame constructor is introduced. The
same host/client call retains exclusive access to credentials throughout this
synchronous preparation; no await or credential mutation occurs between proof
creation and replay admission.

After authentication, durable replay preflight and live replay admission modify
only staged state. Query intent, cancellation fence, terminal observation and
response eligibility remain bound to the original attempt. The recovery store
must successfully replace the complete canonical snapshot before any staged
state is installed or work/response bytes become visible. A definite failed
store leaves the original packet retryable; an indeterminate commit still
requires the backend to fence operations until reopen. Authentication failure
must not consume a nonce, advance the durable clock or close an attempt.

## Derived indexes and bounded cleanup

The live replay cache maintains its existing directional credential counts and
an expiry-ordered index. Durable recovery maintains expiry indexes for replay
and attempts plus incremental per-peer counts. None of these derived indexes
enters the persistent snapshot. Restore validates canonical encoding, digest,
identity, timestamps, limits and records first, then rebuilds the indexes.
Canonical primary snapshot bytes and the schema version are unchanged.

A cleanup batch removes at most 64 expired records. Durable cleanup shares its
batch across the replay and attempt indexes in expiry order. Explicit bounded
maintenance can choose a smaller or larger budget; work never exceeds the
number of retained records. Legacy `ReplayCacheV1::purge_expired` retains its
explicit drain-all behavior. Several bounded batches may run during a single
host transition; the bound applies per cleanup call, not to the whole request.

Expired records left by a bounded batch may conservatively occupy capacity.
Callers must treat capacity errors as backpressure, never evict live replay or
cancellation fences, never reinterpret an unavailable peer as a valid empty
result, and never silently retry the remote operation. A later maintenance call
can reclaim additional expired rows. Monotonic high-water checks remain in
force before purge; clock rollback never reopens a replay window.

Trusted owner-local recovery staging clones primary state and derived indexes
rather than serializing and parsing JSON. This avoids redundant encoding and
validation of already validated private state. It does **not** make successful
host admission constant-time: map cloning, canonical snapshot encoding and the
selected store's write remain proportional to retained state. The expiry work
is O(k log n), and ordinary partition checks use indexed counts, but full
snapshot cost still needs target-host measurement.

## Discovery budget

Owner discovery still has at most half of the one global request horizon. Reads
retain the other half and all unused discovery time when discovery completes
early. The collector already returns at stream exhaustion: no fixed wait or
second scheduler is added. Completed candidates are still sorted/deduplicated
before admission; authority is re-observed rather than cached.

## Qualification order

1. Commit source, tests, command contract, capability-state projections and docs.
2. Run `scripts/prepare_memory_federation_observation.py` with that exact source
   SHA, the resolved base SHA and candidate branch. It rejects a dirty checkout.
3. Commit only the resulting `IMPLEMENTATION_MAP.json`. The observation binds
   the preceding source commit, avoiding a self-referential future-commit hash.
4. Freeze the resulting candidate. Execute the canonical read-only matrix on
   both this SHA and its deterministic merge with the pinned current base.
5. Emit and verify actual command transcripts, payloads and artifact envelopes.
   Failed/incomplete execution remains diagnostic evidence, never a success.
6. Independent semantic/security and operator acceptance remain separate acts.

The author-only observation command is deliberately not part of qualification.
The verifier must not fix source drift or rewrite success fields. Any later
change to capability state, tests, docs or source requires a new observation.

The attestation CLI registers its `__main__` instance under its importable module
name before the execution guard can import it. This prevents duplicate path
extension and verifier wrapping. Fresh-interpreter tests cover both CLI-first
and module-first initialization; they do not claim Rust execution.

## Regressions and capacity evidence

Tests cover authentication before recovery staging on both endpoints, original
packet admissibility after forgery rejection, store-failure retryability,
derived-index reconstruction, bounded mixed cleanup, expiry counter removal,
clock rollback, full live replay saturation and restart-surviving cancellation.
The discovery regression uses the existing product collector and does not add a
test-only executor. Existing real SQLite grant/revoke and Memory extension
physical-send tests remain in the canonical matrix.

The logical capacity probe now uses 16 peers, 1,024 replay rows per peer and
1,024 attempts per peer: 16,384 replay rows and 16,384 attempts. Its attestation
validator binds those exact workload counts. Measured durations are diagnostics,
not target-host SLOs; the receipt must come from actual execution.

## Remaining deployment acceptance

The selected mutually authenticated network transport, per-host credential and
context-key operations, concrete recovery backend, Agentd serving composition,
and two independently provisioned real-host fault qualification must still be
provided and accepted. The checked-in profile does not silently select them.
A qualifying run must identify both hosts, the exact source/merge, transport and
credential generations, backend configuration and fault observations (replay,
identity mismatch, response loss, crash/restart, cancellation, rotation,
revocation, clock anomalies and capacity backpressure). Logical-host tests and
fresh source receipts alone cannot set these deployment gates to true.


## Owner maintenance progress under repeated admission failure

Host and client expose `maintain_expired(now)` through their existing product
bridge. A call commits a shared maximum of 64 expired durable protocol rows and
live replay rows through the same recovery store, without sending or retrying a
query. The selected host owner must budget these calls between admissions;
there is no second worker, authority store, or automatic query retry here.
This matters when a denied attempt would repeatedly discard its staged cleanup
and otherwise never reach later expired rows in a full peer partition. A failed
maintenance store leaves the live snapshot unchanged; a successful call makes
its cleanup and clock high-water mark durable before installing state. Live
replay and cancellation fences remain untouched. Client metadata reconciliation,
state cloning, and full snapshot persistence still have bounded O(n) costs; the
64-row limit is not a claim of constant total operation cost. Regressions cover
partition pressure, a failed maintenance write, progress through multiple
quanta, replay retention, restart, and clock rollback.

The public crate root now also exports the already implemented configured
transport-context issuer, verifier, and key-size constant. This repairs product
consumer compilation without introducing a bare trusted-context constructor.
