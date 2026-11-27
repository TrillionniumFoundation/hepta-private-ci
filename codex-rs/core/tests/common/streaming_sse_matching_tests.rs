use super::MatchingStreamingSseResponse;
use super::StreamingSseChunk;
use super::StreamingSseResponse;
use super::start_matching_streaming_sse_server;
use anyhow::Context;
use anyhow::Result;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;
use tokio::sync::oneshot;
use tokio::time::Duration;
use tokio::time::timeout;
use wiremock::Match;

fn response(
    matcher: impl Match + 'static,
    body: &str,
    header_gate: Option<oneshot::Receiver<()>>,
) -> MatchingStreamingSseResponse {
    MatchingStreamingSseResponse {
        matcher: Box::new(matcher),
        response: StreamingSseResponse {
            header_gate,
            chunks: vec![StreamingSseChunk {
                gate: None,
                body: body.to_string(),
            }],
        },
    }
}

fn parent(request: &wiremock::Request) -> bool {
    request
        .body_json::<Value>()
        .is_ok_and(|body| body["role"] == "parent")
}

fn guardian(request: &wiremock::Request) -> bool {
    request
        .body_json::<Value>()
        .is_ok_and(|body| body["role"] == "guardian")
}

async fn post(uri: &str, body: &[u8], content_encoding: Option<&str>) -> Result<(u16, String)> {
    timeout(Duration::from_secs(/*secs*/ 5), async {
        let addr = uri.strip_prefix("http://").context("HTTP fixture URI")?;
        let mut stream = TcpStream::connect(addr).await?;
        let encoding = content_encoding
            .map(|encoding| format!("Content-Encoding: {encoding}\r\n"))
            .unwrap_or_default();
        let headers = format!(
            "POST /v1/responses HTTP/1.1\r\nHost: {addr}\r\nContent-Length: {}\r\nConnection: close\r\n{encoding}\r\n",
            body.len()
        );
        stream.write_all(headers.as_bytes()).await?;
        stream.write_all(body).await?;
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).await?;
        let raw = String::from_utf8(bytes)?;
        let (headers, body) = raw.split_once("\r\n\r\n").context("HTTP response headers")?;
        let status = headers
            .lines()
            .next()
            .context("HTTP status line")?
            .split_ascii_whitespace()
            .nth(1)
            .context("HTTP status code")?
            .parse()?;
        Ok((status, body.to_string()))
    })
    .await
    .context("HTTP fixture response deadline")?
}

#[tokio::test]
async fn matching_responses_follow_identity_in_either_arrival_order() -> Result<()> {
    for order in [["parent", "guardian"], ["guardian", "parent"]] {
        let (server, _completions, captured) = start_matching_streaming_sse_server(vec![
            response(parent, "parent reply", /*header_gate*/ None),
            response(guardian, "guardian reply", /*header_gate*/ None),
        ])
        .await;
        for role in order {
            let body = serde_json::to_vec(&json!({"role": role, "input": []}))?;
            assert_eq!(
                post(server.uri(), &body, /*content_encoding*/ None).await?,
                (200, format!("{role} reply"))
            );
        }
        assert_eq!(
            captured
                .requests()
                .iter()
                .map(|request| request.body_json()["role"].clone())
                .collect::<Vec<_>>(),
            order.map(Value::from)
        );
        server.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn gated_parent_response_does_not_block_guardian_request() -> Result<()> {
    let (release, gate) = oneshot::channel();
    let (server, _completions, captured) = start_matching_streaming_sse_server(vec![
        response(parent, "parent reply", Some(gate)),
        response(guardian, "guardian reply", /*header_gate*/ None),
    ])
    .await;
    let uri = server.uri().to_string();
    let parent = tokio::spawn(async move {
        let body = serde_json::to_vec(&json!({"role": "parent", "input": []}))?;
        post(&uri, &body, /*content_encoding*/ None).await
    });
    timeout(
        Duration::from_secs(/*secs*/ 5),
        server.wait_for_request_count(/*count*/ 1),
    )
    .await
    .context("parent request admission deadline")?;
    let body = serde_json::to_vec(&json!({"role": "guardian", "input": []}))?;
    assert_eq!(
        post(server.uri(), &body, /*content_encoding*/ None).await?,
        (200, "guardian reply".to_string())
    );
    assert!(
        !parent.is_finished(),
        "parent completed before its gate opened"
    );
    release
        .send(())
        .map_err(|_| anyhow::anyhow!("parent gate receiver disappeared"))?;
    assert_eq!(parent.await??, (200, "parent reply".to_string()));
    assert_eq!(captured.requests().len(), 2);
    server.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn unmatched_request_does_not_consume_a_response() -> Result<()> {
    let (server, _completions, captured) = start_matching_streaming_sse_server(vec![response(
        parent,
        "parent reply",
        /*header_gate*/ None,
    )])
    .await;
    let unknown = serde_json::to_vec(&json!({"role": "unknown", "input": []}))?;
    assert_eq!(
        post(server.uri(), &unknown, /*content_encoding*/ None).await?,
        (500, "no responses queued".to_string())
    );
    let parent = serde_json::to_vec(&json!({"role": "parent", "input": []}))?;
    assert_eq!(
        post(server.uri(), &parent, /*content_encoding*/ None).await?,
        (200, "parent reply".to_string())
    );
    assert_eq!(
        captured.single_request().body_json(),
        json!({"role": "parent", "input": []})
    );
    assert_eq!(server.requests().await.len(), 2);
    server.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn matching_preserves_compressed_request_headers_and_bytes() -> Result<()> {
    let expected = json!({"role": "guardian", "input": []});
    let body = zstd::stream::encode_all(
        std::io::Cursor::new(serde_json::to_vec(&expected)?),
        /*level*/ 0,
    )?;
    let (server, _completions, captured) = start_matching_streaming_sse_server(vec![response(
        |request: &wiremock::Request| {
            request
                .headers
                .get("content-encoding")
                .is_some_and(|encoding| encoding == "zstd")
                && zstd::stream::decode_all(std::io::Cursor::new(&request.body))
                    .ok()
                    .and_then(|body| serde_json::from_slice::<Value>(&body).ok())
                    .is_some_and(|body| body["role"] == "guardian")
        },
        "guardian reply",
        /*header_gate*/ None,
    )])
    .await;
    assert_eq!(
        post(server.uri(), &body, Some("zstd")).await?,
        (200, "guardian reply".to_string())
    );
    assert_eq!(captured.single_request().body_json(), expected);
    assert_eq!(server.requests().await, vec![body]);
    server.shutdown().await;
    Ok(())
}
