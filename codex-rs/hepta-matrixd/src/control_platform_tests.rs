use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::tests::FakeTransport;
use super::tests::agent_id;
#[cfg(unix)]
use super::tests::layout;
use super::tests::state;
use super::*;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[tokio::test]
async fn health_tracks_real_task_state_without_socket_capabilities() -> TestResult {
    let temp = TempDir::new()?;
    let fake = Arc::new(FakeTransport::default());
    let (state, connections) = state(&temp, fake).await?;
    let request = MatrixdRequest {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id: 41,
        agent_id: agent_id()?,
        fence: None,
        method: MatrixdMethod::Health,
    };
    let response = state.response(request).await;
    assert_eq!(response.release_id, "release-1");
    assert!(matches!(
        response.payload,
        MatrixdPayload::Health(MatrixdHealth {
            lifecycle: MatrixdLifecycle::Degraded,
            agentd_connected: false,
            matrix_sync_connected: false,
            ..
        })
    ));
    connections.set_agentd_connected(true);
    connections.set_matrix_sync_connected(true);
    assert_eq!(connections.health().lifecycle, MatrixdLifecycle::Ready);
    connections.set_fenced();
    assert_eq!(connections.health().lifecycle, MatrixdLifecycle::Fenced);
    Ok(())
}

#[cfg(not(unix))]
#[tokio::test]
async fn owner_control_refuses_without_changing_missing_or_existing_paths() -> TestResult {
    let temp = TempDir::new()?;
    let fake = Arc::new(FakeTransport::default());
    let (state, _) = state(&temp, Arc::clone(&fake)).await?;
    let missing_parent = temp.path().join("missing-control");
    let existing_parent = temp.path().join("existing-control");
    std::fs::create_dir(&existing_parent)?;
    let existing_socket = existing_parent.join("control.sock");
    std::fs::write(&existing_socket, b"existing rendezvous must survive")?;
    let sentinel = existing_parent.join("sentinel");
    std::fs::write(&sentinel, b"unrelated owner data")?;
    let before = socket_directory_image(&existing_parent)?;

    for socket in [missing_parent.join("control.sock"), existing_socket] {
        let result =
            MatrixdControlServer::bind(socket, Arc::clone(&state), CancellationToken::new()).await;
        assert!(matches!(
            result,
            Err(MatrixdControlError::Io(ref error))
                if error.kind() == ErrorKind::Unsupported
        ));
        assert!(!missing_parent.try_exists()?);
        assert_eq!(socket_directory_image(&existing_parent)?, before);
    }
    Ok(())
}

#[cfg(not(unix))]
fn socket_directory_image(
    path: &std::path::Path,
) -> std::io::Result<Vec<(std::ffi::OsString, bool, Vec<u8>)>> {
    let mut image = std::fs::read_dir(path)?
        .map(|entry| {
            let entry = entry?;
            Ok((
                entry.file_name(),
                entry.metadata()?.permissions().readonly(),
                std::fs::read(entry.path())?,
            ))
        })
        .collect::<std::io::Result<Vec<_>>>()?;
    image.sort();
    Ok(image)
}

#[cfg(unix)]
#[tokio::test]
async fn health_tracks_real_task_state_and_owner_uds_serves_exact_identity() -> TestResult {
    // The product fleet root deliberately leaves Darwin `sun_path`
    // headroom. The SSD test harness uses a much deeper TMPDIR, so put
    // this socket-binding fixture under the canonical short temp root.
    let temp = tempfile::Builder::new()
        .prefix("hmx-control-")
        .tempdir_in("/tmp")?;
    let fake = Arc::new(FakeTransport::default());
    let (state, connections) = state(&temp, fake).await?;
    let socket = layout(&temp, &agent_id()?)?
        .matrixd_control_socket()
        .to_path_buf();
    let cancel = CancellationToken::new();
    let server =
        MatrixdControlServer::bind(socket.clone(), Arc::clone(&state), cancel.clone()).await?;
    let task = tokio::spawn(server.run());

    let mut stream = UnixStream::connect(&socket).await?;
    let request = MatrixdRequest {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id: 41,
        agent_id: agent_id()?,
        fence: None,
        method: MatrixdMethod::Health,
    };
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await?;
    let mut reader = BufReader::new(stream);
    let mut response = Vec::new();
    reader.read_until(b'\n', &mut response).await?;
    let response: MatrixdResponse = serde_json::from_slice(&response)?;
    assert_eq!(response.release_id, "release-1");
    assert!(matches!(
        response.payload,
        MatrixdPayload::Health(MatrixdHealth {
            lifecycle: MatrixdLifecycle::Degraded,
            agentd_connected: false,
            matrix_sync_connected: false,
            ..
        })
    ));

    connections.set_agentd_connected(true);
    connections.set_matrix_sync_connected(true);
    assert_eq!(connections.health().lifecycle, MatrixdLifecycle::Ready);
    connections.set_fenced();
    assert_eq!(connections.health().lifecycle, MatrixdLifecycle::Fenced);
    cancel.cancel();
    task.await??;
    Ok(())
}
