use std::convert::Infallible;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use axum::Json;
use axum::Router;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::response::Response;
use axum::response::Sse;
use axum::response::sse::Event;
use axum::routing::post;
use codex_config::types::AuthKeyringBackendKind;
use codex_config::types::OAuthCredentialsStoreMode;
use codex_exec_server::Environment;
use codex_rmcp_client::McpProtocolMode;
use codex_rmcp_client::RmcpClient;
use futures::FutureExt;
use futures::stream;
use pretty_assertions::assert_eq;
use rmcp::model::ClientCapabilities;
use rmcp::model::Implementation;
use rmcp::model::InitializeRequestParams;
use rmcp::model::PaginatedRequestParams;
use rmcp::model::ProtocolVersion;
use rmcp::service::ServiceError;
use serde_json::Value;
use serde_json::json;
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tokio::task::JoinSet;

const MAX_LEGACY_MCP_MESSAGE_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Copy)]
enum Scenario {
    Concurrent,
    Recovery,
    Resume,
    Abandoned,
}

struct ServerState {
    scenario: Scenario,
    initializes: AtomicUsize,
    calls: AtomicUsize,
    resumes: AtomicUsize,
    last_request_id: Mutex<Value>,
    cancelled: mpsc::UnboundedSender<Value>,
}

async fn reply(State(state): State<Arc<ServerState>>, Json(request): Json<Value>) -> Response {
    match request["method"].as_str() {
        Some("initialize") => {
            let generation = state.initializes.fetch_add(1, Ordering::SeqCst) + 1;
            (
                [("mcp-session-id", format!("session-{generation}"))],
                Json(json!({
                    "jsonrpc": "2.0", "id": request["id"],
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "local-failure-test", "version": "0.0.0"},
                    },
                })),
            )
                .into_response()
        }
        Some("notifications/initialized") => StatusCode::ACCEPTED.into_response(),
        Some("notifications/cancelled") => {
            let _ = state.cancelled.send(request["params"].clone());
            StatusCode::ACCEPTED.into_response()
        }
        Some("tools/list") => {
            let call = state.calls.fetch_add(1, Ordering::SeqCst);
            *state.last_request_id.lock().expect("request id") = request["id"].clone();
            match state.scenario {
                Scenario::Concurrent if request["params"]["cursor"] == "ordinary" => {
                    tokio::time::sleep(Duration::from_millis(250)).await;
                    ([("content-type", "text/event-stream")], "").into_response()
                }
                Scenario::Recovery if call == 1 => StatusCode::NOT_FOUND.into_response(),
                Scenario::Recovery if call > 1 => {
                    ([("content-type", "text/event-stream")], "").into_response()
                }
                Scenario::Abandoned => {
                    Sse::new(stream::pending::<Result<Event, Infallible>>()).into_response()
                }
                Scenario::Concurrent | Scenario::Recovery | Scenario::Resume => {
                    let response = json!({
                        "jsonrpc": "2.0", "id": request["id"],
                        "result": {"tools": [{
                            "name": "oversized", "inputSchema": {"type": "object"},
                            "description": "x".repeat(MAX_LEGACY_MCP_MESSAGE_BYTES + 1),
                        }]},
                    });
                    let mut events = Vec::new();
                    if matches!(state.scenario, Scenario::Resume) {
                        events.push(Ok::<_, Infallible>(
                            Event::default().event("ping").id("resume-before-limit"),
                        ));
                    }
                    events.push(Ok(Event::default()
                        .event("message")
                        .data(response.to_string())));
                    Sse::new(stream::iter(events)).into_response()
                }
            }
        }
        other => panic!("unexpected request: {other:?}"),
    }
}

