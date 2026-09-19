# Lane A primitive type rules V1

## Identity

`StableId` is nonempty UTF-8 restricted to ASCII alphanumeric characters plus
`.`, `_`, `-`, and `:` with a maximum encoded length of 128 bytes. It performs
no case folding or Unicode normalization. `StableId::parse` validates borrowed
input before allocating the bounded owned copy.

`IdProfileV1` adds a closed namespace contract for execution, schema, receipt,
artifact, producer and normalization IDs. Profiled IDs are encoded as
`<namespace>:<local>`; the local component is nonempty and permits ASCII
alphanumeric plus `.`, `_`, `-`, but not another `:`. `validate_id` never
normalizes mismatched input into a valid ID.

## Authority posture

`AuthorityPosture` V1 has exactly one constructible value: `DENY_ALL`.
`from_untrusted_bits(0)` yields that value and every nonzero bit pattern rejects.
Callers cannot construct a posture that grants runtime, writer, model, dispatch,
external-effect, selection, promotion or release authority.

## Monotonic values

`Generation`, `Revision` and `LogicalSequence` are nonzero `u64` newtypes.
`next` is checked and rejects overflow. They are exact values and are never
passed through approximate numeric conversion.

## Digests and canonical encoding

`Digest32` is exactly 32 bytes. Text parsing accepts exactly 64 lowercase
hexadecimal characters. `ZERO` exists as a structural sentinel; capability and
effect protocols must reject it where evidence is required.

`canonical_encode_v1` freezes `HEPTA-CANONICAL-DIGEST-V1\0`, an ASCII domain,
strictly byte-sorted unique field names, explicit type tags and length framing.
Integers are big-endian and the complete collection is bounded to 256 KiB.
`canonical_digest_v1` is SHA-256 of those exact bytes. The frozen JSON vectors
are the cross-language oracle.

## Bounded values

`BoundedText<N>` and `BoundedBytes<N>` reject zero maximum, empty content and
content larger than `N`; text additionally rejects NUL. The bound is encoded
byte length, not Unicode scalar count. Borrowed `copy_from_str` and
`copy_from_slice` preflight length before making the owned copy.

## Schema and normalization registry

`RegistryDefinitionV1` binds kind, namespaced ID, media type, nonzero schema
version and canonical definition bytes into `canonical_digest_v1`.
`SchemaNormalizationRegistryV1` maps that digest to the exact immutable
definition, is bounded to 256 entries, is host-owned/in-memory only, and rejects
kind mismatches, unknown digests and capacity overflow.

## Numeric values

`FixedQ32` uses checked signed arithmetic and truncating multiply/divide
semantics. `ProbabilityQ32` is restricted to `[0,1]`. Numeric signal conversion
follows `NUMERIC_SIGNAL_CONVERSION.md`; profile, unit, shape, range,
normalization and values are digest-bound.

## Compatibility

Outside `canonical_encode_v1`, these Rust values are not by themselves external
schemas. Any additional wire or database mapping must freeze version, field
order, integer endianness, length framing, unknown-field policy and independent
golden vectors.
