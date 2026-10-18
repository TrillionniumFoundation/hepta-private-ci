type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

use std::future::pending;
use std::sync::Arc;

use codex_hepta_agent_components::cognitive_store::DurableCognitiveStore;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_uds::UnixListener;

use super::*;

pub(super) async fn fixture() -> TestResult<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52")?;
    let resources = ResourceBudget::local_default();
    let record = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        resources.clone(),
    )?)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let layout = record.layout;
    let identity = AgentdIdentity {
        agent_id: agent_id.clone(),
        layout: layout.clone(),
        spawn_generation: 1,
        fleet_root: root.join("fleet"),
        workspace,
        resources,
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
    };
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.attach_cognitive_store(Arc::new(DurableCognitiveStore::open(&layout).await?))?;
    state.mark_runtime_prerequisites_ready()?;
    state.mark_app_server_ready()?;
    Ok((temp, registry, state))
}

#[tokio::test]
async fn recovery_accepts_an_admitted_observation_during_drain_but_rejects_a_replaced_owner()
-> TestResult {
    let (_temp, registry, state) = fixture().await?;
    validate_observation_generation(&state)?;
    registry.compare_and_transition(
        &state.identity().agent_id,
        /*expected_generation*/ 2,
        AgentLifecycle::Draining,
    )?;
    assert!(!state.automation_admission_ready()?);
    validate_observation_generation(&state)?;
    registry.compare_and_transition(
        &state.identity().agent_id,
        /*expected_generation*/ 3,
        AgentLifecycle::Stopped,
    )?;
    assert!(matches!(
        validate_observation_generation(&state),
        Err(AgentdError::GenerationFenced(_))
    ));
    Ok(())
}

#[tokio::test]
async fn recovery_rejects_an_explicitly_fenced_observer() -> TestResult {
    let (_temp, _registry, state) = fixture().await?;
    state.mark_fenced();
    assert!(matches!(
        validate_observation_generation(&state),
        Err(AgentdError::GenerationFenced(_))
    ));
    Ok(())
}

#[tokio::test]
async fn stalled_app_server_handshake_cannot_hold_recovery_indefinitely() -> TestResult {
    let (_temp, _registry, state) = fixture().await?;
    let socket = &state.identity().app_server_socket;
    tokio::fs::create_dir_all(socket.parent().ok_or("socket parent missing")?).await?;
    let mut listener = UnixListener::bind(socket).await?;
    let peer = tokio::spawn(async move {
        let _stream = listener.accept().await?;
        pending::<std::io::Result<()>>().await
    });
    let result = tokio::time::timeout(
        RECOVERY_REQUEST_TIMEOUT + Duration::from_secs(1),
        connect(&state, state.identity()),
    )
    .await?;
    peer.abort();
    assert!(matches!(
        result,
        Err(AgentdError::Protocol(message)) if message == "automation recovery connect timed out"
    ));
    Ok(())
}
