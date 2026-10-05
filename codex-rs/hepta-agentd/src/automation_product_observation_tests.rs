//! Fresh product-baseline regression proposal; no production timeout is changed.
//! Mount as a Unix-only child of automation_service_tests and add the already
//! workspace-pinned futures/tokio-tungstenite dev dependencies before compiling.
use super::*;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_hepta_automation::AutomationTaskId;
use futures::SinkExt;
use futures::StreamExt;
use std::sync::Mutex;
use tokio::net::UnixListener;
use tokio::sync::oneshot;
use tokio_tungstenite::tungstenite::Message;

struct AdmissionLog {
    tasks: Mutex<Vec<AutomationTaskId>>,
    entered: Notify,
}

impl AutomationTurnQueue for AdmissionLog {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.tasks
                .lock()
                .expect("admission log")
                .push(admission.task_id);
            self.entered.notify_one();
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!("observed-independent:{}", admission.task_id),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

async fn ready(fixture: &Fixture) {
    fixture
        .registry
        .compare_and_transition(&fixture.identity.agent_id, 1, AgentLifecycle::Running)
        .expect("running");
    fixture
        .state
        .refresh_generation()
        .expect("current generation");
    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&fixture.identity.layout)
            .await
            .expect("cognitive owner");
    fixture
        .state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("attach owner");
    fixture
        .state
        .mark_runtime_prerequisites_ready()
        .expect("prerequisites");
    fixture
        .state
        .mark_app_server_ready()
        .expect("App Server ready");
}

#[derive(Clone, Copy)]
enum ObservationScenario {
    Defer,
    Cancel,
    NewGeneration,
    InvalidIdentity,
}

