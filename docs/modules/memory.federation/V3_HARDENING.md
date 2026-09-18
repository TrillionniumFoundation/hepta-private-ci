# memory.federation V3 hardening guide

Status: source candidate; exact-head and merge-candidate qualification required before activation.

This document is the implementation-level companion to `TECHNICAL.md` for the authenticated capability-scoped V3 path. V2 remains compatibility-only and is not removed by this change.

## Security invariants

1. A federation query is bound to peer, principal, scope, purpose, generation, query digest, result bound, deadline, lease epoch and request nonce.
2. A capability is usable only after an Ed25519-verified authority envelope and a fresh Ed25519-verified revocation observation agree on grant and epoch.
3. Capability/revocation verification is performed immediately before transport and again after I/O with a fresh clock read.
4. A remote response must bind the query binding digest, request nonce, response nonce, peer, principal, grant, scope, purpose, generation, lease epoch, frontier, expiry and evidence items into its canonical payload digest.
5. The remote canonical payload digest must verify against the enrolled peer verification key.
6. A response that is late, revoked, replayed, scope-mismatched, principal-mismatched, grant-mismatched or signature-invalid is never exposed as usable evidence.
7. Effective result expiry is `min(remote expiry, authority expiry, query deadline)`.
8. `Partial` is never rewritten to `Empty` merely because zero items were returned.
9. A federation aggregate is `Partial` if any peer is partial/indeterminate, any peer failed coverage, or any truncation occurred.
10. Every V3 result and aggregate has `AuthorityPosture::DENY_ALL`; remote evidence never becomes mutation authority.

## Canonical authority receipt

`CapabilityAuthorityEnvelopeV3` binds:

- authority issuer and key ID;
- grant and lease ID;
- query, peer and principal ID;
- scope, purpose and generation digests;
- query binding digest;
- lease and revocation epoch;
- expiry;
- proof digest and Ed25519 signature.

`CapabilityRevocationObservationV3` binds issuer, key, grant, observed revocation epoch, revoked state and observation time. `SignedCapabilityVerifierV3` rejects stale observations, epoch drift and revoked grants.

## Remote response envelope

`RemoteFederatedResponseV3` binds all request identity needed to prevent cross-query replay. `payload_digest` is recomputed locally from canonical field ordering and evidence ordering before signature verification.

The peer signature is verified using `FederationKeyResolverV3`. The resolver is a trust-store boundary; query input cannot inject its own verification key.

## Transport and cancellation

`FederationTransportV3` and `AsyncFederationTransportV3` both receive the absolute deadline and a cancellation token. A selected host transport must observe both while I/O is active. The federation boundary independently repeats deadline and authority checks after return/await, so a transport bug cannot convert a late or revoked response into valid evidence.

A transport attempt remains single-shot. Retries require a new query identity/nonce and separate caller authorization.

## Multi-peer orchestration

`execute_federation_v3` accepts at most 16 peer plans. Per-peer operations execute independently, child results are deterministically sorted, duplicate evidence identity is collapsed deterministically, and the final aggregate is capped at 512 evidence items.

Coverage records requested/completed/failed peers and truncation. Partial/indeterminate child state is monotonic: aggregation cannot promote incomplete evidence to global complete/empty state.

## Cache, revalidation and revocation purge

`FederatedResultCacheV3` stores only non-authoritative results. Entries retain their originating query and signed authority envelope. Reuse calls `get_revalidated`, which checks TTL and repeats live capability verification.

The cache maintains grant, authority-key and peer indexes so a host can purge results on grant revocation, key retirement/compromise or peer removal. Cache entries cannot outlive their capability or query deadline.

## Product composition

`FederationServiceV3` is the product-facing composition boundary. Before transport it requires `PeerEnrollmentRegistryV3::is_enrolled(peer_id)`. The selected host supplies:

- enrolled peer registry;
- peer/authority verification-key resolver;
- current capability revocation source;
- sync or async authenticated network transport;
- monotonic-to-wall-clock-safe time source as required by the host profile.

These adapters are owner facts and must not be synthesized from remote discovery results.

## Verification matrix

The candidate test suite covers canonical remote tamper rejection, post-I/O deadline enforcement, revocation during I/O, cross-query replay rejection, Partial+empty preservation, effective TTL capping, pre-cancellation, cache revalidation/purge and enrollment rejection.

Additional selected-host qualification must cover real network cancellation, per-peer timeout isolation, key rotation, revocation feed interruption, concurrent <=16 peer fan-out, overload, fault injection and deterministic synthetic-merge execution.

## Activation and release ceiling

Source presence and unit/integration tests do not grant activation. The implementation map must continue to report production/activation/release false until concrete selected-host adapters, exact-head qualification, independent review, canary and operator acceptance are present.
