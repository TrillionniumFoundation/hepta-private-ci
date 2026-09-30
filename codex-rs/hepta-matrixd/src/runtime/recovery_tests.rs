use super::*;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

#[derive(Clone)]
enum Fault {
    Transient,
    Slow(Duration),
    Block {
        entered: Arc<Notify>,
        release: Arc<Notify>,
    },
}

#[derive(Clone)]
struct FaultBridge {
    inner: FakeRuntimeBridge,
    event: MatrixEventId,
    fault: Fault,
}

impl MatrixRuntimeBridge for FaultBridge {
    fn ensure_room_thread<'a>(
        &'a self,
        room: &'a MatrixRoomId,
        expected: Option<&'a str>,
    ) -> MatrixRuntimeFuture<'a, RoomThreadBinding> {
        self.inner.ensure_room_thread(room, expected)
    }

    fn submit_matrix_event_on_binding<'a>(
        &'a self,
        room: &'a MatrixRoomId,
        id: &'a MatrixEventId,
        input: Vec<UserInput>,
        binding: &'a RoomThreadBinding,
        mode: MatrixAdmissionMode,
    ) -> MatrixRuntimeFuture<'a, MatrixSubmission> {
        Box::pin(async move {
            if *id == self.event {
                match &self.fault {
                    Fault::Transient => {
                        return Err(MatrixBridgeError::AppServer(
                            "temporary dependency failure".to_string(),
                        ));
                    }
                    Fault::Slow(duration) => tokio::time::sleep(*duration).await,
                    Fault::Block { entered, release } => {
                        entered.notify_one();
                        release.notified().await;
                    }
                }
            }
            self.inner
                .submit_matrix_event_on_binding(room, id, input, binding, mode)
                .await
        })
    }
}

#[tokio::test]
async fn presentation_extensions_reach_agent_as_plain_text_only() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let layout = layout(&temp, &agent_id());
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id());
    let id = event_id("$formatted");
    store.ingest_inbox(&text_inbox(id.clone(), br#"{"msgtype":"m.text","body":"safe plain fallback","format":"org.matrix.custom.html","formatted_body":"<script>never forward</script>","vendor.extra":{"instruction":"never authority"}}"#)).await?;
    let runtime = MatrixRuntime::new(store, fake.clone());
    assert!(matches!(
        runtime.process_event(&id, 20).await?,
        MatrixDispatchOutcome::Queued { .. }
    ));
    let inputs = fake
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .inputs
        .clone();
    assert_eq!(
        inputs,
        vec![vec![UserInput::Text {
            text: "safe plain fallback".to_string(),
            text_elements: vec![]
        }]]
    );
    runtime.store().close().await;
    Ok(())
}

#[tokio::test]
async fn bad_event_is_delayed_durably_while_next_event_progresses() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let layout = layout(&temp, &agent_id());
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id());
    let bad = event_id("$bad");
    let good = event_id("$good");
    for id in [&bad, &good] {
        store
            .ingest_inbox(&text_inbox(
                id.clone(),
                br#"{"msgtype":"m.text","body":"recover"}"#,
            ))
            .await?;
    }
    let bridge = FaultBridge {
        inner: fake.clone(),
        event: bad.clone(),
        fault: Fault::Transient,
    };
    let runtime = MatrixRuntime::new(store, bridge.clone());
    let report = runtime.recover_pending(2, 100).await?;
    assert_eq!(report.deferred, 1);
    assert!(
        matches!(report.outcomes.as_slice(), [MatrixDispatchOutcome::Queued { dispatch }] if dispatch.event_id == good)
    );
    assert_eq!(fake.admissions(), 1);
    runtime.store().close().await;
    drop(runtime);
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let runtime = MatrixRuntime::new(reopened, bridge);
    assert!(matches!(
        runtime.process_event(&bad, 101).await,
        Err(MatrixRuntimeError::RecoveryDeferred)
    ));
    assert_eq!(
        runtime
            .store()
            .inbox(&bad)
            .await?
            .expect("bad inbox retained")
            .state,
        InboxState::Pending
    );
    runtime.store().close().await;
    Ok(())
}

