use super::prepare_socket;
use crate::AgentdError;
use codex_uds::UnixListener;
use codex_uds::UnixStream;
use std::io::ErrorKind;
use std::path::PathBuf;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

#[tokio::test]
async fn missing_control_socket_path_is_preparable_without_a_listener() -> TestResult {
    let temp = TempDir::new()?;
    let socket_path = temp.path().join("owner").join("fresh-control.ctl");
    assert!(!socket_path.exists());
    prepare_socket(&socket_path).await?;
    assert!(socket_path.parent().expect("socket parent").is_dir());
    assert!(!socket_path.exists());
    Ok(())
}

fn control_socket_test_directory() -> TestResult<TempDir> {
    // Darwin's test TMPDIR can exceed sun_path even for these short names.
    let root = if cfg!(target_os = "macos") {
        PathBuf::from("/tmp")
    } else {
        std::env::temp_dir()
    };
    Ok(tempfile::Builder::new()
        .prefix("hag-ctl-")
        .tempdir_in(root)?)
}

#[tokio::test]
async fn stale_control_socket_entry_is_removed_before_rebinding() -> TestResult {
    let temp = control_socket_test_directory()?;
    let socket_path = temp.path().join("stale.ctl");
    let listener = UnixListener::bind(&socket_path).await?;
    drop(listener);
    assert!(tokio::fs::symlink_metadata(&socket_path).await.is_ok());

    prepare_socket(&socket_path).await?;

    assert_eq!(
        tokio::fs::symlink_metadata(&socket_path)
            .await
            .expect_err("stale rendezvous must be unlinked")
            .kind(),
        ErrorKind::NotFound,
    );
    let _replacement = UnixListener::bind(&socket_path).await?;
    let _connected = UnixStream::connect(&socket_path).await?;
    Ok(())
}

#[tokio::test]
async fn live_control_socket_entry_is_preserved() -> TestResult {
    let temp = control_socket_test_directory()?;
    let socket_path = temp.path().join("live.ctl");
    let _listener = UnixListener::bind(&socket_path).await?;

    let error = prepare_socket(&socket_path)
        .await
        .expect_err("a live control socket must not be replaced");

    assert!(matches!(
        error,
        AgentdError::Io(error) if error.kind() == ErrorKind::AddrInUse
    ));
    assert!(tokio::fs::symlink_metadata(&socket_path).await.is_ok());
    let _connected = UnixStream::connect(&socket_path).await?;
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn non_socket_control_path_is_preserved() -> TestResult {
    let temp = control_socket_test_directory()?;
    let socket_path = temp.path().join("not-socket.ctl");
    tokio::fs::write(&socket_path, b"owned non-socket data").await?;

    let error = prepare_socket(&socket_path)
        .await
        .expect_err("a non-socket path must not be removed");

    assert!(matches!(
        error,
        AgentdError::Io(error) if error.kind() == ErrorKind::AlreadyExists
    ));
    assert_eq!(
        tokio::fs::read(&socket_path).await?,
        b"owned non-socket data"
    );
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn dangling_control_symlink_is_not_treated_as_a_missing_entry() -> TestResult {
    let temp = control_socket_test_directory()?;
    let socket_path = temp.path().join("dangling.ctl");
    let target = temp.path().join("absent.ctl");
    std::os::unix::fs::symlink(&target, &socket_path)?;
    assert!(!socket_path.exists());

    let error = prepare_socket(&socket_path)
        .await
        .expect_err("a dangling entry is not an absent rendezvous path");

    assert!(matches!(
        error,
        AgentdError::Io(error) if error.kind() == ErrorKind::AlreadyExists
    ));
    assert_eq!(tokio::fs::read_link(&socket_path).await?, target);
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn control_peer_check_runs_before_control_frames() -> TestResult {
    let temp = control_socket_test_directory()?;
    let socket_path = temp.path().join("peer.ctl");
    let mut listener = UnixListener::bind(&socket_path).await?;
    let client_path = socket_path.clone();
    let client_task = tokio::spawn(async move { UnixStream::connect(client_path).await });
    let server_stream = listener.accept().await?;
    super::ensure_control_peer(&server_stream)?;
    let _client_stream = client_task.await??;
    Ok(())
}

#[cfg(unix)]
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

#[cfg(unix)]
#[test]
fn retiring_control_socket_removes_only_its_original_entry() -> TestResult {
    use std::os::unix::fs::symlink;
    use std::os::unix::net::UnixListener as StdUnixListener;
    use std::os::unix::net::UnixStream as StdUnixStream;

    let temp = control_socket_test_directory()?;
    let path = temp.path().join("retire.ctl");
    let original = StdUnixListener::bind(&path)?;
    let identity = super::control_socket_identity(&path)?.expect("owned socket identity");

    super::remove_owned_control_socket(&path, identity)?;
    assert!(!path.exists());
    super::remove_owned_control_socket(&path, identity)?;

    let successor = StdUnixListener::bind(&path)?;
    super::remove_owned_control_socket(&path, identity)?;
    let _client = StdUnixStream::connect(&path)?;
    let _accepted = successor.accept()?;
    std::fs::remove_file(&path)?;

    std::fs::write(&path, b"replacement")?;
    super::remove_owned_control_socket(&path, identity)?;
    assert_eq!(std::fs::read(&path)?, b"replacement");
    std::fs::remove_file(&path)?;

    let target = temp.path().join("target");
    std::fs::write(&target, b"target")?;
    symlink(&target, &path)?;
    super::remove_owned_control_socket(&path, identity)?;
    assert_eq!(std::fs::read_link(&path)?, target);
    assert_eq!(std::fs::read(&target)?, b"target");
    drop(original);
    Ok(())
}
