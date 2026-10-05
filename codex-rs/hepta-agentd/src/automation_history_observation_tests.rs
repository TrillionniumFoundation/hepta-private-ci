//! Real history pagination and expired recovery-lease transport regressions.
use super::*;

async fn historical_turn_fixture() -> Fixture {
    let fixture = fixture().await;
    ready(&fixture).await;
    let draft = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "historical terminal observation",
        AutomationSchedule::Once,
        1_000,
        1,
    );
    fixture.store.create_task(&draft).await.expect("task");
    let lease = fixture
        .store
        .claim_due(1_000, 1, 1_000)
        .await
        .expect("claim")
        .expect("due");
    let occurrence = fixture
        .store
        .materialize_occurrence(&lease, 1_000)
        .await
        .expect("occurrence");
    fixture
        .store
        .prepare_occurrence_taskflow(&occurrence, &lease, 1_000, 1_000)
        .await
        .expect("outbox");
    fixture
        .store
        .record_dispatch_uncertain(&lease, 1_000)
        .await
        .expect("unknown before admission");
    fixture
        .store
        .record_occurrence_admitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: "historical-queue".to_string(),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            1_001,
        )
        .await
        .expect("admitted");
    let digest =
        crate::automation_recovery::input_digest(&[codex_app_server_protocol::UserInput::Text {
            text: draft.prompt.clone(),
            text_elements: Vec::new(),
        }])
        .expect("wire digest");
    fixture
        .store
        .record_occurrence_turn(
            draft.task_id,
            lease.occurrence,
            &lease.client_user_message_id,
            "historical-turn",
            &digest,
            1_002,
        )
        .await
        .expect("known turn");
    for (generation, state) in [
        (2, AgentLifecycle::Draining),
        (3, AgentLifecycle::Stopped),
        (4, AgentLifecycle::Starting),
        (5, AgentLifecycle::Running),
    ] {
        fixture
            .registry
            .compare_and_transition(&fixture.identity.agent_id, generation, state)
            .expect("legitimate generation transition");
    }
    let Fixture {
        _temp,
        registry,
        mut identity,
        state: old_state,
        store,
    } = fixture;
    // Release the old generation's exclusive prompt-registry owner before
    // constructing its successor. Assignment would evaluate the new owner
    // first and legitimately fail with StateLocked.
    drop(old_state);
    identity.spawn_generation = 5;
    let state = Arc::new(
        AgentdState::new(identity.clone(), registry.clone(), 128).expect("new generation state"),
    );
    let fixture = Fixture {
        _temp,
        registry,
        identity,
        state,
        store,
    };
    fixture
        .state
        .attach_automation_store(fixture.store.clone())
        .expect("automation owner");
    fixture.state.refresh_generation().expect("generation");
    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&fixture.identity.layout)
            .await
            .expect("cognitive owner");
    fixture
        .state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("cognitive attachment");
    fixture
        .state
        .mark_runtime_prerequisites_ready()
        .expect("prerequisites");
    fixture.state.mark_app_server_ready().expect("ready");
    fixture
}

#[derive(Clone, Copy)]
enum HistoryScenario {
    LaterPageDeadline,
    DelayedTerminal,
}

