//! Real remote JSON-RPC transport plus the original cleanup CAS. Responses are
//! fixtures, not production disposal or memory-release evidence.
use super::*;
use crate::native_cleanup_store::CleanupState;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use futures::SinkExt;
use futures::StreamExt;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::net::TcpListener;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::Message;

#[tokio::test]
async fn native_thread_lifecycle_effect_possible_drop_retains_session_without_disposal()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let store = NativeCleanupStore::open(
        &directory.path().join("cleanup.sqlite3"),
        "fixture-agent".to_owned(),
        /*owner_generation*/ 1,
    )
    .await?;
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let (held_tx, held_rx) = tokio::sync::oneshot::channel();
    let receiver = tokio::spawn(async move {
        let (socket, _) = listener.accept().await?;
        let mut ws = accept_async(socket).await?;
        let initialize: Value =
            serde_json::from_str(ws.next().await.ok_or("initialize missing")??.to_text()?)?;
        ws.send(Message::Text(
            json!({"id":initialize["id"],"result":{
                "userAgent":"codex_cli_rs/fixture (Test OS; x86_64) rust","codexHome":"/fixture"
            }})
            .to_string()
            .into(),
        ))
        .await?;
        let initialized: Value =
            serde_json::from_str(ws.next().await.ok_or("initialized missing")??.to_text()?)?;
        assert_eq!(initialized["method"], "initialized");
        for acknowledgement in ["wrong-session", "wrong-version", "unsupported", "exact"] {
            let request: Value =
                serde_json::from_str(ws.next().await.ok_or("retention missing")??.to_text()?)?;
            assert_eq!(request["method"], "thread/ephemeral/retain");
            assert_eq!(request["params"]["protocolVersion"], 1);
            assert_eq!(request["params"]["threadId"], "fixture-thread");
            assert_eq!(request["params"]["expectedSessionId"], "fixture-session");
            assert_eq!(
                request["params"]["operationId"],
                "native.request.v1:fixture-owner-pending"
            );
            let reply = if acknowledgement == "unsupported" {
                json!({"id":request["id"],"error":{"code":-32601,"message":"unsupported"}})
            } else {
                json!({"id":request["id"],"result":{
                    "protocolVersion":if acknowledgement == "wrong-version" {0} else {1},
                    "threadId":"fixture-thread",
                    "sessionId":if acknowledgement == "wrong-session" {"another-session"} else {"fixture-session"},
                    "operationId":"native.request.v1:fixture-owner-pending"
                }})
            };
            ws.send(Message::Text(reply.to_string().into())).await?;
        }
        held_rx.await?;
        assert!(
            tokio::time::timeout(Duration::from_millis(150), ws.next())
                .await
                .is_err(),
            "an unconfirmed original terminal owner must not cause disposal RPC"
        );
        Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
    });
    let client = RemoteAppServerClient::connect(RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::WebSocket {
            websocket_url: format!("ws://{address}"),
            auth_token: None,
        },
        client_name: "cleanup-fixture".to_owned(),
        client_version: "fixture".to_owned(),
        experimental_api: false,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: 8,
    })
    .await?;
    let mut guard = NativeThreadGuard::create(
        store.clone(),
        client.request_handle(),
        "native.request.v1:fixture-owner-pending".to_owned(),
        "fixture-thread".to_owned(),
        "fixture-session".to_owned(),
    )
    .await?;
    assert!(guard.effect_entered().await.is_err());
    for _ in 0..3 {
        assert!(guard.retain_until_disposal().await.is_err());
        assert!(guard.effect_entered().await.is_err());
        let original = store
            .obligation("native.request.v1:fixture-owner-pending")
            .await?
            .ok_or("original prepared obligation")?;
        assert_eq!(original.state, CleanupState::Prepared);
    }
    guard.retain_until_disposal().await?;
    // This hold is installed before cross-owner dispatch/abort RPCs. Dropping
    // their request while its original ACK is missing cannot restore Prepared.
    guard.effect_entered().await?;
    drop(guard);
    held_tx.send(()).map_err(|_| "fixture receiver missing")?;
    receiver.await?.map_err(|e| e.to_string())?;
    let retained = store
        .obligation("native.request.v1:fixture-owner-pending")
        .await?
        .ok_or("unconfirmed obligation retained")?;
    assert_eq!(retained.state, CleanupState::EffectPossible);
    assert!(
        store
            .claim_ready("fixture-recovery".to_owned(), Duration::from_secs(1), 8)
            .await?
            .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn native_thread_lifecycle_requires_disposal_ack_and_keeps_exact_obligation_after_timeout()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let store = NativeCleanupStore::open(
        &directory.path().join("cleanup.sqlite3"),
        "fixture-agent".to_owned(),
        /*owner_generation*/ 1,
    )
    .await?;
    let prepared = store
        .enqueue(
            "fixture-operation".to_owned(),
            "fixture-thread".to_owned(),
            "fixture-session".to_owned(),
        )
        .await?;
    let possible = store.mark_effect_possible(&prepared).await?;
    let ready = store.mark_terminal_durable(&possible).await?;
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let (timeout_seen_tx, timeout_seen_rx) = tokio::sync::oneshot::channel();
    let receiver = tokio::spawn(async move {
        let (socket, _) = listener.accept().await?;
        let mut ws = accept_async(socket).await?;
        let initialize: Value =
            serde_json::from_str(ws.next().await.ok_or("initialize missing")??.to_text()?)?;
        ws.send(Message::Text(
            json!({"id":initialize["id"],"result":{
                "userAgent":"codex_cli_rs/fixture (Test OS; x86_64) rust","codexHome":"/fixture"
            }})
            .to_string()
            .into(),
        ))
        .await?;
        let initialized: Value =
            serde_json::from_str(ws.next().await.ok_or("initialized missing")??.to_text()?)?;
        assert_eq!(initialized["method"], "initialized");
        let mut timeout_seen_tx = Some(timeout_seen_tx);
        for status in [Some("unsubscribed"), None, Some("ephemeralDisposed")] {
            let request: Value =
                serde_json::from_str(ws.next().await.ok_or("cleanup missing")??.to_text()?)?;
            assert_eq!(request["method"], "thread/unsubscribe");
            assert_eq!(request["params"]["threadId"], "fixture-thread");
            assert_eq!(
                request["params"]["ephemeralDisposal"]["expectedSessionId"],
                "fixture-session"
            );
            if let Some(status) = status {
                ws.send(Message::Text(
                    json!({"id":request["id"],"result":{"status":status}})
                        .to_string()
                        .into(),
                ))
                .await?;
            } else {
                timeout_seen_tx
                    .take()
                    .ok_or("timeout signal missing")?
                    .send(())
                    .map_err(|_| "timeout receiver missing")?;
            }
        }
        Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
    });
    let client = RemoteAppServerClient::connect(RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::WebSocket {
            websocket_url: format!("ws://{address}"),
            auth_token: None,
        },
        client_name: "cleanup-fixture".to_owned(),
        client_version: "fixture".to_owned(),
        experimental_api: false,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: 8,
    })
    .await?;
    let claim = store
        .claim_exact(
            &ready,
            "fixture-worker-1".to_owned(),
            Duration::from_secs(1),
        )
        .await?
        .ok_or("first claim")?;
    cleanup_claim(
        store.clone(),
        client.request_handle(),
        claim,
        Instant::now() + Duration::from_secs(1),
    )
    .await;
    let retained = store
        .obligation("fixture-operation")
        .await?
        .ok_or("legacy ACK retained")?;
    assert_eq!(retained.state, CleanupState::TerminalDurable);
    let claim = store
        .claim_exact(
            &retained,
            "fixture-worker-2".to_owned(),
            Duration::from_secs(1),
        )
        .await?
        .ok_or("second claim")?;
    cleanup_claim(
        store.clone(),
        client.request_handle(),
        claim,
        Instant::now() + Duration::from_millis(100),
    )
    .await;
    timeout_seen_rx.await?;
    let retained = store
        .obligation("fixture-operation")
        .await?
        .ok_or("timeout retained")?;
    assert_eq!(
        (&retained.thread_id, &retained.session_id),
        (&ready.thread_id, &ready.session_id)
    );
    let claim = store
        .claim_exact(
            &retained,
            "fixture-worker-3".to_owned(),
            Duration::from_secs(1),
        )
        .await?
        .ok_or("third claim")?;
    cleanup_claim(
        store.clone(),
        client.request_handle(),
        claim,
        Instant::now() + Duration::from_secs(1),
    )
    .await;
    assert!(store.obligation("fixture-operation").await?.is_none());
    receiver.await?.map_err(|e| e.to_string())?;
    Ok(())
}
