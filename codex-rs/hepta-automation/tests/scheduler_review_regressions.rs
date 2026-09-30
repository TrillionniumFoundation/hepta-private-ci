#![allow(clippy::expect_used, reason = "integration fixture assertions")]

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationBatchStopReason;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationOccurrenceState;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationRuntimePolicyV1;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_automation::AutomationTick;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

const FIRST: &str = "019153a4-3088-7000-a56a-9b1964f76100";
const SECOND: &str = "019153a4-3088-7000-a56a-9b1964f76101";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        Self {
            _temp: temp,
            layout: registry.register(manifest).expect("register").layout,
        }
    }

    async fn open(&self) -> AutomationStore {
        let store = AutomationStore::open(&self.layout).await.expect("store");
        for id in [FIRST, SECOND] {
            let mut draft = AutomationTaskDraft::new(
                "019153a4-3088-7e03-a56a-9b1964f75ddd",
                "scheduler review regression",
                AutomationSchedule::Once,
                100,
                1,
            );
            draft.task_id = AutomationTaskId::parse(id).expect("task id");
            store.create_task(&draft).await.expect("task");
        }
        store
    }
}

#[derive(Clone)]
enum QueueMode {
    Success,
    CancelAfterReceipt,
    Fail(AutomationError),
}

struct Queue {
    mode: QueueMode,
    stop: AtomicBool,
    calls: AtomicUsize,
}

impl Queue {
    fn new(mode: QueueMode) -> Self {
        Self {
            mode,
            stop: AtomicBool::new(false),
            calls: AtomicUsize::new(0),
        }
    }
}

impl AutomationTurnQueue for Queue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            match &self.mode {
                QueueMode::Fail(error) => return Err(error.clone()),
                QueueMode::CancelAfterReceipt => self.stop.store(true, Ordering::SeqCst),
                QueueMode::Success => {}
            }
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!("accepted:{}", admission.task_id),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

fn scheduler(store: &AutomationStore, queue: &Arc<Queue>) -> AutomationScheduler<Queue> {
    AutomationScheduler::new(
        store.clone(),
        Arc::clone(queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler")
}

#[tokio::test]
async fn cancelled_batch_does_not_create_a_claim_or_contact_the_queue() {
    let fixture = Fixture::new();
    let store = fixture.open().await;
    let queue = Arc::new(Queue::new(QueueMode::Success));
    queue.stop.store(true, Ordering::SeqCst);
    let report = scheduler(&store, &queue)
        .tick_batch_cancellable(
            &AutomationRuntimePolicyV1::default(),
            || Ok(100),
            || queue.stop.load(Ordering::SeqCst),
        )
        .await
        .expect("cancelled batch");
    assert_eq!(report.ticks, Vec::new());
    assert_eq!(report.stop_reason, AutomationBatchStopReason::Cancelled);
    assert_eq!(queue.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        store
            .automation_occurrence(AutomationTaskId::parse(FIRST).expect("id"), 1)
            .await
            .expect("read"),
        None
    );
    store.close().await;
}

#[tokio::test]
async fn cancellation_preserves_first_acknowledgement_and_stops_second_claim() {
    let fixture = Fixture::new();
    let store = fixture.open().await;
    let queue = Arc::new(Queue::new(QueueMode::CancelAfterReceipt));
    let report = scheduler(&store, &queue)
        .tick_batch_cancellable(
            &AutomationRuntimePolicyV1::default(),
            || Ok(100),
            || queue.stop.load(Ordering::SeqCst),
        )
        .await
        .expect("batch");
    assert_eq!(report.stop_reason, AutomationBatchStopReason::Cancelled);
    assert_eq!(report.ticks.len(), 1);
    assert!(matches!(report.ticks[0], AutomationTick::Submitted { .. }));
    assert_eq!(queue.calls.load(Ordering::SeqCst), 1);
    let first = store
        .automation_occurrence(AutomationTaskId::parse(FIRST).expect("id"), 1)
        .await
        .expect("read")
        .expect("first occurrence");
    assert_eq!(first.state, AutomationOccurrenceState::Admitted);
    assert_eq!(
        store
            .automation_occurrence(AutomationTaskId::parse(SECOND).expect("id"), 1)
            .await
            .expect("read"),
        None
    );
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    assert_eq!(
        reopened
            .automation_occurrence(first.task_id, 1)
            .await
            .expect("read"),
        Some(first)
    );
    reopened.close().await;
}

#[tokio::test]
async fn proven_pre_admission_failure_yields_to_host_backoff_after_one_attempt() {
    let fixture = Fixture::new();
    let store = fixture.open().await;
    let queue = Arc::new(Queue::new(QueueMode::Fail(AutomationError::Dispatch)));
    let report = scheduler(&store, &queue)
        .tick_batch(&AutomationRuntimePolicyV1::default(), || Ok(100))
        .await
        .expect("batch");
    assert_eq!(report.stop_reason, AutomationBatchStopReason::RetryDeferred);
    assert_eq!(report.ticks.len(), 1);
    assert!(matches!(
        report.ticks[0],
        AutomationTick::RetryScheduled { .. }
    ));
    assert_eq!(queue.calls.load(Ordering::SeqCst), 1);
    assert!(
        store
            .uncertain_dispatches(8)
            .await
            .expect("unknown")
            .is_empty()
    );
    store.close().await;
}

#[tokio::test]
async fn fatal_and_fenced_queue_failures_keep_their_class_and_durable_uncertainty() {
    for error in [
        AutomationError::AccessDenied,
        AutomationError::TimerFenced,
        AutomationError::Corrupt,
        AutomationError::Invalid,
        AutomationError::Conflict,
    ] {
        let fixture = Fixture::new();
        let store = fixture.open().await;
        let queue = Arc::new(Queue::new(QueueMode::Fail(error.clone())));
        assert_eq!(scheduler(&store, &queue).tick(100).await, Err(error));
        assert_eq!(queue.calls.load(Ordering::SeqCst), 1);
        let before = store.uncertain_dispatches(8).await.expect("unknown");
        assert_eq!(before.len(), 1);
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen");
        assert_eq!(
            reopened.uncertain_dispatches(8).await.expect("unknown"),
            before
        );
        reopened.close().await;
    }
}
