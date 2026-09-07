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
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_automation::AutomationTaskState;
use codex_hepta_automation::AutomationTick;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use tokio::sync::Mutex;
use tokio::sync::Notify;

const AGENT_IDS: [&str; 5] = [
    "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
    "019153a4-3088-7e03-a56a-9b1964f75dd3",
    "019153a4-3088-7e03-a56a-9b1964f75dd4",
    "019153a4-3088-7e03-a56a-9b1964f75dd5",
    "019153a4-3088-7e03-a56a-9b1964f75dd6",
];
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

struct FleetFixture {
    _temp: tempfile::TempDir,
    layouts: Vec<HeptaAgentLayout>,
}

impl FleetFixture {
    #[allow(
        clippy::expect_used,
        reason = "test fixture construction must fail loudly"
    )]
    fn new(count: usize) -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let mut layouts = Vec::new();
        for (index, raw_agent_id) in AGENT_IDS.iter().take(count).enumerate() {
            let workspace = root.join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace).expect("workspace");
            let workspace = workspace.canonicalize().expect("canonical workspace");
            let agent_id = AgentId::parse(*raw_agent_id).expect("agent id");
            let manifest = AgentManifest::new(
                agent_id,
                WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest");
            layouts.push(registry.register(manifest).expect("register agent").layout);
        }
        Self {
            _temp: temp,
            layouts,
        }
    }
}

#[derive(Default)]
struct RecordingQueue {
    admissions: Mutex<Vec<AutomationAdmission>>,
    entered: Notify,
    release: Option<Arc<Notify>>,
}

impl RecordingQueue {
    fn blocked(release: Arc<Notify>) -> Self {
        Self {
            admissions: Mutex::new(Vec::new()),
            entered: Notify::new(),
            release: Some(release),
        }
    }

    async fn admissions(&self) -> Vec<AutomationAdmission> {
        self.admissions.lock().await.clone()
    }
}

impl AutomationTurnQueue for RecordingQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.entered.notify_one();
            if let Some(release) = &self.release {
                release.notified().await;
            }
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

struct FencedQueue;

impl AutomationTurnQueue for FencedQueue {
    fn enqueue(
        &self,
        _admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async { Err(AutomationError::AccessDenied) })
    }
}

struct DispatchRejectQueue;

impl AutomationTurnQueue for DispatchRejectQueue {
    fn enqueue(
        &self,
        _admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async { Err(AutomationError::Dispatch) })
    }
}

struct AcceptedThenBlockedQueue {
    admissions: Mutex<Vec<AutomationAdmission>>,
    entered: Notify,
    release: Arc<Notify>,
}

impl AcceptedThenBlockedQueue {
    fn new(release: Arc<Notify>) -> Self {
        Self {
            admissions: Mutex::new(Vec::new()),
            entered: Notify::new(),
            release,
        }
    }

    async fn admissions(&self) -> Vec<AutomationAdmission> {
        self.admissions.lock().await.clone()
    }
}

impl AutomationTurnQueue for AcceptedThenBlockedQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            // The external queue has durably accepted the request before the
            // local scheduler receives a terminal receipt.  Holding the
            // response open gives the test a deterministic crash boundary.
            self.admissions.lock().await.push(admission.clone());
            self.entered.notify_one();
            self.release.notified().await;
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!(
                    "accepted-{}-{}",
                    admission.task_id, admission.occurrence
                ),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

#[derive(Default)]
struct UnknownQueue {
    admissions: Mutex<Vec<AutomationAdmission>>,
}

impl UnknownQueue {
    async fn admissions(&self) -> Vec<AutomationAdmission> {
        self.admissions.lock().await.clone()
    }
}

impl AutomationTurnQueue for UnknownQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.admissions.lock().await.push(admission);
            Err(AutomationError::DispatchUnknown)
        })
    }
}

struct RetryOnceQueue {
    admissions: Mutex<Vec<AutomationAdmission>>,
    attempts: Mutex<u8>,
}

