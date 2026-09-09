# HPTA wire envelope V1

## Current executable contract

`platform.wire` implements exactly one immutable envelope version. It does not
currently negotiate versions.

| Offset | Width | Field | Encoding and invariant |
| ---: | ---: | --- | --- |
| 0 | 4 | magic | ASCII `HPTA`, exact |
| 4 | 2 | version | unsigned big-endian integer, exactly `1` |
| 6 | 2 | schema length | unsigned big-endian, 1 through 128 |
| 8 | 2 | producer length | unsigned big-endian, 1 through 128 |
| 10 | 8 | generation | unsigned big-endian, nonzero |
| 18 | 32 | payload digest | raw `Digest32` of payload bytes |
| 50 | 4 | payload length | unsigned big-endian, 1 through 1,048,576 |
| 54 | variable | body | schema bytes, producer bytes, payload bytes |

The complete input length must equal `54 + schema_length + producer_length +
payload_length`; trailing bytes and truncation reject. Schema and producer are
UTF-8 strings accepted only by `StableId::new`. The decoder verifies the digest
against the borrowed payload slice before allocating the owned payload copy.

The decoder distinguishes truncated input, bad magic, unsupported version,
identity length/encoding, zero generation, payload length, total-length mismatch
and digest mismatch. A transport acceptance or a successful re-encode is not an
external-effect acknowledgement.

## Target-only design

Version negotiation, a streaming decoder and multi-version compatibility
adapters are target-only. A future version must use a new version value and a
new frozen vector; V1 bytes and meanings cannot be reinterpreted in place.

## Known limits and non-claims

V1 has no embedded authority token, compression, encryption, transport retry,
domain schema validation or connection state. The payload digest binds only the
payload bytes; callers must separately bind schema, producer, generation and
operation semantics where required.

## Verification

`boundary_tests.rs` covers every truncation, maximum identity/payload/generation,
malformed headers and identities, payload corruption and an independently
frozen 59-byte V1 vector. Fuzzing and cross-language vectors remain additional
qualification work rather than implied current evidence.
