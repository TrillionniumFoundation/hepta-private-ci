use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_config::types::AuthKeyringBackendKind;
use codex_config::types::OAuthCredentialsStoreMode;
use codex_exec_server::Environment;
use codex_exec_server::ExecServerError;
use codex_exec_server::HttpClient;
use codex_exec_server::HttpRequestParams;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::HttpResponseBodyStream;
use futures::future::BoxFuture;
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

#[derive(Clone, Copy)]
enum FixtureAuth {
    Bearer,
    RuntimeHeader,
    DelegatedBearer,
}

async fn client(
    server: &MockServer,
    redirects: StreamableHttpRedirectMode,
) -> anyhow::Result<RmcpClient> {
    authenticated_client(
        server,
        redirects,
        FixtureAuth::Bearer,
        Environment::default_for_tests().get_http_client(),
    )
    .await
}

async fn authenticated_client(
    server: &MockServer,
    redirects: StreamableHttpRedirectMode,
    auth: FixtureAuth,
    http_client: Arc<dyn HttpClient>,
) -> anyhow::Result<RmcpClient> {
    let (bearer, headers) = match auth {
        FixtureAuth::Bearer => (Some(StreamableHttpBearerToken::Resolved(
            "fixture-only-original-token".to_string(),
        )), None),
        FixtureAuth::RuntimeHeader => (None, Some(std::collections::HashMap::from([
            ("X-Hepta-Runtime-Token".to_string(), "fixture-only-original-token".to_string()),
        ]))),
        FixtureAuth::DelegatedBearer => (Some(StreamableHttpBearerToken::ProvidedByHttpClient), Some(std::collections::HashMap::from([
            ("Authorization".to_string(), "Bearer fixture-only-original-token".to_string()),
        ]))),
    };
    let client = RmcpClient::new_streamable_http_client_with_protocol_mode_and_redirect_mode(
        "retained-session-fixture",
        &format!("{}/mcp", server.uri()),
        bearer,
        headers,
        /*env_http_headers*/ None,
        OAuthCredentialsStoreMode::File,
        AuthKeyringBackendKind::default(),
        http_client,
        /*auth_provider*/ None,
        McpProtocolMode::Legacy,
        redirects,
    )
    .await?;
    client
        .initialize(
            InitializeRequestParams::new(
                ClientCapabilities::default(),
                Implementation::new("retained-test", "1"),
            )
            .with_protocol_version(ProtocolVersion::V_2025_06_18),
            Some(Duration::from_secs(2)),
            Box::new(|_, _| {
                Box::pin(async { anyhow::bail!("fixture never authorizes elicitation") })
            }),
        )
        .await?;
    Ok(client)
}

async fn server(status: u16, delay: Duration) -> (MockServer, Arc<AtomicUsize>, Arc<AtomicUsize>) {
    authenticated_server(status, delay, FixtureAuth::Bearer).await
}

async fn authenticated_server(status: u16, delay: Duration, auth: FixtureAuth) -> (MockServer, Arc<AtomicUsize>, Arc<AtomicUsize>) {
    let server = MockServer::start().await;
    let initializes = Arc::new(AtomicUsize::new(0));
    let calls = Arc::new(AtomicUsize::new(0));
    let init_count = Arc::clone(&initializes);
    let call_count = Arc::clone(&calls);
    Mock::given(method("POST")).and(path("/mcp"))
        .respond_with(move |request: &Request| {
            let body: Value = request.body_json().expect("MCP request");
            match auth {
                FixtureAuth::Bearer | FixtureAuth::DelegatedBearer => assert_eq!(request.headers["authorization"], "Bearer fixture-only-original-token"),
                FixtureAuth::RuntimeHeader => {
                    assert_eq!(request.headers["x-hepta-runtime-token"], "fixture-only-original-token");
                    assert!(!request.headers.contains_key("authorization"));
                }
            }
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
                        ResponseTemplate::new(status)
                            .insert_header("www-authenticate", "DPoP error=\"use_dpop_nonce\"")
                            .insert_header("dpop-nonce", "fixture-server-nonce")
                            .insert_header("location", "/unexpected-auth-replay")
                    }
                }
                _ => ResponseTemplate::new(400),
            }
        }).mount(&server).await;
    (server, initializes, calls)
}

