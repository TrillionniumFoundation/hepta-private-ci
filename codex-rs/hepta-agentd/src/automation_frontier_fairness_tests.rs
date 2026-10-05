//! Actual typed-peer/store regressions for both historical recovery classes.
use super::*;
use codex_hepta_automation::AutomationOccurrenceState;
use codex_hepta_automation::TaskFlowFence;

#[derive(Clone, Copy)]
enum UnknownTraffic {
    None,
    Continuous,
}

#[derive(Debug, Eq, PartialEq)]
enum ObservedClass {
    Unknown,
    Oldest,
    Younger,
}

async fn add_unknown(fixture: &Fixture, now_ms: u64) {
    let draft = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f7aaaa",
        "new unknown admission must never be replayed",
        AutomationSchedule::Once,
        now_ms,
        /*created_at_ms*/ 1,
    );
    fixture
        .store
        .create_task(&draft)
        .await
        .expect("new unknown task");
    let lease = fixture
        .store
        .claim_due(
            now_ms,
            fixture.identity.spawn_generation,
            /*lease_duration_ms*/ 60_000,
        )
        .await
        .expect("claim")
        .expect("due");
    assert_eq!(lease.task.task_id, draft.task_id);
    let occurrence = fixture
        .store
        .materialize_occurrence(&lease, now_ms)
        .await
        .expect("occurrence");
    fixture
        .store
        .prepare_occurrence_taskflow(
            &occurrence,
            &lease,
            now_ms,
            /*lease_duration_ms*/ 60_000,
        )
        .await
        .expect("outbox");
    fixture
        .store
        .record_dispatch_uncertain(&lease, now_ms)
        .await
        .expect("unknown before observation");
}

