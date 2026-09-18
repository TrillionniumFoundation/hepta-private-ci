# HPTA wire envelope V2

## Current executable contract

HPTA V2 preserves the bounded fixed-header shape of V1 while changing the
embedded 32-byte digest semantics so metadata and payload are one integrity
unit. V1 bytes and meanings remain immutable.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian, exactly `2` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | frame digest | domain-separated SHA-256 described below |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The frame digest is SHA-256 over this exact preimage:

```text
"hepta.platform.wire.hpta.v2.frame-digest\0"
|| "HPTA"
|| u16_be(2)
|| u16_be(schema_length)
|| u16_be(producer_length)
|| u64_be(generation)
|| u32_be(payload_length)
|| schema
|| producer
|| payload
```

The digest field itself is excluded from the preimage. Any change to version,
lengths, schema, producer, generation or payload therefore invalidates the
embedded digest.

## Security boundary

The V2 frame digest is **not a MAC, signature or authentication mechanism**.
An active attacker who can rewrite the frame can also recompute an unkeyed
SHA-256 digest. Transport/session owners that need tamper resistance must
authenticate the complete encoded frame and the negotiation binding digest.

## Negotiation

`negotiate` selects the highest explicitly common version satisfying every
required capability. Requiring `MetadataBoundIntegrity` excludes V1. The
returned negotiation binding digest covers the role-ordered initiator offer,
responder offer, required capabilities and selected version. The binding digest
must be authenticated by the owning session/transport when downgrade resistance
is required.

## Streaming

`read_envelope` reads and validates the 54-byte fixed header before allocating
the bounded body. Unsupported versions, invalid identity lengths, zero
generation and payloads outside 1..=1,048,576 reject before body allocation.
Exactly one frame is consumed per call.

## Frozen vector

For schema `s`, producer `p`, generation `1`, payload `010203`:

- frame digest:
  `420cbaa9b4717b3099a3ac45a1545b41363a3511eb582afa20f6107e916c4d2d`
- frame length: `59`
- frame SHA-256:
  `47c45481215d23032b6e579c22adace592e745881a0ca6bb2ab6b49363ec4ad8`
- frame hex:
  `485054410002000100010000000000000001420cbaa9b4717b3099a3ac45a1545b41363a3511eb582afa20f6107e916c4d2d000000037370010203`

## Non-claims

V2 does not itself perform schema admission, domain payload validation,
authorization, encryption, compression, retry or effect acknowledgement. Those
remain separate boundaries.