impl RetryOnceQueue {
    async fn admissions(&self) -> Vec<AutomationAdmission> {
        self.admissions.lock().await.clone()
    }
}

impl Default for RetryOnceQueue {
    fn default() -> Self {
        Self {
            admissions: Mutex::new(Vec::new()),
            attempts: Mutex::new(0),
        }
    }
}

impl AutomationTurnQueue for RetryOnceQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.admissions.lock().await.push(admission.clone());
            let mut attempts = self.attempts.lock().await;
            if *attempts == 0 {
                *attempts = 1;
                return Err(AutomationError::Dispatch);
            }
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

#[allow(
    clippy::expect_used,
    reason = "test task identifiers are fixed valid fixtures"
)]
fn draft(id: &str, schedule: AutomationSchedule, due: u64) -> AutomationTaskDraft {
    let mut draft = AutomationTaskDraft::new(THREAD_ID, "perform durable work", schedule, due, 1);
    draft.task_id = AutomationTaskId::parse(id).expect("task id");
    draft
}

#[tokio::test]
async fn one_shot_periodic_disable_and_cancel_are_durable() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let queue = Arc::new(RecordingQueue::default());
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        7,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");

    let one = draft(
        "019153a4-3088-7000-a56a-9b1964f75001",
        AutomationSchedule::Once,
        10,
    );
    store.create_task(&one).await.expect("one-shot");
    assert!(matches!(
        scheduler.tick(10).await.expect("one-shot tick"),
        AutomationTick::Submitted { occurrence: 1, .. }
    ));
    assert_eq!(
        store.task(one.task_id).await.expect("read").unwrap().state,
        AutomationTaskState::Completed
    );

    let periodic = draft(
        "019153a4-3088-7000-a56a-9b1964f75002",
        AutomationSchedule::FixedInterval { interval_ms: 5_000 },
        20,
    );
    store.create_task(&periodic).await.expect("periodic");
    scheduler.tick(20).await.expect("periodic tick");
    assert_eq!(
        store
            .task(periodic.task_id)
            .await
            .expect("read")
            .unwrap()
            .next_run_at_ms,
        Some(5_020)
    );
    store
        .set_enabled(periodic.task_id, false, None, 21)
        .await
        .expect("disable");
    assert_eq!(
        scheduler.tick(9_000).await.expect("disabled tick"),
        AutomationTick::Idle
    );
    store
        .set_enabled(periodic.task_id, true, Some(10_000), 22)
        .await
        .expect("enable");
    scheduler.tick(10_000).await.expect("resumed tick");
    store
        .cancel_task(periodic.task_id, 23)
        .await
        .expect("cancel");
    assert_eq!(
        store
            .task(periodic.task_id)
            .await
            .expect("read")
            .unwrap()
            .state,
        AutomationTaskState::Cancelled
    );
    assert_eq!(queue.admissions().await.len(), 3);
}

#[tokio::test]
async fn owner_or_generation_fence_is_not_downgraded_to_a_dispatch_retry() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75009",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let scheduler = AutomationScheduler::new(
        store,
        Arc::new(FencedQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");

    assert_eq!(
        scheduler.tick(100).await,
        Err(AutomationError::AccessDenied)
    );
}

#[tokio::test]
async fn pre_admission_dispatch_error_clears_intent_and_allows_next_generation_retry() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75010",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(DispatchRejectQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");

    assert_eq!(
        scheduler.tick(100).await.expect("pre-admission rejection"),
        AutomationTick::RetryScheduled {
            task_id: task.task_id,
            occurrence: 1,
        }
    );
    assert!(
        store
            .uncertain_dispatches(10)
            .await
            .expect("uncertain list")
            .is_empty()
    );

    let restarted = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("reopen store");
    assert_eq!(
        restarted
            .recover_stale_generation(2)
            .await
            .expect("recover generation"),
        0,
        "pre-admission cleanup leaves no stale lease to recover"
    );
    let lease = restarted
        .claim_due(101, 2, 60_000)
        .await
        .expect("claim retry")
        .expect("retry remains due");
    restarted
        .mark_submitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: "retry-after-abort".to_string(),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            102,
        )
        .await
        .expect("complete retry");
}

