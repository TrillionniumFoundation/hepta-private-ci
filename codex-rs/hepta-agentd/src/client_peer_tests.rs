use std::os::unix::fs::MetadataExt;

use tokio::io::AsyncReadExt;

use super::*;

#[tokio::test]
async fn pinned_agentd_wrong_uid_or_pid_writes_no_request_payload()
-> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let uid = std::fs::metadata("/proc/self")?.uid();
    assert!(
        uid != 0,
        "run the ordinary client fixture as a non-root user"
    );
    let pid = std::process::id();
    for (expected_uid, expected_pid) in [(uid + 1, pid), (uid, pid + 1)] {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("peer.sock");
        let mut listener = codex_uds::UnixListener::bind(&path).await?;
        let client = AgentdClient::new(
            path,
            AgentId::parse("00000000-0000-4000-8000-000000000001")?,
            1,
        )?
        .with_peer_process(expected_uid, expected_pid)?;
        let read = async {
            let mut peer = listener.accept().await?;
            let mut bytes = Vec::new();
            let count = tokio::time::timeout(Duration::from_secs(1), peer.read_to_end(&mut bytes))
                .await??;
            assert_eq!(
                (count, bytes),
                (0, Vec::new()),
                "kernel rejection leaked protocol bytes"
            );
            Ok::<_, Box<dyn std::error::Error + Send + Sync>>(())
        };
        let (result, observed) = tokio::join!(client.health(), read);
        assert!(result.is_err(), "wrong peer was accepted");
        observed?;
    }
    Ok(())
}
