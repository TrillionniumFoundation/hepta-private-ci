use super::*;

use std::collections::HashMap;
use std::io::Read;
use std::io::Write;
use std::net::Ipv4Addr;
use std::net::SocketAddr;
use std::net::TcpStream;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_config::types::AuthKeyringBackendKind;
use codex_config::types::OAuthCredentialsStoreMode;
use codex_exec_server::RouteAwareHttpClient;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use http::HeaderValue;
use pretty_assertions::assert_eq;
use rmcp::transport::auth::AuthError;
use serde_json::json;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_partial_json;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;

use crate::oauth::stored_oauth_credentials;
use crate::oauth::test_support::TempCodexHome;
use crate::oauth_client_registration::McpOAuthClientRegistration;
use crate::perform_oauth_login::perform_oauth_login_return_url_with_protocol_mode;

struct ObservedRequest {
    resource_origin: String,
    method: String,
    url: String,
    timeout_ms: Option<u64>,
}

struct RecordingRestrictedClient {
    inner: RouteAwareHttpClient,
    ordinary_requests: AtomicUsize,
    requests: Mutex<Vec<ObservedRequest>>,
}

impl RecordingRestrictedClient {
    fn new() -> Self {
        Self {
            inner: RouteAwareHttpClient::new(HttpClientFactory::new(
                OutboundProxyPolicy::ReqwestDefault,
            )),
            ordinary_requests: AtomicUsize::new(0),
            requests: Mutex::new(Vec::new()),
        }
    }

    fn assert_original_capability(&self, origin: &str, expected_post_method: &str) {
        assert_eq!(self.ordinary_requests.load(Ordering::SeqCst), 0);
        let requests = self.requests.lock().expect("request recorder lock");
        assert!(!requests.is_empty());
        assert!(
            requests
                .iter()
                .all(|request| request.resource_origin == origin)
        );
        let mcp_posts = requests
            .iter()
            .filter(|request| request.method == "POST" && request.url == format!("{origin}/mcp"))
            .collect::<Vec<_>>();
        assert_eq!(
            mcp_posts.len(),
            1,
            "one actual {expected_post_method} challenge"
        );
        assert!(mcp_posts.iter().all(|request| {
            request
                .timeout_ms
                .is_some_and(|timeout| timeout > 0 && timeout <= 5_000)
        }));
    }
}

impl HttpClient for RecordingRestrictedClient {
    fn http_request(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, std::result::Result<HttpRequestResponse, ExecServerError>> {
        self.ordinary_requests.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::Protocol(
                "unexpected unrestricted HTTP".to_string(),
            ))
        })
    }

    fn http_request_stream(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<
        '_,
        std::result::Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>,
    > {
        self.ordinary_requests.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::Protocol(
                "unexpected unrestricted HTTP stream".to_string(),
            ))
        })
    }

    fn http_request_stream_restricted(
        &self,
        params: HttpRequestRestrictedParams,
    ) -> BoxFuture<
        '_,
        std::result::Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>,
    > {
        self.requests
            .lock()
            .expect("request recorder lock")
            .push(ObservedRequest {
                resource_origin: params.configured_resource_origin.clone(),
                method: params.request.method.clone(),
                url: params.request.url.clone(),
                timeout_ms: params.request.timeout_ms,
            });
        // Recording never substitutes a fake capability: production transport
        // resolves, validates and connects under the original address policy.
        self.inner.http_request_stream_restricted(params)
    }
}

async fn context(
    server: &MockServer,
) -> (
    AuthorizationManager,
    Arc<OAuthHttpClientAdapter>,
    Arc<RecordingRestrictedClient>,
) {
    let client = Arc::new(RecordingRestrictedClient::new());
    let adapter = Arc::new(
        OAuthHttpClientAdapter::new_with_redirect_mode(
            client.clone(),
            HeaderMap::from_iter([(
                http::HeaderName::from_static("x-configured-resource"),
                HeaderValue::from_static("owner-bound-value"),
            )]),
            &format!("{}/mcp", server.uri()),
            true,
            StreamableHttpRedirectMode::Legacy,
        )
        .expect("configured resource URL"),
    );
    let mut manager = AuthorizationManager::new_with_oauth_http_client(
        format!("{}/mcp", server.uri()),
        adapter.clone(),
    )
    .await
    .expect("authorization manager");
    manager.set_allow_missing_issuer(true);
    (manager, adapter, client)
}

