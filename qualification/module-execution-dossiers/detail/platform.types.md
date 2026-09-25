# platform.types: implementation design

Parent: `docs/modules/platform.types/TECHNICAL.md`. Lane:
`LANE-A-FOUNDATION`.

Status: bounded/profiled primitives, sealed non-authorizing posture, canonical
HPTC V1 encoding/validation, immutable schema/normalization and numeric-profile
registry, deterministic numeric conversion, conformance suite and generated
Python/JavaScript/TypeScript bindings are source implemented. Three
registry-owned target protocols remain source-pending. Named product composition,
candidate qualification and independent acceptance are separate gates.

## 1. Source and work envelope

Root: `codex-rs/hepta-types`. Bootstrap package:
`PLATFORM-0-TYPE-BOUNDARY`. The module is stateless and authority-free.

`productCallerState = not_composed`. Source-level interoperability or generated
bindings do not count as production execution.

## 2. Public operations and contract details

- `validate_id(raw, profile)` validates bounded V1 ID grammar before owned
  construction. Schema, normalization, execution, receipt and artifact profiles
  bind explicit namespaces.
- `AuthorityPosture::try_from_wire_bytes(raw)` is a one-byte negative ingress:
  zero produces deny-all; every nonzero grant bit rejects. `AuthorityPosture`
  and `NonAuthorizingPosture` cannot encode authority.
- `canonical_encode_v1` / `canonical_digest_v1` produce the frozen HPTC V1
  representation. `canonical_validate_v1` independently validates supplied V1
  bytes and rejects invalid tags/bools, ordering, depth, size, truncation and
  trailing data.
- `ContractRegistryV1` holds one immutable bounded caller-owned definition
  generation. Definition kind is bound to ID namespace.
- `NumericProfileDefinitionV1` binds profile identity, definition version,
  scale and rounding to a canonical digest.
- `rescale_signal_registered` requires source profile, target profile and
  normalization definition in the same registry generation before checked
  numeric conversion.
- generated Python/JavaScript runtime bindings and TypeScript declarations are
  deterministically emitted from `PLATFORM_TYPES_BINDINGS_V1.json`.

## 3. State, authority and transaction design

There is no authoritative state, clock, credential, filesystem handle, global
registry, migration or transaction. All values are immutable or caller-owned.

The only authority-related operation is rejection: untrusted raw authority bits
cannot become a trusted shared type. Real authority belongs to
`kernel.authority`.

Authentication and distribution of a registry generation are product-owner
responsibilities. `platform.types` proves semantic identity of definitions, not
who approved them.

## 4. Deterministic algorithms

ID validation performs no case folding or normalization. Canonical V1 binds
domain, namespaced type ID, schema version, type tags, integer widths, lengths
and canonical ordering. Arrays preserve semantic order. V1 deliberately does no
Unicode normalization.

Numeric conversion uses checked i128 intermediates and target profile rounding;
there is no saturation. Numeric profile admission refuses scale/rounding drift
under an existing V1 identity.

`FixedQ32` compatibility multiply/divide is
`fixed-q32-toward-zero-v1`. `signed-q32-nearest-ties-even-v1` shares the raw
2^32 scale but is explicitly not arithmetic-compatible.

## 5. Enforced bounds

- stable identifier: <= 128 encoded bytes;
- canonical HPTC V1: <= 256 KiB;
- canonical array/map/field collection: <= 4096 entries;
- canonical nesting: <= 16;
- immutable registry: <= 256 total ordinary/profile definitions;
- ordinary registry definition: <= 4096 UTF-8 bytes;
- aggregate ordinary registry definition bytes: <= 256 KiB;
- numeric signal elements: <= 4096.

These are source-enforced limits, not target-host latency measurements.

## 6. Concrete verification

- TYPES-01: positive and negative half ties follow target profile rounding.
- TYPES-02: conversion digests bind source/output profile, normalization,
  shape/range/unit and exact rational error bound.
- TYPES-03: overflow, unit/shape/range/normalization mismatch and unregistered
  profile fail closed.
- TYPES-04: all eight raw authority grant bits reject before trusted posture
  construction.
- TYPES-05: five canonical accepted vectors agree across Rust/Python/Node,
  including integer boundaries and NFC/NFD non-normalization.
- TYPES-06: seven rejection vectors cover duplicate field/key, zero schema,
  oversize, depth overflow, invalid bool and invalid tag.
- TYPES-07: generated bindings regenerate without drift and Python/JavaScript
  consumers agree on ID, authority, profile and Q32 semantics.
- TYPES-08: registry definition kind/namespace, duplicate identity/profile and
  aggregate byte bounds reject.

Exact-head and deterministic synthetic-merge workflow success are required
candidate receipts. Static test identities are not pass receipts.

## 7. Completion vocabulary

`implementedOperationMappingComplete` means every operation claimed as
implemented in this candidate maps to public source and tests.

`ownedTargetProtocolSourceComplete` means every protocol canonically owned by
`platform.types` has native source. It remains false while
`RandomStreamManifestV1`, `ExternalSystemManifestV1` and
`SensorCalibrationManifestV1` are source-pending.

The legacy broad `nativeSourceMappingComplete` must not be interpreted as full
module source completion and is false for this candidate.

## 8. Current native implementation

Implemented source surfaces:

- `src/bounded.rs`: bounded text/bytes;
- `src/identity.rs`: IDs, monotonic values, raw authority rejection and sealed
  postures;
- `src/digest.rs`: Digest32;
- `src/canonical_digest.rs`: HPTC V1 encode/digest/validate;
- `src/fixed.rs`: FixedQ32/ProbabilityQ32 and explicit arithmetic profile;
- `src/registry.rs`: immutable contract/profile registry;
- `src/numeric_profile.rs`: native profile semantics and
  `NumericProfileDefinitionV1`;
- `src/numeric_conversion.rs`: native and registry-admitted conversion;
- `bindings/**`, `generated/**`, `conformance/**`: generated language
  surfaces and independent compatibility oracles.

Remaining repository-controlled source work for full target ownership:
`RandomStreamManifestV1`, `ExternalSystemManifestV1`,
`SensorCalibrationManifestV1`.

Remaining integration/evidence work: named product composition, authenticated
registry-generation provisioning, full consumer compile matrix, independent
semantic review, target-host/product qualification, then activation/operator
acceptance/promotion/release.
