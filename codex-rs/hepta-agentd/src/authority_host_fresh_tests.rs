//! Actual Root custody and original Registry/SQLite preparation; no authority fixture.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use pretty_assertions::assert_eq;

#[tokio::test]
#[ignore = "explicit actual Root original Registry and SQLite qualification"]
async fn original_fresh_state_retains_writer_lock_and_refuses_nonempty_or_changed_registry() {
    // SAFETY: geteuid reads the actual process identity without pointers.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
        .expect("explicit Root-owned private test parent required");
    let temporary = tempfile::tempdir_in(parent).unwrap();
    let fleet = HeptaFleetRoot::parse(temporary.path().join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let workspace = temporary.path().join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let agent = AgentId::parse("019a2a19-0000-7000-8000-000000000001").unwrap();
    let record = registry.register(AgentManifest::new(agent.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet).unwrap(), ResourceBudget::local_default(),
    ).unwrap()).unwrap();
    let starting = registry.compare_and_transition(&agent, record.lifecycle.generation, AgentLifecycle::Starting).unwrap();
    let identity = HostAuthorityRegisteredIdentity {
        agent_id: agent.clone(), spawn_generation: starting.generation,
        fleet_root: fleet.as_path().to_path_buf(), workspace, resources: record.manifest.resources,
    };
    let mut wrong = identity.clone();
    wrong.spawn_generation += 1;
    let rejected = FreshHostCognitiveState::prepare(&wrong).await.err().unwrap();
    assert_eq!(rejected.to_string(), "fresh preparation requires the exact original Registry Starting record");
    assert_eq!(std::fs::read_dir(record.layout.cognitive_root()).unwrap().count(), 0);

    let fresh = FreshHostCognitiveState::prepare(&identity).await.unwrap();
    let original = identity.identity().unwrap();
    assert_eq!(fresh.current_cut(&original).unwrap().owner_agent_id, agent);
    let competing = OpenOptions::new().read(true).write(true).open(record.layout.writer_lock()).unwrap();
    assert!(competing.try_lock().is_err(), "fresh preparation retains the actual Agentd writer lock");
    let cut = fresh.cut.clone();
    drop(fresh);
    competing.try_lock().unwrap();
    drop(competing);
    let rejected = FreshHostCognitiveState::prepare(&identity).await.err().unwrap();
    assert_eq!(rejected.to_string(), "fresh preparation refuses existing cognitive bytes");
    let store = CognitiveStore::open(&record.layout).await.unwrap();
    assert_eq!(store.recovery_anchor().await.unwrap(), cut);
    store.close().await;

    let second = AgentId::parse("019a2a19-0000-7000-8000-000000000002").unwrap();
    let workspace = temporary.path().join("second-workspace");
    std::fs::create_dir(&workspace).unwrap();
    let record = registry.register(AgentManifest::new(second.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet).unwrap(), ResourceBudget::local_default(),
    ).unwrap()).unwrap();
    let starting = registry.compare_and_transition(&second, record.lifecycle.generation, AgentLifecycle::Starting).unwrap();
    let second_identity = HostAuthorityRegisteredIdentity {
        agent_id: second.clone(), spawn_generation: starting.generation,
        fleet_root: fleet.as_path().to_path_buf(), workspace, resources: record.manifest.resources,
    };
    let fresh = FreshHostCognitiveState::prepare(&second_identity).await.unwrap();
    registry.compare_and_transition(&second, starting.generation, AgentLifecycle::Running).unwrap();
    assert_eq!(fresh.current_cut(&second_identity.identity().unwrap()).unwrap_err().to_string(),
        "fresh preparation requires the exact original Registry Starting record");
    assert!(fresh.current_cut(&original).is_err());
    drop(fresh);
}
