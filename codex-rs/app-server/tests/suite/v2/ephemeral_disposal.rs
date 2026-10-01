use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ThreadEphemeralDisposalParams;
use codex_app_server_protocol::ThreadLoadedListParams;
use codex_app_server_protocol::ThreadLoadedListResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use codex_app_server_protocol::ThreadUnsubscribeResponse;
use codex_app_server_protocol::ThreadUnsubscribeStatus;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_features::Feature;
use core_test_support::responses;
use core_test_support::streaming_sse::StreamingSseChunk;
use core_test_support::streaming_sse::start_streaming_sse_server;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::connection_handling_websocket::connect_websocket;
use super::connection_handling_websocket::read_error_for_id;
use super::connection_handling_websocket::read_response_for_id;
use super::connection_handling_websocket::send_initialize_request;
use super::connection_handling_websocket::send_request;
use super::connection_handling_websocket::spawn_websocket_server;

#[tokio::test]
async fn ephemeral_disposal_requires_exact_idle_session_and_keeps_persistent_thread() -> Result<()>
{
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let mut client = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let persistent = client
        .start_thread(ThreadStartParams::default())
        .await?
        .thread;
    let ephemeral = client
        .start_thread(ThreadStartParams {
            ephemeral: Some(true),
            ..Default::default()
        })
        .await?
        .thread;
    for (thread_id, session_id) in [
        (&persistent.id, &persistent.session_id),
        (&ephemeral.id, &persistent.session_id),
    ] {
        let rejected = client
            .request::<ThreadUnsubscribeResponse>(|request_id| ClientRequest::ThreadUnsubscribe {
                request_id,
                params: ThreadUnsubscribeParams {
                    thread_id: thread_id.clone(),
                    ephemeral_disposal: Some(ThreadEphemeralDisposalParams {
                        expected_session_id: session_id.clone(),
                    }),
                },
            })
            .await;
        assert!(
            rejected.is_err(),
            "persistent/wrong-session disposal must fail"
        );
    }
    let disposed: ThreadUnsubscribeResponse = client
        .request(|request_id| ClientRequest::ThreadUnsubscribe {
            request_id,
            params: ThreadUnsubscribeParams {
                thread_id: ephemeral.id.clone(),
                ephemeral_disposal: Some(ThreadEphemeralDisposalParams {
                    expected_session_id: ephemeral.session_id.clone(),
                }),
            },
        })
        .await?;
    assert_eq!(
        disposed,
        ThreadUnsubscribeResponse {
            status: ThreadUnsubscribeStatus::EphemeralDisposed,
        }
    );
    let loaded: ThreadLoadedListResponse = client
        .request(|request_id| ClientRequest::ThreadLoadedList {
            request_id,
            params: ThreadLoadedListParams::default(),
        })
        .await?;
    assert_eq!(
        loaded,
        ThreadLoadedListResponse {
            data: vec![persistent.id],
            next_cursor: None,
        }
    );
    let replay: ThreadUnsubscribeResponse = client
        .request(|request_id| ClientRequest::ThreadUnsubscribe {
            request_id,
            params: ThreadUnsubscribeParams {
                thread_id: ephemeral.id,
                ephemeral_disposal: Some(ThreadEphemeralDisposalParams {
                    expected_session_id: ephemeral.session_id,
                }),
            },
        })
        .await?;
    assert_eq!(replay.status, ThreadUnsubscribeStatus::NotLoaded);
    Ok(())
}