fn metadata(origin: &str) -> serde_json::Value {
    json!({
        "issuer": format!("{origin}/issuer"),
        "authorization_endpoint": format!("{origin}/authorize"),
        "token_endpoint": format!("{origin}/token"),
        "registration_endpoint": format!("{origin}/register"),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["read"],
        "authorization_response_iss_parameter_supported": true,
    })
}

async fn mount_challenge(server: &MockServer, mode: McpProtocolMode, challenge: &str) {
    let request_method = match mode {
        McpProtocolMode::Legacy => "initialize",
        McpProtocolMode::V20260728 => "server/discover",
    };
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .and(body_partial_json(json!({"method": request_method})))
        .and(header("x-configured-resource", "owner-bound-value"))
        .respond_with(ResponseTemplate::new(401).insert_header("www-authenticate", challenge))
        .expect(1)
        .mount(server)
        .await;
}

async fn mount_custom_metadata(server: &MockServer, issuer: &str) {
    Mock::given(method("GET"))
        .and(path("/custom/metadata.json"))
        .and(header("x-configured-resource", "owner-bound-value"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "resource": format!("{}/mcp", server.uri()),
            "authorization_servers": [issuer],
            "scopes_supported": ["read"],
        })))
        .expect(1)
        .mount(server)
        .await;
}

async fn send_callback(mut callback: Url, state: &str, issuer: &str) -> Result<()> {
    callback
        .query_pairs_mut()
        .append_pair("code", "reactive-code")
        .append_pair("state", state)
        .append_pair("iss", issuer);
    anyhow::ensure!(
        callback.host_str() == Some("127.0.0.1"),
        "unexpected callback host"
    );
    let port = callback.port().context("callback port")?;
    tokio::task::spawn_blocking(move || -> Result<()> {
        let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
        let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(2))?;
        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
        stream.set_write_timeout(Some(Duration::from_secs(2)))?;
        let query = callback.query().context("callback query")?;
        write!(
            stream,
            "GET {}?{query} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n",
            callback.path(),
        )?;
        let mut response = String::new();
        stream.read_to_string(&mut response)?;
        anyhow::ensure!(
            response.starts_with("HTTP/1.1 200"),
            "callback response: {response}"
        );
        Ok(())
    })
    .await?
}

