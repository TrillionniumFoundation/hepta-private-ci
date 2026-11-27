use std::error::Error;
use std::io::ErrorKind;

use codex_uds::UnixListener;
use codex_uds::UnixStream;

use super::AgentdError;
use super::prepare_socket;

type TestResult = Result<(), Box<dyn Error>>;

#[tokio::test]
async fn absent_endpoint_is_left_absent_until_the_listener_binds() -> TestResult {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("control");
    prepare_socket(&path).await?;
    assert!(matches!(
        std::fs::symlink_metadata(&path),
        Err(error) if error.kind() == ErrorKind::NotFound
    ));
    let _listener = UnixListener::bind(&path).await?;
    let _client = UnixStream::connect(&path).await?;
    Ok(())
}

#[tokio::test]
async fn a_live_listener_remains_live_and_cannot_be_replaced() -> TestResult {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("control");
    let _listener = UnixListener::bind(&path).await?;
    assert!(matches!(
        prepare_socket(&path).await,
        Err(AgentdError::Io(error)) if error.kind() == ErrorKind::AddrInUse
    ));
    let _client = UnixStream::connect(&path).await?;
    Ok(())
}

#[tokio::test]
async fn an_ordinary_file_is_rejected_and_its_bytes_are_preserved() -> TestResult {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("control");
    let bytes = b"this is not a socket";
    std::fs::write(&path, bytes)?;
    assert!(prepare_socket(&path).await.is_err());
    assert_eq!(std::fs::read(&path)?, bytes);
    Ok(())
}
