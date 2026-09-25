//! Real local transport with a delayed handler; this is not canonical owner evidence.
use super::*;
use crate::AgentdClient;
use crate::AgentdIdentity;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

fn fixture() -> (tempfile::TempDir, Arc<AgentdState>) {
    let temp = tempfile::tempdir().expect("temp");
    let root = temp.path().canonicalize().expect("root");
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000221").expect("agent");
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet).expect("binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let record = registry.register(manifest).expect("register");
    registry
        .compare_and_transition(&agent_id, 0, codex_hepta_fleet::AgentLifecycle::Starting)
        .expect("generation");
    let identity = AgentdIdentity {
        agent_id,
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
        layout: record.layout,
    };
    (
        temp,
        Arc::new(AgentdState::new(identity, registry, 16).expect("state")),
    )
}

fn objective_request() -> AuthBusObjectiveIngress {
    AuthBusObjectiveIngress {
        issuer_id: "transport-only".into(),
        key_epoch: 1,
        message_id: "request-1".into(),
        sequence: 1,
        expires_at_ms: u64::MAX,
        signature_hex: String::new(),
        body: AuthBusObjectiveBody {
            spawn_generation: 1,
            run_id: "run.1".into(),
            objective_revision: 1,
            source_envelope_json: "{}".into(),
            runtime_body_digest: "a".repeat(64),
            preference_state_digest: "a".repeat(64),
            model_tuple_digest: "a".repeat(64),
            prompt_registry_digest: "a".repeat(64),
            artifact_set_digest: "a".repeat(64),
            authority_epoch: 1,
        },
    }
}

#[tokio::test]
async fn objective_transport_delivers_after_old_two_second_cutoff() {
    let (temp, state) = fixture();
    let socket = temp.path().join("long.sock");
    let mut listener = UnixListener::bind(&socket).await.expect("bind");
    let client = AgentdClient::new(socket, state.identity().agent_id.clone(), 1).expect("client");
    let server = tokio::spawn(async move {
        let stream = listener.accept().await.expect("accept");
        let owner = Arc::clone(&state);
        serve_connection_with(stream, state, move |request| async move {
            tokio::time::sleep(Duration::from_millis(2_500)).await;
            Ok(error_response(
                &owner,
                request.request_id,
                request.spawn_generation,
                "handler_completed",
                "transport fixture finished",
            ))
        })
        .await
        .expect("serve");
    });
    let error = client
        .objective_start(objective_request())
        .await
        .expect_err("fixture result");
    assert!(error.to_string().contains("handler_completed"), "{error}");
    server.await.expect("server joined");
}

#[tokio::test]
async fn business_timeout_delivers_typed_unknown_acknowledgement() {
    let (temp, state) = fixture();
    let socket = temp.path().join("deadline.sock");
    let mut listener = UnixListener::bind(&socket).await.expect("bind");
    let client = AgentdClient::new(socket, state.identity().agent_id.clone(), 1).expect("client");
    let server = tokio::spawn(async move {
        let stream = listener.accept().await.expect("accept");
        serve_connection_with(stream, state, |_| std::future::pending())
            .await
            .expect("serve");
    });
    let error = client.health().await.expect_err("handler must time out");
    assert!(error.to_string().contains("operation_timed_out"), "{error}");
    assert!(
        error
            .to_string()
            .contains("reconcile the original identity")
    );
    server.await.expect("server joined");
}
