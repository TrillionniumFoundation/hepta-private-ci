//! Original stream/history overlap and subscription lifetime boundaries.
use super::*;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_hepta_agentd::text_session::AgentdTextObservation;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn queued_original_events_do_not_overwrite_history_or_survive_owner_fence() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "snapshot-original-stream")?;
    let model = app_test_support::create_mock_responses_server_sequence(vec![
        app_test_support::create_final_assistant_message_sse_response("first original reply")?,
        app_test_support::create_final_assistant_message_sse_response("second original reply")?,
    ])
    .await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let ingress = control.session_ingress().await?;
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "snapshot-original-test",
        /*channel_capacity*/ 64,
        /*experimental_api*/ true,
    )
    .await?;
    let mut request_id = 1;
    let thread = start_thread(&client, &mut request_id, &agent.workspace).await?;
    let view: ThreadReadResponse = client
        .request_typed(ClientRequest::ThreadRead {
            request_id: take_request_id(&mut request_id),
            params: ThreadReadParams {
                thread_id: thread.clone(),
                include_turns: false,
            },
        })
        .await?;
    let config = AgentdTextSessionConfig {
        control_socket: agent.layout.agentd_control_socket().to_path_buf(),
        agent_id: agent.agent_id.clone(),
        spawn_generation: 1,
        thread_id: thread.clone(),
        app_server_session_id: view.thread.session_id,
        codex_home: agent.layout.home_root().to_path_buf(),
    };
    let mut session = AgentdTextSession::connect(config.clone()).await?;
    let _: TurnStartResponse = client
        .request_typed(ClientRequest::TurnStart {
            request_id: take_request_id(&mut request_id),
            params: TurnStartParams {
                thread_id: thread.clone(),
                input: vec![UserInput::Text {
                    text: TEXT.into(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    // Deliberately leave this real subscription unread while its original
    // producer queues observations and the original owner completes the turn.
    wait_completed_text_turn(&client, &mut request_id, &thread).await?;
    tokio::task::yield_now().await;
    let history = session.requests.history_page(None).await?;
    ensure!(history.turns.len() == 1 && history.turns[0].status == TurnStatus::Completed);
    ensure!(history.turns[0].items.iter().any(|item| matches!(item, ThreadItem::AgentMessage { text, .. } if text == "first original reply")));
    ensure!(
        timeout(
            Duration::from_millis(100),
            session.events.next_observation()
        )
        .await
        .is_err(),
        "prefetched original deltas escaped after a complete history snapshot"
    );

    // Suppressing the snapshotted turn must not suppress subsequent original
    // activity on the same connection or create another conversation owner.
    let next: TurnStartResponse = client
        .request_typed(ClientRequest::TurnStart {
            request_id: take_request_id(&mut request_id),
            params: TurnStartParams {
                thread_id: thread.clone(),
                input: vec![UserInput::Text {
                    text: "new original turn".into(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    timeout(WAIT_TIMEOUT, async {
        loop {
            if let AgentdTextObservation::Notification(event) = session
                .events
                .next_observation()
                .await?
                .context("original stream ended")?
            {
                ensure!(
                    event.turn_id == next.turn.id,
                    "an old prefetched original event resurfaced"
                );
                if matches!(event.notification, ServerNotification::TurnCompleted(_)) {
                    break;
                }
            }
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;

    let resumed = session.reattach(config).await?;
    ensure!(matches!(
        session.events.next_observation().await,
        Err(TextSessionError::Fenced)
    ));
    session.events.shutdown().await?;
    let requests = resumed.requests.clone();
    drop(resumed.events);
    // No await before this check: Drop must fence synchronously, even before
    // the producer is scheduled to close its physical original connection.
    let original = signed_text(
        &agent.agent_id,
        &SigningKey::from_bytes(&[95; 32]),
        &thread,
        /*sequence*/ 1,
    )?;
    ensure!(matches!(
        requests.restore_signed(original),
        Err(TextSessionError::Fenced)
    ));
    ensure!(physical_send_count(&model).await == 2);
    client.shutdown().await?;
    Ok(())
}
