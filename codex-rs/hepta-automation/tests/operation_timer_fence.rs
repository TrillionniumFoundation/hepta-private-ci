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
    fn new() -> Self {
        let directory = tempfile::tempdir().expect("directory");
        let root = directory.path().canonicalize().expect("root");
        let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            WorkspaceBinding::new(workspace, &fleet).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register").layout;
        Self {
            _directory: directory,
            layout,
        }
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
    let fixture = Fixture::new();
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
    let fixture = Fixture::new();
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
    let fixture = Fixture::new();
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

#[tokio::test]
async fn restoring_pre_retirement_database_cannot_resurrect_timer() {
    let fixture = Fixture::new();
    let owner = AutomationStore::open(&fixture.layout).await.expect("owner");
    owner
        .create_task(&draft())
        .await
        .expect("original schedule");
    let database = owner.path().to_path_buf();
    owner.close().await;
    let backup = fixture._directory.path().join("pre-retirement.sqlite3");
    std::fs::copy(&database, &backup).expect("quiescent database snapshot");
    let owner = AutomationStore::open(&fixture.layout).await.expect("owner");
    owner.quiesce_timer().await.expect("quiesce");
    owner.retire_timer().await.expect("durable retirement");
    owner.close().await;
    // Restore only the historical SQLite snapshot. The current owner's
    // independent retirement fence must not be included in that rollback.
    std::fs::copy(backup, database).expect("restore old SQLite snapshot");
    assert!(
        matches!(
            AutomationStore::open(&fixture.layout).await,
            Err(AutomationError::Corrupt)
        ),
        "a pre-retirement database must be quarantined, never reactivated"
    );
}

#[tokio::test]
async fn interrupted_retirement_fences_live_handles_and_reopened_database() {
    let fixture = Fixture::new();
    let owner = AutomationStore::open(&fixture.layout).await.expect("owner");
    let draining = owner.quiesce_timer().await.expect("quiesce");
    let fence = fixture.layout.automation_root().join("timer-retired.v1");
    let contents = format!(
        "hepta.automation.timer-retirement.v1\n{}\n{}\n",
        owner.owner_agent_id().as_str(),
        draining.writer_epoch + 1
    );
    // Reconstruct the cut after the retirement file became visible and before
    // its SQLite terminal commit. No test-only writer path exists in product.
    std::fs::write(&fence, contents).expect("retirement publication cut");
    assert_eq!(
        owner.resume_timer().await,
        Err(AutomationError::TimerFenced)
    );
    let new = draft();
    let intent = automation_task_operation_intent(
        owner.owner_agent_id(),
        &new,
        Generation::new(1).expect("generation"),
    )
    .expect("intent");
    assert_eq!(
        owner.create_task_from_operation(&intent, &new).await,
        Err(AutomationError::TimerFenced)
    );
    assert!(
        owner
            .observe_task_operation(&intent)
            .await
            .expect("no new receipt")
            .is_none()
    );
    owner.close().await;
    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::Corrupt)
    ));
}

#[tokio::test]
async fn malformed_retirement_publication_never_reopens_admission() {
    for contents in [Vec::new(), b"invalid retirement".to_vec(), vec![b'x'; 257]] {
        let fixture = Fixture::new();
        let owner = AutomationStore::open(&fixture.layout).await.expect("owner");
        owner.quiesce_timer().await.expect("quiesce");
        std::fs::write(
            fixture.layout.automation_root().join("timer-retired.v1"),
            contents,
        )
        .expect("incomplete retirement file");
        assert_eq!(owner.resume_timer().await, Err(AutomationError::Corrupt));
        owner.close().await;
        assert!(matches!(
            AutomationStore::open(&fixture.layout).await,
            Err(AutomationError::Corrupt)
        ));
    }
}

#[tokio::test]
async fn legacy_retired_database_acquires_an_immutable_restore_fence() {
    let fixture = Fixture::new();
    let owner = AutomationStore::open(&fixture.layout).await.expect("owner");
    owner.quiesce_timer().await.expect("quiesce");
    let retired = owner.retire_timer().await.expect("retire");
    owner.close().await;
    let fence = fixture.layout.automation_root().join("timer-retired.v1");
    // This fixture reconstructs a retirement by a pre-fence implementation;
    // deleting a current owner's fence is not a supported restore operation.
    std::fs::remove_file(&fence).expect("pre-fence fixture");
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("legacy retired owner");
    assert_eq!(reopened.timer_status().await.expect("status"), retired);
    assert!(fence.is_file());
    assert_eq!(
        reopened.resume_timer().await,
        Err(AutomationError::TimerFenced)
    );
    reopened.close().await;
}

#[tokio::test]
async fn taskflow_registration_waits_for_current_sqlite_writer() {
    use codex_hepta_automation::TaskFlowDefinition;
    use codex_hepta_automation::TaskFlowEdgeSpec;
    use codex_hepta_automation::TaskFlowFence;
    use codex_hepta_automation::TaskFlowNodeKind;
    use codex_hepta_automation::TaskFlowNodeSpec;
    use codex_hepta_contracts::Sha256Digest;
    let fixture = Fixture::new();
    let owner = AutomationStore::open(&fixture.layout).await.expect("owner");
    let definition = TaskFlowDefinition::new(
        "contended-workflow",
        1,
        "work",
        vec![
            TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new("done", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failed", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("work", "done"),
            TaskFlowEdgeSpec::new("work", "failed"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"contention-policy"),
    )
    .expect("definition");
    let fence = TaskFlowFence::new(
        owner.owner_agent_id().clone(),
        "taskflow-writer",
        1,
        1,
        "writer-fence",
    )
    .expect("fence");
    let sqlite_home = codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
        fixture.layout.automation_root(),
    )
    .expect("absolute owner root");
    let external = codex_state::SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(owner.path())
        .await
        .expect("second owner connection through the shared shim");
    let mut transaction = external
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer");
    sqlx::query("UPDATE automation_timer_lifecycle SET phase=phase WHERE singleton=1")
        .execute(&mut *transaction)
        .await
        .expect("existing timer writer");
    let (registered, ()) = tokio::join!(
        owner.register_taskflow_definition(&definition, &fence, 1_000),
        async {
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
            transaction.commit().await.expect("release existing writer");
        }
    );
    assert!(
        registered.is_ok(),
        "ordinary writer contention must not quarantine the capability: {registered:?}"
    );
    owner.close().await;
    external.close().await;
}
