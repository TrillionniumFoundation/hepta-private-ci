use super::*;

#[tokio::test]
async fn control_peer_check_runs_before_control_frames() {
    let temp_dir = tempfile::tempdir().expect("temporary directory");
    let socket_path = temp_dir.path().join("agentd-control.sock");
    let mut listener = UnixListener::bind(&socket_path)
        .await
        .expect("control listener should bind");
    let client_path = socket_path.clone();
    let client_task = tokio::spawn(async move { UnixStream::connect(client_path).await });
    let server_stream = listener
        .accept()
        .await
        .expect("control peer should connect");
    #[cfg(unix)]
    ensure_control_peer(&server_stream).expect("same-UID control peer should pass");
    #[cfg(windows)]
    assert!(
        matches!(
            ensure_control_peer(&server_stream),
            Err(AgentdError::Io(error)) if error.kind() == ErrorKind::Unsupported
        ),
        "Windows AF_UNIX cannot authorize frames without kernel peer credentials"
    );
    let _client_stream = client_task
        .await
        .expect("client task should join")
        .expect("client should connect");
}

#[test]
fn accept_path_authenticates_before_consuming_a_permit() {
    let source = include_str!("control.rs");
    let peer_check = source
        .find("ensure_control_peer(&stream)")
        .expect("accept path must authenticate the peer");
    let permit = source
        .find("try_acquire_owned")
        .expect("accept path must retain the bounded permit");
    assert!(
        peer_check < permit,
        "peer authentication must precede permit allocation"
    );
}
