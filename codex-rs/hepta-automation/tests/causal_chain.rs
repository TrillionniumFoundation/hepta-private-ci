#![allow(
    clippy::expect_used,
    reason = "causal-chain integration fixtures should fail loudly"
)]

use codex_hepta_automation::AutomationDispatchState;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationMissedRunPolicy;
use codex_hepta_automation::AutomationOccurrenceState;
use codex_hepta_automation::AutomationOverlapPolicy;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_automation::AutomationTaskState;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
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
        let root = temp.path().canonicalize().expect("canonical temp root");
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
        Self {
            _temp: temp,
            layout: registry.register(manifest).expect("register agent").layout,
        }
    }
}

fn draft(id: &str, schedule: AutomationSchedule, due: u64) -> AutomationTaskDraft {
    let mut draft = AutomationTaskDraft::new(THREAD_ID, "causal work", schedule, due, 1);
    draft.task_id = AutomationTaskId::parse(id).expect("task id");
    draft
}

fn definition() -> TaskFlowDefinition {
    TaskFlowDefinition::new(
        "automation-causal",
        1,
        "work",
        vec![
            TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("work", "success"),
            TaskFlowEdgeSpec::new("work", "failure"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"automation-causal-policy"),
    )
    .expect("definition")
}

fn fence(generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "automation-causal-owner",
        1,
        generation,
        format!("automation-causal-fence-{generation}"),
    )
    .expect("fence")
}

fn receipt(
    lease: &codex_hepta_automation::AutomationLease,
    suffix: &str,
) -> AutomationQueueReceipt {
    AutomationQueueReceipt {
        queued_submission_id: format!("queue-{}-{suffix}", lease.occurrence),
        client_user_message_id: lease.client_user_message_id.clone(),
    }
}

async fn register_definition(
    store: &AutomationStore,
    owner: &TaskFlowFence,
) -> TaskFlowDefinition {
    let definition = definition();
    store
        .register_taskflow_definition(&definition, owner, 10)
        .await
        .expect("register definition");
    definition
}

async fn terminalize_succeeded(
    store: &AutomationStore,
    task_id: AutomationTaskId,
    occurrence: u64,
    definition: &TaskFlowDefinition,
    owner: &TaskFlowFence,
    now_ms: u64,
) {
    let run = store
        .ensure_occurrence_taskflow_run(
            task_id,
            occurrence,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            now_ms,
        )
        .await
        .expect("ensure occurrence TaskFlow run");
    let claimed = store
        .claim_taskflow_run(&run.run_id, owner, now_ms + 1, 1_000)
        .await
        .expect("claim TaskFlow run");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &run.run_id,
                format!("start-{occurrence}"),
                owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                now_ms + 2,
            )
            .expect("start command"),
        )
        .await
        .expect("start TaskFlow run");
    store
        .sync_occurrence_from_taskflow(task_id, occurrence, now_ms + 2)
        .await
        .expect("sync running occurrence");
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &run.run_id,
                format!("succeed-{occurrence}"),
                owner.clone(),
                started.revision,
                TaskFlowTransition::Succeed {
                    output_digest: Sha256Digest::for_bytes(b"automation-output"),
                },
                now_ms + 3,
            )
            .expect("success command"),
        )
        .await
        .expect("succeed TaskFlow run");
    let terminal = store
        .sync_occurrence_from_taskflow(task_id, occurrence, now_ms + 3)
        .await
        .expect("sync terminal occurrence");
    assert_eq!(
        terminal.execution_state,
        AutomationOccurrenceState::Succeeded
    );
}

