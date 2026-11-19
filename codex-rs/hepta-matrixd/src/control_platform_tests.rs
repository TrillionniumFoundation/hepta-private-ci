use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::tests::FakeTransport;
use super::tests::agent_id;
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
