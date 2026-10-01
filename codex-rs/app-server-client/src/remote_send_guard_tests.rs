use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::JSONRPCResponse;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use futures::StreamExt;
use tokio::net::TcpListener;
use tokio::sync::Notify;
use tokio::time::Duration;
use tokio::time::timeout;

use super::*;
use crate::RemoteAppServerClient;
use crate::RemoteAppServerConnectArgs;
use crate::RemoteAppServerEndpoint;
use crate::TypedRequestError;

fn args(websocket_url: String) -> RemoteAppServerConnectArgs {
    RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::WebSocket {
            websocket_url,
            auth_token: None,
        },
        client_name: "first-contact-test".to_string(),
        client_version: "1".to_string(),
        experimental_api: true,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: 8,
    }
}

fn request(id: i64) -> ClientRequest {
    ClientRequest::ThreadQueueReconcile {
        request_id: RequestId::Integer(id),
        params: ThreadQueueReconcileParams {
            thread_id: "owned-thread".to_string(),
            input: Vec::new(),
            client_user_message_id: format!("exact-{id}"),
            expected_payload_sha256: "a".repeat(64),
            mode: ThreadQueueReconcileMode::AllowIfAbsent,
        },
    }
}

async fn server(
    listener: TcpListener,
    initializing: Arc<Notify>,
    release_initialize: Arc<Notify>,
) -> Vec<String> {
    let (stream, _) = listener.accept().await.unwrap();
    let mut websocket = tokio_tungstenite::accept_async(stream).await.unwrap();
    let frame = websocket.next().await.unwrap().unwrap();
    let Message::Text(text) = frame else {
        panic!("initialize frame");
    };
    let JSONRPCMessage::Request(initialize) = serde_json::from_str(&text).unwrap() else {
        panic!("initialize request");
    };
    assert_eq!(initialize.method, "initialize");
    initializing.notify_one();
    release_initialize.notified().await;
    websocket
        .send(Message::Text(
            serde_json::to_string(&JSONRPCMessage::Response(JSONRPCResponse {
                id: initialize.id,
                result: serde_json::json!({"userAgent": "test", "codexHome": "/owned/home"}),
            }))
            .unwrap()
            .into(),
        ))
        .await
        .unwrap();
    let mut methods = Vec::new();
    while let Some(frame) = websocket.next().await {
        match frame.unwrap() {
            Message::Text(text) => {
                if let JSONRPCMessage::Request(request) = serde_json::from_str(&text).unwrap() {
                    methods.push(request.method);
                    websocket
                        .send(Message::Text(
                            serde_json::to_string(&JSONRPCMessage::Response(JSONRPCResponse {
                                id: request.id,
                                result: serde_json::json!({"accepted": true}),
                            }))
                            .unwrap()
                            .into(),
                        ))
                        .await
                        .unwrap();
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }
    methods
}

fn check(
    live: Arc<AtomicBool>,
    polls: Arc<AtomicUsize>,
) -> impl Future<Output = io::Result<()>> + Send + 'static {
    async move {
        polls.fetch_add(/*val*/ 1, Ordering::SeqCst);
        if live.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "owner lease expired",
            ))
        }
    }
}

#[tokio::test]
async fn delayed_initialize_rechecks_contact_and_writes_no_expired_queue_request() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let websocket_url = format!("ws://{}", listener.local_addr().unwrap());
    let initializing = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let server = tokio::spawn(server(
        listener,
        Arc::clone(&initializing),
        Arc::clone(&release),
    ));
    let live = Arc::new(AtomicBool::new(/*v*/ true));
    let polls = Arc::new(AtomicUsize::new(/*v*/ 0));
    let before_send = check(Arc::clone(&live), Arc::clone(&polls));
    let client = tokio::spawn(RemoteAppServerClient::connect(args(websocket_url)));
    timeout(Duration::from_secs(/*secs*/ 2), initializing.notified())
        .await
        .unwrap();
    assert_eq!(polls.load(Ordering::SeqCst), 0);
    live.store(/*val*/ false, Ordering::SeqCst);
    release.notify_one();
    let client = client.await.unwrap().unwrap();
    let result: Result<serde_json::Value, _> = client
        .request_handle()
        .request_typed_before_send(request(/*id*/ 1), before_send)
        .await;
    assert!(
        matches!(result, Err(TypedRequestError::Transport { source, .. })
        if source.kind() == io::ErrorKind::PermissionDenied)
    );
    assert_eq!(polls.load(Ordering::SeqCst), 1);
    client.shutdown().await.unwrap();
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 2), server)
            .await
            .unwrap()
            .unwrap(),
        Vec::<String>::new()
    );
}