#[tokio::test]
async fn queue_admission_is_not_terminal_and_taskflow_terminal_is_durable() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75101",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let lease = store
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim due")
        .expect("lease");
    assert_eq!(lease.schedule_revision, 1);
    assert_eq!(
        lease.occurrence_id,
        format!(
            "hepta.automation.occurrence.v1:{}:1:100",
            task.task_id
        )
    );
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("read task")
            .expect("task")
            .state,
        AutomationTaskState::Enabled
    );

    let owner = fence(1);
    let definition = register_definition(&store, &owner).await;
    let run = store
        .ensure_occurrence_taskflow_run(
            task.task_id,
            lease.occurrence,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            101,
        )
        .await
        .expect("bind TaskFlow");
    assert_eq!(run.run_id, lease.occurrence_id);

    store
        .mark_submitted(&lease, &receipt(&lease, "accepted"), 102)
        .await
        .expect("queue admission");
    let admitted = store
        .occurrence(task.task_id, 1)
        .await
        .expect("read occurrence")
        .expect("occurrence");
    assert_eq!(admitted.dispatch_state, AutomationDispatchState::Submitted);
    assert_eq!(
        admitted.execution_state,
        AutomationOccurrenceState::TaskFlowBound
    );
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("read task")
            .expect("task")
            .state,
        AutomationTaskState::Enabled
    );

    terminalize_succeeded(&store, task.task_id, 1, &definition, &owner, 103).await;
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("read completed task")
            .expect("task")
            .state,
        AutomationTaskState::Completed
    );
    let path = store.path().to_path_buf();
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen store");
    assert_eq!(reopened.path(), path.as_path());
    let persisted = reopened
        .occurrence(task.task_id, 1)
        .await
        .expect("read persisted occurrence")
        .expect("occurrence");
    assert_eq!(
        persisted.execution_state,
        AutomationOccurrenceState::Succeeded
    );
    assert_eq!(persisted.taskflow_run_id.as_deref(), Some(run.run_id.as_str()));
}

#[tokio::test]
async fn forbid_overlap_waits_for_taskflow_terminal_but_allow_overlap_does_not() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let owner = fence(1);
    let definition = register_definition(&store, &owner).await;

    let forbid = draft(
        "019153a4-3088-7000-a56a-9b1964f75102",
        AutomationSchedule::FixedInterval { interval_ms: 1_000 },
        100,
    );
    store.create_task(&forbid).await.expect("create forbid task");
    let first = store
        .claim_due(100, 1, 60_000)
        .await
        .expect("first claim")
        .expect("first lease");
    store
        .mark_submitted(&first, &receipt(&first, "forbid"), 101)
        .await
        .expect("first admission");
    assert!(
        store
            .claim_due(1_100, 1, 60_000)
            .await
            .expect("overlap check")
            .is_none(),
        "default forbid policy must hold the next occurrence until execution terminal"
    );
    terminalize_succeeded(&store, forbid.task_id, 1, &definition, &owner, 102).await;
    let second = store
        .claim_due(1_100, 1, 60_000)
        .await
        .expect("claim after terminal")
        .expect("second occurrence");
    assert_eq!(second.occurrence, 2);
    assert_eq!(second.scheduled_for_ms, 1_100);
    store
        .mark_submitted(&second, &receipt(&second, "forbid-2"), 1_101)
        .await
        .expect("second admission");
    terminalize_succeeded(&store, forbid.task_id, 2, &definition, &owner, 1_102).await;
    store
        .cancel_task(forbid.task_id, 1_200)
        .await
        .expect("retire forbid fixture before allow case");

    let allow = draft(
        "019153a4-3088-7000-a56a-9b1964f75103",
        AutomationSchedule::FixedInterval { interval_ms: 1_000 },
        10_000,
    )
    .with_overlap_policy(AutomationOverlapPolicy::Allow);
    store.create_task(&allow).await.expect("create allow task");
    let allow_first = store
        .claim_due(10_000, 1, 60_000)
        .await
        .expect("allow first claim")
        .expect("allow first");
    store
        .mark_submitted(&allow_first, &receipt(&allow_first, "allow"), 10_001)
        .await
        .expect("allow first admission");
    let allow_second = store
        .claim_due(11_000, 1, 60_000)
        .await
        .expect("allow overlap claim")
        .expect("allow overlap occurrence");
    assert_eq!(allow_second.occurrence, 2);
    assert_eq!(allow_second.scheduled_for_ms, 11_000);
}

