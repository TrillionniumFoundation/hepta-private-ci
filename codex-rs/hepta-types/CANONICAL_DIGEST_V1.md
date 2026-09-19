# Canonical digest V1

`canonical_digest_v1` is the platform.types contract for deterministic,
domain-separated protocol digests. It is distinct from `Digest32::of_bytes`,
which remains a raw SHA-256 primitive for callers that already own a frozen byte
representation.

## Domain and framing

Every V1 encoding begins with the exact bytes
`HEPTA-CANONICAL-DIGEST-V1\0`, followed by:

1. a big-endian `u16` type-ID byte length and the exact StableId UTF-8 bytes;
2. a nonzero big-endian `u32` schema version;
3. a big-endian `u16` top-level field count;
4. top-level fields sorted lexicographically by UTF-8 field-name bytes.

Each field contains its big-endian `u16` name length, name bytes, one type tag
and the canonical value encoding. Duplicate field names reject.

## Value tags

- `0x01`: opaque bytes, `u32` byte length then bytes.
- `0x02`: UTF-8 text, `u32` byte length then exact supplied bytes.
- `0x03`: unsigned `u64`, big endian.
- `0x04`: signed two's-complement `i64`, big endian.
- `0x05`: bool, one byte (`0` or `1`).
- `0x06`: `Digest32`, exactly 32 bytes.
- `0x07`: array, `u32` item count followed by items in semantic order.
- `0x08`: map, `u32` entry count followed by entries sorted
  lexicographically by UTF-8 key bytes. Each key is framed with a big-endian
  `u16` byte length. Duplicate keys reject.

V1 performs no case folding and no Unicode normalization. Producers that require
normalization must name it as a separate registered contract and bind its digest.

## Bounds

The complete canonical encoding is bounded to 256 KiB. Top-level fields are
bounded to 256, arrays/maps to 4096 items, nesting to eight levels, field names
to 128 bytes and map keys to 256 bytes. Oversize or ambiguous inputs reject;
there is no truncation.

## Frozen cross-language vector

`docs/lane-a-foundation/platform.types/CANONICAL_DIGEST_V1.json` freezes an
independent conformance vector. Rust unit tests, Python and Node verifiers all
reconstruct the same 254-byte encoding and SHA-256 digest
`8ef482c0a0cd42aee59638898402103024004fbb0ea189d5673d4d6455c2a53d`.

The vector deliberately includes Unicode UTF-8, `u64::MAX`, `i64::MIN`,
opaque bytes, a digest, an array and a map whose source order differs from its
canonical order. Integer values are carried as decimal strings in the JSON
fixture so JavaScript never passes full-width integers through IEEE-754 `Number`. A change that alters the frozen bytes is a protocol-version
change, not a refactor.
