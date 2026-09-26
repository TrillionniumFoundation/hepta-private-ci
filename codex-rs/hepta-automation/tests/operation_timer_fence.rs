//! Every schedule writer, including the kernel.operations destination, must
//! honor the same durable timer epoch. These tests use real owner SQLite stores.
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::automation_task_operation_intent;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_operations::DestinationApplyDisposition;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;

struct Fixture {
    _directory: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace)?;
        let manifest = AgentManifest::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
            WorkspaceBinding::new(workspace, &fleet)?,
            ResourceBudget::local_default(),
        )?;
        let layout = registry.register(manifest)?.layout;
        Ok(Self {
            _directory: directory,
            layout,
        })
    }
}

fn draft() -> AutomationTaskDraft {
    AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "bounded owner schedule",
        AutomationSchedule::Once,
        /*first_run_at_ms*/ 20_000,
        /*created_at_ms*/ 10_000,
    )
}

#[tokio::test]
async fn kernel_destination_rejects_new_schedule_while_timer_is_draining() {
    let fixture = Fixture::new().expect("valid owner fixture");
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let draft = draft();
    let intent = automation_task_operation_intent(
        store.owner_agent_id(),
        &draft,
        Generation::new(1).expect("epoch"),
    )
    .expect("intent");
    store.quiesce_timer().await.expect("quiesce");
    assert_eq!(
        store.create_task_from_operation(&intent, &draft).await,
        Err(AutomationError::Conflict)
    );
    assert!(
        store
            .observe_task_operation(&intent)
            .await
            .expect("observation")
            .is_none()
    );
    assert!(store.task(draft.task_id).await.expect("task").is_none());
    // A denied request must not consume the operation identity.
    store.resume_timer().await.expect("resume");
    let applied = store
        .create_task_from_operation(&intent, &draft)
        .await
        .expect("apply");
    assert_eq!(applied.disposition, DestinationApplyDisposition::Applied);
    store.close().await;
}

#[tokio::test]
async fn predecessor_kernel_destination_cannot_write_after_timer_handoff() {
    let fixture = Fixture::new().expect("valid owner fixture");
    let old = AutomationStore::open(&fixture.layout).await.expect("store");
    let draft = draft();
    let intent = automation_task_operation_intent(
        old.owner_agent_id(),
        &draft,
        Generation::new(1).expect("epoch"),
    )
    .expect("intent");
    old.quiesce_timer().await.expect("quiesce");
    let successor = old.handoff_timer().await.expect("handoff");
    successor.resume_timer().await.expect("resume successor");
    assert_eq!(
        old.create_task_from_operation(&intent, &draft).await,
        Err(AutomationError::TimerFenced)
    );
    assert!(
        successor
            .observe_task_operation(&intent)
            .await
            .expect("no stolen receipt")
            .is_none()
    );
    let applied = successor
        .create_task_from_operation(&intent, &draft)
        .await
        .expect("successor apply");
    assert_eq!(applied.disposition, DestinationApplyDisposition::Applied);
    old.close().await;
    successor.close().await;
}

#[tokio::test]
async fn retirement_blocks_new_effects_after_restart_but_preserves_old_receipts() {
    let fixture = Fixture::new().expect("valid owner fixture");
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let original = draft();
    let intent = automation_task_operation_intent(
        store.owner_agent_id(),
        &original,
        Generation::new(1).expect("epoch"),
    )
    .expect("intent");
    let first = store
        .create_task_from_operation(&intent, &original)
        .await
        .expect("original apply");
    store.quiesce_timer().await.expect("quiesce");
    store.retire_timer().await.expect("retire");
    store.close().await;
    let recovered = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let new = draft();
    let next = automation_task_operation_intent(
        recovered.owner_agent_id(),
        &new,
        Generation::new(2).expect("epoch"),
    )
    .expect("new intent");
    assert_eq!(
        recovered.create_task_from_operation(&next, &new).await,
        Err(AutomationError::TimerFenced)
    );
    assert!(
        recovered
            .observe_task_operation(&next)
            .await
            .expect("no receipt")
            .is_none()
    );
    let replay = recovered
        .create_task_from_operation(&intent, &original)
        .await
        .expect("historical read-only replay");
    assert_eq!(
        replay.disposition,
        DestinationApplyDisposition::AlreadyApplied
    );
    assert_eq!(replay.destination_receipt, first.destination_receipt);
    assert_eq!(recovered.list_tasks(10).await.expect("tasks").len(), 1);
    assert_eq!(
        recovered.resume_timer().await,
        Err(AutomationError::TimerFenced)
    );
    recovered.close().await;
}
