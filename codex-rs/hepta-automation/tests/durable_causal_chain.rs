use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationMissedRunPolicy;
use codex_hepta_automation::AutomationOccurrenceState;
use codex_hepta_automation::AutomationOccurrenceTerminalState;
use codex_hepta_automation::AutomationOverlapPolicy;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_automation::AutomationTaskState;
use codex_hepta_automation::AutomationTick;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

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

#[derive(Default)]
struct SuccessQueue;

impl AutomationTurnQueue for SuccessQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!(
                    "queue:{}:{}",
                    admission.task_id, admission.occurrence
                ),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

#[derive(Default)]
struct UnknownQueue;

impl AutomationTurnQueue for UnknownQueue {
    fn enqueue(
        &self,
        _admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async { Err(AutomationError::DispatchUnknown) })
    }
}

fn draft(id: &str, schedule: AutomationSchedule, due: u64) -> AutomationTaskDraft {
    let mut draft = AutomationTaskDraft::new(THREAD_ID, "durable causal work", schedule, due, 1);
    draft.task_id = AutomationTaskId::parse(id).expect("task id");
    draft
}

#[tokio::test]
async fn queue_submission_is_not_occurrence_or_taskflow_success() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75101",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let policy = store.schedule_policy(task.task_id).await.expect("policy");
    assert_eq!(policy.overlap, AutomationOverlapPolicy::Allow);
    assert_eq!(policy.missed_run, AutomationMissedRunPolicy::Skip);

    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    assert!(matches!(
        scheduler.tick(100).await.expect("tick"),
        AutomationTick::Submitted { occurrence: 1, .. }
    ));

    // Legacy task state means no further schedule instant; it is not the
    // execution outcome. The occurrence and TaskFlow run remain non-terminal.
    assert_eq!(
        store.task(task.task_id).await.expect("task").unwrap().state,
        AutomationTaskState::Completed
    );
    let occurrence = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("occurrence")
        .expect("materialized");
    assert_eq!(occurrence.state, AutomationOccurrenceState::Admitted);
    assert!(occurrence.terminal_at_ms.is_none());
    let run = store
        .taskflow_run(&occurrence.taskflow_run_id)
        .await
        .expect("run")
        .expect("taskflow run");
    assert_eq!(run.state, TaskFlowRunState::Indeterminate);

    let terminal = Sha256Digest::for_bytes(b"observed terminal success");
    assert!(matches!(
        store
            .complete_occurrence(
                task.task_id,
                1,
                AutomationOccurrenceTerminalState::Succeeded,
                &terminal,
                190,
            )
            .await,
        Err(AutomationError::Conflict)
    ));

    let work = store
        .pending_occurrence_work(1)
        .await
        .expect("work")
        .pop()
        .expect("pending occurrence");
    store
        .reconcile_occurrence_taskflow_terminal(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            200,
        )
        .await
        .expect("taskflow terminal");
    let occurrence = store
        .complete_occurrence(
            task.task_id,
            1,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            200,
        )
        .await
        .expect("occurrence terminal");
    assert_eq!(occurrence.state, AutomationOccurrenceState::Succeeded);
    assert_eq!(occurrence.terminal_at_ms, Some(200));
}

#[tokio::test]
async fn allow_overlap_advances_recurrence_without_terminalizing_prior_occurrence() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75104",
        AutomationSchedule::FixedInterval { interval_ms: 1_000 },
        100,
    );
    store.create_task(&task).await.expect("create task");
    let policy = store.schedule_policy(task.task_id).await.expect("policy");
    assert_eq!(policy.overlap, AutomationOverlapPolicy::Allow);

    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    assert!(matches!(
        scheduler.tick(100).await.expect("first tick"),
        AutomationTick::Submitted { occurrence: 1, .. }
    ));
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("task")
            .unwrap()
            .next_run_at_ms,
        Some(1_100),
        "allow overlap advances only the schedule frontier after durable admission"
    );

    let first = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("first occurrence")
        .expect("first materialized");
    assert_eq!(first.state, AutomationOccurrenceState::Admitted);
    assert!(first.terminal_at_ms.is_none());

    assert!(matches!(
        scheduler.tick(1_100).await.expect("second tick"),
        AutomationTick::Submitted { occurrence: 2, .. }
    ));
    let first_after = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("first occurrence after overlap")
        .expect("first remains materialized");
    let second = store
        .automation_occurrence(task.task_id, 2)
        .await
        .expect("second occurrence")
        .expect("second materialized");
    assert_eq!(first_after.state, AutomationOccurrenceState::Admitted);
    assert!(first_after.terminal_at_ms.is_none());
    assert_eq!(second.state, AutomationOccurrenceState::Admitted);
    assert_ne!(first_after.occurrence_id, second.occurrence_id);
}