#[tokio::test]
async fn successful_dispatch_upgrades_pre_admission_intent_atomically() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75011",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let queue = Arc::new(RecordingQueue::default());
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");

    assert!(matches!(
        scheduler.tick(100).await.expect("successful dispatch"),
        AutomationTick::Submitted {
            task_id,
            occurrence: 1,
            ..
        } if task_id == task.task_id
    ));
    assert!(
        store
            .uncertain_dispatches(10)
            .await
            .expect("uncertain list")
            .is_empty()
    );
    assert_eq!(queue.admissions().await.len(), 1);
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("read task")
            .expect("task exists")
            .state,
        AutomationTaskState::Completed
    );
}

#[tokio::test]
async fn crash_after_external_acceptance_keeps_unknown_intent_across_reopen() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75012",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let release = Arc::new(Notify::new());
    let queue = Arc::new(AcceptedThenBlockedQueue::new(Arc::clone(&release)));
    let scheduler = Arc::new(
        AutomationScheduler::new(
            store.clone(),
            Arc::clone(&queue),
            1,
            Duration::from_secs(30),
            Duration::from_secs(10),
        )
        .expect("scheduler"),
    );
    let tick = {
        let scheduler = Arc::clone(&scheduler);
        tokio::spawn(async move { scheduler.tick(100).await })
    };
    queue.entered.notified().await;
    assert_eq!(queue.admissions().await.len(), 1);

    // Simulate process death after the external queue accepted the request but
    // before the local scheduler received its terminal receipt.
    tick.abort();
    let _ = tick.await;
    drop(scheduler);
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("reopen store");
    assert_eq!(
        reopened
            .recover_stale_generation(2)
            .await
            .expect("recover generation"),
        0,
        "durable pre-admission intent must not be reclaimed as a blind retry"
    );
    assert!(
        reopened
            .claim_due(100_000, 2, 60_000)
            .await
            .expect("claim after crash")
            .is_none(),
        "lost response remains quarantined until explicit reconciliation"
    );
    let uncertain = reopened
        .uncertain_dispatches(10)
        .await
        .expect("uncertain list after crash");
    assert_eq!(uncertain.len(), 1);
    assert_eq!(uncertain[0].task_id, task.task_id);
    assert_eq!(
        uncertain[0].client_user_message_id,
        queue.admissions().await[0].client_user_message_id
    );
}

#[tokio::test]
async fn in_flight_unknown_intent_fences_stale_generation_and_second_claim() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75013",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let release = Arc::new(Notify::new());
    let queue = Arc::new(AcceptedThenBlockedQueue::new(Arc::clone(&release)));
    let scheduler = Arc::new(
        AutomationScheduler::new(
            store.clone(),
            Arc::clone(&queue),
            1,
            Duration::from_secs(1),
            Duration::from_millis(500),
        )
        .expect("scheduler"),
    );
    let tick = {
        let scheduler = Arc::clone(&scheduler);
        tokio::spawn(async move { scheduler.tick(100).await })
    };
    queue.entered.notified().await;

    assert_eq!(
        store
            .recover_stale_generation(2)
            .await
            .expect("recover while request is in flight"),
        0,
        "unknown in-flight intent must not be reset by generation recovery"
    );
    assert!(
        store
            .claim_due(2_000, 2, 60_000)
            .await
            .expect("second generation claim")
            .is_none(),
        "a second generation cannot submit while the first admission is unknown"
    );

    release.notify_waiters();
    assert!(matches!(
        tick.await.expect("join scheduler").expect("dispatch"),
        AutomationTick::Submitted { .. }
    ));
    assert!(
        store
            .uncertain_dispatches(10)
            .await
            .expect("uncertain list after receipt")
            .is_empty()
    );
    assert_eq!(queue.admissions().await.len(), 1);
}

