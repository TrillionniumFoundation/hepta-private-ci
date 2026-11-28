use std::time::Duration;

use anyhow::Result;
use app_test_support::TestAppServer;
use codex_app_server_protocol::JSONRPCError;
use codex_app_server_protocol::RequestId;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;
use wiremock::matchers::query_param;

#[tokio::test]
async fn oauth_login_reports_discovery_status_without_query_or_header_secrets() -> Result<()> {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/mcp"))
        .and(query_param("api_key", "query-secret"))
        .and(header("x-secret", "header-secret"))
        .respond_with(ResponseTemplate::new(/*s*/ 408))
        .expect(/*r*/ 1)
        .mount(&server)
        .await;
    let codex_home = TempDir::new()?;
    let server_url = format!("{}/mcp?api_key=query-secret", server.uri());
    std::fs::write(
        codex_home.path().join("config.toml"),
        format!(
            "mcp_oauth_credentials_store = \"file\"\n\
             [mcp_servers.discovery]\n\
             url = \"{server_url}\"\n\
             http_headers = {{ x-secret = \"header-secret\" }}\n\
             [mcp_servers.discovery.oauth]\n\
             client_id = \"test-client\"\n"
        ),
    )?;
    let read_timeout = Duration::from_secs(/*secs*/ 10);
    let mut app = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(read_timeout)
        .await?;
    assert_eq!(
        server
            .received_requests()
            .await
            .map(|requests| requests.len()),
        Some(0),
        "initialization must not consume the login discovery request"
    );
    let request_id = app
        .send_raw_request(
            "mcpServer/oauth/login",
            Some(json!({"name": "discovery", "scopes": ["read"], "timeoutSecs": 10})),
        )
        .await?;
    let error: JSONRPCError = timeout(
        read_timeout,
        app.read_stream_until_error_message(RequestId::Integer(request_id)),
    )
    .await??;
    assert_eq!(
        serde_json::to_value(error)?,
        json!({
            "id": request_id,
            "error": {
                "code": -32603,
                "message": "failed to login to MCP server 'discovery': OAuth metadata discovery failed: HTTP 408 Request Timeout"
            }
        })
    );
    server.verify().await;
    Ok(())
}
