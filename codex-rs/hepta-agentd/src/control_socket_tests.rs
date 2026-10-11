use super::*;

#[tokio::test]
async fn missing_control_socket_can_bind_without_replacing_a_live_listener() -> anyhow::Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("control.sock");
    prepare_socket(&path).await?;
    let listener = UnixListener::bind(&path).await?;
    assert!(matches!(
        prepare_socket(&path).await,
        Err(AgentdError::Io(error)) if error.kind() == ErrorKind::AddrInUse
    ));
    drop(listener);
    Ok(())
}
