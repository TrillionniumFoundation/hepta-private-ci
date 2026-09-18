# HPTA wire envelope V2

## Current executable contract

HPTA V2 is the metadata-integrity successor to frozen V1. It preserves the same
field offsets and bounds so a transport can inspect a fixed 54-byte header
before body allocation.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII HPTA, exact |
| 4 | 2 | version | unsigned big-endian, exactly 2 |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | integrity digest | raw Digest32 of the V2 canonical preimage |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The digest is SHA-256 over this exact byte sequence:

HPTA-FRAME-V2\0 || HPTA || u16be(2) || u16be(schema_length) ||
u16be(producer_length) || u64be(generation) || u32be(payload_length) ||
schema || producer || payload

The on-wire digest field is excluded from its own preimage. Any change to
schema, producer, generation, payload or encoded lengths therefore changes the
expected digest.

## Public symbols and source bindings

WireEnvelopeV2 and WIRE_VERSION_V2 are implemented in
codex-rs/hepta-wire/src/v2.rs. Version dispatch lives in protocol.rs. The
independent 59-byte vector is recorded in HPTA_V2_CONFORMANCE.json and repeated
by the V2 source test.

## Durability and activation

V2 is stateless and library-only. Its integrity digest grants no authority and
is not an acknowledgement. Production activation remains the responsibility of
the owning caller and transport.

## Target-only design

Authenticated negotiation transcripts, transport-specific deadlines, generated
foreign-language SDKs and product schema population remain integration work.
Future wire versions must use new version values and frozen vectors.

## Known limits and non-claims

The V2 digest is not a MAC or signature. A party able to replace the full frame
can recompute the digest. Authentication and anti-downgrade properties therefore
require an authenticated transport/session or an independently authenticated
transcript.

V2 does not encrypt or compress payloads and does not perform domain schema
validation by itself. SchemaRegistry is the separate admission layer.

## Verification

Tests freeze an independent 59-byte vector, round-trip V2 exactly and reject
same-length valid-identifier mutations to schema/producer, generation changes
and payload corruption. Stream tests verify bounded header-first allocation.

The live qualification test has Python independently build V2 bytes, send them
over TCP and Rust perform frame decode, schema admission and typed loading.

## Integration prerequisites

Peers must share the V2 conformance vector and canonical digest preimage.
Negotiation must explicitly select V2 whenever FullFrameIntegrity is required.
Consumers must separately authenticate their transport/session and apply schema
admission before domain use.
