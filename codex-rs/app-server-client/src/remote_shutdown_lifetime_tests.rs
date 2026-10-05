//! Exercises the real shutdown method with a worker stuck in close/flush.
//! This is a task-lifetime test, not an actual WebSocket handshake test.
use super::*;
use std::sync::atomic::AtomicBool;

struct WorkerOwnedResource(Arc<AtomicBool>);

impl Drop for WorkerOwnedResource {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

#[tokio::test]
async fn owned_shutdown_aborts_and_joins_stalled_worker_and_drops_pending_waiters() {
    let (command_tx, mut command_rx) = mpsc::channel(8);
    let (_event_tx, event_rx) = mpsc::unbounded_channel::<AppServerEvent>();
    let (response_tx, response_rx) = oneshot::channel::<IoResult<RequestResult>>();
    let mut pending_requests = HashMap::new();
    pending_requests.insert(RequestId::Integer(41), response_tx);
    let dropped = Arc::new(AtomicBool::new(false));
    let worker_resource = WorkerOwnedResource(Arc::clone(&dropped));
    let worker_handle = tokio::spawn(async move {
        let command = command_rx.recv().await.expect("shutdown command");
        let RemoteClientCommand::Shutdown { response_tx } = command else {
            panic!("only the exclusively owned connection is being shut down");
        };
        // Model stream.close/flush never completing while an older read-only
        // response is also absent. Keep every resource live across this await.
        std::future::pending::<()>().await;
        drop(response_tx);
        drop(pending_requests);
        drop(worker_resource);
    });
    let worker_status = worker_handle.abort_handle();
    let client = RemoteAppServerClient {
        command_tx,
        event_rx: RemoteEventReceiver::Unbounded(event_rx),
        pending_events: VecDeque::new(),
        server_version: None,
        codex_home: None,
        connection_id: 1,
        worker_handle,
    };
    timeout(
        SHUTDOWN_TIMEOUT * 2 + Duration::from_secs(2),
        client.shutdown(),
    )
    .await
    .expect("shutdown must finish after its existing two bounded waits")
    .expect("forced cleanup completes");
    assert!(
        worker_status.is_finished(),
        "returning a timeout must not detach the worker"
    );
    assert!(
        dropped.load(Ordering::SeqCst),
        "worker-owned resources must be dropped"
    );
    assert!(
        response_rx.await.is_err(),
        "unanswered response sender must be dropped"
    );
}
// Proposal to append to the isolated remote_shutdown_lifetime_tests module.
struct TrackedDuplex {
    inner: tokio::io::DuplexStream,
    dropped: Arc<AtomicBool>,
}

impl Drop for TrackedDuplex {
    fn drop(&mut self) {
        self.dropped.store(true, Ordering::SeqCst);
    }
}

impl AsyncRead for TrackedDuplex {
    fn poll_read(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
        buffer: &mut tokio::io::ReadBuf<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        std::pin::Pin::new(&mut self.get_mut().inner).poll_read(cx, buffer)
    }
}

impl AsyncWrite for TrackedDuplex {
    fn poll_write(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
        bytes: &[u8],
    ) -> std::task::Poll<std::io::Result<usize>> {
        std::pin::Pin::new(&mut self.get_mut().inner).poll_write(cx, bytes)
    }

    fn poll_flush(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        std::pin::Pin::new(&mut self.get_mut().inner).poll_flush(cx)
    }

    fn poll_shutdown(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        std::pin::Pin::new(&mut self.get_mut().inner).poll_shutdown(cx)
    }
}

#[tokio::test]
async fn cancellation_during_initialization_drops_owned_transport_before_worker_creation() {
    let dropped = Arc::new(AtomicBool::new(false));
    let (stream, peer) = tokio::io::duplex(4096);
    let stream = TrackedDuplex {
        inner: stream,
        dropped: Arc::clone(&dropped),
    };
    let websocket = WebSocketStream::from_raw_socket(
        stream,
        tokio_tungstenite::tungstenite::protocol::Role::Client,
        None,
    )
    .await;
    let args = RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::WebSocket {
            websocket_url: "ws://unused.test".to_string(),
            auth_token: None,
        },
        client_name: "constructor-lifetime-fixture".to_string(),
        client_version: "1".to_string(),
        experimental_api: true,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: 8,
    };
    let mut connect = Box::pin(RemoteAppServerClient::connect_with_stream(
        8,
        RemoteEventMode::Bounded { capacity: 16 },
        "in-memory".to_string(),
        websocket,
        args.initialize_params(),
    ));
    assert!(
        timeout(Duration::from_millis(20), &mut connect)
            .await
            .is_err()
    );
    drop(connect);
    assert!(
        dropped.load(Ordering::SeqCst),
        "cancellation must not leave a task owning the stream"
    );
    let mut peer = WebSocketStream::from_raw_socket(
        peer,
        tokio_tungstenite::tungstenite::protocol::Role::Server,
        None,
    )
    .await;
    let message = timeout(Duration::from_secs(1), peer.next())
        .await
        .expect("buffered initialization request")
        .expect("request")
        .expect("valid frame");
    let Message::Text(text) = message else {
        panic!("initialization must be JSON text");
    };
    let request: serde_json::Value = serde_json::from_str(&text).expect("JSON request");
    assert_eq!(request["method"], "initialize");
}

#[tokio::test]
async fn cancelling_owned_shutdown_does_not_detach_worker_or_pending_waiters() {
    let (command_tx, mut command_rx) = mpsc::channel(8);
    let (_event_tx, event_rx) = mpsc::unbounded_channel::<AppServerEvent>();
    let (pending_tx, pending_rx) = oneshot::channel::<IoResult<RequestResult>>();
    let mut pending_requests = HashMap::new();
    pending_requests.insert(RequestId::Integer(41), pending_tx);
    let dropped = Arc::new(AtomicBool::new(false));
    let worker_resource = WorkerOwnedResource(Arc::clone(&dropped));
    let (closing_tx, closing_rx) = oneshot::channel();
    let worker_handle = tokio::spawn(async move {
        let Some(RemoteClientCommand::Shutdown { response_tx }) = command_rx.recv().await else {
            panic!("expected shutdown");
        };
        closing_tx.send(()).expect("close barrier");
        std::future::pending::<()>().await;
        drop(response_tx);
        drop(pending_requests);
        drop(worker_resource);
    });
    let worker_status = worker_handle.abort_handle();
    let client = RemoteAppServerClient {
        command_tx,
        event_rx: RemoteEventReceiver::Unbounded(event_rx),
        pending_events: VecDeque::new(),
        server_version: None,
        codex_home: None,
        connection_id: 1,
        worker_handle,
    };
    let shutdown = tokio::spawn(client.into_abort_on_drop().shutdown());
    closing_rx.await.expect("worker is stuck closing");
    // RuntimeTasks uses this same abort-and-join mechanism after its shorter
    // production host grace. Do not alter that grace or the client deadlines.
    shutdown.abort();
    assert!(
        shutdown
            .await
            .expect_err("shutdown parent cancelled")
            .is_cancelled()
    );
    let stopped = timeout(Duration::from_secs(1), async {
        while !worker_status.is_finished() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .is_ok();
    if !stopped {
        // Clean up the expected-red baseline worker before failing the test.
        worker_status.abort();
        timeout(Duration::from_secs(1), async {
            while !worker_status.is_finished() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("baseline worker cleanup");
    }
    assert!(dropped.load(Ordering::SeqCst));
    assert!(pending_rx.await.is_err());
    assert!(
        stopped,
        "parent cancellation detached the exclusively owned worker"
    );
}
