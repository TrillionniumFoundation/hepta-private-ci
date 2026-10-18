use std::os::unix::fs::MetadataExt;

use tokio::io::AsyncReadExt;

use super::*;

#[tokio::test]
async fn pinned_app_server_wrong_uid_or_pid_writes_no_handshake() -> IoResult<()> {
    let uid = std::fs::metadata("/proc/self")?.uid();
    assert_ne!(uid, 0, "ordinary client fixture requires a non-root user");
    let pid = std::process::id();
    for (expected_uid, expected_pid) in [(uid + 1, pid), (uid, pid + 1)] {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("peer.sock");
        let mut listener = codex_uds::UnixListener::bind(&path).await?;
        let args = RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::UnixSocket {
                socket_path: AbsolutePathBuf::from_absolute_path(&path)?,
            },
            client_name: "physical-peer-fixture".into(),
            client_version: "1".into(),
            experimental_api: false,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: 8,
        };
        let client = RemoteAppServerClient::connect_with_bounded_events_for_peer(
            args,
            8,
            expected_uid,
            expected_pid,
        );
        let read = async {
            let mut peer = listener.accept().await?;
            let mut bytes = Vec::new();
            let count = timeout(Duration::from_secs(1), peer.read_to_end(&mut bytes)).await??;
            assert_eq!(count, 0, "peer rejection precedes the WebSocket handshake");
            assert!(bytes.is_empty());
            IoResult::Ok(())
        };
        let (result, observed) = tokio::join!(client, read);
        assert!(result.is_err(), "wrong kernel tuple was accepted");
        observed?;
    }
    Ok(())
}
