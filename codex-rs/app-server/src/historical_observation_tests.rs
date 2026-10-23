use super::*;
use codex_protocol::protocol::SessionSource;
use codex_protocol::user_input::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_thread_store::LocalQueueStore;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

#[tokio::test(start_paused = true)]
async fn unfinished_thread_start_tasks_cannot_acknowledge_a_graceful_drain() {
    let tasks = tokio_util::task::TaskTracker::new();
    let (release, wait) = tokio::sync::oneshot::channel::<()>();
    tasks.spawn(async move {
        let _ = wait.await;
    });
    let handle = AppServerDrainHandle::new();
    handle.request_drain();
    assert!(!join_thread_background_tasks(&tasks).await);
    assert!(!tasks.is_empty());
    assert!(!handle.drained());
    assert!(!handle.historical_observation_ready());
    release.send(()).unwrap();
    assert!(join_thread_background_tasks(&tasks).await);
}

#[tokio::test]
async fn original_owner_observation_requires_drain_and_never_repairs_missing_metadata() {
    let temporary = tempfile::tempdir().unwrap();
    let home = temporary.path().canonicalize().unwrap();
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::from_absolute_path(&home).unwrap());
    let database = StateRuntime::init(sqlite, "test-provider".to_string())
        .await
        .unwrap();
    let handle = AppServerDrainHandle::new();
    handle.bind_historical_owner(
        home.clone(),
        Arc::clone(&database),
        Arc::new(LocalQueueStore::new(Arc::clone(&database))),
    );
    let thread_id = ThreadId::new();
    let digest = user_input_payload_sha256(&[UserInput::Text {
        text: "exact input".to_string(),
        text_elements: Vec::new(),
    }])
    .unwrap();
    assert!(
        handle
            .observe_exact_submission(&home, &thread_id.to_string(), "client-a", &digest)
            .await
            .is_err()
    );
    handle.request_drain();
    assert!(!handle.historical_observation_ready());
    // This owner fixture has no request task or thread writer. Its actual
    // TaskTracker joins before acknowledging; it is not a transport fixture.
    let tasks = tokio_util::task::TaskTracker::new();
    assert!(join_thread_background_tasks(&tasks).await);
    handle.mark_drained();
    assert!(handle.historical_observation_ready());
    let sessions = home.join("sessions/2026/09/30");
    std::fs::create_dir_all(&sessions).unwrap();
    std::fs::write(
        sessions.join(format!("rollout-2026-09-30T12-00-00-{thread_id}.jsonl")),
        b"existing unindexed rollout must not trigger repair\n",
    )
    .unwrap();
    assert_eq!(
        handle
            .observe_exact_submission(&home, &thread_id.to_string(), "client-a", &digest)
            .await
            .unwrap(),
        QueueHistoricalObservation {
            client_user_message_id: "client-a".to_string(),
            payload_sha256: digest.clone(),
            outcome: QueueHistoricalOutcome::Missing
        }
    );
    assert!(database.get_thread(thread_id).await.unwrap().is_none());
    assert!(
        database
            .thread_queue()
            .observe_client_binding(thread_id, "client-a", &digest)
            .await
            .unwrap()
            .is_none()
    );
    assert!(
        handle
            .observe_exact_submission(
                &home.join("other-home"),
                &thread_id.to_string(),
                "client-a",
                &digest
            )
            .await
            .is_err()
    );
    // Register only the currently selected pointer, then observe its actual
    // lifecycle records through the same retained database owner.
    use codex_protocol::items::TurnItem;
    use codex_protocol::items::UserMessageItem;
    use codex_protocol::protocol::EventMsg;
    use codex_protocol::protocol::ItemStartedEvent;
    use codex_protocol::protocol::SessionMeta;
    use codex_protocol::protocol::SessionMetaLine;
    use codex_protocol::protocol::TurnCompleteEvent;
    use codex_protocol::protocol::TurnStartedEvent;
    use codex_rollout::RolloutItem;
    use codex_rollout::RolloutLine;
    let selected_path = home.join("selected.jsonl");
    let records = [
        RolloutItem::SessionMeta(SessionMetaLine {
            meta: SessionMeta {
                id: thread_id,
                session_id: thread_id.into(),
                timestamp: "2026-09-30T20:00:00Z".to_string(),
                ..Default::default()
            },
            git: None,
        }),
        RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent {
            turn_id: "turn-a".to_string(),
            trace_id: None,
            started_at: None,
            model_context_window: None,
            collaboration_mode_kind: Default::default(),
        })),
        RolloutItem::EventMsg(EventMsg::ItemStarted(ItemStartedEvent {
            thread_id,
            turn_id: "turn-a".to_string(),
            item: TurnItem::UserMessage(UserMessageItem {
                id: "item-a".to_string(),
                client_id: Some("client-a".to_string()),
                content: vec![UserInput::Text {
                    text: "exact input".to_string(),
                    text_elements: Vec::new(),
                }],
            }),
            started_at_ms: 100,
        })),
        RolloutItem::EventMsg(EventMsg::TurnComplete(TurnCompleteEvent {
            turn_id: "turn-a".to_string(),
            last_agent_message: None,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
            time_to_first_token_ms: None,
        })),
    ];
    let mut bytes = Vec::new();
    for item in records {
        serde_json::to_writer(
            &mut bytes,
            &RolloutLine {
                timestamp: "2026-09-30T20:00:00Z".to_string(),
                ordinal: None,
                item,
            },
        )
        .unwrap();
        bytes.push(b'\n');
    }
    std::fs::write(&selected_path, bytes).unwrap();
    let metadata = codex_state::ThreadMetadataBuilder::new(
        thread_id,
        selected_path,
        chrono::Utc::now(),
        SessionSource::Cli,
    )
    .build("test-provider");
    database.upsert_thread(&metadata).await.unwrap();
    drop(database);
    assert_eq!(
        handle
            .observe_exact_submission(&home, &thread_id.to_string(), "client-a", &digest)
            .await
            .unwrap()
            .outcome,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-a".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed)
        }
    );
}
