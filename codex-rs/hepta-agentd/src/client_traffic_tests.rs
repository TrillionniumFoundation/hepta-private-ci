use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_uds::UnixListener;
use pretty_assertions::assert_eq;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::sync::Notify;

use super::AgentdClient;

#[tokio::test]
async fn traffic_counts_observed_partial_response_bytes_on_protocol_failure() {
    let directory = tempfile::tempdir().expect("socket directory");
    let path = directory.path().join("traffic.sock");
    let mut listener = UnixListener::bind(&path).await.expect("listener");
    let partial = b"{\"schema_version\":1";
    let server = tokio::spawn(async move {
        let stream = listener.accept().await.expect("accept");
        let (reader, mut writer) = tokio::io::split(stream);
        let mut frame = Vec::new();
        BufReader::new(reader).read_until(b'\n', &mut frame).await.expect("request bytes");
        writer.write_all(partial).await.expect("partial response");
        writer.shutdown().await.expect("close partial frame");
        frame.len()
    });
    let client = AgentdClient::new(path, AgentId::parse("00000000-0000-4000-8000-000000000099").expect("agent"), /*spawn_generation*/ 1).expect("client");
    assert!(client.health().await.is_err());
    let request_bytes = server.await.expect("server join");
    let counts = client.traffic_snapshot();
    assert_eq!((counts.rpc_attempts, counts.transmitted_bytes, counts.received_bytes), (1, request_bytes as u64, partial.len() as u64));
}

#[tokio::test]
async fn cancelling_a_real_pending_socket_read_preserves_its_already_observed_bytes() {
    let directory = tempfile::tempdir().expect("socket directory");
    let path = directory.path().join("cancel-traffic.sock");
    let mut listener = UnixListener::bind(&path).await.expect("listener");
    let release = Arc::new(Notify::new());
    let server_release = Arc::clone(&release);
    let partial = b"{\"schema_version\":";
    let server = tokio::spawn(async move {
        let stream = listener.accept().await.expect("accept");
        let (reader, mut writer) = tokio::io::split(stream);
        let mut frame = Vec::new();
        BufReader::new(reader).read_until(b'\n', &mut frame).await.expect("request bytes");
        writer.write_all(partial).await.expect("partial response");
        server_release.notified().await;
        frame.len()
    });
    let client = Arc::new(AgentdClient::new(path, AgentId::parse("00000000-0000-4000-8000-000000000099").expect("agent"), /*spawn_generation*/ 1).expect("client"));
    let read = { let client = Arc::clone(&client); tokio::spawn(async move { client.health().await }) };
    tokio::time::timeout(Duration::from_secs(5), async {
        while client.traffic_snapshot().received_bytes < partial.len() as u64 { tokio::task::yield_now().await; }
    }).await.expect("partial bytes reached the actual client");
    read.abort();
    assert!(read.await.expect_err("cancelled reader").is_cancelled());
    release.notify_one();
    let transmitted = server.await.expect("server join");
    let counts = client.traffic_snapshot();
    assert_eq!((counts.rpc_attempts, counts.transmitted_bytes, counts.received_bytes), (1, transmitted as u64, partial.len() as u64));
}
