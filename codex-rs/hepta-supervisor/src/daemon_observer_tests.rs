use anyhow::Result;
use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;

use super::super::shutdown_tests::Fixture;
use super::*;
use crate::robrix_protocol::RobrixSupervisordMethod;
use crate::robrix_protocol::RobrixSupervisordPayload;

async fn exchange(path: &Path, request: &[u8]) -> Result<Vec<u8>> {
    let mut stream = UnixStream::connect(path).await?;
    stream.write_all(request).await?;
    stream.shutdown().await?;
    let mut bytes = Vec::new();
    timeout(
        IO_TIMEOUT,
        stream
            .take(MAX_ROBRIX_SUPERVISORD_RESPONSE_BYTES + 1)
            .read_to_end(&mut bytes),
    )
    .await??;
    Ok(bytes)
}

#[tokio::test(flavor = "current_thread")]
async fn enrolled_observer_reads_the_original_owner_while_writer_is_held() -> Result<()> {
    let fixture = Fixture::new()?;
    let path = fixture
        .state
        .registry
        .layout()
        .run_root()
        .join("observer/ctl");
    let server = ObserverServer::bind(
        path.clone(),
        Arc::clone(&fixture.state),
        fixture.cancellation.clone(),
        Principal {
            uid: unsafe { libc::geteuid() },
            gid: unsafe { libc::getegid() },
        },
    )
    .await?;
    let task = tokio::spawn(server.run());
    let writer = fixture.state.supervisor.lock().await;
    fixture.state.execution.view.publish(
        &fixture.state.registry,
        &writer,
        &fixture.state.supervisor_epoch,
        /*recovery_observation_blocked*/ false,
    )?;
    let client = crate::SupervisorObserverClient::new(path.clone(), unsafe { libc::geteuid() })?;
    for method in [
        RobrixSupervisordMethod::Health,
        RobrixSupervisordMethod::Roster {
            limit: MAX_SUPERVISORD_ROSTER,
        },
        RobrixSupervisordMethod::Snapshot {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        },
    ] {
        match client.query(method).await? {
            RobrixSupervisordPayload::Health(health) => {
                assert_eq!(health.supervisor_epoch, fixture.state.supervisor_epoch);
                assert_eq!(health.process_id, std::process::id());
                assert_eq!(health.registered_agents, 0);
                assert!(health.ready);
            }
            RobrixSupervisordPayload::Roster { agents } => assert!(agents.is_empty()),
            RobrixSupervisordPayload::Error { code, actual, .. } => {
                assert_eq!(code, "unknown_agent");
                assert_eq!(actual, None);
            }
            payload => panic!("unexpected observation: {payload:?}"),
        }
    }
    drop(writer);
    fixture.cancellation.cancel();
    task.await??;
    assert!(!path.exists());
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn mutation_and_malformed_frames_cannot_enter_original_owner() -> Result<()> {
    let fixture = Fixture::new()?;
    let original = fixture.state.registry.load()?;
    let path = fixture
        .state
        .registry
        .layout()
        .run_root()
        .join("observer/ctl");
    let server = ObserverServer::bind(
        path.clone(),
        Arc::clone(&fixture.state),
        fixture.cancellation.clone(),
        Principal {
            uid: unsafe { libc::geteuid() },
            gid: unsafe { libc::getegid() },
        },
    )
    .await?;
    let task = tokio::spawn(server.run());
    for (request_id, method) in [
        (81, serde_json::json!({"type": "start"})),
        (
            82,
            serde_json::json!({"type": "health", "release_id": "foreign"}),
        ),
        (0, serde_json::json!({"type": "health"})),
    ] {
        let mut frame = serde_json::to_vec(&serde_json::json!({
            "schema_version": SUPERVISORD_CONTROL_SCHEMA_VERSION,
            "request_id": request_id,
            "method": method,
        }))?;
        frame.push(b'\n');
        assert!(exchange(&path, &frame).await?.is_empty());
    }
    assert_eq!(fixture.state.registry.load()?, original);
    fixture.cancellation.cancel();
    task.await??;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn kernel_peer_rejection_precedes_even_a_health_query() -> Result<()> {
    let fixture = Fixture::new()?;
    let path = fixture
        .state
        .registry
        .layout()
        .run_root()
        .join("observer/ctl");
    let server = ObserverServer::bind(
        path.clone(),
        Arc::clone(&fixture.state),
        fixture.cancellation.clone(),
        Principal {
            uid: unsafe { libc::geteuid() }.checked_add(1).expect("test UID"),
            gid: unsafe { libc::getegid() },
        },
    )
    .await?;
    let task = tokio::spawn(server.run());
    let mut stream = UnixStream::connect(&path).await?;
    // A real kernel peer is rejected without consuming or decoding any bytes.
    let mut bytes = Vec::new();
    timeout(IO_TIMEOUT, stream.read_to_end(&mut bytes)).await??;
    assert!(bytes.is_empty());
    fixture.cancellation.cancel();
    task.await??;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn unavailable_observation_has_no_authoritative_read_fallback() -> Result<()> {
    let fixture = Fixture::new()?;
    let path = fixture
        .state
        .registry
        .layout()
        .run_root()
        .join("observer/ctl");
    let server = ObserverServer::bind(
        path.clone(),
        Arc::clone(&fixture.state),
        fixture.cancellation.clone(),
        Principal {
            uid: unsafe { libc::geteuid() },
            gid: unsafe { libc::getegid() },
        },
    )
    .await?;
    fixture.state.execution.view.invalidate();
    let task = tokio::spawn(server.run());
    let mut request = serde_json::to_vec(&RobrixSupervisordRequest::new(
        91,
        RobrixSupervisordMethod::Health,
    ))?;
    request.push(b'\n');
    let bytes = exchange(&path, &request).await?;
    let response: RobrixSupervisordResponse = serde_json::from_slice(&bytes)?;
    response.validate(91)?;
    assert!(
        matches!(response.payload, RobrixSupervisordPayload::Error { ref code, .. } if code == "control_state_unavailable")
    );
    fixture.cancellation.cancel();
    task.await??;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn client_rejects_another_request_id_and_another_query_projection() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("observer");
    let mut listener = UnixListener::bind(&path).await?;
    let client = crate::SupervisorObserverClient::new(path, unsafe { libc::geteuid() })?;
    let peer = tokio::spawn(async move {
        for substitute_id in [true, false] {
            let stream = listener.accept().await?;
            let (reader, mut writer) = tokio::io::split(stream);
            let mut reader = BufReader::new(reader);
            let mut bytes = Vec::new();
            reader.read_until(b'\n', &mut bytes).await?;
            let request: RobrixSupervisordRequest = serde_json::from_slice(&bytes)?;
            let response = RobrixSupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: if substitute_id {
                    request.request_id + 1
                } else {
                    request.request_id
                },
                payload: RobrixSupervisordPayload::Roster { agents: Vec::new() },
            };
            let mut bytes = serde_json::to_vec(&response)?;
            bytes.push(b'\n');
            writer.write_all(&bytes).await?;
            writer.shutdown().await?;
        }
        anyhow::Ok(())
    });
    let identity_error = client
        .query(RobrixSupervisordMethod::Health)
        .await
        .expect_err("foreign request identity");
    assert!(
        identity_error
            .to_string()
            .contains("invalid Robrix control envelope")
    );
    let projection_error = client
        .query(RobrixSupervisordMethod::Health)
        .await
        .expect_err("foreign query projection");
    assert!(
        projection_error
            .to_string()
            .contains("another query's projection")
    );
    peer.await??;
    Ok(())
}
