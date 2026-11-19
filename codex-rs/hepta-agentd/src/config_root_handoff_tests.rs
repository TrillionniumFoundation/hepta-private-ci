//! Original Registry/lock behavior; the privileged test opens a real fresh DB.

use super::*;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::WorkspaceBinding;
use pretty_assertions::assert_eq;

fn original_config(parent: &Path) -> (tempfile::TempDir, AgentdConfig) {
    let temporary = tempfile::tempdir_in(parent).unwrap();
    let fleet = HeptaFleetRoot::parse(temporary.path().join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let workspace = temporary.path().join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let agent = AgentId::parse("019a2a19-0000-7000-8000-000000000006").unwrap();
    let record = registry
        .register(
            AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(workspace.clone(), &fleet).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    let starting = registry
        .compare_and_transition(
            &agent,
            record.lifecycle.generation,
            AgentLifecycle::Starting,
        )
        .unwrap();
    let config = AgentdConfig::load(
        fleet.as_path().to_owned(),
        agent,
        starting.generation,
        record.layout.home_root().to_owned(),
        record.layout.run_root().to_owned(),
        record.layout.home_root().to_owned(),
        workspace,
    )
    .unwrap();
    (temporary, config)
}

#[test]
fn root_handoff_rejects_zero_uid_or_gid_without_releasing_a_runtime() {
    for (uid, gid) in [(0, 60001), (60001, 0), (0, 0)] {
        let parent = tempfile::tempdir().unwrap();
        let (_temporary, config) = original_config(parent.path());
        let error = config.prepare_root_handoff(uid, gid).err().unwrap();
        assert!(
            matches!(error, AgentdError::Invalid(message) if message.contains("dedicated non-Root UID/GID"))
        );
    }
}

#[tokio::test]
#[ignore = "explicit actual Root original Registry, file lock and SQLite preparation"]
async fn original_root_preparation_releases_same_lock_for_fresh_owner_without_changing_registry() {
    // SAFETY: geteuid only reads this process's actual kernel credential.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent =
        std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT").expect("explicit private Root test parent");
    let (_temporary, config) = original_config(Path::new(&parent));
    let identity = config.identity().clone();
    let before = config.registry.load_agent(&identity.agent_id).unwrap();
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(identity.layout.writer_lock())
        .unwrap();
    assert!(
        contender.try_lock().is_err(),
        "the original constructor still owns its actual lock"
    );
    let prepared = config
        .prepare_root_handoff(/*expected_uid*/ 60001, /*expected_gid*/ 60001)
        .unwrap();
    assert_eq!(prepared.identity(), &identity);
    assert_eq!(
        prepared
            .config
            .registry
            .load_agent(&identity.agent_id)
            .unwrap(),
        before
    );
    contender.try_lock().unwrap();
    contender.unlock().unwrap();
    let registered = crate::HostAuthorityRegisteredIdentity {
        agent_id: identity.agent_id.clone(),
        spawn_generation: identity.spawn_generation,
        fleet_root: identity.fleet_root.clone(),
        workspace: identity.workspace.clone(),
        resources: identity.resources.clone(),
    };
    let fresh = crate::FreshHostCognitiveState::prepare(&registered)
        .await
        .unwrap();
    assert!(
        contender.try_lock().is_err(),
        "Root fresh factory now owns the same original lock"
    );
    assert_eq!(
        prepared
            .config
            .registry
            .load_agent(&identity.agent_id)
            .unwrap(),
        before
    );
    drop(fresh);
    contender.try_lock().unwrap();
    contender.unlock().unwrap();
    let metadata = prepared.config._writer_lock.metadata().unwrap();
    let path = std::fs::symlink_metadata(identity.layout.writer_lock()).unwrap();
    assert_eq!((metadata.dev(), metadata.ino()), (path.dev(), path.ino()));
    assert_eq!((metadata.uid(), metadata.mode() & 0o7777), (0, 0o600));
    assert_eq!(
        std::fs::metadata(identity.layout.run_root()).unwrap().uid(),
        0
    );
    // Without a real active Root session there is no finish/usable Config.
    drop(prepared);
}
