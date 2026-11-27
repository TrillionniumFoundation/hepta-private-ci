use super::*;

#[path = "oauth_authorization_revocation_tests.rs"]
mod revocation_tests;

use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_exec_server::HttpRedirectPolicy;
use codex_exec_server::RouteAwareHttpClient;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;
use pretty_assertions::assert_eq;
use rmcp::transport::AuthorizationManager;
use rmcp::transport::auth::AuthError;
use rmcp::transport::auth::AuthorizationMetadataSource;
use serde_json::json;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_partial_json;
use wiremock::matchers::method;
use wiremock::matchers::path;

use crate::http_client_adapter::StreamableHttpRedirectMode;
use crate::oauth_http_client::OAuthHttpClientAdapter;
use crate::oauth_reactive_discovery::resolve_metadata_with_mcp_challenge;
use crate::protocol_mode::McpProtocolMode;

#[derive(Default)]
struct RecordingClient {
    restricted: Mutex<Vec<HttpRequestRestrictedParams>>,
    ordinary: AtomicUsize,
    once: AtomicUsize,
}

impl HttpClient for RecordingClient {
    fn http_request_stream_restricted(
        &self,
        params: HttpRequestRestrictedParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.restricted.lock().unwrap().push(params);
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "recorded restricted request".to_string(),
            ))
        })
    }

    fn supports_single_attempt_requests(&self) -> bool {
        true
    }

    fn http_request_stream_once(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.once.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "recorded single attempt".to_string(),
            ))
        })
    }

    fn http_request(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        self.ordinary.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "recorded ordinary request".to_string(),
            ))
        })
    }

    fn http_request_stream(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.ordinary.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "recorded ordinary stream".to_string(),
            ))
        })
    }
}

fn request() -> HttpRequestRestrictedParams {
    HttpRequestRestrictedParams {
        request: HttpRequestParams {
            method: "GET".to_string(),
            url: "http://localhost:8383/metadata".to_string(),
            headers: Vec::new(),
            body: None,
            timeout_ms: Some(1234),
            redirect_policy: HttpRedirectPolicy::Stop,
            request_id: "owner-origin-request".to_string(),
            stream_response: true,
        },
        configured_resource_origin: "http://localhost:8181".to_string(),
        authorization_origins: Default::default(),
    }
}

#[test]
fn empty_owner_grants_preserve_the_original_transport_identity() {
    let original: Arc<dyn HttpClient> = Arc::new(RecordingClient::default());
    let wrapped = with_oauth_authorization_origins(
        original.clone(),
        "http://localhost:8181/mcp",
        OAuthAuthorizationOrigins::default(),
    )
    .unwrap();
    assert!(Arc::ptr_eq(&original, &wrapped));
}

#[tokio::test]
async fn owner_grants_bind_exact_resource_and_reject_caller_supplied_grants_before_io() {
    let original = Arc::new(RecordingClient::default());
    let origins =
        OAuthAuthorizationOrigins::new(vec!["http://localhost:8383".to_string()]).unwrap();
    let wrapped = with_oauth_authorization_origins(
        original.clone(),
        "http://localhost:8181/mcp",
        origins.clone(),
    )
    .unwrap();
    let expected = request();
    let _ = wrapped
        .http_request_stream_restricted(expected.clone())
        .await;
    let seen = original.restricted.lock().unwrap().clone();
    assert_eq!(seen.len(), 1);
    assert_eq!(seen[0].request, expected.request);
    assert_eq!(
        seen[0].configured_resource_origin,
        expected.configured_resource_origin
    );
    assert_eq!(seen[0].authorization_origins, origins);

    let mut rebound = request();
    rebound.configured_resource_origin = "http://localhost:8383".to_string();
    let mut injected = request();
    injected.authorization_origins =
        OAuthAuthorizationOrigins::new(vec!["http://localhost:8585".to_string()]).unwrap();
    for invalid in [rebound, injected] {
        assert!(matches!(
            wrapped.http_request_stream_restricted(invalid).await,
            Err(ExecServerError::HttpRequest(message))
                if message == "OAuth request does not match its owner-bound address capability"
        ));
    }
    assert_eq!(original.restricted.lock().unwrap().len(), 1);
    assert_eq!(original.ordinary.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn owner_grant_wrapper_preserves_single_attempt_capability_and_other_methods() {
    let original = Arc::new(RecordingClient::default());
    let wrapped = with_oauth_authorization_origins(
        original.clone(),
        "http://localhost:8181/mcp",
        OAuthAuthorizationOrigins::new(vec!["http://localhost:8383".to_string()]).unwrap(),
    )
    .unwrap();
    assert!(wrapped.supports_single_attempt_requests());
    let _ = wrapped.http_request_stream_once(request().request).await;
    let _ = wrapped.http_request(request().request).await;
    let _ = wrapped.http_request_stream(request().request).await;
    assert_eq!(original.once.load(Ordering::SeqCst), 1);
    assert_eq!(original.ordinary.load(Ordering::SeqCst), 2);
    assert!(original.restricted.lock().unwrap().is_empty());
}

async fn context(
    resource: &MockServer,
    origins: OAuthAuthorizationOrigins,
) -> (AuthorizationManager, Arc<OAuthHttpClientAdapter>) {
    let resource_url = format!("{}/mcp", resource.uri());
    let route = Arc::new(RouteAwareHttpClient::new(HttpClientFactory::new(
        OutboundProxyPolicy::ReqwestDefault,
    )));
    let client = with_oauth_authorization_origins(route, &resource_url, origins).unwrap();
    let adapter = Arc::new(
        OAuthHttpClientAdapter::new_with_redirect_mode(
            client,
            HeaderMap::from_iter([(
                HeaderName::from_static("x-configured-resource"),
                HeaderValue::from_static("owner-secret"),
            )]),
            &resource_url,
            /*has_configured_headers*/ true,
            StreamableHttpRedirectMode::Legacy,
        )
        .unwrap(),
    );
    let manager = AuthorizationManager::new_with_oauth_http_client(resource_url, adapter.clone())
        .await
        .unwrap();
    (manager, adapter)
}

async fn authorization_metadata(server: &MockServer) {
    Mock::given(method("GET"))
        .and(path("/.well-known/oauth-authorization-server"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "issuer": server.uri(),
            "authorization_endpoint": format!("{}/authorize", server.uri()),
            "token_endpoint": format!("{}/token", server.uri()),
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"]
        })))
        .expect(1)
        .mount(server)
        .await;
}

