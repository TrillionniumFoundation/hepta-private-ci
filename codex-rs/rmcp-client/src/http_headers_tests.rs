use super::*;
use pretty_assertions::assert_eq;

#[test]
fn helper_output_errors_do_not_echo_secrets() {
    for output in [
        br#"{"Authorization":"secret"}"#.as_slice(),
        br#"{"secret":"secret","secret":"secret"}"#.as_slice(),
        br#"{"secret":"secret","Secret":"secret"}"#.as_slice(),
    ] {
        let error = parse_helper_output(output.to_vec()).expect_err("invalid helper output");
        assert!(!error.to_string().contains("secret"));
    }
}

#[cfg(unix)]
#[tokio::test]
async fn helper_attempt_is_shared_after_cancellation() {
    use tempfile::tempdir;

    let temp = tempdir().expect("temporary helper directory");
    let cwd = temp
        .path()
        .canonicalize()
        .expect("canonical helper directory");
    let cancelled_invocations = cwd.join("cancelled-invocations");
    let cancelled = HttpHeadersProvider::new(
        "https://example.com",
        &format!(
            "test \"$(pwd)\" = '{0}'; test -n \"$HOME\"; test -n \"$PATH\"; \
             printf x >> '{1}'; sleep 0.2; printf '{{\"X-Gateway\":\"token\"}}'",
            cwd.display(),
            cancelled_invocations.display(),
        ),
        cwd.clone(),
    )
    .expect("cancelled provider");
    assert!(
        tokio::time::timeout(Duration::from_millis(20), cancelled.headers())
            .await
            .is_err()
    );
    assert!(cancelled.headers().await.is_ok());
    assert_eq!(
        std::fs::read_to_string(cancelled_invocations).expect("cancelled invocation count"),
        "x"
    );

    let dropped_started = cwd.join("dropped-helper-started");
    let dropped_finished = cwd.join("dropped-helper-finished");
    let dropped = HttpHeadersProvider::new(
        "https://example.com",
        &format!(
            "printf x > '{}'; sleep 1; printf x > '{}'",
            dropped_started.display(),
            dropped_finished.display(),
        ),
        cwd,
    )
    .expect("dropped provider");
    assert!(
        tokio::time::timeout(Duration::from_millis(500), dropped.headers())
            .await
            .is_err()
    );
    assert!(dropped_started.exists());
    drop(dropped);
    tokio::time::sleep(Duration::from_millis(1_100)).await;
    assert!(!dropped_finished.exists());
}

#[tokio::test]
async fn nonzero_helper_exit_is_cached() {
    let temp = tempfile::tempdir().expect("temporary helper directory");
    let failed_invocations = temp.path().join("failed-invocations");
    let command = if cfg!(windows) {
        format!(
            r#"echo x>>"{0}" & echo {{"X-Gateway":"valid"}} & exit /b 23"#,
            failed_invocations.display()
        )
    } else {
        format!(
            "echo x >> '{0}'; printf '{{\"X-Gateway\":\"valid\"}}'; exit 23",
            failed_invocations.display()
        )
    };
    let failed = HttpHeadersProvider::new(
        "https://example.com/mcp",
        &command,
        temp.path().to_path_buf(),
    )
    .expect("failed provider");
    let first = failed.headers().await.expect_err("failed helper");
    let second = failed.headers().await.expect_err("cached failure");
    assert_eq!(first.to_string(), second.to_string());
    let invocations = std::fs::read_to_string(failed_invocations).expect("failed invocation count");
    assert_eq!(invocations.lines().count(), 1);
}

