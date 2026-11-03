//! Product-path qualification uses the real HTTP adapter and actual private recovery store.
#![cfg(all(target_os = "linux", feature = "http"))]
use crate::client::RuntimeClient;
use crate::contract::{Action, ConfirmationInput, Method};
use crate::ledger::OperationState;
use crate::{ErrorCode, FileRecoveryStore, HttpTransport, MemoryCredentials, RecoveryScope};
use pretty_assertions::assert_eq;
use serde_json::{Value, json};
use std::io::{Read, Write};
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt;
use std::thread;
use std::time::Duration;

#[test]
fn real_http_response_loss_restart_and_query_only_recovery_never_repeat_mutation() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let endpoint = format!("http://{address}/api/ui-control/v1/");
    let server = thread::spawn(move || {
        let mut admission: Option<Value> = None;
        let mut mutations = 0;
        for _ in 0..7 {
            let (mut socket, _) = listener.accept().unwrap();
            socket
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut bytes = Vec::new();
            let mut block = [0; 4096];
            let (headers, body) = loop {
                let n = socket.read(&mut block).unwrap();
                bytes.extend_from_slice(&block[..n]);
                if let Some(split) = bytes.windows(4).position(|value| value == b"\r\n\r\n") {
                    let headers = String::from_utf8(bytes[..split].to_vec()).unwrap();
                    let len = headers
                        .lines()
                        .find_map(|line| {
                            line.to_lowercase()
                                .strip_prefix("content-length: ")
                                .map(str::to_owned)
                        })
                        .map_or(0, |len| len.parse::<usize>().unwrap());
                    if bytes.len() >= split + 4 + len {
                        break (headers, bytes[split + 4..split + 4 + len].to_vec());
                    }
                }
            };
            let path = headers
                .lines()
                .next()
                .unwrap()
                .split_whitespace()
                .nth(1)
                .unwrap();
            let response = if path.ends_with("session/connect") {
                json!({"authenticated":true,"protocolVersion":"hepta.ui-control.v1","sessionId":"session.real","identityId":"operator.real",
                    "connectionGeneration":1,"permissionRevision":1,"expiresAt":999_999_999_999_999_u64,
                    "permissions":["hepta://ui.control/runtime.read","hepta://ui.control/runtime.stop"]})
            } else if path.ends_with("/view") {
                json!({"sessionId":"session.real","connectionGeneration":1,"generation":1,"revision":1,
                    "modules":[{"id":"runtime.agentd","status":"ready","revision":1,"semanticDigest":"a".repeat(64)}]})
            } else if path.ends_with("/operations") {
                mutations += 1;
                admission = Some(serde_json::from_slice(&body).unwrap());
                // The authoritative backend admitted the operation but its ACK was lost.
                continue;
            } else if path.contains("/operations/") {
                let admitted = admission.as_ref().unwrap();
                json!({"found":true,"operationId":admitted["operationId"],"semanticDigest":admitted["semanticDigest"],
                    "status":"succeeded","auditTraceId":"audit.real","outcomeDigest":"b".repeat(64)})
            } else if path.ends_with("session/close") {
                json!({"closed":true})
            } else {
                panic!("unexpected route {path}")
            };
            let encoded = serde_json::to_vec(&response).unwrap();
            write!(socket,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",encoded.len()).unwrap();
            socket.write_all(&encoded).unwrap();
        }
        mutations
    });
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let scope = RecoveryScope {
        endpoint: endpoint.clone(),
        protocol_version: "hepta.ui-control.v1".into(),
        identity_id: "operator.real".into(),
    };
    let make_client = || {
        let credentials =
            MemoryCredentials::new("session=owned-test".into(), "csrf-owned-test".into()).unwrap();
        RuntimeClient::new(
            HttpTransport::new(&endpoint, credentials, Duration::from_secs(2)).unwrap(),
            FileRecoveryStore::open(directory.path(), scope.clone(), 1024).unwrap(),
            1024,
        )
        .unwrap()
    };
    let mut client = make_client();
    client.connect(&json!({})).unwrap();
    client.refresh_view().unwrap();
    let input = ConfirmationInput {
        operation_id: "op.real".into(),
        action: Action::RequestStop,
        target_id: "runtime.agentd".into(),
        reason: "Owned qualification".into(),
    };
    let confirmation = client.capture_confirmation(&input).unwrap();
    assert_eq!(
        client
            .submit(Method::Stop, input, &confirmation)
            .unwrap_err()
            .code,
        ErrorCode::AmbiguousSubmission
    );
    client.close().unwrap();
    drop(client);
    let mut reopened = make_client();
    reopened.connect(&json!({})).unwrap();
    assert_eq!(
        reopened.view().unwrap().pending[0].state,
        OperationState::Indeterminate
    );
    let result = reopened.recover_operation("op.real").unwrap();
    assert_eq!(result.state, OperationState::Terminal);
    reopened.close().unwrap();
    assert_eq!(server.join().unwrap(), 1);
}
