use std::io::Result as IoResult;

use pretty_assertions::assert_eq;
use tokio::io::DuplexStream;
use tokio_tungstenite::tungstenite::protocol::Role;

use super::*;

async fn read_message(stream: &mut WebSocketStream<DuplexStream>) -> IoResult<serde_json::Value> {
    let message = stream
        .next()
        .await
        .ok_or_else(|| IoError::other("mock connection closed"))?
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

#[tokio::test]
async fn process_spawn_checks_this_connection_echo_and_decodes_unknown_notifications()
-> IoResult<()> {
    timeout(Duration::from_secs(5), async {
        for echo in [None, Some(false), Some(true)] {
            let (client_io, server_io) = tokio::io::duplex(16384);
            let client_stream = WebSocketStream::from_raw_socket(client_io, Role::Client, None).await;
            let mut server_stream = WebSocketStream::from_raw_socket(server_io, Role::Server, None).await;
            let server = tokio::spawn(async move {
                let initialize = read_message(&mut server_stream).await?;
                assert_eq!(initialize["method"], "initialize");
                assert_eq!(initialize["params"]["capabilities"]["processIndeterminate"], true);
                let mut result = serde_json::json!({"userAgent": "fixture/1"});
                if let Some(echo) = echo { result["processIndeterminate"] = serde_json::json!(echo); }
                send_message(&mut server_stream, serde_json::json!({
                    "id": initialize["id"], "result": result
                })).await?;
                assert_eq!(read_message(&mut server_stream).await?["method"], "initialized");
                let request = read_message(&mut server_stream).await?;
                let expected_method = if echo == Some(true) { "process/spawn" } else { "server/diagnostics" };
                assert_eq!(request["method"], expected_method);
                send_message(&mut server_stream, serde_json::json!({"id": request["id"], "result": {}})).await?;
                if echo == Some(true) {
                    send_message(&mut server_stream, serde_json::json!({
                        "method": "process/indeterminate",
                        "params": {"processHandle": "fixture", "reason": "exitObservationLost",
                            "stdout": "seen", "stdoutCapReached": false, "stderr": "", "stderrCapReached": false}
                    })).await?;
                }
                Ok::<(), IoError>(())
            });
            let mut client = RemoteAppServerClient::connect_with_stream(
                1, RemoteEventMode::Unbounded, "in-memory-fixture".to_string(), client_stream,
                InitializeParams {
                    client_info: ClientInfo { name: "typed-process-client".to_string(), title: None, version: "1".to_string() },
                    capabilities: Some(InitializeCapabilities {
                        experimental_api: true, process_indeterminate: true, ..Default::default()
                    }),
                },
            ).await?;
            let spawn = client.request_handle().request_json_rpc(JSONRPCRequest {
                id: RequestId::Integer(1), method: "process/spawn".to_string(),
                params: Some(serde_json::json!({"processHandle": "fixture", "command": ["not-executed"], "cwd": "/fixture"})),
            }).await;
            if echo == Some(true) {
                assert_eq!(spawn?.map_err(|error| IoError::other(error.message))?, serde_json::json!({}));
                let Some(AppServerEvent::ServerNotification(notification)) = client.next_event().await else {
                    return Err(IoError::other("missing typed indeterminate observation"));
                };
                assert_eq!(serde_json::to_value(notification).map_err(IoError::other)?, serde_json::json!({
                    "method": "process/indeterminate",
                    "params": {"processHandle": "fixture", "reason": "exitObservationLost",
                        "stdout": "seen", "stdoutCapReached": false, "stderr": "", "stderrCapReached": false}
                }));
            } else {
                let error = match spawn {
                    Err(error) => error,
                    Ok(_) => return Err(IoError::other("legacy server received process/spawn")),
                };
                assert_eq!(error.kind(), ErrorKind::Unsupported);
                // A real subsequent frame proves the rejected spawn was never written.
                client.request_handle().request_json_rpc(JSONRPCRequest {
                    id: RequestId::Integer(2), method: "server/diagnostics".to_string(), params: None,
                }).await?.map_err(|error| IoError::other(error.message))?;
            }
            server.await.map_err(IoError::other)??;
            client.shutdown().await?;
        }
        Ok::<(), IoError>(())
    }).await.map_err(IoError::other)?
}
