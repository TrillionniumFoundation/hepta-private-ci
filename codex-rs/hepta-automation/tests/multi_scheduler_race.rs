#![allow(
    clippy::expect_used,
    reason = "concurrency qualification requires explicit fixture failure context"
)]

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTick;
use codex_hepta_automation::AutomationTurnQueue;
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

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_schedulers_claim_one_occurrence_exactly_once() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    store
        .create_task(&AutomationTaskDraft::new(
            THREAD_ID,
            "multi-scheduler race",
            AutomationSchedule::Once,
            100,
            1,
        ))
        .await
        .expect("create task");

    let queue = Arc::new(RecordingQueue::default());
    let first = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("first scheduler");
    let second = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("second scheduler");

    let (left, right) = tokio::join!(first.tick(100), second.tick(100));
    let mut submitted = 0;
    let mut unavailable = 0;
    for result in [left, right] {
        match result {
            Ok(AutomationTick::Submitted { .. }) => submitted += 1,
            Ok(AutomationTick::NoTask) => {}
            Err(AutomationError::Unavailable) => unavailable += 1,
            Ok(other) => panic!("unexpected concurrent scheduler result: {other:?}"),
            Err(error) => panic!("unexpected concurrent scheduler error: {error:?}"),
        }
    }
    assert_eq!(submitted, 1);
    assert!(unavailable <= 1);
    assert_eq!(queue.admissions.lock().await.len(), 1);

    // A lock-contention loser is a proven pre-admission retry, not a second
    // semantic outcome.  Once the winning transaction settles, another tick
    // must converge without re-enqueueing the occurrence.
    let retry = first.tick(101).await.expect("post-race retry");
    assert!(matches!(retry, AutomationTick::NoTask));
    assert_eq!(queue.admissions.lock().await.len(), 1);
    assert!(
        store
            .uncertain_dispatches(8)
            .await
            .expect("uncertain dispatches")
            .is_empty()
    );
    store.close().await;
}
