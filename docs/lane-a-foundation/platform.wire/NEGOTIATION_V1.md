# HPTN negotiation hello V1

## Current executable contract

HPTN is the transport-neutral pre-frame negotiation record used by
`platform.wire`. It advertises raw wire-version numbers and explicit
capability bits. It does not reinterpret an unknown wire version and it does
not make negotiation an authorization boundary.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTN`, exact |
| 4 | 2 | negotiation format | unsigned big-endian, exactly `1` |
| 6 | 1 | version count | 1 through 16 |
| 7 | 1 | reserved | exactly zero |
| 8 | 8 | capabilities | unsigned big-endian known-bit mask |
| 16 | variable | wire versions | strictly increasing unsigned big-endian u16 values |

The complete input length is `16 + 2 * version_count`. Version zero,
duplicates, descending versions, unknown capability bits, trailing bytes and
truncation reject.

## Capability bits

| Bit | Name | Meaning |
| ---: | --- | --- |
| 0 | `METADATA_BOUND_DIGEST` | peer implements HPTA V2 metadata-bound frame digest |
| 1 | `SCHEMA_ADMISSION` | peer supports explicit schema admission before typed decode |
| 2 | `STREAM_DECODING` | peer supports bounded incremental stream framing |

No other bits are currently assigned.

## Selection algorithm

`negotiate(local, remote, required)` considers only wire versions implemented
by the local library, in descending preference order. A version is selected
only when it is explicitly present in both offers and the common capability set
contains both the caller's required capabilities and the capabilities required
by that wire version.

HPTA V2 intrinsically requires `METADATA_BOUND_DIGEST`. A caller that also
requires schema admission must pass both requirements. If the only common
version cannot satisfy the required properties, negotiation fails rather than
silently falling back.

A future peer may advertise an unknown raw version number. An older
implementation preserves that advertisement as data but never invents semantics
for it and never selects it.

## Frozen current offer

The current implementation advertises versions `1, 2` and capability mask
`0x0000000000000007`.

- length: `20`
- SHA-256:
  `350b41f9ed09225a2fb6262743489293681061b520dbd2601c24665664dba994`
- hex:
  `4850544e00010200000000000000000700010002`

The same vector is frozen in `HPTN_V1_CONFORMANCE.json` and native tests.

## Authentication requirement

The HPTN hello is not authenticated by itself. Where downgrade or peer
impersonation matters, the transport/session owner must authenticate the
negotiation transcript together with the subsequent encoded HPTA frame, for
example by running HPTN inside an authenticated secure channel or binding the
transcript and frame into the channel's authenticated transcript.

## Recovery

Connection-local negotiation state is discarded on disconnect. A new
connection negotiates again. Negotiation success is not an effect
acknowledgement and must not cause an uncertain external effect to be replayed.