#[tokio::test]
async fn missed_run_policy_is_bounded_and_deterministic() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");

    let skipped = draft(
        "019153a4-3088-7000-a56a-9b1964f75104",
        AutomationSchedule::FixedInterval { interval_ms: 1_000 },
        100,
    );
    store.create_task(&skipped).await.expect("create skip task");
    let latest = store
        .claim_due(5_100, 1, 60_000)
        .await
        .expect("skip claim")
        .expect("latest retained occurrence");
    assert_eq!(latest.occurrence, 6);
    assert_eq!(latest.scheduled_for_ms, 5_100);

    let bounded = draft(
        "019153a4-3088-7000-a56a-9b1964f75105",
        AutomationSchedule::FixedInterval { interval_ms: 1_000 },
        20_100,
    )
    .with_missed_run_policy(AutomationMissedRunPolicy::BoundedCatchUp {
        max_occurrences: 3,
    })
    .with_overlap_policy(AutomationOverlapPolicy::Allow);
    store.create_task(&bounded).await.expect("create bounded task");
    let one = store
        .claim_due(25_100, 1, 60_000)
        .await
        .expect("bounded one")
        .expect("bounded occurrence one");
    assert_eq!((one.occurrence, one.scheduled_for_ms), (4, 23_100));
    store
        .mark_submitted(&one, &receipt(&one, "bounded-1"), 25_101)
        .await
        .expect("bounded one admission");
    let two = store
        .claim_due(25_100, 1, 60_000)
        .await
        .expect("bounded two")
        .expect("bounded occurrence two");
    assert_eq!((two.occurrence, two.scheduled_for_ms), (5, 24_100));
    store
        .mark_submitted(&two, &receipt(&two, "bounded-2"), 25_102)
        .await
        .expect("bounded two admission");
    let three = store
        .claim_due(25_100, 1, 60_000)
        .await
        .expect("bounded three")
        .expect("bounded occurrence three");
    assert_eq!((three.occurrence, three.scheduled_for_ms), (6, 25_100));
    store
        .mark_submitted(&three, &receipt(&three, "bounded-3"), 25_103)
        .await
        .expect("bounded three admission");
    assert!(
        store
            .claim_due(25_100, 1, 60_000)
            .await
            .expect("bounded exhausted")
            .is_none(),
        "catch-up must stop after the registered bound"
    );
}

#[tokio::test]
async fn schedule_revision_changes_occurrence_identity_and_cannot_straddle_execution() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75106",
        AutomationSchedule::FixedInterval { interval_ms: 1_000 },
        100,
    );
    let created = store.create_task(&task).await.expect("create task");
    assert_eq!(created.schedule_revision, 1);
    let revised = store
        .revise_schedule(
            task.task_id,
            AutomationSchedule::FixedInterval { interval_ms: 2_000 },
            200,
            AutomationMissedRunPolicy::Skip,
            AutomationOverlapPolicy::Forbid,
            150,
        )
        .await
        .expect("revise schedule");
    assert_eq!(revised.schedule_revision, 2);
    let lease = store
        .claim_due(200, 1, 60_000)
        .await
        .expect("claim revised occurrence")
        .expect("revised occurrence");
    assert_eq!(lease.schedule_revision, 2);
    assert_eq!(
        lease.occurrence_id,
        format!(
            "hepta.automation.occurrence.v1:{}:2:200",
            task.task_id
        )
    );
    assert_eq!(
        store
            .revise_schedule(
                task.task_id,
                AutomationSchedule::Once,
                500,
                AutomationMissedRunPolicy::Skip,
                AutomationOverlapPolicy::Forbid,
                201,
            )
            .await,
        Err(AutomationError::Conflict),
        "a schedule revision cannot straddle a non-terminal occurrence"
    );
}
