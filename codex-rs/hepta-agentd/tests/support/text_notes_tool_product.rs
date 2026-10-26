//! Ordinary TextSession isolation from the Notes owner's bounded callback table.
//! This runs an actual disposable Agentd/App Server with a test model. Only the
//! explicit test client refuses callbacks; no Root grant or Notes effect exists.
use super::*;
use codex_app_server_client::AppServerEvent;
use codex_app_server_protocol::DynamicToolCallOutputContentItem;
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::DynamicToolCallResponse;
use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::DynamicToolSpec;
use codex_app_server_protocol::ServerRequest;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_hepta_agentd::AgentdNotesModelRoute;
use codex_hepta_agentd::text_session::AgentdTextObservation;
use codex_hepta_agentd::text_session::TextApprovalObservation;
use std::collections::BTreeSet;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ordinary_text_session_survives_more_than_eight_notes_callbacks() -> Result<()> {
    // Exceed the private Notes owner's eight retained callbacks. A public text
    // session must never populate that owner-only table, even on the same thread.
    const CALLBACK_COUNT: usize = 9;
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "ordinary-text-notes-callbacks")?;
    let proposals: Vec<_> = (0..CALLBACK_COUNT)
        .map(|index| {
            (
                format!("notes-fixture-{index}"),
                serde_json::json!({ "text": format!("fixture proposal {index}") }),
            )
        })
        .collect();
    let mut sequence = Vec::new();
    for (index, (call_id, arguments)) in proposals.iter().enumerate() {
        let response_id = format!("notes-fixture-response-{index}");
        sequence.push(responses::sse(vec![
            responses::ev_response_created(&response_id),
            serde_json::json!({
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": call_id,
                    "namespace": "trill_notes",
                    "name": "propose_replace",
                    "arguments": serde_json::to_string(arguments)?,
                }
            }),
            responses::ev_completed(&response_id),
        ]));
    }
    sequence.push(
        app_test_support::create_final_assistant_message_sse_response(
            "all fixture proposals refused",
        )?,
    );
    let model = app_test_support::create_mock_responses_server_sequence(sequence).await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let ingress = control.session_ingress().await?;
    let mut client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "ordinary-text-notes-callback-test",
        /*channel_capacity*/ 64,
        /*experimental_api*/ true,
    )
    .await?;
    let mut request_id = 1;
    let definition: DynamicToolSpec =
        serde_json::from_str(AgentdNotesModelRoute::TOOL_DEFINITION_JSON)?;
    // Registration is explicit in this disposable fixture. Production routing
    // may only attach to a thread whose trusted launcher already registered it.
    let thread: ThreadStartResponse = client
        .request_typed(ClientRequest::ThreadStart {
            request_id: take_request_id(&mut request_id),
            params: ThreadStartParams {
                cwd: Some(agent.workspace.to_string_lossy().into_owned()),
                ephemeral: Some(false),
                dynamic_tools: Some(vec![definition]),
                ..Default::default()
            },
        })
        .await?;
    let thread_id = thread.thread.id;
    let mut session = AgentdTextSession::connect(AgentdTextSessionConfig {
        control_socket: agent.layout.agentd_control_socket().to_path_buf(),
        agent_id: agent.agent_id.clone(),
        spawn_generation: 1,
        thread_id: thread_id.clone(),
        app_server_session_id: thread.thread.session_id,
        codex_home: agent.layout.home_root().to_path_buf(),
    })
    .await?;
    let turn: TurnStartResponse = client
        .request_typed(ClientRequest::TurnStart {
            request_id: take_request_id(&mut request_id),
            params: TurnStartParams {
                thread_id: thread_id.clone(),
                input: vec![UserInput::Text {
                    text: "propose the nine fixture edits for refusal".into(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    let expected_calls: Vec<_> = proposals
        .iter()
        .map(|(call_id, arguments)| DynamicToolCallParams {
            thread_id: thread_id.clone(),
            turn_id: turn.turn.id.clone(),
            call_id: call_id.clone(),
            namespace: Some("trill_notes".into()),
            tool: "propose_replace".into(),
            arguments: arguments.clone(),
        })
        .collect();
    let refusal = DynamicToolCallResponse {
        content_items: vec![DynamicToolCallOutputContentItem::InputText {
            text: "fixture refused; no Notes document effect".into(),
        }],
        success: false,
    };
    let mut original_requests = BTreeSet::new();
    let mut unsupported_requests = BTreeSet::new();
    let mut completed_items = BTreeSet::new();
    timeout(WAIT_TIMEOUT, async {
        loop {
            tokio::select! {
                event = client.next_event() => match event.context("original client stream ended")? {
                    AppServerEvent::ServerRequest(request) => {
                        let ServerRequest::DynamicToolCall { request_id, params } = request.as_ref() else {
                            anyhow::bail!("unexpected original callback: {request:?}");
                        };
                        ensure!(Some(params) == expected_calls.get(original_requests.len()), "original tool identity or arguments changed");
                        ensure!(original_requests.insert(serde_json::to_string(request_id)?), "original callback was replayed");
                        client.resolve_server_request(request_id.clone(), serde_json::to_value(&refusal)?).await?;
                    }
                    AppServerEvent::Disconnected { .. } | AppServerEvent::Lagged { .. } => {
                        anyhow::bail!("original client stream disconnected or lost events");
                    }
                    AppServerEvent::ServerNotification(_) => {}
                },
                observation = session.events.next_observation() => match observation?.context("ordinary text stream ended")? {
                    AgentdTextObservation::Approval(TextApprovalObservation::Unavailable { id, .. }) => {
                        ensure!(unsupported_requests.insert(id), "ordinary text duplicated a callback");
                    }
                    AgentdTextObservation::Approval(other) => anyhow::bail!("Notes callback entered public text approval authority: {other:?}"),
                    AgentdTextObservation::Notification(event) => {
                        ensure!(event.turn_id == turn.turn.id, "ordinary text switched turns");
                        match event.notification {
                            ServerNotification::ItemCompleted(item) => {
                                if let ThreadItem::DynamicToolCall { id, .. } = item.item {
                                    ensure!(completed_items.insert(id), "ordinary text duplicated a completed tool item");
                                }
                            }
                            ServerNotification::TurnCompleted(completed) => {
                                ensure!(completed.turn.status == TurnStatus::Completed);
                                break;
                            }
                            _ => {}
                        }
                    }
                },
            }
        }
        Ok::<_, anyhow::Error>(())
    })
    .await
    .context("ordinary text stopped before all nine original callbacks completed")??;
    ensure!(original_requests.len() == CALLBACK_COUNT);
    ensure!(unsupported_requests == original_requests);
    ensure!(
        completed_items
            == proposals
                .iter()
                .map(|(id, _)| id.clone())
                .collect::<BTreeSet<_>>()
    );

    // The same public session remains live and reads the original persisted
    // items. Callback socket writes alone are not completion evidence.
    let history = session.requests.history_page(None).await?;
    ensure!(history.turns.len() == 1 && history.earlier_cursor.is_none());
    let original = &history.turns[0];
    ensure!(original.id == turn.turn.id && original.status == TurnStatus::Completed);
    let actual_items: Vec<_> = original
        .items
        .iter()
        .filter_map(|item| {
            let mut item = item.clone();
            if let ThreadItem::DynamicToolCall { duration_ms, .. } = &mut item {
                *duration_ms = None;
                Some(item)
            } else {
                None
            }
        })
        .collect();
    let expected_items: Vec<_> = expected_calls
        .into_iter()
        .map(|call| ThreadItem::DynamicToolCall {
            id: call.call_id,
            namespace: call.namespace,
            tool: call.tool,
            arguments: call.arguments,
            status: DynamicToolCallStatus::Failed,
            content_items: Some(refusal.content_items.clone()),
            success: Some(false),
            duration_ms: None,
        })
        .collect();
    ensure!(
        actual_items == expected_items,
        "original history lost exact tool results: expected {expected_items:?}; actual {actual_items:?}"
    );
    ensure!(physical_send_count(&model).await == CALLBACK_COUNT + 1);
    session.events.shutdown().await?;
    client.shutdown().await?;
    Ok(())
}