async fn exercise_stalled_observation(scenario: ObservationScenario) {
    let cancel_after_request = matches!(scenario, ObservationScenario::Cancel);
    let generation_changed = matches!(scenario, ObservationScenario::NewGeneration);
    let invalid_identity = matches!(scenario, ObservationScenario::InvalidIdentity);
    let fixture = fixture().await;
    ready(&fixture).await;
    let now = super::super::unix_time_ms().expect("time");
    let original = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "the existing unknown must never be sent again",
        AutomationSchedule::Once,
        now.saturating_sub(1_000),
        now.saturating_sub(2_000),
    );
    fixture
        .store
        .create_task(&original)
        .await
        .expect("old task");
    let lease = fixture
        .store
        .claim_due(now, 1, 60_000)
        .await
        .expect("claim")
        .expect("old due");
    assert_eq!(lease.task.task_id, original.task_id);
    let occurrence = fixture
        .store
        .materialize_occurrence(&lease, now)
        .await
        .expect("materialize");
    let dispatch = fixture
        .store
        .prepare_occurrence_taskflow(&occurrence, &lease, now, 60_000)
        .await
        .expect("durable outbox");
    fixture
        .store
        .record_dispatch_uncertain(&lease, now)
        .await
        .expect("record unknown");
    let before_unknown = fixture
        .store
        .uncertain_dispatches(16)
        .await
        .expect("unknown snapshot");
    let before_occurrence = fixture
        .store
        .automation_occurrence(original.task_id, lease.occurrence)
        .await
        .expect("occurrence snapshot");
    let before_run = fixture
        .store
        .taskflow_run(&dispatch.run.run_id)
        .await
        .expect("run snapshot");
    let before_step = fixture
        .store
        .read_taskflow_step(
            &dispatch.run.run_id,
            "codex_turn",
            dispatch.step_attempt,
            &dispatch.fence,
        )
        .await
        .expect("step snapshot");

    let independent = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "independently eligible new work",
        AutomationSchedule::Once,
        now,
        now,
    );
    fixture
        .store
        .create_task(&independent)
        .await
        .expect("independent task");
    let socket = &fixture.identity.app_server_socket;
    tokio::fs::create_dir_all(socket.parent().expect("socket parent"))
        .await
        .expect("socket directory");
    let listener =
        UnixListener::bind(socket).expect("actual UDS listener required; never skip EPERM");
    let home = fixture.identity.home_root.to_string_lossy().into_owned();
    let (observed_tx, observed_rx) = oneshot::channel();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.expect("actual connection");
        let mut websocket = tokio_tungstenite::accept_async(stream)
            .await
            .expect("WebSocket handshake");
        let mut observed_tx = Some(observed_tx);
        while let Some(message) = websocket.next().await {
            match message.expect("WebSocket message") {
                Message::Text(text) => {
                    let request: serde_json::Value = serde_json::from_str(&text).expect("JSON RPC");
                    match request["method"].as_str() {
                        Some("initialize") => {
                            websocket.send(Message::Text(serde_json::json!({
                                "id": request["id"],
                                "result": {"userAgent": "observation-fixture/1", "codexHome": home}
                            }).to_string().into())).await.expect("initialize response");
                        }
                        Some("initialized") => {}
                        Some("thread/queue/reconcile") => {
                            let params: ThreadQueueReconcileParams =
                                serde_json::from_value(request["params"].clone())
                                    .expect("real typed reconcile request");
                            assert_eq!(params.mode, ThreadQueueReconcileMode::ReconcileOnly);
                            let invalid_response = codex_app_server_protocol::ThreadQueueReconcileResponse {
                                client_user_message_id: "wrong-client-identity".to_string(),
                                payload_sha256: params.expected_payload_sha256.clone(),
                                outcome: codex_app_server_protocol::ThreadQueueReconcileOutcome::Missing,
                            };
                            observed_tx
                                .take()
                                .expect("exactly one read-only request")
                                .send(params)
                                .expect("test receiver");
                            if invalid_identity {
                                websocket
                                    .send(Message::Text(
                                        serde_json::json!({
                                            "id": request["id"], "result": invalid_response,
                                        })
                                        .to_string()
                                        .into(),
                                    ))
                                    .await
                                    .expect("invalid identity response");
                            }
                            // Intentionally withhold only this historical observation.
                            // Continue reading so WebSocket close can finish normally.
                        }
                        method => panic!("unexpected provider-facing method: {method:?}"),
                    }
                }
                Message::Close(_) => break,
                Message::Ping(bytes) => websocket.send(Message::Pong(bytes)).await.expect("pong"),
                _ => {}
            }
        }
    });
    let queue = Arc::new(AdmissionLog {
        tasks: Mutex::new(Vec::new()),
        entered: Notify::new(),
    });
    let scheduler = AutomationScheduler::new(
        fixture.store.clone(),
        Arc::clone(&queue),
        1,
        super::super::AUTOMATION_LEASE_DURATION,
        super::super::AUTOMATION_DISPATCH_TIMEOUT,
    )
    .expect("production scheduler");
    let stop = CancellationToken::new();
    let mut task = tokio::spawn(run_scheduler_loop(
        scheduler,
        Arc::clone(&fixture.state),
        stop.clone(),
        Duration::from_millis(1),
    ));
    let request = timeout(Duration::from_secs(10), observed_rx)
        .await
        .expect("server received recovery request")
        .expect("observation signal");
    assert_eq!(request.client_user_message_id, lease.client_user_message_id);
    assert_eq!(request.thread_id, original.thread_id);
    assert_eq!(
        request.expected_payload_sha256,
        crate::automation_recovery::input_digest(&request.input).expect("exact wire digest")
    );

    if generation_changed {
        fixture
            .registry
            .compare_and_transition(&fixture.identity.agent_id, 2, AgentLifecycle::Draining)
            .expect("old generation draining");
        fixture
            .registry
            .compare_and_transition(&fixture.identity.agent_id, 3, AgentLifecycle::Stopped)
            .expect("old generation stopped");
        fixture
            .registry
            .compare_and_transition(&fixture.identity.agent_id, 4, AgentLifecycle::Starting)
            .expect("new spawn generation");
    }
    let progressed = if invalid_identity {
        timeout(Duration::from_secs(12), async {
            while fixture
                .state
                .automation_is_available()
                .expect("module state")
            {
                tokio::task::yield_now().await;
            }
        })
        .await
        .is_ok()
    } else if generation_changed {
        true
    } else if cancel_after_request {
        stop.cancel();
        true
    } else {
        // Allows a proposed 5-second observation budget plus current bounded
        // transport cleanup. The production dispatch timeout is unchanged.
        timeout(Duration::from_secs(20), queue.entered.notified())
            .await
            .is_ok()
    };
    if !generation_changed {
        stop.cancel();
    }
    let drain_bound = if generation_changed { 20 } else { 12 };
    let drained = match timeout(Duration::from_secs(drain_bound), &mut task).await {
        Ok(result) => {
            let result = result.expect("scheduler join");
            if generation_changed {
                assert!(matches!(
                    result,
                    Err(crate::AgentdError::GenerationFenced(_))
                ));
            } else {
                result.expect("graceful stop");
            }
            true
        }
        Err(_) => {
            task.abort();
            let _ = task.await;
            false
        }
    };
    server.abort();
    match server.await {
        Ok(()) => {}
        Err(error) if error.is_cancelled() => {}
        Err(error) => panic!("observation server failed: {error}"),
    }

    // Check safety even when the desired liveness assertion is expected red.
    assert_eq!(
        fixture
            .store
            .uncertain_dispatches(16)
            .await
            .expect("unknown after"),
        before_unknown
    );
    assert_eq!(
        fixture
            .store
            .automation_occurrence(original.task_id, lease.occurrence)
            .await
            .expect("occurrence after"),
        before_occurrence
    );
    assert_eq!(
        fixture
            .store
            .taskflow_run(&dispatch.run.run_id)
            .await
            .expect("run after"),
        before_run
    );
    assert_eq!(
        fixture
            .store
            .read_taskflow_step(
                &dispatch.run.run_id,
                "codex_turn",
                dispatch.step_attempt,
                &dispatch.fence,
            )
            .await
            .expect("step after"),
        before_step
    );
    let admissions = queue.tasks.lock().expect("admission log").clone();
    assert!(
        !admissions.contains(&original.task_id),
        "unknown effect was readmitted"
    );
    if generation_changed {
        assert!(fixture.state.is_fenced().expect("fenced state"));
    } else if invalid_identity {
        assert!(
            !fixture
                .state
                .automation_is_available()
                .expect("module state")
        );
        assert!(!fixture.state.is_fenced().expect("generation state"));
    } else {
        assert!(
            fixture
                .state
                .automation_is_available()
                .expect("module state")
        );
    }
    fixture.store.close().await;
    if generation_changed || invalid_identity {
        assert!(
            admissions.is_empty(),
            "fatal observation admitted independent work"
        );
        assert!(progressed && drained, "fatal disposition was not preserved");
    } else if cancel_after_request {
        assert!(admissions.is_empty(), "cancellation admitted new work");
        assert!(
            drained,
            "stalled read-only recovery prevented graceful cancellation"
        );
    } else {
        assert!(
            progressed,
            "one historical observation starved independent eligible work"
        );
        assert_eq!(admissions, vec![independent.task_id]);
        assert!(drained, "scheduler did not drain");
    }
}

