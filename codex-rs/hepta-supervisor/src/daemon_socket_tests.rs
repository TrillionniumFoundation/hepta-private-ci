use std::error::Error;
use std::io::ErrorKind;

use codex_uds::UnixListener;
use codex_uds::UnixStream;
use pretty_assertions::assert_eq;

use super::SupervisorError;
use super::prepare_socket;

#[tokio::test]
async fn socket_preparation_handles_missing_stale_live_and_regular_paths()
-> Result<(), Box<dyn Error>> {
    // Keep the socket within Darwin's pathname limit under deep test TMPDIRs.
    let temp = tempfile::Builder::new()
        .prefix("hctl-")
        .tempdir_in("/tmp")?;
    let socket = temp.path().join("control.sock");

    prepare_socket(&socket).await?;
    let listener = UnixListener::bind(&socket).await?;
    assert!(matches!(
        prepare_socket(&socket).await,
        Err(SupervisorError::Io(error)) if error.kind() == ErrorKind::AddrInUse
    ));
    drop(UnixStream::connect(&socket).await?);

    drop(listener);
    assert!(tokio::fs::symlink_metadata(&socket).await.is_ok());
    prepare_socket(&socket).await?;
    let replacement = UnixListener::bind(&socket).await?;
    drop(replacement);

    let regular = temp.path().join("owner-state");
    tokio::fs::write(&regular, b"preserve owner state").await?;
    assert!(prepare_socket(&regular).await.is_err());
    assert_eq!(tokio::fs::read(&regular).await?, b"preserve owner state");

    // A nonexistent path must not hide an unrelated socket probe error.
    let oversized = temp.path().join("s".repeat(128));
    assert!(matches!(
        prepare_socket(&oversized).await,
        Err(SupervisorError::Io(error)) if error.kind() == ErrorKind::InvalidInput
    ));
    Ok(())
}
