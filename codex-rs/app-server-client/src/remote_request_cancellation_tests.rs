//! Real queued requests and WebSocket frames, with no authority or provider fixture.

use pretty_assertions::assert_eq;
use tokio::io::DuplexStream;
use tokio_tungstenite::tungstenite::protocol::Role;

use super::*;

const CASE_TIMEOUT: Duration = Duration::from_secs(5);
const CHANNEL_CAPACITY: usize = 1;
const TRANSPORT_BUFFER_BYTES: usize = 16 * 1024;

fn request(id: RequestId, marker: &str) -> JSONRPCRequest {
    JSONRPCRequest {
        id,
        method: "server/diagnostics".to_string(),
        params: Some(serde_json::json!({"marker": marker})),
        trace: None,
    }
}

async fn read_message(stream: &mut WebSocketStream<DuplexStream>) -> IoResult<serde_json::Value> {
    let message = stream
        .next()
        .await
        .ok_or_else(|| IoError::other("transport fixture connection closed"))?
        .map_err(IoError::other)?;
    let Message::Text(text) = message else {
        return Err(IoError::other("expected a text JSON-RPC frame"));
    };
    serde_json::from_str(&text).map_err(IoError::other)
}

async fn send_message(
    stream: &mut WebSocketStream<DuplexStream>,
    value: serde_json::Value,
) -> IoResult<()> {
    stream
        .send(Message::Text(value.to_string().into()))
        .await
        .map_err(IoError::other)
}

async fn connect_fixture() -> IoResult<(RemoteAppServerClient, WebSocketStream<DuplexStream>)> {
    let (client_io, peer_io) = tokio::io::duplex(TRANSPORT_BUFFER_BYTES);
    let client_stream =
        WebSocketStream::from_raw_socket(client_io, Role::Client, /*config*/ None).await;
    let mut peer = WebSocketStream::from_raw_socket(peer_io, Role::Server, /*config*/ None).await;
    let handshake = async {
        let initialize = read_message(&mut peer).await?;
        assert_eq!(initialize["method"], "initialize");
        send_message(
            &mut peer,
            serde_json::json!({"id": initialize["id"], "result": {"userAgent": "transport-fixture/1"}}),
        )
        .await?;
        assert_eq!(read_message(&mut peer).await?["method"], "initialized");
        Ok::<(), IoError>(())
    };
    let connect = RemoteAppServerClient::connect_with_stream(
        CHANNEL_CAPACITY,
        RemoteEventMode::Unbounded,
        "request-cancellation-fixture".to_string(),
        client_stream,
        InitializeParams {
            client_info: ClientInfo {
                name: "request-cancellation-client".to_string(),
                title: None,
                version: "1".to_string(),
            },
            capabilities: None,
        },
    );
    let (client, initialized) = tokio::join!(connect, handshake);
    initialized?;
    Ok((client?, peer))
}

#[tokio::test(flavor = "current_thread")]
async fn queued_request_cancelled_before_worker_poll_is_not_written() -> IoResult<()> {
    timeout(CASE_TIMEOUT, async {
        let (client, mut peer) = connect_fixture().await?;
        let handle = client.request_handle();
        let mut cancelled = Box::pin(
            handle.request_json_rpc(request(RequestId::Integer(1001), "cancelled-before-write")),
        );
        // No executor yield between this actual enqueue and dropping its waiter.
        assert!(futures::poll!(cancelled.as_mut()).is_pending());
        assert_eq!(handle.command_tx.capacity(), 0);
        drop(cancelled);

        let live_request = request(RequestId::Integer(1002), "live-barrier");
        let expected = serde_json::to_value(&live_request).map_err(IoError::other)?;
        let receive = async {
            let mut frames = Vec::new();
            loop {
                let frame = read_message(&mut peer).await?;
                send_message(
                    &mut peer,
                    serde_json::json!({"id": frame["id"], "result": {}}),
                )
                .await?;
                let is_barrier = frame["id"] == expected["id"];
                frames.push(frame);
                if is_barrier {
                    return Ok::<_, IoError>(frames);
                }
            }
        };
        let (response, frames) = tokio::join!(handle.request_json_rpc(live_request), receive);
        client.shutdown().await?;
        let response = response?.map_err(|error| IoError::other(error.message))?;
        assert_eq!(response, serde_json::json!({}));
        assert_eq!(
            frames?,
            vec![expected],
            "a request cancelled before worker admission must not reach the wire"
        );
        Ok::<(), IoError>(())
    })
    .await
    .map_err(IoError::other)?
}

