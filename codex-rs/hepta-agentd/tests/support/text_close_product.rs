//! Actual App Server/Agentd process recovery; the model endpoint only counts
//! physical sends. The delayed request pauses at its transport boundary.
use super::*;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_protocol::user_input::user_input_payload_sha256;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn original_cancelled_binding_survives_owner_restart_and_late_original_rpc() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "closed-text-workspace")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let ingress = control.session_ingress().await?;
    let client =
        connect_app_server_with_experimental(&ingress.socket_path, "close-original-text", 32, true)
            .await?;
    let mut request_id = 1;
    let thread = start_thread(&client, &mut request_id, &agent.workspace).await?;
    // Materialize this exact live zero-turn thread using the original store.
    let resumed: ThreadResumeResponse = client
        .request_typed(ClientRequest::ThreadResume {
            request_id: take_request_id(&mut request_id),
            params: ThreadResumeParams {
                thread_id: thread.clone(),
                ..Default::default()
            },
        })
        .await?;
    ensure!(resumed.thread.id == thread && resumed.thread.turns.is_empty());
    let input = vec![UserInput::Text {
        text: "an old input must stay closed".into(),
        text_elements: Vec::new(),
    }];
    let protocol_input = input
        .clone()
        .into_iter()
        .map(UserInput::into_core)
        .collect::<Vec<_>>();
    let digest = user_input_payload_sha256(&protocol_input)?;
    let original = ThreadQueueReconcileParams {
        thread_id: thread.clone(),
        input,
        client_user_message_id: "hepta.authbus:late-original-closed".into(),
        expected_payload_sha256: digest,
        mode: ThreadQueueReconcileMode::AllowIfAbsent,
    };
    // Hold the already-created original transport request. It is released only
    // after the original owner has durably closed the identity and restarted.
    let (release, delayed) = tokio::sync::oneshot::channel::<std::path::PathBuf>();
    let late_params = original.clone();
    let late = tokio::spawn(async move {
        let socket = delayed.await?;
        let peer = connect_app_server_with_experimental(&socket, "delayed-original-text", 32, true)
            .await?;
        let response: ThreadQueueReconcileResponse = peer
            .request_typed(ClientRequest::ThreadQueueReconcile {
                request_id: RequestId::Integer(901),
                params: late_params,
            })
            .await?;
        peer.shutdown().await?;
        Ok::<_, anyhow::Error>(response)
    });
    let closed: ThreadQueueReconcileResponse = client
        .request_typed(ClientRequest::ThreadQueueReconcile {
            request_id: take_request_id(&mut request_id),
            params: ThreadQueueReconcileParams {
                mode: ThreadQueueReconcileMode::CloseIfAbsent,
                ..original.clone()
            },
        })
        .await?;
    ensure!(closed.outcome == ThreadQueueReconcileOutcome::Cancelled);
    ensure!(physical_send_count(&model).await == 0);
    client.shutdown().await?;
    fleet
        .supervisor
        .restart(&agent.agent_id, std::time::Instant::now())?;
    let (control, _) = fleet.wait_new_spawn(&agent, 1).await?;
    let ingress = control.session_ingress().await?;
    release
        .send(ingress.socket_path.clone())
        .map_err(|_| anyhow::anyhow!("delayed original request disappeared"))?;
    let late_response = timeout(WAIT_TIMEOUT, late).await???;
    ensure!(
        late_response == closed,
        "late input revived a durable original cancellation"
    );
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "verify-closed-original",
        32,
        true,
    )
    .await?;
    let view: ThreadReadResponse = client
        .request_typed(ClientRequest::ThreadRead {
            request_id: RequestId::Integer(902),
            params: ThreadReadParams {
                thread_id: thread.clone(),
                include_turns: true,
            },
        })
        .await?;
    ensure!(view.thread.id == thread && view.thread.turns.is_empty());
    ensure!(
        physical_send_count(&model).await == 0,
        "closed input reached the model after restart"
    );
    client.shutdown().await?;
    drop(fleet);
    ensure!(physical_send_count(&model).await == 0);
    Ok(())
}
