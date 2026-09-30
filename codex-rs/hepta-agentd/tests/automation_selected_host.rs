#![cfg(unix)]

pub use codex_hepta_agentd::AgentdError;
pub use codex_hepta_agentd::AgentdIdentity;
pub use codex_hepta_agentd::MAX_AUTOMATION_EFFECT_WIRE_BYTES;

#[path = "../src/automation_effect_host.rs"]
mod automation_effect_host;

use std::env;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde_json::json;

use crate::automation_effect_host::AgentdAutomationEffectHost;

const MAX_EFFECT_HOST_BYTES: u64 = 64 * 1024;
const MAX_REVOCATIONS_BYTES: u64 = 4 * 1024 * 1024;
const MAX_TERMINAL_PROFILE_BYTES: u64 = 64 * 1024;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SelectedHostTerminalObserverV1 {
    schema_version: u32,
    observer_id: String,
    agent_id: String,
    protocol: String,
}

#[test]
#[ignore = "requires protected selected-host provider and observer evidence"]
fn selected_host_effect_host_uses_exact_protected_inputs() {
    let effect_host_path = required_path("AUTOMATION_EFFECT_HOST_FILE");
    let terminal_profile_path = required_path("AUTOMATION_TERMINAL_OBSERVER_FILE");
    let receipt_path = required_path("AUTOMATION_EFFECT_HOST_RUST_RECEIPT");
    let expected_effect_host_sha = required_digest("AUTOMATION_EXPECTED_EFFECT_HOST_SHA256");
    let expected_revocations_sha = required_digest("AUTOMATION_EXPECTED_REVOCATIONS_SHA256");
    let expected_terminal_sha = required_digest("AUTOMATION_EXPECTED_TERMINAL_OBSERVER_SHA256");

    let effect_host_bytes = read_protected_file(&effect_host_path, MAX_EFFECT_HOST_BYTES);
    assert_eq!(
        Sha256Digest::for_bytes(&effect_host_bytes),
        expected_effect_host_sha
    );
    let host_json: serde_json::Value =
        serde_json::from_slice(&effect_host_bytes).expect("parse protected effect host file");
    let revocations_path = host_json
        .get("final_use_revocations_file")
        .and_then(serde_json::Value::as_str)
        .map(PathBuf::from)
        .expect("effect host revocations path");
    let revocation_bytes = read_protected_file(&revocations_path, MAX_REVOCATIONS_BYTES);
    assert_eq!(
        Sha256Digest::for_bytes(&revocation_bytes),
        expected_revocations_sha
    );

    let terminal_bytes = read_protected_file(&terminal_profile_path, MAX_TERMINAL_PROFILE_BYTES);
    assert_eq!(
        Sha256Digest::for_bytes(&terminal_bytes),
        expected_terminal_sha
    );
    let terminal: SelectedHostTerminalObserverV1 =
        serde_json::from_slice(&terminal_bytes).expect("parse terminal observer profile");
    assert_eq!(terminal.schema_version, 1);
    assert!(!terminal.observer_id.is_empty());
    assert_eq!(
        terminal.protocol,
        "thread/queue/reconcile+thread/turns/list@v2"
    );
    let agent_id = AgentId::parse(&terminal.agent_id).expect("terminal observer agent id");

    let temp = tempfile::tempdir().expect("selected-host qualification root");
    let root = temp
        .path()
        .canonicalize()
        .expect("canonical qualification root");
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
    let workspace = root.join("workspace");
    fs::create_dir(&workspace).expect("workspace");
    let workspace = workspace.canonicalize().expect("canonical workspace");
    let resources = ResourceBudget::local_default();
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet_root).expect("workspace binding"),
        resources.clone(),
    )
    .expect("agent manifest");
    let layout = registry.register(manifest).expect("register agent").layout;
    let identity = AgentdIdentity {
        agent_id: agent_id.clone(),
        layout: layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources,
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
    };
    let host = AgentdAutomationEffectHost::open(&identity, &effect_host_path)
        .expect("load exact selected-host provider/final-use/revocation configuration");
    drop(host);

    // The source files must remain byte-identical across actual product loading;
    // otherwise the receipt would bind a pre-load snapshot rather than the bytes
    // consumed by Agentd.
    assert_eq!(
        Sha256Digest::for_bytes(&read_protected_file(
            &effect_host_path,
            MAX_EFFECT_HOST_BYTES,
        )),
        expected_effect_host_sha
    );
    assert_eq!(
        Sha256Digest::for_bytes(&read_protected_file(
            &revocations_path,
            MAX_REVOCATIONS_BYTES,
        )),
        expected_revocations_sha
    );

    let receipt = json!({
        "schema": "hepta.automation-taskflow.selected-host-effect-rust-receipt.v1",
        "effectHostPath": effect_host_path,
        "effectHostSha256": expected_effect_host_sha.as_str(),
        "revocationsPath": revocations_path,
        "revocationsSha256": expected_revocations_sha.as_str(),
        "terminalObserverPath": terminal_profile_path,
        "terminalObserverSha256": expected_terminal_sha.as_str(),
        "terminalObserverId": terminal.observer_id,
        "agentId": agent_id.as_str(),
        "productConfigurationLoaded": true,
    });
    if let Some(parent) = receipt_path.parent() {
        fs::create_dir_all(parent).expect("create receipt parent");
    }
    fs::write(
        receipt_path,
        serde_json::to_vec_pretty(&receipt).expect("encode effect receipt"),
    )
    .expect("write effect receipt");
}

fn required_path(name: &str) -> PathBuf {
    PathBuf::from(env::var(name).unwrap_or_else(|_| panic!("missing {name}")))
}

fn required_digest(name: &str) -> Sha256Digest {
    let value = env::var(name).unwrap_or_else(|_| panic!("missing {name}"));
    Sha256Digest::parse(value).unwrap_or_else(|_| panic!("invalid {name}"))
}

fn read_protected_file(path: &Path, max_bytes: u64) -> Vec<u8> {
    assert!(path.is_absolute());
    assert_eq!(path.canonicalize().expect("canonical protected file"), path);
    let metadata = fs::symlink_metadata(path).expect("protected file metadata");
    assert!(metadata.is_file() && !metadata.file_type().is_symlink());
    assert!(metadata.len() > 0 && metadata.len() <= max_bytes);
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(metadata.permissions().mode() & 0o077, 0);
    fs::read(path).expect("read protected selected-host file")
}