#[tokio::test]
async fn forbid_overlap_parks_recurrence_until_terminal_observation() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75102",
        AutomationSchedule::FixedInterval { interval_ms: 1_000 },
        100,
    );
    store.create_task(&task).await.expect("create task");
    let policy = store
        .set_schedule_policy(
            task.task_id,
            1,
            AutomationMissedRunPolicy::Skip,
            AutomationOverlapPolicy::Forbid,
            2,
        )
        .await
        .expect("set policy");
    assert_eq!(policy.revision, 2);

    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    scheduler.tick(100).await.expect("tick");
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("task")
            .unwrap()
            .next_run_at_ms,
        None,
        "forbidden overlap must park the timer after queue admission"
    );

    let work = store
        .pending_occurrence_work(1)
        .await
        .expect("work")
        .pop()
        .expect("pending occurrence");
    assert_eq!(work.occurrence.schedule_revision, 2);
    let receipt = Sha256Digest::for_bytes(b"terminal before next interval");
    store
        .reconcile_occurrence_taskflow_terminal(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &receipt,
            500,
        )
        .await
        .expect("taskflow terminal");
    store
        .complete_occurrence(
            task.task_id,
            1,
            AutomationOccurrenceTerminalState::Succeeded,
            &receipt,
            500,
        )
        .await
        .expect("occurrence terminal");
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("task")
            .unwrap()
            .next_run_at_ms,
        Some(1_100)
    );
}

#[tokio::test]
async fn proven_absent_unknown_dispatch_reuses_same_occurrence_identity() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75103",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(UnknownQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    assert_eq!(
        scheduler.tick(100).await.expect("unknown tick"),
        AutomationTick::DispatchUncertain {
            task_id: task.task_id,
            occurrence: 1,
        }
    );
    let first = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("occurrence")
        .expect("materialized");
    assert_eq!(first.state, AutomationOccurrenceState::Claimed);
    let uncertain = store
        .uncertain_dispatches(1)
        .await
        .expect("uncertain")
        .pop()
        .expect("uncertain row");

    // Only an external ReconcileOnly `Missing` proof may open this retry path.
    let run_before_absence = store
        .taskflow_run(&first.taskflow_run_id)
        .await
        .expect("run before absence")
        .expect("running TaskFlow");
    let old_fence = TaskFlowFence::new(
        run_before_absence.owner_agent_id.clone(),
        run_before_absence.owner_id.clone().expect("owner id"),
        run_before_absence.owner_epoch.expect("owner epoch"),
        run_before_absence.generation.expect("generation"),
        run_before_absence.fencing_token.clone().expect("fencing token"),
    )
    .expect("historical fence");
    let proof_digest = Sha256Digest::for_bytes(b"provider proved stable id absent");
    store
        .reconcile_uncertain_occurrence_absent(
            task.task_id,
            1,
            &uncertain.client_user_message_id,
            &proof_digest,
            101,
        )
        .await
        .expect("release after absence proof");
    let old_step = store
        .read_taskflow_step(
            &first.taskflow_run_id,
            "codex_turn",
            first.step_attempt,
            &old_fence,
        )
        .await
        .expect("read old step")
        .expect("old step evidence");
    assert_eq!(old_step.state, TaskFlowStepState::Reconciled);
    assert_eq!(
        old_step.final_outcome,
        Some(TaskFlowReconcileOutcome::Cancelled)
    );
    assert_eq!(old_step.receipt_digest.as_ref(), Some(&proof_digest));

    // Exercise the real second scheduler pass, not merely rematerialization.
    // Reusing the same Agent generation proves TaskFlow's attempt-generation
    // fence advances independently from the Agent spawn generation.
    let retry_scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("retry scheduler");
    assert!(matches!(
        retry_scheduler.tick(102).await.expect("retry tick"),
        AutomationTick::Submitted {
            task_id,
            occurrence: 1,
            ..
        } if task_id == task.task_id
    ));
    let second = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("occurrence")
        .expect("same occurrence after retry");
    assert_eq!(second.occurrence_id, first.occurrence_id);
    assert_eq!(second.schedule_revision, first.schedule_revision);
    assert_eq!(
        second.client_user_message_id,
        uncertain.client_user_message_id
    );
    assert_eq!(second.claim_generation, 1);
    assert_eq!(second.step_attempt, 2);
    assert_eq!(second.state, AutomationOccurrenceState::Admitted);
}

