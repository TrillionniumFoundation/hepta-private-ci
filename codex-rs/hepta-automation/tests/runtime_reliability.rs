use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationBatchLimits;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFailureDisposition;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTick;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_automation::classify_automation_error;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use tokio::sync::Mutex;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    #[allow(
        clippy::expect_used,
        reason = "test fixture construction must fail loudly"
    )]
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(
                workspace.canonicalize().expect("canonical workspace"),
                &fleet_root,
            )
            .expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register").layout;
        Self {
            _temp: temp,
            layout,
        }
    }
}

#[derive(Default)]
struct RecordingQueue {
    admissions: Mutex<Vec<AutomationAdmission>>,
}

impl AutomationTurnQueue for RecordingQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.admissions.lock().await.push(admission.clone());
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!(
                    "queue-{}-{}",
                    admission.task_id, admission.occurrence
                ),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

#[tokio::test]
async fn bounded_batch_preserves_fifo_identity_and_backlog_age() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    for index in 0..5 {
        let draft = AutomationTaskDraft::new(
            THREAD_ID,
            format!("batch task {index}"),
            AutomationSchedule::Once,
            100,
            1,
        );
        store.create_task(&draft).await.expect("task");
    }

    let before = store.backlog_snapshot(150).await.expect("backlog");
    assert_eq!(before.due_tasks, 5);
    assert_eq!(before.oldest_due_age_ms, Some(50));
    assert_eq!(before.fairness_order, "scheduled_for_ms,task_id,occurrence");

    let queue = Arc::new(RecordingQueue::default());
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("scheduler");
    let limits = AutomationBatchLimits::new(2).expect("limits");

    let first = scheduler
        .tick_batch(150, limits)
        .await
        .expect("first batch");
    assert_eq!(first.ticks.len(), 2);
    assert!(first.budget_exhausted);
    assert!(
        first
            .ticks
            .iter()
            .all(|tick| matches!(tick, AutomationTick::Submitted { .. }))
    );

    let second = scheduler
        .tick_batch(150, limits)
        .await
        .expect("second batch");
    assert_eq!(second.ticks.len(), 2);
    assert!(second.budget_exhausted);

    let third = scheduler
        .tick_batch(150, limits)
        .await
        .expect("third batch");
    assert_eq!(third.ticks.len(), 2);
    assert!(matches!(third.ticks[0], AutomationTick::Submitted { .. }));
    assert_eq!(third.ticks[1], AutomationTick::Idle);
    assert!(!third.budget_exhausted);

    let admissions = queue.admissions.lock().await;
    assert_eq!(admissions.len(), 5);
    let identities = admissions
        .iter()
        .map(|item| item.client_user_message_id.clone())
        .collect::<BTreeSet<_>>();
    assert_eq!(identities.len(), admissions.len());
    drop(admissions);

    let after = store.backlog_snapshot(150).await.expect("backlog");
    assert_eq!(after.due_tasks, 0);
    store.close().await;
}

#[test]
fn invalid_batch_and_failure_dispositions_are_explicit() {
    assert_eq!(AutomationBatchLimits::new(0), Err(AutomationError::Invalid));
    assert_eq!(
        classify_automation_error(&AutomationError::Corrupt),
        AutomationFailureDisposition::FailStop
    );
    assert_eq!(
        classify_automation_error(&AutomationError::Unavailable),
        AutomationFailureDisposition::Retry
    );
    assert_eq!(
        classify_automation_error(&AutomationError::Conflict),
        AutomationFailureDisposition::Isolate
    );
    assert_eq!(
        classify_automation_error(&AutomationError::DispatchUnknown),
        AutomationFailureDisposition::Reconcile
    );
}
