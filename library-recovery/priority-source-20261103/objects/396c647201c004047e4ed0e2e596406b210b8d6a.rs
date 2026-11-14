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

async fn exercise_stalled_observation(cancel_after_request: bool) {
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
                            observed_tx
                                .take()
                                .expect("exactly one read-only request")
                                .send(params)
                                .expect("test receiver");
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

    let progressed = if cancel_after_request {
        stop.cancel();
        true
    } else {
        // Allows a proposed 5-second observation budget plus current bounded
        // transport cleanup. The production dispatch timeout is unchanged.
        timeout(Duration::from_secs(20), queue.entered.notified())
            .await
            .is_ok()
    };
    stop.cancel();
    let drained = match timeout(Duration::from_secs(12), &mut task).await {
        Ok(result) => {
            result.expect("scheduler join").expect("graceful stop");
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
    assert!(
        fixture
            .state
            .automation_is_available()
            .expect("module state")
    );
    fixture.store.close().await;
    if cancel_after_request {
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
    exercise_stalled_observation(false).await;
}

#[tokio::test]
async fn cancellation_interrupts_stalled_read_only_observation_without_new_admission() {
    exercise_stalled_observation(true).await;
}
