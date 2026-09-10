# Lane A primitive type rules V1

## Identity

`StableId` is nonempty UTF-8 restricted to ASCII alphanumeric characters plus
`.`, `_`, `-`, and `:` with a maximum encoded length of 128 bytes. It performs
no case folding or Unicode normalization.

## Monotonic values

`Generation`, `Revision` and `LogicalSequence` are nonzero `u64` newtypes.
`next` is checked and rejects overflow. They are exact values and are never
passed through approximate numeric conversion.

## Digests

`Digest32` is exactly 32 bytes. Text parsing accepts exactly 64 lowercase
hexadecimal characters. `ZERO` exists as a structural sentinel; capability and
effect protocols must reject it where evidence is required.

## Bounded values

`BoundedText<N>` and `BoundedBytes<N>` reject zero maximum, empty content and
content larger than `N`; text additionally rejects NUL. The bound is encoded
byte length, not Unicode scalar count.

## Numeric values

`FixedQ32` uses checked signed arithmetic and truncating multiply/divide
semantics. `ProbabilityQ32` is restricted to `[0,1]`. Numeric signal conversion
follows `NUMERIC_SIGNAL_CONVERSION.md`; profile, unit, shape, range,
normalization and values are digest-bound.

## Compatibility

These Rust values are not by themselves external schemas. Any wire or database
mapping must freeze version, field order, integer endianness, length framing,
unknown-field policy and independent golden vectors.
