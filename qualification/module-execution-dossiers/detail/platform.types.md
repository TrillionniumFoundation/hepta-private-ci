# platform.types: implementation design

Parent: `docs/modules/platform.types/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: bounded identity, digest and numeric-conversion source implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-types`.
Packages: `PLATFORM-0-TYPE-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`validate_id(raw, id_profile) -> StableId | InvalidId` checks byte count, alphabet and normalized representation without allocating a second unrestricted copy. `rescale(value, source_profile, target_profile) -> ConversionReceipt | NumericError` uses checked wide arithmetic and the target rounding rule. `canonical_digest(type_id, schema_version, fields) -> Digest32` applies domain separation and length-delimits variable fields; map ordering is canonical and arrays retain semantic order. Schema version and numeric profile are part of the digest input, not ambient globals.

## 3. State records and transaction design

No authoritative state, clocks, credentials, filesystem handles or process-global mutable registries. Numeric-profile definitions are immutable inputs. A `ConversionReceipt` contains source/target profile IDs, input/output digests and a rational absolute-error bound. Authority/fence identifiers are exact integers or opaque IDs and must never pass through approximate rescaling.

## 4. Deterministic algorithm and scheduling

Validate shape and limits; decode into exact primitive types; validate units and scale; compute with checked intermediates; apply only the named rounding/projection; encode and hash. Do not implicitly normalize invalid user IDs into valid identities. Compile-time ownership keeps authority-bearing types opaque to consumers.

## 5. Capacity and performance profile

Pilot scalar conversion batch <= 4096 values; string identifier <= the existing StableId bound; serialized primitive collection <= 256 KiB; no network/SQL dependencies. Record allocations per decode and numeric conversion separately.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- TYPES-01: positive and negative half ties reproduce ties-to-even (+2.5 -> 2, -3.5 -> -4).
- TYPES-02: same number in ppm and Q24 has distinct source bytes/profile digests and a valid conversion receipt.
- TYPES-03: overflow, unknown profile and unit mismatch reject; authority IDs are not accepted by approximate conversion.
- TYPES-04: Rust/Python/TypeScript golden encodings agree byte-for-byte for the declared wire representation.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Shared type changes land through the contract integrator before consumer PRs. Freeze generated type hashes for all affected lanes; rollback restores compatible readers and profile versions, never silently reinterprets stored numeric bytes.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `rescale_signal`, `StableId`, `validate_id`,
  `canonical_encode_v1`, `canonical_digest_v1`, deny-all
  `AuthorityPosture::from_untrusted_bits`, and the bounded
  `SchemaNormalizationRegistryV1` register/resolve contract.
- **Canonical semantics:** V1 domain separation, mandatory nonzero semantic schema
  version, named/type-tagged length framing, sorted unique field names,
  big-endian integers and a 256 KiB collection ceiling
  are executable in `src/canonical.rs`.
- **Identity semantics:** `IdProfileV1` binds exact execution/schema/receipt/
  artifact/producer/normalization namespaces without normalization or nested
  namespace separators.
- **State and recovery:** No authoritative state or recovery surface. The
  schema/normalization registry is bounded host-owned memory only; durability
  remains a separate host concern.
- **Source tests:** canonical, identity, bounded, digest, fixed-point, registry and
  numeric conversion unit suites. Frozen canonical vectors live at
  `codex-rs/hepta-types/testdata/canonical_digest_v1_vectors.json` and are
  independently reconstructed by Python and TypeScript scripts.
- **Qualification:** `.github/workflows/lane-a-foundation.yml` runs exact-head
  source/native checks and a deterministic synthetic-merge job, retaining both
  receipt sets as Actions artifacts. Source documents do not self-assert those
  execution receipts.
- **Remaining work:** generated bindings, durable/runtime registry integration,
  product consumer composition, independent acceptance, activation, promotion
  and release remain outside this native library closure.
