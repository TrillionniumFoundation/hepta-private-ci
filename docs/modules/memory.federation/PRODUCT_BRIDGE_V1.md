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

`FederationProductExchangeV1` is the only selected-transport seam. A concrete
implementation must obtain the peer identity and channel-binding digest from the
same mutually authenticated channel that carries the product packet. A caller
cannot substitute a bare peer string for `FederationAuthenticatedTransportV1`.
The bridge validates the source-controlled transport profile and the channel
lifetime before wire admission.

## Packet and body binding

A product packet contains:

1. one registered authenticated federation frame; and
2. one bounded canonical V2 body.

For queries, the authenticated frame carries the canonical query binding digest
and all duplicated routing fields. The host decodes and validates the bounded
body, checks the exact canonical binding, recipient, deadline, and transport
horizon, and only then calls the durable wire admission boundary.

For responses, the authenticated frame carries both the canonical response
digest and a digest of the exact encoded body. The client verifies packet
bounds, transport identity/profile/currentness, the body digest, canonical
response digest, query binding, peer, expiry horizon, and frontier number before
calling the durable client admission boundary.

This order is deliberate. A malformed or tampered outer body must not consume a
replay nonce, create a durable query attempt, or terminally close a valid client
attempt. Regression tests submit a tampered packet first and then prove that the
original authenticated packet remains admissible.

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
material and deliberately leaves concrete transport and production recovery
selection unset.

## Qualification

The existing exact-head and deterministic-current-base qualification command
runs the standalone wire crate's full library tests, doctests, capacity probe,
strict Clippy, and tracked-lock verification. Because the attestation selects
the whole wire source root and module documentation directory, the product
bridge, tests, deployment profile, implementation map, and canonical capability
state are bound into the same source identity and artifact receipt.

Repository-controlled source qualification is necessary but not sufficient for
production claims. Remaining external gates are a selected mutually
authenticated transport, secure credential operations, deployment-specific
persistent recovery policy, two independently provisioned real-host fault
qualification, target-host latency/capacity/backpressure/cancellation evidence,
independent security and semantic acceptance, and operator-controlled canary,
promotion, and release.
