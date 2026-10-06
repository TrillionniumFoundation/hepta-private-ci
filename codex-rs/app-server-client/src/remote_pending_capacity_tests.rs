//! Capacity tests use the initialized production worker over in-memory WebSockets.
//! Peer-observed frames and FIFO markers establish ordering, without timing-based
//! assertions that a frame did not arrive. Deadlines only detect a hung test.
use super::*;
use pretty_assertions::assert_eq;
use tokio::io::DuplexStream;
use tokio_tungstenite::tungstenite::protocol::Role;

type ResponseReceiver = oneshot::Receiver<IoResult<RequestResult>>;

struct Fixture {
    client: RemoteAppServerClient,
    peer: WebSocketStream<DuplexStream>,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        // Also clean up if an assertion fails. Successful tests join the worker.
        self.client.worker_handle.abort();
    }
}

async fn read_message(peer: &mut WebSocketStream<DuplexStream>) -> JSONRPCMessage {
    let Message::Text(text) = peer.next().await.expect("frame").expect("valid frame") else {
        panic!("expected JSON text");
    };
    serde_json::from_str(&text).expect("JSON-RPC")
}

async fn send_message(peer: &mut WebSocketStream<DuplexStream>, message: JSONRPCMessage) {
    peer.send(Message::Text(
        serde_json::to_string(&message).expect("JSON-RPC").into(),
    ))
    .await
    .expect("write frame");
}

impl Fixture {
    async fn new() -> Self {
        let (stream, peer) = tokio::io::duplex(64 * 1024);
        let websocket =
            WebSocketStream::from_raw_socket(stream, Role::Client, /*config*/ None).await;
        let mut peer = WebSocketStream::from_raw_socket(peer, Role::Server, /*config*/ None).await;
        let args = RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::WebSocket {
                websocket_url: "ws://unused.test".to_string(),
                auth_token: None,
            },
            client_name: "pending-capacity-fixture".to_string(),
            client_version: "1".to_string(),
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: 8,
        };
        let connect = RemoteAppServerClient::connect_with_stream(
            args.channel_capacity,
            RemoteEventMode::Bounded { capacity: 16 },
            "in-memory".to_string(),
            websocket,
            args.initialize_params(),
        );
        let handshake = async {
            let JSONRPCMessage::Request(request) = read_message(&mut peer).await else {
                panic!("initialize request");
            };
            assert_eq!(request.method, "initialize");
            send_message(
                &mut peer,
                JSONRPCMessage::Response(JSONRPCResponse {
                    id: request.id,
                    result: serde_json::json!({"userAgent": "test/1"}),
                }),
            )
            .await;
            let JSONRPCMessage::Notification(notification) = read_message(&mut peer).await else {
                panic!("initialized notification");
            };
            assert_eq!(notification.method, "initialized");
        };
        let (client, ()) = tokio::join!(connect, handshake);
        Self {
            client: client.expect("initialized client"),
            peer,
        }
    }

    async fn enqueue(&self, id: i64, method: &str) -> ResponseReceiver {
        let (response_tx, response_rx) = oneshot::channel();
        self.client
            .command_tx
            .send(RemoteClientCommand::Request {
                request: Box::new(JSONRPCRequest {
                    id: RequestId::Integer(id),
                    method: method.to_string(),
                    params: None,
                    trace: None,
                }),
                response_tx,
            })
            .await
            .expect("enqueue request");
        response_rx
    }

    async fn expect_request(&mut self, id: i64, method: &str) {
        let JSONRPCMessage::Request(request) = read_message(&mut self.peer).await else {
            panic!("request frame");
        };
        assert_eq!(
            request,
            JSONRPCRequest {
                id: RequestId::Integer(id),
                method: method.to_string(),
                params: None,
                trace: None,
            }
        );
    }

    async fn fill(&mut self) -> Vec<ResponseReceiver> {
        let mut responses = Vec::new();
        for id in 0..MAX_PENDING_REMOTE_REQUESTS as i64 {
            responses.push(self.enqueue(id, "test/pending").await);
            self.expect_request(id, "test/pending").await;
        }
        responses
    }

    async fn reply(&mut self, id: i64) {
        send_message(
            &mut self.peer,
            JSONRPCMessage::Response(JSONRPCResponse {
                id: RequestId::Integer(id),
                result: serde_json::json!({"replyTo": id}),
            }),
        )
        .await;
    }

    async fn marker(&mut self) {
        self.client
            .notify(ClientNotification::Initialized)
            .await
            .expect("notifications bypass request capacity");
        let JSONRPCMessage::Notification(notification) = read_message(&mut self.peer).await else {
            panic!("rejected requests must not precede the FIFO notification marker");
        };
        assert_eq!(notification.method, "initialized");
    }

    async fn close(&mut self) {
        self.peer.close(/*frame*/ None).await.expect("peer close");
        (&mut self.client.worker_handle)
            .await
            .expect("worker joined");
    }
}

