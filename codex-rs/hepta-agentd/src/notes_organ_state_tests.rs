//! Real Fleet lifecycle with explicit in-memory readiness fixtures. No Root
//! authority or real execution service is inferred from fixture flags.

use super::*;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

fn fixture() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let temporary = tempfile::tempdir()?;
    let directory = temporary.path().canonicalize()?;
    let root = HeptaFleetRoot::parse(directory.join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = directory.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = codex_hepta_contracts::AgentId::parse("00000000-0000-4000-8000-00000000c081")?;
    let record = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &agent,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let identity = AgentdIdentity {
        agent_id: agent,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: root.as_path().to_path_buf(),
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    Ok((temporary, registry, state))
}

fn fixture_notes_ready(state: &AgentdState) {
    let mut runtime = state.runtime.lock().unwrap();
    runtime.notes_organ_ready = true;
    runtime.critical_stores_ready = true;
    runtime.revocation_ready = true;
    runtime.required_ports_ready = true;
}

#[test]
fn missing_original_root_cannot_open_notes_organ_admission() -> anyhow::Result<()> {
    let (_temporary, _registry, state) = fixture()?;
    assert!(state.mark_notes_organ_ready().is_err());
    assert!(!state.runtime.lock().unwrap().notes_organ_ready);
    assert!(!state.objective_admission_ready()?);
    Ok(())
}

#[tokio::test]
async fn finite_notes_readiness_keeps_app_server_and_text_ingress_closed() -> anyhow::Result<()> {
    let (_temporary, registry, state) = fixture()?;
    fixture_notes_ready(&state);
    assert!(!state.objective_admission_ready()?);
    registry.compare_and_transition(
        &state.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    assert!(state.objective_admission_ready()?);
    assert!(!state.automation_admission_ready()?);
    assert!(crate::authbus_ingress::require_ready(&state).is_err());
    assert!(crate::authbus_ingress::require_objective_ready(&state).is_ok());
    let lifecycle = state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            AgentdMethod::Lifecycle,
        )
        .await?;
    assert_eq!(
        lifecycle.payload,
        AgentdPayload::Lifecycle(crate::LifecycleSnapshot {
            lifecycle: AgentLifecycle::Running,
            app_server_ready: false,
            fenced: false,
        })
    );
    state.mark_draining()?;
    assert!(!state.objective_admission_ready()?);
    assert!(!state.runtime.lock().unwrap().notes_organ_ready);
    Ok(())
}

#[test]
fn original_fleet_draining_and_permanent_fence_close_finite_notes_readiness() -> anyhow::Result<()>
{
    let (_temporary, registry, state) = fixture()?;
    fixture_notes_ready(&state);
    registry.compare_and_transition(
        &state.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    assert!(state.objective_admission_ready()?);
    registry.compare_and_transition(
        &state.identity.agent_id,
        /*expected_generation*/ 2,
        AgentLifecycle::Draining,
    )?;
    assert!(!state.objective_admission_ready()?);
    assert!(!state.runtime.lock().unwrap().notes_organ_ready);
    state.mark_fenced();
    assert!(state.is_fenced()?);
    assert!(!state.objective_admission_ready()?);
    Ok(())
}
