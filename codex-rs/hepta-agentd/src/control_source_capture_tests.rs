//! Real control sockets exercise ownership; private receipts are never fabricated.

use anyhow::Context;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_uds::UnixStream;
use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::RuntimeFixture;
use super::attach_runtime_prerequisites;
use super::runtime_fixture;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdControlServer;
use crate::AgentdError;
use crate::AgentdMethod;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::runtime::source_capture::run_until_original_source_drain;

async fn await_accepted(state: &Arc<AgentdState>) -> anyhow::Result<()> {
    timeout(Duration::from_secs(1), async {
        while Arc::strong_count(state) < 3 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .context("the real control supervisor accepted the connection")?;
    Ok(())
}

async fn finish_health(stream: &mut UnixStream) -> anyhow::Result<()> {
    let request = AgentdRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 91,
        spawn_generation: 1,
        method: AgentdMethod::Health,
    };
    let mut bytes = serde_json::to_vec(&request).context("encode health")?;
    bytes.push(b'\n');
    stream
        .write_all(&bytes)
        .await
        .context("send real request")?;
    let mut response = Vec::new();
    timeout(Duration::from_secs(1), stream.read_to_end(&mut response))
        .await
        .context("bounded real response")?
        .context("read response")?;
    let response: AgentdResponse = serde_json::from_slice(&response).context("decode response")?;
    assert_eq!(response.request_id, request.request_id);
    Ok(())
}

#[tokio::test]
async fn source_capture_control_waits_for_accepted_connection_before_join_receipt()
-> anyhow::Result<()> {
    let fixture = runtime_fixture();
    let cancellation = CancellationToken::new();
    let mut server = AgentdControlServer::bind(
        fixture.identity.control_socket.clone(),
        Arc::clone(&fixture.state),
        cancellation.clone(),
    )
    .await
    .expect("bind original control socket");
    let receipt = server.original_source_capture_join().expect("select join");
    let mut running = tokio::spawn(server.run());
    let mut stream = UnixStream::connect(&fixture.identity.control_socket)
        .await
        .expect("connect");
    await_accepted(&fixture.state).await?;
    cancellation.cancel();
    assert!(
        timeout(Duration::from_millis(20), &mut running)
            .await
            .is_err(),
        "shutdown must wait for the already accepted request"
    );
    finish_health(&mut stream).await?;
    running
        .await
        .expect("join supervisor")
        .expect("clean control completion");
    receipt
        .require_original_control_join()
        .expect("actual join receipt");
    assert_eq!(Arc::strong_count(&fixture.state), 1);
    Ok(())
}

#[tokio::test]
async fn source_capture_control_drains_after_a_health_reader_disconnects() -> anyhow::Result<()> {
    let fixture = runtime_fixture();
    let cancellation = CancellationToken::new();
    let mut server = AgentdControlServer::bind(
        fixture.identity.control_socket.clone(),
        Arc::clone(&fixture.state),
        cancellation.clone(),
    )
    .await
    .context("bind control")?;
    let receipt = server.original_source_capture_join()?;
    // Queue a valid probe then drop the reader before the server starts.
    // This exercises a real disconnected peer without a timing assumption.
    let mut disconnected = UnixStream::connect(&fixture.identity.control_socket).await?;
    let mut request = serde_json::to_vec(&AgentdRequest::health(90, 1))?;
    request.push(b'\n');
    disconnected.write_all(&request).await?;
    drop(disconnected);

    let running = tokio::spawn(server.run());
    let mut connected = UnixStream::connect(&fixture.identity.control_socket).await?;
    finish_health(&mut connected).await?;
    cancellation.cancel();
    running.await??;
    receipt.require_original_control_join()?;
    assert_eq!(Arc::strong_count(&fixture.state), 1);
    Ok(())
}

#[tokio::test]
async fn source_capture_control_retains_connection_error_without_stopping_other_requests()
-> anyhow::Result<()> {
    let fixture = runtime_fixture();
    let cancellation = CancellationToken::new();
    let mut server = AgentdControlServer::bind(
        fixture.identity.control_socket.clone(),
        Arc::clone(&fixture.state),
        cancellation.clone(),
    )
    .await
    .expect("bind");
    let receipt = server.original_source_capture_join().expect("select join");
    let running = tokio::spawn(server.run());
    let mut invalid = UnixStream::connect(&fixture.identity.control_socket)
        .await
        .expect("connect invalid frame");
    invalid
        .write_all(b"invalid-json\n")
        .await
        .expect("send malformed frame");
    let mut discarded = Vec::new();
    timeout(Duration::from_secs(1), invalid.read_to_end(&mut discarded))
        .await
        .expect("bounded failed connection")
        .expect("failed connection closed");
    let mut valid = UnixStream::connect(&fixture.identity.control_socket)
        .await
        .expect("connect after failed request");
    finish_health(&mut valid).await?;
    cancellation.cancel();
    assert!(running.await.expect("join supervisor").is_err());
    assert!(receipt.require_original_control_join().is_err());
    assert_eq!(Arc::strong_count(&fixture.state), 1);
    Ok(())
}

#[tokio::test]
async fn source_capture_control_supervisor_abort_cannot_acknowledge_join() -> anyhow::Result<()> {
    let fixture = runtime_fixture();
    let cancellation = CancellationToken::new();
    let mut server = AgentdControlServer::bind(
        fixture.identity.control_socket.clone(),
        Arc::clone(&fixture.state),
        cancellation.clone(),
    )
    .await
    .expect("bind");
    let receipt = server.original_source_capture_join().expect("select join");
    // A short test grace forces the real supervisor's abort path. Product
    // grace and transport deadlines remain unchanged.
    let mut tasks =
        RuntimeTasks::new(cancellation, Duration::from_millis(20)).expect("task supervisor");
    tasks
        .spawn_required("control-server", server.run())
        .expect("own control");
    let mut stream = UnixStream::connect(&fixture.identity.control_socket)
        .await
        .expect("connect pending frame");
    await_accepted(&fixture.state).await?;
    tasks
        .run_until(async { Ok(()) })
        .await
        .expect("bounded shutdown");
    assert!(receipt.require_original_control_join().is_err());
    let mut bytes = Vec::new();
    timeout(Duration::from_secs(1), stream.read_to_end(&mut bytes))
        .await
        .expect("aborted accepted connection must close")
        .expect("read EOF");
    assert_eq!(bytes, Vec::<u8>::new());
    assert_eq!(Arc::strong_count(&fixture.state), 1);
    Ok(())
}

#[tokio::test]
async fn source_capture_runtime_cancellation_without_actual_drain_is_refused() {
    let RuntimeFixture { _temp, state, .. } = runtime_fixture();
    let cancellation = CancellationToken::new();
    let mut server = AgentdControlServer::bind(
        state.identity().control_socket.clone(),
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await
    .expect("bind");
    let receipt = server.original_source_capture_join().expect("select join");
    let mut tasks =
        RuntimeTasks::new(cancellation.clone(), Duration::from_secs(1)).expect("task supervisor");
    tasks
        .spawn_required("control-server", server.run())
        .expect("own control");
    cancellation.cancel();
    let result = run_until_original_source_drain(
        &mut tasks,
        state,
        std::future::pending::<Result<(), AgentdError>>(),
        receipt,
    )
    .await;
    assert!(matches!(result, Err(AgentdError::Protocol(message))
        if message == "original runtime returned without an actual drain"));
}

#[tokio::test]
async fn source_capture_runtime_requires_actual_drain_join_and_state_release() {
    let fixture = runtime_fixture();
    attach_runtime_prerequisites(&fixture).await;
    fixture
        .state
        .attach_automation_store(
            AutomationStore::open(&fixture.identity.layout)
                .await
                .expect("real automation store"),
        )
        .expect("attach automation");
    fixture
        .registry
        .compare_and_transition(&fixture.identity.agent_id, 1, AgentLifecycle::Running)
        .expect("running generation");
    fixture.state.refresh_generation().expect("refresh running");
    fixture.state.mark_app_server_ready().expect("ready");
    let RuntimeFixture { _temp, state, .. } = fixture;
    let released = Arc::downgrade(&state);
    let cancellation = CancellationToken::new();
    let mut server = AgentdControlServer::bind(
        state.identity().control_socket.clone(),
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await
    .expect("bind");
    let receipt = server.original_source_capture_join().expect("select join");
    let mut tasks =
        RuntimeTasks::new(cancellation, Duration::from_secs(1)).expect("task supervisor");
    tasks
        .spawn_required("control-server", server.run())
        .expect("own control");
    let drained = run_until_original_source_drain(&mut tasks, state, async { Ok(()) }, receipt)
        .await
        .expect("real drain, successful control join and State release");
    drained.require_released_state().expect("still released");
    assert!(released.upgrade().is_none());
}