async fn complete_reactive_login(mode: McpProtocolMode, preregistered: bool) -> Result<()> {
    let _home = TempCodexHome::new();
    let server = MockServer::start().await;
    let origin = server.uri();
    let resource_url = format!("{origin}/mcp");
    let issuer = format!("{origin}/issuer");
    mount_challenge(
        &server,
        mode,
        &format!("Bearer resource_metadata=\"{origin}/custom/metadata.json\", scope=\"read\""),
    )
    .await;
    mount_custom_metadata(&server, &issuer).await;
    Mock::given(method("GET"))
        .and(path("/.well-known/oauth-authorization-server/issuer"))
        .respond_with(ResponseTemplate::new(200).set_body_json(metadata(&origin)))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/register"))
        .and(body_partial_json(json!({
            "client_name": "Codex",
            "token_endpoint_auth_method": "none",
        })))
        .respond_with(ResponseTemplate::new(201).set_body_json(json!({
            "client_id": "reactive-dynamic-client",
            "client_name": "Codex",
            "redirect_uris": [],
            "token_endpoint_auth_method": "none",
        })))
        .expect(if preregistered { 0 } else { 1 })
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/token"))
        .and(header("x-configured-resource", "owner-bound-value"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "access_token": "reactive-access-token",
            "token_type": "Bearer",
            "refresh_token": "reactive-refresh-token",
            "scope": "read",
        })))
        .expect(1)
        .mount(&server)
        .await;
    let client = Arc::new(RecordingRestrictedClient::new());
    let handle = perform_oauth_login_return_url_with_protocol_mode(
        "reactive-owner",
        &resource_url,
        OAuthCredentialsStoreMode::File,
        AuthKeyringBackendKind::Direct,
        Some(HashMap::from([(
            "x-configured-resource".to_string(),
            "owner-bound-value".to_string(),
        )])),
        None,
        &["read".to_string()],
        preregistered.then_some("reactive-preregistered-client"),
        McpOAuthClientRegistration::Dcr,
        None,
        Some(10),
        None,
        None,
        client.clone(),
        StreamableHttpRedirectMode::Legacy,
        mode,
    )
    .await?;
    let auth_url = Url::parse(handle.authorization_url())?;
    assert_eq!(auth_url.path(), "/authorize");
    let query = auth_url
        .query_pairs()
        .into_owned()
        .collect::<HashMap<_, _>>();
    let expected_client = if preregistered {
        "reactive-preregistered-client"
    } else {
        "reactive-dynamic-client"
    };
    assert_eq!(
        query.get("client_id").map(String::as_str),
        Some(expected_client)
    );
    assert_eq!(query.get("scope").map(String::as_str), Some("read"));
    assert_eq!(
        query.get("code_challenge_method").map(String::as_str),
        Some("S256")
    );
    let callback = Url::parse(query.get("redirect_uri").context("redirect URI")?)?;
    send_callback(
        callback,
        query.get("state").context("OAuth state")?,
        &issuer,
    )
    .await?;
    handle.wait().await?;
    let stored = stored_oauth_credentials(
        "reactive-owner",
        &resource_url,
        OAuthCredentialsStoreMode::File,
        AuthKeyringBackendKind::Direct,
    )?
    .context("stored OAuth credentials")?;
    assert_eq!(stored.issuer.as_deref(), Some(issuer.as_str()));
    assert_eq!(stored.client_id, expected_client);
    assert_eq!(stored.url, resource_url);
    client.assert_original_capability(
        &origin,
        if mode == McpProtocolMode::Legacy {
            "initialize"
        } else {
            "server/discover"
        },
    );
    server.verify().await;
    Ok(())
}

#[tokio::test]
async fn legacy_post_challenge_completes_dcr_callback_and_issuer_persistence() -> Result<()> {
    complete_reactive_login(McpProtocolMode::Legacy, false).await
}

#[tokio::test]
async fn modern_post_challenge_completes_preregistered_callback_and_issuer_persistence()
-> Result<()> {
    complete_reactive_login(McpProtocolMode::V20260728, true).await
}

#[tokio::test]
async fn published_metadata_does_not_send_an_mcp_probe() {
    let server = MockServer::start().await;
    let origin = server.uri();
    Mock::given(method("GET"))
        .and(path("/mcp"))
        .respond_with(ResponseTemplate::new(401).insert_header(
            "www-authenticate",
            format!("Bearer resource_metadata=\"{origin}/custom/metadata.json\""),
        ))
        .expect(1)
        .mount(&server)
        .await;
    mount_custom_metadata(&server, &format!("{origin}/issuer")).await;
    Mock::given(method("GET"))
        .and(path("/.well-known/oauth-authorization-server/issuer"))
        .respond_with(ResponseTemplate::new(200).set_body_json(metadata(&origin)))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(500))
        .expect(0)
        .mount(&server)
        .await;
    let (manager, adapter, client) = context(&server).await;
    let resolved = resolve_metadata_with_mcp_challenge(
        &manager,
        &adapter,
        &format!("{origin}/mcp"),
        McpProtocolMode::V20260728,
        Instant::now() + Duration::from_secs(5),
    )
    .await
    .expect("published metadata succeeds without an extra handshake");
    assert_eq!(
        resolved.source,
        AuthorizationMetadataSource::ProtectedResourceMetadata
    );
    assert_eq!(client.ordinary_requests.load(Ordering::SeqCst), 0);
    server.verify().await;
}

