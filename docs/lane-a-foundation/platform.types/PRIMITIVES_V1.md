# Lane A primitive and shared-contract rules V1

## Identity

`StableId` is nonempty UTF-8 restricted to ASCII alphanumeric characters plus
`.`, `_`, `-`, and `:` with a maximum encoded length of 128 bytes. It
performs no case folding or Unicode normalization.

`IdProfileV1` makes semantic namespace grammar explicit. `Stable` preserves
the historical StableId grammar; `Namespaced` requires exactly one nonempty
namespace separator; `Execution`, `Schema`, `Normalization`, `Receipt` and `Artifact`
require the corresponding `execution:`, `schema:`, `normalization:`, `receipt:`
and `artifact:` namespace. `validate_id` validates borrowed input before
allocating the bounded owned identifier. No profile makes an ID safe for
filesystem, URI, SQL or other unrelated contexts.

## Monotonic values

`Generation`, `Revision` and `LogicalSequence` are nonzero `u64`
newtypes. `next` is checked and rejects overflow. They are exact values and are
never passed through approximate numeric conversion.

## Authority posture

`AuthorityPosture` is deny-only by construction: its representation is
private and the only public value is `DENY_ALL`. Safe callers cannot widen it
with runtime, selection, promotion, release or effect bits.

`NonAuthorizingPosture` is the explicit receipt proof form and is likewise
deny-only. Conversion between the two is infallible. Protocol owners that
decode raw/wire authority flags must validate those flags before constructing
shared Platform Types values; raw flags are not represented as
`AuthorityPosture`.

## Digests

`Digest32` is exactly 32 bytes. Text parsing accepts exactly 64 lowercase
hexadecimal characters. `ZERO` exists as a structural sentinel; capability
and effect protocols must reject it where evidence is required.

`canonical_digest_v1` is the structured digest contract. It binds the exact
V1 domain prefix, type ID, nonzero schema version, field names, type tags and
length-framed values. Top-level fields and maps are canonicalized by UTF-8 byte
ordering; arrays retain semantic order. Duplicate names/keys and oversize input
reject. The complete encoding is bounded to 256 KiB.

## Bounded values

`BoundedText<N>` and `BoundedBytes<N>` reject zero maximum, empty content and
content larger than `N`; text additionally rejects NUL. The bound is encoded
byte length, not Unicode scalar count. Borrowed `try_from_str` and
`try_from_slice` constructors validate the size before allocating their owned
representation.

## Immutable schema and normalization registry

`ContractDefinitionV1` binds definition kind, StableId, nonzero version and an
opaque bounded body into a canonical digest. `ContractRegistryV1` is a
caller-owned immutable collection that resolves those digests and enforces
definition kind. It is bounded to 256 entries, 16 KiB per definition and 256
KiB aggregate definition bytes.

Definition kind and identifier namespace are bound at construction: schema definitions require `schema:*`, and normalization definitions require `normalization:*`. There is deliberately no process-global mutable registry. Trust provisioning,
network discovery, mutable registration and production admission are outside
this primitive contract.

## Numeric values

`FixedQ32` uses checked signed arithmetic and truncating multiply/divide
semantics. `ProbabilityQ32` is restricted to `[0,1]`. Numeric signal
conversion follows `NUMERIC_SIGNAL_CONVERSION.md`; profile, unit, shape,
range, normalization and values are digest-bound.

`rescale_signal_registered` additionally requires the normalization digest to
resolve as a `Normalization` definition in an explicitly supplied
`ContractRegistryV1`. Conversion receipts carry `NonAuthorizingPosture`.

## Compatibility

These Rust values are not by themselves external schemas. The V1 canonical
digest encoding is language-neutral and has a frozen Rust/Python/Node vector,
but arbitrary wire/database mappings must still freeze version, field order,
integer endianness, length framing, unknown-field policy and independent golden
vectors. Generated cross-language bindings are not claimed.