#[tokio::test]
async fn retired_schedule_with_proven_absence_terminalizes_taskflow_and_occurrence() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75105",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(UnknownQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    assert!(matches!(
        scheduler.tick(100).await.expect("unknown tick"),
        AutomationTick::DispatchUncertain { occurrence: 1, .. }
    ));
    store
        .set_enabled(task.task_id, false, None, 101)
        .await
        .expect("disable while outcome is unknown");
    let uncertain = store
        .uncertain_dispatches(1)
        .await
        .expect("uncertain")
        .pop()
        .expect("uncertain row");
    let proof = Sha256Digest::for_bytes(b"retired schedule provider absence");
    store
        .reconcile_uncertain_occurrence_absent(
            task.task_id,
            1,
            &uncertain.client_user_message_id,
            &proof,
            102,
        )
        .await
        .expect("terminalize retired absence");

    let occurrence = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("occurrence")
        .expect("materialized");
    assert_eq!(occurrence.state, AutomationOccurrenceState::Cancelled);
    assert_eq!(occurrence.terminal_receipt_digest.as_ref(), Some(&proof));
    let run = store
        .taskflow_run(&occurrence.taskflow_run_id)
        .await
        .expect("run")
        .expect("taskflow run");
    assert_eq!(run.state, TaskFlowRunState::Cancelled);
    assert!(
        store
            .uncertain_dispatches(1)
            .await
            .expect("uncertain scan")
            .is_empty()
    );
    assert_eq!(
        store.task(task.task_id).await.expect("task").unwrap().state,
        AutomationTaskState::Disabled
    );
}

#[tokio::test]
async fn stale_generation_between_taskflow_intent_and_uncertainty_recovers_same_occurrence() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75106",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let lease = store
        .claim_due(100, 1, 30_000)
        .await
        .expect("claim")
        .expect("lease");
    let occurrence = store
        .materialize_occurrence(&lease, 100)
        .await
        .expect("materialize");
    store
        .prepare_occurrence_taskflow(&occurrence, &lease, 100, 30_000)
        .await
        .expect("persist TaskFlow intent");
    // Simulate process loss before record_dispatch_uncertain().
    assert_eq!(
        store
            .recover_stale_generation(2, 101)
            .await
            .expect("causal stale recovery"),
        1
    );

    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        2,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("replacement scheduler");
    assert!(matches!(
        scheduler.tick(102).await.expect("replacement tick"),
        AutomationTick::Submitted { occurrence: 1, .. }
    ));
    let recovered = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("occurrence")
        .expect("same occurrence");
    assert_eq!(recovered.occurrence_id, occurrence.occurrence_id);
    assert_eq!(
        recovered.client_user_message_id,
        occurrence.client_user_message_id
    );
    assert_eq!(recovered.step_attempt, 2);
    assert_eq!(recovered.claim_generation, 2);
    assert_eq!(recovered.state, AutomationOccurrenceState::Admitted);
}

#[tokio::test]
async fn retired_stale_generation_before_uncertainty_closes_without_provider_contact() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75107",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let lease = store
        .claim_due(100, 1, 30_000)
        .await
        .expect("claim")
        .expect("lease");
    let occurrence = store
        .materialize_occurrence(&lease, 100)
        .await
        .expect("materialize");
    store
        .prepare_occurrence_taskflow(&occurrence, &lease, 100, 30_000)
        .await
        .expect("persist TaskFlow intent");
    store
        .set_enabled(task.task_id, false, None, 101)
        .await
        .expect("retire schedule");
    assert_eq!(
        store
            .recover_stale_generation(2, 102)
            .await
            .expect("retired stale recovery"),
        1
    );
    let terminal = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("occurrence")
        .expect("terminal occurrence");
    assert_eq!(terminal.state, AutomationOccurrenceState::Cancelled);
    assert!(terminal.terminal_receipt_digest.is_some());
    assert_eq!(
        store
            .taskflow_run(&terminal.taskflow_run_id)
            .await
            .expect("run")
            .expect("taskflow")
            .state,
        TaskFlowRunState::Cancelled
    );
}
