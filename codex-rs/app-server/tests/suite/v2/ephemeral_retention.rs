use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ThreadEphemeralRetainResponse;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::ThreadUnsubscribeResponse;
use codex_app_server_protocol::ThreadUnsubscribeStatus;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;

use super::connection_handling_websocket::connect_websocket;
use super::connection_handling_websocket::read_error_for_id;
use super::connection_handling_websocket::read_response_for_id;
use super::connection_handling_websocket::send_initialize_request;
use super::connection_handling_websocket::send_request;
use super::connection_handling_websocket::spawn_websocket_server;

#[tokio::test]
async fn ephemeral_retention_v1_requires_same_session_operation_and_loaded_ephemeral_runtime()
-> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let (mut process, address) = spawn_websocket_server(home.path()).await?;
    let mut client = connect_websocket(address).await?;
    send_initialize_request(&mut client, /*id*/ 1, "retention-owner").await?;
    read_response_for_id(&mut client, /*id*/ 1).await?;
    send_request(&mut client, "thread/start", /*id*/ 2, Some(json!({}))).await?;
    let persistent: ThreadStartResponse =
        serde_json::from_value(read_response_for_id(&mut client, /*id*/ 2).await?.result)?;
    send_request(
        &mut client,
        "thread/start",
        /*id*/ 3,
        Some(json!({"ephemeral":true})),
    )
    .await?;
    let ephemeral: ThreadStartResponse =
        serde_json::from_value(read_response_for_id(&mut client, /*id*/ 3).await?.result)?;
    let thread = ephemeral.thread;
    for (version, thread_id, session_id) in [
        (1, &persistent.thread.id, &persistent.thread.session_id),
        (1, &thread.id, &persistent.thread.session_id),
        (0, &thread.id, &thread.session_id),
    ] {
        send_request(
            &mut client,
            "thread/ephemeral/retain",
            /*id*/ 4,
            Some(json!({
                "protocolVersion":version,"threadId":thread_id,"expectedSessionId":session_id,
                "operationId":"native.request.v1:original"
            })),
        )
        .await?;
        let rejected = read_error_for_id(&mut client, /*id*/ 4).await?;
        assert_eq!(rejected.error.code, -32600);
    }
    for _ in 0..2 {
        send_request(
            &mut client,
            "thread/ephemeral/retain",
            /*id*/ 5,
            Some(json!({
                "protocolVersion":1,"threadId":thread.id,"expectedSessionId":thread.session_id,
                "operationId":"native.request.v1:original"
            })),
        )
        .await?;
        let acknowledged: ThreadEphemeralRetainResponse =
            serde_json::from_value(read_response_for_id(&mut client, /*id*/ 5).await?.result)?;
        assert_eq!(
            acknowledged,
            ThreadEphemeralRetainResponse {
                protocol_version: 1,
                thread_id: thread.id.clone(),
                session_id: thread.session_id.clone(),
                operation_id: "native.request.v1:original".into(),
            }
        );
    }
    send_request(
        &mut client,
        "thread/ephemeral/retain",
        /*id*/ 6,
        Some(json!({
            "protocolVersion":1,"threadId":thread.id,"expectedSessionId":thread.session_id,
            "operationId":"native.request.v1:replacement"
        })),
    )
    .await?;
    let rejected = read_error_for_id(&mut client, /*id*/ 6).await?;
    assert!(
        rejected
            .error
            .message
            .contains("another runtime or operation")
    );
    // Connection loss must not release residency or its bounded capacity. A
    // new cleanup connection can still dispose only this exact original Core
    // session after its independent native terminal/ACK gate has settled.
    send_request(
        &mut client,
        "thread/unsubscribe",
        /*id*/ 7,
        Some(json!({"threadId":thread.id})),
    )
    .await?;
    let ordinary: ThreadUnsubscribeResponse =
        serde_json::from_value(read_response_for_id(&mut client, /*id*/ 7).await?.result)?;
    assert_eq!(ordinary.status, ThreadUnsubscribeStatus::Unsubscribed);
    client.close(None).await?;
    let mut recovery = connect_websocket(address).await?;
    send_initialize_request(&mut recovery, /*id*/ 1, "retention-recovery").await?;
    read_response_for_id(&mut recovery, /*id*/ 1).await?;
    send_request(
        &mut recovery,
        "thread/unsubscribe",
        /*id*/ 2,
        Some(json!({
            "threadId":thread.id,"ephemeralDisposal":{"expectedSessionId":thread.session_id}
        })),
    )
    .await?;
    let disposed: ThreadUnsubscribeResponse =
        serde_json::from_value(read_response_for_id(&mut recovery, /*id*/ 2).await?.result)?;
    assert_eq!(disposed.status, ThreadUnsubscribeStatus::EphemeralDisposed);
    process.kill().await?;
    Ok(())
}
