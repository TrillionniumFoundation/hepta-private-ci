# Lane A primitive type rules V1

## Identity

`StableId` is nonempty UTF-8 restricted to ASCII alphanumeric characters plus
`.`, `_`, `-`, and `:` with a maximum encoded length of 128 bytes. It
performs no case folding or Unicode normalization.

`IdProfileV1` preserves that grammar and adds semantic namespace validation for
`execution:`, `schema:`, `receipt:`, `artifact:` and
`normalization:`. `validate_id` rejects a missing/wrong namespace and an
empty namespace suffix. Borrowed validation occurs before constructing the
bounded owned ID.

## Monotonic values

`Generation`, `Revision` and `LogicalSequence` are nonzero `u64` newtypes.
`next` is checked and rejects overflow. They are exact values and are never
passed through approximate numeric conversion.

## Authority posture

`AuthorityPosture` is a sealed deny-all marker for qualification/evidence
values. Its fields are private and the public API exposes only
`AuthorityPosture::DENY_ALL`; consumers cannot construct an authority-bearing
posture.

## Digests

`Digest32` is exactly 32 bytes. Text parsing accepts exactly 64 lowercase
hexadecimal characters. `ZERO` exists as a structural sentinel; capability and
effect protocols must reject it where evidence is required.

`canonical_digest_v1` is the shared canonical framing contract: explicit V1
domain separation, nonzero schema version, StableId type/field names, 32-bit
big-endian length frames, UTF-8-byte-ordered maps, semantic-order arrays and
typed value tags. Canonical input is capped at 256 KiB, depth 32 and 1024
fields/map entries. Cross-language fixture bytes are frozen in
`CANONICAL_GOLDEN_V1.json`.

## Bounded values

`BoundedText<N>` and `BoundedBytes<N>` reject zero maximum, empty content and
content larger than `N`; text additionally rejects NUL. The bound is encoded
byte length, not Unicode scalar count. `from_str` / `from_slice` validate a
borrowed input before allocating the owned bounded value.

## Registry definitions

`DefinitionRegistryV1` is an immutable caller-supplied value, not a global
runtime service. It binds schema or normalization definitions to namespaced
IDs, nonzero versions and nonzero definition digests, rejects duplicate IDs or
digests, and resolves digest identity back to the stable definition reference.

## Numeric values

`FixedQ32` uses checked signed arithmetic and truncating multiply/divide
semantics. `ProbabilityQ32` is restricted to `[0,1]`. Numeric signal conversion
follows `NUMERIC_SIGNAL_CONVERSION.md`; profile, unit, shape, range,
normalization and values are digest-bound.

## Compatibility

Rust object layout is not the external schema. External implementations must
reproduce the frozen canonical bytes and SHA-256 values for every shared
canonical vector. Generated Python/TypeScript bindings remain a separate
composition deliverable.
