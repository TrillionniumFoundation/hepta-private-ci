# memory.federation canonical V2 product adapter layer

This stacked delivery binds the authenticated durable wire host/client to the canonical memory.federation V2 query and response contracts.

## Included

- bounded canonical V2 query and response body encoding;
- body digests bound to authenticated wire frames;
- exact-attempt response preflight before replay or terminal mutation;
- authenticated transport-context issuer/verifier binding local owner, remote peer, profile, channel lifetime, and key generation;
- product client and read-only host adapters;
- interruptible single-attempt transport with deadline and final local-use fences;
- same-process and restart retry safety when inbound persistence fails;
- contention, body-tamper, wrong-attempt, clock-regression, cancellation, atomicity, and capacity-probe tests.

## Excluded

The crate remains transport-neutral. This layer does not select mTLS/QUIC, provision deployment credentials, compose Agentd serving, operate two independent real hosts, establish target SLOs, or grant independent acceptance, activation, promotion, or release.


## Contract and ownership map

| Boundary | Implementation under `codex-rs/hepta-memory-federation-wire/src` | Admission requirement |
| --- | --- | --- |
| Packet | `product/packet.rs` | HFP1/version 1, bounded frame/body lengths, exact EOF |
| Query/response body | `product/body.rs` | Versioned schema, unknown-field rejection, bounded bytes, canonical V2 binding |
| Transport context | `product/context.rs` | Authenticated local owner, remote peer, profile, channel digest, lifetime and key generation |
| Read host | `product/bridge.rs::FederationProductHostV1` | Context and body checked before durable wire admission |
| Outbound client | `product/bridge.rs::FederationProductClientV1` | Exact attempt/body checked before replay or terminal persistence |
| Adapter | `product/transport.rs::FederationWireTransportV2` | One exchange, nonblocking lock, fresh dispatch/receive/completion clocks |
| Recovery | `client/`, `host.rs`, `recovery.rs`, `file_store.rs` | Persist before acceptance; poison ambiguous post-rename state |

Canonical cancellation and authority admission remain owned by
`codex-rs/hepta-memory-federation/src/v2.rs::execute_once`. The engine checks
stop before constructing transport/authority futures and after each ready poll.
A pending exchange is dropped on stop; the selected transport must stop further
I/O when dropped. This does not preempt synchronous storage work or undo an
already admitted external effect.

## Data carried and product completion boundary

The request carries `query_digest` and binding metadata, rather than the
full owner `RetrievalRequest`. The current host-local adapter additionally
captures that request in `hepta-memory/src/cognitive_runtime.rs`.
A remote serving owner therefore needs an explicit bounded query/evidence
resolution contract and its own current principal/scope/purpose grant check.
Peer authentication alone does not authorize an owner read.

The response carries owner/record identity, revision and record/support/validity
digests. It does **not** carry model-visible memory content or complete remote
revalidation material. A receiving host cannot construct a model attachment
from these authenticated digests alone. Existing Agentd model input still uses
local read-only owner stores.

The next layer must specify a bounded authenticated evidence payload, bind it
to the response and owner cut, validate it before replay/terminal mutation,
and preserve purpose, permissions, completeness, expiry, correction/deletion
and final-use checks. It must then compose the selected channel and remote owner
service through Agentd. Until that and independent two-host qualification pass,
this is a protocol/adapter candidate, not usable cross-host product recall.

## Failure and recovery semantics

- Outbound query, response and cancellation-reply packet lengths are checked
  against the selected product profile before pending/terminal/replay state
  commits. Rejection preserves the prior durable snapshot and replay slots.
- An owner response already expired at completion is rejected before terminal
  persistence. Response shape and digest validation performed by body decoding
  is reused by client preflight.
- Lock contention before network entry reports unavailable coverage; after
  entry it reports indeterminate coverage and retains pending intent.
- Durable query preparation precedes exchange. A fresh local clock rejects
  regression or deadline crossing after preparation.
- Exact-query response preflight precedes replay/terminal mutation, so a packet
  for another attempt cannot consume its replay slot.
- Pre-commit storage failure permits reconciliation with the same exact attempt.
  Ambiguous post-rename failure requires close/reopen and durable-state inspection.
- Completion persistence can cross expiry. Retain the terminal fence while
  suppressing stale evidence; do not blindly retry an unknown outcome.
- The filesystem snapshot digest is not an independent rollback witness.
  HMAC and context attestation require separately provisioned peer keys and a
  mutually authenticated selected channel.

## Verification and operation

The product workflow also triggers on changes to canonical federation, types
and wire dependencies. It tests the canonical engine and adapter, checks
formatting/doctests/strict Clippy, and runs the capacity probe using its positional
output path. Capacity diagnostics are retained under the asserted event source
SHA. Local results do not replace hosted source/merge qualification.

Deployment must separately select the channel, provision/rotate secrets, own
pending-attempt expiry maintenance, bound blocking disk work and backpressure,
measure host SLOs, and rehearse restart, revoke, deletion, partition and rollback
on two independently provisioned hosts. These implementation and acceptance
gates cannot be replaced by changing completion flags.
