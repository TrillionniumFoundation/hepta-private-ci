use std::io::ErrorKind;

use codex_uds::UnixListener;
use codex_uds::UnixStream;
use pretty_assertions::assert_eq;

use super::prepare_socket;
use crate::AgentdError;

fn temporary_socket_directory() -> tempfile::TempDir {
    #[cfg(target_os = "macos")]
    let directory = tempfile::Builder::new().tempdir_in("/tmp");
    #[cfg(not(target_os = "macos"))]
    let directory = tempfile::tempdir();
    directory.expect("create socket fixture directory")
}

#[tokio::test]
async fn absent_control_socket_remains_absent_until_the_real_bind() {
    let directory = temporary_socket_directory();
    let path = directory.path().canonicalize().unwrap().join("control.ctl");
    prepare_socket(&path)
        .await
        .expect("an absent path is available even if the probe reports connection refusal");
    assert_eq!(
        std::fs::symlink_metadata(&path).unwrap_err().kind(),
        ErrorKind::NotFound
    );
    let _listener = UnixListener::bind(&path).await.expect("bind real endpoint");
    let _stream = UnixStream::connect(&path)
        .await
        .expect("new endpoint is reachable");
}

#[tokio::test]
async fn live_control_socket_is_refused_and_remains_reachable() {
    let directory = temporary_socket_directory();
    let path = directory.path().canonicalize().unwrap().join("control.ctl");
    let _listener = UnixListener::bind(&path).await.expect("bind live endpoint");
    let error = prepare_socket(&path).await.unwrap_err();
    assert!(matches!(error, AgentdError::Io(error) if error.kind() == ErrorKind::AddrInUse));
    let _stream = UnixStream::connect(&path)
        .await
        .expect("refusal must preserve the existing endpoint");
}

#[tokio::test]
async fn directory_at_control_socket_path_is_refused_and_retained() {
    let directory = temporary_socket_directory();
    let path = directory.path().canonicalize().unwrap().join("control.ctl");
    std::fs::create_dir(&path).expect("create non-socket directory");
    prepare_socket(&path)
        .await
        .expect_err("an existing directory is never an absent socket path");
    assert!(std::fs::symlink_metadata(&path).unwrap().is_dir());
    assert_eq!(std::fs::read_dir(&path).unwrap().count(), 0);
}