#[tokio::test]
async fn stalled_historical_observation_does_not_starve_independent_work() {
    exercise_stalled_observation(ObservationScenario::Defer).await;
}

#[tokio::test]
async fn cancellation_interrupts_stalled_read_only_observation_without_new_admission() {
    exercise_stalled_observation(ObservationScenario::Cancel).await;
}

#[tokio::test]
async fn generation_change_during_deferred_observation_fences_before_mutation() {
    exercise_stalled_observation(ObservationScenario::NewGeneration).await;
}

#[tokio::test]
async fn invalid_identity_is_fatal_not_a_negative_or_deferred_observation() {
    exercise_stalled_observation(ObservationScenario::InvalidIdentity).await;
}

async fn lease_times(fixture: &Fixture, task_id: AutomationTaskId) -> (i64, i64) {
    use sqlx::Connection;
    let options = sqlx::sqlite::SqliteConnectOptions::new()
        .filename(fixture.store.path())
        .read_only(true);
    let mut connection = sqlx::SqliteConnection::connect_with(&options)
        .await
        .expect("read-only owner view");
    let values = sqlx::query_as::<_, (i64, i64)>(
        "SELECT scheduled_for_ms, lease_expires_at_ms FROM automation_runs WHERE task_id = ? AND state = 'leased'",
    ).bind(task_id.to_string()).fetch_one(&mut connection).await.expect("live lease");
    connection.close().await.expect("close read view");
    values
}

