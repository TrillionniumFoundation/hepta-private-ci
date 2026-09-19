# HPTA wire envelope V2

## Current executable contract

HPTA V2 preserves the V1 framing shape but changes the digest semantics so that
the digest binds every semantic frame field. V1 bytes and meanings are
unchanged.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian, exactly `2` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | frame digest | raw SHA-256 digest defined below |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The complete input length must equal
`54 + schema_length + producer_length + payload_length`. Trailing bytes and
truncation reject. Schema and producer are UTF-8 strings accepted only by
`StableId::new`.

## Canonical frame digest

The V2 digest is SHA-256 over the exact concatenation below:

1. ASCII domain bytes `HPTA-WIRE-V2` followed by one NUL byte.
2. magic bytes.
3. version as the two encoded big-endian bytes.
4. schema length as the two encoded big-endian bytes.
5. producer length as the two encoded big-endian bytes.
6. generation as the eight encoded big-endian bytes.
7. payload length as the four encoded big-endian bytes.
8. schema bytes.
9. producer bytes.
10. payload bytes.

The digest field itself is excluded from its own preimage.

This construction detects mutation of schema, producer, generation, payload
length or payload in addition to payload corruption. It is an **unkeyed
digest**, not a MAC, signature, identity proof or authorization token. On an
untrusted transport, the owning transport/session must authenticate the
negotiation transcript and the encoded frame or bind them into an authenticated
channel.

## Public symbols and source bindings

`WireEnvelopeV2::new`, `encode`, `decode`, accessors and
`WireV2Error` are implemented in
`codex-rs/hepta-wire/src/envelope_v2.rs`. Multi-version dispatch is in
`src/frame.rs`.

## Frozen conformance vector

For schema `s`, producer `p`, generation `1` and payload `010203`:

- frame digest:
  `24c225cf242fbef3f1428af4827091793d13c051c4f01979a47633f0729f1d5e`
- frame length: `59`
- frame SHA-256:
  `5fde1073e0728e98693400a124c6c91332848af5a233562a8ff3ba11460fa43b`
- frame hex:
  `48505441000200010001000000000000000124c225cf242fbef3f1428af4827091793d13c051c4f01979a47633f0729f1d5e000000037370010203`

The same vector is frozen in `HPTA_V2_CONFORMANCE.json` and native tests.

## Compatibility and negotiation

V2 is selected only by explicit HPTN negotiation or by a caller that has
already bound version 2 out of band. Unknown versions remain fail-closed.
Security-sensitive callers requiring metadata binding must require the
`METADATA_BOUND_DIGEST` capability so a V1-only peer cannot silently
downgrade that property.

## Schema and streaming layers

Framing does not interpret a domain payload. `SchemaRegistry` admits a stable
schema identity, compatible wire-version range and payload bound before a
`PayloadCodec` performs typed semantic validation. `StreamingDecoder`
checks the fixed 54-byte header before accepting the advertised body and caps
connection-local buffering at two maximum-size frames.

## Non-claims

Successful V2 decode proves only canonical framing and unkeyed frame-digest
consistency. It does not prove transport authentication, authorization,
dispatch acknowledgement, external effect success, deployment qualification or
operator acceptance.
