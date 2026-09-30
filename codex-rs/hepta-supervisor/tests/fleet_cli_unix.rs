#![cfg(unix)]

use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::SupervisordClient;
use codex_utils_cargo_bin::cargo_bin;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const OTHER_AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";

struct Daemon(Child);

impl Drop for Daemon {
    fn drop(&mut self) {
        // This is the test's own daemon, never a Cargo process or other fleet.
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn cli(root: &Path, args: &[&str]) -> std::process::Output {
    Command::new(cargo_bin("hepta-fleetctl").expect("fleetctl binary"))
        .arg("--fleet-root")
        .arg(root)
        .args(args)
        .output()
        .expect("execute fleetctl")
}

fn success(root: &Path, args: &[&str]) -> Value {
    let deadline = Instant::now() + Duration::from_secs(5);
    let output = loop {
        let output = cli(root, args);
        // Only a read can be repeated. Mutations retain their exact request ID
        // and any uncertain response is an error requiring a status query.
        let read = matches!(
            args.first(),
            Some(&"health" | &"roster" | &"snapshot" | &"mutation-status" | &"retirement-status")
        );
        if output.status.success() || !read || Instant::now() >= deadline {
            break output;
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    assert!(
        output.status.success(),
        "command {args:?}: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("CLI JSON")
}

#[tokio::test]
async fn cli_installs_immutable_release_controls_real_process_and_queries_durable_outcome() {
    let directory = tempfile::Builder::new()
        .prefix("h7-cli-")
        .tempdir_in("/tmp")
        .expect("short socket root");
    let root = directory.path().join("fleet");
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let workspace = workspace.canonicalize().expect("canonical workspace");
    success(&root, &["init"]);
    success(
        &root,
        &["register", AGENT, workspace.to_str().expect("path")],
    );
    // A real installed executable verifies release copying and process control;
    // it has no authority fixtures, model tokens, or fake readiness service.
    success(
        &root,
        &[
            "install-release",
            "local-v1",
            "/bin/sleep",
            "--agentd-arg",
            "30",
        ],
    );
    success(&root, &["allow-release", AGENT, "local-v1"]);
    let root_type = HeptaFleetRoot::parse(root.clone()).expect("fleet root");
    let registry = FleetRegistry::open_existing(root_type.clone()).expect("registry");
    let agent = AgentId::parse(AGENT).expect("agent");
    let installed = registry
        .resolve_release(&agent, &"local-v1".parse().expect("release"))
        .expect("installed release");
    assert_eq!(
        std::fs::read(&installed.program).expect("installed bytes"),
        std::fs::read("/bin/sleep").expect("source bytes")
    );
    let mut daemon = Daemon(
        Command::new(cargo_bin("hepta-supervisord").expect("Supervisor binary"))
            .arg("--fleet-root")
            .arg(&root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("actual Supervisor daemon"),
    );
    let client = SupervisordClient::new(root_type.layout().supervisor_socket().to_path_buf())
        .expect("client")
        .with_timeout(Duration::from_secs(10))
        .expect("bounded installation transport");
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if client.health().await.is_ok() {
            break;
        }
        assert!(Instant::now() < deadline, "daemon never bound its socket");
        assert!(
            daemon.0.try_wait().expect("daemon status").is_none(),
            "daemon exited"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let started = success(&root, &["start", AGENT, "local-v1", "7001"]);
    let active = client.snapshot(agent.clone()).await.expect("owned process");
    assert!(active.active);
    assert!(active.process_id.is_some());
    let deadline = Instant::now() + Duration::from_secs(5);
    let status = loop {
        match client.ordinary_mutation_status(agent.clone(), 7001).await {
            Ok(status) => break status,
            Err(error) => {
                assert!(Instant::now() < deadline, "durable query failed: {error}");
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        }
    };
    assert_eq!(
        success(&root, &["mutation-status", AGENT, "7001"]),
        json!({"requestId": 7001, "status": status})
    );
    assert_eq!(
        started["agent"],
        serde_json::to_value(&active).expect("status JSON")
    );
    let repeated = cli(&root, &["start", AGENT, "local-v1", "7001"]);
    assert!(!repeated.status.success());
    // Both recorded-ID rejection and busy admission are safe refusals. Neither
    // response may create another process or alter the durable original result.
    assert_eq!(
        client.snapshot(agent.clone()).await.expect("same process"),
        active
    );
    assert_eq!(
        success(&root, &["mutation-status", AGENT, "7001"]),
        json!({"requestId": 7001, "status": status})
    );

    let other_workspace = directory.path().join("other-workspace");
    std::fs::create_dir(&other_workspace).expect("other workspace");
    let forbidden = cli(
        &root,
        &[
            "register",
            OTHER_AGENT,
            other_workspace.to_str().expect("path"),
        ],
    );
    assert!(!forbidden.status.success());
    assert!(String::from_utf8_lossy(&forbidden.stderr).contains("another supervisord owns"));
    assert!(
        !root_type
            .layout()
            .agent(&AgentId::parse(OTHER_AGENT).expect("other agent"))
            .agent_root()
            .exists()
    );
    success(&root, &["kill", AGENT, "7002"]);
    await_terminal(&client, &agent).await;
}

#[test]
fn cli_rejects_invalid_mutation_identity_before_connecting() {
    let directory = tempfile::tempdir().expect("directory");
    let output = cli(
        &directory.path().join("absent"),
        &["start", AGENT, "local-v1", "0"],
    );
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("REQUEST_ID must be nonzero"));
    assert!(!String::from_utf8_lossy(&output.stderr).contains("No such file"));
}

#[test]
fn cli_rejects_unknown_install_flags_without_publishing_release() {
    let directory = tempfile::tempdir().expect("directory");
    let root = directory.path().join("fleet");
    success(&root, &["init"]);
    let output = cli(
        &root,
        &[
            "install-release",
            "local-v1",
            "/bin/sleep",
            "--credential-profile",
            "/tmp/profile",
        ],
    );
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("unknown install-release argument"));
    assert!(!root.join("releases/local-v1").exists());
}

#[tokio::test]
async fn live_registration_and_retirement_preserve_history_under_the_same_daemon() {
    let directory = tempfile::Builder::new()
        .prefix("h7-hot-")
        .tempdir_in("/tmp")
        .expect("short root");
    let root = directory.path().join("fleet");
    let workspace = directory.path().join("workspace");
    let peer_workspace = directory.path().join("peer-workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    std::fs::create_dir(&peer_workspace).expect("peer workspace");
    success(&root, &["init"]);
    success(
        &root,
        &[
            "install-release",
            "local-v1",
            "/bin/sleep",
            "--agentd-arg",
            "30",
        ],
    );
    let root_type = HeptaFleetRoot::parse(root.clone()).expect("root");
    let registry = FleetRegistry::open_existing(root_type.clone()).expect("registry");
    let mut daemon = Daemon(
        Command::new(cargo_bin("hepta-supervisord").expect("daemon"))
            .arg("--fleet-root")
            .arg(&root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("Supervisor"),
    );
    let client = SupervisordClient::new(root_type.layout().supervisor_socket().to_path_buf())
        .expect("client")
        .with_timeout(Duration::from_secs(10))
        .expect("transport");
    let deadline = Instant::now() + Duration::from_secs(5);
    let epoch = loop {
        if let Ok(health) = client.health().await {
            break health.supervisor_epoch;
        }
        assert!(
            Instant::now() < deadline && daemon.0.try_wait().expect("status").is_none(),
            "daemon unavailable"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    let registered = success(
        &root,
        &[
            "register-live",
            AGENT,
            workspace.to_str().expect("workspace"),
        ],
    );
    assert_eq!(
        success(
            &root,
            &[
                "register-live",
                AGENT,
                workspace.to_str().expect("workspace")
            ]
        ),
        registered
    );
    let changed_identity = cli(
        &root,
        &[
            "register-live",
            AGENT,
            peer_workspace.to_str().expect("workspace"),
        ],
    );
    assert!(!changed_identity.status.success());
    success(
        &root,
        &[
            "register-live",
            OTHER_AGENT,
            peer_workspace.to_str().expect("peer"),
        ],
    );
    let agent = AgentId::parse(AGENT).expect("agent");
    let peer = AgentId::parse(OTHER_AGENT).expect("peer");
    let before = client
        .snapshot(agent.clone())
        .await
        .expect("registered Agent");
    success(&root, &["allow-release-live", AGENT, "local-v1"]);
    success(&root, &["start", AGENT, "local-v1", "8001"]);
    let running = client.snapshot(agent.clone()).await.expect("owned process");
    let peer_before = client.snapshot(peer.clone()).await.expect("peer");
    assert!(running.active);
    assert!(
        client
            .retire_agent(running.control_fence.clone())
            .await
            .is_err(),
        "live process cannot be archived"
    );
    assert_eq!(
        success(&root, &["retirement-status", AGENT]),
        json!({"agentId": agent, "archivedRoot": null})
    );
    assert_eq!(
        client.snapshot(peer.clone()).await.expect("unchanged peer"),
        peer_before
    );
    assert!(
        client.retire_agent(before.control_fence).await.is_err(),
        "stale fence cannot retire a replacement"
    );
    success(&root, &["kill", AGENT, "8002"]);
    await_terminal(&client, &agent).await;
    let agent_root = root_type.layout().agent(&agent).agent_root().to_path_buf();
    let history = agent_root.join("operator-history.txt");
    std::fs::write(&history, b"complete retained private history\n").expect("private history");
    let retired = success(&root, &["retire", AGENT]);
    let archive = registry
        .retired_agent_path(&agent)
        .expect("archive")
        .expect("durable retirement");
    assert_eq!(retired, json!({"agentId": agent, "archivedRoot": archive}));
    assert_eq!(success(&root, &["retirement-status", AGENT]), retired);
    assert_eq!(
        std::fs::read(archive.join("operator-history.txt")).expect("preserved history"),
        b"complete retained private history\n"
    );
    assert!(!agent_root.exists());
    assert_eq!(
        client
            .snapshot(peer.clone())
            .await
            .expect("peer survives retirement"),
        peer_before
    );
    assert_eq!(
        client.health().await.expect("same daemon").supervisor_epoch,
        epoch
    );
    assert!(daemon.0.try_wait().expect("same process").is_none());
    assert!(
        !cli(
            &root,
            &[
                "register-live",
                AGENT,
                workspace.to_str().expect("workspace")
            ]
        )
        .status
        .success(),
        "retired identity cannot be reused"
    );
    let new_id = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c14";
    success(
        &root,
        &[
            "register-live",
            new_id,
            workspace.to_str().expect("workspace"),
        ],
    );
    assert_eq!(
        client.snapshot(peer).await.expect("peer still unchanged"),
        peer_before
    );
    assert!(
        archive.exists(),
        "new workspace registration cannot erase retired identity"
    );
}

async fn await_terminal(client: &SupervisordClient, agent: &AgentId) {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Ok(snapshot) = client.snapshot(agent.clone()).await
            && !snapshot.active
            && snapshot.process_id.is_none()
        {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "exact child exit was never observed"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}
