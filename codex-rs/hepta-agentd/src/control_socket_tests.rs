use std::io::ErrorKind;
use std::path::PathBuf;

use codex_uds::UnixListener;
use pretty_assertions::assert_eq;

use super::prepare_socket;
use crate::AgentdError;

async fn fixture() -> (tempfile::TempDir, PathBuf) {
    let temporary = tempfile::tempdir().expect("socket fixture");
    let parent = temporary.path().join("private");
    codex_uds::prepare_private_socket_directory(&parent)
        .await
        .expect("private socket directory");
    // Production fleet identities also retain canonical Windows paths.
    let socket = std::fs::canonicalize(parent)
        .expect("canonical private directory")
        .join("control.sock");
    (temporary, socket)
}

#[tokio::test]
async fn absent_control_socket_allows_actual_listener_binding() {
    let (_temporary, socket) = fixture().await;
    assert!(!socket.exists());
    prepare_socket(&socket)
        .await
        .expect("an absent rendezvous must be available");
    assert!(!socket.exists());
    let listener = UnixListener::bind(&socket)
        .await
        .expect("bind fresh socket");
    assert!(socket.exists());
    drop(listener);
}

#[tokio::test]
async fn live_control_socket_is_refused_without_removal() {
    let (_temporary, socket) = fixture().await;
    let listener = UnixListener::bind(&socket).await.expect("bind live socket");
    let error = prepare_socket(&socket)
        .await
        .expect_err("a live listener must remain in use");
    let AgentdError::Io(error) = error else {
        panic!("unexpected live socket error: {error:?}");
    };
    assert_eq!(error.kind(), ErrorKind::AddrInUse);
    assert!(socket.exists());
    codex_uds::UnixStream::connect(&socket)
        .await
        .expect("the original listener must still accept connections");
    drop(listener);
}

#[tokio::test]
async fn closed_control_socket_is_removed_before_rebinding() {
    let (_temporary, socket) = fixture().await;
    let listener = UnixListener::bind(&socket).await.expect("bind socket");
    drop(listener);
    assert!(
        socket.exists(),
        "the fixture must retain a stale rendezvous"
    );
    prepare_socket(&socket)
        .await
        .expect("a closed socket rendezvous can be removed");
    assert!(!socket.exists());
    let listener = UnixListener::bind(&socket)
        .await
        .expect("rebind the removed stale socket");
    drop(listener);
}

#[cfg(unix)]
#[tokio::test]
async fn regular_control_path_is_refused_without_removal() {
    let (_temporary, socket) = fixture().await;
    std::fs::write(&socket, b"not a socket").expect("unrelated file");
    let error = prepare_socket(&socket)
        .await
        .expect_err("a regular file cannot be removed as a stale socket");
    let AgentdError::Io(error) = error else {
        panic!("unexpected regular-file error: {error:?}");
    };
    assert_eq!(error.kind(), ErrorKind::AlreadyExists);
    assert_eq!(
        std::fs::read(&socket).expect("retained file"),
        b"not a socket"
    );
}