#[tokio::test]
async fn queued_requests_check_after_worker_wait_and_rejection_keeps_connection_usable() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let websocket_url = format!("ws://{}", listener.local_addr().unwrap());
    let initializing = Arc::new(Notify::new());
    let release_initialize = Arc::new(Notify::new());
    release_initialize.notify_one();
    let server = tokio::spawn(server(listener, initializing, release_initialize));
    let client = RemoteAppServerClient::connect(args(websocket_url))
        .await
        .unwrap();
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let handle = client.request_handle();
    let before_send = {
        let entered = Arc::clone(&entered);
        let release = Arc::clone(&release);
        async move {
            entered.notify_one();
            release.notified().await;
            Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "first owner closed",
            ))
        }
    };
    let first = tokio::spawn(async move {
        handle
            .request_typed_before_send::<serde_json::Value>(request(/*id*/ 1), before_send)
            .await
    });
    timeout(Duration::from_secs(/*secs*/ 2), entered.notified())
        .await
        .unwrap();
    let live = Arc::new(AtomicBool::new(/*v*/ true));
    let polls = Arc::new(AtomicUsize::new(/*v*/ 0));
    let handle = client.request_handle();
    let queued_check = check(Arc::clone(&live), Arc::clone(&polls));
    let second = tokio::spawn(async move {
        handle
            .request_typed_before_send::<serde_json::Value>(request(/*id*/ 2), queued_check)
            .await
    });
    tokio::task::yield_now().await;
    assert_eq!(polls.load(Ordering::SeqCst), 0);
    live.store(/*val*/ false, Ordering::SeqCst);
    release.notify_one();
    assert!(first.await.unwrap().is_err());
    assert!(second.await.unwrap().is_err());
    assert_eq!(polls.load(Ordering::SeqCst), 1);
    let result: serde_json::Value = client
        .request_handle()
        .request_typed_before_send(request(/*id*/ 3), async { Ok(()) })
        .await
        .unwrap();
    assert_eq!(result, serde_json::json!({"accepted": true}));
    client.shutdown().await.unwrap();
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 2), server)
            .await
            .unwrap()
            .unwrap(),
        vec!["thread/queue/reconcile".to_string()]
    );
}

#[tokio::test]
async fn cancelled_request_does_not_cross_first_send_while_guard_waits() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let websocket_url = format!("ws://{}", listener.local_addr().unwrap());
    let release_initialize = Arc::new(Notify::new());
    release_initialize.notify_one();
    let server = tokio::spawn(server(
        listener,
        Arc::new(Notify::new()),
        release_initialize,
    ));
    let client = RemoteAppServerClient::connect(args(websocket_url))
        .await
        .unwrap();
    let entered = Arc::new(Notify::new());
    let handle = client.request_handle();
    let notify = Arc::clone(&entered);
    let request = tokio::spawn(async move {
        handle
            .request_typed_before_send::<serde_json::Value>(request(/*id*/ 1), async move {
                notify.notify_one();
                std::future::pending::<io::Result<()>>().await
            })
            .await
    });
    timeout(Duration::from_secs(/*secs*/ 2), entered.notified())
        .await
        .unwrap();
    request.abort();
    assert!(request.await.unwrap_err().is_cancelled());
    client.shutdown().await.unwrap();
    assert_eq!(
        timeout(Duration::from_secs(/*secs*/ 2), server)
            .await
            .unwrap()
            .unwrap(),
        Vec::<String>::new()
    );
}
