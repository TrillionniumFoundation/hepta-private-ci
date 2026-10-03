# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is the authority-free Rust contract library for shared
Hepta values. Current source implements bounded values and identities, HPTC V1,
checked Q32 arithmetic, immutable contract registries, pure and
registry-admitted numeric conversion, versioned prompt-delivery observations,
runtime-topology candidates, and the random-stream, external-system and
sensor-calibration manifest families.

Compatibility is versioned rather than silently reinterpreted:

- `PromptDeliveryObservationV1` keeps its historical custom byte commitment;
- `PromptDeliveryObservationV2` is a distinct private-field HPTC semantic
  commitment and may carry the exact V1 digest as an explicit migration witness;
- `RegisteredNumericConversionReceiptV1` remains readable compatibility
  evidence;
- V2 registry admission binds an explicit registry generation and digest,
  source/target profile-definition digests, normalization-definition digest and
  canonical base conversion-receipt digest;
- `verify_for_snapshot` additionally requires an independently owner-pinned
  `RegistrySnapshotIdentityV1`, so a valid older-generation or wrong-registry
  receipt cannot satisfy the current owner policy.

`platform.wire` now owns strict JSON transport for Prompt V2, Topology V1 and
all three manifest protocols. Each codec applies raw resource limits and
duplicate/unknown/missing-field rejection before reconstructing the native
private-field contract through its validated constructor. JSON bytes are
transport only; the native HPTC semantic commitment remains the cross-owner
identity.

The exact current-state correction to the stable architecture guide is
`docs/modules/platform.types/TECHNICAL_CURRENT_AMENDMENT_V2.md`. The full
protocol boundary is
`docs/modules/platform.types/PROTOCOL_AND_QUALIFICATION_V1.md`.

The closed-world top-level ownership projection remains in
`docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json`. It covers every
exact `pub use` export and every exact public `pub mod` declaration in
`codex-rs/hepta-types/src/lib.rs`; adding either form without assigning an
operation owner fails verification. It is not described as the complete nested
Rust API. Exact-candidate public modules, types, methods, fields, enum variants
and signatures are derived from rustdoc JSON and compared against the PR base.
The module truth state remains in
`docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json`.

## Public symbols and source bindings

Core semantic source bindings are:

- bounded values: `src/bounded.rs`;
- identities and deny-only authority posture: `src/identity.rs`;
- digest and HPTC primitives: `src/digest.rs` and `src/canonical_digest.rs`;
- Q32 values: `src/fixed.rs`;
- immutable registry and numeric profiles: `src/registry.rs` and
  `src/numeric_profile.rs`;
- V1 conversion and compatibility receipt: `src/numeric_conversion.rs`;
- generation-bound V2 admission, owner-pinned snapshot verification and private
  receipt: `src/numeric_registry_v2.rs`;
- frozen Prompt V1: `src/prompt_delivery.rs`;
- HPTC Prompt V2 and V1 migration witness: `src/prompt_delivery_v2.rs`;
- topology candidates: `src/topology.rs`;
- the three manifest families: `src/manifests.rs`;
- typed normative field/version catalog: `src/protocol_catalog_v2.rs`.

Product transport source bindings are:

- Prompt V2 and Topology V1 strict codecs:
  `codex-rs/hepta-wire/src/platform_types_json.rs`;
- Random Stream, External System and Sensor Calibration strict codecs:
  `codex-rs/hepta-wire/src/platform_manifest_json.rs`;
- public codec exports: `codex-rs/hepta-wire/src/lib.rs`.

The transport layer bounds raw input at 64 KiB and nesting depth 16, rejects
duplicate and unknown fields, requires precision-safe canonical decimal strings
for i64/u64 fields and revalidates native semantics. Topology decoding returns
`ValidatedRuntimeTopologyCandidateV1` only after candidate-digest
recomputation.

Named source consumers include:

- Codex/Agentd and Learning Ledger for the frozen Prompt V1 compatibility path;
- Runtime Supervisor for validated topology admission;
- authenticated NDU owner for registry-admitted numeric signals;
- NDU random-stream owner for namespace, generator/version, episode, decision
  and counter-window binding;
- Runtime Supervisor external-system owner for system/class, host identity and
  authorization-witness binding;
- Runtime Supervisor sensor owner for sensor/class, hardware or adapter,
  calibration generation, clock domain and failure-policy binding.

These callsites prove source composition and owner-bound admission. They do not
prove deployed product activation.

