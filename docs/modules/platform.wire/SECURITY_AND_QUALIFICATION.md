# platform.wire production security and qualification

This document defines the production-facing security composition added above the frozen HPTA V1/V2 framing contracts. It does not turn source code, a pull request, or a passing generic CI run into deployment authority.

## 1. Immutable registry and policy snapshot

Production sessions use `FrozenSchemaRegistryBuilder` and `FrozenSchemaRegistry`, not a process-global mutable `SchemaRegistry`. Each `SchemaPolicy` binds one schema descriptor to:

- an explicit bounded producer allowlist;
- an explicit bounded runtime-role allowlist;
- the minimum effective negotiated capabilities;
- wire-version and payload ceilings inherited from `SchemaDescriptor`.

The builder is bounded to `MAX_FROZEN_SCHEMA_ENTRIES` and rejects conflicting reuse. `freeze()` creates a read-only registry and a deterministic `snapshot_digest`. The digest includes every schema identity, version range, payload limit, capability requirement, producer and role in canonical sorted order. A session therefore cannot silently observe a later registry mutation.

## 2. Negotiation and channel binding

`NegotiationTranscript::from_offers` re-runs negotiation and rejects a supplied result that does not equal the result implied by the ordered initiator/responder offers. Its digest binds:

1. both canonical HPTN offer byte strings in role order;
2. selected wire version;
3. effective, common-advertised and required capabilities;
4. frozen registry snapshot digest;
5. an authenticated transport channel binding.

The channel binding must contain 16–512 bytes. It should be a TLS exporter, Noise handshake hash, mutually authenticated local-channel binding, or an equivalently authenticated value supplied by the transport owner. A hostname, socket address, bearer token string, or unverified peer claim is not an acceptable channel binding.

`WireSession` derives a stable session identifier from the transcript, registry snapshot and selected posture. It couples typed encoding/decoding to the negotiated version, runtime role, admitted producer and schema policy.

## 3. Authenticated record format

`AuthenticatedWireSession` provides an optional transport-neutral HMAC-SHA-256 record layer for transports that do not already provide equivalent per-record authentication and replay ordering.

Record V1 layout:

| Field | Width | Meaning |
|---|---:|---|
| magic | 4 | ASCII `HPTM` |
| format | 2 | unsigned big-endian `1` |
| session ID | 32 | transcript/registry/session posture digest |
| sequence | 8 | unsigned big-endian, starts at 1 |
| frame length | 4 | bounded encoded HPTA frame length |
| frame | variable | exact HPTA V1/V2 frame selected by the session |
| tag | 32 | HMAC-SHA-256 over domain separator and all preceding record bytes |

The MAC covers the exact frame bytes, session identity and sequence. Verification uses a constant-work byte comparison. Wrong session, sequence, length, format, tag or admitted frame poisons the connection-local authenticated session. Sequence state is never reset in place; reconnect and renegotiate instead.

`SessionMacKey` is exactly 32 bytes, rejects the all-zero value and redacts its debug representation. Key creation, storage, rotation and destruction remain responsibilities of the authenticated transport/secret owner. Keys must not enter generic evidence, logs, prompts or learning artifacts.

## 4. Security boundaries and nonclaims

HPTA V1 and V2 digests remain unkeyed integrity digests. V2 prevents undetected metadata drift when the expected digest is trusted, but it does not authenticate a producer. Producer identity becomes meaningful only after the transport channel and session transcript are authenticated and the frozen policy admits that producer.

The authenticated record layer proves possession of the session MAC key and ordered record integrity. It does not mint final-use authority, authorize a domain effect, replace revocation checks, or prove that a remote operator accepted deployment.

A transport that already supplies equivalent authenticated encryption and replay ordering may omit the HPTM wrapper, but it must still construct the same negotiation transcript and bind the selected session posture to that transport channel. That equivalence must be documented and independently reviewed.

## 5. Error and resource semantics

New production-facing errors carry the session identifier and, where known, the byte offset. Length failures report actual and maximum or expected values. Registry failures identify the rejected schema, producer, role or capability mask. These diagnostics are safe identifiers and bounds; secret key bytes and payload contents are not included.

The existing `StreamingDecoder` remains header-first, bounded and terminally poisoned after protocol/resource failure. The authenticated layer additionally caps records at `MAX_AUTHENTICATED_RECORD_BYTES` and verifies record bounds before frame decode.

## 6. Required qualification evidence

Lifecycle state is generated by `scripts/platform_wire_status.py` and fails closed:

- **Designed** requires the normative and module design documents.
- **Implemented** additionally requires all declared native source components, including frozen policy and secure session modules.
- **Qualified** additionally requires passing, source-consistent receipts for exact head, deterministic synthetic merge and the named target host.
- **Released** additionally requires a separate release receipt.

Exact-head and synthetic-merge receipts are produced by the Lane A workflow. Target-host evidence must be produced on the selected host profile; an Ubuntu-hosted generic runner is not target-host evidence. Independent reviewer and operations acceptance cannot be self-attested by the implementation author or generated merely because tests passed.

## 7. Required tests

The native suite must cover:

- registry entry and subject ceilings;
- snapshot stability across registration order;
- conflicting policy rejection;
- selected-version, effective-capability, producer and role denial;
- envelope-coupled typed round trips;
- transcript mismatch and channel-binding bounds;
- frame tamper, MAC tamper, replay, sequence gap and cross-session replay;
- terminal poison behavior;
- bidirectional Rust/Python framing and strict payload rejection;
- exact-head, synthetic-merge and target-host receipt schema validation.

Any change to the HPTM layout, transcript material, registry digest, sequence semantics or MAC algorithm requires a new version and cannot reinterpret V1 bytes in place.