#[tokio::test]
async fn unknown_provider_outcome_is_quarantined_across_store_recovery_until_reconciled() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f7500a",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let queue = Arc::new(UnknownQueue::default());
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
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
    assert_eq!(queue.admissions().await.len(), 1);
    let uncertain = store
        .uncertain_dispatches(10)
        .await
        .expect("uncertain list");
    assert_eq!(uncertain.len(), 1);
    assert_eq!(uncertain[0].task_id, task.task_id);
    assert_eq!(
        uncertain[0].client_user_message_id,
        queue.admissions().await[0].client_user_message_id
    );

    drop(scheduler);
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("reopen store");
    assert_eq!(
        reopened
            .recover_stale_generation(2)
            .await
            .expect("recover generation"),
        0,
        "unknown provider outcome must not be silently retried on restart"
    );
    assert!(
        reopened
            .claim_due(100_000, 2, 60_000)
            .await
            .expect("claim after recovery")
            .is_none(),
        "quarantined occurrence must remain blocked until reconciliation"
    );

    let receipt = AutomationQueueReceipt {
        queued_submission_id: "provider-receipt-unknown-recovered".to_string(),
        client_user_message_id: uncertain[0].client_user_message_id.clone(),
    };
    let completed = reopened
        .reconcile_dispatch(task.task_id, 1, &receipt, 200)
        .await
        .expect("reconcile provider receipt");
    assert_eq!(completed.state, AutomationTaskState::Completed);
    assert!(
        reopened
            .uncertain_dispatches(10)
            .await
            .expect("uncertain list after reconcile")
            .is_empty()
    );
    assert_eq!(queue.admissions().await.len(), 1);
}

#[tokio::test]
async fn stale_generation_recovery_is_owner_fenced() {
    let fixture = FleetFixture::new(1);
    let layout = &fixture.layouts[0];
    let store = AutomationStore::open(layout).await.expect("open store");
    let owner_task = draft(
        "019153a4-3088-7000-a56a-9b1964f75014",
        AutomationSchedule::Once,
        100,
    );
    store
        .create_task(&owner_task)
        .await
        .expect("create owner task");
    store
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim owner task")
        .expect("owner task is due");

    // A malformed/imported row can appear after the opener's one-time store
    // verification. Recovery must still fence mutations by task ownership;
    // generation alone is not an Agent identity proof.
    let foreign_task_id = "019153a4-3088-7000-a56a-9b1964f75015";
    let database_path = store.path().to_path_buf();
    let sqlite_home = AbsolutePathBuf::from_absolute_path(layout.automation_root())
        .expect("absolute sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await
        .expect("open inspection pool");
    sqlx::query(
        "INSERT INTO automation_tasks (
             task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
             state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
         ) VALUES (?, ?, ?, ?, 'once', NULL, 'enabled', ?, 1, ?, ?)",
    )
    .bind(foreign_task_id)
    .bind(AGENT_IDS[1])
    .bind(THREAD_ID)
    .bind("foreign task")
    .bind(100_i64)
    .bind(0_i64)
    .bind(100_i64)
    .execute(&pool)
    .await
    .expect("insert foreign task");
    sqlx::query(
        "INSERT INTO automation_runs (
             task_id, occurrence, scheduled_for_ms, client_user_message_id, state,
             lease_generation, lease_token, lease_expires_at_ms
         ) VALUES (?, 1, ?, ?, 'leased', ?, ?, ?)",
    )
    .bind(foreign_task_id)
    .bind(100_i64)
    .bind("foreign-client-message")
    .bind(1_i64)
    .bind("foreign-lease")
    .bind(160_i64)
    .execute(&pool)
    .await
    .expect("insert foreign lease");
    pool.close().await;

    assert_eq!(
        store
            .recover_stale_generation(2)
            .await
            .expect("recover stale generation"),
        1,
        "only the current Agent's stale lease is recoverable"
    );

    let sqlite_home = AbsolutePathBuf::from_absolute_path(layout.automation_root())
        .expect("absolute sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await
        .expect("reopen inspection pool");
    let (state, generation): (String, Option<i64>) = sqlx::query_as(
        "SELECT state, lease_generation FROM automation_runs
         WHERE task_id = ? AND occurrence = 1",
    )
    .bind(foreign_task_id)
    .fetch_one(&pool)
    .await
    .expect("read foreign lease");
    assert_eq!(state, "leased");
    assert_eq!(generation, Some(1));
    pool.close().await;
}

