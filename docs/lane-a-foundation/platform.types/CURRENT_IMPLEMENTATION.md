# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust contract library. It owns bounded
byte/text values, stable and namespaced identifiers, raw SHA-256 digests, a
versioned canonical digest encoding, nonzero monotonic generation/revision/sequence
values, checked Q32 values, deterministic numeric-signal conversion, an
unforgeable deny-all qualification posture and a bounded in-memory
schema/normalization definition registry.

The crate forbids unsafe code and owns no clock, network, filesystem, credential,
process-global mutable registry or durable writer.

## Public symbols and source bindings

- `BoundedBytes`, `BoundedText`, `BoundedValueError`: `src/bounded.rs`.
- `StableId`, `IdNamespaceV1`, `IdProfileV1`, `validate_id`, `Generation`,
  `Revision`, `LogicalSequence`, `AuthorityPosture`, `AuthorityPostureError`,
  `IdentityError`: `src/identity.rs`.
- `Digest32`, `DigestParseError`: `src/digest.rs`.
- `CanonicalFieldV1`, `CanonicalValueV1`, `canonical_encode_v1`,
  `canonical_digest_v1`: `src/canonical.rs`.
- `FixedQ32`, `ProbabilityQ32`: `src/fixed.rs`.
- `NumericProfileV1`, `NumericSignalV1`, `rescale_signal` and conversion
  receipts: `src/numeric_profile.rs` and `src/numeric_conversion.rs`.
- `RegistryDefinitionV1`, `RegistryKindV1`,
  `SchemaNormalizationRegistryV1`: `src/registry.rs`.

`validate_id` checks a borrowed namespaced identifier before creating the one
bounded owned `StableId`. `AuthorityPosture` has exactly one representable V1
value, `DENY_ALL`; untrusted nonzero authority bits reject during construction.

## Durability and activation

The module is stateless with respect to authoritative state and has no durability.
`SchemaNormalizationRegistryV1` is a bounded host-owned in-memory collection; it
is not process-global and does not claim persistence. The module remains a
library-only dependency and its values grant no runtime or effect authority.

## Target-only design

Generated language bindings, a durable/process-global schema service, production
profile admission and product/runtime composition remain target-only. The current
cross-language claim is limited to the frozen canonical V1 vectors, independently
checked by Rust, Python and TypeScript code.

## Known limits and non-claims

`Digest32::of_bytes` remains a low-level raw SHA-256 primitive. Protocol owners
that require stable semantic hashing should use `canonical_digest_v1` with an
explicit domain and sorted named fields instead of ad-hoc concatenation.

The registry resolves a digest to exact versioned definition bytes and metadata;
it does not execute, normalize or semantically interpret those definitions.
Rust type equality is not a frozen wire representation outside the declared
canonical V1 encoding. Generic bounded values are not secret containers.

## Verification

Native tests cover bounds, borrowed preflight paths, the complete ASCII StableId
alphabet, namespace/profile rejection, authority-bit rejection, digest parsing,
monotonic overflow, fixed-point boundaries, canonical framing/domain separation,
registry capacity/kind binding, numeric overflow, rounding and error bounds.

`testdata/canonical_digest_v1_vectors.json` freezes language-neutral bytes and
SHA-256 outputs. `scripts/verify_platform_types_vectors.py` and
`scripts/verify_platform_types_vectors.ts` independently reconstruct those bytes.
The Lane A workflow runs these vector checks plus native tests and strict lint on
both exact PR source and the deterministic synthetic merge candidate.

## Integration prerequisites

A product consumer must name the semantic type/profile/version, use the declared
ID namespace, preserve exact authority/fence fields, use canonical V1 framing for
shared semantic digests, and bind registry digests to exact definitions. Generated
bindings, host durability, independent acceptance, activation, promotion and
release require their separate evidence gates.
