# HPTA wire envelope V2

## Current executable contract

HPTA V2 is the authenticated-transport-ready successor to the immutable V1
codec. V1 bytes and meanings are unchanged. V2 uses the same compact field
layout so bounded framing remains simple, but the 32-byte digest changes scope
from payload-only to all protocol metadata plus body bytes.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian, exactly `2` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | frame digest | SHA-256 of the canonical V2 digest preimage below |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The complete input length must equal
`54 + schema_length + producer_length + payload_length`. Trailing bytes and
truncation reject. Schema and producer are UTF-8 strings accepted only by
`StableId::new`.

### Canonical frame-digest preimage

The V2 digest is:

`SHA-256("hepta.hpta.v2.frame\\0" || magic || version || schema_length || producer_length || generation || payload_length || schema || producer || payload)`

All numeric fields in the preimage use the exact big-endian wire encoding. The
digest field itself is omitted to avoid self-reference. As a result, changing a
valid schema, producer, generation, declared length or payload without updating
the digest fails closed.

The frame digest is an integrity/checking primitive, **not an authenticator**.
An active attacker who can replace the frame can also recompute an unkeyed
SHA-256 value. Production transports therefore authenticate the complete frame
or the domain-separated `transport_binding_digest()` with their secure-channel,
MAC or signature mechanism.

## Public symbols and source bindings

- `WireEnvelopeV2`, `WireV2Error`, `V2_WIRE_VERSION` —
  `codex-rs/hepta-wire/src/v2.rs`.
- `NegotiationOffer`, `VersionOffer`, `CapabilitySet`, `NegotiatedWire`,
  `negotiate` — `codex-rs/hepta-wire/src/negotiation.rs`.
- `SchemaRegistry`, `WirePayload`, `PayloadCodecError`, `SchemaError` —
  `codex-rs/hepta-wire/src/schema.rs`.
- `WireFrameDecoder`, `DecodeProgress`, `DecodedFrame`, `FrameDecodeError` —
  `codex-rs/hepta-wire/src/stream.rs`.

`codex-rs/hepta-codex-adapter/src/wire.rs` is the first named product-source
composition. It serializes `CodexOperationIntent` through a registered typed
schema and requires negotiated V2 full-frame integrity plus schema admission.
This composition is source evidence, not deployment or external acceptance.

## Version and capability negotiation

Negotiation is separate from frame decoding. Each side supplies an explicit set
of supported versions and capabilities plus required capabilities. The
negotiator selects the highest common version whose capability intersection
satisfies both sides' requirements. It never interprets an unknown version.

`NegotiatedWire::transcript_digest()` canonically binds both offers and the
selected result. A secure session authenticates this digest to detect downgrade
or offer substitution. The digest alone is not authentication.

Current capability bits are:

- `FULL_FRAME_INTEGRITY`
- `SCHEMA_ADMISSION`
- `STREAMING_DECODE`

A caller that requires V2 integrity includes `FULL_FRAME_INTEGRITY` in its
required capabilities; a V1-only peer then fails negotiation instead of
silently downgrading.

## Schema admission and typed protocol serialization

`SchemaRegistry` is an admission layer above framing. A schema registration
binds an exact `StableId`, an explicit set of allowed wire versions, a stricter
per-schema payload ceiling and a validator. `WirePayload` is the typed codec
contract owned by the domain defining the schema.

A `WirePayload` decoder must reject missing required fields, unknown critical
fields and non-canonical values. The wire crate does not invent domain schema
semantics. Unknown schemas, disallowed wire versions, over-bound payloads and
validator failures reject before typed values are returned.

## Incremental decoder

`WireFrameDecoder` consumes at most one frame per call. It buffers only the
fixed 54-byte header until magic, version, identity lengths, generation and
payload length pass admission. Only then can it extend the buffer to the exact
bounded frame length. If the supplied chunk also contains another frame, the
returned `consumed` count leaves the remainder with the caller rather than
buffering an unbounded queue.

The decoder accepts V1 and V2 and rejects every unknown version. Disconnect or
transport timeout discards decoder state; deadline policy remains owned by the
transport profile.

## Known limits and non-claims

- V2 does not carry an authority token, encryption key, retry state or effect
  acknowledgement.
- Frame integrity is unkeyed; active-attacker resistance requires authenticated
  transport/session binding.
- Schema validators are registered by product/domain owners; `platform.wire`
  does not own application semantics.
- Version negotiation is an in-process/session API. A transport must define how
  offers and the authenticated transcript digest are exchanged.
- Product-source composition does not imply deployed production activation,
  operator acceptance, promotion or release.

## Verification

The source tests cover V2 round trips, schema/producer/generation/payload
mutation, downgrade prevention, typed schema admission, unknown schemas,
non-canonical typed payloads, incremental header admission, oversized-length
rejection, every streaming chunk size and deterministic arbitrary-byte
no-panic regression.

`codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs` sends
raw V2 bytes through a real Rust-to-Python process pipe. The Python runtime
independently recomputes the V2 digest, admits the exact schema, loads the typed
JSON object and rejects metadata/payload faults.

The frozen independent vector is
`docs/lane-a-foundation/platform.wire/HPTA_V2_CONFORMANCE.json`.

## Integration prerequisites

A product session that requires V2 security properties must:

1. negotiate an explicit common version and required capabilities;
2. authenticate the negotiation transcript digest with its secure channel;
3. use a registered schema and domain-owned typed decoder;
4. authenticate the complete V2 frame or its transport-binding digest;
5. keep effect acknowledgement and retry semantics outside the codec.
