#![allow(clippy::expect_used, reason = "test fixture setup and assertions")]

use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaFleetRoot;

use super::*;

fn identity(root: &Path) -> AgentdIdentity {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c28").expect("agent id");
    let layout = HeptaFleetRoot::parse(root.join("fleet"))
        .expect("fleet root")
        .layout()
        .agent(&agent_id);
    AgentdIdentity {
        agent_id,
        layout: layout.clone(),
        spawn_generation: 1,
        fleet_root: root.join("fleet"),
        workspace: root.join("workspace"),
        resources: ResourceBudget::local_default(),
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
    }
}

fn config(root: &Path) -> serde_json::Value {
    serde_json::json!({
        "schema_version": 2, "provider": "hcsn_process_v1",
        "authority_profile": "production_ml_dsa65_v2", "provider_scope": "provider:hcsn",
        "final_use_scope_sha256": Sha256Digest::for_bytes(b"scope"),
        "final_use_signer_id": "synthetic-fixture", "final_use_verifying_key_hex": "00".repeat(32),
        "final_use_revocations_file": root.join("revocations.json"),
        "python_executable": root.join("python"), "python_sha256": Sha256Digest::for_bytes(b"python"),
        "repository_root": root.join("repo"), "supervisor_sha256": Sha256Digest::for_bytes(b"supervisor"),
        "durable_root": root.join("jobs"), "timeout_ms": 1_000,
    })
}

#[test]
fn production_profile_is_refused_before_any_classical_authority_or_worker_state() {
    let directory = tempfile::tempdir().expect("root");
    let root = directory.path().canonicalize().expect("canonical root");
    let config = serde_json::from_value(config(&root)).expect("recognized production profile");
    let error = AgentdAutomationEffectHost::open_hcsn(&identity(&root), config)
        .expect_err("PQ composition is unavailable");
    assert!(
        error
            .to_string()
            .contains("production HCSN registration requires the PQ owner authority")
    );
    assert_eq!(fs::read_dir(&root).expect("untouched root").count(), 0);
}

#[test]
fn profile_cannot_be_omitted_or_inferred_from_classical_key_fields() {
    let directory = tempfile::tempdir().expect("root");
    let mut value = config(directory.path());
    value
        .as_object_mut()
        .expect("config object")
        .remove("authority_profile");
    assert!(serde_json::from_value::<HcsnHostFileV2>(value).is_err());
}

#[test]
fn unregistered_operation_is_rejected_before_supervisor_pin_io() {
    let directory = tempfile::tempdir().expect("root");
    let root = directory.path().canonicalize().expect("canonical root");
    let provider = HcsnProvider {
        provider_scope: "provider:hcsn".to_string(),
        requests_root: root.join("requests"),
        config: HcsnProcessSupervisorConfig {
            python_executable: root.join("python"),
            python_sha256: Sha256Digest::for_bytes(b"python"),
            repository_root: root.join("repo"),
            supervisor_sha256: Sha256Digest::for_bytes(b"supervisor"),
            durable_root: root.join("jobs"),
            deadline: Duration::from_secs(1),
        },
    };
    let Err(error) = provider.driver("hcsn.training.publish") else {
        panic!("publication is not registered");
    };
    assert!(error.to_string().contains("operation is not registered"));
    assert_eq!(fs::read_dir(&root).expect("untouched root").count(), 0);
}

#[test]
fn private_directory_validation_rejects_permission_changes_and_symlink_redirection() {
    let directory = tempfile::tempdir().expect("root");
    let root = directory.path().canonicalize().expect("canonical root");
    let retained = root.join("retained");
    create_private_directory(&retained).expect("private directory");
    fs::set_permissions(&retained, fs::Permissions::from_mode(0o755)).expect("change permissions");
    assert!(validate_private_directory(&retained).is_err());
    assert!(
        create_private_directory(&retained).is_err(),
        "an invalid existing directory must not be silently repaired"
    );
    fs::set_permissions(&retained, fs::Permissions::from_mode(0o700))
        .expect("restore fixture mode");
    symlink(&retained, root.join("redirected")).expect("symlink");
    assert!(validate_private_directory(&root.join("redirected")).is_err());
}

#[test]
fn retained_request_read_rejects_linked_or_exposed_bytes() {
    let directory = tempfile::tempdir().expect("root");
    let root = directory.path().canonicalize().expect("canonical root");
    let request = root.join("request.json");
    fs::write(&request, b"{}").expect("request");
    fs::set_permissions(&request, fs::Permissions::from_mode(0o600)).expect("private request");
    assert_eq!(
        read_retained_request(&request).expect("retained bytes"),
        b"{}"
    );
    fs::hard_link(&request, root.join("linked.json")).expect("hard link");
    assert!(read_retained_request(&request).is_err());
    fs::remove_file(root.join("linked.json")).expect("remove test link");
    fs::set_permissions(&request, fs::Permissions::from_mode(0o644)).expect("exposed request");
    assert!(read_retained_request(&request).is_err());
}