#[tokio::test]
async fn uncertain_dispatch_requires_explicit_negative_provider_proof_before_retry() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f7500f",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let queue = Arc::new(UnknownQueue::default());
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    assert!(matches!(
        scheduler.tick(100).await.expect("unknown tick"),
        AutomationTick::DispatchUncertain { .. }
    ));
    let uncertain = store
        .uncertain_dispatches(1)
        .await
        .expect("uncertain list")
        .pop()
        .expect("uncertain occurrence");
    assert_eq!(
        store
            .release_uncertain_for_retry(task.task_id, 1, "wrong-client-id")
            .await,
        Err(AutomationError::Conflict),
        "a retry cannot be released without the exact fenced client id"
    );
    assert!(
        store
            .claim_due(100_000, 2, 60_000)
            .await
            .expect("claim while uncertain")
            .is_none()
    );
    store
        .release_uncertain_for_retry(task.task_id, 1, &uncertain.client_user_message_id)
        .await
        .expect("explicit negative provider proof");
    let lease = store
        .claim_due(100_000, 2, 60_000)
        .await
        .expect("claim after explicit release")
        .expect("released occurrence due");
    assert_eq!(lease.occurrence, 1);
    assert_eq!(
        lease.client_user_message_id,
        uncertain.client_user_message_id
    );
    store
        .mark_submitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: "negative-proof-retry-receipt".to_string(),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            101,
        )
        .await
        .expect("retry submission");
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("read completed task")
            .expect("task exists")
            .state,
        AutomationTaskState::Completed
    );
}

