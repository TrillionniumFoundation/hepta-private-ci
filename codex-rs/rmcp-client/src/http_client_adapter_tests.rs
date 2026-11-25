use std::collections::HashMap;
use std::io::ErrorKind;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_exec_server::HttpRedirectPolicy;
use codex_exec_server::RouteAwareHttpClient;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use http::HeaderMap;
use http::HeaderValue;
use http::header::AUTHORIZATION;
use pretty_assertions::assert_eq;
use rmcp::transport::streamable_http_client::StreamableHttpClient;
use rmcp::transport::streamable_http_client::StreamableHttpError;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio::task::JoinSet;
use tokio::time::timeout;

use super::HttpHeader;
use super::SseEventSizeLimit;
use super::StreamableHttpClientAdapter;
use super::StreamableHttpRedirectMode;
use super::mcp_redirect_policy;
use super::protocol_headers;

#[tokio::test]
async fn delete_session_uses_status_before_an_unfinished_response_body() -> anyhow::Result<()> {
    for status in [200, 405, 500] {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let address = listener.local_addr()?;
        let (headers_sent, headers_received) = oneshot::channel();
        let (release_body, body_released) = oneshot::channel();
        // JoinSet aborts its owned task on every early-return or panic path.
        let mut server = JoinSet::new();
        server.spawn(async move {
            let (mut socket, _) = listener.accept().await?;
            let mut request = Vec::new();
            let mut chunk = [0_u8; 1024];
            while !request.ends_with(b"\r\n\r\n") {
                let count = socket.read(&mut chunk).await?;
                anyhow::ensure!(count > 0, "DELETE request ended before its headers");
                anyhow::ensure!(request.len() + count <= 16 * 1024, "request headers too large");
                request.extend_from_slice(&chunk[..count]);
            }
            let request = String::from_utf8(request)?;
            anyhow::ensure!(request.starts_with("DELETE /mcp HTTP/1.1\r\n"));
            let headers: HashMap<_, _> = request
                .split("\r\n")
                .filter_map(|line| line.split_once(':'))
                .map(|(name, value)| (name.to_ascii_lowercase(), value.trim().to_string()))
                .collect();
            anyhow::ensure!(headers.get("authorization").map(String::as_str) == Some("Bearer delete-token"));
            anyhow::ensure!(headers.get("mcp-session-id").map(String::as_str) == Some("delete-session"));
            anyhow::ensure!(headers.get("x-delete-control").map(String::as_str) == Some("present"));
            socket
                .write_all(
                    format!("HTTP/1.1 {status} Control\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                        .as_bytes(),
                )
                .await?;
            socket.flush().await?;
            let _ = headers_sent.send(());
            // No terminating chunk or EOF is sent before the operation has
            // returned or reached its test-only deadline.
            let _ = body_released.await;
            anyhow::Ok(())
        });
        let adapter = StreamableHttpClientAdapter::new(
            Arc::new(RouteAwareHttpClient::new(HttpClientFactory::new(
                OutboundProxyPolicy::ReqwestDefault,
            ))),
            HeaderMap::new(),
            /*auth_provider*/ None,
            /*has_configured_headers*/ false,
            StreamableHttpRedirectMode::AgentPluginV1,
            Arc::new(Mutex::new(None)),
        );
        let operation = adapter.delete_session(
            format!("http://{address}/mcp").into(),
            "delete-session".into(),
            Some("delete-token".to_string()),
            HashMap::from([(
                http::HeaderName::from_static("x-delete-control"),
                HeaderValue::from_static("present"),
            )]),
        );
        let (headers_result, operation_result) = tokio::join!(
            timeout(Duration::from_secs(2), headers_received),
            timeout(Duration::from_secs(2), operation),
        );
        // Release and join the real socket owner before asserting either
        // outcome, including the original buffered implementation's timeout.
        let _ = release_body.send(());
        let joined = timeout(Duration::from_secs(1), server.join_next()).await;
        let cleanup = timeout(Duration::from_secs(1), server.shutdown()).await;
        cleanup.expect("owned DELETE control server must terminate");
        joined
            .expect("DELETE control server must join")
            .expect("one owned DELETE control task")??;
        headers_result
            .expect("real HTTP headers must arrive within the control deadline")
            .expect("real HTTP server must send response headers");
        let result = operation_result
            .expect("DELETE must finish without waiting for its unused response body");
        if status == 500 {
            assert!(
                matches!(result, Err(StreamableHttpError::UnexpectedServerResponse(ref message))
                    if message.as_ref() == "DELETE returned HTTP 500"),
                "unexpected DELETE failure: {result:?}"
            );
        } else {
            result?;
        }
    }
    Ok(())
}

#[test]
fn protocol_headers_preserve_utf8_values() {
    let mut headers = HeaderMap::new();
    headers.insert(
        "x-plugin-name",
        HeaderValue::from_str("café").expect("valid HTTP field value"),
    );

    assert_eq!(
        protocol_headers(&headers),
        vec![HttpHeader {
            name: "x-plugin-name".to_string(),
            value: "café".to_string(),
            value_env_var: None,
        }]
    );
}

#[test]
fn legacy_configured_headers_follow_redirects() {
    assert_eq!(
        mcp_redirect_policy(
            StreamableHttpRedirectMode::Legacy,
            &HeaderMap::new(),
            /*has_configured_headers*/ true,
        ),
        HttpRedirectPolicy::Follow
    );
}

#[test]
fn agent_plugin_configured_headers_stop_redirects() {
    assert_eq!(
        mcp_redirect_policy(
            StreamableHttpRedirectMode::AgentPluginV1,
            &HeaderMap::new(),
            /*has_configured_headers*/ true,
        ),
        HttpRedirectPolicy::Stop
    );
}

#[test]
fn requests_without_sensitive_headers_follow_redirects() {
    assert_eq!(
        mcp_redirect_policy(
            StreamableHttpRedirectMode::AgentPluginV1,
            &HeaderMap::new(),
            /*has_configured_headers*/ false,
        ),
        HttpRedirectPolicy::Follow
    );
}

#[test]
fn authorization_redirects_depend_on_mode() {
    let mut headers = HeaderMap::new();
    headers.insert(AUTHORIZATION, HeaderValue::from_static("Bearer secret"));
    assert_eq!(
        mcp_redirect_policy(
            StreamableHttpRedirectMode::Legacy,
            &headers,
            /*has_configured_headers*/ false,
        ),
        HttpRedirectPolicy::Follow
    );
    assert_eq!(
        mcp_redirect_policy(
            StreamableHttpRedirectMode::AgentPluginV1,
            &headers,
            /*has_configured_headers*/ false,
        ),
        HttpRedirectPolicy::Stop
    );
}

#[test]
fn lf_terminators_reset_the_event_limit() {
    let mut limit = SseEventSizeLimit::new(8);

    limit
        .observe(b"data: a\n\ndata: b\n\n")
        .expect("LF-terminated events must have independent size limits");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn carriage_return_terminators_reset_the_event_limit() {
    let mut limit = SseEventSizeLimit::new(8);

    limit
        .observe(b"data: a\r\rdata: b\r\r")
        .expect("CR-terminated events must have independent size limits");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn crlf_terminators_split_across_chunks_reset_the_event_limit() {
    let mut limit = SseEventSizeLimit::new(8);

    limit
        .observe(b"data: a\r")
        .expect("a CR must finish the first event field");
    limit
        .observe(b"\n\r")
        .expect("a split CRLF must not finish another field");
    limit
        .observe(b"\ndata: b\r")
        .expect("the blank CRLF must reset the first event");
    limit
        .observe(b"\n\r\n")
        .expect("the second split CRLF event must remain within the limit");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn event_at_the_exact_size_limit_is_accepted() {
    let mut limit = SseEventSizeLimit::new(9);

    limit
        .observe(b"data: ab\n\n")
        .expect("an event at the exact limit must be accepted");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn completed_keepalive_comments_do_not_accumulate() {
    let mut limit = SseEventSizeLimit::new(6);

    limit
        .observe(&b": ping\n".repeat(/*n*/ 64))
        .expect("completed keepalive comments must not accumulate");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn split_keepalive_comments_are_discarded_only_when_complete() {
    let mut limit = SseEventSizeLimit::new(6);

    limit
        .observe(b": pi")
        .expect("an incomplete comment within the limit must be retained");
    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 4));

    limit
        .observe(b"ng\n: ping\n")
        .expect("only completed comments may be excluded from the limit");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn comments_do_not_reset_accumulated_event_data() {
    let mut limit = SseEventSizeLimit::new(14);

    limit
        .observe(b"data: a\n")
        .expect("the first data field must fit");
    limit
        .observe(b": ping\n")
        .expect("a completed comment must not count as event data");

    let error = limit
        .observe(b"data: b\n")
        .expect_err("a comment must not reset previously retained data");

    assert_eq!(
        (error.kind(), error.to_string()),
        (
            ErrorKind::InvalidData,
            "MCP response body exceeds 14 bytes".to_string(),
        )
    );
}

#[test]
fn an_unterminated_comment_remains_size_limited() {
    let mut limit = SseEventSizeLimit::new(6);

    limit
        .observe(b": ping")
        .expect("a comment at the exact limit must be accepted");

    let error = limit
        .observe(b"!")
        .expect_err("an unterminated comment must not bypass the limit");

    assert_eq!(
        (error.kind(), error.to_string()),
        (
            ErrorKind::InvalidData,
            "MCP response body exceeds 6 bytes".to_string(),
        )
    );
}

#[test]
fn multiline_data_counts_parser_inserted_newlines() {
    let mut limit = SseEventSizeLimit::new(18);

    let error = limit
        .observe(b"data: aaa\ndata: bbb\n\n")
        .expect_err("joined multiline event data must remain size limited");

    assert_eq!(
        (error.kind(), error.to_string()),
        (
            ErrorKind::InvalidData,
            "MCP response body exceeds 18 bytes".to_string(),
        )
    );
}

#[test]
fn completed_events_can_exceed_one_event_budget() {
    let mut limit = SseEventSizeLimit::new(8);

    limit
        .observe(&b"data: a\n\n".repeat(/*n*/ 64))
        .expect("a long stream of bounded events must remain usable");

    assert_eq!(
        (
            limit.retained_bytes,
            limit.line_bytes,
            limit.line_is_comment,
            limit.previous_was_carriage_return,
            limit.failed,
        ),
        (0, 0, false, false, false)
    );
}

#[test]
fn zero_event_limit_rejects_nonempty_data() {
    let mut limit = SseEventSizeLimit::new(0);

    let error = limit
        .observe(b"d")
        .expect_err("an explicit zero limit must not disable the bound");

    assert_eq!((error.kind(), limit.failed), (ErrorKind::InvalidData, true));
}

#[test]
fn rejected_events_remain_rejected() {
    let mut limit = SseEventSizeLimit::new(8);

    limit
        .observe(b"data: abc")
        .expect_err("an oversized event must be rejected");

    let error = limit
        .observe(b"")
        .expect_err("a rejected event must not be resumed");

    assert_eq!(
        (error.kind(), error.to_string()),
        (
            ErrorKind::InvalidData,
            "oversized MCP SSE event was already rejected".to_string(),
        )
    );
}

#[test]
fn size_accounting_saturates_without_overflow() {
    let mut limit = SseEventSizeLimit::new(usize::MAX - 1);
    limit.retained_bytes = usize::MAX - 2;
    limit.line_bytes = 1;

    let error = limit
        .observe(b"x")
        .expect_err("saturating counts must still reject an oversized event");

    assert_eq!((error.kind(), limit.failed), (ErrorKind::InvalidData, true));
}
