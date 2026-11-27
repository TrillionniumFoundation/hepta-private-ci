use super::StreamingSseRoute;
use super::start_routed_streaming_sse_server;
use crate::responses::ResponsesRequest;
use crate::streaming_sse::StreamingSseChunk;
use crate::streaming_sse::StreamingSseServer;
use anyhow::Context;
use anyhow::Result;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;
use tokio::sync::oneshot;
use tokio::time::timeout;

fn route(name: &'static str, chunks: Vec<StreamingSseChunk>) -> StreamingSseRoute {
    StreamingSseRoute {
        matcher: Arc::new(move |request: &wiremock::Request| {
            request
                .headers
                .get("x-fixture-route")
                .and_then(|value| value.to_str().ok())
                == Some(name)
        }),
        responses: vec![chunks],
    }
}

async fn post(server: &StreamingSseServer, route: &str, compressed: bool) -> Result<TcpStream> {
    let address = server
        .uri()
        .strip_prefix("http://")
        .context("HTTP fixture")?;
    let mut stream = TcpStream::connect(address).await?;
    let body = serde_json::to_vec(&json!({"input": [], "route": route}))?;
    let (body, encoding) = if compressed {
        (
            zstd::stream::encode_all(body.as_slice(), /*level*/ 0)?,
            "Content-Encoding: zstd\r\n",
        )
    } else {
        (body, "")
    };
    let headers = format!(
        "POST /v1/responses HTTP/1.1\r\nHost: {address}\r\nX-Fixture-Route: {route}\r\n{encoding}Content-Length: {}\r\n\r\n",
        body.len()
    );
    stream.write_all(headers.as_bytes()).await?;
    stream.write_all(&body).await?;
    Ok(stream)
}

async fn headers(stream: &mut TcpStream) -> Result<u16> {
    let mut bytes = Vec::new();
    while !bytes.ends_with(b"\r\n\r\n") {
        let mut byte = [0u8; 1];
        stream.read_exact(&mut byte).await?;
        bytes.extend_from_slice(&byte);
    }
    let text = String::from_utf8(bytes)?;
    Ok(text
        .split_whitespace()
        .nth(/*n*/ 1)
        .context("HTTP status")?
        .parse()?)
}

async fn body(mut stream: TcpStream) -> Result<String> {
    let mut bytes = Vec::new();
    stream.read_to_end(&mut bytes).await?;
    Ok(String::from_utf8(bytes)?)
}

async fn response(mut stream: TcpStream) -> Result<(u16, String)> {
    Ok((headers(&mut stream).await?, body(stream).await?))
}

#[tokio::test]
async fn gated_parent_does_not_block_compressed_guardian_or_captured_json() -> Result<()> {
    let (release, gate) = oneshot::channel();
    let (server, recorded) = start_routed_streaming_sse_server(vec![
        route(
            "parent",
            vec![StreamingSseChunk {
                gate: Some(gate),
                body: "parent final".to_string(),
            }],
        ),
        route(
            "guardian",
            vec![StreamingSseChunk {
                gate: None,
                body: "guardian allow".to_string(),
            }],
        ),
    ])
    .await;
    let mut parent = post(&server, "parent", /*compressed*/ false).await?;
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), headers(&mut parent)).await??,
        200
    );
    let guardian = post(&server, "guardian", /*compressed*/ true).await?;
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), response(guardian)).await??,
        (200, "guardian allow".to_string())
    );
    let parent_response = body(parent);
    tokio::pin!(parent_response);
    assert!(
        timeout(Duration::from_millis(/*millis*/ 200), &mut parent_response)
            .await
            .is_err()
    );
    assert_eq!(
        recorded
            .requests()
            .iter()
            .map(ResponsesRequest::body_json)
            .collect::<Vec<_>>(),
        vec![
            json!({"input": [], "route": "parent"}),
            json!({"input": [], "route": "guardian"})
        ]
    );
    assert!(release.send(()).is_ok());
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), parent_response).await??,
        "parent final"
    );
    server.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn unknown_exhausted_and_dropped_gates_do_not_release_another_route() -> Result<()> {
    let (release, gate) = oneshot::channel();
    let (server, recorded) = start_routed_streaming_sse_server(vec![
        route(
            "parent",
            vec![StreamingSseChunk {
                gate: Some(gate),
                body: "must remain gated".to_string(),
            }],
        ),
        route(
            "guardian",
            vec![StreamingSseChunk {
                gate: None,
                body: "guardian allow".to_string(),
            }],
        ),
    ])
    .await;
    let unknown = post(&server, "unknown", /*compressed*/ false).await?;
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), response(unknown)).await??,
        (500, "no responses queued".to_string())
    );
    let mut parent = post(&server, "parent", /*compressed*/ false).await?;
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), headers(&mut parent)).await??,
        200
    );
    let exhausted = post(&server, "parent", /*compressed*/ false).await?;
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), response(exhausted)).await??,
        (500, "no responses queued".to_string())
    );
    let guardian = post(&server, "guardian", /*compressed*/ false).await?;
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), response(guardian)).await??,
        (200, "guardian allow".to_string())
    );
    drop(release);
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), body(parent)).await??,
        String::new()
    );
    assert_eq!(recorded.requests().len(), 4);
    server.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn routed_server_shutdown_drops_a_gate_without_sending_its_body() -> Result<()> {
    let (release, gate) = oneshot::channel();
    let (server, _) = start_routed_streaming_sse_server(vec![route(
        "parent",
        vec![StreamingSseChunk {
            gate: Some(gate),
            body: "must remain gated".to_string(),
        }],
    )])
    .await;
    let mut parent = post(&server, "parent", /*compressed*/ false).await?;
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 5), headers(&mut parent)).await??,
        200
    );
    server.shutdown().await;
    assert!(
        release.send(()).is_err(),
        "shutdown must drop the gated connection"
    );
    let mut bytes = Vec::new();
    timeout(
        Duration::from_secs(/*secs*/ 5),
        parent.read_to_end(&mut bytes),
    )
    .await??;
    assert!(!String::from_utf8(bytes)?.contains("must remain gated"));
    Ok(())
}