async fn exercise_history_fairness(traffic: UnknownTraffic) {
    let fixture = historical_turn_fixture(&[
        HistoricalTurnSeed {
            thread_id: "019153a4-3088-7e03-a56a-9b1964f75ddd",
            turn_id: "stalled-oldest",
        },
        HistoricalTurnSeed {
            thread_id: "019153a4-3088-7e03-a56a-9b1964f75dde",
            turn_id: "younger-terminal",
        },
    ])
    .await;
    let work = fixture
        .store
        .pending_occurrence_work(/*limit*/ 10)
        .await
        .expect("two historical rows");
    assert_eq!(work.len(), 2);
    for item in &work {
        fixture
            .store
            .ensure_admitted_taskflow_uncertainty(item, /*now_ms*/ 100_000)
            .await
            .expect("preexisting durable uncertainty");
    }
    let oldest = work
        .iter()
        .find(|item| item.occurrence.turn_id.as_deref() == Some("stalled-oldest"))
        .expect("oldest");
    let younger = work
        .iter()
        .find(|item| item.occurrence.turn_id.as_deref() == Some("younger-terminal"))
        .expect("younger");
    let before = fixture
        .store
        .automation_occurrence(oldest.occurrence.task_id, oldest.occurrence.occurrence)
        .await
        .expect("old snapshot")
        .expect("exists");
    let before_run = fixture
        .store
        .taskflow_run(&oldest.occurrence.taskflow_run_id)
        .await
        .expect("old run")
        .expect("exists");
    let fence = TaskFlowFence {
        owner_agent_id: before_run.owner_agent_id.clone(),
        owner_id: before_run.owner_id.clone().expect("historical owner"),
        owner_epoch: before_run.owner_epoch.expect("epoch"),
        generation: before_run.generation.expect("generation"),
        fencing_token: before_run.fencing_token.clone().expect("token"),
    };
    let before_step = fixture
        .store
        .read_taskflow_step(
            &before_run.run_id,
            "codex_turn",
            oldest.occurrence.step_attempt,
            &fence,
        )
        .await
        .expect("step snapshot");
    let socket = &fixture.identity.app_server_socket;
    tokio::fs::create_dir_all(socket.parent().expect("parent"))
        .await
        .expect("socket directory");
    let listener = UnixListener::bind(socket).expect("actual UDS required; no skip");
    let home = fixture.identity.home_root.to_string_lossy().into_owned();
    let expected = match traffic {
        UnknownTraffic::None => vec![ObservedClass::Oldest, ObservedClass::Younger],
        UnknownTraffic::Continuous => vec![
            ObservedClass::Unknown,
            ObservedClass::Oldest,
            ObservedClass::Unknown,
            ObservedClass::Younger,
        ],
    };
    let passes = expected.len();
    let observed = Arc::new(Mutex::new(Vec::new()));
    let server_observed = Arc::clone(&observed);
    let server = tokio::spawn(async move {
        for _ in 0..passes {
            let (stream, _) = listener
                .accept()
                .await
                .expect("actual observation connection");
            let mut websocket = tokio_tungstenite::accept_async(stream)
                .await
                .expect("WebSocket handshake");
            while let Some(frame) = websocket.next().await {
                match frame.expect("frame") {
                    Message::Text(text) => {
                        let request: serde_json::Value = serde_json::from_str(&text).expect("RPC");
                        match request["method"].as_str() {
                            Some("initialize") => websocket.send(Message::Text(serde_json::json!({
                                "id":request["id"], "result":{"userAgent":"frontier-fairness/1","codexHome":home}
                            }).to_string().into())).await.expect("initialize"),
                            Some("initialized") => {},
                            Some("thread/queue/reconcile") => {
                                let params: ThreadQueueReconcileParams = serde_json::from_value(request["params"].clone()).expect("typed queue read");
                                assert_eq!(params.mode, ThreadQueueReconcileMode::ReconcileOnly);
                                assert_eq!(params.expected_payload_sha256, crate::automation_recovery::input_digest(&params.input).expect("wire digest"));
                                server_observed.lock().expect("trace").push(ObservedClass::Unknown);
                                // Every unknown keeps withholding its response while later
                                // independent unknown arrivals keep this class nonempty.
                            }
                            Some("thread/turns/list") => {
                                let params: codex_app_server_protocol::ThreadTurnsListParams = serde_json::from_value(request["params"].clone()).expect("typed history read");
                                if params.thread_id == "019153a4-3088-7e03-a56a-9b1964f75ddd" {
                                    server_observed.lock().expect("trace").push(ObservedClass::Oldest);
                                    // The oldest historical occurrence never responds.
                                } else {
                                    assert_eq!(params.thread_id, "019153a4-3088-7e03-a56a-9b1964f75dde");
                                    server_observed.lock().expect("trace").push(ObservedClass::Younger);
                                    let response = codex_app_server_protocol::ThreadTurnsListResponse {
                                        data: vec![codex_app_server_protocol::Turn {
                                            id: "younger-terminal".to_string(), items: Vec::new(),
                                            items_view: codex_app_server_protocol::TurnItemsView::NotLoaded,
                                            status: codex_app_server_protocol::TurnStatus::Completed,
                                            error: None, started_at: None, completed_at: None, duration_ms: None,
                                        }], next_cursor: None, backwards_cursor: None,
                                    };
                                    websocket.send(Message::Text(serde_json::json!({"id":request["id"],"result":response}).to_string().into())).await.expect("terminal historical receipt");
                                }
                            }
                            method => panic!("recovery must never enqueue/replay: {method:?}"),
                        }
                    }
                    Message::Close(_) => break,
                    Message::Ping(bytes) => {
                        websocket.send(Message::Pong(bytes)).await.expect("pong")
                    }
                    _ => {}
                }
            }
        }
    });
    let mut scan = crate::automation_recovery::RecoveryScan::new(&fixture.store);
    let stop = CancellationToken::new();
    let mut expected_unknown = Vec::new();
    for index in 0..passes {
        let now_ms = 100_000 + u64::try_from(index).expect("fixture index");
        if matches!(traffic, UnknownTraffic::Continuous) {
            add_unknown(&fixture, now_ms).await;
            expected_unknown = fixture
                .store
                .uncertain_dispatches(/*limit*/ 32)
                .await
                .expect("unchanged unknown evidence");
        }
        let result = timeout(
            Duration::from_secs(18),
            crate::automation_recovery::reconcile_one(
                &fixture.store,
                &fixture.state,
                &fixture.identity,
                now_ms,
                &mut scan,
                &stop,
                &move || Ok(now_ms),
            ),
        )
        .await
        .expect("bounded observation and cleanup")
        .expect("recovery pass");
        if index + 1 == passes {
            assert!(matches!(
                result,
                crate::automation_recovery::RecoveryPass::Observed
            ));
        } else {
            assert!(matches!(
                result,
                crate::automation_recovery::RecoveryPass::Deferred
            ));
        }
    }
    timeout(Duration::from_secs(2), server)
        .await
        .expect("peer drains")
        .expect("server join");
    assert_eq!(*observed.lock().expect("trace"), expected);
    let younger_after = fixture
        .store
        .automation_occurrence(younger.occurrence.task_id, younger.occurrence.occurrence)
        .await
        .expect("younger outcome")
        .expect("retained");
    assert_eq!(younger_after.state, AutomationOccurrenceState::Succeeded);
    assert_eq!(
        fixture
            .store
            .automation_occurrence(oldest.occurrence.task_id, oldest.occurrence.occurrence)
            .await
            .expect("old uncertainty"),
        Some(before)
    );
    assert_eq!(
        fixture
            .store
            .taskflow_run(&before_run.run_id)
            .await
            .expect("old run retained"),
        Some(before_run.clone())
    );
    assert_eq!(
        fixture
            .store
            .read_taskflow_step(
                &before_run.run_id,
                "codex_turn",
                oldest.occurrence.step_attempt,
                &fence
            )
            .await
            .expect("old step retained"),
        before_step
    );
    assert_eq!(
        fixture
            .store
            .uncertain_dispatches(/*limit*/ 32)
            .await
            .expect("unknown retained"),
        expected_unknown
    );
    fixture.store.close().await;
}

#[tokio::test]
async fn stalled_oldest_history_does_not_block_younger_terminal_observation() {
    exercise_history_fairness(UnknownTraffic::None).await;
}

#[tokio::test]
async fn continuous_unknown_arrivals_do_not_starve_pending_terminal_observation() {
    exercise_history_fairness(UnknownTraffic::Continuous).await;
}