async fn fixture(
    scenario: Scenario,
) -> anyhow::Result<(
    RmcpClient,
    Arc<ServerState>,
    mpsc::UnboundedReceiver<Value>,
    JoinSet<()>,
)> {
    let (cancelled, received_cancellation) = mpsc::unbounded_channel();
    let state = Arc::new(ServerState {
        scenario,
        initializes: AtomicUsize::new(0),
        calls: AtomicUsize::new(0),
        resumes: AtomicUsize::new(0),
        last_request_id: Mutex::new(Value::Null),
        cancelled,
    });
    let router = Router::new()
        .route(
            "/mcp",
            post(reply)
                .get(
                    |State(state): State<Arc<ServerState>>, headers: HeaderMap| async move {
                        if let Some(id) = headers.get("last-event-id") {
                            assert_eq!(id, "resume-before-limit");
                            state.resumes.fetch_add(1, Ordering::SeqCst);
                        }
                        StatusCode::METHOD_NOT_ALLOWED
                    },
                )
                .delete(|| async { StatusCode::OK }),
        )
        .with_state(Arc::clone(&state));
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}/mcp", listener.local_addr()?);
    let mut tasks = JoinSet::new();
    tasks.spawn(async move {
        axum::serve(listener, router).await.expect("fixture server");
    });
    let client = RmcpClient::new_streamable_http_client_with_protocol_mode(
        "local-failure-test",
        &url,
        /*bearer_token*/ None,
        /*http_headers*/ None,
        /*env_http_headers*/ None,
        OAuthCredentialsStoreMode::File,
        AuthKeyringBackendKind::default(),
        Environment::default_for_tests().get_http_client(),
        /*auth_provider*/ None,
        McpProtocolMode::Legacy,
    )
    .await?;
    client
        .initialize(
            InitializeRequestParams::new(
                ClientCapabilities::default(),
                Implementation::new("local-failure-test", "0.0.0"),
            )
            .with_protocol_version(ProtocolVersion::V_2025_06_18),
            Some(Duration::from_secs(5)),
            Box::new(|_, _| async { anyhow::bail!("unexpected elicitation") }.boxed()),
        )
        .await?;
    Ok((client, state, received_cancellation, tasks))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_ordinary_close_cannot_borrow_another_requests_size_failure()
-> anyhow::Result<()> {
    let (client, state, _cancelled, _tasks) = fixture(Scenario::Concurrent).await?;
    let (oversized, ordinary) = tokio::join!(
        client.list_tools(/*params*/ None, Some(Duration::from_secs(5))),
        client.list_tools_with_connector_ids(
            Some(PaginatedRequestParams {
                cursor: Some("ordinary".to_string()),
                meta: None
            }),
            Some(Duration::from_secs(5)),
        ),
    );
    let oversized = oversized.expect_err("local size rejection");
    assert!(
        oversized
            .to_string()
            .contains("MCP response body exceeds 16777216 bytes")
    );
    assert!(oversized.chain().any(|source| matches!(
        source.downcast_ref::<ServiceError>(),
        Some(ServiceError::TransportClosed)
    )));
    let ordinary = ordinary.err().expect("ordinary transport close");
    assert_eq!(ordinary.to_string(), "Transport closed");
    assert_eq!(state.calls.load(Ordering::SeqCst), 2);
    client.shutdown().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn session_recovery_does_not_reuse_a_prior_local_failure() -> anyhow::Result<()> {
    let (client, state, _cancelled, _tasks) = fixture(Scenario::Recovery).await?;
    let first = client
        .list_tools(/*params*/ None, Some(Duration::from_secs(5)))
        .await
        .expect_err("first local size rejection");
    assert!(
        first
            .to_string()
            .contains("MCP response body exceeds 16777216 bytes")
    );
    let recovered = client
        .list_tools(/*params*/ None, Some(Duration::from_secs(5)))
        .await
        .expect_err("ordinary close after actual session recovery");
    assert_eq!(recovered.to_string(), "Transport closed");
    assert_eq!(state.initializes.load(Ordering::SeqCst), 2);
    assert_eq!(state.calls.load(Ordering::SeqCst), 3);
    client.shutdown().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_resumed_get_close_is_not_attributed_to_the_original_post() -> anyhow::Result<()> {
    let (client, state, _cancelled, _tasks) = fixture(Scenario::Resume).await?;
    let error = client
        .list_tools(/*params*/ None, Some(Duration::from_secs(5)))
        .await
        .expect_err("GET resume is unavailable");
    assert_eq!(error.to_string(), "Transport closed");
    assert_eq!(state.resumes.load(Ordering::SeqCst), 1);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    client.shutdown().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abandoning_a_list_request_preserves_its_exact_cancellation() -> anyhow::Result<()> {
    let (client, state, mut cancelled, _tasks) = fixture(Scenario::Abandoned).await?;
    let error = client
        .list_tools(/*params*/ None, Some(Duration::from_millis(500)))
        .await
        .expect_err("pending list request must time out");
    assert!(error.to_string().contains("timed out awaiting tools/list"));
    let notification = tokio::time::timeout(Duration::from_secs(2), cancelled.recv())
        .await?
        .expect("one cancellation notification");
    let request_id = state.last_request_id.lock().expect("request id").clone();
    assert_ne!(request_id, Value::Null);
    assert_eq!(notification["requestId"], request_id);
    assert_eq!(notification["reason"], "request abandoned by the caller");
    client.shutdown().await;
    Ok(())
}
