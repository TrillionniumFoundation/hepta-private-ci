# platform.types: implementation design

Parent: `docs/modules/platform.types/TECHNICAL.md`. Lane:
`LANE-A-FOUNDATION`.

Status: the bounded foundational types, HPTC V1, immutable registry, generated
bindings, prompt-delivery/topology contracts and all three owned manifest
contracts are source implemented. A registered numeric-conversion consumer is
composed through the authenticated NDU owner. Exact-candidate qualification,
authenticated registry provisioning and external acceptance remain separate.

## 1. Source and work envelope

Root: `codex-rs/hepta-types`. Bootstrap package:
`PLATFORM-0-TYPE-BOUNDARY`. The module is stateless and authority-free. The
only cross-owner source touched by the registered-consumer slice is
`codex-rs/hepta-ndu`, where the immutable registry is frozen and consumed.

## 2. Public operations and contract details

- `validate_id` checks profile-specific ID grammar before owned construction.
- `AuthorityPosture::try_from_wire_bytes` admits exactly deny-all and rejects
  all grant bits.
- `canonical_encode_v1`, `canonical_digest_v1` and
  `canonical_validate_v1` implement frozen HPTC V1.
- `ContractRegistryV1` holds one bounded immutable generation.
- `rescale_signal` emits a pure arithmetic receipt.
- `rescale_signal_registered` additionally emits
  `RegisteredNumericConversionReceiptV1`, binding registry,
  normalization, profiles and exact input/output evidence.
- `PromptDeliveryObservationV1` binds physical prompt-delivery observation
  fields without granting authority.
- `RuntimeTopologyCandidateV1` binds every topology delta and participant into
  the candidate digest before supervisor admission.
- `RandomStreamManifestV1`, `ExternalSystemManifestV1` and
  `SensorCalibrationManifestV1` use private fields, checked constructors,
  `validate` and `semantic_digest`; they do not execute the systems described.
- generated Python/JavaScript/TypeScript surfaces come only from the checked
  foundational binding spec.

## 3. State, authority and transaction design

There is no authoritative mutable state, transaction or recovery protocol in
`platform.types`. Registry authentication belongs to the caller. The NDU
consumer owns an immutable `NduNumericRegistryV1`, records its digest in the
owner production-policy digest at open, and returns a registered utility-signal
type that cannot be confused with a plain arithmetic receipt.

## 4. Deterministic algorithms

HPTC V1 sorts fields/maps by accepted byte names and preserves array order.
Numeric conversion uses checked wide intermediates and the target profile's
rounding. Manifest semantic digests cover every native semantic field. UTC
manifest timestamps use a canonical bounded parser and chronological key;
invalid calendar dates, offsets, excess precision and reversed windows reject.

## 5. Enforced bounds

- ID: 128 encoded bytes;
- HPTC: 256 KiB, 4096 items, depth 16;
- registry: 256 definitions/profiles and 256 KiB aggregate ordinary text;
- numeric signal: 4096 values;
- manifest enum/version/timestamp/clock/unit text: fixed per-field limits;
- random counter range: strictly increasing;
- sensor confidence: `1..=1_000_000` ppm;
- sensor uncertainty, operating and validity ranges: ordered.

## 6. Concrete verification

- TYPES-01 through TYPES-08 retain the existing numeric, authority, canonical,
  registry and generated-binding coverage.
- TYPES-09 rejects JavaScript prototype-chain names in generated ID/profile
  lookups and verifies the same rejection set in Python and Rust.
- TYPES-10 covers random-stream identity/seed/counter/generator binding and
  rejection.
- TYPES-11 covers external-system digests, closed class values and strict UTC
  observation time.
- TYPES-12 covers sensor class, generation, clock, uncertainty, operating range,
  failure policy and increasing validity window.
- TYPES-13 proves the registered conversion receipt changes with the registry
  generation even when pure arithmetic output is unchanged.
- TYPES-14 proves an authenticated NDU owner without a configured registry
  cannot claim admission, while a configured owner freezes and consumes the
  registry digest.

## 7. Completion vocabulary

`implementedOperationMappingComplete` covers every operation listed in the
module implementation map. `ownedTargetProtocolSourceComplete` is true only
because all three owned manifest protocols now have native source and tests.
This still does not imply an external wire codec, product activation or host
qualification.

## 8. Current native implementation

Implemented files include `bounded.rs`, `identity.rs`, `digest.rs`,
`canonical_digest.rs`, `fixed.rs`, `registry.rs`, `numeric_profile.rs`,
`numeric_conversion.rs`, `prompt_delivery.rs`, `topology.rs`, `manifests.rs`,
`bindings/**`, `generated/**` and `conformance/**`.

Current consumers are `hepta-codex-adapter`/Agentd plus `learning.ledger` for
prompt delivery, `hepta-supervisor` for topology, and
`NduAuthenticatedOwnerV1` for registry-admitted numeric utility signals.
Remaining gates are exact-head and synthetic-merge qualification, the selected
consumer compile matrix, authenticated registry provisioning, target-host
qualification and external acceptance.
