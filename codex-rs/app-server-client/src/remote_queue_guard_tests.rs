//! Real transport-owner tests over WebSocket frames on an in-memory duplex.
//! No TCP permission, fake executor, or alternate command owner is involved.
use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use tokio::time::Instant;
use tokio_tungstenite::tungstenite::protocol::Role;

enum QueuedCase {
    Expired,
    Abandoned,
    LegacyAbandoned,
}

async fn run_queued_case(case: QueuedCase) {
    let (client_io, server_io) = tokio::io::duplex(16 * 1024);
    let client_stream = WebSocketStream::from_raw_socket(client_io, Role::Client, None).await;
    let mut server_stream = WebSocketStream::from_raw_socket(server_io, Role::Server, None).await;
    let server = tokio::spawn(async move {
        let init = server_stream.next().await.unwrap().unwrap();
        let JSONRPCMessage::Request(init) =
            serde_json::from_str(&init.into_text().unwrap()).unwrap()
        else {
            panic!("initialize request")
        };
        write_jsonrpc_message(&mut server_stream, JSONRPCMessage::Response(JSONRPCResponse {
            id: init.id, result: serde_json::json!({"userAgent":"codex/guard-test", "codexHome":"/tmp/guard-test"}),
        }), "duplex").await.unwrap();
        let initialized = server_stream.next().await.unwrap().unwrap();
        assert!(matches!(
            serde_json::from_str::<JSONRPCMessage>(&initialized.into_text().unwrap()).unwrap(),
            JSONRPCMessage::Notification(_)
        ));
        let mut methods = Vec::new();
        while let Some(Ok(message)) = server_stream.next().await {
            if let Message::Text(text) = message {
                let JSONRPCMessage::Request(request) = serde_json::from_str(&text).unwrap() else {
                    panic!("request")
                };
                methods.push(request.method);
                if write_jsonrpc_message(
                    &mut server_stream,
                    JSONRPCMessage::Response(JSONRPCResponse {
                        id: request.id,
                        result: serde_json::json!({}),
                    }),
                    "duplex",
                )
                .await
                .is_err()
                {
                    break;
                }
                if methods.len() == 2 {
                    break;
                }
            }
        }
        methods
    });
    let args = RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::WebSocket {
            websocket_url: "ws://localhost".into(),
            auth_token: None,
        },
        client_name: "guard-test".into(),
        client_version: "0".into(),
        experimental_api: false,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: vec![],
        channel_capacity: 4,
    };
    let client = RemoteAppServerClient::connect_with_stream(
        4,
        RemoteEventMode::Unbounded,
        "duplex".into(),
        client_stream,
        args.initialize_params(),
    )
    .await
    .unwrap();
    let (ready_tx, ready_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let first_guard = RemoteRequestSendGuard::new(
        Instant::now() + Duration::from_secs(5),
        std::future::pending(),
        async {
            ready_tx.send(()).unwrap();
            release_rx.await.unwrap();
            Ok(|| Ok(()))
        },
    );
    let (first_tx, first_rx) = oneshot::channel();
    client
        .command_tx
        .send(RemoteClientCommand::Request {
            request: Box::new(JSONRPCRequest {
                id: RequestId::Integer(1),
                method: "first".into(),
                params: None,
                trace: None,
            }),
            guard: Some(first_guard),
            response_tx: first_tx,
        })
        .await
        .unwrap();
    ready_rx.await.unwrap();
    let entered = Arc::new(AtomicUsize::new(0));
    let entered_guard = entered.clone();
    let deadline = if matches!(case, QueuedCase::Expired) {
        Instant::now() + Duration::from_millis(30)
    } else {
        Instant::now() + Duration::from_secs(5)
    };
    let guard = if matches!(case, QueuedCase::LegacyAbandoned) {
        None
    } else {
        Some(RemoteRequestSendGuard::new(
            deadline,
            std::future::pending(),
            async move {
                Ok(move || {
                    entered_guard.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                })
            },
        ))
    };
    let (second_tx, second_rx) = oneshot::channel();
    client
        .command_tx
        .send(RemoteClientCommand::Request {
            request: Box::new(JSONRPCRequest {
                id: RequestId::Integer(2),
                method: "second".into(),
                params: None,
                trace: None,
            }),
            guard,
            response_tx: second_tx,
        })
        .await
        .unwrap();
    let second_rx = if matches!(case, QueuedCase::Expired) {
        Some(second_rx)
    } else {
        drop(second_rx);
        None
    };
    if matches!(case, QueuedCase::Expired) {
        // Valid when enqueued, then expires while the first command owns the
        // transport. Waking the writer cannot revive that old budget.
        tokio::time::sleep_until(deadline + Duration::from_millis(1)).await;
    }
    release_tx.send(()).unwrap();
    if let Some(second_rx) = second_rx {
        assert!(second_rx.await.unwrap().is_err());
    }
    let _ = first_rx.await;
    let methods = timeout(Duration::from_secs(5), server)
        .await
        .unwrap()
        .unwrap();
    let expected = if matches!(case, QueuedCase::LegacyAbandoned) {
        vec!["first", "second"]
    } else {
        vec!["first"]
    };
    assert_eq!(methods, expected);
    assert_eq!(entered.load(Ordering::SeqCst), 0);
    let _ = client.shutdown().await;
}

#[tokio::test]
async fn real_writer_drops_expired_queued_request() {
    run_queued_case(QueuedCase::Expired).await;
}
#[tokio::test]
async fn real_writer_drops_abandoned_queued_request() {
    run_queued_case(QueuedCase::Abandoned).await;
}
#[tokio::test]
async fn legacy_queued_request_preserves_abandonment_semantics() {
    run_queued_case(QueuedCase::LegacyAbandoned).await;
}
