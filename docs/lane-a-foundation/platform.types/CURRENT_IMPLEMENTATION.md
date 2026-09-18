# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust foundational-contract library.
It owns bounded byte/text values, profiled stable identifiers and namespaces,
raw digests plus canonical digest V1, nonzero monotonic generation/revision/
sequence values, checked Q32 values, an immutable schema/normalization registry
and deterministic numeric-signal conversion. The crate forbids unsafe code and
owns no clock, network, filesystem, credential, process-global mutable registry
or durable writer.

## Public symbols and source bindings

- `BoundedBytes`, `BoundedText`, `BoundedValueError`:
  `src/bounded.rs`.
- `StableId`, `IdProfileV1`, `IdNamespaceV1`, `validate_id`,
  `Generation`, `Revision`, `LogicalSequence`, sealed
  `AuthorityPosture`: `src/identity.rs`.
- `Digest32`, `DigestParseError`: `src/digest.rs`.
- `canonical_encode_v1`, `canonical_digest_v1`, `CanonicalValueV1`:
  `src/canonical_digest.rs`.
- `ContractRegistryV1`, `RegistryDefinitionV1`, `RegistryKindV1`:
  `src/registry.rs`.
- `FixedQ32`, `ProbabilityQ32`: `src/fixed.rs`.
- `NumericProfileV1`, `NumericSignalV1`, `rescale_signal`,
  `rescale_signal_registered` and conversion receipts:
  `src/numeric_profile.rs` and `src/numeric_conversion.rs`.

`StableId::new` preserves the original V1 grammar. New protocol surfaces use
`validate_id` with an explicit profile. `AuthorityPosture` has no granting
representation; untrusted `AuthorityFlagsV1` can only be converted when every
flag is false.

## Durability and activation

The module is stateless and has no durability. `ContractRegistryV1` is an
immutable value supplied by the caller for one generation, not a global
service. The module is a library-only dependency; its values grant no runtime
or effect authority.

## Target-only design

Generated cross-language bindings, broader production numeric/unit registries
and any process-global or remotely distributed schema service remain
target-only. Python and TypeScript canonical-digest conformance oracles are
source-level interoperability evidence, not generated client bindings.

## Known limits and non-claims

Rust type equality is not itself a frozen wire representation.
`Digest32::of_bytes` remains raw SHA-256 for low-level hashing; shared protocol
commitments use `canonical_digest_v1` with frozen V1 framing and domain
separation. The immutable registry proves a digest resolves to an exact
definition in the caller-supplied generation; it does not authenticate who
approved that definition.

Generic bounded values are not secret containers, and their debug
representations must not be used for credentials.

## Verification

Native tests cover borrowed allocation boundaries, UTF-8 byte bounds, the full
ASCII StableId alphabet, profiled IDs/namespaces, sealed authority, digest
parsing, monotonic overflow, Q32 errors, canonical ordering/framing/negative
cases, immutable registry lookup/capacity, numeric profile mismatch, overflow,
rounding, error bounds and registry-enforced normalization.

`CANONICAL_V1_CONFORMANCE.json` freezes exact bytes and SHA-256. Independent
Python and TypeScript oracles reproduce the vector. Lane A CI executes those
oracles plus native package tests on the exact source HEAD and deterministic
synthetic merge candidate. Source tests are not themselves execution receipts.

## Integration prerequisites

A consumer must name the semantic type and version, use explicit ID profiles,
preserve exact authority/fence fields, use canonical digest V1 for shared
commitments and supply the immutable registry generation required by its
normalization/schema contract. Product execution, target-host qualification,
operator acceptance, promotion and release remain separate evidence gates.
