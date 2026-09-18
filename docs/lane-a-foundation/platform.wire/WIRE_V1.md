# HPTA wire envelope V1

## Current executable contract

HPTA V1 remains an immutable, transport-neutral compatibility format. The
platform.wire module also implements V2 and module-level negotiation, but V1
bytes and meanings are frozen and are never reinterpreted.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII HPTA, exact |
| 4 | 2 | version | unsigned big-endian, exactly 1 |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | payload digest | raw Digest32 of payload bytes |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The complete input length must equal
54 + schema_length + producer_length + payload_length. Trailing bytes and
truncation reject. Schema and producer are UTF-8 strings accepted only by
StableId::new. The decoder verifies the payload digest before allocating the
owned payload copy.

## Public symbols and source bindings

WireEnvelope::new, encode, decode, accessors, WireError,
WIRE_VERSION_V1 and MAX_WIRE_PAYLOAD_BYTES are implemented in
codex-rs/hepta-wire/src/envelope.rs. The independent 59-byte vector is recorded
both in boundary_tests.rs and HPTA_V1_CONFORMANCE.json.

WireFrame in protocol.rs dispatches V1 without changing its semantics.

## Durability and activation

The codec is stateless and library-only. Successful decode is not transport
acceptance, authorization, dispatch acknowledgement or external terminal
success.

## Target-only design

No new behavior is added inside V1. New integrity semantics use V2. The module
now has bounded streaming and negotiation helpers, but authenticated negotiation
transcript binding and production transport composition remain integration work.

A future version must use a new version value and frozen vectors; V1 bytes and
meanings cannot change in place.

## Known limits and non-claims

V1 has no authority token, encryption, compression, retry state or domain
payload validation. Its embedded digest binds only payload bytes. Metadata
integrity must use V2 or an independently authenticated complete-frame/session
binding.

The V1 digest is not a MAC or signature.

## Verification

Boundary tests cover every truncation, maximum identities/payload/generation,
bad headers, malformed identities, trailing bytes, payload corruption and the
independent frozen frame. WireFrame property-style tests also round-trip V1
without changing its canonical bytes.

## Integration prerequisites

A producer or consumer retaining V1 must share the exact V1 conformance vector,
validate the domain payload separately and reject unsupported versions. A
caller requiring metadata integrity must require FullFrameIntegrity during
negotiation and therefore select V2 rather than mutating V1.
