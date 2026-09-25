use std::fs;

use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_matrix_protocol::MatrixRoomId;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn configured_fleet() -> (TempDir, PathBuf, AgentId) {
    let temp = TempDir::new().expect("tempdir");
    let fleet_root = temp.path().join("fleet");
    let workspace = temp.path().join("workspace");
    fs::create_dir_all(&fleet_root).expect("fleet root");
    fs::create_dir_all(&workspace).expect("workspace");
    let fleet_root = fleet_root.canonicalize().expect("canonical fleet root");
    let workspace = workspace.canonicalize().expect("canonical workspace");
    let typed_root = HeptaFleetRoot::parse(fleet_root.clone()).expect("typed fleet root");
    let registry = FleetRegistry::initialize(typed_root.clone()).expect("registry");
    let agent_id = AgentId::parse(AGENT_ID).expect("agent ID");
    registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(workspace, &typed_root).expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("starting");
    registry
        .compare_and_transition(&agent_id, 1, AgentLifecycle::Running)
        .expect("running");
    (temp, fleet_root, agent_id)
}

fn binding(agent_id: AgentId) -> MatrixBindingV1 {
    MatrixBindingV1 {
        schema_version: MATRIX_BINDING_SCHEMA_VERSION,
        agent_id,
        revision: 1,
        homeserver: MatrixHomeserverUrl::parse("http://127.0.0.1:28008").expect("homeserver"),
        expected_mxid: MatrixUserId::parse("@hepta-agent-a:localhost").expect("mxid"),
        expected_device_id: MatrixDeviceId::parse("HEPTA-R4-A").expect("device"),
        allowed_rooms: vec![MatrixRoomId::parse("!room-a:localhost").expect("room")],
        allowed_senders: vec![MatrixUserId::parse("@hepta-human:localhost").expect("sender")],
        require_explicit_mention: false,
    }
}

fn process_identity(binding: &MatrixBindingV1) -> MatrixdProcessIdentity {
    MatrixdProcessIdentity {
        release_id: "release-test".to_string(),
        binding_digest: matrix_binding_digest(binding).expect("binding digest"),
        process_incarnation: "matrixd-test-incarnation".to_string(),
        plane_epoch: 1,
    }
}

#[test]
fn config_binds_one_running_spawn_generation_without_exposing_secrets() {
    let (_temp, fleet_root, agent_id) = configured_fleet();
    let binding = binding(agent_id.clone());
    let config = MatrixdConfig::load(
        fleet_root,
        agent_id,
        1,
        binding.clone(),
        process_identity(&binding),
        MatrixdCredentials::new("super-private-value", Some("store-secret".to_string()))
            .expect("credentials"),
        64,
        Duration::from_secs(30),
        "Hepta test agent".to_string(),
    )
    .expect("config");
    assert_eq!(config.spawn_generation, 1);
    assert_eq!(config.binding.revision, 1);
    let debug = format!("{config:?}");
    assert!(!debug.contains("super-private-value"));
    assert!(!debug.contains("store-secret"));
    assert!(debug.contains("<redacted>"));
}

#[test]
fn config_rejects_a_generation_that_does_not_own_the_running_agentd() {
    let (_temp, fleet_root, agent_id) = configured_fleet();
    let binding = binding(agent_id.clone());
    let error = MatrixdConfig::load(
        fleet_root,
        agent_id,
        2,
        binding.clone(),
        process_identity(&binding),
        MatrixdCredentials::new("password", None).expect("credentials"),
        64,
        Duration::from_secs(30),
        "Hepta test agent".to_string(),
    )
    .expect_err("wrong spawn generation must be fenced");
    assert!(matches!(error, MatrixdConfigError::GenerationFenced(_)));
}
