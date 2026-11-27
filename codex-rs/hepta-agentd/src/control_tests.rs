use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_uds::UnixListener;
use codex_uds::UnixStream;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::AgentdControlServer;
use crate::AgentdIdentity;
use crate::AgentdState;

fn fixture() -> anyhow::Result<(tempfile::TempDir, Arc<AgentdState>)> {
    // Darwin sockaddr_un is short and TMPDIR can be deeply nested. Keep the
    // transport pathname under /tmp; canonicalize only the Fleet state root.
    let temp = tempfile::Builder::new().prefix("ad").tempdir_in("/tmp")?;
    let root = temp.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = AgentdState::new(identity, registry, /*event_capacity*/ 16)?;
    Ok((temp, Arc::new(state)))
}

#[tokio::test]
async fn retired_control_server_removes_its_owned_socket() -> anyhow::Result<()> {
    let (temp, state) = fixture()?;
    let socket = temp.path().join("control.sock");
    let server = AgentdControlServer::bind(socket.clone(), state, CancellationToken::new()).await?;
    assert!(fs::symlink_metadata(&socket).is_ok());
    drop(server);
    assert!(matches!(
        fs::symlink_metadata(&socket),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound
    ));
    Ok(())
}

#[tokio::test]
async fn retired_control_server_preserves_a_successor_socket() -> anyhow::Result<()> {
    let (temp, state) = fixture()?;
    let socket = temp.path().join("control.sock");
    let server = AgentdControlServer::bind(socket.clone(), state, CancellationToken::new()).await?;
    fs::remove_file(&socket)?;
    let mut successor = UnixListener::bind(&socket).await?;
    drop(server);
    let connected = timeout(Duration::from_secs(1), UnixStream::connect(&socket)).await??;
    timeout(Duration::from_secs(1), successor.accept()).await??;
    drop(connected);
    Ok(())
}

#[tokio::test]
async fn retired_control_server_preserves_a_replacement_file() -> anyhow::Result<()> {
    let (temp, state) = fixture()?;
    let socket = temp.path().join("control.sock");
    let server = AgentdControlServer::bind(socket.clone(), state, CancellationToken::new()).await?;
    fs::remove_file(&socket)?;
    fs::write(&socket, b"successor-owned content")?;
    drop(server);
    assert_eq!(fs::read(&socket)?, b"successor-owned content");
    Ok(())
}

#[tokio::test]
async fn retired_control_server_preserves_a_replacement_symlink() -> anyhow::Result<()> {
    let (temp, state) = fixture()?;
    let socket = temp.path().join("control.sock");
    let target = temp.path().join("replacement-owner");
    fs::write(&target, b"replacement target")?;
    let server = AgentdControlServer::bind(socket.clone(), state, CancellationToken::new()).await?;
    fs::remove_file(&socket)?;
    std::os::unix::fs::symlink(&target, &socket)?;
    drop(server);
    assert_eq!(fs::read_link(&socket)?, target);
    assert_eq!(fs::read(&target)?, b"replacement target");
    Ok(())
}

#[tokio::test]
async fn retired_control_server_tolerates_an_already_removed_socket() -> anyhow::Result<()> {
    let (temp, state) = fixture()?;
    let socket = temp.path().join("control.sock");
    let server = AgentdControlServer::bind(socket.clone(), state, CancellationToken::new()).await?;
    fs::remove_file(&socket)?;
    drop(server);
    assert!(matches!(
        fs::symlink_metadata(&socket),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound
    ));
    Ok(())
}