#[tokio::test]
async fn post_challenge_does_not_authorize_another_loopback_issuer() {
    let destination = MockServer::start().await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(200).set_body_json(metadata(&destination.uri())))
        .expect(0)
        .mount(&destination)
        .await;
    let server = MockServer::start().await;
    let origin = server.uri();
    mount_challenge(
        &server,
        McpProtocolMode::Legacy,
        &format!("Bearer resource_metadata=\"{origin}/custom/metadata.json\""),
    )
    .await;
    mount_custom_metadata(&server, &format!("{}/issuer", destination.uri())).await;
    let (manager, adapter, client) = context(&server).await;
    let error = resolve_metadata_with_mcp_challenge(
        &manager,
        &adapter,
        &format!("{origin}/mcp"),
        McpProtocolMode::Legacy,
        Instant::now() + Duration::from_secs(5),
    )
    .await
    .expect_err("metadata cannot grant a new loopback origin");
    let denied_url = format!(
        "{}/.well-known/oauth-authorization-server/issuer",
        destination.uri()
    );
    assert!(
        matches!(
            error.downcast_ref::<AuthError>(),
            Some(AuthError::DiscoveryRequestFailed { url, source })
                if url.as_str() == denied_url
                    && matches!(
                        source.downcast_ref::<ExecServerError>(),
                        Some(ExecServerError::HttpRequest(reason))
                            if reason.contains("HTTP destination is outside the configured address capability")
                    )
        ),
        "must preserve the typed address denial: {error:#}"
    );
    client.assert_original_capability(&origin, "initialize");
    destination.verify().await;
    assert!(
        destination
            .received_requests()
            .await
            .expect("request recording")
            .is_empty()
    );
    server.verify().await;
}

#[tokio::test]
async fn post_challenge_preserves_metadata_redirect_and_issuer_checks() {
    for bad_issuer in [false, true] {
        let destination = MockServer::start().await;
        let server = MockServer::start().await;
        let origin = server.uri();
        mount_challenge(
            &server,
            McpProtocolMode::Legacy,
            &format!("Bearer resource_metadata=\"{origin}/custom/metadata.json\""),
        )
        .await;
        if bad_issuer {
            mount_custom_metadata(&server, &format!("{origin}/issuer")).await;
            let mut document = metadata(&origin);
            document["issuer"] = json!(format!("{origin}/wrong-issuer"));
            Mock::given(method("GET"))
                .and(path("/.well-known/oauth-authorization-server/issuer"))
                .respond_with(ResponseTemplate::new(200).set_body_json(document))
                .expect(1)
                .mount(&server)
                .await;
        } else {
            Mock::given(method("GET"))
                .and(path("/custom/metadata.json"))
                .respond_with(
                    ResponseTemplate::new(302).insert_header(
                        "location",
                        format!("{}/stolen-metadata", destination.uri()),
                    ),
                )
                .expect(1)
                .mount(&server)
                .await;
        }
        let (manager, adapter, client) = context(&server).await;
        let error = resolve_metadata_with_mcp_challenge(
            &manager,
            &adapter,
            &format!("{origin}/mcp"),
            McpProtocolMode::Legacy,
            Instant::now() + Duration::from_secs(5),
        )
        .await
        .expect_err("reactive discovery must preserve issuer and credentialed redirect checks");
        if bad_issuer {
            assert!(
                matches!(
                    error.downcast_ref::<AuthError>(),
                    Some(AuthError::AuthorizationServerMismatch {
                        expected_issuer,
                        received_issuer,
                    }) if expected_issuer == &format!("{origin}/issuer")
                        && received_issuer == &format!("{origin}/wrong-issuer")
                ),
                "issuer mismatch must remain the exact typed cause: {error:#}"
            );
        } else {
            assert!(
                matches!(
                    error.downcast_ref::<AuthError>(),
                    Some(AuthError::DiscoveryRequestFailed { source, .. })
                        if source.to_string().contains("non-same-origin URL rejected")
                ),
                "credentialed metadata redirect must be rejected: {error:#}"
            );
        }
        assert!(
            destination
                .received_requests()
                .await
                .expect("request recording")
                .is_empty()
        );
        client.assert_original_capability(&origin, "initialize");
        server.verify().await;
    }
}

