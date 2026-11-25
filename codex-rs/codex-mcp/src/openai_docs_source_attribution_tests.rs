use std::sync::Arc;
use std::sync::Mutex;

use codex_exec_server::ExecServerError;
use codex_exec_server::HttpClient;
use codex_exec_server::HttpRedirectPolicy;
use codex_exec_server::HttpRequestParams;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::HttpRequestRestrictedParams;
use codex_exec_server::HttpResponseBodyStream;
use futures::FutureExt;
use futures::future::BoxFuture;
use pretty_assertions::assert_eq;

use super::OPENAI_DEVELOPER_DOCS_MCP_CODEX_URL;
use super::OPENAI_DEVELOPER_DOCS_MCP_URL;
use super::maybe_with_openai_docs_source_attribution;

#[derive(Default)]
struct RecordingHttpClient {
    urls: Mutex<Vec<String>>,
    restricted: Mutex<Vec<HttpRequestRestrictedParams>>,
}

impl HttpClient for RecordingHttpClient {
    fn http_request_stream_restricted(
        &self,
        params: HttpRequestRestrictedParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.restricted.lock().unwrap().push(params);
        async { Err(ExecServerError::HttpRequest("test response".to_string())) }.boxed()
    }

    fn http_request(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        self.urls.lock().unwrap().push(params.url);
        async { Err(ExecServerError::HttpRequest("test response".to_string())) }.boxed()
    }

    fn http_request_stream(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.urls.lock().unwrap().push(params.url);
        async { Err(ExecServerError::HttpRequest("test response".to_string())) }.boxed()
    }
}

fn request(url: &str) -> HttpRequestParams {
    HttpRequestParams {
        method: "POST".to_string(),
        url: url.to_string(),
        headers: Vec::new(),
        body: None,
        timeout_ms: None,
        redirect_policy: HttpRedirectPolicy::Follow,
        request_id: "test-request".to_string(),
        stream_response: true,
    }
}

#[tokio::test]
async fn attributes_only_docs_mcp_requests() {
    let recording_client = Arc::new(RecordingHttpClient::default());
    let http_client = maybe_with_openai_docs_source_attribution(
        OPENAI_DEVELOPER_DOCS_MCP_URL,
        recording_client.clone(),
    );

    let _ = http_client
        .http_request_stream(request(OPENAI_DEVELOPER_DOCS_MCP_URL))
        .await;
    let _ = http_client
        .http_request(request(
            "https://developers.openai.com/.well-known/oauth-protected-resource/mcp",
        ))
        .await;

    assert_eq!(
        recording_client.urls.lock().unwrap().as_slice(),
        [
            OPENAI_DEVELOPER_DOCS_MCP_CODEX_URL,
            "https://developers.openai.com/.well-known/oauth-protected-resource/mcp",
        ]
    );
}

#[test]
fn leaves_other_mcp_clients_unwrapped() {
    let recording_client = Arc::new(RecordingHttpClient::default());
    let http_client = maybe_with_openai_docs_source_attribution(
        "https://example.com/mcp",
        recording_client.clone(),
    );

    assert!(Arc::ptr_eq(
        &http_client,
        &(recording_client as Arc<dyn HttpClient>)
    ));
}

#[tokio::test]
async fn restricted_docs_attribution_preserves_original_resource_capability() {
    let recording_client = Arc::new(RecordingHttpClient::default());
    let http_client = maybe_with_openai_docs_source_attribution(
        OPENAI_DEVELOPER_DOCS_MCP_URL,
        recording_client.clone(),
    );
    let original_origin = "https://developers.openai.com";
    let mut expected = Vec::new();
    for url in [
        OPENAI_DEVELOPER_DOCS_MCP_URL,
        "https://developers.openai.com/.well-known/oauth-protected-resource/mcp",
        "https://issuer.example/token",
    ] {
        let mut params = HttpRequestRestrictedParams {
            request: request(url),
            configured_resource_origin: original_origin.to_string(),
        };
        params.request.timeout_ms = Some(1234);
        params.request.redirect_policy = HttpRedirectPolicy::Stop;
        let _ = http_client
            .http_request_stream_restricted(params.clone())
            .await;
        if url == OPENAI_DEVELOPER_DOCS_MCP_URL {
            params.request.url = OPENAI_DEVELOPER_DOCS_MCP_CODEX_URL.to_string();
        }
        expected.push(params);
    }
    assert_eq!(*recording_client.restricted.lock().unwrap(), expected);
    assert!(recording_client.urls.lock().unwrap().is_empty());
}
