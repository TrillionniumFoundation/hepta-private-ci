//! Actual socket contract with controlled readiness; no model is installed.
use codex_hepta_agent_protocol::MemoryCellReadIngress;
use codex_hepta_agent_protocol::MemoryCellRole;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn native_memory_control_socket_requires_explicit_owner_and_generation() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().canonicalize().unwrap();
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cfe").unwrap();
    let record = registry
        .register(
            AgentManifest::new(
                owner.clone(),
                WorkspaceBinding::new(&workspace, &fleet).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    registry
        .compare_and_transition(&owner, 0, AgentLifecycle::Starting)
        .unwrap();
    let config = crate::AgentdConfig::load(
        root.join("fleet"),
        owner.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .unwrap();
    let (identity, state_registry, _guard) = config.into_parts();
    let socket = identity.control_socket.clone();
    let state = Arc::new(crate::AgentdState::new(identity, state_registry, 16).unwrap());
    state.mark_runtime_prerequisites_ready().unwrap();
    registry
        .compare_and_transition(&owner, 1, AgentLifecycle::Running)
        .unwrap();
    state.mark_app_server_ready().unwrap();
    let cancellation = CancellationToken::new();
    let server = crate::AgentdControlServer::bind(socket.clone(), state, cancellation.clone())
        .await
        .unwrap();
    let serving = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(socket.clone(), owner.clone(), 1).unwrap();
    let ingress = MemoryCellReadIngress {
        invocation_id: "socket:missing-model".to_string(),
        role: MemoryCellRole::Procedural,
        entity: "case".to_string(),
        relation: "repair".to_string(),
        deadline_unix_ms: u64::MAX,
    };
    assert!(
        client
            .memory_cell_read_start(ingress.clone())
            .await
            .is_err()
    );
    assert!(
        client
            .memory_cell_read_status(ingress.invocation_id.clone())
            .await
            .is_err()
    );
    assert!(
        !client
            .capabilities()
            .await
            .unwrap()
            .capabilities
            .iter()
            .any(|c| c.id == "memory.cell.native")
    );
    let stale = crate::AgentdClient::new(socket, owner, 2).unwrap();
    assert!(stale.memory_cell_read_start(ingress).await.is_err());
    cancellation.cancel();
    serving.await.unwrap().unwrap();
}
