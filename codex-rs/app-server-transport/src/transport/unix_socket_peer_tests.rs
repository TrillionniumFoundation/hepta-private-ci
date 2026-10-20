use super::*;

#[tokio::test]
async fn accepted_peer_passes_kernel_identity_gate() -> IoResult<()> {
    let temp_dir = tempfile::tempdir()?;
    let socket_path = temp_dir.path().join("app-server-control.sock");
    let mut listener = UnixListener::bind(&socket_path).await?;
    let client_path = socket_path.clone();
    let client_task = tokio::spawn(async move { UnixStream::connect(client_path).await });
    let server_stream = listener.accept().await?;
    ensure_control_peer(&server_stream)?;
    client_task.await.expect("client task should join")?;
    Ok(())
}

#[test]
fn accept_path_authenticates_before_websocket_upgrade() {
    let source = include_str!("unix_socket.rs");
    let peer_check = source
        .find("ensure_control_peer(&stream)")
        .expect("accept path must authenticate the peer");
    let websocket_spawn = source
        .find("tokio::spawn(async move {")
        .expect("accept path must spawn the websocket task");
    assert!(
        peer_check < websocket_spawn,
        "peer authentication must precede WebSocket upgrade"
    );
}