async fn exercise_turn_history_transport(scenario: HistoryScenario) {
    let terminal = matches!(scenario, HistoryScenario::DelayedTerminal);
    use sqlx::Connection;
    use sqlx::Row;
    use std::sync::atomic::AtomicU64;
    let fixture = historical_turn_fixture().await;
    let work = fixture
        .store
        .pending_occurrence_work(1)
        .await
        .expect("frontier")
        .pop()
        .expect("historical work");
    let before_run = fixture
        .store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .expect("run")
        .expect("exists");
    assert_eq!(before_run.generation, Some(1));
    assert_eq!(before_run.lease_expires_at_ms, Some(2_000));
    let socket = &fixture.identity.app_server_socket;
    tokio::fs::create_dir_all(socket.parent().expect("parent"))
        .await
        .expect("directory");
    let listener =
        UnixListener::bind(socket).expect("actual UDS required; no skipped transport assertions");
    let home = fixture.identity.home_root.to_string_lossy().into_owned();
    let (observed_tx, observed_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.expect("connection");
        let mut websocket = tokio_tungstenite::accept_async(stream)
            .await
            .expect("handshake");
        let mut observed_tx = Some(observed_tx);
        let mut release_rx = Some(release_rx);
        let mut page_count = 0;
        while let Some(frame) = websocket.next().await {
            match frame.expect("frame") {
                Message::Text(text) => {
                    let request: serde_json::Value = serde_json::from_str(&text).expect("RPC");
                    match request["method"].as_str() {
                        Some("initialize") => websocket.send(Message::Text(serde_json::json!({
                            "id":request["id"], "result":{"userAgent":"history-fixture/1","codexHome":home}
                        }).to_string().into())).await.expect("initialize"),
                        Some("initialized") => {},
                        Some("thread/turns/list") => {
                            let params: codex_app_server_protocol::ThreadTurnsListParams = serde_json::from_value(request["params"].clone()).expect("typed history request");
                            assert_eq!(params.thread_id, "019153a4-3088-7e03-a56a-9b1964f75ddd");
                            assert_eq!(params.limit, Some(100));
                            assert_eq!(params.items_view, Some(codex_app_server_protocol::TurnItemsView::NotLoaded));
                            page_count += 1;
                            if terminal {
                                assert_eq!(page_count, 1);
                                assert_eq!(params.cursor, None);
                                observed_tx.take().expect("signal once").send(()).expect("receiver");
                                release_rx.take().expect("release once").await.expect("clock advanced");
                                let response = codex_app_server_protocol::ThreadTurnsListResponse {
                                    data: vec![codex_app_server_protocol::Turn {
                                        id: "historical-turn".to_string(), items: Vec::new(),
                                        items_view: codex_app_server_protocol::TurnItemsView::NotLoaded,
                                        status: codex_app_server_protocol::TurnStatus::Completed,
                                        error: None, started_at: None, completed_at: None, duration_ms: None,
                                    }], next_cursor: None, backwards_cursor: None,
                                };
                                websocket.send(Message::Text(serde_json::json!({"id":request["id"],"result":response}).to_string().into())).await.expect("terminal response");
                            } else if page_count == 1 {
                                assert_eq!(params.cursor, None);
                                let response = codex_app_server_protocol::ThreadTurnsListResponse {
                                    data: Vec::new(), next_cursor: Some("opaque-page-two".to_string()), backwards_cursor: None,
                                };
                                websocket.send(Message::Text(serde_json::json!({"id":request["id"],"result":response}).to_string().into())).await.expect("first page");
                            } else {
                                assert_eq!(page_count, 2);
                                assert_eq!(params.cursor.as_deref(), Some("opaque-page-two"));
                                observed_tx.take().expect("signal once").send(()).expect("receiver");
                                // Withhold the second response, but keep polling close.
                            }
                        }
                        method => panic!("no enqueue or queue reconciliation permitted: {method:?}"),
                    }
                }
                Message::Close(_) => break,
                Message::Ping(bytes) => websocket.send(Message::Pong(bytes)).await.expect("pong"),
                _ => {}
            }
        }
        page_count
    });
    let now = Arc::new(AtomicU64::new(3_000));
    let clock = Arc::clone(&now);
    let store = fixture.store.clone();
    let state = Arc::clone(&fixture.state);
    let identity = fixture.identity.clone();
    let task = tokio::spawn(async move {
        let mut scan = store.uncertain_dispatch_scan();
        crate::automation_recovery::reconcile_one(
            &store,
            &state,
            &identity,
            3_000,
            &mut scan,
            &CancellationToken::new(),
            &move || Ok(clock.load(Ordering::SeqCst)),
        )
        .await
    });
    timeout(Duration::from_secs(5), observed_rx)
        .await
        .expect("actual history request")
        .expect("signal");
    now.store(10_000, Ordering::SeqCst);
    if terminal {
        release_tx.send(()).expect("release terminal observation");
    }
    let result = timeout(Duration::from_secs(18), task)
        .await
        .expect("read and bounded cleanup")
        .expect("join")
        .expect("reconcile");
    assert!(matches!(
        result,
        crate::automation_recovery::RecoveryPass::Observed
    ));
    let count = timeout(Duration::from_secs(2), server)
        .await
        .expect("server close")
        .expect("server join");
    let after = fixture
        .store
        .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
        .await
        .expect("occurrence")
        .expect("exists");
    let run = fixture
        .store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .expect("run")
        .expect("exists");
    if terminal {
        assert_eq!(count, 1);
        assert_eq!(
            after.state,
            codex_hepta_automation::AutomationOccurrenceState::Succeeded
        );
        assert_eq!(after.updated_at_ms, 10_000);
        assert_eq!(
            run.state,
            codex_hepta_automation::TaskFlowRunState::Succeeded
        );
        assert_eq!(
            run.generation, None,
            "terminal projection releases its lease"
        );
        let options = sqlx::sqlite::SqliteConnectOptions::new()
            .filename(fixture.store.path())
            .read_only(true);
        let mut connection = sqlx::SqliteConnection::connect_with(&options)
            .await
            .expect("read-only evidence");
        let rows = sqlx::query("SELECT generation, recorded_at_ms FROM taskflow_events WHERE run_id = ? AND transition = 'lease_claimed' ORDER BY event_seq")
            .bind(&work.occurrence.taskflow_run_id).fetch_all(&mut connection).await.expect("claim evidence");
        let claims: Vec<(i64, i64)> = rows
            .iter()
            .map(|row| (row.get("generation"), row.get("recorded_at_ms")))
            .collect();
        assert_eq!(
            claims,
            vec![(1, 1_000), (5, 10_000)],
            "terminal recovery claim must use refreshed host time"
        );
        connection.close().await.expect("close evidence");
    } else {
        assert_eq!(count, 2);
        assert_eq!(after.state, work.occurrence.state);
        assert_eq!(after.turn_id, work.occurrence.turn_id);
        assert_eq!(
            after.terminal_scan_cursor.as_deref(),
            Some("opaque-page-two")
        );
        assert_eq!(after.updated_at_ms, 10_000);
        assert_eq!(
            run, before_run,
            "a page timeout cannot authorize terminal settlement or run takeover"
        );
        // The first listener is gone; bind the same fixture endpoint for the
        // next production pass and verify the persisted cursor on the wire.
        tokio::fs::remove_file(socket)
            .await
            .expect("remove closed fixture socket");
        let listener = UnixListener::bind(socket).expect("second actual UDS");
        let home = fixture.identity.home_root.to_string_lossy().into_owned();
        let resumed_server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.expect("resumed connection");
            let mut websocket = tokio_tungstenite::accept_async(stream)
                .await
                .expect("handshake");
            let mut history_requests = 0;
            while let Some(frame) = websocket.next().await {
                match frame.expect("frame") {
                    Message::Text(text) => {
                        let request: serde_json::Value = serde_json::from_str(&text).expect("RPC");
                        match request["method"].as_str() {
                            Some("initialize") => websocket.send(Message::Text(serde_json::json!({
                                "id":request["id"], "result":{"userAgent":"history-resume/1","codexHome":home}
                            }).to_string().into())).await.expect("initialize"),
                            Some("initialized") => {},
                            Some("thread/turns/list") => {
                                let params: codex_app_server_protocol::ThreadTurnsListParams = serde_json::from_value(request["params"].clone()).expect("typed resumed request");
                                assert_eq!(params.cursor.as_deref(), Some("opaque-page-two"));
                                assert_eq!(params.thread_id, "019153a4-3088-7e03-a56a-9b1964f75ddd");
                                history_requests += 1;
                                let response = codex_app_server_protocol::ThreadTurnsListResponse {
                                    data: vec![codex_app_server_protocol::Turn {
                                        id: "historical-turn".to_string(), items: Vec::new(),
                                        items_view: codex_app_server_protocol::TurnItemsView::NotLoaded,
                                        status: codex_app_server_protocol::TurnStatus::InProgress,
                                        error: None, started_at: None, completed_at: None, duration_ms: None,
                                    }], next_cursor: None, backwards_cursor: None,
                                };
                                websocket.send(Message::Text(serde_json::json!({"id":request["id"],"result":response}).to_string().into())).await.expect("still running response");
                            }
                            other => panic!("unexpected resumed method: {other:?}"),
                        }
                    }
                    Message::Close(_) => break,
                    Message::Ping(bytes) => {
                        websocket.send(Message::Pong(bytes)).await.expect("pong")
                    }
                    _ => {}
                }
            }
            history_requests
        });
        let mut scan = fixture.store.uncertain_dispatch_scan();
        let resumed = timeout(
            Duration::from_secs(18),
            crate::automation_recovery::reconcile_one(
                &fixture.store,
                &fixture.state,
                &fixture.identity,
                10_000,
                &mut scan,
                &CancellationToken::new(),
                &|| Ok(11_000),
            ),
        )
        .await
        .expect("bounded resumed observation")
        .expect("resumed pass");
        assert!(matches!(
            resumed,
            crate::automation_recovery::RecoveryPass::Observed
        ));
        assert_eq!(
            timeout(Duration::from_secs(2), resumed_server)
                .await
                .expect("closed resumed peer")
                .expect("join"),
            1
        );
        let resumed_occurrence = fixture
            .store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .expect("resumed occurrence")
            .expect("exists");
        assert_eq!(
            resumed_occurrence, after,
            "an in-progress turn neither clears uncertainty nor terminalizes the occurrence"
        );
        assert_eq!(
            fixture
                .store
                .taskflow_run(&work.occurrence.taskflow_run_id)
                .await
                .expect("resumed run")
                .expect("exists"),
            before_run
        );
    }
    assert!(
        fixture
            .store
            .uncertain_dispatches(16)
            .await
            .expect("no new dispatch")
            .is_empty()
    );
    fixture.store.close().await;
}

#[tokio::test]
async fn actual_later_history_page_deadline_persists_only_observed_continuation() {
    exercise_turn_history_transport(HistoryScenario::LaterPageDeadline).await;
}

#[tokio::test]
async fn actual_delayed_terminal_history_uses_refreshed_recovery_claim_time() {
    exercise_turn_history_transport(HistoryScenario::DelayedTerminal).await;
}
