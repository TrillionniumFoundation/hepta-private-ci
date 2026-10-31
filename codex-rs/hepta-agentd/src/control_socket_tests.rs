use super::*;

use pretty_assertions::assert_eq;

#[tokio::test]
async fn absent_live_and_stale_socket_entries_remain_distinct()
-> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    #[cfg(unix)]
    let temp = tempfile::Builder::new().prefix("hac-").tempdir_in("/tmp")?;
    #[cfg(not(unix))]
    let temp = tempfile::tempdir()?;
    let socket = temp.path().join("control");

    prepare_socket(&socket).await?;
    let listener = UnixListener::bind(&socket).await?;
    let live = prepare_socket(&socket).await;
    assert!(matches!(live, Err(AgentdError::Io(error)) if error.kind() == ErrorKind::AddrInUse));
    assert!(tokio::fs::symlink_metadata(&socket).await.is_ok());
    drop(listener);

    prepare_socket(&socket).await?;
    assert_eq!(
        tokio::fs::symlink_metadata(&socket)
            .await
            .err()
            .map(|error| error.kind()),
        Some(ErrorKind::NotFound),
    );
    let rebound = UnixListener::bind(&socket).await?;
    drop(rebound);
    tokio::fs::remove_file(&socket).await?;
    Ok(())
}
