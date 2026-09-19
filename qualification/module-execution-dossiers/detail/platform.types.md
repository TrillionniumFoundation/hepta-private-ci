# platform.types: implementation design

Parent: `docs/modules/platform.types/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: bounded values, profiled identity, canonical digest framing, immutable
schema/normalization registry and numeric-conversion source implemented;
generated bindings, named product composition and independent acceptance remain
separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and
`../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-types`.
Packages: `PLATFORM-0-TYPE-BOUNDARY`.

Operation signatures below describe the native V1 contract. Preserve existing
stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`validate_id(raw, id_profile) -> StableId | InvalidId` checks byte count,
alphabet and profile namespace without allocating a second unrestricted copy.
V1 profiles preserve the legacy StableId grammar and add explicit namespaced,
execution, schema, normalization, receipt and artifact forms. Validation never case-folds or
normalizes invalid user IDs into valid identities.

`rescale_signal(source, target) -> (NumericSignalV1, ConversionReceipt) |
NumericError` uses checked wide arithmetic and the target rounding rule.
`rescale_signal_registered(source, target, registry)` additionally requires
the normalization digest to resolve to an immutable registered
`Normalization` definition.

`canonical_digest_v1(type_id, schema_version, fields) -> Digest32` applies the
frozen V1 domain prefix and length-delimited typed encoding. Top-level fields
and maps are canonicalized by UTF-8 byte ordering; arrays retain semantic
order. Schema version is part of the digest input, not an ambient global.

`ContractRegistryV1::require(kind, digest)` resolves a caller-supplied,
immutable, bounded definition set. It does not mutate, discover over the
network, or establish production trust.

## 3. State records and transaction design

No authoritative state, clocks, credentials, filesystem handles or
process-global mutable registries. Numeric-profile and contract-definition
registries are immutable inputs. A conversion receipt contains source/target
profile IDs, input/output digests and a rational absolute-error bound. `AuthorityPosture` itself is deny-only by construction, and new Platform Types
receipts use the likewise deny-only `NonAuthorizingPosture`. Raw protocol
authority flags must be validated by their owning protocol before shared typed
values are constructed; no Platform Types value can be widened into authority.

Authority/fence identifiers are exact integers or opaque IDs and must never
pass through approximate rescaling.

## 4. Deterministic algorithm and scheduling

Validate identity/version/size first; decode into exact primitive types; resolve
required definition digests; validate units and scale; compute with checked
intermediates; apply only the named rounding/projection; encode and hash.
Canonical digest input is domain-separated, typed and length-framed so
concatenation ambiguity cannot collapse distinct field tuples.

Do not implicitly normalize user IDs. Compile-time ownership keeps
non-authorizing outputs unrepresentable as authority-bearing values.

## 5. Capacity and performance profile

Pilot scalar conversion batch <= 4096 values; identifier <= 128 encoded bytes;
canonical digest encoding <= 256 KiB; immutable registry <= 256 entries, <= 16
KiB per definition and <= 256 KiB aggregate definition bytes; no network/SQL
dependencies. Canonical arrays/maps are bounded to 4096 items and nesting to
eight levels.

Pilot ceilings are deterministic contract bounds, not host measurements.
Stricter consumer limits prevail. Bind actual host measurements before
production composition; stateless modules prove absence rather than inventing
state.

## 6. Concrete verification cases

- TYPES-01: positive and negative half ties reproduce ties-to-even (+2.5 -> 2,
  -3.5 -> -4).
- TYPES-02: same number in ppm and Q24 has distinct source bytes/profile digests
  and a valid conversion receipt.
- TYPES-03: overflow, unknown profile, unresolved normalization and unit
  mismatch reject; authority IDs are not accepted by approximate conversion.
- TYPES-04: Rust/Python/Node reconstruct the frozen canonical-digest V1 bytes
  independently and agree byte-for-byte and digest-for-digest.
- TYPES-05: StableId hits 128 bytes exactly, rejects 129, exhaustively checks the
  ASCII alphabet, and profiled namespaces reject cross-profile substitution.
- TYPES-06: non-authorizing receipt posture cannot be constructed from a legacy
  posture with any granted flag.

Source test identities and frozen vectors are current repository evidence.
Exact-head and deterministic synthetic-merge execution remain candidate-bound
workflow receipts, not static documentation claims.

## 7. Integration, rollback and capability ceiling

Shared type changes land through the contract integrator before consumer PRs.
Freeze canonical vectors for affected languages and protocol versions. Rollback
restores compatible readers and profile versions; it never silently reinterprets
stored numeric or canonical bytes.

Immediate revocation/stop remains effective across frozen snapshots. Preserve
every applicable external gate; no generator self-acceptance, self-merge or
self-release. Generated bindings, product caller composition, target-host
qualification, operator acceptance, promotion and release are not granted by
this source package.

## 8. Current native implementation

- **Implemented entrypoints:** `rescale_signal` in [codex-rs/hepta-types/src/numeric_conversion.rs](../../../codex-rs/hepta-types/src/numeric_conversion.rs); `rescale_signal_registered` in [codex-rs/hepta-types/src/numeric_conversion.rs](../../../codex-rs/hepta-types/src/numeric_conversion.rs); `validate_id` in [codex-rs/hepta-types/src/identity.rs](../../../codex-rs/hepta-types/src/identity.rs); `canonical_digest_v1` in [codex-rs/hepta-types/src/canonical_digest.rs](../../../codex-rs/hepta-types/src/canonical_digest.rs); `ContractRegistryV1::require` in [codex-rs/hepta-types/src/registry.rs](../../../codex-rs/hepta-types/src/registry.rs).
- **State and recovery:** Stateless native values and immutable caller-owned registries. NumericSignalV1 digests bind profile, unit, shape, normalization and raw values; conversion checks i128 intermediates and returns an exact rational error bound, with no saturation.
- **Canonical compatibility:** [docs/lane-a-foundation/platform.types/CANONICAL_DIGEST_V1.json](../../../docs/lane-a-foundation/platform.types/CANONICAL_DIGEST_V1.json) freezes the V1 byte vector; Rust, Python and Node reconstruct it independently.
- **Source tests:** [codex-rs/hepta-types/src/bounded_tests.rs](../../../codex-rs/hepta-types/src/bounded_tests.rs), [codex-rs/hepta-types/src/identity_tests.rs](../../../codex-rs/hepta-types/src/identity_tests.rs), [codex-rs/hepta-types/src/digest_tests.rs](../../../codex-rs/hepta-types/src/digest_tests.rs), [codex-rs/hepta-types/src/fixed_tests.rs](../../../codex-rs/hepta-types/src/fixed_tests.rs), [codex-rs/hepta-types/src/canonical_digest_tests.rs](../../../codex-rs/hepta-types/src/canonical_digest_tests.rs), [codex-rs/hepta-types/src/registry_tests.rs](../../../codex-rs/hepta-types/src/registry_tests.rs), [codex-rs/hepta-types/src/numeric_conversion_tests.rs](../../../codex-rs/hepta-types/src/numeric_conversion_tests.rs).
- **Implementation and operating references:** [codex-rs/hepta-types/CANONICAL_DIGEST_V1.md](../../../codex-rs/hepta-types/CANONICAL_DIGEST_V1.md), [codex-rs/hepta-types/NUMERIC_SIGNAL_CONVERSION.md](../../../codex-rs/hepta-types/NUMERIC_SIGNAL_CONVERSION.md), [docs/lane-a-foundation/platform.types/PRIMITIVES_V1.md](../../../docs/lane-a-foundation/platform.types/PRIMITIVES_V1.md).
- **Remaining work:** Generated language bindings, production numeric-profile admission, named consumer/wire composition and independent acceptance. Cross-language canonical vector parity does not by itself establish arbitrary product wire compatibility.
