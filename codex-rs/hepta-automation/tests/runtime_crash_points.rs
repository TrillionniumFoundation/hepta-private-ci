#![allow(
    clippy::expect_used,
    reason = "test assertions use explicit failure context"
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

#[derive(Clone, Copy)]
enum QueueMode {
    BeforeAdmissionFailure,
    OutcomeUnknown,
}

struct CrashQueue {
    mode: QueueMode,
}

impl AutomationTurnQueue for CrashQueue {
    fn enqueue(
        &self,
        _admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        let mode = self.mode;
        Box::pin(async move {
            match mode {
                QueueMode::BeforeAdmissionFailure => Err(AutomationError::Dispatch),
                QueueMode::OutcomeUnknown => Err(AutomationError::DispatchUnknown),
            }
        })
    }
}

async fn create_due(store: &AutomationStore, prompt: &str) {
    store
        .create_task(&AutomationTaskDraft::new(
            THREAD_ID,
            prompt,
            AutomationSchedule::Once,
            100,
            1,
        ))
        .await
        .expect("create task");
}

#[tokio::test]
async fn possible_admission_survives_close_and_reopen_as_exact_uncertainty() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    create_due(&store, "unknown after provider boundary").await;
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(CrashQueue {
            mode: QueueMode::OutcomeUnknown,
        }),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("scheduler");
    let tick = scheduler.tick(100).await.expect("tick");
    let (task_id, occurrence) = match tick {
        AutomationTick::DispatchUncertain {
            task_id,
            occurrence,
        } => (task_id, occurrence),
        other => panic!("expected uncertainty, observed {other:?}"),
    };
    let before = store.uncertain_dispatches(8).await.expect("uncertain");
    assert_eq!(before.len(), 1);
    let stable_client_id = before[0].client_user_message_id.clone();
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let after = reopened
        .uncertain_dispatches(8)
        .await
        .expect("reopened uncertainty");
    assert_eq!(after.len(), 1);
    assert_eq!(after[0].task_id, task_id);
    assert_eq!(after[0].occurrence, occurrence);
    assert_eq!(after[0].client_user_message_id, stable_client_id);
    reopened.close().await;
}

#[tokio::test]
async fn proven_pre_admission_failure_is_retryable_and_never_quarantined_unknown() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    create_due(&store, "failure before provider boundary").await;
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(CrashQueue {
            mode: QueueMode::BeforeAdmissionFailure,
        }),
        1,
        Duration::from_secs(30),
        Duration::from_secs(5),
    )
    .expect("scheduler");
    assert!(matches!(
        scheduler.tick(100).await.expect("tick"),
        AutomationTick::RetryScheduled { .. }
    ));
    assert!(
        store
            .uncertain_dispatches(8)
            .await
            .expect("uncertain")
            .is_empty()
    );
    store.close().await;
}