## Durability and activation

`platform.types` is stateless. It owns no clock, filesystem path, network,
credential, mutable global registry, journal, recovery worker, durable writer,
model call or external effect. Registry snapshots are immutable caller-owned
inputs. V2 records and verifies the caller-selected generation/digest pair but
does not authenticate, publish or advance that generation.

Product-owner admission receipts remain `NonAuthorizingPosture::DENY_ALL`.
Randomness execution, host inventory collection, sensor operation, registry
publication and durable storage stay with their existing owners.

Production implementation, deployment qualification, activation and release
remain false until both the final exact source head and deterministic synthetic
merge produce retained authoritative receipts and the separate governance gates
pass.

## Target-only design

The following remain outside this module's present source claim:

- authenticated publication, rotation and advancement of current registry
  snapshots;
- deployed random-stream execution, host inventory collection and physical
  sensor calibration drivers;
- complete migration of every historical Prompt producer and durable consumer
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
- Canonical i64/u64 decimal transport strings are bounded to 20 bytes and then
  native-range checked.
- Registries admit at most 256 definitions/profiles and 256 KiB aggregate
  ordinary-definition data.
- Numeric signals admit at most 4096 values and reject overflow.
- Manifest text, timestamps, ranges and confidence are explicitly bounded.
- Topology delta and related-module sets use strictly increasing `StableId` order
  and reject producer non-conformance rather than silently sorting.
- Prompt V1 bytes are not HPTC and are never relabeled as HPTC.
- `verify_for_snapshot` proves equality with an owner-pinned snapshot; it does
  not mint or authenticate the current snapshot.
- Coverage-guided fuzz execution is bounded evidence, not exhaustive proof.
- No type, codec or receipt grants runtime, write, selection, promotion or
  release authority.

Committed prose and detailed source maps do not pretend to contain their own
current commit SHA. Historical `sourceBase` and `observedAtHead` values are
non-authoritative provenance. Exact Git commit/tree identity and the SHA-256
digests of the committed public inventory and detailed implementation map are
emitted at runtime for the checked-out source-head or synthetic-merge candidate;
the two candidate kinds are never interchangeable.

## Verification

The consumer qualification executes 24 independent checks and retains every
log. It covers canonical HPTC vectors, manifest vectors, Prompt V2/Topology V1
Python and Node oracles, generated-binding drift, strict Rust product codecs for
all five contracts, complete types/NDU tests, prompt producer and ledger paths,
topology admission, all three manifest product owners, and strict Clippy for
types, wire and NDU.

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

Merge governance is checked separately by
`.github/workflows/platform-types-independent-review.yml`. It requires a formal
approval bound to the exact current head from a repository owner, member or
collaborator who is neither the PR author nor an author or committer of any
candidate commit. Stale approvals, bots, outsiders, dismissed reviews and a
latest decisive changes-requested state fail closed. Review evidence is not a
qualification receipt.

Repository reproduction entrypoints are:

```text
python3 scripts/verify_lane_a_foundation.py verify
python3 scripts/platform_types_public_api.py
python3 codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py
node codex-rs/hepta-types/conformance/verify_platform_wire_vectors.mjs
bash scripts/run_platform_types_consumer_qualification.sh
bash scripts/run_platform_types_deep_qualification.sh <candidate arguments>
python3 scripts/test_platform_types_independent_review.py
```

Until retained source-head and synthetic-merge receipts exist for the final
head, qualification remains `exact_candidate_pending`.

## Integration prerequisites

Prompt producers migrating to V2 must first compute and retain the frozen V1
digest when historical continuity is required, then construct V2 and preserve
its HPTC semantic commitment. No consumer may recompute V1 using V2 rules.

Registered numeric consumers requiring generation-sensitive admission must use
V2, independently pin the current `RegistrySnapshotIdentityV1`, and invoke
`verify_for_snapshot` with the source signal, target schema and exact immutable
registry. A V1 receipt, or a V2 receipt verified only against its embedded
snapshot, must not be treated as owner-current anti-rollback evidence.

Topology producers must provide all set-valued IDs in strictly increasing
`StableId` order. Product consumers accept the validated wrapper rather than a
raw DTO.

All manifest transport users must use the `platform.wire` product codecs rather
than duplicating JSON projection logic. Manifest producers preserve the native
HPTC semantic commitment through transport and storage; final owners then apply
their product-specific identity, authorization, hardware and generation policy
before use.
