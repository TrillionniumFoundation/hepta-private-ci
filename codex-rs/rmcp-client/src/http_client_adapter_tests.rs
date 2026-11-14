use std::collections::HashMap;
use std::io::ErrorKind;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use axum::Router;
use axum::body::Body;
use axum::routing::any;
use bytes::Bytes;
use codex_exec_server::Environment;
use codex_exec_server::HttpRedirectPolicy;
use futures::StreamExt;
use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;
use http::Method;
use http::header::AUTHORIZATION;
use http::header::CONTENT_TYPE;
use pretty_assertions::assert_eq;
use rmcp::transport::streamable_http_client::StreamableHttpClient;
use rmcp::transport::streamable_http_client::StreamableHttpPostResponse;
use serde_json::json;

use super::HttpHeader;
use super::SseEventSizeLimit;
use super::StreamableHttpClientAdapter;
use super::StreamableHttpRedirectMode;
use super::mcp_redirect_policy;
use super::protocol_headers;

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

#[tokio::test]
async fn configured_sse_limit_applies_to_legacy_post_and_get() -> anyhow::Result<()> {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let app = Router::new().route(
        "/mcp",
        any(|| async {
            let body = futures::stream::once(async {
                Ok::<_, std::io::Error>(Bytes::from_static(
                    b"data: this event is longer than the configured limit\n\n",
                ))
            })
            .chain(futures::stream::pending());
            (
                [(CONTENT_TYPE, "text/event-stream")],
                Body::from_stream(body),
            )
        }),
    );
    let server = tokio::spawn(async move { axum::serve(listener, app).await });
    let adapter = StreamableHttpClientAdapter::new(
        Environment::default_for_tests().get_http_client(),
        HeaderMap::new(),
        /*auth_provider*/ None,
        /*has_configured_headers*/ false,
        StreamableHttpRedirectMode::Legacy,
        Arc::new(Mutex::new(None)),
    );

    for method in [Method::POST, Method::GET] {
        let uri: Arc<str> = format!("http://{address}/mcp").into();
        let headers = HashMap::from([(
            HeaderName::from_static("mcp-protocol-version"),
            HeaderValue::from_static("2025-06-18"),
        )]);
        let mut events = if method == Method::POST {
            let message = serde_json::from_value(json!({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            }))?;
            let response = adapter
                .post_message_with_max_sse_event_size(
                    uri, message, /*session_id*/ None, /*auth_token*/ None, headers,
                    /*max_sse_event_size*/ 32,
                )
                .await?;
            let StreamableHttpPostResponse::Sse(events, _) = response else {
                anyhow::bail!("expected an SSE response");
            };
            events
        } else {
            adapter
                .get_stream_with_max_sse_event_size(
                    uri, /*session_id*/ None, /*last_event_id*/ None,
                    /*auth_token*/ None, headers, /*max_sse_event_size*/ 32,
                )
                .await?
        };
        let error = events
            .next()
            .await
            .expect("oversized SSE event must produce an error")
            .expect_err("configured limit must apply before parsing the legacy SSE event");
        assert!(
            error.to_string().contains("32 bytes"),
            "unexpected {method} SSE error: {error}"
        );
        assert!(
            tokio::time::timeout(Duration::from_secs(1), events.next())
                .await?
                .is_none(),
            "failed {method} SSE stream must terminate after its error"
        );
    }
    server.abort();
    Ok(())
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
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 8);

    limit
        .observe(b"data: a\n\ndata: b\n\n")
        .expect("LF-terminated events must have independent size limits");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn carriage_return_terminators_reset_the_event_limit() {
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 8);

    limit
        .observe(b"data: a\r\rdata: b\r\r")
        .expect("CR-terminated events must have independent size limits");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn crlf_terminators_split_across_chunks_reset_the_event_limit() {
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 8);

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
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 9);

    limit
        .observe(b"data: ab\n\n")
        .expect("an event at the exact limit must be accepted");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn completed_keepalive_comments_do_not_accumulate() {
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 6);

    limit
        .observe(&b": ping\n".repeat(/*n*/ 64))
        .expect("completed keepalive comments must not accumulate");

    assert_eq!((limit.retained_bytes, limit.line_bytes), (0, 0));
}

#[test]
fn split_keepalive_comments_are_discarded_only_when_complete() {
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 6);

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
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 14);

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
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 6);

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
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 18);

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
fn total_stream_size_does_not_accumulate_across_complete_events() {
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 16);

    limit
        .observe(&b"data: x\n\n".repeat(/*n*/ 128))
        .expect("individually bounded events must not share a cumulative stream limit");

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
fn rejected_events_remain_rejected() {
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ 8);

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
    let mut limit = SseEventSizeLimit::new(/*maximum_bytes*/ usize::MAX - 1);
    limit.retained_bytes = usize::MAX - 2;
    limit.line_bytes = 1;

    let error = limit
        .observe(b"x")
        .expect_err("saturating counts must still reject an oversized event");

    assert_eq!((error.kind(), limit.failed), (ErrorKind::InvalidData, true));
}
