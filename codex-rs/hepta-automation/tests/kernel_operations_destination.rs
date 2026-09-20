use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationOperationDisposition;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::automation_task_operation_intent;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let agent_id = AgentId::parse(AGENT_ID).expect("agent id");
        let manifest = AgentManifest::new(
            agent_id,
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

fn draft() -> AutomationTaskDraft {
    AutomationTaskDraft::new(
        THREAD_ID,
        "create a durable bounded automation task",
        AutomationSchedule::FixedInterval { interval_ms: 5_000 },
        20_000,
        10_000,
    )
}

#[tokio::test]
async fn exact_operation_replay_returns_one_task_and_one_destination_receipt() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("open");
    let draft = draft();
    let operation =
        automation_task_operation_intent(store.owner_agent_id(), &draft).expect("operation");

    let first = store
        .create_task_from_operation(&operation, &draft)
        .await
        .expect("first create");
    assert_eq!(first.disposition, AutomationOperationDisposition::Applied);

    let replay = store
        .create_task_from_operation(&operation, &draft)
        .await
        .expect("exact replay");
    assert_eq!(
        replay.disposition,
        AutomationOperationDisposition::AlreadyApplied
    );
    assert_eq!(replay.task, first.task);
    assert_eq!(replay.outcome_digest, first.outcome_digest);
    assert_eq!(store.list_tasks(10).await.expect("list").len(), 1);
}

#[tokio::test]
async fn same_operation_identity_with_changed_task_payload_conflicts() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("open");
    let draft = draft();
    let operation =
        automation_task_operation_intent(store.owner_agent_id(), &draft).expect("operation");
    store
        .create_task_from_operation(&operation, &draft)
        .await
        .expect("first create");

    let mut changed = draft.clone();
    changed.prompt = "changed semantic payload".to_owned();
    let changed_operation =
        automation_task_operation_intent(store.owner_agent_id(), &changed).expect("changed");
    assert_eq!(changed_operation.key.id, operation.key.id);
    assert_ne!(
        changed_operation.key.payload_digest,
        operation.key.payload_digest
    );
    assert_eq!(
        store
            .create_task_from_operation(&changed_operation, &changed)
            .await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(store.list_tasks(10).await.expect("list").len(), 1);
}

#[tokio::test]
async fn mismatched_destination_or_predecessor_is_denied_before_domain_mutation() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("open");
    let draft = draft();

    let mut wrong_destination =
        automation_task_operation_intent(store.owner_agent_id(), &draft).expect("operation");
    wrong_destination.destination =
        StableId::new("cognitive.store").expect("different destination");
    assert_eq!(
        store
            .create_task_from_operation(&wrong_destination, &draft)
            .await,
        Err(AutomationError::AccessDenied)
    );

    let mut wrong_predecessor =
        automation_task_operation_intent(store.owner_agent_id(), &draft).expect("operation");
    wrong_predecessor.expected_predecessor =
        Some(Digest32::of_bytes(b"unexpected-predecessor"));
    assert_eq!(
        store
            .create_task_from_operation(&wrong_predecessor, &draft)
            .await,
        Err(AutomationError::AccessDenied)
    );
    assert!(store.list_tasks(10).await.expect("list").is_empty());
}

#[tokio::test]
async fn destination_dedupe_and_task_survive_store_reopen() {
    let fixture = Fixture::new();
    let draft = draft();
    let store = AutomationStore::open(&fixture.layout).await.expect("open");
    let operation =
        automation_task_operation_intent(store.owner_agent_id(), &draft).expect("operation");
    let first = store
        .create_task_from_operation(&operation, &draft)
        .await
        .expect("first create");
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout).await.expect("reopen");
    let observed = reopened
        .observe_task_operation(&operation)
        .await
        .expect("observe")
        .expect("destination receipt");
    assert_eq!(
        observed.disposition,
        AutomationOperationDisposition::AlreadyApplied
    );
    assert_eq!(observed.task, first.task);
    assert_eq!(observed.outcome_digest, first.outcome_digest);
}
