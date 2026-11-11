use super::ExecServerClient;
use super::ExecServerClientConnectOptions;
use super::SessionState;
use super::tests::read_jsonrpc_line;
use super::tests::write_jsonrpc_line;
use crate::ExecProcessEvent;
use crate::connection::JsonRpcConnection;
use crate::protocol::ByteChunk;
use crate::protocol::ExecOutputStream;
use crate::protocol::INITIALIZE_METHOD;
use crate::protocol::ProcessOutputChunk;
use crate::protocol::ReadResponse;
use codex_exec_server_protocol::JSONRPCMessage;
use codex_exec_server_protocol::JSONRPCResponse;
use pretty_assertions::assert_eq;
use tokio::io::AsyncBufReadExt;
use tokio::io::BufReader;
use tokio::io::duplex;
use tokio::time::Duration;
use tokio::time::timeout;

#[test]
fn transport_failure_without_native_observation_is_not_closed() {
    let state = SessionState::new(false);
    state.set_failure("transport lost".to_string());
    let response = state.failed_response().expect("failure response");
    assert_eq!(response.failure.as_deref(), Some("transport lost"));
    assert!(!response.exited);
    assert_eq!(response.exit_code, None);
    assert!(!response.closed);
}

#[test]
fn failure_preserves_observed_exit_with_or_without_numeric_code() {
    for code in [None, Some(17)] {
        let state = SessionState::new(false);
        state.observe_read_response(&ReadResponse {
            chunks: vec![],
            next_seq: 3,
            exited: true,
            exit_code: code,
            closed: false,
            failure: None,
            sandbox_denied: false,
        });
        state.set_failure("transport lost after exit".to_string());
        let response = state.failed_response().expect("failure response");
        assert!(response.exited);
        assert_eq!(response.exit_code, code);
        assert!(!response.closed);
    }
}

#[tokio::test]
async fn unknown_notification_keeps_output_order_and_actual_exit_events() {
    tokio::time::timeout(std::time::Duration::from_secs(1), async {
    let state = SessionState::new(false);
    let mut events = state.subscribe_events();
    let output = |seq, bytes: &[u8]| ExecProcessEvent::Output(ProcessOutputChunk {
        seq, stream: ExecOutputStream::Stdout, chunk: ByteChunk(bytes.to_vec()),
    });
    assert!(!state.publish_ordered_event(output(2, b"tail")).expect("queue tail"));
    state.set_observation_failure("process exit observation lost".to_string());
    assert!(matches!(events.recv().await, Ok(ExecProcessEvent::Failed(_))));
    let unknown = state.synthesized_failure("observation lost".to_string());
    assert!(!unknown.exited);
    assert_eq!(unknown.exit_code, None);
    assert!(!unknown.closed);
    assert!(!state.publish_ordered_event(output(1, b"head")).expect("queue head"));
    assert!(matches!(events.recv().await, Ok(ExecProcessEvent::Output(chunk)) if chunk.seq == 1 && chunk.chunk.0 == b"head"));
    assert!(matches!(events.recv().await, Ok(ExecProcessEvent::Output(chunk)) if chunk.seq == 2 && chunk.chunk.0 == b"tail"));
    assert!(!state.publish_ordered_event(ExecProcessEvent::Exited {
        seq: 3, exit_code: 19, sandbox_denied: Some(false),
    }).expect("actual exited event"));
    assert!(matches!(events.recv().await, Ok(ExecProcessEvent::Exited { exit_code: 19, .. })));
    assert!(state.publish_ordered_event(ExecProcessEvent::Closed { seq: 4 }).expect("actual closed event"));
    assert!(matches!(events.recv().await, Ok(ExecProcessEvent::Closed { seq: 4 })));
    let final_read = state.synthesized_failure("original observation failure".to_string());
    assert!(final_read.exited);
    assert_eq!(final_read.exit_code, Some(19));
    assert!(final_read.closed);
    }).await.expect("original client event observation budget");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn legacy_server_is_rejected_before_process_admission() {
    let (client_stdin, server_reader) = duplex(1 << 20);
    let (mut server_writer, client_stdout) = duplex(1 << 20);
    let (done_tx, done_rx) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let mut lines = BufReader::new(server_reader).lines();
        let JSONRPCMessage::Request(request) = read_jsonrpc_line(&mut lines).await else {
            panic!("expected initialize request");
        };
        assert_eq!(request.method, INITIALIZE_METHOD);
        let params: crate::protocol::InitializeParams =
            serde_json::from_value(request.params.expect("initialize params"))
                .expect("typed params");
        assert!(params.process_exit_observation);
        write_jsonrpc_line(
            &mut server_writer,
            JSONRPCMessage::Response(JSONRPCResponse {
                id: request.id,
                // The legacy wire response deliberately omits the capability.
                result: serde_json::json!({"sessionId": "legacy-session"}),
            }),
        )
        .await;
        done_rx.await.expect("client finished handshake");
    });
    let result = ExecServerClient::connect(
        JsonRpcConnection::from_stdio(client_stdout, client_stdin, "legacy-peer".to_string()),
        ExecServerClientConnectOptions::default(),
    )
    .await;
    assert!(
        matches!(result, Err(super::ExecServerError::Protocol(message)) if message == "exec-server does not support process exit observation")
    );
    done_tx.send(()).expect("release legacy fixture");
    timeout(Duration::from_secs(1), server)
        .await
        .expect("fixture deadline")
        .expect("fixture task");
}
