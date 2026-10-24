use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_config::types::AuthKeyringBackendKind;
use codex_config::types::OAuthCredentialsStoreMode;
use codex_exec_server::Environment;
use pretty_assertions::assert_eq;
use rmcp::model::ClientCapabilities;
use rmcp::model::Implementation;
use rmcp::model::InitializeRequestParams;
use rmcp::model::ProtocolVersion;
use serde_json::Value;
use serde_json::json;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::Request;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

use crate::McpProtocolMode;
use crate::RmcpClient;
use crate::StreamableHttpBearerToken;
use crate::StreamableHttpRedirectMode;

async fn client(server: &MockServer, redirects: StreamableHttpRedirectMode) -> anyhow::Result<RmcpClient> {
    let client = RmcpClient::new_streamable_http_client_with_protocol_mode_and_redirect_mode(
        "retained-session-fixture", &format!("{}/mcp", server.uri()),
        Some(StreamableHttpBearerToken::Resolved("fixture-only-original-token".to_string())),
        /*http_headers*/ None, /*env_http_headers*/ None,
        OAuthCredentialsStoreMode::File, AuthKeyringBackendKind::default(),
        Environment::default_for_tests().get_http_client(), /*auth_provider*/ None,
        McpProtocolMode::Legacy, redirects,
    ).await?;
    client.initialize(
        InitializeRequestParams::new(ClientCapabilities::default(), Implementation::new("retained-test", "1"))
            .with_protocol_version(ProtocolVersion::V_2025_06_18),
        Some(Duration::from_secs(2)),
        Box::new(|_, _| Box::pin(async { anyhow::bail!("fixture never authorizes elicitation") })),
    ).await?;
    Ok(client)
}

async fn server(status: u16, delay: Duration) -> (MockServer, Arc<AtomicUsize>, Arc<AtomicUsize>) {
    let server = MockServer::start().await;
    let initializes = Arc::new(AtomicUsize::new(0));
    let calls = Arc::new(AtomicUsize::new(0));
    let init_count = Arc::clone(&initializes);
    let call_count = Arc::clone(&calls);
    Mock::given(method("POST")).and(path("/mcp"))
        .respond_with(move |request: &Request| {
            let body: Value = request.body_json().expect("MCP request");
            assert_eq!(request.headers["authorization"], "Bearer fixture-only-original-token");
            match body["method"].as_str() {
                Some("initialize") => {
                    init_count.fetch_add(1, Ordering::SeqCst);
                    ResponseTemplate::new(200).insert_header("mcp-session-id", "original-session")
                        .set_body_json(json!({"jsonrpc":"2.0","id":body["id"],"result":{
                            "protocolVersion":"2025-06-18","capabilities":{"tools":{}},
                            "serverInfo":{"name":"retained-test","version":"1"}
                        }}))
                }
                Some("notifications/initialized" | "notifications/cancelled") => ResponseTemplate::new(202),
                Some("tools/call") => {
                    call_count.fetch_add(1, Ordering::SeqCst);
                    if status == 200 {
                        ResponseTemplate::new(200).set_delay(delay).set_body_json(json!({
                            "jsonrpc":"2.0","id":body["id"],"result":{"content":[{"type":"text","text":"actual fixture reply"}]}
                        }))
                    } else {
                        ResponseTemplate::new(status).insert_header("www-authenticate", "Bearer resource_metadata=\"http://127.0.0.1/unused\"")
                    }
                }
                _ => ResponseTemplate::new(400),
            }
        }).mount(&server).await;
    (server, initializes, calls)
}

#[tokio::test]
async fn retained_session_never_recovers_404_or_retries_auth_or_transient_failures() -> anyhow::Result<()> {
    for status in [404, 401, 502] {
        let (server, initializes, calls) = server(status, Duration::ZERO).await;
        let client = client(&server, StreamableHttpRedirectMode::AgentPluginV1).await?;
        let retained = client.retain_tool_session().await?;
        assert!(retained.call_tool_once("process_start", Default::default(), Duration::from_secs(2)).await.is_err());
        assert_eq!((initializes.load(Ordering::SeqCst), calls.load(Ordering::SeqCst)), (1, 1));
        client.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn retained_session_lost_reply_has_hard_deadline_and_no_second_request() -> anyhow::Result<()> {
    let (server, initializes, calls) = server(200, Duration::from_secs(1)).await;
    let client = client(&server, StreamableHttpRedirectMode::AgentPluginV1).await?;
    let retained = client.retain_tool_session().await?;
    let started = std::time::Instant::now();
    assert!(retained.call_tool_once("process_start", Default::default(), Duration::from_millis(100)).await.is_err());
    assert!(started.elapsed() < Duration::from_millis(700));
    assert_eq!((initializes.load(Ordering::SeqCst), calls.load(Ordering::SeqCst)), (1, 1));
    client.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn retained_session_refuses_redirecting_transport_and_closed_peer() -> anyhow::Result<()> {
    let (server, _, calls) = server(200, Duration::ZERO).await;
    let redirecting = client(&server, StreamableHttpRedirectMode::Legacy).await?;
    assert!(redirecting.retain_tool_session().await.is_err());
    redirecting.shutdown().await;
    let original = client(&server, StreamableHttpRedirectMode::AgentPluginV1).await?;
    let retained = original.retain_tool_session().await?;
    original.shutdown().await;
    assert!(retained.call_tool_once("process_start", Default::default(), Duration::from_secs(1)).await.is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    Ok(())
}
