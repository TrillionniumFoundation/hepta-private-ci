use super::*;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;

#[tokio::test]
async fn original_owner_uid_mismatch_writes_no_protocol_bytes() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("ctl");
    let listener = UnixListener::bind(&socket)?;
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).await?;
        anyhow::Ok(bytes)
    });
    let uid = unsafe { libc::geteuid() };
    let client = SupervisordClient::new(socket)?.with_owner_uid(uid + 1);
    assert!(client.health().await.is_err());
    assert!(
        tokio::time::timeout(Duration::from_secs(2), server)
            .await???
            .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn original_owner_uid_pin_preserves_real_read_protocol() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("ctl");
    let listener = UnixListener::bind(&socket)?;
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).await?;
        let request: SupervisordRequest = serde_json::from_slice(&bytes)?;
        assert_eq!(request.method, SupervisordMethod::Health);
        let response = SupervisordResponse {
            schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            payload: SupervisordPayload::Health(SupervisordHealth {
                ready: true,
                supervisor_epoch: crate::SupervisorEpoch::parse(
                    "00000000-0000-4000-8000-000000000001",
                )
                .map_err(anyhow::Error::msg)?,
                process_id: std::process::id(),
                registered_agents: 2,
                observed_faults: 0,
            }),
        };
        let mut bytes = serde_json::to_vec(&response)?;
        bytes.push(b'\n');
        stream.write_all(&bytes).await?;
        anyhow::Ok(())
    });
    let client = SupervisordClient::new(socket)?.with_owner_uid(unsafe { libc::geteuid() });
    let health = client.health().await?;
    assert!(health.ready);
    assert_eq!(health.process_id, std::process::id());
    server.await??;
    Ok(())
}
