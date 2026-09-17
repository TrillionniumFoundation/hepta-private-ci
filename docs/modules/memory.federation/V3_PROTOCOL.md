# memory.federation V3 protocol and product composition

Status: implementation candidate on `codex/memory-federation-full-closure-20260917`.
Parent: `TECHNICAL.md`. This document specifies the authenticated, capability-scoped V3 path. It does not grant peer-enrollment, memory-write, promotion or release authority.

## 1. Security boundary

V3 separates two trust domains:

1. **Local capability authority.** `FinalUseAuthority` from `codex-hepta-contracts` is the only verifier for the signed final-use grant. It pins the authority issuer and Ed25519 verifying key, persists claimed nonces, consumes each grant once, applies monotonic revocation heads, and revalidates live authority after asynchronous I/O through `with_verified_use`.
2. **Remote peer authenticity.** `FederatedPeerEnrollmentV3` contains an immutable host-enrolled HTTPS origin, pinned CA, peer response key ID, Ed25519 verifying key, enrollment epoch and expiry. `memory.federation` verifies remote response signatures but owns no peer signing key and cannot enroll a peer.

A federation result always carries `AuthorityPosture::DENY_ALL`. Remote evidence is observational input, never reusable authority.

## 2. Query binding

`FederatedPeerQueryV3::binding_digest()` domain-separates and hashes:

- query ID;
- peer ID;
- principal ID;
- scope digest;
- purpose digest;
- generation-vector digest;
- query digest;
- maximum result count;
- absolute deadline;
- authority epoch;
- request nonce digest.

The final-use authority binding maps principal to `subject_id`, peer to `destination_id`, the full V3 query binding to `request_sha256`, scope to `scope_sha256`, and the query digest to `payload_sha256`.

A peer permit is therefore not transferable to another principal, peer, scope, query, deadline, generation or request nonce.

## 3. Remote signed envelope

`RemoteFederatedEnvelopeV3` binds:

- exact query, peer and principal identities;
- scope and purpose;
- generation vector;
- V3 query-binding digest;
- request nonce digest;
- authority epoch and grant ID;
- independent response nonce digest;
- enrolled peer key ID;
- observed remote frontier;
- response expiry;
- sorted evidence identities and their record/support/validity digests;
- completeness and terminal observation.

`payload_digest` is recomputed from canonical domain-separated bytes. The peer Ed25519 signature covers a second domain-separated message containing that payload digest. A payload change after signing, query replay under another binding, key substitution, grant substitution, scope drift or peer drift fails closed.

The wire decoder uses `serde(deny_unknown_fields)` and schema version `3`. The outbound wire request does not transmit the local signed grant or signature; it exposes only the authority issuer/grant identity and bound query metadata required by the enrolled peer protocol.

## 4. Time, revocation and TOCTOU

Every peer attempt performs these checks in order:

1. sample a fresh clock;
2. validate deadline, peer target and current enrollment;
3. call `FinalUseAuthority::claim` immediately before dispatch;
4. execute exactly one transport attempt;
5. sample a fresh clock after I/O;
6. reject an expired query and re-resolve the immutable peer enrollment;
7. verify the complete remote envelope and peer signature;
8. set result expiry to `min(remote response expiry, signed grant expiry, query deadline, peer enrollment expiry)`;
9. sample a fresh release time;
10. call `FinalUseAuthority::with_verified_use` before releasing evidence to the aggregate/cache path.

A revocation or authority-epoch transition that races with network I/O therefore prevents evidence release. A grant nonce remains consumed after an uncertain attempt; any explicit retry requires a separately issuer-signed grant and a new request nonce.

## 5. Multi-peer orchestration

A `FederatedReadPlanV3` supports 1 through 16 unique peers and an explicit concurrency bound no larger than the peer count. Fan-out uses bounded unordered execution; merge output is deterministic.

Per-peer coverage records peer identity, completeness, validity, returned/truncated items and an explicit failure class. Aggregate rules are:

