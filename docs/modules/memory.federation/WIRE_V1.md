# memory.federation authenticated wire V1

This document specifies the transport-neutral cross-host candidate implemented by
`codex-rs/hepta-memory-federation-wire`. It does not activate a network service
and does not change the in-process product caller into a cross-host product.

## 1. Registered schema and admission

The only admitted payload schema is
`hepta-memory-federation-authenticated-frame-v1`, registered through
`codex-hepta-wire` at wire version V2. Encoding is canonical, length-delimited,
versioned, and rejects unknown message tags, invalid booleans, trailing bytes,
invalid identities, empty/oversized frames, and non-canonical enum values.

The schema carries four message classes:

- scoped query;
- terminal response with an authenticated frontier witness;
- cancellation request;
- cancellation acknowledgement with a typed disposition.

Query, response, cancellation, and acknowledgement remain distinct message
classes. A cancellation acknowledgement is evidence that the peer observed the
request; it is not proof that an already-completed external effect was undone.

## 2. Peer identity and credential lifecycle

Authentication uses directional 256-bit peer credentials. Each credential binds
sender peer, receiver peer, key identity, strictly positive generation, effective
time, expiry, and secret key bytes. Enrollment, strict-generation rotation, and
revocation are explicit registry operations. A frame is rejected when the exact
directional credential is missing, not yet effective, expired, or revoked.

Production transport must additionally use mutually authenticated TLS, or an
independently reviewed equivalent secure channel, with the transport identity
bound to the same peer identities carried by the authenticated frame. The frame
MAC is not a substitute for endpoint routing, certificate validation, or secure
key distribution.

## 3. Frame integrity and replay resistance

Every frame uses an operating-system-generated 256-bit nonce and an HMAC-SHA-256
over the protocol domain, sender, receiver, key identity/generation, issue and
expiry times, nonce, and canonical message digest. Frame lifetime is capped at
five minutes and may not exceed credential expiry.

The receiver admits a nonce exactly once under the directional credential. The
bounded replay cache removes only expired entries. When all slots contain
unexpired entries it fails closed rather than evicting an entry and reopening a
replay window.

## 4. Authenticated frontier witness

A response includes owner peer, generation, monotone frontier, state digest,
parent witness digest, and observation time. The witness is covered by the frame
MAC. A successor must preserve owner identity, not regress generation/frontier or
clock, and bind the exact digest of its predecessor. This is stronger than the
current in-process SQLite row-count frontier and is the minimum remote rollback
witness for the candidate profile.

The selected remote store must still define how its state digest and generation
are derived from a durable committed cut. The protocol does not manufacture a
truthful store witness from an untrusted count.

## 5. Cancellation

Cancellation requests bind query identity, query digest, cancellation identity,
and typed reason. A peer replies with one of:

- `observed_before_terminal`;
- `terminal_already_observed`;
- `unknown_attempt`.

Both request and acknowledgement are authenticated and replay-protected. Product
activation requires an attempt registry that emits and retains these messages;
future-drop alone remains sufficient only for the current in-process adapter.

## 6. Qualification boundary

Repository tests cover canonical round-trip, field tamper, replay, rotation,
revocation during logical in-flight delivery, frontier rollback, cancellation
acknowledgement, clock/lifetime checks, and replay-cache overload. They use two
logical hosts and a deterministic fault harness.

The following remain external release gates:

- two independently provisioned real hosts;
- mutually authenticated transport and certificate/key rotation;
- partition, timeout, replay, rollback, clock-skew, revoke-during-I/O, and overload
  tests over the selected network implementation;
- measured latency, capacity, backpressure, cancellation tail, recovery, and
  operator acceptance;
- canary, promotion, and release authority.

Until those gates pass, product documentation must say **authenticated wire
candidate**, not **production cross-host memory federation**.
