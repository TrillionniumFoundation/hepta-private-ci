use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use tokio_util::sync::CancellationToken;

use super::AgentdControlServer;
use super::CONNECTION_CAPACITY;
use crate::AGENTD_OVERLOAD_RETRY_AFTER_MS;
use crate::AgentdClient;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

// Use the actual registry and prompt owner. Do not grant readiness or attach a
// substitute state owner just to exercise the transport.
fn state_fixture() -> TestResult<(tempfile::TempDir, Arc<AgentdState>)> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let agent_id = AgentId::parse("11111111-1111-4111-8111-111111111111")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)?;
    std::fs::create_dir_all(record.layout.home_root())?;
    std::fs::create_dir_all(record.layout.run_root())?;
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
    Ok((
        directory,
        Arc::new(AgentdState::new(identity, registry, 16)?),
    ))
}

#[tokio::test]
async fn ordinary_control_preserves_server_identity_and_launch_generation() -> TestResult {
    let (_directory, state) = state_fixture()?;
    let identity = state.identity().clone();
    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let server =
        AgentdControlServer::bind(identity.control_socket.clone(), state, cancellation.clone())
            .await?;
    let task = tokio::spawn(server.run());
    let client = AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
    )?;
    let health = client.health().await?;
    assert_eq!(health.process_id, std::process::id());
    assert_eq!(health.home_root, identity.home_root);
    assert_eq!(health.lifecycle, AgentLifecycle::Starting);
    assert!(!health.ready);
    assert!(!health.promotion_ready);
    for (agent_id, generation) in [
        (
            AgentId::parse("22222222-2222-4222-8222-222222222222")?,
            identity.spawn_generation,
        ),
        (identity.agent_id, identity.spawn_generation + 1),
    ] {
        let wrong = AgentdClient::new(identity.control_socket.clone(), agent_id, generation)?;
        assert!(
            matches!(wrong.health().await, Err(AgentdError::Protocol(_))),
            "a same-user connection must not replace agent or launch identity"
        );
    }
    cancellation.cancel();
    task.await??;
    Ok(())
}

#[tokio::test]
async fn saturated_ordinary_control_returns_original_overload_and_recovers() -> TestResult {
    let (_directory, state) = state_fixture()?;
    let identity = state.identity().clone();
    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let server =
        AgentdControlServer::bind(identity.control_socket.clone(), state, cancellation.clone())
            .await?;
    // Hold the actual server's whole existing limit deterministically. The
    // response still crosses its real accept/authenticate/overload path.
    let permits = Arc::clone(&server.connections)
        .try_acquire_many_owned(u32::try_from(CONNECTION_CAPACITY)?)?;
    let task = tokio::spawn(server.run());
    let client = AgentdClient::new(
        identity.control_socket,
        identity.agent_id,
        identity.spawn_generation,
    )?;
    assert!(matches!(
        client.health().await,
        Err(AgentdError::Overloaded { retry_after_ms })
            if retry_after_ms == AGENTD_OVERLOAD_RETRY_AFTER_MS
    ));
    drop(permits);
    assert_eq!(client.health().await?.process_id, std::process::id());
    cancellation.cancel();
    task.await??;
    Ok(())
}
