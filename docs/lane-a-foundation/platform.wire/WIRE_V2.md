# HPTA wire envelope V2

## Current executable contract

HPTA V2 is a bounded, transport-neutral envelope version implemented by
`WireEnvelopeV2`. It exists alongside the immutable V1 format; V1 bytes are
not reinterpreted.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian, exactly `2` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | complete-frame digest | SHA-256 digest defined below |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The complete input length is exactly
`54 + schema_length + producer_length + payload_length`. Trailing bytes and
truncation reject. Schema and producer must be UTF-8 accepted by
`StableId::new`.

### Complete-frame digest material

The stored digest is SHA-256 over this exact concatenation, with no padding:

1. ASCII/domain bytes `HPTA-FRAME-V2` followed by one NUL byte;
2. magic `HPTA`;
3. version as big-endian u16 (`2`);
4. schema length as big-endian u16;
5. producer length as big-endian u16;
6. generation as big-endian u64;
7. payload length as big-endian u32;
8. schema bytes;
9. producer bytes;
10. payload bytes.

The digest field itself is not included in the digest material. This binds all
semantic V2 metadata and the payload while avoiding recursive hashing.

## Public symbols and source bindings

`WireEnvelopeV2::new`, `encode`, `decode`, accessors and
`complete_frame_digest` live in
`codex-rs/hepta-wire/src/integrity.rs`. `WireFrame::decode` is the explicit
V1/V2 dispatcher. Negotiation is separate in `negotiation.rs`.

The independent 59-byte vector is recorded in
[HPTA_V2_CONFORMANCE.json](HPTA_V2_CONFORMANCE.json).

## Durability and activation

The V2 codec is stateless and library-only. Decode success has no authority or
effect semantics.

## Target-only design

A keyed MAC, signature or authenticated transport binding remains target-owned
outside this codec. Future wire versions require a new numeric version and new
frozen vectors; V2 bytes cannot change meaning in place.

## Known limits and non-claims

The V2 digest is unkeyed SHA-256. It is complete-frame integrity/fault-detection,
not source authentication. An adversary able to rewrite the frame and recompute
SHA-256 can produce another internally consistent frame. Production consumers
that require adversarial tamper resistance must bind the encoded frame to an
authenticated transport or owning cryptographic authorization mechanism.

V2 does not define encryption, compression, retries, domain payload semantics or
authority tokens.

## Verification

`protocol_tests.rs` mutates schema, producer, generation and payload bytes and
requires `FrameDigestMismatch`. It also exercises V2 streaming reads and
deterministic fuzz/property round trips.

`cross_language_wire_fault.rs` independently reproduces the digest algorithm
in Python, validates Rust-produced V2 bytes, constructs a Python reply frame and
requires Rust to decode that reply exactly.

## Integration prerequisites

Sessions supporting multiple versions negotiate with `negotiate` before
selecting a codec. A caller that requires complete-frame digest uses
`NegotiationPolicy::require_complete_frame_digest()`; a peer that cannot
satisfy V2 plus the critical feature rejects rather than silently falling back
to V1.

After V2 framing succeeds, callers still perform schema admission, typed domain
decoding, transport authentication and authority checks at their owning
boundaries.
