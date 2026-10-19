use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn bounded_history_rpc_returns_complete_items_or_typed_refusal() -> Result<()> {
    for size in [16, 300_000] {
        let server = create_mock_responses_server_repeating_assistant("Done").await;
        let codex_home = TempDir::new()?;
        MockResponsesConfig::new(&server.uri()).write(codex_home.path())?;
        let thread_id = codex_protocol::ThreadId::default();
        let sqlite = codex_state::SqliteConfig::new_for_testing(codex_home.path().abs());
        let state_db =
            codex_state::StateRuntime::init(sqlite.clone(), "mock_provider".to_string()).await?;
        let store = LocalThreadStore::new(
            LocalThreadStoreConfig {
                codex_home: codex_home.path().to_path_buf(),
                sqlite,
                default_model_provider_id: "mock_provider".to_string(),
            },
            Some(state_db),
        );
        store
            .create_thread(CreateThreadParams {
                session_id: thread_id.into(),
                thread_id,
                extra_config: None,
                forked_from_id: None,
                parent_thread_id: None,
                source: ProtocolSessionSource::Cli,
                thread_source: None,
                originator: "test_originator".to_string(),
                base_instructions: BaseInstructions::default(),
                dynamic_tools: Vec::new(),
                selected_capability_roots: Vec::new(),
                multi_agent_version: None,
                history_mode: codex_protocol::protocol::ThreadHistoryMode::Paginated,
                history_base: None,
                subagent_history_start_ordinal: None,
                initial_window_id: Uuid::now_v7().to_string(),
                metadata: ThreadPersistenceMetadata {
                    cwd: Some(codex_home.path().to_path_buf()),
                    model_provider: "mock_provider".to_string(),
                    memory_mode: ThreadMemoryMode::Enabled,
                },
            })
            .await?;
        store
            .persist_thread(thread_id, PersistContext::Standard)
            .await?;
        store
            .append_items(AppendThreadItemsParams {
                thread_id,
                items: vec![
                    paginated_turn_started("bounded-turn"),
                    paginated_completed_item(
                        thread_id,
                        "bounded-turn",
                        CoreTurnItem::AgentMessage(AgentMessageItem {
                            id: "bounded-item".into(),
                            content: vec![AgentMessageContent::Text {
                                text: "x".repeat(size),
                            }],
                            phase: None,
                            memory_citation: None,
                            delivery: None,
                        }),
                    ),
                    paginated_turn_completed("bounded-turn"),
                ],
            })
            .await?;
        store.shutdown_thread(thread_id).await?;
        let mut mcp = TestAppServer::builder()
            .with_codex_home(codex_home.path())
            .build_initialized()
            .await?;
        let request = mcp
            .send_thread_turns_list_request(ThreadTurnsListParams {
                thread_id: thread_id.to_string(),
                cursor: None,
                limit: Some(1),
                sort_direction: None,
                items_view: Some(TurnItemsView::BoundedFull),
            })
            .await?;
        if size == 16 {
            let response: ThreadTurnsListResponse =
                timeout(DEFAULT_READ_TIMEOUT, mcp.read_response(request)).await??;
            assert_eq!(response.data.len(), 1);
            assert_eq!(response.data[0].items_view, TurnItemsView::Full);
            assert_eq!(response.data[0].items.len(), 1);
            assert_eq!(response.data[0].id, "bounded-turn");
        } else {
            let error = timeout(
                DEFAULT_READ_TIMEOUT,
                mcp.read_stream_until_error_message(RequestId::Integer(request)),
            )
            .await??;
            assert_eq!(
                error.error.code,
                codex_app_server_protocol::HISTORY_READ_UNAVAILABLE_ERROR_CODE
            );
            assert_eq!(
                error.error.data,
                Some(
                    serde_json::json!({"kind":"historyReadUnavailable", "reason":"budgetExceeded"})
                )
            );
        }
        // Resume cannot accidentally route the request-only mode through legacy replay.
        let request = mcp
            .send_thread_resume_request(ThreadResumeParams {
                thread_id: thread_id.to_string(),
                initial_turns_page: Some(ThreadResumeInitialTurnsPageParams {
                    limit: Some(1),
                    sort_direction: None,
                    items_view: Some(TurnItemsView::BoundedFull),
                }),
                ..Default::default()
            })
            .await?;
        let error = timeout(
            DEFAULT_READ_TIMEOUT,
            mcp.read_stream_until_error_message(RequestId::Integer(request)),
        )
        .await??;
        assert_eq!(error.error.code, -32600);
    }
    Ok(())
}
