use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationBatchStopReason;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
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
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register agent").layout;
        Self {
            _temp: temp,
            layout,
        }
    }
}

struct SuccessQueue;

impl AutomationTurnQueue for SuccessQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!(
                    "batch:{}:{}",
                    admission.task_id, admission.occurrence
                ),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

struct UnknownQueue;

impl AutomationTurnQueue for UnknownQueue {
    fn enqueue(
        &self,
        _admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async { Err(AutomationError::DispatchUnknown) })
    }
}

fn task(id: &str) -> AutomationTaskDraft {
    let mut draft = AutomationTaskDraft::new(
        THREAD_ID,
        "bounded batch work",
        AutomationSchedule::Once,
        100,
        1,
    );
    draft.task_id = AutomationTaskId::parse(id).expect("task id");
    draft
}

#[tokio::test]
async fn bounded_batch_drains_only_its_admission_budget() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    for id in [
        "019153a4-3088-7000-a56a-9b1964f76000",
        "019153a4-3088-7000-a56a-9b1964f76001",
        "019153a4-3088-7000-a56a-9b1964f76002",
        "019153a4-3088-7000-a56a-9b1964f76003",
        "019153a4-3088-7000-a56a-9b1964f76004",
    ] {
        store.create_task(&task(id)).await.expect("create task");
    }
    let scheduler = AutomationScheduler::new(
        store,
        Arc::new(SuccessQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    let policy = AutomationRuntimePolicyV1 {
        admission_budget_per_cycle: 3,
        ..AutomationRuntimePolicyV1::default()
    };

    let first = scheduler
        .tick_batch(&policy, || Ok(100))
        .await
        .expect("first batch");
    assert_eq!(first.ticks.len(), 3);
    assert_eq!(
        first.stop_reason,
        AutomationBatchStopReason::AdmissionBudgetExhausted
    );
    assert!(
        first
            .ticks
            .iter()
            .all(|tick| matches!(tick, AutomationTick::Submitted { .. }))
    );

    let second = scheduler
        .tick_batch(&policy, || Ok(101))
        .await
        .expect("second batch");
    assert_eq!(second.ticks.len(), 3);
    assert!(matches!(second.ticks.last(), Some(AutomationTick::Idle)));
    assert_eq!(second.stop_reason, AutomationBatchStopReason::Idle);
}

#[tokio::test]
async fn unknown_dispatch_stops_the_batch_before_a_second_identity_is_contacted() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    store
        .create_task(&task("019153a4-3088-7000-a56a-9b1964f76100"))
        .await
        .expect("first task");
    store
        .create_task(&task("019153a4-3088-7000-a56a-9b1964f76101"))
        .await
        .expect("second task");
    let scheduler = AutomationScheduler::new(
        store,
        Arc::new(UnknownQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");

    let report = scheduler
        .tick_batch(&AutomationRuntimePolicyV1::default(), || Ok(100))
        .await
        .expect("batch");
    assert_eq!(report.ticks.len(), 1);
    assert!(matches!(
        report.ticks[0],
        AutomationTick::DispatchUncertain { .. }
    ));
    assert_eq!(
        report.stop_reason,
        AutomationBatchStopReason::DispatchUncertain
    );
}
