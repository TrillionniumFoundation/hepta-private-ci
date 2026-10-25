//! Real original owner with a large model item; mock credentials remain fixtures.
use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn large_original_item_keeps_history_navigable_and_exact_terminal_reconcilable() -> Result<()>
{
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "large-original-text")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    responses::mount_sse_once(
        &model,
        responses::sse(vec![
            responses::ev_assistant_message("large-item", &"界".repeat(100_000)),
            responses::ev_completed("large-response"),
        ]),
    )
    .await;
    let key = SigningKey::from_bytes(&[94; 32]);
    let trust_file = agent.layout.home_root().join("authbus-trust.json");
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    write_trust(
        &trust_file,
        &agent.agent_id,
        &key,
        &[],
        /*revoked*/ false,
    )?;
    let checkpoint_root = tempfile::tempdir()?;
    std::fs::set_permissions(
        checkpoint_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let checkpoint_file = checkpoint_root
        .path()
        .join("authbus-replay-checkpoint.json");
    let evidence = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::from_absolute_path(agent.layout.home_root())?,
    ))
    .await?;
    let frontier = evidence.authbus_replay_frontier_digest().await?;
    drop(evidence);
    write_checkpoint(&checkpoint_file, &agent.agent_id, 1, frontier)?;
    fleet.start_with_authbus_trust_file(&agent, &trust_file, &checkpoint_file)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let ingress = control.session_ingress().await?;
    let client =
        connect_app_server_with_experimental(&ingress.socket_path, "large-original-text", 32, true)
            .await?;
    let mut request_id = 1;
    let thread = start_thread(&client, &mut request_id, &agent.workspace).await?;
    write_trust(
        &trust_file,
        &agent.agent_id,
        &key,
        std::slice::from_ref(&thread),
        /*revoked*/ false,
    )?;
    let view: ThreadReadResponse = client
        .request_typed(ClientRequest::ThreadRead {
            request_id: take_request_id(&mut request_id),
            params: ThreadReadParams {
                thread_id: thread.clone(),
                include_turns: false,
            },
        })
        .await?;
    let session = AgentdTextSession::connect(AgentdTextSessionConfig {
        control_socket: agent.layout.agentd_control_socket().to_path_buf(),
        agent_id: agent.agent_id.clone(),
        spawn_generation: 1,
        thread_id: thread.clone(),
        app_server_session_id: view.thread.session_id,
        codex_home: agent.layout.home_root().to_path_buf(),
    })
    .await?;
    let original = signed_text(&agent.agent_id, &key, &thread, /*sequence*/ 1)?;
    let admitted = session.requests.submit_signed(original.clone()).await?;
    wait_queue_accepted(&control, &admitted.delivery_id).await?;
    wait_completed_text_turn(&client, &mut request_id, &thread).await?;
    let page = session.requests.history_page(None).await?;
    ensure!(page.turns.len() == 1 && page.notice.is_some() && page.earlier_cursor.is_none());
    ensure!(
        page.turns[0].items.is_empty()
            && page.turns[0].items_view == codex_app_server_protocol::TurnItemsView::NotLoaded
    );
    ensure!(serde_json::to_vec(&page)?.len() < 16 * 1024);
    let terminal = session.requests.reconcile(&original.message_id).await?;
    let turn = terminal
        .turn
        .context("large original terminal was not recoverable")?;
    ensure!(turn.id == page.turns[0].id && turn.status == TurnStatus::Completed);
    ensure!(
        turn.items.is_empty()
            && turn.items_view == codex_app_server_protocol::TurnItemsView::NotLoaded
    );
    // The UI limitation did not mutate or replace the original stored item.
    let stored: ThreadReadResponse = client
        .request_typed(ClientRequest::ThreadRead {
            request_id: take_request_id(&mut request_id),
            params: ThreadReadParams {
                thread_id: thread,
                include_turns: true,
            },
        })
        .await?;
    ensure!(stored.thread.turns[0].items.iter().any(
        |item| matches!(item, ThreadItem::AgentMessage { text, .. } if text.len() == 300_000)
    ));
    ensure!(physical_send_count(&model).await == 1);
    session.events.shutdown().await?;
    client.shutdown().await?;
    Ok(())
}
