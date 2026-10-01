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
fn parent_alias_is_bound_once_and_cannot_redirect_migration_or_lifecycle_writes() {
    let (temp, registry, first, _peer) = fixture();
    let root = temp.path().canonicalize().expect("canonical fixture root");
    let redirects = root.join("redirects");
    fs::create_dir(&redirects).expect("alias parent");
    fs::set_permissions(&redirects, fs::Permissions::from_mode(0o777))
        .expect("third-party writable alias parent");
    let alias = redirects.join("selected");
    std::os::unix::fs::symlink(&root, &alias).expect("stable parent alias");
    let aliased_root = HeptaFleetRoot::parse(alias.join("fleet")).expect("aliased Fleet root");
    let bound =
        FleetRegistry::open_existing(aliased_root).expect("parent alias remains a valid input");
    assert_eq!(bound.layout().fleet_root(), registry.layout().fleet_root());
    let victim_parent = root.join("victim");
    fs::create_dir(&victim_parent).expect("victim parent");
    let victim = FleetRegistry::initialize(
        HeptaFleetRoot::parse(victim_parent.join("fleet")).expect("victim root"),
    )
    .expect("unrelated Fleet");
    fs::remove_dir(first.layout.matrix_secrets_root()).expect("legacy secrets missing");
    fs::remove_dir(first.layout.matrix_root()).expect("legacy Matrix missing");
    fs::remove_file(&alias).expect("replace externally controlled alias");
    std::os::unix::fs::symlink(&victim_parent, &alias)
        .expect("alias now selects another owner root");
    bound
        .migrate_legacy_matrix_roots()
        .expect("migration uses its originally bound owner");
    assert!(first.layout.matrix_secrets_root().is_dir());
    bound
        .compare_and_transition(
            &first.manifest.agent_id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .expect("lifecycle mutation uses the bound owner");
    assert_eq!(
        registry
            .load_agent(&first.manifest.agent_id)
            .expect("original owner")
            .lifecycle
            .lifecycle,
        AgentLifecycle::Starting
    );
    assert_eq!(
        fs::read_dir(victim.layout().agents_root())
            .expect("unrelated Fleet retained")
            .count(),
        0
    );
}

#[test]
fn initialization_resolves_missing_suffixes_and_rejects_a_linked_final_root() {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp.path().canonicalize().expect("canonical root");
    let alias = root.join("parent-alias");
    std::os::unix::fs::symlink(&root, &alias).expect("stable parent alias");
    let initialized = FleetRegistry::initialize(
        HeptaFleetRoot::parse(alias.join("new/nested/fleet")).expect("missing suffix"),
    )
    .expect("aliased initializer");
    assert_eq!(
        initialized.layout().fleet_root().as_path(),
        root.join("new/nested/fleet")
    );
    let final_link = root.join("linked-root");
    std::os::unix::fs::symlink(initialized.layout().fleet_root().as_path(), &final_link)
        .expect("linked final component");
    assert!(
        FleetRegistry::open_existing(HeptaFleetRoot::parse(&final_link).expect("root")).is_err()
    );
    assert!(FleetRegistry::initialize(HeptaFleetRoot::parse(final_link).expect("root")).is_err());
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
    let Some(nonroot_uid) =
        root_reader_fixture_uid(fs::metadata(temp.path()).expect("fixture owner").uid())
    else {
        return;
    };
    let expected = registry.load().expect("initial catalog");
    let path = first.layout.agent_config();
    let uid = nonroot_uid.to_string();
    let changed = Command::new("chown")
        .arg(&uid)
        .arg(path)
        .output()
        .expect("POSIX chown");
    assert!(
        changed.status.success(),
        "chown to mapped UID {uid} failed: {}",
        String::from_utf8_lossy(&changed.stderr)
    );
    assert_eq!(
        fs::metadata(path).expect("foreign control owner").uid(),
        nonroot_uid
    );
    assert!(registry.load().is_err());
    let changed = Command::new("chown")
        .arg("-R")
        .arg(&uid)
        .arg(temp.path())
        .output()
        .expect("nonroot Fleet owner");
    assert!(
        changed.status.success(),
        "recursive chown to mapped UID {uid} failed: {}",
        String::from_utf8_lossy(&changed.stderr)
    );
    assert_eq!(
        fs::metadata(registry.layout().fleet_root().as_path())
            .expect("nonroot Fleet root")
            .uid(),
        nonroot_uid
    );
    let reopened = FleetRegistry::open_existing(registry.layout.fleet_root().clone())
        .expect("root reads nonroot-owned Fleet");
    assert_eq!(reopened.load().expect("nonroot catalog"), expected);
}

// Returning here reports success to the test harness; the explicit diagnostic
// distinguishes unavailable prerequisites from executed cross-UID assertions.
fn root_reader_fixture_uid(fixture_uid: u32) -> Option<u32> {
    if fixture_uid != 0 {
        eprintln!(
            "CAPABILITY SKIP: root_reader_preserves_nonroot_fleet_owner_and_rejects_foreign_control_owner requires UID 0; cross-UID assertions were not executed"
        );
        return None;
    }
    #[cfg(target_os = "linux")]
    {
        let mapping = fs::read_to_string("/proc/self/uid_map").expect("read Linux UID mappings");
        let nonroot_uid = mapping.lines().find_map(|line| {
            let fields = line
                .split_whitespace()
                .map(|field| field.parse::<u64>().expect("valid Linux UID mapping"))
                .collect::<Vec<_>>();
            assert_eq!(fields.len(), 3, "Linux UID mapping has three fields");
            let inside = fields[0];
            let end = inside.checked_add(fields[2]).expect("UID mapping range");
            assert!(end <= u64::from(u32::MAX) + 1, "UID mapping fits uid_t");
            let candidate = inside.max(1);
            (candidate < end && candidate < u64::from(u32::MAX))
                .then(|| u32::try_from(candidate).expect("mapped nonroot UID"))
        });
        let Some(nonroot_uid) = nonroot_uid else {
            eprintln!(
                "CAPABILITY SKIP: root_reader_preserves_nonroot_fleet_owner_and_rejects_foreign_control_owner has no mapped nonroot Linux UID; cross-UID assertions were not executed"
            );
            return None;
        };
        let status =
            fs::read_to_string("/proc/self/status").expect("read Linux effective capabilities");
        let capabilities = status
            .lines()
            .find_map(|line| line.strip_prefix("CapEff:"))
            .expect("Linux status contains effective capabilities");
        let capabilities = u64::from_str_radix(capabilities.trim(), 16)
            .expect("valid Linux effective capabilities");
        let can_chown = capabilities & (1 << 0) != 0;
        let can_read_private_nonroot_files = capabilities & ((1 << 1) | (1 << 2)) != 0;
        let can_set_nonroot_directory_permissions = capabilities & (1 << 3) != 0;
        if !can_chown || !can_read_private_nonroot_files || !can_set_nonroot_directory_permissions {
            eprintln!(
                "CAPABILITY SKIP: root_reader_preserves_nonroot_fleet_owner_and_rejects_foreign_control_owner requires CAP_CHOWN, CAP_FOWNER, and CAP_DAC_OVERRIDE or CAP_DAC_READ_SEARCH; cross-UID assertions were not executed"
            );
            return None;
        }
        Some(nonroot_uid)
    }
    #[cfg(not(target_os = "linux"))]
    {
        Some(65534)
    }
}