#[tokio::test]
async fn retained_session_never_recovers_404_or_retries_auth_or_transient_failures()
-> anyhow::Result<()> {
    for (auth, redirects, status) in [FixtureAuth::Bearer, FixtureAuth::RuntimeHeader].into_iter().flat_map(|auth| [StreamableHttpRedirectMode::Legacy, StreamableHttpRedirectMode::AgentPluginV1].into_iter().flat_map(move |redirects| [404, 401, 400, 403, 502, 307].map(|status| (auth, redirects, status)))) {
        let (server, initializes, calls) = authenticated_server(status, Duration::ZERO, auth).await;
        let client = authenticated_client(&server, redirects, auth, Environment::default_for_tests().get_http_client()).await?;
        let retained = client.retain_tool_session().await?;
        assert!(
            retained
                .call_tool_once("process_start", Default::default(), Duration::from_secs(2))
                .await
                .is_err()
        );
        assert_eq!(
            (
                initializes.load(Ordering::SeqCst),
                calls.load(Ordering::SeqCst)
            ),
            (1, 1)
        );
        let requests = server.received_requests().await.expect("recorded requests");
        assert!(requests.iter().all(|request| request.url.path() == "/mcp"));
        assert_eq!(requests.iter().filter(|request| request.body_json::<Value>().is_ok_and(|body| body["method"] == "tools/call")).count(), 1);
        client.shutdown().await;
    }
    Ok(())
}

/// An ordinary authenticated HTTP wrapper with no single-attempt contract.
/// Retention must not infer its behavior from successful initialization.
struct OpaqueHttpClient(Arc<dyn HttpClient>);

impl HttpClient for OpaqueHttpClient {
    fn http_request(&self, params: HttpRequestParams) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        self.0.http_request(params)
    }

    fn http_request_stream(&self, params: HttpRequestParams) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.0.http_request_stream(params)
    }
}

#[tokio::test]
async fn retained_session_refuses_opaque_transport_and_delegated_auth_before_tool_call() -> anyhow::Result<()> {
    let (server, initializes, calls) = server(200, Duration::ZERO).await;
    for (auth, http_client) in [
        (FixtureAuth::Bearer, Arc::new(OpaqueHttpClient(Environment::default_for_tests().get_http_client())) as Arc<dyn HttpClient>),
        (FixtureAuth::DelegatedBearer, Environment::default_for_tests().get_http_client()),
    ] {
        let client = authenticated_client(&server, StreamableHttpRedirectMode::AgentPluginV1, auth, http_client).await?;
        assert!(client.retain_tool_session().await.is_err());
        client.shutdown().await;
    }
    assert_eq!((initializes.load(Ordering::SeqCst), calls.load(Ordering::SeqCst)), (2, 0));
    Ok(())
}

#[tokio::test]
async fn retained_session_lost_reply_has_hard_deadline_and_no_second_request() -> anyhow::Result<()>
{
    let (server, initializes, calls) = server(200, Duration::from_secs(1)).await;
    let client = client(&server, StreamableHttpRedirectMode::AgentPluginV1).await?;
    let retained = client.retain_tool_session().await?;
    let started = std::time::Instant::now();
    assert!(
        retained
            .call_tool_once(
                "process_start",
                Default::default(),
                Duration::from_millis(100)
            )
            .await
            .is_err()
    );
    assert!(started.elapsed() < Duration::from_millis(700));
    // Keep the original authenticated peer alive past the delayed response.
    // Closing it immediately would hide an SDK worker's deferred replay.
    tokio::time::sleep(Duration::from_millis(1100)).await;
    assert_eq!(
        (
            initializes.load(Ordering::SeqCst),
            calls.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
    client.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn retained_session_refuses_closed_original_peer() -> anyhow::Result<()> {
    let (server, _, calls) = server(200, Duration::ZERO).await;
    let original = client(&server, StreamableHttpRedirectMode::AgentPluginV1).await?;
    let retained = original.retain_tool_session().await?;
    original.shutdown().await;
    assert!(
        retained
            .call_tool_once("process_start", Default::default(), Duration::from_secs(1))
            .await
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn retained_session_does_not_follow_parent_session_recovery() -> anyhow::Result<()> {
    let (server, initializes, calls) = server(404, Duration::ZERO).await;
    let original = client(&server, StreamableHttpRedirectMode::AgentPluginV1).await?;
    let retained = original.retain_tool_session().await?;
    // The ordinary client's existing policy recovers once. The retained effect
    // capability must lose its original lifetime even if the server reuses its
    // opaque session ID, rather than following the parent's replacement peer.
    assert!(
        original
            .call_tool(
                "process_wait".to_string(),
                Some(json!({})),
                /*meta*/ None,
                Some(Duration::from_secs(2))
            )
            .await
            .is_err()
    );
    assert_eq!(
        (
            initializes.load(Ordering::SeqCst),
            calls.load(Ordering::SeqCst)
        ),
        (2, 2)
    );
    assert!(
        retained
            .call_tool_once("process_start", Default::default(), Duration::from_secs(1))
            .await
            .is_err()
    );
    assert_eq!(
        (
            initializes.load(Ordering::SeqCst),
            calls.load(Ordering::SeqCst)
        ),
        (2, 2)
    );
    original.shutdown().await;
    Ok(())
}
