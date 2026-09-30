# memory.federation authenticated product bridge V1

## Status and claim boundary

This document describes a source candidate that connects the authenticated
cross-host protocol to the existing canonical `FederationTransportV2` boundary.
It does not select a network stack, configure an Agentd listener, provision
credentials, approve a durable production backend, prove two-host execution, or
authorize activation, promotion, or release. Canonical claim state remains in
`CAPABILITY_STATE.json`; prose cannot widen it.

## Ownership

The bridge lives in `codex-rs/hepta-memory-federation-wire/src/product/mod.rs` and
depends on the existing canonical V2 types and transport trait in
`codex-rs/hepta-memory-federation/src/v2.rs`. The canonical engine continues to
own single-attempt execution, authority revalidation, deadline/cancellation
racing, result semantics, and the no-blind-retry rule. The bridge does not add a
second peer registry, scheduler, authority store, or retry queue.

`FederationProductExchangeV1` is the only selected-network seam. A concrete
implementation must obtain the local endpoint identity, remote peer identity and
channel-binding digest from the same mutually authenticated channel that carries
the product packet. Each selected transport endpoint receives a
`FederationTransportContextIssuerV1` bound to its exact local wire owner; the
matching product host or client receives the corresponding
`FederationTransportContextVerifierV1`. Product host/client construction rejects
a verifier whose local owner or transport profile differs from the actual wire
owner/profile.

The issuer HMAC-attests local peer, remote peer, transport profile, channel
binding, channel lifetime, context-key identity and generation. The bridge
verifies that attestation before packet parsing, replay admission or
attempt-state mutation. A caller cannot make a trusted context by supplying a
bare peer string, arbitrary nonzero digest, independently chosen issuer key, or
a context minted for another local host.

The transport-context attestation secret is deployment-owned secret material. It
is separate from the directional frame credential, absent from the
source-controlled product profile, never serialized into a packet or recovery
snapshot, and redacted from debug output. Key selection, per-host placement,
rotation, revocation, storage and process isolation remain part of the selected
transport and host credential design. Reusing one issuer key across unrelated
local hosts is outside the deployment contract even though local-owner binding
also makes such a context fail closed.

## Packet and body binding

A product packet contains:

1. one registered authenticated federation frame; and
2. one bounded canonical V2 body.

For queries, the authenticated frame carries the canonical query binding digest
and all duplicated routing fields. The host first verifies the selected
transport's local/remote context attestation, then decodes and validates the
bounded body, checks the exact canonical binding, recipient, deadline, and
transport horizon, and only then calls the durable wire admission boundary.

For responses, the authenticated frame carries both the canonical response
digest and a digest of the exact encoded body. The client verifies the transport
context attestation, packet bounds, local endpoint, remote identity, profile,
currentness, body digest, canonical response digest, query binding, peer, expiry
horizon, and frontier number before calling the durable client admission
boundary.

This order is deliberate. A forged or wrong-local-host transport context,
malformed outer packet, or tampered body must not consume a replay nonce, create
a durable query attempt, or terminally close a valid client attempt. Regression
tests submit untrusted-key and wrong-local-host contexts, plus tampered packets,
then prove that the original packet remains admissible through the correct local
issuer.

## Time and cancellation

The adapter samples its local clock before creating the authenticated query and
again after the selected transport returns. It does not trust a transport-owned
"received at" timestamp. A clock regression or a response at/after the query
deadline is treated as a non-terminal timeout result.

Dropping the exchange future is the canonical cancellation boundary. The
selected transport is required to stop subsequent network I/O on drop. The
underlying wire protocol retains explicit durable query/cancel/cancel-ack
semantics; selecting and qualifying a concrete transport must additionally
prove that its drop/cancel integration preserves those semantics under process
and network faults.

## Bounds

The canonical body is bounded to 512 KiB and at most 512 evidence items. The
registered authenticated frame budget includes the existing 256 KiB frame
payload ceiling plus bounded schema-envelope overhead. The entire product
packet is rejected before allocation or admission when it exceeds the
source-controlled profile or architecture ceiling.

The checked-in deployment profile is
`docs/modules/memory.federation/DEPLOYMENT_PROFILE.json`. It contains no secret
material and deliberately leaves concrete transport, per-host transport-context
key, and production recovery selection unset.

## Qualification

The existing exact-head and deterministic-current-base qualification command
runs the standalone wire crate's full library tests, doctests, capacity probe,
strict Clippy, and tracked-lock verification. Compile-fail documentation rejects
direct construction of authenticated transport context. Product tests reject a
correctly shaped context minted under an untrusted key and a validly attested
context minted for another local wire owner before replay state is consumed;
they then prove the same query remains admissible through the correct issuer.
Because the attestation selects the whole wire source root and module
documentation directory, the product bridge, tests, deployment profile,
implementation map, and canonical capability state are bound into the same
source identity and artifact receipt.

Repository-controlled source qualification is necessary but not sufficient for
production claims. Remaining external gates are a selected mutually
authenticated transport, secure frame and per-host transport-context credential
operations, deployment-specific persistent recovery policy, two independently
provisioned real-host fault qualification, target-host
latency/capacity/backpressure/cancellation evidence, independent security and
semantic acceptance, and operator-controlled canary, promotion, and release.
