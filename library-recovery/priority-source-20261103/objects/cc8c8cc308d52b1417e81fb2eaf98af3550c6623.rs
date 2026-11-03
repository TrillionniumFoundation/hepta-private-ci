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
