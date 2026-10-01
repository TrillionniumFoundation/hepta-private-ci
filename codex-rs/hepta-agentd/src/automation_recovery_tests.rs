use std::future::pending;
use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_uds::UnixListener;

use super::*;

pub(super) async fn fixture() -> (tempfile::TempDir, FleetRegistry, AgentdState) {
    let temp = tempfile::tempdir().expect("temporary owner");
    let root = temp.path().canonicalize().expect("canonical owner");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52").expect("agent id");
    let resources = ResourceBudget::local_default();
    let record = registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(&workspace, &fleet).expect("workspace binding"),
                resources.clone(),
            )
            .expect("manifest"),
        )
        .expect("registered owner");
    registry
        .compare_and_transition(
            &agent_id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .expect("starting");
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
    let state =
        AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16).expect("runtime state");
    registry
        .compare_and_transition(
            &agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .expect("running");
    state.refresh_generation().expect("current generation");
    state
        .attach_cognitive_store(Arc::new(
            DurableCognitiveStore::open(&layout)
                .await
                .expect("cognitive owner"),
        ))
        .expect("attached owner");
    state
        .mark_runtime_prerequisites_ready()
        .expect("prerequisites");
    state.mark_app_server_ready().expect("app server ready");
    (temp, registry, state)
}

#[tokio::test]
async fn recovery_accepts_an_admitted_observation_during_drain_but_rejects_a_replaced_owner() {
    let (_temp, registry, state) = fixture().await;
    validate_observation_generation(&state).expect("current owner");
    registry
        .compare_and_transition(
            &state.identity().agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("ordinary drain");
    assert!(
        !state
            .automation_admission_ready()
            .expect("closed admission")
    );
    validate_observation_generation(&state).expect("finish already admitted observation");
    registry
        .compare_and_transition(
            &state.identity().agent_id,
            /*expected_generation*/ 3,
            AgentLifecycle::Stopped,
        )
        .expect("stopped owner");
    assert!(matches!(
        validate_observation_generation(&state),
        Err(AgentdError::GenerationFenced(_))
    ));
}

#[tokio::test]
async fn recovery_rejects_an_explicitly_fenced_observer() {
    let (_temp, _registry, state) = fixture().await;
    state.mark_fenced();
    assert!(matches!(
        validate_observation_generation(&state),
        Err(AgentdError::GenerationFenced(_))
    ));
}

#[tokio::test]
async fn stalled_app_server_handshake_cannot_hold_recovery_indefinitely() {
    let (_temp, _registry, state) = fixture().await;
    let mut listener = UnixListener::bind(&state.identity().app_server_socket)
        .await
        .expect("fake App Server socket");
    let peer = tokio::spawn(async move {
        let _stream = listener.accept().await.expect("automation peer");
        pending::<()>().await;
    });
    let result = tokio::time::timeout(
        RECOVERY_REQUEST_TIMEOUT + Duration::from_secs(1),
        connect(&state, state.identity()),
    )
    .await
    .expect("production recovery timeout must fire first");
    peer.abort();
    assert!(matches!(
        result,
        Err(AgentdError::Protocol(message)) if message == "automation recovery connect timed out"
    ));
}