#[tokio::test]
async fn admission_lease_uses_clock_resampled_after_recovery_phase() {
    let fixture = fixture().await;
    ready(&fixture).await;
    let draft = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "fresh admission time",
        AutomationSchedule::Once,
        1_000,
        1,
    );
    fixture.store.create_task(&draft).await.expect("task");
    let queue = Arc::new(DelayedQueue {
        entered: Notify::new(),
        release: Notify::new(),
        completed: AtomicUsize::new(0),
    });
    let scheduler = AutomationScheduler::new(
        fixture.store.clone(),
        Arc::clone(&queue),
        1,
        super::super::AUTOMATION_LEASE_DURATION,
        super::super::AUTOMATION_DISPATCH_TIMEOUT,
    )
    .expect("scheduler");
    let samples = Arc::new(AtomicUsize::new(0));
    let clock_samples = Arc::clone(&samples);
    let stop = CancellationToken::new();
    let mut task = tokio::spawn(super::super::run_scheduler_loop_with_clock(
        scheduler,
        Arc::clone(&fixture.state),
        stop.clone(),
        Duration::from_millis(1),
        move || {
            Ok(if clock_samples.fetch_add(1, Ordering::SeqCst) == 0 {
                1_000
            } else {
                10_000
            })
        },
    ));
    timeout(Duration::from_secs(2), queue.entered.notified())
        .await
        .expect("admitted queue wait");
    let times = lease_times(&fixture, draft.task_id).await;
    stop.cancel();
    assert!(
        timeout(Duration::from_millis(20), &mut task).await.is_err(),
        "admitted acknowledgement must not be cancelled"
    );
    queue.release.notify_one();
    timeout(Duration::from_secs(2), task)
        .await
        .expect("drain")
        .expect("join")
        .expect("stop");
    fixture.store.close().await;
    assert!(samples.load(Ordering::SeqCst) >= 2);
    assert_eq!(
        times,
        (1_000, 40_000),
        "schedule instant stays fixed; lease starts from refreshed admission time"
    );
}