#[cfg(unix)]
#[tokio::test]
async fn connection_headers_are_cached_and_origin_bound() {
    use axum::Router;
    use axum::http::StatusCode;
    use axum::response::Redirect;
    use axum::routing::get;
    use axum::routing::post;
    use codex_exec_server::RouteAwareHttpClient;
    use codex_http_client::HttpClientFactory;
    use codex_http_client::OutboundProxyPolicy;
    use std::sync::Arc;
    use tempfile::tempdir;
    use tokio::net::TcpListener;

    async fn handle(headers: axum::http::HeaderMap) -> StatusCode {
        assert_eq!(
            headers.get("proxy-authorization"),
            Some(&HeaderValue::from_static("Bearer token"))
        );
        assert_eq!(
            headers.get("x-label"),
            Some(&HeaderValue::from_bytes("café".as_bytes()).unwrap())
        );
        StatusCode::NO_CONTENT
    }
    let temp = tempdir().expect("temporary helper directory");
    let invocation_file = temp.path().join("invocations");
    let cross_listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind cross-origin server");
    let cross_url = format!("http://{}/start", cross_listener.local_addr().unwrap());
    tokio::spawn(async move {
        axum::serve(
            cross_listener,
            Router::new()
                .route("/start", get(|| async { Redirect::temporary("/final") }))
                .route("/final", get(|| async { StatusCode::NO_CONTENT })),
        )
        .await
        .expect("serve cross-origin requests");
    });
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind test server");
    let url = format!("http://{}/mcp", listener.local_addr().unwrap());
    let redirect_url = cross_url.clone();
    let app = Router::new().route("/mcp", post(handle)).route(
        "/redirect",
        get(move || std::future::ready(Redirect::temporary(&redirect_url))),
    );
    tokio::spawn(async move {
        axum::serve(listener, app)
            .await
            .expect("serve test requests");
    });
    let command = format!(
        "printf x >> '{}'; printf '{{\"Proxy-Authorization\":\"Bearer token\",\"X-Label\":\"café\"}}'",
        invocation_file.display(),
    );
    let inner: Arc<dyn HttpClient> = Arc::new(RouteAwareHttpClient::new(HttpClientFactory::new(
        OutboundProxyPolicy::ReqwestDefault,
    )));
    let client = with_http_headers_helper(inner, &url, &command, temp.path().to_path_buf())
        .expect("headers helper client");
    let request = |session: &str| HttpRequestParams {
        method: "POST".to_string(),
        url: url.clone(),
        headers: Vec::new(),
        body: None,
        timeout_ms: Some(5_000),
        redirect_policy: HttpRedirectPolicy::Follow,
        request_id: session.to_string(),
        stream_response: true,
    };
    let mut cross_request = request("cross-origin");
    cross_request.method = "GET".to_string();
    cross_request.url = cross_url;
    assert_eq!(
        client.http_request(cross_request).await.unwrap().status,
        204
    );
    assert!(!invocation_file.exists());
    let mut redirect_request = request("redirect");
    redirect_request.method = "GET".to_string();
    redirect_request.url = url.replace("/mcp", "/redirect");
    assert_eq!(
        client.http_request(redirect_request).await.unwrap().status,
        307
    );
    let (left, right) = tokio::join!(
        client.http_request_stream(request("session-a")),
        client.http_request_stream(request("session-b"))
    );
    assert_eq!(left.expect("left request").0.status, 204);
    assert_eq!(right.expect("right request").0.status, 204);
    assert_eq!(
        std::fs::read_to_string(&invocation_file).expect("helper invocation count"),
        "x"
    );
}

