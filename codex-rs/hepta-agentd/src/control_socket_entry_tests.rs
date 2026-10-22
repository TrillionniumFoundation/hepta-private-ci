use super::*;

#[cfg(unix)]
use std::os::unix::fs::symlink as symlink_file;
#[cfg(windows)]
use std::os::windows::fs::symlink_file;

#[tokio::test]
async fn absent_socket_entry_can_be_prepared_and_bound() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agent.ctl");
    prepare_socket(&socket).await?;
    let _listener = UnixListener::bind(socket).await?;
    Ok(())
}

#[tokio::test]
async fn closed_socket_entry_is_removed_before_rebinding() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agent.ctl");
    let listener = UnixListener::bind(&socket).await?;
    drop(listener);
    prepare_socket(&socket).await?;
    let _rebound = UnixListener::bind(socket).await?;
    Ok(())
}

#[tokio::test]
async fn live_socket_entry_is_never_replaced() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agent.ctl");
    let _listener = UnixListener::bind(&socket).await?;
    assert!(matches!(
        prepare_socket(&socket).await,
        Err(AgentdError::Io(error)) if error.kind() == ErrorKind::AddrInUse
    ));
    assert!(tokio::fs::symlink_metadata(socket).await.is_ok());
    Ok(())
}

#[tokio::test]
async fn ordinary_file_entry_is_never_removed() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agent.ctl");
    std::fs::write(&socket, b"not a socket")?;
    assert!(prepare_socket(&socket).await.is_err());
    assert_eq!(std::fs::read(socket)?, b"not a socket");
    Ok(())
}

#[tokio::test]
async fn dangling_symlink_entry_is_never_removed() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agent.ctl");
    symlink_file(directory.path().join("absent"), &socket)?;
    assert!(prepare_socket(&socket).await.is_err());
    assert!(std::fs::symlink_metadata(socket)?.file_type().is_symlink());
    Ok(())
}