#[tokio::test]
async fn v1_store_migrates_atomically_to_dispatch_outcome_schema() {
    let fixture = FleetFixture::new(1);
    let layout = &fixture.layouts[0];
    let store = AutomationStore::open(layout).await.expect("open v2 store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f7500e",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create legacy task");
    let database_path = store.path().to_path_buf();
    store.close().await;

    // Reduce the fresh database to the observable v1 shape while retaining
    // SQLx's v1 migration row.  Reopening must execute the real 0002 migration,
    // not a test-only schema shortcut.
    let sqlite_home = AbsolutePathBuf::from_absolute_path(layout.automation_root())
        .expect("absolute sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await
        .expect("open legacy pool");
    // Keep the schema rewind on one connection so each DDL statement sees
    // the preceding change, and publish the complete v1 fixture atomically.
    let mut rewind = pool.begin().await.expect("begin legacy schema rewind");
    sqlx::query("DROP INDEX automation_dispatch_outcome_state_idx")
        .execute(&mut *rewind)
        .await
        .expect("drop v2 index");
    sqlx::query("DROP TABLE automation_dispatch_outcomes")
        .execute(&mut *rewind)
        .await
        .expect("drop v2 table");
    // The current opener also applies the qualification-only TaskFlow
    // migration. Remove that schema and rewind its migration ledger so this
    // test still exercises a genuine v1 -> latest upgrade path.
    sqlx::query("DROP TRIGGER taskflow_events_no_update")
        .execute(&mut *rewind)
        .await
        .expect("drop TaskFlow event update trigger");
    sqlx::query("DROP TRIGGER taskflow_events_no_delete")
        .execute(&mut *rewind)
        .await
        .expect("drop TaskFlow event delete trigger");
    sqlx::query("DROP TRIGGER taskflow_definitions_no_update")
        .execute(&mut *rewind)
        .await
        .expect("drop TaskFlow definition update trigger");
    sqlx::query("DROP TRIGGER taskflow_definitions_no_delete")
        .execute(&mut *rewind)
        .await
        .expect("drop TaskFlow definition delete trigger");
    sqlx::query("DROP TABLE taskflow_events")
        .execute(&mut *rewind)
        .await
        .expect("drop TaskFlow events");
    sqlx::query("DROP TABLE taskflow_runs")
        .execute(&mut *rewind)
        .await
        .expect("drop TaskFlow runs");
    sqlx::query("DROP TABLE taskflow_definitions")
        .execute(&mut *rewind)
        .await
        .expect("drop TaskFlow definitions");
    sqlx::query("DELETE FROM _sqlx_migrations WHERE version >= 2")
        .execute(&mut *rewind)
        .await
        .expect("rewind migration ledger");
    sqlx::query("DROP TRIGGER automation_meta_no_update")
        .execute(&mut *rewind)
        .await
        .expect("drop immutable trigger for rewind");
    sqlx::query("UPDATE automation_meta SET schema_version = 1 WHERE singleton = 1")
        .execute(&mut *rewind)
        .await
        .expect("rewind metadata version");
    sqlx::query(
        "CREATE TRIGGER automation_meta_no_update
         BEFORE UPDATE ON automation_meta
         BEGIN
             SELECT RAISE(ABORT, 'automation owner metadata is immutable');
         END",
    )
    .execute(&mut *rewind)
    .await
    .expect("restore immutable trigger");
    rewind.commit().await.expect("commit legacy schema rewind");
    pool.close().await;

    let migrated = AutomationStore::open(layout)
        .await
        .expect("v1 to v2 migration");
    let migrated_task = migrated
        .task(task.task_id)
        .await
        .expect("read migrated task")
        .expect("migrated task exists");
    assert_eq!(migrated_task.task_id, task.task_id);
    assert_eq!(migrated_task.thread_id, task.thread_id);
    assert_eq!(migrated_task.prompt, task.prompt);
    assert_eq!(migrated_task.schedule, task.schedule);
    assert_eq!(migrated_task.state, AutomationTaskState::Enabled);
    let lease = migrated
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim migrated task")
        .expect("migrated task due");
    migrated
        .mark_submitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: "migration-receipt".to_string(),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            101,
        )
        .await
        .expect("write migrated outcome");
    migrated.close().await;

    let sqlite_home = AbsolutePathBuf::from_absolute_path(layout.automation_root())
        .expect("absolute sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await
        .expect("inspect migrated pool");
    let schema: i64 =
        sqlx::query_scalar("SELECT schema_version FROM automation_meta WHERE singleton = 1")
            .fetch_one(&pool)
            .await
            .expect("read migrated schema version");
    assert_eq!(schema, 3);
    let outcomes: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM automation_dispatch_outcomes WHERE task_id = ?")
            .bind(task.task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("read migrated outcome");
    assert_eq!(outcomes, 1);
    assert!(
        sqlx::query("UPDATE automation_meta SET schema_version = 99 WHERE singleton = 1")
            .execute(&pool)
            .await
            .is_err(),
        "migration must restore the immutable metadata trigger"
    );
    pool.close().await;
}

#[tokio::test]
async fn explicit_dispatch_failure_retries_same_occurrence_and_client_id() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f7500b",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("create task");
    let queue = Arc::new(RetryOnceQueue::default());
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");

    assert_eq!(
        scheduler.tick(100).await.expect("first retry tick"),
        AutomationTick::RetryScheduled {
            task_id: task.task_id,
            occurrence: 1,
        }
    );
    assert!(matches!(
        scheduler.tick(100).await.expect("second retry tick"),
        AutomationTick::Submitted {
            task_id,
            occurrence: 1,
            ..
        } if task_id == task.task_id
    ));
    let admissions = queue.admissions().await;
    assert_eq!(admissions.len(), 2);
    assert_eq!(admissions[0].occurrence, admissions[1].occurrence);
    assert_eq!(
        admissions[0].client_user_message_id,
        admissions[1].client_user_message_id
    );
    assert_eq!(
        store
            .task(task.task_id)
            .await
            .expect("read task")
            .unwrap()
            .state,
        AutomationTaskState::Completed
    );
}

#[tokio::test]
async fn duplicate_provider_receipt_is_rejected_by_local_outcome_fence() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let first = draft(
        "019153a4-3088-7000-a56a-9b1964f7500c",
        AutomationSchedule::Once,
        100,
    );
    let second = draft(
        "019153a4-3088-7000-a56a-9b1964f7500d",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&first).await.expect("first task");
    store.create_task(&second).await.expect("second task");
    let first_lease = store
        .claim_due(100, 1, 60_000)
        .await
        .expect("first claim")
        .expect("first lease");
    let second_lease = store
        .claim_due(100, 1, 60_000)
        .await
        .expect("second claim")
        .expect("second lease");
    let receipt = |lease: &codex_hepta_automation::AutomationLease| AutomationQueueReceipt {
        queued_submission_id: "provider-receipt-shared".to_string(),
        client_user_message_id: lease.client_user_message_id.clone(),
    };
    store
        .mark_submitted(&first_lease, &receipt(&first_lease), 101)
        .await
        .expect("first receipt");
    assert_eq!(
        store
            .mark_submitted(&second_lease, &receipt(&second_lease), 102)
            .await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(
        store
            .task(second.task_id)
            .await
            .expect("second read")
            .unwrap()
            .state,
        AutomationTaskState::Enabled
    );
}

#[tokio::test]
async fn restart_reclaims_same_occurrence_with_same_core_client_id_and_fences_old_lease() {
    let fixture = FleetFixture::new(5);
    let first = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("first open");
    let mut peers = Vec::new();
    for (index, layout) in fixture.layouts.iter().enumerate().skip(1) {
        let store = AutomationStore::open(layout).await.expect("open peer");
        let task_id = format!("019153a4-3088-71{index:02x}-a56a-9b1964f76{index:03x}");
        store
            .create_task(&draft(
                &task_id,
                AutomationSchedule::Once,
                1_000 + u64::try_from(index).expect("peer index"),
            ))
            .await
            .expect("create peer task");
        peers.push(store);
    }
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75003",
        AutomationSchedule::Once,
        100,
    );
    first.create_task(&task).await.expect("create task");
    let old = first
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim")
        .expect("due lease");
    drop(first);

    let restarted = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("reopen");
    assert_eq!(
        restarted
            .recover_stale_generation(2)
            .await
            .expect("recover"),
        1
    );
    let new = restarted
        .claim_due(101, 2, 60_000)
        .await
        .expect("reclaim")
        .expect("recovered lease");
    assert_eq!(new.occurrence, old.occurrence);
    assert_eq!(new.client_user_message_id, old.client_user_message_id);
    assert_ne!(new.lease_token, old.lease_token);
    assert!(matches!(
        restarted.release_for_retry(&old).await,
        Err(AutomationError::Conflict)
    ));
    for peer in peers {
        let tasks = peer.list_tasks(1).await.expect("peer remains available");
        assert_eq!(tasks.len(), 1);
        assert_eq!(tasks[0].owner_agent_id, *peer.owner_agent_id());
        assert_eq!(tasks[0].state, AutomationTaskState::Enabled);
    }
}

#[tokio::test]
async fn disabling_an_inflight_lease_never_resurrects_the_task() {
    let fixture = FleetFixture::new(1);
    let store = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("open store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75004",
        AutomationSchedule::FixedInterval { interval_ms: 5_000 },
        100,
    );
    store.create_task(&task).await.expect("create task");
    let lease = store
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim")
        .expect("due lease");

    let disabled = store
        .set_enabled(task.task_id, false, None, 101)
        .await
        .expect("disable in-flight task");
    assert_eq!(disabled.state, AutomationTaskState::Disabled);
    assert!(matches!(
        store.set_enabled(task.task_id, true, Some(200), 102).await,
        Err(AutomationError::Conflict)
    ));

    let submitted = store
        .mark_submitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: "queue-in-flight".to_string(),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            103,
        )
        .await
        .expect("finish admitted occurrence");
    assert_eq!(submitted.state, AutomationTaskState::Disabled);
    assert_eq!(submitted.next_run_at_ms, None);
    let resumed = store
        .set_enabled(task.task_id, true, Some(200), 104)
        .await
        .expect("resume after admitted occurrence finishes");
    assert_eq!(resumed.state, AutomationTaskState::Enabled);
    assert_eq!(resumed.next_run_at_ms, Some(200));
}

