//! Route fixtures establish no registered tool, human session or model result.
use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use serde_json::json;

fn registered(scope: Digest32) -> serde_json::Value {
    json!({
        "thread_id": "original-thread",
        "app_server_session_id": "original-app-session",
        "principal_scope_digest": scope.to_string(),
        "registered_tool_schema_sha256": Digest32::of_bytes(
            AgentdNotesModelRoute::TOOL_DEFINITION_JSON.as_bytes()
        ).to_string(),
    })
}

#[test]
fn sealed_model_route_refuses_scope_definition_and_transport_overrides() -> anyhow::Result<()> {
    let scope = Digest32::of_bytes(b"original human scope");
    let route: RegisteredNotesModelRoute = serde_json::from_value(registered(scope))?;
    let route = route.into_route(scope)?;
    route.validate_for(scope)?;
    assert!(
        route
            .validate_for(Digest32::of_bytes(b"another human"))
            .is_err()
    );
    for (field, value) in [
        ("thread_id", json!("")),
        ("thread_id", json!("thread\nreplacement")),
        ("app_server_session_id", json!("x".repeat(257))),
        ("principal_scope_digest", json!(Digest32::ZERO.to_string())),
        (
            "registered_tool_schema_sha256",
            json!(Digest32::of_bytes(b"another dynamic tool").to_string()),
        ),
    ] {
        let mut input = registered(scope);
        input[field] = value;
        let declared: RegisteredNotesModelRoute = serde_json::from_value(input)?;
        assert!(declared.into_route(scope).is_err());
    }
    for field in ["control_socket", "codex_home", "agent_id", "issuer_id"] {
        let mut input = registered(scope);
        input[field] = json!("untrusted-route-override");
        assert!(serde_json::from_value::<RegisteredNotesModelRoute>(input).is_err());
    }
    Ok(())
}

#[test]
fn model_route_derives_transport_from_original_agent_identity() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let layout = fleet.layout().agent(&agent_id);
    let mut identity = AgentdIdentity {
        agent_id,
        spawn_generation: 3,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace: root,
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
        layout,
    };
    let scope = Digest32::of_bytes(b"original human scope");
    let route: RegisteredNotesModelRoute = serde_json::from_value(registered(scope))?;
    let route = route.into_route(scope)?;
    assert_eq!(
        route.text_session_config(&identity)?,
        AgentdTextSessionConfig {
            control_socket: identity.control_socket.clone(),
            agent_id: identity.agent_id.clone(),
            spawn_generation: 3,
            thread_id: "original-thread".into(),
            app_server_session_id: "original-app-session".into(),
            codex_home: identity.home_root.clone(),
        }
    );
    identity.control_socket = "relative.sock".into();
    assert!(route.text_session_config(&identity).is_err());
    Ok(())
}
