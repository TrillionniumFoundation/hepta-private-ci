use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::AgentdControlServer;
use super::CONNECTION_CAPACITY;
use crate::AGENTD_CONTROL_OVERLOAD_FRAME;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdConfig;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AgentdState;

fn fixture() -> anyhow::Result<(tempfile::TempDir, Arc<AgentdState>)> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)?;
    let config = AgentdConfig::load(
        fleet_path,
        agent_id.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;
    let (identity, registry, _writer_lock) = config.into_parts();
    let state = Arc::new(AgentdState::new(identity, registry.clone(), 16)?);
    registry.compare_and_transition(&agent_id, 1, AgentLifecycle::Running)?;
    state.refresh_generation()?;
    Ok((temp, state))
}

#[tokio::test]
async fn rejected_control_frame_reports_owner_generation_instead_of_request_generation()
-> anyhow::Result<()> {
    let (_temp, state) = fixture()?;
    let cancellation = CancellationToken::new();
    let socket = state.identity().control_socket.clone();
    let server = AgentdControlServer::bind(socket.clone(), state, cancellation.clone()).await?;
    let server_task = tokio::spawn(server.run());
    let mut stream = UnixStream::connect(&socket).await?;
    let mut request = AgentdRequest::health(7, 987);
    request.schema_version = AGENTD_CONTROL_SCHEMA_VERSION + 1;
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await?;
    let mut response_bytes = Vec::new();
    timeout(
        Duration::from_secs(1),
        BufReader::new(stream).read_until(b'\n', &mut response_bytes),
    )
    .await??;
    let response: AgentdResponse = serde_json::from_slice(&response_bytes)?;
    assert_eq!(
        (
            response.request_id,
            response.spawn_generation,
            response.current_generation
        ),
        (7, 1, 2)
    );
    assert!(matches!(
        response.payload,
        crate::AgentdPayload::Error { code, .. } if code == "unsupported_schema"
    ));
    cancellation.cancel();
    timeout(Duration::from_secs(1), server_task).await???;
    Ok(())
}

#[tokio::test]
async fn targeted_control_request_is_rejected_by_the_receiver_before_method_dispatch()
-> anyhow::Result<()> {
    let (_temp, state) = fixture()?;
    let cancellation = CancellationToken::new();
    let socket = state.identity().control_socket.clone();
    let server = AgentdControlServer::bind(socket.clone(), state, cancellation.clone()).await?;
    let server_task = tokio::spawn(server.run());
    let mut stream = UnixStream::connect(&socket).await?;
    let mut request = AgentdRequest::drain(8, 1);
    request.target_agent_id = Some(AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?);
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await?;
    let mut response_bytes = Vec::new();
    timeout(
        Duration::from_secs(1),
        BufReader::new(stream).read_until(b'\n', &mut response_bytes),
    )
    .await??;
    let response: AgentdResponse = serde_json::from_slice(&response_bytes)?;
    assert!(matches!(
        response.payload,
        crate::AgentdPayload::Error { code, .. } if code == "target_agent_mismatch"
    ));
    cancellation.cancel();
    timeout(Duration::from_secs(1), server_task).await???;
    Ok(())
}

#[tokio::test]
async fn retiring_control_server_closes_all_admitted_connections() -> anyhow::Result<()> {
    let (_temp, state) = fixture()?;
    let cancellation = CancellationToken::new();
    let socket = state.identity().control_socket.clone();
    let server = AgentdControlServer::bind(socket.clone(), state, cancellation.clone()).await?;
    let permits = Arc::clone(&server.connections);
    let server_task = tokio::spawn(server.run());
    let mut streams = Vec::new();
    for _ in 0..CONNECTION_CAPACITY {
        let mut stream = UnixStream::connect(&socket).await?;
        stream.write_all(b"{").await?;
        streams.push(stream);
    }
    timeout(Duration::from_secs(1), async {
        while permits.available_permits() != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await?;

    let mut overload = UnixStream::connect(&socket).await?;
    let mut frame = Vec::new();
    timeout(Duration::from_secs(1), overload.read_to_end(&mut frame)).await??;
    assert_eq!(frame.as_slice(), AGENTD_CONTROL_OVERLOAD_FRAME);

    cancellation.cancel();
    timeout(Duration::from_secs(1), server_task).await???;
    assert_eq!(permits.available_permits(), CONNECTION_CAPACITY);
    for mut stream in streams {
        let mut frame = Vec::new();
        timeout(Duration::from_secs(1), stream.read_to_end(&mut frame)).await??;
        assert!(
            frame.is_empty(),
            "incomplete requests cannot receive a response"
        );
    }
    assert!(!socket.exists());
    Ok(())
}
