# platform.types: implementation design

Parent: `docs/modules/platform.types/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: bounded/profiled identity, canonical digest, immutable registry and
numeric-conversion source implemented; independent product execution and
acceptance remain separate gates. Common requirements:
`../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and
package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-types`.
Packages: `PLATFORM-0-TYPE-BOUNDARY`.

The operations below are native V1 APIs. They carry no runtime, production,
effect, selection, promotion or release authority.

## 2. Public operations and contract details

`validate_id(raw, id_profile) -> StableId | IdentityError` checks byte count,
profile alphabet and canonical representation before allocating the accepted
owned value. `canonical_digest_v1(type_id, schema_version, fields) -> Digest32`
applies the frozen `HPTC` domain-separated, typed and length-framed V1 encoding;
field/map ordering is canonical and arrays retain semantic order.
`rescale_signal_registered(value, target_profile, registry) -> (signal,
ConversionReceipt) | NumericError` uses checked wide arithmetic, the target
rounding rule and an explicitly resolved immutable normalization contract.
Schema version and numeric/ID profile are values, not ambient globals.

## 3. State records and transaction design

No authoritative state, clocks, credentials, filesystem handles or
process-global mutable registries. `ContractRegistryV1` is an immutable bounded
input for one caller generation. `RegistryDefinitionV1` binds kind, ID,
version and definition text to a canonical digest. A `ConversionReceipt`
contains source/target profile IDs, input/output digests and a rational
absolute-error bound. Authority/fence identifiers are exact integers or opaque
IDs and never pass through approximate rescaling.

## 4. Deterministic algorithm and scheduling

Validate profile, shape and limits; validate units and normalization identity;
resolve the normalization definition when using the registered boundary;
compute with checked intermediates; apply only the named rounding; canonical
encode and hash. Do not implicitly normalize invalid IDs into valid identities.
`AuthorityPosture` is sealed deny-only, so this module cannot represent a
grant.

## 5. Capacity and performance profile

Numeric conversion batch <= 4096 values; identifier <= 128 encoded bytes;
canonical encoding <= 256 KiB; canonical container <= 4096 items and depth <=
16; immutable registry <= 256 definitions; one definition <= 4096 UTF-8 bytes.
No network/SQL dependencies.

These are enforced source limits, not target-host latency measurements.
Performance measurements and product composition remain separate evidence.

## 6. Concrete verification cases

- TYPES-01: positive and negative half ties reproduce ties-to-even (+2.5 -> 2,
  -3.5 -> -4).
- TYPES-02: same number in ppm and Q24 has distinct source digests and a valid
  conversion receipt.
- TYPES-03: overflow, unknown profile/unit/normalization mismatch reject;
  authority posture cannot represent a grant.
- TYPES-04: Rust/Python/TypeScript canonical V1 golden encoding agrees
  byte-for-byte and on SHA-256.

The repository now contains native test identities and a frozen
`CANONICAL_V1_CONFORMANCE.json`. Exact-head and synthetic-merge workflow
success remain the execution receipts for a candidate.

## 7. Integration, rollback and capability ceiling

Shared type changes land through the contract integrator before consumer PRs.
V1 canonical bytes and ID profile semantics never change in place. Rollback
restores compatible readers/profile versions; it never silently reinterprets a
stored commitment.

Repository qualification cannot self-grant operator acceptance, promotion or
release.

## 8. Current native implementation

- **Implemented entrypoints:** `validate_id` in [codex-rs/hepta-types/src/identity.rs](../../../codex-rs/hepta-types/src/identity.rs); `canonical_digest_v1` in [codex-rs/hepta-types/src/canonical_digest.rs](../../../codex-rs/hepta-types/src/canonical_digest.rs); `ContractRegistryV1` in [codex-rs/hepta-types/src/registry.rs](../../../codex-rs/hepta-types/src/registry.rs); `rescale_signal` in [codex-rs/hepta-types/src/numeric_conversion.rs](../../../codex-rs/hepta-types/src/numeric_conversion.rs); `rescale_signal_registered` in [codex-rs/hepta-types/src/numeric_conversion.rs](../../../codex-rs/hepta-types/src/numeric_conversion.rs).
- **State and recovery:** Stateless native values plus caller-owned immutable registry generations. Canonical V1 framing is bounded and deterministic; numeric conversion checks i128 intermediates and returns an exact rational error bound with no saturation.
- **Source tests:** [codex-rs/hepta-types/src/canonical_digest_tests.rs](../../../codex-rs/hepta-types/src/canonical_digest_tests.rs), [codex-rs/hepta-types/src/registry_tests.rs](../../../codex-rs/hepta-types/src/registry_tests.rs), [codex-rs/hepta-types/src/numeric_conversion_tests.rs](../../../codex-rs/hepta-types/src/numeric_conversion_tests.rs), [codex-rs/hepta-types/src/identity_tests.rs](../../../codex-rs/hepta-types/src/identity_tests.rs), [codex-rs/hepta-types/src/bounded_tests.rs](../../../codex-rs/hepta-types/src/bounded_tests.rs), [codex-rs/hepta-types/src/fixed_tests.rs](../../../codex-rs/hepta-types/src/fixed_tests.rs). These are source test identities, not candidate execution receipts.
- **Implementation and operating references:** [codex-rs/hepta-types/CANONICAL_DIGEST_V1.md](../../../codex-rs/hepta-types/CANONICAL_DIGEST_V1.md), [codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json](../../../codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json), [codex-rs/hepta-types/NUMERIC_SIGNAL_CONVERSION.md](../../../codex-rs/hepta-types/NUMERIC_SIGNAL_CONVERSION.md).
- **Remaining work:** generated cross-language bindings, named product-execution evidence and external operator/acceptance gates remain outside this source-only module closure.