#[tokio::test]
async fn delayed_historical_response_refreshes_reconciliation_and_new_lease_time() {
    use std::sync::atomic::AtomicU64;
    let fixture = fixture().await;
    ready(&fixture).await;
    let old = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "already unknown",
        AutomationSchedule::Once,
        1_000,
        1,
    );
    fixture.store.create_task(&old).await.expect("old task");
    let lease = fixture
        .store
        .claim_due(1_000, 1, 60_000)
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
        .prepare_occurrence_taskflow(&occurrence, &lease, 1_000, 60_000)
        .await
        .expect("outbox");
    fixture
        .store
        .record_dispatch_uncertain(&lease, 1_000)
        .await
        .expect("unknown");
    let new = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "new eligible task",
        AutomationSchedule::Once,
        1_000,
        1,
    );
    fixture.store.create_task(&new).await.expect("new task");
    let socket = &fixture.identity.app_server_socket;
    tokio::fs::create_dir_all(socket.parent().expect("parent"))
        .await
        .expect("socket directory");
    let listener = UnixListener::bind(socket).expect("actual UDS required");
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
        while let Some(frame) = websocket.next().await {
            match frame.expect("frame") {
                Message::Text(text) => {
                    let request: serde_json::Value = serde_json::from_str(&text).expect("RPC");
                    match request["method"].as_str() {
                        Some("initialize") => websocket.send(Message::Text(serde_json::json!({
                            "id": request["id"], "result": {"userAgent":"clock-fixture/1", "codexHome":home},
                        }).to_string().into())).await.expect("initialize"),
                        Some("initialized") => {},
                        Some("thread/queue/reconcile") => {
                            let params: ThreadQueueReconcileParams = serde_json::from_value(request["params"].clone()).expect("typed observation");
                            assert_eq!(params.mode, ThreadQueueReconcileMode::ReconcileOnly);
                            observed_tx.take().expect("single observation").send(params.clone()).expect("barrier");
                            release_rx.take().expect("release receiver").await.expect("logical clock advanced");
                            let response = codex_app_server_protocol::ThreadQueueReconcileResponse {
                                client_user_message_id: params.client_user_message_id,
                                payload_sha256: params.expected_payload_sha256,
                                outcome: codex_app_server_protocol::ThreadQueueReconcileOutcome::Persisted { turn_id: "existing-turn".to_string() },
                            };
                            websocket.send(Message::Text(serde_json::json!({"id":request["id"],"result":response}).to_string().into())).await.expect("existing outcome");
                        }
                        other => panic!("unexpected request: {other:?}"),
                    }
                }
                Message::Close(_) => break,
                Message::Ping(bytes) => websocket.send(Message::Pong(bytes)).await.expect("pong"),
                _ => {}
            }
        }
    });
    let queue = Arc::new(DelayedQueue {
        entered: Notify::new(),
        release: Notify::new(),
        completed: AtomicUsize::new(0),
    });
    let scheduler = AutomationScheduler::new(
        fixture.store.clone(),
        Arc::clone(&queue),
        1,
        super::super::AUTOMATION_LEASE_DURATION,
        super::super::AUTOMATION_DISPATCH_TIMEOUT,
    )
    .expect("scheduler");
    let now = Arc::new(AtomicU64::new(1_000));
    let clock = Arc::clone(&now);
    let stop = CancellationToken::new();
    let task = tokio::spawn(super::super::run_scheduler_loop_with_clock(
        scheduler,
        Arc::clone(&fixture.state),
        stop.clone(),
        Duration::from_millis(1),
        move || Ok(clock.load(Ordering::SeqCst)),
    ));
    let observed = timeout(Duration::from_secs(5), observed_rx)
        .await
        .expect("read reached server")
        .expect("observation");
    assert_eq!(
        observed.client_user_message_id,
        lease.client_user_message_id
    );
    now.store(10_000, Ordering::SeqCst);
    release_tx
        .send(())
        .expect("release delayed historical response");
    timeout(Duration::from_secs(12), queue.entered.notified())
        .await
        .expect("new admission");
    let times = lease_times(&fixture, new.task_id).await;
    let old_after = fixture
        .store
        .automation_occurrence(old.task_id, lease.occurrence)
        .await
        .expect("old occurrence")
        .expect("retained");
    stop.cancel();
    queue.release.notify_one();
    timeout(Duration::from_secs(2), task)
        .await
        .expect("drain")
        .expect("join")
        .expect("stop");
    server.abort();
    match server.await {
        Ok(()) => {}
        Err(error) if error.is_cancelled() => {}
        Err(error) => panic!("server: {error}"),
    }
    fixture.store.close().await;
    assert_eq!(times, (1_000, 40_000));
    assert_eq!(old_after.turn_id.as_deref(), Some("existing-turn"));
    assert_eq!(old_after.updated_at_ms, 10_000);
    assert_eq!(
        queue.completed.load(Ordering::SeqCst),
        1,
        "only the new occurrence was admitted"
    );
}

#[path = "automation_history_observation_tests.rs"]
mod history_transport_tests;
