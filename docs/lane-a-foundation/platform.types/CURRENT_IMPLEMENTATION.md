# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is the authority-free Rust contract library for shared
Hepta values. The current source implements bounded values and identities,
HPTC V1, checked Q32 arithmetic, immutable contract registries, pure and
registry-admitted numeric conversion, prompt-delivery observations, topology
candidates, and the random-stream, external-system and sensor-calibration
manifest families.

Compatibility is versioned rather than silently reinterpreted:

- `PromptDeliveryObservationV1` keeps its historical custom byte commitment;
- `PromptDeliveryObservationV2` is a distinct HPTC semantic commitment and may
  carry the exact V1 digest as an explicit migration witness;
- `RegisteredNumericConversionReceiptV1` remains readable compatibility
  evidence;
- V2 registry admission binds an explicit registry generation, registry digest,
  source and target profile definition digests, normalization definition digest
  and base conversion receipt digest, and exposes a full recomputation verifier.

The V2 prompt and numeric receipt DTOs use private fields and validated
constructors. Existing topology V1 public fields remain source-compatible, but
the product codec returns `ValidatedRuntimeTopologyCandidateV1` only after
native validation and candidate-digest recomputation.

The narrow exact-`pub use` ownership projection remains in
`docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json`. It is not described
as the complete Rust API. Exact-candidate public types, methods, fields, enum
variants and signatures are derived from rustdoc JSON and compared against the
PR base. The module truth state remains in
`docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json`.

## Public symbols and source bindings

Core source bindings are:

- bounded values: `src/bounded.rs`;
- identities and deny-only authority posture: `src/identity.rs`;
- digest and HPTC primitives: `src/digest.rs` and `src/canonical_digest.rs`;
- Q32 values: `src/fixed.rs`;
- immutable registry and numeric profiles: `src/registry.rs` and
  `src/numeric_profile.rs`;
- V1 conversion and compatibility receipt: `src/numeric_conversion.rs`;
- generation-bound V2 admission and verifier: `src/numeric_registry_v2.rs`;
- frozen prompt V1: `src/prompt_delivery.rs`;
- HPTC prompt V2 and V1 migration witness: `src/prompt_delivery_v2.rs`;
- topology candidates: `src/topology.rs`;
- the three manifest families: `src/manifests.rs`;
- the typed normative field/version catalog: `src/protocol_catalog_v2.rs`.

`platform.wire` owns strict JSON transport for Prompt V2 and Topology V1. Its
codec bounds raw bytes and nesting, rejects duplicate and unknown fields,
requires canonical decimal generation strings, and reconstructs native values
before publication. Python and JavaScript independently recompute the same HPTC
semantic commitment from shared golden vectors.

Named source consumers now include:

- Codex/Agentd and Learning Ledger for the frozen prompt V1 compatibility path;
- Runtime Supervisor for validated topology admission;
- authenticated NDU owner for registered numeric signals;
- NDU random-stream owner for episode/decision/generator/counter-window binding;
- Runtime Supervisor external-system owner for system/class/host/authorization
  binding;
- Runtime Supervisor sensor owner for sensor/class/hardware/generation/clock and
  failure-policy binding.

These callsites prove source composition and owner-bound admission. They do not
prove deployed product activation.

## Durability and activation

`platform.types` is stateless. It owns no clock, filesystem path, network,
credential, mutable global registry, journal, recovery worker, durable writer,
model call or external effect. Registry snapshots are immutable caller-owned
inputs. V2 records the caller-selected monotonic generation but does not mint or
authenticate that generation.

Product-owner admission receipts remain `NonAuthorizingPosture::DENY_ALL`.
Randomness execution, host inventory collection, sensor operation, registry
publication and durable storage stay with their existing owners.

Production implementation, deployment qualification, activation and release
remain false until both the exact source head and deterministic synthetic merge
produce authoritative receipts and the separate external governance gates pass.

## Target-only design

The following remain outside this module's present source claim:

- authenticated publication, rotation and anti-rollback distribution of
  registry snapshots;
- deployed random-stream execution, host inventory collection and physical
  sensor calibration drivers;
- complete migration of every historical prompt producer and durable consumer
  from V1 to V2;
- target-host performance and soak evidence beyond the bounded qualification
  lanes;
- independent semantic acceptance, operator canary approval, promotion and
  release.

The strict codecs are protocol-specific. They do not turn arbitrary Rust domain
objects into an ambient serialization platform.

## Known limits and non-claims

- `StableId` is bounded to 128 encoded bytes.
- HPTC V1 is bounded to 256 KiB, 4096 collection items and depth 16.
- Product JSON transport is bounded to 64 KiB and depth 16 before parsing.
- Registries admit at most 256 definitions/profiles and 256 KiB aggregate
  ordinary-definition data.
- Numeric signals admit at most 4096 values and reject overflow.
- Manifest text, timestamps, ranges and confidence are explicitly bounded.
- Topology delta and related-module sets use strictly increasing `StableId` order
  and reject producer non-conformance rather than silently sorting.
- V1 prompt bytes are not HPTC and are never relabeled as HPTC.
- Coverage-guided fuzz execution is bounded evidence, not exhaustive proof.
- No type or receipt grants runtime, write, selection, promotion or release
  authority.

Committed prose does not pretend to contain its own current commit SHA. Exact
Git tree/blob provenance, rustdoc API snapshots, generated protocol projections,
diagnostics and qualification receipts are produced for the checked-out
candidate.

## Verification

The consumer qualification executes 24 independent checks and retains every
log. It covers canonical HPTC vectors, manifest vectors, Prompt V2/Topology V1
Python and Node oracles, generated-binding drift, strict Rust product codecs,
complete types/NDU tests, prompt producer and ledger paths, topology admission,
all three manifest product owners, and strict Clippy for types, wire and NDU.

Deep qualification independently requires:

- exact Git blob/tree provenance;
- a Rust-generated protocol catalog and schema-field coverage check;
- rustdoc JSON public-API and semver comparison;
- deterministic mutation/property checks;
- declared MSRV build and tests;
- native tests and strict lint;
- pinned Miri;
- bounded libFuzzer execution for HPTC raw validation and product JSON codecs;
- exact-candidate source-head and synthetic-merge document bundles.

Repository reproduction entrypoints are:

```text
python3 scripts/verify_lane_a_foundation.py verify
python3 scripts/platform_types_public_api.py
python3 codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py
node codex-rs/hepta-types/conformance/verify_platform_wire_vectors.mjs
bash scripts/run_platform_types_consumer_qualification.sh
bash scripts/run_platform_types_deep_qualification.sh <candidate arguments>
```

Until retained source-head and synthetic-merge receipts exist for the current
head, qualification remains `exact_candidate_pending`.

## Integration prerequisites

Prompt producers migrating to V2 must first compute and retain the frozen V1
digest when historical continuity is required, then construct V2 and preserve
its HPTC semantic commitment. No consumer may recompute V1 using V2 rules.

Registered numeric consumers requiring generation-sensitive admission must use
V2 and invoke its verifier with the source signal, target schema and exact
immutable registry snapshot. A V1 receipt must not be treated as generation or
anti-rollback evidence.

Topology producers must provide all set-valued IDs in strictly increasing
`StableId` order. Product consumers accept the validated wrapper rather than a
raw DTO. Manifest producers must preserve the native semantic digest through
transport and storage; final owners must apply their product-specific identity,
authorization, hardware and generation policy before use.
