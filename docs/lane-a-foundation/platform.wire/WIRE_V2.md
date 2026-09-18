# HPTA wire envelope V2

## Current executable contract

HPTA V2 is an additive wire version. HPTA V1 remains immutable and is not
reinterpreted. V2 keeps the same fixed-width header positions as V1 so a
bounded transport can learn the total frame size after 54 bytes, but the
32-byte field at offset 18 has V2 semantics: it is a domain-separated digest
over the complete semantic frame rather than a payload-only digest.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian, exactly `2` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | frame digest | SHA-256 of the V2 canonical digest preimage below |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The total frame length is exactly
`54 + schema_length + producer_length + payload_length`. Truncation and
trailing bytes reject.

The V2 digest preimage is the exact byte concatenation:

`"HPTA-WIRE-V2\0" || magic || version_be || schema_len_be || producer_len_be || generation_be || payload_len_be || schema || producer || payload`

The 32-byte digest field itself is excluded to avoid circularity. The domain
prefix prevents a digest produced for another operation from being interpreted
as a V2 frame digest.

The digest binds protocol metadata and payload, but it is **not** a MAC,
signature, identity assertion or authority token. Authentication still belongs
to the owning transport/session or an independently verified signature.

## Public symbols and source bindings

`WireEnvelopeV2` and `WireV2Error` are implemented in
`codex-rs/hepta-wire/src/v2.rs`. The independent 59-byte vector is frozen in
`HPTA_V2_CONFORMANCE.json` and repeated by the V2 boundary test.

Version/capability negotiation is separate from decoding. A decoder never
accepts an unknown version by guessing compatibility.

## Durability and activation

The codec is stateless and library-only. Decode success does not mean schema
admission, authorization, dispatch acknowledgement or terminal product success.

## Target-only design

Cryptographic peer authentication, signatures/MACs, distributed schema
registry publication, production caller composition and deployment activation
remain outside this codec. Those capabilities must not be inferred from the
presence of a SHA-256 frame digest.

## Known limits and non-claims

V2 does not add encryption, compression, retries, authority or domain-specific
payload semantics. Schema admission is a separate bounded layer in
`schema.rs`; the envelope only carries the schema identifier and bytes.

## Verification

Tests freeze the V2 vector, mutate schema/producer/generation/payload bytes,
exercise exact maximum bounds, negotiate required features fail-closed, stream
frames incrementally, and run generated arbitrary-byte/property coverage.
A Rust producer also sends a V2 frame over loopback TCP to a Python runtime
that independently parses the frame and recomputes the V2 digest.

## Integration prerequisites

Peers must negotiate an explicitly common version before decoding session
traffic. If either side requires `FullFrameDigest`, negotiation must not select
V1. Consumers must separately admit the schema and decode the domain payload.