#[tokio::test]
async fn budget_yields_without_canceling_or_reordering_identity() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let layout = layout(&temp, &agent_id());
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id());
    let slow = event_id("$slow");
    let next = event_id("$next");
    for id in [&slow, &next] {
        store
            .ingest_inbox(&text_inbox(
                id.clone(),
                br#"{"msgtype":"m.text","body":"budget"}"#,
            ))
            .await?;
    }
    let runtime = MatrixRuntime::new(
        store,
        FaultBridge {
            inner: fake.clone(),
            event: slow,
            fault: Fault::Slow(Duration::from_millis(100)),
        },
    )
    .with_recovery_policy(MatrixRecoveryPolicy {
        max_batch: 2,
        pass_budget: Duration::from_millis(50),
    })?;
    let first = runtime.recover_pending(2, 100).await?;
    assert!(first.budget_exhausted);
    assert_eq!(first.outcomes.len(), 1);
    assert_eq!(fake.admissions(), 1);
    let second = runtime.recover_pending(1, 500).await?;
    assert!(
        matches!(second.outcomes.as_slice(), [MatrixDispatchOutcome::Queued { dispatch }] if dispatch.event_id == next)
    );
    assert_eq!(fake.admissions(), 2);
    runtime.store().close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn known_turn_projection_does_not_wait_for_slow_admission() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let layout = layout(&temp, &agent_id());
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id());
    let good = event_id("$project-good");
    let slow = event_id("$project-slow");
    store
        .ingest_inbox(&text_inbox(
            good.clone(),
            br#"{"msgtype":"m.text","body":"good"}"#,
        ))
        .await?;
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let runtime = Arc::new(MatrixRuntime::new(
        store,
        FaultBridge {
            inner: fake.clone(),
            event: slow.clone(),
            fault: Fault::Block {
                entered: entered.clone(),
                release: release.clone(),
            },
        },
    ));
    runtime.process_event(&good, 20).await?;
    fake.admit(
        &client_user_message_id(&agent_id(), &room_id(), &good),
        "turn-1",
    );
    runtime.process_event(&good, 30).await?;
    runtime
        .store()
        .ingest_inbox(&text_inbox(
            slow.clone(),
            br#"{"msgtype":"m.text","body":"slow"}"#,
        ))
        .await?;
    let worker_runtime = runtime.clone();
    let worker = tokio::spawn(async move { worker_runtime.process_event(&slow, 40).await });
    tokio::time::timeout(Duration::from_secs(2), entered.notified()).await?;
    let projected = tokio::time::timeout(
        Duration::from_secs(2),
        runtime.project_app_server_event(&final_event("answer"), 50),
    )
    .await;
    release.notify_one();
    worker.await??;
    assert!(matches!(
        projected??,
        MatrixEventProjection::Stored {
            kind: OutboxKind::Final,
            ..
        }
    ));
    let encoded = runtime.operational_metrics().to_string();
    assert!(
        !encoded.contains("project-good")
            && !encoded.contains("project-slow")
            && !encoded.contains("answer")
    );
    assert!(
        runtime.operational_metrics()["measurements"]["projection_gate"]["acquisitions"]
            .as_u64()
            .unwrap_or(0)
            > 0
    );
    runtime.store().close().await;
    Ok(())
}

#[tokio::test]
async fn missing_turn_lookup_reconciles_only_its_existing_thread() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let layout = layout(&temp, &agent_id());
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id());
    let id = event_id("$queued-race");
    store
        .ingest_inbox(&text_inbox(
            id.clone(),
            br#"{"msgtype":"m.text","body":"once"}"#,
        ))
        .await?;
    let runtime = MatrixRuntime::new(store, fake.clone());
    runtime.process_event(&id, 20).await?;
    fake.admit(
        &client_user_message_id(&agent_id(), &room_id(), &id),
        "turn-1",
    );
    assert!(matches!(
        runtime
            .project_app_server_event(&final_event("exact output"), 30)
            .await?,
        MatrixEventProjection::Stored { .. }
    ));
    assert_eq!(fake.admissions(), 1);
    runtime.store().close().await;
    Ok(())
}

#[tokio::test]
async fn missing_core_identity_quarantines_without_losing_output_silently() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let layout = layout(&temp, &agent_id());
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id());
    let id = event_id("$missing-turn");
    store
        .ingest_inbox(&text_inbox(
            id.clone(),
            br#"{"msgtype":"m.text","body":"once"}"#,
        ))
        .await?;
    let runtime = MatrixRuntime::new(store, fake.clone());
    runtime.process_event(&id, 20).await?;
    fake.lose_core_record(&client_user_message_id(&agent_id(), &room_id(), &id));
    assert!(matches!(
        runtime
            .project_app_server_event(&final_event("do not silently drop"), 30)
            .await,
        Err(MatrixRuntimeError::ProjectionPending)
    ));
    assert_eq!(fake.admissions(), 1);
    assert!(runtime.store().pending_outbox(10).await?.is_empty());
    runtime.store().close().await;
    Ok(())
}
