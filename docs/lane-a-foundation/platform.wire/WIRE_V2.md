# HPTA wire envelope V2

## Format

HPTA V2 is a new immutable wire version. It does not reinterpret HPTA V1.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian, exactly `2` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | payload digest | SHA-256 of payload bytes |
| 50 | 32 | frame digest | domain-separated digest defined below |
| 82 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 86 | variable | body | schema bytes, producer bytes, payload bytes |

The complete input length must equal
`86 + schema_length + producer_length + payload_length`. Trailing bytes and
truncation reject. Schema and producer are UTF-8 strings accepted only by
`StableId::new`.

## Complete semantic frame digest

The V2 frame digest is:

`SHA-256("HPTA-FRAME-V2\0" || magic || version || schema_length || producer_length || generation || payload_digest || payload_length || schema || producer || payload)`

All integer terms use the exact big-endian wire encoding. The frame-digest field
itself is excluded, so there is one canonical digest input.

The decoder verifies the payload digest and frame digest before allocating the
owned payload copy. Metadata changes to schema, producer, generation, lengths
or version therefore invalidate the stored frame digest.

This digest is integrity binding, not authentication. Because SHA-256 is
unkeyed, an attacker able to replace the entire unauthenticated frame can also
recompute it. Use authenticated transport/session protection, or obtain the
expected frame digest through an authenticated channel and call
`WireEnvelopeV2::decode_bound`.

## Negotiation

`negotiate(local_versions, remote_versions, critical_features)` selects the
highest explicitly common implemented version from HPTA V2 then HPTA V1.
Unknown versions are never guessed or parsed as a compatible framing.

V2 advertises these library capabilities:

- `hpta.frame-digest.v2`
- `hpta.schema-admission.v1`
- `hpta.streaming-frames.v1`

If a caller declares a critical capability and the only common version lacks
it, negotiation rejects rather than silently downgrading.

## Schema admission and typed payloads

`SchemaRegistry` binds exact stable schema IDs to:

- required top-level fields;
- optional top-level fields;
- unknown-field policy;
- a per-schema payload byte limit.

JSON admission also enforces nesting <= 32 and at most 1024 total object fields
before typed deserialization. `TypedWirePayload` plus `encode_typed` provide
canonicalized JSON DTO encoding. This layer remains transport/domain neutral and
does not deserialize permission-bearing runtime authority.

## Streaming

`FramedReader<R: Read>` reads six prefix bytes, resolves only implemented
versions, reads the corresponding fixed header, validates identity/payload
bounds, computes the exact frame size and only then allocates the bounded body.
It can consume concatenated V1/V2 frames. Read deadlines and reconnect policy
belong to the transport owner.

## Frozen vector

The independent vector in `HPTA_V2_CONFORMANCE.json` uses
`schema=s`, `producer=p`, `generation=1`, `payload=010203` and has an
exact frame length of 91 bytes. Rust tests compare both encode and decode
against those frozen bytes.
