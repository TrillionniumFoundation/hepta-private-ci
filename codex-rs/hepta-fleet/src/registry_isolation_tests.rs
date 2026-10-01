use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::FleetRegistry;
use super::lifecycle_path;
use crate::AgentLifecycle;
use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

fn fixture() -> (tempfile::TempDir, FleetRegistry, crate::AgentRecord) {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp.path().canonicalize().expect("canonical root");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let workspace = root.join("workspace");
    fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("id");
    let manifest = AgentManifest::new(
        agent_id,
        WorkspaceBinding::new(&workspace, &fleet_root).expect("binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let record = registry.register(manifest).expect("register");
    (temp, registry, record)
}

#[test]
fn local_read_ignores_corrupt_peers_but_global_audit_still_rejects_them() {
    let (_temp, registry, record) = fixture();
    // Each added peer is deliberately incomplete. A reader that accidentally
    // enumerates the fleet will fail, independently of filesystem timing.
    for number in 1..=128 {
        let peer = format!("019153a4-3088-7e03-a56a-{number:012x}");
        fs::create_dir(registry.layout().agents_root().join(peer)).expect("peer");
        assert_eq!(
            registry
                .load_agent(&record.manifest.agent_id)
                .expect("local read"),
            record
        );
    }
    assert!(registry.load().is_err());
}

#[test]
fn local_read_observes_a_new_generation_without_cached_authority() {
    let (_temp, registry, mut expected) = fixture();
    expected.lifecycle = registry
        .compare_and_transition(
            &expected.manifest.agent_id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .expect("new generation");
    assert_eq!(
        registry
            .load_agent(&expected.manifest.agent_id)
            .expect("fresh read"),
        expected
    );
}

#[test]
fn historical_starting_read_requires_the_complete_exact_agent_history() {
    let (_temp, registry, record) = fixture();
    let id = &record.manifest.agent_id;
    for (generation, lifecycle) in [
        (0, AgentLifecycle::Starting),
        (1, AgentLifecycle::Failed),
        (2, AgentLifecycle::Stopped),
        (3, AgentLifecycle::Starting),
    ] {
        registry
            .compare_and_transition(id, generation, lifecycle)
            .expect("real lifecycle transition");
    }
    let prior = registry
        .load_agent_lifecycle_generation(id, 1)
        .expect("original Starting event");
    assert_eq!(prior.lifecycle, AgentLifecycle::Starting);
    assert_eq!(prior.generation, 1);
    assert_eq!(
        registry
            .load_agent(id)
            .expect("current owner")
            .lifecycle
            .generation,
        4
    );
    assert_eq!(
        registry
            .load_agent_lifecycle_generation(id, 3)
            .expect("historical Stopped")
            .lifecycle,
        AgentLifecycle::Stopped
    );
    assert!(registry.load_agent_lifecycle_generation(id, 5).is_err());
    // A real-looking older event from another Agent cannot become a restart
    // grant merely because the current event and requested index still exist.
    let path = lifecycle_path(record.layout.owner_run_root(), 1);
    let mut unrelated = prior;
    unrelated.agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("other id");
    fs::write(path, serde_json::to_vec(&unrelated).expect("fixture event"))
        .expect("fixture corruption");
    assert!(registry.load_agent_lifecycle_generation(id, 1).is_err());
    assert!(registry.load_agent(id).is_err());
}

#[test]
fn local_read_still_rejects_its_own_corrupt_lifecycle_and_missing_manifest() {
    let (_temp, registry, record) = fixture();
    let path = lifecycle_path(record.layout.owner_run_root(), /*generation*/ 0);
    let original = fs::read(&path).expect("original lifecycle");
    fs::write(&path, b"not-json").expect("corrupt local lifecycle");
    assert!(registry.load_agent(&record.manifest.agent_id).is_err());
    fs::write(path, original).expect("restore fixture lifecycle");
    fs::remove_file(record.layout.agent_config()).expect("remove own manifest");
    assert!(registry.load_agent(&record.manifest.agent_id).is_err());
}

#[cfg(unix)]
#[test]
fn local_read_rejects_a_symlinked_control_file() {
    let (_temp, registry, record) = fixture();
    let path = record.layout.agent_config();
    let target = path.with_extension("saved");
    fs::rename(path, &target).expect("move fixture manifest");
    std::os::unix::fs::symlink(target, path).expect("fixture symlink");
    assert!(registry.load_agent(&record.manifest.agent_id).is_err());
}

#[cfg(unix)]
#[test]
fn retirement_reclaims_shared_read_permissions_and_preserves_identity_history() {
    use std::os::unix::fs::PermissionsExt;

    let (_temp, registry, record) = fixture();
    fs::set_permissions(
        record.layout.agent_root(),
        fs::Permissions::from_mode(0o750),
    )
    .expect("protected workload read access");
    let evidence = record.layout.home_root().join("historical-evidence");
    fs::write(&evidence, b"actual retained history").expect("historical record");
    let archived = registry
        .retire_agent(&record.manifest.agent_id, /*expected_generation*/ 0)
        .expect("terminal archive");
    assert_eq!(
        registry
            .retired_agent_path(&record.manifest.agent_id)
            .expect("retirement receipt after publication"),
        Some(archived.clone())
    );
    assert_eq!(
        fs::metadata(&archived).unwrap().permissions().mode() & 0o777,
        0o700
    );
    assert_eq!(
        fs::read(archived.join("home").join("historical-evidence")).unwrap(),
        b"actual retained history"
    );
    assert!(matches!(
        registry.register(record.manifest.clone()),
        Err(super::FleetRegistryError::AlreadyRegistered(agent)) if agent == record.manifest.agent_id
    ));
}
