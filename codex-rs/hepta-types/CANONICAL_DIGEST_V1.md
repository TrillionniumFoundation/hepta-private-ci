# Canonical digest V1

`canonical_digest_v1` is the platform-owned deterministic commitment format for
shared typed contracts. Raw `Digest32::of_bytes` remains a cryptographic
primitive; protocol commitments use this encoding instead of ad-hoc byte
concatenation.

## Envelope

The exact byte sequence is:

1. ASCII magic `HPTC`.
2. big-endian `u16` encoding version, exactly `1`.
3. big-endian `u16` domain length plus UTF-8 domain
   `hepta.platform.types.canonical-digest.v1`.
4. big-endian `u16` type-ID length plus a canonical namespaced `StableId`.
5. big-endian nonzero `u32` schema version.
6. big-endian `u32` field count.
7. fields sorted by UTF-8 field-name bytes. Each field is a `u16`-length name
   followed by one typed value.

Field and map labels are lowercase ASCII alphanumeric with internal `.`, `_`,
`-` or `:`, bounded to 128 bytes. Duplicate fields and map keys reject.
Arrays retain caller order. Maps sort keys by their UTF-8 bytes.

## Value tags

| Tag | Meaning | Payload |
|---|---|---|
| `01` | bool | one byte, `00` or `01` |
| `02` | u64 | 8-byte big-endian |
| `03` | u128 | 16-byte big-endian |
| `04` | i64 | 8-byte two's-complement big-endian |
| `05` | bytes | u32 byte length + bytes |
| `06` | UTF-8 text | u32 byte length + bytes; NUL rejects |
| `07` | Digest32 | exactly 32 bytes |
| `08` | StableId | u16 byte length + exact accepted bytes |
| `09` | array | u32 item count + values in semantic order |
| `0a` | map | u32 entry count + canonical key/value entries |

The complete encoding is capped at 256 KiB, each container at 4096 items and
nesting at 16 levels. No Unicode normalization, locale folding, host endianness,
map insertion order or process-global registry participates in the encoding.

## Conformance

`CANONICAL_V1_CONFORMANCE.json` freezes exact bytes and SHA-256 output. Rust
unit tests plus independent Python and TypeScript oracle implementations must
all reproduce every vector byte-for-byte. CI executes both external oracles on
the exact source HEAD and deterministic synthetic merge candidate.

Changing any tag, framing rule, ordering rule, domain, limit or normalization
rule requires a new encoding version. V1 bytes are never reinterpreted in place.