#[tokio::test]
async fn copied_database_cannot_cross_agent_owner_boundary() {
    let fixture = FleetFixture::new(2);
    let first = AutomationStore::open(&fixture.layouts[0])
        .await
        .expect("first store");
    first
        .create_task(&draft(
            "019153a4-3088-7000-a56a-9b1964f75005",
            AutomationSchedule::Once,
            100,
        ))
        .await
        .expect("first task");
    let first_path = first.path().to_path_buf();
    first.close().await;

    let second_path = fixture.layouts[1]
        .automation_root()
        .join("automation_1.sqlite3");
    std::fs::copy(first_path, second_path).expect("copy owner-bound database");
    assert!(matches!(
        AutomationStore::open(&fixture.layouts[1]).await,
        Err(AutomationError::AccessDenied)
    ));
}

#[tokio::test]
async fn five_real_agent_identities_are_isolated_and_one_blocked_backlog_cannot_starve_peers() {
    let fixture = FleetFixture::new(5);
    let mut stores = Vec::new();
    for (index, layout) in fixture.layouts.iter().enumerate() {
        let store = AutomationStore::open(layout).await.expect("agent store");
        let count = if index == 0 { 32 } else { 1 };
        for task_index in 0..count {
            let task_id = format!(
                "019153a4-3088-7{:03x}-a56a-9b1964f7{:04x}",
                index,
                task_index + 0x100
            );
            store
                .create_task(&draft(&task_id, AutomationSchedule::Once, 1))
                .await
                .expect("create isolated task");
        }
        stores.push(store);
    }
    let unique_paths = stores
        .iter()
        .map(|store| store.path().to_path_buf())
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(unique_paths.len(), 5);
    assert_eq!(
        stores
            .iter()
            .map(|store| store.owner_agent_id().clone())
            .collect::<std::collections::BTreeSet<_>>()
            .len(),
        5
    );

    let release_a = Arc::new(Notify::new());
    let queue_a = Arc::new(RecordingQueue::blocked(Arc::clone(&release_a)));
    let scheduler_a = Arc::new(
        AutomationScheduler::new(
            stores[0].clone(),
            Arc::clone(&queue_a),
            1,
            Duration::from_secs(30),
            Duration::from_secs(10),
        )
        .expect("A scheduler"),
    );
    let a_task = {
        let scheduler_a = Arc::clone(&scheduler_a);
        tokio::spawn(async move { scheduler_a.tick(1).await })
    };
    queue_a.entered.notified().await;

    for (index, store) in stores.iter().enumerate().skip(1) {
        let queue = Arc::new(RecordingQueue::default());
        let scheduler = AutomationScheduler::new(
            store.clone(),
            Arc::clone(&queue),
            u64::try_from(index + 1).expect("generation"),
            Duration::from_secs(30),
            Duration::from_secs(2),
        )
        .expect("peer scheduler");
        let outcome = tokio::time::timeout(Duration::from_secs(1), scheduler.tick(1))
            .await
            .expect("peer must not wait for A")
            .expect("peer tick");
        assert!(matches!(outcome, AutomationTick::Submitted { .. }));
        let admissions = queue.admissions().await;
        assert_eq!(admissions.len(), 1);
        assert_eq!(admissions[0].agent_id, *store.owner_agent_id());
    }

    assert!(!a_task.is_finished(), "A remains deliberately blocked");
    release_a.notify_waiters();
    assert!(matches!(
        a_task.await.expect("join A").expect("A tick"),
        AutomationTick::Submitted { .. }
    ));
}
