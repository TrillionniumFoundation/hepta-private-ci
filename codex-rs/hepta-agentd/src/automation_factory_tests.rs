//! Existing owner factory exercised with a substituted typed queue.

use super::*;

struct RejectingQueue {
    admissions: tokio::sync::mpsc::Sender<AutomationAdmission>,
    release: Notify,
}

impl AutomationTurnQueue for RejectingQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.admissions
                .send(admission)
                .await
                .expect("bounded admission observation");
            self.release.notified().await;
            Err(AutomationError::Dispatch)
        })
    }
}

#[tokio::test]
async fn factory_routes_substituted_queue_and_drains_before_handoff() {
    let fixture = fixture().await;
    fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            fixture.identity.spawn_generation,
            AgentLifecycle::Running,
        )
        .expect("running");
    // A live predecessor still owns the durable prompt/host lock. Replacement
    // must release that host, not weaken the owner lock to assemble the fixture.
    assert!(AgentdState::new(fixture.identity.clone(), fixture.registry.clone(), 128).is_err());
    drop(fixture.state);
    let event_capacity = 128;
    let state = Arc::new(
        AgentdState::new(
            fixture.identity.clone(),
            fixture.registry.clone(),
            event_capacity,
        )
        .expect("host"),
    );
    let service =
        AutomationService::open(Arc::clone(&state), crate::RuntimeModuleProfileV1::Compiled)
            .await
            .expect("production owner factory");
    let cognitive = codex_hepta_agent_components::cognitive_store::DurableCognitiveStore::open(
        &fixture.identity.layout,
    )
    .await
    .expect("cognitive owner");
    state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("attachment");
    state
        .mark_runtime_prerequisites_ready()
        .expect("prerequisites");
    state.mark_app_server_ready().expect("ready");
    let original = fixture.store.create_task(&draft()).await.expect("task");
    let admission_capacity = 1;
    let (admissions, mut received) = tokio::sync::mpsc::channel(admission_capacity);
    let queue = Arc::new(RejectingQueue {
        admissions,
        release: Notify::new(),
    });
    let (mut tasks, stop) = host();
    service
        .spawn_with_queue(&mut tasks, Arc::clone(&queue), stop.clone())
        .await
        .expect("same startup path as Agentd");
    let admission = timeout(Duration::from_secs(2), received.recv())
        .await
        .expect("bounded dispatch")
        .expect("real scheduler reached substitute");
    assert_eq!(
        (admission.agent_id, admission.task_id, admission.prompt),
        (
            fixture.identity.agent_id.clone(),
            original.task_id,
            "preserve the existing owner result".to_string(),
        ),
    );
    {
        let retirement = tasks.retire_optional_generation(
            "automation.taskflow",
            Generation::new(fixture.identity.spawn_generation).expect("generation"),
        );
        tokio::pin!(retirement);
        assert!(
            timeout(Duration::from_millis(30), &mut retirement)
                .await
                .is_err()
        );
        queue.release.notify_one();
        timeout(Duration::from_secs(2), retirement)
            .await
            .expect("bounded retirement")
            .expect("pre-admission rejection permits drain");
    }
    assert_eq!(tasks.active_count(), 0);
    assert!(!stop.is_cancelled());
    assert!(!state.automation_is_available().expect("route removed"));
    let status = fixture.store.timer_status().await.expect("owner state");
    assert_eq!(
        (
            status.phase,
            status.leased_occurrences,
            status.uncertain_dispatches
        ),
        (TimerPhase::Draining, 0, 0)
    );
    assert!(status.can_handoff());
    let successor = fixture.store.handoff_timer().await.expect("handoff");
    assert_eq!(
        fixture.store.create_task(&draft()).await,
        Err(AutomationError::TimerFenced)
    );
    assert_eq!(
        successor
            .timer_status()
            .await
            .expect("successor")
            .writer_epoch,
        status.writer_epoch + 1
    );
    assert_eq!(
        successor.list_tasks(10).await.expect("retained task").len(),
        1
    );
    tasks.shutdown().await;
    successor.close().await;
    fixture.store.close().await;
}
