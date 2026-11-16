use super::AuthRequestTelemetryContext;
use super::PendingUnauthorizedRetry;
use super::create_model_provider;
use super::create_oss_provider_with_base_url;
use super::test_model_client;
use super::test_responses_metadata_for_client;
use super::test_session_telemetry;
use crate::client::WebsocketAuthSnapshot;
use crate::test_support::TestCodexResponsesRequestKind;
use codex_api::AuthProvider;
use codex_model_provider_info::WireApi;
use codex_protocol::protocol::SessionSource;
use futures::StreamExt;
use http::HeaderMap;
use http::HeaderValue;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[derive(Default)]
struct CountingAuth {
    headers: Mutex<HeaderMap>,
    calls: AtomicUsize,
}

impl AuthProvider for CountingAuth {
    fn add_auth_headers(&self, headers: &mut HeaderMap) {
        self.calls.fetch_add(1, Ordering::SeqCst);
        headers.extend(self.headers.lock().unwrap().clone());
    }
}

#[test]
fn websocket_auth_snapshot_freezes_all_headers_and_redacts_debug() {
    let auth = CountingAuth::default();
    auth.headers.lock().unwrap().insert(
        "authorization",
        HeaderValue::from_static("Bearer auth-snapshot-secret-a"),
    );
    let snapshot = WebsocketAuthSnapshot::capture(&auth);
    auth.headers.lock().unwrap().insert(
        "authorization",
        HeaderValue::from_static("Bearer auth-snapshot-secret-b"),
    );
    let mut wire_headers = HeaderMap::new();
    wire_headers.insert("authorization", HeaderValue::from_static("stale-provider"));
    snapshot.add_auth_headers(&mut wire_headers);
    assert_eq!(
        wire_headers["authorization"],
        "Bearer auth-snapshot-secret-a"
    );
    assert_eq!(auth.calls.load(Ordering::SeqCst), 1);
    assert!(!format!("{snapshot:?}").contains("auth-snapshot-secret"));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn websocket_reconnects_for_actual_auth_route_and_unknown_boundaries() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind websocket server");
    let base_url = format!("http://{}/v1", listener.local_addr().unwrap());
    let handshakes = Arc::new(Mutex::new(Vec::new()));
    let server_handshakes = Arc::clone(&handshakes);
    let server = tokio::spawn(async move {
        let mut connections = tokio::task::JoinSet::new();
        loop {
            let (tcp, _) = listener
                .accept()
                .await
                .expect("accept websocket connection");
            let handshakes = Arc::clone(&server_handshakes);
            connections.spawn(async move {
                let mut socket = tokio_tungstenite::accept_hdr_async_with_config(
                    tcp,
                    move |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
                          response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                        handshakes.lock().unwrap().push((request.headers().clone(), request.uri().to_string()));
                        Ok(response)
                    },
                    Some(tokio_tungstenite::tungstenite::protocol::WebSocketConfig::default()),
                )
                .await
                .expect("websocket handshake");
                while socket.next().await.is_some() {}
            });
        }
    });
    let mut provider = create_oss_provider_with_base_url(&base_url, WireApi::Responses);
    provider.supports_websockets = true;
    provider.websocket_connect_timeout_ms = Some(5_000);
    let mut client = test_model_client(SessionSource::Exec);
    Arc::get_mut(&mut client.state)
        .expect("client state is unique")
        .provider = create_model_provider(provider, None);
    let setup = client.current_client_setup().await.expect("client setup");
    let mut api_provider = setup.api_provider;
    let telemetry = test_session_telemetry();
    let mut session = client.new_session();
    let mut metadata = test_responses_metadata_for_client(
        &client,
        Some("turn-a"),
        "window-a".to_string(),
        None,
        TestCodexResponsesRequestKind::Turn,
    );
    let auth = Arc::new(CountingAuth::default());
    auth.headers.lock().unwrap().extend([
        (
            http::header::AUTHORIZATION,
            HeaderValue::from_static("Bearer auth-snapshot-secret-a"),
        ),
        (
            http::HeaderName::from_static("chatgpt-account-id"),
            HeaderValue::from_static("account-a"),
        ),
        (
            http::HeaderName::from_static("x-openai-tenant"),
            HeaderValue::from_static("tenant-a"),
        ),
    ]);
    for (change, expected) in [
        ("initial", 1),
        ("unchanged", 1),
        ("token", 2),
        ("account", 3),
        ("tenant", 4),
        ("auth-route", 5),
        ("unknown-auth", 6),
        ("unknown-caller-extra", 7),
        ("endpoint", 8),
        ("query", 9),
        ("unknown-provider", 10),
        ("removed-auth", 11),
    ] {
        {
            let mut headers = auth.headers.lock().unwrap();
            match change {
                "token" => {
                    headers.insert(
                        "authorization",
                        HeaderValue::from_static("Bearer auth-snapshot-secret-b"),
                    );
                }
                "account" => {
                    headers.insert("chatgpt-account-id", HeaderValue::from_static("account-b"));
                }
                "tenant" => {
                    headers.insert("x-openai-tenant", HeaderValue::from_static("tenant-b"));
                }
                "auth-route" => {
                    headers.insert(
                        "x-codex-routing-hint",
                        HeaderValue::from_static("auth-route-b"),
                    );
                }
                "unknown-auth" => {
                    headers.insert(
                        "x-future-auth-boundary",
                        HeaderValue::from_static("future-b"),
                    );
                }
                "removed-auth" => {
                    headers.remove("x-future-auth-boundary");
                }
                _ => {}
            }
        }
        match change {
            "unknown-caller-extra" => {
                metadata
                    .extra
                    .insert("future_extra".to_string(), "opaque-b".to_string());
            }
            "endpoint" => {
                api_provider.base_url = base_url.replace("/v1", "/v2");
            }
            "query" => {
                api_provider.query_params = Some(std::collections::HashMap::from([(
                    "tenant_route".to_string(),
                    "b".to_string(),
                )]));
            }
            "unknown-provider" => {
                api_provider.headers.insert(
                    "x-future-provider-boundary",
                    HeaderValue::from_static("provider-b"),
                );
            }
            _ => {}
        }
        let auth_context = AuthRequestTelemetryContext::new(
            None,
            auth.as_ref(),
            None,
            PendingUnauthorizedRetry::default(),
        );
        let calls_before = auth.calls.load(Ordering::SeqCst);
        session
            .websocket_connection(crate::client::WebsocketConnectParams {
                session_telemetry: &telemetry,
                api_provider: api_provider.clone(),
                api_auth: auth.clone(),
                responses_metadata: &metadata,
                auth_context,
                request_route_telemetry: crate::client::RequestRouteTelemetry::for_endpoint(
                    crate::client::RESPONSES_ENDPOINT,
                ),
            })
            .await
            .expect("websocket connection");
        assert_eq!(
            auth.calls.load(Ordering::SeqCst),
            calls_before + 1,
            "{change}: one source snapshot per reuse decision and no refresh during connect"
        );
        assert_eq!(
            session.websocket_session.connection_reused(),
            change == "unchanged"
        );
        let recorded = handshakes.lock().unwrap();
        assert_eq!(recorded.len(), expected, "{change}");
        let (wire_headers, uri) = recorded.last().unwrap();
        for (name, value) in auth.headers.lock().unwrap().iter() {
            assert_eq!(
                wire_headers.get(name),
                Some(value),
                "{change}: actual auth header {name}"
            );
        }
        if expected >= 8 {
            assert!(uri.starts_with("/v2/responses"), "{change}: {uri}");
        }
        if expected >= 9 {
            assert!(uri.contains("tenant_route=b"), "{change}: {uri}");
        }
        if change == "removed-auth" {
            assert!(!wire_headers.contains_key("x-future-auth-boundary"));
        }
        let connection = session.websocket_session.connection.as_ref().unwrap();
        assert!(!format!("{:?}", connection.identity).contains("auth-snapshot-secret"));
    }
    server.abort();
    assert!(server.await.unwrap_err().is_cancelled());
}
