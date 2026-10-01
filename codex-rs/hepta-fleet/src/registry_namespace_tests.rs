use std::fs;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::*;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

fn fixture() -> (tempfile::TempDir, FleetRegistry, AgentRecord, AgentRecord) {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp.path().canonicalize().expect("canonical root");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let mut records = Vec::new();
    for (index, id) in [
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
        "019153a4-3088-7e03-a56a-9b1964f75dd3",
    ]
    .iter()
    .enumerate()
    {
        let workspace = root.join(format!("workspace-{index}"));
        fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(*id).expect("id"),
            WorkspaceBinding::new(&workspace, &fleet_root).expect("binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        records.push(registry.register(manifest).expect("register"));
    }
    let second = records.pop().expect("second record");
    let first = records.pop().expect("first record");
    (temp, registry, first, second)
}

#[test]
fn unsafe_peer_namespace_is_rejected_before_legacy_migration_side_effects() {
    let (_temp, registry, first, peer) = fixture();
    fs::remove_dir(peer.layout.matrix_secrets_root()).expect("legacy secrets missing");
    fs::remove_dir(peer.layout.matrix_root()).expect("legacy matrix missing");
    fs::set_permissions(peer.layout.agent_root(), fs::Permissions::from_mode(0o777))
        .expect("unsafe peer root");
    assert!(FleetRegistry::open_existing(registry.layout.fleet_root().clone()).is_err());
    assert!(!peer.layout.matrix_root().exists());
    assert!(registry.load().is_err());
    assert_eq!(
        registry
            .load_agent(&first.manifest.agent_id)
            .expect("safe local read"),
        first
    );
}

#[test]
fn unsafe_peer_control_files_are_rejected_without_affecting_local_read() {
    let (_temp, registry, first, peer) = fixture();
    for path in [
        peer.layout.agent_config().to_path_buf(),
        lifecycle_path(peer.layout.run_root(), 0),
        peer.layout
            .releases_root()
            .join("release-state-00000000000000000000.json"),
    ] {
        fs::set_permissions(&path, fs::Permissions::from_mode(0o666)).expect("unsafe control file");
        assert!(registry.load().is_err());
        assert_eq!(
            registry
                .load_agent(&first.manifest.agent_id)
                .expect("safe local read"),
            first
        );
        fs::set_permissions(path, fs::Permissions::from_mode(0o644)).expect("restore control file");
    }
    registry.load().expect("restored native catalog");
}

#[test]
fn sticky_ancestor_and_retained_hardlinks_preserve_native_catalog_recovery() {
    let (temp, registry, _first, peer) = fixture();
    for path in [
        lifecycle_path(peer.layout.run_root(), 0),
        peer.layout
            .releases_root()
            .join("release-state-00000000000000000000.json"),
    ] {
        fs::hard_link(&path, path.with_file_name(".retained-publication.tmp"))
            .expect("crash publication residue");
    }
    let expected = registry.load().expect("hardlink recovery");
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(FleetRegistry::open_existing(registry.layout.fleet_root().clone()).is_err());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o1777))
        .expect("trusted sticky ancestor");
    let reopened = FleetRegistry::open_existing(registry.layout.fleet_root().clone())
        .expect("sticky namespace");
    assert_eq!(reopened.load().expect("native catalog recovery"), expected);
}

#[test]
fn root_reader_preserves_nonroot_fleet_owner_and_rejects_foreign_control_owner() {
    let (temp, registry, first, _peer) = fixture();
    if fs::metadata(temp.path()).expect("fixture owner").uid() != 0 {
        return;
    }
    let expected = registry.load().expect("initial catalog");
    let path = first.layout.agent_config();
    assert!(
        Command::new("chown")
            .arg("65534")
            .arg(path)
            .status()
            .expect("POSIX chown")
            .success()
    );
    assert!(registry.load().is_err());
    assert!(
        Command::new("chown")
            .args(["-R", "65534"])
            .arg(temp.path())
            .status()
            .expect("nonroot Fleet owner")
            .success()
    );
    let reopened = FleetRegistry::open_existing(registry.layout.fleet_root().clone())
        .expect("root reads nonroot-owned Fleet");
    assert_eq!(reopened.load().expect("nonroot catalog"), expected);
}
