use anyhow::Context;
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_sequence;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ThreadGoalSetParams;
use codex_app_server_protocol::ThreadGoalSetResponse;
use codex_app_server_protocol::ThreadGoalStatus;
use codex_app_server_protocol::ThreadQueueAddParams;
use codex_app_server_protocol::ThreadQueueAddResponse;
use codex_app_server_protocol::ThreadQueueListParams;
use codex_app_server_protocol::ThreadQueueListResponse;
use codex_app_server_protocol::ThreadStartParams;
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
use std::time::Duration;
use tempfile::TempDir;
use tokio::sync::oneshot;
use tokio::time::timeout;

const READ_TIMEOUT: Duration = Duration::from_secs(10);

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_notification_allows_immediate_next_turn() -> Result<()> {
    let responses = (0..6)
        .map(|index| {
            let id = format!("ready-response-{index}");
            responses::sse(vec![
                responses::ev_response_created(&id),
                responses::ev_completed(&id),
            ])
        })
        .collect();
    let server = create_mock_responses_server_sequence(responses).await;
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(codex_home.path())?;
    let mut app = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let started = app.start_thread(ThreadStartParams::default()).await?;
    let mut previous_id = None;
    for index in 0..6 {
        // No sleeps, readiness polling, NotIdle retries or steering fallbacks:
        // the preceding public completion must be sufficient for a fresh turn.
        let response: TurnStartResponse = app
            .request(|request_id| ClientRequest::TurnStart {
                request_id,
                params: TurnStartParams {
                    thread_id: started.thread.id.clone(),
                    input: vec![UserInput::Text {
                        text: format!("next turn {index}"),
                        text_elements: Vec::new(),
                    }],
                    ..Default::default()
                },
            })
            .await?;
        assert_ne!(previous_id.as_ref(), Some(&response.turn.id));
        let notification = timeout(
            READ_TIMEOUT,
            app.read_stream_until_notification_message("turn/completed"),
        )
        .await??;
        let completed: TurnCompletedNotification =
            serde_json::from_value(notification.params.context("turn/completed parameters")?)?;
        assert_eq!(completed.thread_id, started.thread.id);
        assert_eq!(completed.turn.id, response.turn.id);
        assert_eq!(completed.turn.status, TurnStatus::Completed);
        previous_id = Some(response.turn.id);
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn goal_idle_wake_requests_continuation_after_finish_fence() -> Result<()> {
    let (first_release, first_gate) = oneshot::channel();
    let (next_release, next_gate) = oneshot::channel();
    let streams = [
        ("user-response", first_gate),
        ("goal-continuation", next_gate),
    ]
    .into_iter()
    .map(|(id, gate)| {
        vec![
            StreamingSseChunk {
                gate: None,
                body: responses::sse(vec![responses::ev_response_created(id)]),
            },
            StreamingSseChunk {
                gate: Some(gate),
                body: responses::sse(vec![responses::ev_completed_with_tokens(id, 100)]),
            },
        ]
    })
    .collect();
    let (server, _responses_complete) = start_streaming_sse_server(streams).await;
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(server.uri())
        .enable_feature(Feature::Goals)
        .write(codex_home.path())?;
    let mut app = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let started = app.start_thread(ThreadStartParams::default()).await?;
    let first: TurnStartResponse = app
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: started.thread.id.clone(),
                input: vec![UserInput::Text {
                    text: "Begin the goal".to_string(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    timeout(READ_TIMEOUT, server.wait_for_request_count(1)).await?;
    let _: ThreadGoalSetResponse = app
        .request(|request_id| ClientRequest::ThreadGoalSet {
            request_id,
            params: ThreadGoalSetParams {
                thread_id: started.thread.id.clone(),
                objective: Some("Continue after this turn".to_string()),
                status: Some(ThreadGoalStatus::Active),
                token_budget: Some(Some(1_000)),
            },
        })
        .await?;
    first_release
        .send(())
        .expect("first response remains gated");
    timeout(READ_TIMEOUT, server.wait_for_request_count(2))
        .await
        .context("goal continuation must issue an actual model request")?;
    // Pause while the second response is still gated, so the wake must read
    // fresh goal state and cannot schedule a third response after completion.
    let paused: ThreadGoalSetResponse = app
        .request(|request_id| ClientRequest::ThreadGoalSet {
            request_id,
            params: ThreadGoalSetParams {
                thread_id: started.thread.id.clone(),
                objective: None,
                status: Some(ThreadGoalStatus::Paused),
                token_budget: None,
            },
        })
        .await?;
    assert_eq!(paused.goal.status, ThreadGoalStatus::Paused);
    next_release
        .send(())
        .expect("continuation response remains gated");
    let mut ids = Vec::new();
    for _ in 0..2 {
        let notification = timeout(
            READ_TIMEOUT,
            app.read_stream_until_notification_message("turn/completed"),
        )
        .await??;
        let completed: TurnCompletedNotification =
            serde_json::from_value(notification.params.context("turn/completed parameters")?)?;
        assert_eq!(completed.thread_id, started.thread.id);
        assert_eq!(completed.turn.status, TurnStatus::Completed);
        ids.push(completed.turn.id);
    }
    assert_eq!(ids.first(), Some(&first.turn.id));
    assert_ne!(ids[0], ids[1]);
    assert_eq!(server.requests().await.len(), 2);
    server.shutdown().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn preexisting_user_queue_precedes_goal_continuation_after_completion() -> Result<()> {
    let mut releases = Vec::new();
    let streams = (0..4)
        .map(|index| {
            let (release, gate) = oneshot::channel();
            releases.push(release);
            let id = format!("queue-before-goal-{index}");
            vec![
                StreamingSseChunk {
                    gate: None,
                    body: responses::sse(vec![responses::ev_response_created(&id)]),
                },
                StreamingSseChunk {
                    gate: Some(gate),
                    body: responses::sse(vec![responses::ev_completed_with_tokens(&id, 100)]),
                },
            ]
        })
        .collect();
    let (server, _response_completion) = start_streaming_sse_server(streams).await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(server.uri())
        .enable_feature(Feature::Goals)
        .write(home.path())?;
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let started = app.start_thread(ThreadStartParams::default()).await?;
    let first: TurnStartResponse = app.request(|request_id| ClientRequest::TurnStart {
        request_id,
        params: TurnStartParams {
            thread_id: started.thread.id.clone(),
            input: vec![UserInput::Text { text: "initial user".to_string(), text_elements: Vec::new() }],
            ..Default::default()
        },
    }).await?;
    timeout(READ_TIMEOUT, server.wait_for_request_count(1)).await?;
    for (id, text) in [("queue-first", "first queued user"), ("queue-second", "second queued user")] {
        let _: ThreadQueueAddResponse = app.request(|request_id| ClientRequest::ThreadQueueAdd {
            request_id,
            params: ThreadQueueAddParams {
                thread_id: started.thread.id.clone(),
                client_user_message_id: id.to_string(),
                input: vec![UserInput::Text { text: text.to_string(), text_elements: Vec::new() }],
            },
        }).await?;
    }
    let _: ThreadGoalSetResponse = app.request(|request_id| ClientRequest::ThreadGoalSet {
        request_id,
        params: ThreadGoalSetParams {
            thread_id: started.thread.id.clone(),
            objective: Some("Continue only after durable queued user messages".to_string()),
            status: Some(ThreadGoalStatus::Active),
            token_budget: Some(Some(10_000)),
        },
    }).await?;
    // Both callbacks observe each completion. Durable preexisting user work
    // must win without relying on the scheduling order of two spawned waiters.
    let mut releases = releases.into_iter();
    for count in 2..=4 {
        releases.next().unwrap().send(()).unwrap();
        timeout(READ_TIMEOUT, server.wait_for_request_count(count)).await?;
    }
    let requests = server.requests().await;
    let expected_prompts = ["initial user", "first queued user", "second queued user"];
    for (index, request) in requests[..3].iter().enumerate() {
        let body: serde_json::Value = serde_json::from_slice(request)?;
        let user_texts = body["input"].as_array().context("request input array")?
            .iter().filter(|item| item["role"] == "user")
            .filter_map(|item| item["content"].as_array())
            .flatten().filter_map(|part| part["text"].as_str()).collect::<Vec<_>>();
        // Goal/context fragments may also use the user role. Assert the actual
        // queued payload and absence of later queue payloads without assuming
        // that internal context fragments occupy a particular array position.
        assert!(user_texts.contains(&expected_prompts[index]));
        for later in &expected_prompts[index + 1..] {
            assert!(!user_texts.contains(later));
        }
    }
    let queued: ThreadQueueListResponse = app.request(|request_id| ClientRequest::ThreadQueueList {
        request_id,
        params: ThreadQueueListParams { thread_id: started.thread.id.clone(), cursor: None, limit: None },
    }).await?;
    assert!(queued.data.is_empty());
    let paused: ThreadGoalSetResponse = app.request(|request_id| ClientRequest::ThreadGoalSet {
        request_id,
        params: ThreadGoalSetParams {
            thread_id: started.thread.id.clone(), objective: None,
            status: Some(ThreadGoalStatus::Paused), token_budget: None,
        },
    }).await?;
    assert_eq!(paused.goal.status, ThreadGoalStatus::Paused);
    releases.next().unwrap().send(()).unwrap();
    let mut completed_ids = Vec::new();
    for _ in 0..4 {
        let completed: TurnCompletedNotification = timeout(READ_TIMEOUT, app.read_notification("turn/completed")).await??;
        assert_eq!(completed.turn.status, TurnStatus::Completed);
        assert_eq!(completed.thread_id, started.thread.id);
        completed_ids.push(completed.turn.id);
    }
    assert_eq!(completed_ids.first(), Some(&first.turn.id));
    assert_eq!(completed_ids.iter().collect::<std::collections::HashSet<_>>().len(), 4);
    assert_eq!(server.requests().await.len(), 4);
    server.shutdown().await;
    Ok(())
}
