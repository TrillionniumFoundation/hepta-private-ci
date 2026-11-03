use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use pretty_assertions::assert_eq;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio::time::timeout;

use super::super::ModelEvent;
use super::super::ModelRequest;
use super::super::ResponsesModel;

struct FixtureEntryGuard(Arc<AtomicBool>);

impl Drop for FixtureEntryGuard {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

#[tokio::test]
async fn denied_concrete_entry_opens_no_http_connection() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}/v1/responses", listener.local_addr()?);
    let model = ResponsesModel::new(
        &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
        url.clone(),
        /*bearer*/ None,
        Duration::from_secs(2),
        /*max_stream_bytes*/ 4096,
    )?;
    let request = ModelRequest {
        operation_id: "operation:denied-at-entry".to_string(),
        body: br#"{"model":"fixture","stream":true}"#.to_vec(),
    };
    let result = model
        .open_with_entry(&request, |endpoint, actual| -> Result<()> {
            assert_eq!(
                (endpoint, actual.operation_id.as_str(), actual.body.as_slice()),
                (url.as_str(), request.operation_id.as_str(), request.body.as_slice())
            );
            bail!("fixture final entry rejected")
        })
        .await;
    assert!(result.is_err());
    assert!(timeout(Duration::from_millis(100), listener.accept()).await.is_err());
    Ok(())
}

#[tokio::test]
async fn exact_request_is_sent_once_with_guard_held_until_response_headers() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}/v1/responses", listener.local_addr()?);
    let (observed_tx, observed_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut bytes = Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") {
            ensure!(bytes.len() < 8192, "fixture header limit");
            bytes.push(socket.read_u8().await?);
        }
        let headers = String::from_utf8(bytes)?;
        let length = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>())
            })
            .context("content length")??;
        ensure!(length < 4096, "fixture body limit");
        let mut body = vec![0; length];
        socket.read_exact(&mut body).await?;
        observed_tx
            .send((headers, body))
            .map_err(|_| anyhow::anyhow!("fixture observer dropped"))?;
        release_rx.await?;
        let events = [
            json!({"type":"response.created", "response":{"id":"response:original"}}),
            json!({"type":"response.completed", "response":{
                "id":"response:original", "status":"completed",
                "usage":{"input_tokens":1,"output_tokens":1}
            }}),
        ]
        .into_iter()
        .map(|event| format!("data: {event}\n\n"))
        .collect::<String>();
        let wire = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{events}",
            events.len()
        );
        socket.write_all(wire.as_bytes()).await?;
        socket.shutdown().await?;
        ensure!(
            timeout(Duration::from_millis(100), listener.accept()).await.is_err(),
            "a second HTTP connection would be a retry"
        );
        Ok::<_, anyhow::Error>(())
    });
    let model = ResponsesModel::new(
        &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
        url.clone(),
        /*bearer*/ None,
        Duration::from_secs(3),
        /*max_stream_bytes*/ 4096,
    )?;
    let exact_body = br#"{"model":"fixture", "stream":true}"#.to_vec();
    let request = ModelRequest {
        operation_id: "operation:original".to_string(),
        body: exact_body.clone(),
    };
    let guard_live = Arc::new(AtomicBool::new(false));
    let callback_live = Arc::clone(&guard_live);
    let opened = tokio::spawn(async move {
        model
            .open_with_entry(&request, move |endpoint, actual| {
                ensure!(endpoint == url, "wrong physical endpoint");
                ensure!(actual.operation_id == "operation:original", "wrong operation");
                callback_live.store(true, Ordering::SeqCst);
                Ok(FixtureEntryGuard(callback_live))
            })
            .await
    });
    let (headers, body) = timeout(Duration::from_secs(3), observed_rx).await??;
    assert!(guard_live.load(Ordering::SeqCst));
    assert!(headers.starts_with("POST /v1/responses HTTP/1.1\r\n"));
    assert!(headers.to_ascii_lowercase().contains("idempotency-key: operation:original\r\n"));
    assert_eq!(body, exact_body);
    release_tx.send(()).map_err(|_| anyhow::anyhow!("fixture release dropped"))?;
    let mut stream = timeout(Duration::from_secs(3), opened).await???;
    assert!(!guard_live.load(Ordering::SeqCst));
    assert_eq!(
        stream.next().await?,
        Some(ModelEvent::Created("response:original".to_string()))
    );
    assert_eq!(
        stream.next().await?,
        Some(ModelEvent::Completed {
            response_id: "response:original".to_string(),
            usage: json!({"input_tokens":1,"output_tokens":1}),
        })
    );
    assert_eq!(stream.next().await?, None);
    timeout(Duration::from_secs(3), peer).await???;
    Ok(())
}
