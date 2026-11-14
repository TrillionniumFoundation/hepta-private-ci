//! Actual original App Server callbacks. This is an owner protocol test, not
//! evidence that a real human has supplied the Root UI approval capability.
use super::*;
use codex_app_server_protocol::CommandExecutionApprovalDecision;
use codex_app_server_protocol::CommandExecutionRequestApprovalResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_hepta_agentd::text_session::AgentdTextObservation;
use codex_hepta_agentd::text_session::TextApprovalObservation;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn original_pending_approval_survives_text_reattach_and_resolves_without_disconnect()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "original-pending-approval")?;
    let marker = agent.workspace.join("declined-command-must-not-run");
    let model = app_test_support::create_mock_responses_server_sequence(vec![
        app_test_support::create_escalated_command_execution_sse_response(
            vec![
                "python3".into(),
                "-c".into(),
                format!(
                    "from pathlib import Path; Path({:?}).write_text('unexpected')",
                    marker.to_string_lossy()
                ),
            ],
            None,
            Some(5000),
            "original-approval-call",
        )?,
        app_test_support::create_final_assistant_message_sse_response("declined, no effect")?,
    ])
    .await;
    MockResponsesConfig::new(&model.uri())
        .with_approval_policy("on-request")
        .write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let ingress = control.session_ingress().await?;
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "original-approval-test",
        64,
        true,
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
                    text: "propose the fixture command for review".into(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    let original = timeout(WAIT_TIMEOUT, async {
        loop {
            if let Some(AgentdTextObservation::Approval(TextApprovalObservation::Pending(
                approval,
            ))) = session.events.next_observation().await?
            {
                return Ok::<_, anyhow::Error>(approval);
            }
        }
    })
    .await??;
    ensure!(original.thread_id == thread && original.item_id == "original-approval-call");
    ensure!(original.can_decline && original.details.contains("python3"));
    let mut resumed = session.reattach(config).await?;
    session.events.shutdown().await?;
    let replayed = timeout(WAIT_TIMEOUT, async {
        loop {
            if let Some(AgentdTextObservation::Approval(TextApprovalObservation::Pending(
                approval,
            ))) = resumed.events.next_observation().await?
            {
                return Ok::<_, anyhow::Error>(approval);
            }
        }
    })
    .await??;
    ensure!(
        replayed.id == original.id
            && replayed.connection_id != original.connection_id
            && replayed.details == original.details
    );
    // Only this explicit original owner test client answers the callback. The
    // production native worker additionally requires live Root approval scope.
    client
        .resolve_server_request(
            serde_json::from_str(&replayed.id)?,
            serde_json::to_value(CommandExecutionRequestApprovalResponse {
                decision: CommandExecutionApprovalDecision::Decline,
            })?,
        )
        .await?;
    timeout(WAIT_TIMEOUT, async {
        let mut resolved = false;
        loop {
            match resumed
                .events
                .next_observation()
                .await?
                .context("original stream ended")?
            {
                AgentdTextObservation::Approval(TextApprovalObservation::Resolved {
                    id, ..
                }) if id == original.id => resolved = true,
                AgentdTextObservation::Notification(event)
                    if matches!(event.notification, ServerNotification::TurnCompleted(_)) =>
                {
                    ensure!(
                        resolved,
                        "turn completed before original resolution was observed"
                    );
                    break;
                }
                _ => {}
            }
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    ensure!(!marker.exists());
    ensure!(physical_send_count(&model).await == 2);
    resumed.events.shutdown().await?;
    client.shutdown().await?;
    Ok(())
}
