use std::sync::Arc;

use codex_exec_server_protocol::JSONRPCMessage;
use pretty_assertions::assert_eq;
use tokio::sync::mpsc;
use tokio::sync::watch;

use super::CancellationAttempt;
use super::HTTP_CANCELLATION_ACK_TIMEOUT;
use super::HttpStreamCancellation;
use crate::connection::JsonRpcConnection;
use crate::connection::JsonRpcTransport;
use crate::protocol::HTTP_REQUEST_CANCEL_METHOD;
use crate::rpc::RpcClient;

#[tokio::test(start_paused = true)]
async fn absent_ack_closes_only_original_transport_without_retry() {
    let (outgoing_tx, mut outgoing_rx) = mpsc::channel(/*buffer*/ 4);
    let (_incoming_tx, incoming_rx) = mpsc::channel(/*buffer*/ 4);
    let (_disconnected_tx, disconnected_rx) = watch::channel(/*init*/ false);
    let (client, _events) = RpcClient::new(JsonRpcConnection {
        outgoing_tx,
        incoming_rx,
        disconnected_rx,
        task_handles: Vec::new(),
        transport: JsonRpcTransport::Plain,
    });
    let client = Arc::new(client);
    let (other_tx, _other_rx) = mpsc::channel(/*buffer*/ 4);
    let (_other_incoming_tx, other_incoming_rx) = mpsc::channel(/*buffer*/ 4);
    let (_other_disconnected_tx, other_disconnected_rx) = watch::channel(/*init*/ false);
    let (other, _other_events) = RpcClient::new(JsonRpcConnection {
        outgoing_tx: other_tx,
        incoming_rx: other_incoming_rx,
        disconnected_rx: other_disconnected_rx,
        task_handles: Vec::new(),
        transport: JsonRpcTransport::Plain,
    });
    let owner = HttpStreamCancellation::new(Arc::clone(&client), "http-7".to_string());
    owner.cancel();
    assert!(
        !client.is_disconnected(),
        "the original transport must stay open while its cleanup task awaits an acknowledgement"
    );
    owner.cancel();
    let JSONRPCMessage::Request(request) = outgoing_rx.recv().await.expect("cleanup request")
    else {
        panic!("expected cleanup request");
    };
    assert_eq!(
        (request.method.as_str(), request.params),
        (
            HTTP_REQUEST_CANCEL_METHOD,
            Some(serde_json::json!({"requestId":"http-7"}))
        )
    );
    assert!(!client.is_disconnected());
    tokio::time::advance(HTTP_CANCELLATION_ACK_TIMEOUT).await;
    tokio::task::yield_now().await;
    assert!(client.is_disconnected());
    assert!(!other.is_disconnected());
    assert!(
        outgoing_rx.try_recv().is_err(),
        "no cleanup retry or replacement connection"
    );
}

#[tokio::test]
async fn unpolled_cleanup_task_drop_closes_its_original_transport() {
    let (outgoing_tx, _outgoing_rx) = mpsc::channel(/*buffer*/ 4);
    let (_incoming_tx, incoming_rx) = mpsc::channel(/*buffer*/ 4);
    let (_disconnected_tx, disconnected_rx) = watch::channel(/*init*/ false);
    let (client, _events) = RpcClient::new(JsonRpcConnection {
        outgoing_tx,
        incoming_rx,
        disconnected_rx,
        task_handles: Vec::new(),
        transport: JsonRpcTransport::Plain,
    });
    let client = Arc::new(client);
    let attempt = CancellationAttempt {
        rpc_client: Arc::clone(&client),
        response_received: false,
    };
    let cleanup = async move {
        std::future::pending::<()>().await;
        drop(attempt);
    };
    assert!(!client.is_disconnected());
    drop(cleanup);
    assert!(client.is_disconnected());
}
