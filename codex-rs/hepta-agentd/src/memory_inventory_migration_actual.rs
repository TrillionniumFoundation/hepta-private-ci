//! Transfer new residual bytes through the existing authorized image provider.
//! Receiver and final owner are separate processes on the same physical host.

use std::fs::File;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::{AgentLifecycle, FleetRegistry};
use codex_hepta_memory::{CognitiveAccess, CognitiveScope};
use pretty_assertions::assert_eq;
use serde_json::{Value, json};

use crate::{MemoryCellMigrationPinV9, MemoryCellMigrationStoreV9};
use crate::memory_cell_network::migration_v9_process_tests::{copy_inventory_data, descriptors, inventory_image, transfer_inventory_image};
use crate::memory_inventory_release_test_support::{InventoryReleaseCheckpoint, InventoryReleaseFixture};
use super::cases::save;
use super::process::{RecoverySpec, fleet};

pub(super) async fn transfer(
    output: &Path,
    source_root: &Path,
    registry: &FleetRegistry,
    owner: &AgentId,
    checkpoint: &InventoryReleaseCheckpoint,
) -> (PathBuf, FleetRegistry, RecoverySpec, Value) {
    let record = registry.load_agent(owner).expect("stopped source owner");
    assert_eq!(record.lifecycle.lifecycle, AgentLifecycle::Stopped);
    let store = DurableCognitiveStore::open(&record.layout).await.expect("quiesce actual source database");
    let snapshot = store.memory_inventory_snapshot(&CognitiveAccess::agent_private(owner.clone()), &CognitiveScope::AgentPrivate,
        crate::memory_cell_runtime::now_unix_seconds().expect("clock")).await.expect("complete source cut");
    let anchor = store.recovery_anchor().await.expect("independently retained source anchor");
    let release = InventoryReleaseFixture::reopen(source_root.join("artifacts"), &snapshot, checkpoint.clone());
    let bundle = release.host.load_current().expect("actual residual source selection");
    let pin = MemoryCellMigrationPinV9::from_inventory_source(&snapshot, &bundle, anchor).expect("inventory image pin");
    drop(bundle);
    drop(release);
    let database = store.path().to_path_buf();
    store.close().await;
    for suffix in ["-wal", "-shm", "-journal"] {
        assert!(!PathBuf::from(format!("{}{suffix}", database.display())).exists(), "capture requires a fully quiesced source database");
    }
    let mut files = descriptors(&source_root.join("artifacts"), "artifacts/");
    files.insert("cognitive/cognitive_1.sqlite3".into(), File::open(&database).expect("cold database descriptor"));
    let image = inventory_image(pin.clone(), files);
    let migration_root = output.join("inventory-migration");
    std::fs::create_dir(&migration_root).expect("new migration evidence root");
    std::fs::set_permissions(&migration_root, std::fs::Permissions::from_mode(0o700)).expect("private migration root");
    std::fs::write(migration_root.join("source.image"), image.bytes()).expect("exact transferred image");
    let image_store = migration_root.join("received");
    let (transport, intent) = transfer_inventory_image(&migration_root, &image_store, &record.layout, &image).await;
    let received = MemoryCellMigrationStoreV9::open(image_store, image.manifest().clone()).expect("committed received image");
    let data = received.committed_image(&intent.payload_sha256).expect("verified complete received image");
    let destination = output.join("migrated-owner");
    std::fs::create_dir(&destination).expect("independent destination root");
    let (destination_registry, destination_owner) = fleet(&destination);
    assert_eq!(&destination_owner, owner);
    let target = destination_registry.load_agent(owner).expect("registered destination owner");
    let mut copied = copy_inventory_data(&data.join("cognitive"), target.layout.cognitive_root());
    copied.extend(copy_inventory_data(&data.join("artifacts"), &destination.join("artifacts")));
    drop(received);
    let unavailable = output.join("quiesced-source-retained");
    std::fs::rename(source_root, &unavailable).expect("make original source root unavailable before target startup");
    assert!(!source_root.exists());
    let evidence = json!({
        "schema":"hepta.memory.inventory-migration-actual.v1","transport_profile":"existing_authorized_TaskFlow_provider_same_host_TCP",
        "pin":pin,"image_digest":image.digest(),"image_manifest":image.manifest(),"transport":transport,
        "destination_root":destination,"original_source_absent":source_root,"retained_source_evidence":unavailable,"copied_files":copied,
        "destination_admission":"fresh child must independently verify exact recovery anchor and signed inventory selection",
    });
    save(&migration_root.join("MIGRATION.json"), &evidence);
    (destination, destination_registry, RecoverySpec { pin, unavailable_source:source_root.to_path_buf(), withdrawal:None }, evidence)
}
