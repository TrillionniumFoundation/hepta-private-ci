use std::io::ErrorKind;
use std::path::PathBuf;

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

fn control_socket_path(directory: &tempfile::TempDir) -> PathBuf {
    directory
        .path()
        .canonicalize()
        .unwrap()
        .join("private")
        .join("control.ctl")
}

#[tokio::test]
async fn absent_control_socket_remains_absent_until_the_real_bind() {
    let directory = temporary_socket_directory();
    let path = control_socket_path(&directory);
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
    let path = control_socket_path(&directory);
    let _prepared = prepare_socket(&path).await.expect("prepare private parent");
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
    let path = control_socket_path(&directory);
    let _prepared = prepare_socket(&path).await.expect("prepare private parent");
    std::fs::create_dir(&path).expect("create non-socket directory");
    prepare_socket(&path)
        .await
        .expect_err("an existing directory is never an absent socket path");
    assert!(std::fs::symlink_metadata(&path).unwrap().is_dir());
    assert_eq!(std::fs::read_dir(&path).unwrap().count(), 0);
}

#[tokio::test]
async fn regular_file_at_control_socket_path_is_refused_and_retained() {
    let directory = temporary_socket_directory();
    let path = control_socket_path(&directory);
    let _prepared = prepare_socket(&path).await.expect("prepare private parent");
    std::fs::write(&path, b"retain this ordinary file").unwrap();
    prepare_socket(&path)
        .await
        .expect_err("ordinary files cannot be stale sockets");
    assert_eq!(std::fs::read(&path).unwrap(), b"retain this ordinary file");
}

#[tokio::test]
async fn closed_real_socket_can_be_removed_and_rebound() {
    let directory = temporary_socket_directory();
    let path = control_socket_path(&directory);
    let _prepared = prepare_socket(&path).await.expect("prepare private parent");
    let listener = UnixListener::bind(&path)
        .await
        .expect("bind original socket");
    drop(listener);
    assert!(std::fs::symlink_metadata(&path).is_ok());
    let _prepared = prepare_socket(&path)
        .await
        .expect("remove a real stale socket");
    assert_eq!(
        std::fs::symlink_metadata(&path).unwrap_err().kind(),
        ErrorKind::NotFound
    );
    let _listener = UnixListener::bind(&path)
        .await
        .expect("rebind the cleared path");
    let _stream = UnixStream::connect(&path)
        .await
        .expect("replacement socket works");
}

#[cfg(windows)]
#[tokio::test]
async fn retained_bound_socket_prevents_replacement_and_cleans_the_same_object() {
    let directory = temporary_socket_directory();
    let path = control_socket_path(&directory);
    let prepared = prepare_socket(&path).await.expect("prepare private parent");
    let listener = UnixListener::bind(&path)
        .await
        .expect("bind actual AF_UNIX object");
    let socket = prepared
        .open_socket("control.ctl")
        .unwrap()
        .expect("retain actual AF_UNIX object");
    assert!(std::fs::rename(&path, path.with_file_name("replaced.ctl")).is_err());
    let error = prepare_socket(&path).await.unwrap_err();
    assert!(matches!(error, AgentdError::Io(error) if error.kind() == ErrorKind::AddrInUse));
    let stream = UnixStream::connect(&path)
        .await
        .expect("retained socket is reachable");
    drop(stream);
    drop(listener);
    socket
        .remove()
        .expect("remove only the owned socket handle");
    assert_eq!(
        std::fs::symlink_metadata(&path).unwrap_err().kind(),
        ErrorKind::NotFound
    );
}