async fn protected_resource_metadata(resource: &MockServer, authorization: &MockServer, at: &str) {
    Mock::given(method("GET"))
        .and(path(at))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "resource": format!("{}/mcp", resource.uri()),
            "authorization_servers": [authorization.uri()]
        })))
        .expect(1)
        .mount(resource)
        .await;
}

#[tokio::test]
async fn actual_discovery_denies_ungranted_authorization_origin_without_http_delivery() {
    let resource = MockServer::start().await;
    let authorization = MockServer::start().await;
    protected_resource_metadata(
        &resource,
        &authorization,
        "/.well-known/oauth-protected-resource/mcp",
    )
    .await;
    let (manager, _) = context(&resource, OAuthAuthorizationOrigins::default()).await;
    let result = tokio::time::timeout(Duration::from_secs(2), manager.resolve_metadata())
        .await
        .unwrap();
    assert!(matches!(
        result,
        Err(AuthError::DiscoveryRequestFailed { url, source })
            if url.as_str() == format!("{}/.well-known/oauth-authorization-server", authorization.uri())
                && matches!(
                    source.downcast_ref::<ExecServerError>(),
                    Some(ExecServerError::HttpRequest(message)) if message.contains("address capability")
                )
    ));
    assert!(authorization.received_requests().await.unwrap().is_empty());
}

#[tokio::test]
async fn actual_discovery_uses_explicit_owner_origin_without_forwarding_resource_headers() {
    let resource = MockServer::start().await;
    let authorization = MockServer::start().await;
    protected_resource_metadata(
        &resource,
        &authorization,
        "/.well-known/oauth-protected-resource/mcp",
    )
    .await;
    authorization_metadata(&authorization).await;
    let origins = OAuthAuthorizationOrigins::new(vec![authorization.uri()]).unwrap();
    let (manager, _) = context(&resource, origins).await;
    let result = tokio::time::timeout(Duration::from_secs(2), manager.resolve_metadata())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        result.source,
        AuthorizationMetadataSource::ProtectedResourceMetadata
    );
    assert_eq!(
        result.metadata.issuer.as_deref(),
        Some(authorization.uri().as_str())
    );
    let requests = authorization.received_requests().await.unwrap();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].headers.get("x-configured-resource").is_none());
    assert!(requests[0].headers.get("authorization").is_none());
    let resource_requests = resource.received_requests().await.unwrap();
    assert!(
        resource_requests
            .iter()
            .all(|request| request.headers.get("x-configured-resource").is_some())
    );
}

#[tokio::test]
async fn actual_reactive_challenge_preserves_owner_grants_and_resource_header_boundary() {
    let resource = MockServer::start().await;
    let authorization = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .and(body_partial_json(json!({"method": "initialize"})))
        .respond_with(ResponseTemplate::new(401).insert_header(
            "www-authenticate",
            format!(
                "Bearer resource_metadata=\"{}/owner-metadata\"",
                resource.uri()
            ),
        ))
        .expect(1)
        .mount(&resource)
        .await;
    protected_resource_metadata(&resource, &authorization, "/owner-metadata").await;
    authorization_metadata(&authorization).await;
    let origins = OAuthAuthorizationOrigins::new(vec![authorization.uri()]).unwrap();
    let (manager, adapter) = context(&resource, origins).await;
    let result = resolve_metadata_with_mcp_challenge(
        &manager,
        &adapter,
        &format!("{}/mcp", resource.uri()),
        McpProtocolMode::Legacy,
        Instant::now() + Duration::from_secs(2),
    )
    .await
    .unwrap();
    assert_eq!(
        result.source,
        AuthorizationMetadataSource::ProtectedResourceMetadata
    );
    assert_eq!(
        result.metadata.issuer.as_deref(),
        Some(authorization.uri().as_str())
    );
    let requests = authorization.received_requests().await.unwrap();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].headers.get("x-configured-resource").is_none());
    let resource_requests = resource.received_requests().await.unwrap();
    let posts = resource_requests
        .iter()
        .filter(|request| request.method.as_str() == "POST")
        .collect::<Vec<_>>();
    assert_eq!(posts.len(), 1);
    assert!(posts[0].headers.get("x-configured-resource").is_some());
}
