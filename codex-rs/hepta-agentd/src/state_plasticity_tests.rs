use super::*;
use crate::AgentdIdentity;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::TryLockError;

fn fixture() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(/*mode*/ 0o700))?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let record = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    Ok((temp, registry, state))
}

fn start_running(registry: &FleetRegistry, state: &AgentdState) {
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .expect("Running generation");
    state.refresh_generation().expect("refresh Running");
    state.mark_app_server_ready().expect("ready");
}

#[test]
fn final_guard_pins_running_epoch_while_owner_starts_in_starting() {
    let (_temp, registry, state) = fixture().expect("fixture");
    state.mark_app_server_ready().expect("early readiness");
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 2)
            .is_err()
    );
    start_running(&registry, &state);
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 1)
            .is_err()
    );
    let guard = state
        .plasticity_final_admission_guard(/*expected_generation*/ 2)
        .expect("same process Running epoch");
    assert!(matches!(
        state.runtime.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    drop(guard);
    assert!(state.runtime.try_lock().is_ok());
}

#[test]
fn late_readiness_cannot_reopen_local_drain() {
    let (_temp, registry, state) = fixture().expect("fixture");
    start_running(&registry, &state);
    state.mark_draining().expect("local drain");
    state.mark_app_server_ready().expect("late probe");
    assert!(!state.plasticity_admission_ready().expect("readiness"));
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 2)
            .is_err()
    );
    let runtime = state.runtime.lock().expect("runtime");
    assert!(!runtime.app_server_ready);
    assert!(!runtime.admission_open);
}

#[test]
fn late_readiness_cannot_reopen_local_fence() {
    let (_temp, registry, state) = fixture().expect("fixture");
    start_running(&registry, &state);
    state.mark_fenced();
    state.mark_app_server_ready().expect("late probe");
    assert!(!state.plasticity_admission_ready().expect("readiness"));
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 2)
            .is_err()
    );
    assert!(!state.runtime.lock().expect("runtime").app_server_ready);
}

#[test]
fn old_owner_cannot_adopt_restarted_running_epoch() {
    let (_temp, registry, state) = fixture().expect("fixture");
    start_running(&registry, &state);
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("supervisor drain");
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 2)
            .is_err()
    );
    state.mark_app_server_ready().expect("late drain probe");
    assert!(!state.plasticity_admission_ready().expect("drain readiness"));
    for (generation, lifecycle) in [
        (3, AgentLifecycle::Stopped),
        (4, AgentLifecycle::Starting),
        (5, AgentLifecycle::Running),
    ] {
        registry
            .compare_and_transition(&state.identity.agent_id, generation, lifecycle)
            .expect("restart lifecycle");
    }
    state.mark_app_server_ready().expect("late restarted probe");
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 2)
            .is_err()
    );
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 6)
            .is_err()
    );
}

#[test]
fn observed_fleet_drain_cannot_be_undone_by_history_rollback_and_late_probe() {
    let (_temp, registry, state) = fixture().expect("fixture");
    start_running(&registry, &state);
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("supervisor drain");
    state.refresh_generation().expect("observe drain");
    // Replay the previously valid Running history after this owner has
    // observed Draining. The private drain latch must remain one-way.
    fs::remove_file(
        state
            .identity
            .run_root
            .join("lifecycle-00000000000000000003.json"),
    )
    .expect("rollback lifecycle history");
    state
        .refresh_generation()
        .expect("previous history is structurally valid");
    state.mark_app_server_ready().expect("late probe");
    assert!(!state.plasticity_admission_ready().expect("readiness"));
    assert!(
        !state
            .automation_admission_ready()
            .expect("automation readiness")
    );
    assert!(
        state
            .plasticity_final_admission_guard(/*expected_generation*/ 2)
            .is_err()
    );
    let runtime = state.runtime.lock().expect("runtime");
    assert_eq!(runtime.lifecycle, AgentLifecycle::Running);
    assert!(runtime.draining);
    assert!(!runtime.app_server_ready);
    assert!(!runtime.admission_open);
}
