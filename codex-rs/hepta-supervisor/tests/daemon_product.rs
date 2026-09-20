#![cfg(unix)]

use std::io::Read;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::SupervisordClient;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn product_binary_is_single_instance_owner_only_and_bad_frames_are_isolated() -> Result<()> {
    // The production fleet root is deliberately short enough for Darwin's
    // Unix-domain socket limit.  The SSD build harness uses a much deeper TMP
    // root, so keep this product test's synthetic fleet under a short root as
    // well instead of testing an impossible deployment geometry.
    let temp = tempfile::Builder::new()
        .prefix("hsup-product-")
        .tempdir_in("/tmp")?;
    let root = temp.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let agent_id = AgentId::parse(AGENT_ID).map_err(anyhow::Error::msg)?;
    registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;

    let mut daemon = DaemonChild::spawn(fleet_root.as_path())?;
    let client = wait_for_daemon(&registry).await?;
    let health = client.health().await?;
    ensure!(health.ready && health.registered_agents == 1);
    let initial_epoch = health.supervisor_epoch;
    ensure!(
        std::fs::metadata(registry.layout().supervisor_socket())?
            .permissions()
            .mode()
            & 0o777
            == 0o600
    );
    ensure!(
        std::fs::metadata(registry.layout().supervisor_lock())?
            .permissions()
            .mode()
            & 0o777
            == 0o600
    );

    let second = Command::new(env!("CARGO_BIN_EXE_hepta-supervisord"))
        .arg("--fleet-root")
        .arg(fleet_root.as_path())
        .output()?;
    ensure!(
        !second.status.success(),
        "a second daemon acquired the fleet"
    );

    let malformed = send_bounded_frame(registry.layout().supervisor_socket(), b"{bad json}\n")?;
    assert_wire_error(&malformed, 0, "invalid_frame")?;
    let old_schema = send_bounded_frame(
        registry.layout().supervisor_socket(),
        br#"{"schema_version":1,"request_id":9,"method":{"type":"health"}}
"#,
    )?;
    assert_wire_error(&old_schema, 9, "unsupported_schema")?;
    let zero_request = send_bounded_frame(
        registry.layout().supervisor_socket(),
        br#"{"schema_version":2,"request_id":0,"method":{"type":"health"}}
"#,
    )?;
    assert_wire_error(&zero_request, 0, "invalid_frame")?;
    let unknown_field = send_bounded_frame(
        registry.layout().supervisor_socket(),
        br#"{"schema_version":2,"request_id":10,"method":{"type":"health"},"program":"/secret/agentd"}
"#,
    )?;
    assert_wire_error(&unknown_field, 0, "invalid_frame")?;
    ensure!(
        !unknown_field.to_string().contains("/secret/agentd"),
        "invalid frame reflected private request content"
    );
    ensure!(
        client.health().await?.ready,
        "malformed frame stopped daemon"
    );
    send_oversized_frame(registry.layout().supervisor_socket())?;
    ensure!(
        client.health().await?.ready,
        "oversized frame stopped daemon"
    );

    daemon.kill()?;
    let mut restarted = DaemonChild::spawn(fleet_root.as_path())?;
    let restarted_client = wait_for_daemon(&registry).await?;
    let restarted_health = restarted_client.health().await?;
    ensure!(restarted_health.ready);
    ensure!(
        restarted_health.supervisor_epoch != initial_epoch,
        "supervisord reused its authority epoch after daemon restart"
    );
    let roster = restarted_client.roster(16).await?;
    ensure!(roster.len() == 1 && roster[0].agent_id == agent_id);
    restarted.terminate()?;
    Ok(())
}

fn send_bounded_frame(path: &std::path::Path, frame: &[u8]) -> Result<serde_json::Value> {
    let mut stream = std::os::unix::net::UnixStream::connect(path)?;
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    stream.write_all(frame)?;
    stream.shutdown(std::net::Shutdown::Write)?;
    let mut response = Vec::new();
    stream.read_to_end(&mut response)?;
    ensure!(
        response.ends_with(b"\n"),
        "bad frame did not get bounded error"
    );
    Ok(serde_json::from_slice(&response)?)
}

fn assert_wire_error(value: &serde_json::Value, request_id: u64, code: &str) -> Result<()> {
    ensure!(
        value["schema_version"] == 2
            && value["request_id"] == request_id
            && value["payload"]["type"] == "error"
            && value["payload"]["code"] == code,
        "unexpected bounded error payload: {value}"
    );
    Ok(())
}

fn send_oversized_frame(path: &std::path::Path) -> Result<()> {
    let mut stream = std::os::unix::net::UnixStream::connect(path)?;
    stream.set_write_timeout(Some(Duration::from_secs(3)))?;
    stream.write_all(&vec![b'x'; 65_537])?;
    stream.shutdown(std::net::Shutdown::Write)?;
    Ok(())
}

async fn wait_for_daemon(registry: &FleetRegistry) -> Result<SupervisordClient> {
    let deadline = Instant::now() + Duration::from_secs(10);
    let client = SupervisordClient::new(registry.layout().supervisor_socket().to_path_buf())?;
    loop {
        let last_error = match client.health().await {
            Ok(_) => return Ok(client),
            Err(error) => error,
        };
        ensure!(
            Instant::now() < deadline,
            "supervisord did not become ready: {last_error:#}"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

struct DaemonChild(Child);

impl DaemonChild {
    fn spawn(fleet_root: &std::path::Path) -> Result<Self> {
        let child = Command::new(env!("CARGO_BIN_EXE_hepta-supervisord"))
            .arg("--fleet-root")
            .arg(fleet_root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            // Keep daemon startup failures visible to the test harness.  A
            // discarded stderr turns every early exit into the same opaque
            // "did not become ready" timeout.
            .stderr(Stdio::inherit())
            .spawn()?;
        Ok(Self(child))
    }

    fn kill(&mut self) -> Result<()> {
        self.0.kill()?;
        self.0.wait()?;
        Ok(())
    }

    fn terminate(&mut self) -> Result<()> {
        let status = Command::new("/bin/kill")
            .arg("-TERM")
            .arg(self.0.id().to_string())
            .status()?;
        ensure!(status.success(), "failed to terminate supervisord");
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if self.0.try_wait()?.is_some() {
                return Ok(());
            }
            ensure!(Instant::now() < deadline, "supervisord ignored SIGTERM");
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

impl Drop for DaemonChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}
