# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust primitive and canonical-contract
library. It owns bounded byte/text values, stable identifiers and semantic ID
profiles, canonical SHA-256 framing, nonzero monotonic generation/revision/
sequence values, checked Q32 values, registered numeric signal conversion and
an immutable digest-to-definition registry. The crate forbids unsafe code and
owns no clock, network, filesystem, credential, process-global mutable registry
or durable writer.

## Public symbols and source bindings

- `BoundedBytes`, `BoundedText`, `BoundedValueError`:
  `src/bounded.rs`.
- `StableId`, `IdProfileV1`, `validate_id`, `Generation`, `Revision`,
  `LogicalSequence`, `AuthorityPosture`, `IdentityError`:
  `src/identity.rs`.
- `Digest32`, `DigestParseError`: `src/digest.rs`.
- `CanonicalFieldV1`, `CanonicalValueV1`, `canonical_digest_v1` and
  `CanonicalDigestError`: `src/canonical.rs`.
- `DefinitionRegistryV1`, `RegistryDefinitionV1`, `RegistryKindV1` and
  `RegistryErrorV1`: `src/registry.rs`.
- `FixedQ32`, `ProbabilityQ32`: `src/fixed.rs`.
- `NumericProfileV1`, `NumericSignalV1`, `rescale_signal` and conversion
  receipts: `src/numeric_profile.rs` and `src/numeric_conversion.rs`.

## Canonical digest V1

`canonical_digest_v1(type_id, schema_version, fields)` is domain-separated by
`hepta.canonical-digest.v1\0`. Type IDs and field names use the StableId
alphabet, schema version must be nonzero, variable-width values use explicit
32-bit big-endian length frames, top-level fields and nested maps are sorted by
UTF-8 byte order, and arrays retain semantic order. Encodings are bounded to
256 KiB, nesting depth to 32 and map/field count to 1024.

The frozen cross-language fixture is
`codex-rs/hepta-types/CANONICAL_GOLDEN_V1.json`. It records canonical bytes and
the expected SHA-256 digest independently of Rust object layout.

## Identity profiles and authority posture

`IdProfileV1` preserves the existing StableId grammar and adds explicit
`execution:`, `schema:`, `receipt:`, `artifact:` and
`normalization:` namespace profiles. `validate_id` validates borrowed input
before allocating the bounded owned StableId and never normalizes malformed
input into a valid identifier.

`AuthorityPosture` has private fields. Downstream code can receive and compare
`AuthorityPosture::DENY_ALL`, but cannot construct a posture with an authority
bit enabled through the public API.

## Immutable definition registry V1

`DefinitionRegistryV1` is a bounded immutable value supplied explicitly by the
caller; it is not a runtime-global registry. A definition binds kind, namespaced
StableId, nonzero version and nonzero definition digest. The registry rejects
duplicate IDs/digests and resolves a digest to the stable definition reference.

## Durability and activation

The module is stateless and has no durability. It is a library-only dependency;
its values grant no runtime or effect authority.

## Remaining target-only design

Generated language bindings and production composition of registry definitions
remain target-only. The V1 golden file is the compatibility oracle for future
Python/TypeScript implementations; their generated bindings are not claimed by
this Rust source change.

## Verification

Native tests cover exact/max/oversized bounds, UTF-8 byte limits, the full ASCII
StableId alphabet, namespace mismatches, monotonic overflow, digest parsing,
canonical map ordering and array ordering, framing ambiguity, canonical size
limits, immutable registry duplicate/zero cases, Q32 arithmetic boundaries,
numeric profile mismatch, numeric overflow, rounding and exact error bounds.

`CAPABILITY_EVIDENCE_MAP.json` binds current capabilities to source and test
identities. These source-test references are not themselves exact-head or
synthetic-merge execution receipts.

## Integration prerequisites

A consumer must name the semantic type and version, preserve exact values for
authority/fence fields, use `canonical_digest_v1` or another explicitly
versioned protocol-owned canonical encoding, and add frozen cross-language
vectors before making compatibility claims.
