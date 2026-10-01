# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust foundational-contract
library. It owns bounded bytes/text, profiled identifiers, nonzero monotonic
identities, raw SHA-256 digests, canonical HPTC V1 bytes/digests and raw-byte
validation, checked Q32 values, immutable schema/normalization definitions,
numeric-profile admission definitions, registered numeric-signal conversion and
deterministically generated Python/JavaScript/TypeScript bindings.

The crate forbids unsafe code and owns no clock, network, filesystem,
credential, process-global mutable registry, durable writer or authority token.

## Public symbols and source bindings

- `BoundedBytes`, `BoundedText`, `BoundedValueError`: `src/bounded.rs`.
- `StableId`, `IdProfileV1`, `IdNamespaceV1`, `validate_id`,
  `Generation`, `Revision`, `LogicalSequence`, `AuthorityFlagsV1`,
  sealed `AuthorityPosture` and `NonAuthorizingPosture`: `src/identity.rs`.
- `Digest32`, `DigestParseError`: `src/digest.rs`.
- `canonical_encode_v1`, `canonical_digest_v1`,
  `canonical_validate_v1`, `CanonicalValueV1`: `src/canonical_digest.rs`.
- `ContractRegistryV1`, `RegistryDefinitionV1`, `RegistryKindV1`:
  `src/registry.rs`.
- `FixedQ32`, `ProbabilityQ32`,
  `FIXED_Q32_ARITHMETIC_PROFILE_V1`: `src/fixed.rs`.
- `NumericProfileV1`, `NumericProfileDefinitionV1`,
  `NumericSignalSchemaV1`: `src/numeric_profile.rs`.
- `NumericSignalV1`, `rescale_signal`, `rescale_signal_registered` and
  `NumericConversionReceiptV1`: `src/numeric_conversion.rs`.
- binding source/generator:
  `bindings/PLATFORM_TYPES_BINDINGS_V1.json`,
  `bindings/generate_bindings.py`.
- generated outputs:
  `generated/python/hepta_platform_types_v1.py`,
  `generated/javascript/hepta_platform_types_v1.mjs`,
  `generated/typescript/hepta_platform_types_v1.d.ts`.

## Authority boundary

`AuthorityPosture` and `NonAuthorizingPosture` cannot represent a grant.
Raw V1 authority input is exactly one untrusted byte. `0x00` admits deny-all;
any nonzero bit rejects in `AuthorityPosture::try_from_wire_bytes` before a
trusted posture is constructed. This is a negative boundary, not an authority
implementation.

## Canonical compatibility

HPTC V1 is frozen in `CANONICAL_DIGEST_V1.md`.
`CANONICAL_V1_CONFORMANCE.json` contains five accepted vectors and seven
rejection cases. `canonical_validate_v1`, the Python/Node conformance oracles
and generated-binding consumer gates are independent implementations of the
same bounded contract. V1 performs no Unicode normalization; NFC and NFD
fixtures intentionally digest differently.

Generated bindings cover foundational constants, ID profiles, deny-all raw
authority admission, numeric-profile metadata, FixedQ32 arithmetic semantics and
canonical limits. They do not automatically expose arbitrary Rust structs as
external schemas.

## Registry and numeric-profile admission

`ContractRegistryV1` is an immutable caller-owned generation, not ambient
state. Schema definitions require `schema:*` IDs; normalization definitions
require `normalization:*` IDs.

`NumericProfileDefinitionV1` canonically binds profile identity, V1 definition
version, scale and rounding. `rescale_signal_registered` requires the exact
source profile, target profile and normalization definition to resolve in the
same registry generation. Authentication and distribution of that generation
belong to the product owner and are not supplied by `platform.types`.

## Q32 semantic split

`FixedQ32` and `signed-q32-nearest-ties-even-v1` share raw scale `2^32`,
but not arithmetic semantics. `FixedQ32` compatibility multiply/divide uses
`fixed-q32-toward-zero-v1`; the numeric conversion profile uses
nearest-ties-even. The source API exposes this distinction explicitly.

## Durability and activation

The module is stateless and has no durability. `productCallerState` is
`not_composed`: source tests, generated bindings and conformance oracles are
not a named production caller. Product provisioning of an authenticated
registry generation, target-host qualification and operator acceptance are
separate gates.

## Target-only design

Canonical registries assign these protocols to `platform.types`, but no native
Rust contract exists for them in this candidate:

- `RandomStreamManifestV1`;
- `ExternalSystemManifestV1`;
- `SensorCalibrationManifestV1`.

Their ownership does not make the module's full target protocol inventory source
complete.

## Known limits and non-claims

`platform.types` validates bounded values and canonical representations; it does
not authenticate a registry generation, authorize a caller, persist mutable
facts or prove that a generated binding was deployed. Source conformance and
binding generation are not target-host product execution or external
acceptance.

## Verification

Native tests cover bounds, exhaustive identifier grammar/profile substitution,
monotonic overflow, raw authority-bit rejection, digest parsing, Q32 errors,
canonical encoding/validation, registry bounds/namespace invariants,
numeric-profile semantic binding and registered conversion.

Lane A exact-head and deterministic synthetic-merge jobs additionally run the
Python/Node accepted and rejected conformance oracles, regenerate bindings with
`--check`, run generated Python/JavaScript consumer compatibility gates and
run Lane A native tests plus strict lint. Executed workflow artifacts, not this
document, are the candidate receipts.


## Integration prerequisites

A product owner supplies and authenticates the exact registry generation,
selects the numeric and identifier profiles it admits, and validates generated
bindings in its target runtime. Exact-head and deterministic synthetic-merge
qualification, target-host execution, operator acceptance, activation,
promotion and release remain separate gates.