#[tokio::test]
async fn non_challenge_responses_never_become_reactive_success() {
    for status in [401, 403, 503] {
        let server = MockServer::start().await;
        let origin = server.uri();
        Mock::given(method("POST"))
            .and(path("/mcp"))
            .respond_with(ResponseTemplate::new(status).set_body_string(format!(
                "WWW-Authenticate: Bearer resource_metadata=\"{origin}/forged-from-body\""
            )))
            .expect(1)
            .mount(&server)
            .await;
        Mock::given(path("/forged-from-body"))
            .respond_with(ResponseTemplate::new(200))
            .expect(0)
            .mount(&server)
            .await;
        let (manager, adapter, client) = context(&server).await;
        let error = resolve_metadata_with_mcp_challenge(
            &manager,
            &adapter,
            &format!("{origin}/mcp"),
            McpProtocolMode::Legacy,
            Instant::now() + Duration::from_secs(5),
        )
        .await
        .expect_err("only a typed 401 response header can seed reactive discovery");
        assert!(
            matches!(
                error.downcast_ref::<ClientInitializeError>(),
                Some(ClientInitializeError::TransportError { error: transport, .. })
                    if matches!(
                        transport.error.downcast_ref::<StreamableHttpError<StreamableHttpClientAdapterError>>(),
                        Some(StreamableHttpError::UnexpectedServerResponse(reason))
                            if reason.starts_with(&format!("HTTP {status}: "))
                    )
            ),
            "a missing header must retain the actual HTTP status error: {error:#}"
        );
        client.assert_original_capability(&origin, "initialize");
        server.verify().await;
    }
}

#[tokio::test]
async fn oversized_challenge_is_rejected_before_metadata_io() {
    let server = MockServer::start().await;
    let origin = server.uri();
    mount_challenge(
        &server,
        McpProtocolMode::Legacy,
        &format!(
            "Bearer resource_metadata=\"{origin}/never-read\", scope=\"{}\"",
            "a".repeat(MAX_OBSERVED_CHALLENGE_BYTES),
        ),
    )
    .await;
    Mock::given(path("/never-read"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&server)
        .await;
    let (manager, adapter, client) = context(&server).await;
    let error = resolve_metadata_with_mcp_challenge(
        &manager,
        &adapter,
        &format!("{origin}/mcp"),
        McpProtocolMode::Legacy,
        Instant::now() + Duration::from_secs(5),
    )
    .await
    .expect_err("oversized response header must not become metadata input");
    assert!(
        error
            .to_string()
            .contains("challenge has an invalid length")
    );
    client.assert_original_capability(&origin, "initialize");
    server.verify().await;
}

#[tokio::test]
async fn expired_login_deadline_stops_before_any_http_request() {
    let server = MockServer::start().await;
    let (manager, adapter, client) = context(&server).await;
    let error = resolve_metadata_with_mcp_challenge(
        &manager,
        &adapter,
        &format!("{}/mcp", server.uri()),
        McpProtocolMode::Legacy,
        Instant::now(),
    )
    .await
    .expect_err("expired login cannot begin discovery");
    assert!(
        error
            .to_string()
            .contains("timed out before metadata discovery")
    );
    assert_eq!(client.ordinary_requests.load(Ordering::SeqCst), 0);
    assert!(
        client
            .requests
            .lock()
            .expect("request recorder lock")
            .is_empty()
    );
    assert!(
        server
            .received_requests()
            .await
            .expect("request recording")
            .is_empty()
    );
}

#[tokio::test]
async fn probe_deadline_failure_remains_failure() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .respond_with(
            ResponseTemplate::new(401)
                .insert_header("www-authenticate", "Bearer")
                .set_delay(Duration::from_secs(5)),
        )
        .expect(1)
        .mount(&server)
        .await;
    let (_, adapter, client) = context(&server).await;
    let result = tokio::time::timeout(
        Duration::from_secs(2),
        observe_mcp_challenge(
            adapter.mcp_probe_context(),
            &format!("{}/mcp", server.uri()),
            McpProtocolMode::Legacy,
            Instant::now() + Duration::from_secs(1),
        ),
    )
    .await
    .expect("restricted request must terminate inside the outer test bound");
    result.expect_err("delayed 401 must not be accepted after its request deadline");
    client.assert_original_capability(&server.uri(), "initialize");
    server.verify().await;
}

