# HPTA wire envelope V1

## Current executable contract

`platform.wire` implements exactly one immutable, transport-neutral HPTA
envelope version. It does not negotiate versions.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian, exactly `1` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | payload digest | raw `Digest32` of payload bytes |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The complete input length must equal
`54 + schema_length + producer_length + payload_length`. Trailing bytes and
truncation reject. Schema and producer are UTF-8 strings accepted only by
`StableId::new`. The decoder verifies the digest against the borrowed payload
slice before allocating the owned payload copy.

## Public symbols and source bindings

`WireEnvelope::new`, `encode`, `decode`, accessors, `WireError` and
`MAX_WIRE_PAYLOAD_BYTES` are implemented in
`codex-rs/hepta-wire/src/envelope.rs`. The independent 59-byte vector is
recorded both in `boundary_tests.rs` and `HPTA_V1_CONFORMANCE.json`.

## Durability and activation

The codec is stateless and library-only. Successful decode is not transport
acceptance, authorization, dispatch acknowledgement or external terminal
success.

## Target-only design

V1 itself intentionally remains a fixed codec and never negotiates or accepts
another version. Session negotiation, bounded stream framing and explicit
multi-version dispatch are implemented as separate library layers so V1 bytes
and meanings remain frozen. HPTA V2 is a distinct version documented in
`WIRE_V2.md`.

Authenticated/keyed protection remains outside V1 and outside the unkeyed V2
digest. Future versions must use a new version value and frozen vectors; V1
bytes and meanings cannot be reinterpreted in place.

## Known limits and non-claims

V1 has no authority token, encryption, compression, retry state or domain
payload validation. Its embedded digest binds only payload bytes. Callers that
need producer/schema/generation integrity must bind the complete frame in their
own domain-separated operation or signature digest.

## Verification

Boundary tests cover every truncation, maximum identities/payload/generation,
bad headers, malformed identities, trailing bytes, payload corruption and the
independent frozen frame. `envelope_tests.rs` also freezes the deliberate V1
non-claim that a valid payload digest does not authenticate schema metadata;
changing a valid schema byte can still decode when payload bytes are unchanged.

## Integration prerequisites

Producers and consumers must share the exact V1 conformance vector, validate the
domain payload separately and reject unknown versions. A multi-version session
must negotiate outside the V1 codec; callers that require metadata-bound frame
integrity must require HPTA V2 rather than weakening V1 compatibility. A
successful re-encode must never be treated as effect acknowledgement.