#[tokio::test]
async fn explicit_oauth_grant_does_not_extend_helper_or_resource_credential_scope() {
    use codex_exec_server::RouteAwareHttpClient;
    use codex_http_client::HttpClientFactory;
    use codex_http_client::OutboundProxyPolicy;
    use codex_protocol::OAuthAuthorizationOrigins;
    use rmcp::transport::AuthorizationManager;
    use serde_json::json;
    use wiremock::Mock;
    use wiremock::MockServer;
    use wiremock::ResponseTemplate;
    use wiremock::matchers::method;
    use wiremock::matchers::path;

    use crate::http_client_adapter::StreamableHttpRedirectMode;
    use crate::oauth_authorization_http_client::with_oauth_authorization_origins;
    use crate::oauth_http_client::OAuthHttpClientAdapter;

    let resource = MockServer::start().await;
    let authorization = MockServer::start().await;
    let resource_url = format!("{}/mcp", resource.uri());
    // rmcp probes the resource before fetching protected resource metadata.
    Mock::given(method("GET"))
        .and(path("/mcp"))
        .respond_with(ResponseTemplate::new(404))
        .expect(1)
        .mount(&resource)
        .await;
    Mock::given(method("GET"))
        .and(path("/.well-known/oauth-protected-resource/mcp"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "resource": resource_url,
            "authorization_servers": [authorization.uri()]
        })))
        .expect(1)
        .mount(&resource)
        .await;
    Mock::given(method("GET"))
        .and(path("/.well-known/oauth-authorization-server"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "issuer": authorization.uri(),
            "authorization_endpoint": format!("{}/authorize", authorization.uri()),
            "token_endpoint": format!("{}/token", authorization.uri())
        })))
        .expect(1)
        .mount(&authorization)
        .await;
    let helper_headers = Arc::new(
        parse_helper_output(
            br#"{"X-Helper":"helper-secret","Proxy-Authorization":"Basic proxy-secret"}"#.to_vec(),
        )
        .unwrap(),
    );
    let provider = HttpHeadersProvider {
        server_origin: Url::parse(&resource_url).unwrap().origin(),
        cached: futures::future::ready(Ok::<_, Arc<str>>(helper_headers))
            .boxed()
            .shared(),
    };
    let route = Arc::new(RouteAwareHttpClient::new(HttpClientFactory::new(
        OutboundProxyPolicy::ReqwestDefault,
    )));
    let helper = Arc::new(HttpHeadersClient {
        inner: route,
        provider,
    });
    let client = with_oauth_authorization_origins(
        helper,
        &resource_url,
        OAuthAuthorizationOrigins::new(vec![authorization.uri()]).unwrap(),
    )
    .unwrap();
    let adapter = Arc::new(
        OAuthHttpClientAdapter::new_with_redirect_mode(
            client,
            HeaderMap::from_iter([
                (
                    HeaderName::from_static("authorization"),
                    HeaderValue::from_static("Bearer resource-secret"),
                ),
                (
                    HeaderName::from_static("x-resource-secret"),
                    HeaderValue::from_static("resource-custom-secret"),
                ),
            ]),
            &resource_url,
            /*has_configured_headers*/ true,
            StreamableHttpRedirectMode::Legacy,
        )
        .unwrap(),
    );
    let manager = AuthorizationManager::new_with_oauth_http_client(resource_url, adapter)
        .await
        .unwrap();
    let result = tokio::time::timeout(Duration::from_secs(2), manager.resolve_metadata())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        result.metadata.issuer.as_deref(),
        Some(authorization.uri().as_str())
    );
    let authorized = authorization.received_requests().await.unwrap();
    assert_eq!(authorized.len(), 1);
    for header in [
        "authorization",
        "proxy-authorization",
        "x-helper",
        "x-resource-secret",
    ] {
        assert!(authorized[0].headers.get(header).is_none(), "{header}");
    }
    let (probes, original): (Vec<_>, Vec<_>) = resource
        .received_requests()
        .await
        .unwrap()
        .into_iter()
        .partition(|request| request.url.path() == "/mcp");
    assert_eq!(probes.len(), 1);
    assert_eq!(probes[0].method.as_str(), "GET");
    assert_eq!(
        original
            .iter()
            .map(|request| (request.method.as_str(), request.url.path()))
            .collect::<Vec<_>>(),
        vec![("GET", "/.well-known/oauth-protected-resource/mcp")]
    );
    for (header, expected) in [
        ("authorization", "Bearer resource-secret"),
        ("proxy-authorization", "Basic proxy-secret"),
        ("x-helper", "helper-secret"),
        ("x-resource-secret", "resource-custom-secret"),
    ] {
        assert_eq!(probes[0].headers[header], expected);
    }
    assert_eq!(original.len(), 1);
    assert_eq!(
        original[0].headers["authorization"],
        "Bearer resource-secret"
    );
    assert_eq!(
        original[0].headers["proxy-authorization"],
        "Basic proxy-secret"
    );
    assert_eq!(original[0].headers["x-helper"], "helper-secret");
    assert_eq!(
        original[0].headers["x-resource-secret"],
        "resource-custom-secret"
    );
}