#[derive(Default)]
struct OrdinaryOnlyClient {
    requests: AtomicUsize,
}

impl HttpClient for OrdinaryOnlyClient {
    fn http_request(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, std::result::Result<HttpRequestResponse, ExecServerError>> {
        self.requests.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::Protocol(
                "ordinary HTTP was called".to_string(),
            ))
        })
    }

    fn http_request_stream(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<
        '_,
        std::result::Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>,
    > {
        self.requests.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::Protocol(
                "ordinary HTTP stream was called".to_string(),
            ))
        })
    }
}

#[tokio::test]
async fn transport_without_restricted_capability_never_falls_back_to_ordinary_http() {
    let server = MockServer::start().await;
    let client = Arc::new(OrdinaryOnlyClient::default());
    let error = observe_mcp_challenge(
        McpOAuthProbeContext {
            http_client: client.clone(),
            default_headers: HeaderMap::new(),
            configured_resource_origin: server.uri(),
            has_configured_headers: false,
            redirect_mode: StreamableHttpRedirectMode::Legacy,
        },
        &format!("{}/mcp", server.uri()),
        McpProtocolMode::Legacy,
        Instant::now() + Duration::from_secs(5),
    )
    .await
    .expect_err("ordinary HTTP support does not grant restricted HTTP capability");
    let Some(ClientInitializeError::TransportError {
        error: transport, ..
    }) = error.downcast_ref::<ClientInitializeError>()
    else {
        panic!("expected original typed handshake transport error: {error:#}");
    };
    assert!(
        matches!(
            transport.error.downcast_ref::<StreamableHttpError<StreamableHttpClientAdapterError>>(),
            Some(StreamableHttpError::Client(StreamableHttpClientAdapterError::HttpRequest(
                ExecServerError::Protocol(reason)
            ))) if reason == "HTTP transport does not support restricted destination requests"
        ),
        "unsupported restricted capability must remain the actual cause: {error:#}"
    );
    assert_eq!(client.requests.load(Ordering::SeqCst), 0);
    assert!(
        server
            .received_requests()
            .await
            .expect("request recording")
            .is_empty()
    );
}

#[tokio::test]
async fn changed_resource_origin_is_rejected_before_the_probe() {
    let configured = MockServer::start().await;
    let other = MockServer::start().await;
    let (_, adapter, client) = context(&configured).await;
    let error = observe_mcp_challenge(
        adapter.mcp_probe_context(),
        &format!("{}/mcp", other.uri()),
        McpProtocolMode::Legacy,
        Instant::now() + Duration::from_secs(5),
    )
    .await
    .expect_err("probe must remain bound to the original configured resource origin");
    assert_eq!(
        error.to_string(),
        "MCP OAuth challenge resource origin changed"
    );
    assert_eq!(client.ordinary_requests.load(Ordering::SeqCst), 0);
    assert!(
        client
            .requests
            .lock()
            .expect("request recorder lock")
            .is_empty()
    );
    assert!(
        configured
            .received_requests()
            .await
            .expect("request recording")
            .is_empty()
    );
    assert!(
        other
            .received_requests()
            .await
            .expect("request recording")
            .is_empty()
    );
}

#[tokio::test]
async fn empty_challenge_header_is_distinct_from_a_missing_header() {
    let server = MockServer::start().await;
    mount_challenge(&server, McpProtocolMode::Legacy, "").await;
    let (manager, adapter, client) = context(&server).await;
    let error = resolve_metadata_with_mcp_challenge(
        &manager,
        &adapter,
        &format!("{}/mcp", server.uri()),
        McpProtocolMode::Legacy,
        Instant::now() + Duration::from_secs(5),
    )
    .await
    .expect_err("an actual but empty 401 header must be rejected");
    assert_eq!(
        error.to_string(),
        "MCP OAuth challenge has an invalid length"
    );
    assert!(error.downcast_ref::<ClientInitializeError>().is_none());
    client.assert_original_capability(&server.uri(), "initialize");
    server.verify().await;
}

