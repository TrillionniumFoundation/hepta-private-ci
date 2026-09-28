#!/usr/bin/env python3
"""Apply the guarded, one-time platform.types qualification closure patch."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement anchor, found {count}")
    file.write_text(text.replace(old, new), encoding="utf-8")


def insert_before_once(path: str, marker: str, addition: str, sentinel: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if sentinel in text:
        raise SystemExit(f"{path}: insertion already present")
    if text.count(marker) != 1:
        raise SystemExit(f"{path}: insertion anchor drifted")
    file.write_text(text.replace(marker, addition + marker), encoding="utf-8")


def append_once(path: str, addition: str, sentinel: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if sentinel in text:
        raise SystemExit(f"{path}: append already present")
    file.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


def repair_clippy_and_rustdoc() -> None:
    replace_once(
        "codex-rs/hepta-wire/src/platform_manifest_json.rs",
        ".set(index.checked_add(1).ok_or_else(|| StrictJsonError::InvalidValue(field))?);",
        ".set(index.checked_add(1).ok_or(StrictJsonError::InvalidValue(field))?);",
    )
    replace_once(
        "scripts/platform_types_rustdoc_api.py",
        'ID_LIST_KEYS = frozenset({"fields", "variants"})',
        '# Tuple-variant payloads are also Vec<Id>; raw numeric IDs are not stable.\n'
        '    ID_LIST_KEYS = frozenset({"fields", "variants", "tuple"})',
    )

    path = Path("scripts/test_platform_types_rustdoc_api.py")
    text = path.read_text(encoding="utf-8")
    marker = "\n\nif __name__ == \"__main__\":\n"
    if "test_tuple_variant_item_ids_normalize_to_owned_signatures" in text:
        raise SystemExit("rustdoc tuple regression already present")
    if text.count(marker) != 1:
        raise SystemExit("rustdoc test insertion anchor drifted")
    regression = r'''

    def test_tuple_variant_item_ids_normalize_to_owned_signatures(self):
        def with_tuple_variant(value: dict, offset: int) -> dict:
            result = copy.deepcopy(value)
            root = offset
            enum_id = offset + 6
            variant_id = offset + 7
            field_id = offset + 8
            result["index"][str(root)]["inner"]["module"]["items"].append(enum_id)
            result["index"][str(enum_id)] = {
                "id": enum_id,
                "crate_id": 0,
                "name": "TupleError",
                "visibility": "public",
                "inner": {
                    "enum": {
                        "generics": {"params": [], "where_predicates": []},
                        "has_stripped_variants": False,
                        "variants": [variant_id],
                        "impls": [],
                    }
                },
            }
            result["index"][str(variant_id)] = {
                "id": variant_id,
                "crate_id": 0,
                "name": "Wrapped",
                "visibility": "public",
                "inner": {
                    "variant": {
                        "kind": {"tuple": [field_id]},
                        "discriminant": None,
                    }
                },
            }
            result["index"][str(field_id)] = {
                "id": field_id,
                "crate_id": 0,
                "name": None,
                "visibility": "public",
                "inner": {"struct_field": {"primitive": "u64"}},
            }
            result["paths"][str(enum_id)] = {
                "crate_id": 0,
                "path": ["codex_hepta_types", "TupleError"],
                "kind": "enum",
            }
            return result

        first = _Normalizer(with_tuple_variant(document(0), 0)).snapshot()
        shifted = _Normalizer(with_tuple_variant(document(100), 100)).snapshot()
        self.assertEqual(first["items"], shifted["items"])
        self.assertEqual(first["snapshotSha256"], shifted["snapshotSha256"])
'''
    path.write_text(text.replace(marker, regression + marker), encoding="utf-8")


def repair_rama_manifest() -> None:
    replace_once(
        "codex-rs/network-proxy/Cargo.toml",
        '''rama-core = { version = "=0.3.0-alpha.4" }
rama-http = { version = "=0.3.0-alpha.4" }
rama-http-backend = { version = "=0.3.0-alpha.4", features = ["tls"] }
rama-net = { version = "=0.3.0-alpha.4", features = ["http", "tls"] }
rama-socks5 = { version = "=0.3.0-alpha.4" }
rama-tcp = { version = "=0.3.0-alpha.4", features = ["http"] }
rama-tls-rustls = { version = "=0.3.0-alpha.4", features = ["http"] }''',
        '''# Rama prerelease crates share private APIs. Exact direct constraints keep
# Cargo from combining the alpha.4 public crates with incompatible 0.3.0
# stable support crates during a later lock refresh.
rama-core = { version = "=0.3.0-alpha.4" }
rama-error = "=0.3.0-alpha.4"
rama-http = { version = "=0.3.0-alpha.4" }
rama-http-backend = { version = "=0.3.0-alpha.4", features = ["tls"] }
rama-macros = "=0.3.0-alpha.4"
rama-net = { version = "=0.3.0-alpha.4", features = ["http", "tls"] }
rama-socks5 = { version = "=0.3.0-alpha.4" }
rama-tcp = { version = "=0.3.0-alpha.4", features = ["http"] }
rama-tls-rustls = { version = "=0.3.0-alpha.4", features = ["http"] }
rama-utils = "=0.3.0-alpha.4"''',
    )


def repair_registry_indexes() -> None:
    path = "codex-rs/hepta-types/src/registry.rs"
    replace_once(
        path,
        '''/// Bounded immutable in-process registry. There is no global singleton or
/// mutation API; callers construct one generation and pass it explicitly.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractRegistryV1 {
    entries: Vec<RegistryDefinitionV1>,
    numeric_profiles: Vec<NumericProfileDefinitionV1>,
}''',
        '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct RegistryDigestIndexEntryV1 {
    kind: RegistryKindV1,
    digest: Digest32,
    entry_index: usize,
}

/// Bounded immutable in-process registry. There is no global singleton or
/// mutation API; callers construct one generation and pass it explicitly.
/// Private lookup indexes are derived once at construction and never enter the
/// canonical registry digest or any persisted protocol representation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractRegistryV1 {
    entries: Vec<RegistryDefinitionV1>,
    numeric_profiles: Vec<NumericProfileDefinitionV1>,
    digest_index: Vec<RegistryDigestIndexEntryV1>,
}''',
    )
    replace_once(
        path,
        '''        Ok(Self {
            entries,
            numeric_profiles,
        })''',
        '''        let mut digest_index = entries
            .iter()
            .enumerate()
            .map(|(entry_index, entry)| RegistryDigestIndexEntryV1 {
                kind: entry.kind,
                digest: entry.digest,
                entry_index,
            })
            .collect::<Vec<_>>();
        digest_index.sort_unstable_by_key(|entry| {
            (entry.kind, entry.digest, entry.entry_index)
        });
        Ok(Self {
            entries,
            numeric_profiles,
            digest_index,
        })''',
    )
    replace_once(
        path,
        '''        self.entries
            .iter()
            .find(|entry| entry.kind == kind && entry.id == *id && entry.version == version)''',
        '''        let entry_index = self
            .entries
            .binary_search_by(|entry| {
                (entry.kind, entry.id.as_str(), entry.version)
                    .cmp(&(kind, id.as_str(), version))
            })
            .ok()?;
        self.entries.get(entry_index)''',
    )
    replace_once(
        path,
        '''        self.entries
            .iter()
            .find(|entry| entry.kind == kind && entry.digest == digest)''',
        '''        let index_position = self
            .digest_index
            .partition_point(|entry| (entry.kind, entry.digest) < (kind, digest));
        let index_entry = self.digest_index.get(index_position)?;
        if (index_entry.kind, index_entry.digest) != (kind, digest) {
            return None;
        }
        self.entries.get(index_entry.entry_index)''',
    )
    replace_once(
        path,
        '''        self.numeric_profiles
            .iter()
            .find(|definition| definition.profile() == profile)
            .ok_or(RegistryError::UnknownNumericProfile)''',
        '''        let profile_index = self
            .numeric_profiles
            .binary_search_by_key(&profile, |definition| definition.profile())
            .map_err(|_| RegistryError::UnknownNumericProfile)?;
        Ok(&self.numeric_profiles[profile_index])''',
    )
    append_once(
        "codex-rs/hepta-types/src/registry_tests.rs",
        r'''
#[test]
fn derived_indexes_preserve_lookup_and_digest_semantics_at_capacity() {
    let mut entries = (0..MAX_REGISTRY_ENTRIES_V1)
        .map(|index| {
            definition(
                RegistryKindV1::Schema,
                &format!("schema:index-{index}"),
                1,
                &format!("field=value-{index}:u64"),
            )
        })
        .collect::<Vec<_>>();
    let expected = entries.clone();
    entries.reverse();
    let registry = ContractRegistryV1::new(entries)
        .unwrap_or_else(|error| panic!("indexed registry fixture: {error}"));

    for entry in &expected {
        assert_eq!(
            registry.resolve(entry.kind(), entry.id(), entry.version()),
            Some(entry)
        );
        assert_eq!(
            registry.resolve_digest(entry.kind(), entry.digest()),
            Some(entry)
        );
    }

    let reordered = ContractRegistryV1::new(expected)
        .unwrap_or_else(|error| panic!("reordered registry fixture: {error}"));
    assert_eq!(registry.registry_digest(), reordered.registry_digest());
}
''',
        "derived_indexes_preserve_lookup_and_digest_semantics_at_capacity",
    )


def clarify_registry_identity() -> None:
    path = "codex-rs/hepta-types/src/numeric_registry_v2.rs"
    replace_once(
        path,
        '''//! The existing V1 registered receipt remains a content-addressed compatibility
//! receipt. V2 adds a caller-owned monotonic snapshot generation, explicit
//! definition digests and a full recomputation verifier without changing V1.''',
        '''//! The existing V1 registered receipt remains a content-addressed compatibility
//! receipt. V2 adds a caller-owned monotonic snapshot generation, explicit
//! definition digests and a full recomputation verifier without changing V1.
//!
//! Registry identity is the versioned canonical SHA-256 `Digest32` produced by
//! `ContractRegistryV1::registry_digest`. It is a strong semantic content
//! identity, not a signature, publisher authentication, or freshness claim.
//! Product owners authenticate and pin the current generation independently.''',
    )
    replace_once(
        path,
        '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RegistrySnapshotIdentityV1 {''',
        '''/// Owner-selected generation paired with a canonical SHA-256 registry digest.
/// The digest detects semantic content substitution; the owner remains
/// responsible for authentic publication, monotonic advancement and rollback
/// policy.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RegistrySnapshotIdentityV1 {''',
    )


def extend_deep_qualification() -> None:
    path = "scripts/run_platform_types_deep_qualification.sh"
    replace_once(
        path,
        '''  python3 scripts/platform_types_candidate_bundle.py self-test
  python3 scripts/platform_types_public_api.py''',
        '''  python3 scripts/platform_types_candidate_bundle.py self-test
  python3 scripts/platform_types_rama_lock_guard.py
  python3 -m unittest \\
    scripts/test_platform_types_rama_lock_guard.py \\
    scripts/test_platform_types_rustdoc_api.py
  python3 scripts/platform_types_public_api.py''',
    )
    replace_once(
        path,
        '''  bash scripts/run_platform_types_consumer_qualification.sh
  git diff --check''',
        '''  bash scripts/run_platform_types_consumer_qualification.sh
  cargo run --release --locked --manifest-path "$MANIFEST" \\
    --package "$PACKAGE" --bin platform-types-registry-bench -- \\
    100000 "$OUT/registry-benchmark.json"
  git diff --check''',
    )
    replace_once(
        path,
        '''  --evidence "property-report=$OUT/property-report.json"
  --evidence "protocol-catalog=$OUT/protocol-catalog.json"''',
        '''  --evidence "property-report=$OUT/property-report.json"
  --evidence "registry-benchmark=$OUT/registry-benchmark.json"
  --evidence "protocol-catalog=$OUT/protocol-catalog.json"''',
    )


def update_documents() -> None:
    insert_before_once(
        "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
        "## Public symbols and source bindings\n",
        r'''## Acceptance-state ladder and exact owner paths

Completion is represented as separate facts rather than one overloaded boolean:

| Layer | Current meaning |
| --- | --- |
| Contract specified | Normative protocol and technical documents exist. |
| Source implemented | Native constructors, strict codecs and named owner callsites exist in the candidate tree. |
| Focused checks passed | Unit, conformance, strict-lint and dependency-coherence checks pass for that exact checkout. |
| Exact source-head qualified | A retained deep receipt exists for the final source SHA; pending until the hosted lane succeeds. |
| Synthetic merge qualified | A separate retained deep receipt exists for the deterministic merge of the same source/base pair; pending until that lane succeeds. |
| Independently accepted | An eligible non-author approval is bound to the exact final head; separate from technical qualification. |
| Deployed or released | Operator, promotion and release evidence exists; currently not granted by this module. |

The executable source-owner map is deliberately concrete:

| Product boundary | Source path | Validation and owner context |
| --- | --- | --- |
| Registered numeric evaluation | `codex-rs/hepta-ndu/src/owner.rs` | Admits utility axes through the immutable registry and binds the admission digest into the production policy digest. Generation-sensitive callers additionally pin `RegistrySnapshotIdentityV1` and use `verify_for_snapshot`. |
| Random-stream admission | `codex-rs/hepta-ndu/src/random_stream_owner.rs` | Checks root-seed digest, namespace, generator/version, episode, decision and counter window before use. |
| Runtime topology admission | `codex-rs/hepta-supervisor/src/module_runtime.rs` | Calls candidate validation before registering the selected topology; raw DTOs are not the accepted product value. |
| External-system and sensor admission | `codex-rs/hepta-supervisor/src/platform_manifest_admission.rs` | Applies host/authorization or hardware/calibration/clock/failure-policy context before returning deny-only receipts. |
| Prompt production and durable consumption | `codex-rs/hepta-codex-adapter/src/lib.rs`; `codex-rs/hepta-learning-ledger/src/ledger.rs` | Preserves the frozen V1 semantic digest on the compatibility path; V2 migration remains explicitly versioned. |

`ContractRegistryV1` derives immutable binary-search indexes once during
construction for identity, digest and numeric-profile lookups. Those indexes are
private process-local acceleration data: they do not enter canonical registry
bytes, receipts or persistence. The deep lane retains a small/maximum-capacity
lookup benchmark as comparative evidence, with no machine-independent pass
threshold. A timing observation is not deployment or resource acceptance.

Registry identity itself is not a non-cryptographic cache checksum. It is the
versioned canonical SHA-256 `Digest32` of registry semantics. That content identity
detects substitution but does not authenticate a publisher, select the current
generation or grant authority; those remain owner responsibilities.

''',
        "## Acceptance-state ladder and exact owner paths",
    )
    append_once(
        "docs/modules/platform.types/QUALIFICATION_HARDENING_20260928.md",
        r'''## Exact-candidate closure repair

The retained run for source `8376d8426518dc3a2661ce4ba3756d965f13ff64`
failed the same three groups in both source-head and synthetic-merge lanes. The
failure set was not a merge-only conflict and was not accurately described by a
single resource/performance label:

- `truth` and `native` exposed one strict-Clippy error and an incoherent Rama
  prerelease lock selection (`rama-core` alpha.4 with stable `rama-error`);
- `api` exposed raw rustdoc numeric IDs leaking through tuple-variant payloads,
  producing 15 false signature mutations;
- provenance, schema, MSRV, Miri, fuzz and document-bundle checks succeeded for
  that older exact candidate but are not inherited by a later commit.

The repair keeps all Rama family declarations on one exact prerelease, adds an
executable manifest/lock coherence guard and regression suite, normalizes tuple
variant `Vec<Id>` fields, removes the strict-Clippy violation and restores the
lock workflow to `contents: read`. The temporary migration workflow deletes
itself after a race-checked lock regeneration and focused verification; it is not
part of the final qualification architecture.

The immutable registry builds private indexes once at construction and uses
binary search for identity, digest and profile resolution. A bounded benchmark
records small and maximum-capacity lookup observations in each deep-lane artifact.
The benchmark has no universal timing threshold and is not relabeled as production
performance acceptance.

Registry snapshot identity is explicitly the canonical SHA-256 semantic digest
plus caller-owned generation. It is not a signature, authenticated publication,
owner-current freshness proof or authorization. The real NDU and Supervisor
consumer paths remain the acceptance boundary; no parallel demonstration owner
was added.

These source repairs do not mark the final rows above as passed. Only new retained
receipts for the exact repaired source and its deterministic merge may close the
two technical qualification rows. Independent review, deployment and release
remain separate.
''',
        "## Exact-candidate closure repair",
    )


def main() -> None:
    repair_clippy_and_rustdoc()
    repair_rama_manifest()
    repair_registry_indexes()
    clarify_registry_identity()
    extend_deep_qualification()
    update_documents()
    print("platform.types closure repair: source patch applied")


if __name__ == "__main__":
    main()
