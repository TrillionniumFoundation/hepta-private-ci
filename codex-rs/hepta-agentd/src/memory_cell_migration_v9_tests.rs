use std::collections::BTreeMap;
use std::fs::File;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::*;

#[path = "memory_cell_migration_v9_concurrency_tests.rs"]
mod concurrency_tests;

fn image(
    directory: &std::path::Path,
    generation: u64,
    previous: Option<Sha256Digest>,
) -> MemoryCellMigrationImageV9 {
    let path = directory.join(format!("input-{generation}.json"));
    std::fs::write(&path, format!("{{\"memory\":{generation}}}")).expect("input bytes");
    let owner = AgentId::parse("00000000-0000-4000-9000-000000000001").expect("owner");
    let digest = ContractDigestV1::from_digest(Digest32::of_bytes(b"protocol-fixture-only"))
        .expect("digest");
    let pin = MemoryCellMigrationPinV9 {
        owner_agent_id: owner.clone(),
        scope: ContractIdV1::new("scope:protocol").expect("scope"),
        owner_cut_digest: digest,
        generation: ContractGenerationV1::new(1).expect("generation"),
        bundle_digest: digest,
        cognitive_anchor: CognitiveRecoveryAnchor {
            profile: "protocol-fixture-not-a-database".into(),
            owner_agent_id: owner,
            schema_digest: Sha256Digest::for_bytes(b"schema"),
            state_digest: Sha256Digest::for_bytes(b"state"),
        },
    };
    MemoryCellMigrationImageV9::capture(
        "memory:node-b".into(),
        generation,
        previous,
        pin,
        BTreeMap::from([(
            "facts/input.json".into(),
            File::open(path).expect("descriptor"),
        )]),
    )
    .expect("image")
}

fn intent(image: &MemoryCellMigrationImageV9, key: &str) -> ProviderEffectIntent {
    ProviderEffectIntent::new(
        ProviderEffectKey::for_logical_effect("memory:node-b", key).expect("key"),
        image.digest(),
    )
}

#[test]
fn migration_v9_reopens_prepared_and_current_commits_and_deduplicates() {
    for cut in ["received", "prepared", "current"] {
        let temp = tempfile::tempdir().expect("root");
        let root = temp.path().canonicalize().expect("canonical");
        let image = image(&root, 1, None);
        let intent = intent(&image, "transfer");
        let store =
            MemoryCellMigrationStoreV9::open(root.join("receiver"), image.manifest().clone())
                .expect("store");
        let interrupted = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            store.commit(&intent, image.bytes(), &mut |stage| {
                assert_ne!(stage, cut, "injected checkpoint interruption");
            })
        }));
        assert!(interrupted.is_err());
        drop(store);
        let store =
            MemoryCellMigrationStoreV9::open(root.join("receiver"), image.manifest().clone())
                .expect("durable recovery");
        let before = store.lookup(&intent).expect("status");
        let receipt = store
            .commit(&intent, image.bytes(), &mut |_| {
                panic!("duplicate must not reexecute stages")
            })
            .expect("dedupe");
        assert_eq!(before, ProviderEffectLookup::Ack(receipt));
        let destination = store
            .committed_image(&image.digest())
            .expect("committed image");
        assert_eq!(
            std::fs::read(destination.join("facts/input.json")).expect("readback"),
            b"{\"memory\":1}"
        );
    }
}

#[test]
fn migration_v9_rejects_corruption_conflicting_keys_and_stale_vectors() {
    let temp = tempfile::tempdir().expect("root");
    let root = temp.path().canonicalize().expect("canonical");
    let first = image(&root, 1, None);
    let first_intent = intent(&first, "transfer");
    let store = MemoryCellMigrationStoreV9::open(root.join("receiver"), first.manifest().clone())
        .expect("store");
    let mut corrupt = first.bytes().to_vec();
    *corrupt.last_mut().expect("nonempty") ^= 1;
    let wrong =
        ProviderEffectIntent::new(first_intent.key.clone(), Sha256Digest::for_bytes(&corrupt));
    assert!(
        store
            .commit(&wrong, &corrupt, &mut |_| panic!(
                "bad image must not write"
            ))
            .is_err()
    );
    assert_eq!(
        store.lookup(&wrong).expect("absent"),
        ProviderEffectLookup::NotFound
    );
    store
        .commit(&first_intent, first.bytes(), &mut |_| {})
        .expect("first");
    assert!(matches!(
        store.lookup(&wrong).expect("conflict"),
        ProviderEffectLookup::Conflict { .. }
    ));
    drop(store);
    let successor = image(&root, 2, Some(first.digest()));
    let successor_intent = intent(&successor, "successor");
    let store =
        MemoryCellMigrationStoreV9::open(root.join("receiver"), successor.manifest().clone())
            .expect("successor store");
    store
        .commit(&successor_intent, successor.bytes(), &mut |_| {})
        .expect("successor");
    assert!(store.committed_image(&first.digest()).is_err());
    assert!(matches!(
        store.lookup(&first_intent).expect("historical completion"),
        ProviderEffectLookup::Ack(_)
    ));
    drop(store);
    assert!(
        MemoryCellMigrationStoreV9::open(root.join("receiver"), first.manifest().clone()).is_err()
    );
}