#[tokio::test]
async fn ephemeral_disposal_refuses_active_turn_then_disposes_after_true_completion() -> Result<()>
{
    let (gate_tx, gate_rx) = tokio::sync::oneshot::channel();
    let (server, _) = start_streaming_sse_server(vec![vec![StreamingSseChunk {
        gate: Some(gate_rx),
        body: responses::sse(vec![
            responses::ev_response_created("response-1"),
            responses::ev_assistant_message("message-1", "Done"),
            responses::ev_completed("response-1"),
        ]),
    }]])
    .await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(server.uri()).write(home.path())?;
    let mut client = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let thread = client
        .start_thread(ThreadStartParams {
            ephemeral: Some(true),
            ..Default::default()
        })
        .await?
        .thread;
    let started: TurnStartResponse = client
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread.id.clone(),
                input: vec![UserInput::Text {
                    text: "Finish this test turn".to_owned(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    server.wait_for_request_count(/*count*/ 1).await;
    let rejected = client
        .request::<ThreadUnsubscribeResponse>(|request_id| ClientRequest::ThreadUnsubscribe {
            request_id,
            params: ThreadUnsubscribeParams {
                thread_id: thread.id.clone(),
                ephemeral_disposal: Some(ThreadEphemeralDisposalParams {
                    expected_session_id: thread.session_id.clone(),
                }),
            },
        })
        .await;
    assert!(
        rejected.is_err(),
        "an active original turn must remain running"
    );
    gate_tx
        .send(())
        .expect("original provider request is still live");
    let completed: TurnCompletedNotification = client.read_notification("turn/completed").await?;
    assert_eq!(completed.thread_id, thread.id);
    assert_eq!(completed.turn.id, started.turn.id);
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    let disposed: ThreadUnsubscribeResponse = client
        .request(|request_id| ClientRequest::ThreadUnsubscribe {
            request_id,
            params: ThreadUnsubscribeParams {
                thread_id: thread.id,
                ephemeral_disposal: Some(ThreadEphemeralDisposalParams {
                    expected_session_id: thread.session_id,
                }),
            },
        })
        .await?;
    assert_eq!(disposed.status, ThreadUnsubscribeStatus::EphemeralDisposed);
    Ok(())
}

#[tokio::test]
async fn ephemeral_disposal_keeps_a_session_until_its_other_subscriber_unsubscribes() -> Result<()>
{
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .disable_feature(Feature::RealtimeConversation)
        .write(home.path())?;
    let (mut process, address) = spawn_websocket_server(home.path()).await?;
    let mut owner = connect_websocket(address).await?;
    let mut observer = connect_websocket(address).await?;
    send_initialize_request(&mut owner, /*id*/ 1, "ephemeral-owner").await?;
    read_response_for_id(&mut owner, /*id*/ 1).await?;
    send_initialize_request(&mut observer, /*id*/ 1, "ephemeral-observer").await?;
    read_response_for_id(&mut observer, /*id*/ 1).await?;
    send_request(
        &mut owner,
        "thread/start",
        /*id*/ 2,
        Some(serde_json::json!({"ephemeral":true})),
    )
    .await?;
    let started: ThreadStartResponse =
        serde_json::from_value(read_response_for_id(&mut owner, /*id*/ 2).await?.result)?;
    let thread = started.thread;
    send_request(
        &mut observer,
        "thread/realtime/start",
        /*id*/ 2,
        Some(serde_json::json!({"threadId":thread.id,"outputModality":"text"})),
    )
    .await?;
    // Ephemeral threads have no rollout to resume. Realtime preparation uses
    // the existing live-session listener before checking its feature gate;
    // the disabled operation never starts a provider session, but the actual
    // observer subscription remains until ordinary unsubscribe.
    let realtime = read_error_for_id(&mut observer, /*id*/ 2).await?;
    assert!(realtime.error.message.contains("does not support realtime"));
    let disposal = serde_json::json!({"threadId":thread.id,
        "ephemeralDisposal":{"expectedSessionId":thread.session_id}});
    send_request(
        &mut owner,
        "thread/unsubscribe",
        /*id*/ 3,
        Some(disposal.clone()),
    )
    .await?;
    let rejected = read_error_for_id(&mut owner, /*id*/ 3).await?;
    assert!(rejected.error.message.contains("another subscriber"));
    send_request(
        &mut observer,
        "thread/unsubscribe",
        /*id*/ 3,
        Some(serde_json::json!({"threadId":thread.id})),
    )
    .await?;
    let unsubscribed: ThreadUnsubscribeResponse =
        serde_json::from_value(read_response_for_id(&mut observer, /*id*/ 3).await?.result)?;
    assert_eq!(unsubscribed.status, ThreadUnsubscribeStatus::Unsubscribed);
    send_request(
        &mut owner,
        "thread/unsubscribe",
        /*id*/ 4,
        Some(disposal),
    )
    .await?;
    let disposed: ThreadUnsubscribeResponse =
        serde_json::from_value(read_response_for_id(&mut owner, /*id*/ 4).await?.result)?;
    assert_eq!(disposed.status, ThreadUnsubscribeStatus::EphemeralDisposed);
    process.kill().await?;
    Ok(())
}
