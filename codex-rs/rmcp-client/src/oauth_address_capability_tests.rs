use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_exec_server::ExecServerError;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::HttpResponseBodyStream;
use futures::future::BoxFuture;
use pretty_assertions::assert_eq;

use super::*;

#[derive(Default)]
struct RecordingRestrictedCapability {
    requests: Mutex<Vec<HttpRequestRestrictedParams>>,
}

impl HttpClient for RecordingRestrictedCapability {
    fn http_request(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        panic!("OAuth must not use buffered unrestricted HTTP")
    }
    fn http_request_stream(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        panic!("OAuth must not use unrestricted HTTP")
    }
    fn http_request_stream_restricted(
        &self,
        params: HttpRequestRestrictedParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.requests.lock().expect("recording lock").push(params);
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "recorded without network".to_string(),
            ))
        })
    }
}

#[tokio::test]
async fn oauth_capability_always_carries_original_configured_origin_and_keeps_header_scoping() {
    let recorder = Arc::new(RecordingRestrictedCapability::default());
    let mut headers = HeaderMap::new();
    headers.insert("x-resource-key", HeaderValue::from_static("resource-only"));
    let adapter =
        OAuthHttpClientAdapter::new(recorder.clone(), headers, "https://resource.example/mcp");
    for url in [
        "https://resource.example/metadata",
        "https://issuer.example/metadata",
    ] {
        assert!(
            adapter
                .execute_request(
                    oauth2::http::Request::builder()
                        .uri(url)
                        .body(Vec::new())
                        .unwrap(),
                    OAuthHttpRedirectPolicy::Stop,
                    /*timeout*/ None
                )
                .await
                .is_err()
        );
    }
    let observed = recorder
        .requests
        .lock()
        .unwrap()
        .iter()
        .map(|request| {
            (
                request.configured_resource_origin.clone(),
                request.request.url.clone(),
                request
                    .request
                    .headers
                    .iter()
                    .find(|header| header.name == "x-resource-key")
                    .map(|header| header.value.clone()),
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(
        observed,
        vec![
            (
                "https://resource.example".to_string(),
                "https://resource.example/metadata".to_string(),
                Some("resource-only".to_string())
            ),
            (
                "https://resource.example".to_string(),
                "https://issuer.example/metadata".to_string(),
                None
            ),
        ]
    );
}

#[derive(Default)]
struct OrdinaryOnly(AtomicUsize);

impl HttpClient for OrdinaryOnly {
    fn http_request(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "ordinary method invoked".to_string(),
            ))
        })
    }
    fn http_request_stream(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "ordinary stream invoked".to_string(),
            ))
        })
    }
}

#[tokio::test]
async fn missing_restricted_capability_rejects_without_invoking_ordinary_http() {
    let client = Arc::new(OrdinaryOnly::default());
    let adapter = OAuthHttpClientAdapter::new(
        client.clone(),
        HeaderMap::new(),
        "https://resource.example/mcp",
    );
    let result = adapter
        .execute_request(
            oauth2::http::Request::builder()
                .uri("https://issuer.example/token")
                .body(Vec::new())
                .unwrap(),
            OAuthHttpRedirectPolicy::Stop,
            /*timeout*/ None,
        )
        .await;
    assert!(
        matches!(result, Err(error) if error.to_string().contains("does not support restricted"))
    );
    assert_eq!(client.0.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn protocol_fixture_cannot_expand_resource_method_path_or_query() {
    let server = wiremock::MockServer::start().await;
    let resource = format!("{}/mcp", server.uri());
    let endpoint = format!("{}/metadata", server.uri());
    let client = crate::oauth_fixture_capability::fixture_http_client(
        &resource,
        &[("GET", endpoint.clone())],
    );
    for (method, url, origin) in [
        ("GET", endpoint.clone(), "http://localhost".to_string()),
        ("POST", endpoint.clone(), server.uri()),
        ("GET", format!("{}/token", server.uri()), server.uri()),
        ("GET", format!("{endpoint}?extra=1"), server.uri()),
    ] {
        let result = client
            .http_request_stream_restricted(HttpRequestRestrictedParams {
                configured_resource_origin: origin,
                request: HttpRequestParams {
                    method: method.to_string(),
                    url,
                    headers: Vec::new(),
                    body: None,
                    timeout_ms: Some(1000),
                    redirect_policy: HttpRedirectPolicy::Stop,
                    request_id: "fixture-refusal".to_string(),
                    stream_response: true,
                },
            })
            .await;
        assert!(matches!(result, Err(error) if error.to_string().contains("OAuth fixture")));
    }
    assert!(
        server
            .received_requests()
            .await
            .expect("recorded fixture traffic")
            .is_empty()
    );
}