#[tokio::test]
async fn ordinary_discovery_and_post_probe_share_the_same_absolute_deadline() {
    let server = MockServer::start().await;
    let origin = server.uri();
    // Spend one second in real ordinary HTTP discovery. A freshly granted five
    // seconds after this point would incorrectly admit the delayed challenge.
    Mock::given(method("GET"))
        .and(path("/mcp"))
        .respond_with(ResponseTemplate::new(404).set_delay(Duration::from_secs(1)))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .and(body_partial_json(json!({"method": "initialize"})))
        .respond_with(
            ResponseTemplate::new(401)
                .insert_header(
                    "www-authenticate",
                    format!("Bearer resource_metadata=\"{origin}/too-late\""),
                )
                .set_delay(Duration::from_millis(4_500)),
        )
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(path("/too-late"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "resource": format!("{origin}/mcp"),
            "authorization_servers": [format!("{origin}/issuer")],
        })))
        .expect(0)
        .mount(&server)
        .await;
    Mock::given(path("/.well-known/oauth-authorization-server/issuer"))
        .respond_with(ResponseTemplate::new(200).set_body_json(metadata(&origin)))
        .expect(0)
        .mount(&server)
        .await;
    let (manager, adapter, client) = context(&server).await;
    let started = Instant::now();
    let result = tokio::time::timeout(
        Duration::from_secs(6),
        resolve_metadata_with_mcp_challenge(
            &manager,
            &adapter,
            &format!("{origin}/mcp"),
            McpProtocolMode::Legacy,
            started + Duration::from_secs(30),
        ),
    )
    .await
    .expect("the complete discovery chain must finish within its original five-second budget");
    result.expect_err("ordinary discovery cannot grant the POST probe a fresh five seconds");
    assert!(started.elapsed() >= Duration::from_millis(4_500));
    client.assert_original_capability(&origin, "initialize");
    {
        let requests = client.requests.lock().expect("request recorder lock");
        let post = requests
            .iter()
            .find(|request| request.method == "POST" && request.url == format!("{origin}/mcp"))
            .expect("the actual probe was attempted after ordinary discovery");
        assert!(
            post.timeout_ms
                .is_some_and(|timeout| timeout > 0 && timeout <= 4_000),
            "POST receives only the remaining original budget: {:?}",
            post.timeout_ms,
        );
    }
    server.verify().await;
}

#[tokio::test]
async fn successful_unprotected_probe_awaits_service_cleanup() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .and(body_partial_json(json!({"method": "initialize"})))
        .respond_with(|request: &wiremock::Request| {
            let message: serde_json::Value =
                serde_json::from_slice(&request.body).expect("actual initialize JSON");
            ResponseTemplate::new(200).set_body_json(json!({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "serverInfo": {"name": "unprotected-probe", "version": "1"},
                },
            }))
        })
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .and(body_partial_json(
            json!({"method": "notifications/initialized"}),
        ))
        .respond_with(ResponseTemplate::new(202))
        .expect(1)
        .mount(&server)
        .await;
    let (_, adapter, client) = context(&server).await;
    let challenge = tokio::time::timeout(
        Duration::from_secs(2),
        observe_mcp_challenge(
            adapter.mcp_probe_context(),
            &format!("{}/mcp", server.uri()),
            McpProtocolMode::Legacy,
            Instant::now() + Duration::from_secs(2),
        ),
    )
    .await
    .expect("service cleanup must use the same finite probe budget")
    .expect("an unprotected server may complete and close without a challenge");
    assert_eq!(challenge, None);
    assert_eq!(client.ordinary_requests.load(Ordering::SeqCst), 0);
    assert!(
        client
            .requests
            .lock()
            .expect("request recorder lock")
            .iter()
            .all(|request| { request.resource_origin == server.uri() })
    );
    server.verify().await;
}