#[tokio::test(flavor = "current_thread")]
async fn cancelled_after_write_keeps_pending_id_until_the_actual_reply() -> IoResult<()> {
    timeout(CASE_TIMEOUT, async {
        let (client, mut peer) = connect_fixture().await?;
        let handle = client.request_handle();
        let first_request = request(RequestId::Integer(2001), "written-before-cancel");
        let expected_first = serde_json::to_value(&first_request).map_err(IoError::other)?;
        let mut cancelled = Box::pin(handle.request_json_rpc(first_request));
        assert!(futures::poll!(cancelled.as_mut()).is_pending());
        assert_eq!(handle.command_tx.capacity(), 0);
        let first_frame = read_message(&mut peer).await?;
        drop(cancelled);

        // The peer has received a real frame and has deliberately not replied.
        // Closing the waiter cannot prove the request had no external effect.
        let duplicate = handle
            .request_json_rpc(request(RequestId::Integer(2001), "duplicate-before-reply"))
            .await;
        send_message(
            &mut peer,
            serde_json::json!({"id": first_frame["id"], "result": {}}),
        )
        .await?;
        let barrier = request(RequestId::Integer(2002), "after-actual-reply");
        let expected_barrier = serde_json::to_value(&barrier).map_err(IoError::other)?;
        let receive = async {
            let frame = read_message(&mut peer).await?;
            send_message(
                &mut peer,
                serde_json::json!({"id": frame["id"], "result": {}}),
            )
            .await?;
            Ok::<_, IoError>(frame)
        };
        let (response, barrier_frame) = tokio::join!(handle.request_json_rpc(barrier), receive);
        client.shutdown().await?;
        let duplicate = duplicate.expect_err("an actually written request retains its pending id");
        assert_eq!(
            (duplicate.kind(), duplicate.to_string()),
            (
                ErrorKind::InvalidInput,
                "duplicate remote app-server request id `2001`".to_string()
            )
        );
        assert_eq!(
            vec![first_frame, barrier_frame?],
            vec![expected_first, expected_barrier]
        );
        assert_eq!(
            response?.map_err(|error| IoError::other(error.message))?,
            serde_json::json!({})
        );
        Ok::<(), IoError>(())
    })
    .await
    .map_err(IoError::other)?
}

#[tokio::test(flavor = "current_thread")]
async fn lost_reply_after_actual_frame_remains_a_transport_error() -> IoResult<()> {
    timeout(CASE_TIMEOUT, async {
        let (mut client, mut peer) = connect_fixture().await?;
        let handle = client.request_handle();
        let original = request(RequestId::Integer(3001), "reply-lost-after-write");
        let expected = serde_json::to_value(&original).map_err(IoError::other)?;
        let mut pending = Box::pin(handle.request_json_rpc(original));
        assert!(futures::poll!(pending.as_mut()).is_pending());
        assert_eq!(handle.command_tx.capacity(), 0);
        let frame = read_message(&mut peer).await?;
        // An actual protocol close is sent without a JSON-RPC reply.
        peer.close(/*msg*/ None).await.map_err(IoError::other)?;
        let unknown = pending.await;
        let event = client.next_event().await;
        let closed_owner = handle
            .request_json_rpc(request(
                RequestId::Integer(3002),
                "closed-owner-must-not-reconnect",
            ))
            .await;
        client.shutdown().await?;

        assert_eq!(frame, expected);
        assert_eq!(
            unknown
                .expect_err("a lost reply is not success or a no-effect receipt")
                .kind(),
            ErrorKind::ConnectionAborted
        );
        assert!(matches!(event, Some(AppServerEvent::Disconnected { .. })));
        assert_eq!(
            closed_owner
                .expect_err("the closed worker must not reconnect or replay")
                .kind(),
            ErrorKind::BrokenPipe
        );
        Ok::<(), IoError>(())
    })
    .await
    .map_err(IoError::other)?
}
