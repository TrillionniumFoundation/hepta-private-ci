# Lane A primitive type rules V1

## Identity

`StableId::new` preserves the original nonempty UTF-8 grammar restricted to
ASCII alphanumeric characters plus `.`, `_`, `-`, and `:`, with a
maximum encoded length of 128 bytes. It performs no case folding or Unicode
normalization.

New protocol boundaries use `validate_id(raw, IdProfileV1)` before allocation:

- `stable-v1`: the compatibility grammar above;
- `module-v1`: lowercase dot-separated module segments;
- `namespaced-v1`: one canonical module namespace, `:`, then one lowercase
  local identifier.

`IdNamespaceV1` validates a module namespace once and constructs canonical
namespaced IDs. Profiles never silently normalize rejected input.

## Monotonic values

`Generation`, `Revision` and `LogicalSequence` are nonzero `u64` newtypes.
`next` is checked and rejects overflow. They are exact values and are never
passed through approximate numeric conversion.

## Digests

`Digest32` is exactly 32 bytes. Text parsing accepts exactly 64 lowercase
hexadecimal characters. `ZERO` exists as a structural sentinel; capability and
effect protocols must reject it where evidence is required.

`canonical_digest_v1` is the shared protocol commitment primitive. It hashes
the exact `HPTC` V1 encoding documented in `CANONICAL_DIGEST_V1.md`: fixed
domain separation, namespaced type ID, nonzero schema version, explicit type
tags and length framing, canonical field/map ordering and semantic array order.
The complete encoding is bounded to 256 KiB.

## Bounded values

`BoundedText<N>` and `BoundedBytes<N>` reject zero maximum, empty content and
content larger than `N`; text additionally rejects NUL. The bound is encoded
byte length, not Unicode scalar count. Borrowed `try_from_str` /
`try_from_slice` constructors validate the limit before allocating the owned
copy.

## Authority posture

`AuthorityPosture` is a sealed deny-only value. There are no public grant
fields. `AuthorityFlagsV1` exists only as an untrusted decoding/testing shape;
`AuthorityPosture::try_from_flags` rejects when any flag is true. Actual
authority belongs to the owning authority module, not to platform types.

## Immutable registry

`RegistryDefinitionV1` binds kind, namespaced ID, version and bounded canonical
definition text into `canonical_digest_v1`. `ContractRegistryV1` holds at
most 256 definitions, sorts them deterministically, rejects duplicate
identities and has no mutation/global-singleton API. A normalization digest can
therefore resolve to an exact immutable definition supplied for the current
caller generation.

## Numeric values

`FixedQ32` uses checked signed arithmetic and truncating multiply/divide
semantics. `ProbabilityQ32` is restricted to `[0,1]`. Numeric signal conversion
follows `NUMERIC_SIGNAL_CONVERSION.md`; profile, unit, shape, range,
normalization and values are canonical-digest-bound.
`rescale_signal_registered` additionally requires the normalization digest to
resolve in an explicit `ContractRegistryV1`.

## Compatibility

`CANONICAL_V1_CONFORMANCE.json` freezes canonical bytes and digest output, with
independent Rust, Python and TypeScript checks. Other Rust values are not
automatically external schemas. Any additional wire/database mapping must
freeze version, field order, integer endianness, length framing, unknown-field
policy and independent golden vectors.