#[tokio::test]
async fn pending_capacity_rejects_before_send_preserves_duplicates_and_releases_on_reply() {
    timeout(Duration::from_secs(30), async {
        let mut fixture = Fixture::new().await;
        let mut responses = fixture.fill().await;
        let original = responses.pop().expect("last waiter");
        let id = MAX_PENDING_REMOTE_REQUESTS as i64 - 1;
        let duplicate = fixture.enqueue(id, "test/duplicate").await;
        assert_eq!(
            duplicate.await.unwrap().unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
        // A control/cancellation RPC has no implicit reservation or priority.
        let rejected = fixture.enqueue(10_000, "turn/interrupt").await;
        assert_eq!(
            rejected.await.unwrap().unwrap_err().kind(),
            ErrorKind::WouldBlock
        );
        fixture.marker().await;
        fixture.reply(id).await;
        assert_eq!(
            original.await.unwrap().unwrap().unwrap(),
            serde_json::json!({"replyTo": id})
        );
        // Removal occurs before waking the original waiter, so immediate ID
        // reuse and the N-1 -> N capacity transition both succeed.
        let replacement = fixture.enqueue(id, "test/reuse").await;
        fixture.expect_request(id, "test/reuse").await;
        let rejected_again = fixture.enqueue(10_001, "test/over-cap").await;
        assert_eq!(
            rejected_again.await.unwrap().unwrap_err().kind(),
            ErrorKind::WouldBlock
        );
        fixture.marker().await;
        let error = JSONRPCErrorError {
            code: -32000,
            message: "fixture rejection".to_string(),
            data: None,
        };
        send_message(
            &mut fixture.peer,
            JSONRPCMessage::Error(JSONRPCError {
                id: RequestId::Integer(id),
                error: error.clone(),
            }),
        )
        .await;
        assert_eq!(replacement.await.unwrap().unwrap().unwrap_err(), error);
        let after_error = fixture.enqueue(id, "test/after-error").await;
        fixture.expect_request(id, "test/after-error").await;
        fixture.reply(id).await;
        assert_eq!(
            after_error.await.unwrap().unwrap().unwrap(),
            serde_json::json!({"replyTo": id})
        );
        fixture.close().await;
        for response in responses {
            assert!(response.await.unwrap().is_err());
        }
    })
    .await
    .expect("capacity test deadline");
}

#[tokio::test]
async fn abandoned_sent_ids_keep_capacity_until_late_reply_without_misdelivery() {
    timeout(Duration::from_secs(30), async {
        let mut fixture = Fixture::new().await;
        let mut responses = fixture.fill().await;
        let unrelated_id = MAX_PENDING_REMOTE_REQUESTS as i64 - 1;
        let unrelated = responses.pop().expect("unrelated live waiter");
        // Every request was peer-observed before dropping its response receiver.
        drop(responses);
        let reuse = fixture.enqueue(0, "test/premature-reuse").await;
        assert_eq!(
            reuse.await.unwrap().unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
        let rejected = fixture.enqueue(10_000, "test/over-cap").await;
        assert_eq!(
            rejected.await.unwrap().unwrap_err().kind(),
            ErrorKind::WouldBlock
        );
        fixture.marker().await;
        fixture.reply(0).await;
        fixture.reply(unrelated_id).await;
        // FIFO inbound processing makes this a barrier after the abandoned reply.
        assert_eq!(
            unrelated.await.unwrap().unwrap().unwrap(),
            serde_json::json!({"replyTo": unrelated_id})
        );
        let reused = fixture.enqueue(0, "test/reuse").await;
        fixture.expect_request(0, "test/reuse").await;
        let mut reused = reused;
        assert!(matches!(
            reused.try_recv(),
            Err(oneshot::error::TryRecvError::Empty)
        ));
        fixture.reply(0).await;
        assert_eq!(
            reused.await.unwrap().unwrap().unwrap(),
            serde_json::json!({"replyTo": 0})
        );
        fixture.close().await;
    })
    .await
    .expect("abandoned-ID test deadline");
}

#[tokio::test]
async fn saturated_requests_do_not_block_server_resolutions_or_owner_shutdown() {
    timeout(Duration::from_secs(30), async {
        let mut fixture = Fixture::new().await;
        let responses = fixture.fill().await;
        fixture
            .client
            .resolve_server_request(
                RequestId::Integer(-1),
                serde_json::json!({"resolved": true}),
            )
            .await
            .expect("server response bypasses request capacity");
        let JSONRPCMessage::Response(response) = read_message(&mut fixture.peer).await else {
            panic!("server response frame");
        };
        assert_eq!(
            response,
            JSONRPCResponse {
                id: RequestId::Integer(-1),
                result: serde_json::json!({"resolved": true}),
            }
        );
        let error = JSONRPCErrorError {
            code: -32601,
            message: "fixture rejection".to_string(),
            data: None,
        };
        fixture
            .client
            .reject_server_request(RequestId::Integer(-2), error.clone())
            .await
            .expect("server error bypasses request capacity");
        let JSONRPCMessage::Error(rejection) = read_message(&mut fixture.peer).await else {
            panic!("server error frame");
        };
        assert_eq!(
            rejection,
            JSONRPCError {
                id: RequestId::Integer(-2),
                error,
            }
        );
        // Exercise the real Shutdown command and join; the pending budget must
        // not reserve a slot for shutdown. This does not claim a bounded time
        // when the pre-existing transport write or command queue is blocked.
        let (response_tx, response_rx) = oneshot::channel();
        fixture
            .client
            .command_tx
            .send(RemoteClientCommand::Shutdown { response_tx })
            .await
            .expect("shutdown enqueue");
        response_rx.await.unwrap().expect("shutdown close");
        (&mut fixture.client.worker_handle)
            .await
            .expect("worker joined");
        for response in responses {
            assert_eq!(
                response.await.unwrap().unwrap_err().kind(),
                ErrorKind::BrokenPipe
            );
        }
        let result = fixture
            .client
            .request_handle()
            .request_json_rpc(JSONRPCRequest {
                id: RequestId::Integer(0),
                method: "test/after-close".to_string(),
                params: None,
                trace: None,
            })
            .await;
        assert_eq!(result.unwrap_err().kind(), ErrorKind::BrokenPipe);
    })
    .await
    .expect("shutdown test deadline");
}
