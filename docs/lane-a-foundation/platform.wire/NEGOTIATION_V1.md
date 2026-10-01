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

`NegotiatedWire.capabilities` contains only capabilities effective for the
selected version. `common_advertised_capabilities` separately records the raw
intersection for diagnostics, so a V1 selection cannot be mistaken for a V2
metadata-bound session merely because both peers advertised that capability.

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

## Session binding

After negotiation, a live byte stream uses `NegotiatedStreamingDecoder`. A
frame whose HPTA version differs from the selected HPTN version terminates and
poisons that connection-local decoder. The generic `decode_frame` function is
an offline multi-version parser and is not a replacement for session binding.
A fresh connection negotiates again.

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

### Header-first session rejection

`NegotiatedStreamingDecoder` applies the selected frame version when the fixed
54-byte HPTA header is complete, before reserving or copying its advertised
body. A supported but unselected version returns `VersionMismatch` even when
the peer sends no body. Completed prefix frames are returned in the same batch;
all partial bytes are discarded and subsequent feeds retain the terminal error.
This is connection policy, not authentication: transport/session owners still
bind the actual peer and transcript using their existing security boundary.

## Native session result

`NegotiatedWire` is constructed only by `negotiate`. Its read-only `version()`,
`capabilities()`, `common_advertised_capabilities()` and
`required_capabilities()` accessors distinguish effective session properties
from peer advertisements. No public field mutation or DTO deserialization can
replace the selected version or remove the caller's required capabilities.
This native API constraint neither authenticates the HPTN transcript nor grants
execution authority; those checks remain at the existing security owner.