- no completed peers => `Indeterminate`;
- any failed, partial or stale peer with at least one completed peer => `Partial`;
- `Empty` is possible only when every requested peer completed without partial/stale coverage and no evidence exists;
- `Complete` is possible only when every requested peer completed without partial/stale coverage and evidence exists.

Evidence is keyed by `(source_owner_id, record_id, record_revision)`. Equal identities with different contents are rejected instead of choosing a winner. Final evidence is deterministically sorted and bounded by the request maximum, with truncation forcing `Partial`.

## 6. Transport and cancellation

`FederationTransportV3` is asynchronous and receives a per-attempt cancellation token. `FederationClientV3` also owns a query-level token registered by query ID.

The concrete `PinnedHttpsFederationTransportV3`:

- accepts only the enrolled HTTPS root origin;
- uses the repository-owned `codex-http-client` pinned-CA direct transport;
- sets one request deadline from the remaining query lifetime;
- performs no automatic retry;
- bounds response bodies to 4 MiB;
- maps timeout/unavailable outcomes explicitly;
- checks cancellation while receiving the response body.

The client races each network future against query cancellation and the absolute query deadline. Cancellation signals the transport token and drops the in-flight future; returned evidence is never released after cancellation.

## 7. Cache and revalidation

`FederationResultCacheV3` is a non-authoritative in-process projection capped at 4096 entries. It indexes entries by:

- grant ID;
- peer response key ID;
- peer ID.

Entries store the original query, original signed grant metadata and sealed peer result. Only `Valid`, unexpired results enter the cache.

`revalidate_remote` does not trust the cached authority receipt alone. It requires a fresh signed final-use grant with the same grant ID/authority epoch and a fresh nonce, checks the current peer enrollment/key and generation vector, calls `FinalUseAuthority::claim`, and finally releases the cached result only through `with_verified_use`.

Purge APIs remove by grant, peer, peer key or a trusted `FinalUseRevocations` head. An authority epoch change invalidates cached entries from the previous epoch.

## 8. Authority receipt

`VerifiedFederationAuthorityReceiptV3` is observational proof produced only after the real authority claim succeeds. It contains issuer/key metadata, grant ID, authority epoch, principal, peer, scope, purpose, query binding, grant expiry, a digest over the canonical signed-grant bytes plus signature, a local receipt digest and `DENY_ALL` authority.

The receipt is not a capability and cannot be replayed to authorize another operation.

## 9. Compatibility V2

The root `execute_once` compatibility path retains the V2 transport contract but corrects two semantics:

- a terminal remote `Partial` response with zero items remains `Partial` instead of becoming `Empty`;
- result expiry is capped by both lease expiry and query deadline.

V2 still lacks authenticated remote signatures and post-I/O clock/authority revalidation. Product composition must use V3 for the closed security model.

## 10. Verification cases

`src/v3_tests.rs` composes fixtures from `src/v3/tests/` and covers:

- partial-empty semantics and capability-bounded TTL;
- tampered remote payload rejection after signing;
- fresh-clock deadline TOCTOU rejection;
- revocation racing transport and final authority fence;
- multi-peer failure preserving global partial coverage;
- bounded fan-out and deterministic merge;
- cache fresh-authority revalidation and revocation purge;
- in-flight cancellation returning explicit indeterminate coverage.

The existing V1/V2 tests remain in place and a root regression test covers the V2 partial-empty correction.

## 11. Product composition and remaining external gates

`ProductionFederationClientV3` is the concrete pinned-HTTPS composition. A product host supplies:

- the kernel-owned `FinalUseAuthority` instance and its configured key ID metadata;
- an immutable `FederationPeerRegistryV3` snapshot constructed from owner-approved enrollment records;
- signed final-use grants for each peer attempt.

This source implementation deliberately does not become the enrollment owner or authority issuer. A named upstream product caller may compose the concrete client only after its own owner path supplies those dependencies.

Source implementation, package tests and repository qualification do not themselves establish operator acceptance, production activation, promotion or release. Those claim boundaries remain external until exact-candidate CI and host qualification receipts exist.
