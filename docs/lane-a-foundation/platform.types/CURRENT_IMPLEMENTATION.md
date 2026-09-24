# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is the authority-free Rust contract library for shared
Hepta values. The current source implements:

- bounded text/bytes, profiled identifiers, monotonic identities and raw
  `Digest32` values;
- frozen HPTC V1 canonical encoding, digesting and raw-byte validation;
- deny-only authority posture and exact one-byte untrusted authority ingress;
- checked Q32 primitives, immutable schema/normalization/numeric-profile
  registries and bounded signal conversion;
- a distinct `RegisteredNumericConversionReceiptV1` that binds the immutable
  registry digest and normalization admission instead of reusing a pure
  arithmetic receipt as admission evidence;
- `PromptDeliveryObservationV1` and `RuntimeTopologyCandidateV1` shared
  contracts;
- native `RandomStreamManifestV1`, `ExternalSystemManifestV1` and
  `SensorCalibrationManifestV1` contracts with bounded constructors,
  fail-closed validation and stable semantic digests;
- deterministically generated Python and JavaScript runtime bindings plus
  TypeScript declarations for the intentionally smaller foundational binding
  specification.

The crate forbids unsafe code and owns no clock, filesystem path, network,
credential, durable writer, mutable global registry, model call or external
effect. Manifest construction validates supplied observations; it does not
collect randomness, inspect a host or operate a sensor.

## Public symbols and source bindings

Core source bindings:

- `BoundedBytes`, `BoundedText`: `src/bounded.rs`;
- `StableId`, `IdProfileV1`, `Generation`, `Revision`, `LogicalSequence`,
  `AuthorityPosture`, `NonAuthorizingPosture`: `src/identity.rs`;
- `Digest32`: `src/digest.rs`;
- `canonical_encode_v1`, `canonical_digest_v1`, `canonical_validate_v1`:
  `src/canonical_digest.rs`;
- `ContractRegistryV1`, `RegistryDefinitionV1`,
  `NumericProfileDefinitionV1`: `src/registry.rs` and
  `src/numeric_profile.rs`;
- `NumericSignalV1`, `NumericConversionReceiptV1`,
  `RegisteredNumericConversionReceiptV1`, `rescale_signal` and
  `rescale_signal_registered`: `src/numeric_conversion.rs`;
- `PromptDeliveryObservationV1`, `PromptDeliveryRejectReasonV1`:
  `src/prompt_delivery.rs`;
- `RuntimeTopologyCandidateV1`, `RuntimeTopologyDeltaV1`,
  `RuntimeTopologyOperationV1`: `src/topology.rs`;
- `RandomStreamManifestV1`, `ExternalSystemManifestV1`,
  `SensorCalibrationManifestV1` and their closed enum/range/timestamp helpers:
  `src/manifests.rs`;
- generated binding source and generator:
  `bindings/PLATFORM_TYPES_BINDINGS_V1.json` and
  `bindings/generate_bindings.py`.

Current source consumers are capability-specific rather than one ambient
`platform.types` product caller:

- `PromptDeliveryObservationV1` is produced by the Codex adapter/Agentd prompt
  path and consumed by `learning.ledger`;
- `RuntimeTopologyCandidateV1` is validated and consumed by
  `runtime.supervisor` before topology admission;
- `rescale_signal_registered` is consumed through
  `utility.ndu::NduNumericRegistryV1`; `NduAuthenticatedOwnerV1` freezes the
  registry digest into its production-policy identity before admitting utility
  signals.

These source callsites prove composition of the named contracts. They do not by
themselves prove target-host qualification, operator acceptance or release.

## Durability and activation

`platform.types` is stateless. It has no journal, migration, recovery worker or
production writer. `ContractRegistryV1` and `NduNumericRegistryV1` are immutable
caller-owned generations. Authentication, selection and distribution of a
registry generation belong to the product owner.

The NDU consumer deliberately returns `NduRegisteredUtilitySignalV1`, which
contains the distinct registered receipt. A caller holding only
`NumericConversionReceiptV1` has evidence of deterministic arithmetic, not
registry admission.

Source consumers exist, but production implementation and activation remain
false until the exact candidate completes Lane A and the applicable consumer
qualification matrix. No contract in this module grants runtime, write,
selection, promotion or release authority.

## Target-only design

The following remain outside the current source claim:

- an authenticated product service that publishes or rotates registry
  generations;
- external canonical-JSON/wire codecs for arbitrary Rust domain structs beyond
  the frozen generated foundational binding surface;
- host inventory collection, random-stream execution and physical sensor
  calibration drivers;
- target-host performance qualification, canary, operator acceptance,
  promotion and release.

Those capabilities require their existing owners and must not be absorbed into
this pure contract library.

## Known limits and non-claims

- `StableId` is bounded to 128 encoded bytes.
- HPTC V1 is bounded to 256 KiB, 4096 collection items and depth 16.
- A registry admits at most 256 ordinary/profile definitions; ordinary
  definitions are limited to 4096 UTF-8 bytes and 256 KiB aggregate data.
- Numeric signals admit at most 4096 elements and reject overflow rather than
  saturating.
- Manifest enum/version/timestamp fields are explicitly bounded. UTC manifest
  timestamps accept only canonical `Z` form with at most six fractional digits;
  validity windows must be increasing.
- Generated bindings cover only the checked binding spec. They do not expose
  every Rust contract as Python/JavaScript/TypeScript.
- `productExecutionProved`, independent acceptance, activation and release are
  not claimed by this document.

## Verification

Focused source evidence includes:

- Rust tests for bounds, identifiers, authority rejection, HPTC framing,
  registry invariants, numeric conversion and all three manifests;
- prompt-delivery and topology positive/negative contract tests;
- NDU registered-consumer tests showing registry-generation changes alter the
  admission digest while preserving the same pure arithmetic result;
- five accepted and seven rejected HPTC cross-language vectors;
- generated-binding drift checks and Python/JavaScript negative tests for
  unknown and inherited property names such as `constructor`, `toString` and
  `__proto__`;
- strict `codex-hepta-types` Clippy/fmt and the selected consumer compile/test
  matrix.

Lane A reports current-truth and native-test outcomes independently, then fails
the final job unless every required step and receipt succeeds. Exact-head and
deterministic synthetic-merge workflow artifacts, not prose, are candidate
qualification evidence.

## Integration prerequisites

A consuming owner must pin the exact contract/profile IDs and, for registered
numeric conversion, supply one immutable registry generation whose digest is
bound into the consuming owner identity. Consumers must validate at their final
use boundary and must never reinterpret a pure conversion receipt as admission.

Protocol producers must construct the native manifest/observation type before
publication and preserve its semantic digest through any owner-specific wire or
durable representation. Any future wire codec must deny unknown critical fields
and demonstrate parity with the native validation rules.
