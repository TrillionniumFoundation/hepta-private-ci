//! Real SQLite owners and the same constructor/loop called by Agentd::run.
//! The controllable queue is a typed test adapter, not a provider or a second
//! App Server. These tests make no cross-schema or deployed-host performance claim.

use std::future::pending;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_agent_components::automation::AutomationAdmission;
use codex_hepta_agent_components::automation::AutomationError;
use codex_hepta_agent_components::automation::AutomationFuture;
use codex_hepta_agent_components::automation::AutomationQueueReceipt;
use codex_hepta_agent_components::automation::AutomationSchedule;
use codex_hepta_agent_components::automation::AutomationScheduler;
use codex_hepta_agent_components::automation::AutomationStore;
use codex_hepta_agent_components::automation::AutomationTaskDraft;
use codex_hepta_agent_components::automation::AutomationTurnQueue;
use codex_hepta_agent_components::automation::TimerPhase;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agent_components::types::Generation;
use tokio::sync::Notify;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::AgentdAutomationQueue;
use super::AutomationService;
use super::run_scheduler_loop;
use super::spawn_automation_service;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::RuntimeTasks;

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    identity: AgentdIdentity,
    state: Arc<AgentdState>,
    store: AutomationStore,
}

async fn fixture() -> Fixture {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp.path().canonicalize().expect("canonical root");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let record = registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(&workspace, &fleet_root).expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("starting");
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: root.join("fleet"),
        workspace,
        resources: record.manifest.resources.clone(),
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state =
        Arc::new(AgentdState::new(identity.clone(), registry.clone(), 128).expect("Agentd state"));
    let store = AutomationStore::open(&record.layout).await.expect("owner");
    state
        .attach_automation_store(store.clone())
        .expect("real attachment");
    Fixture {
        _temp: temp,
        registry,
        identity,
        state,
        store,
    }
}

fn host() -> (RuntimeTasks, CancellationToken) {
    let stop = CancellationToken::new();
    let tasks = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).expect("host");
    (tasks, stop)
}

async fn install(fixture: &Fixture, tasks: &mut RuntimeTasks, stop: &CancellationToken) {
    spawn_automation_service(
        tasks,
        Some(fixture.store.clone()),
        Arc::clone(&fixture.state),
        fixture.identity.clone(),
        Arc::new(AgentdAutomationQueue::new(
            Arc::clone(&fixture.state),
            fixture.identity.clone(),
        )),
        stop.clone(),
        Generation::new(fixture.identity.spawn_generation).expect("generation"),
    )
    .await
    .expect("production constructor");
}

fn draft() -> AutomationTaskDraft {
    AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "preserve the existing owner result",
        AutomationSchedule::FixedInterval { interval_ms: 5_000 },
        100,
        1,
    )
}

#[tokio::test]
async fn production_constructor_rejects_mismatched_identity_before_spawn() {
    let fixture = fixture().await;
    let (mut tasks, stop) = host();
    let mut wrong = fixture.identity.clone();
    wrong.spawn_generation += 1;
    assert!(
        spawn_automation_service(
            &mut tasks,
            Some(fixture.store.clone()),
            Arc::clone(&fixture.state),
            wrong,
            Arc::new(AgentdAutomationQueue::new(
                Arc::clone(&fixture.state),
                fixture.identity.clone(),
            )),
            stop.clone(),
            Generation::new(fixture.identity.spawn_generation).expect("generation"),
        )
        .await
        .is_err()
    );
    assert_eq!(tasks.active_count(), 0);
    assert!(!stop.is_cancelled());
    fixture.store.close().await;
}

#[tokio::test]
async fn production_service_retirement_drains_owner_then_unpublishes_only_automation() {
    let fixture = fixture().await;
    let (mut tasks, stop) = host();
    tasks.spawn_required("core", pending()).expect("sibling");
    install(&fixture, &mut tasks, &stop).await;
    tasks
        .retire_optional_generation(
            "automation.taskflow",
            Generation::new(1).expect("generation"),
        )
        .await
        .expect("owner-confirmed retirement");
    let status = fixture.store.timer_status().await.expect("durable status");
    assert_eq!(status.phase, TimerPhase::Draining);
    assert!(status.can_handoff());
    assert!(
        !fixture
            .state
            .automation_is_available()
            .expect("route state")
    );
    assert_eq!(tasks.active_count(), 1);
    assert!(!stop.is_cancelled());
    let successor = fixture
        .store
        .handoff_timer()
        .await
        .expect("separate handoff");
    assert!(fixture.store.create_task(&draft()).await.is_err());
    assert_eq!(
        successor
            .timer_status()
            .await
            .expect("successor")
            .writer_epoch,
        status.writer_epoch + 1
    );
    tasks.shutdown().await;
    successor.close().await;
    fixture.store.close().await;
}

#[tokio::test]
async fn process_shutdown_does_not_turn_into_durable_timer_retirement() {
    let fixture = fixture().await;
    let (mut tasks, stop) = host();
    install(&fixture, &mut tasks, &stop).await;
    tasks.shutdown().await;
    assert_eq!(
        fixture.store.timer_status().await.expect("status").phase,
        TimerPhase::Active
    );
    assert!(
        tasks
            .retire_optional_generation(
                "automation.taskflow",
                Generation::new(1).expect("generation"),
            )
            .await
            .is_err()
    );
    fixture.store.close().await;
}

#[tokio::test]
async fn unknown_owner_dispatch_prevents_retirement_and_replacement_after_reopen() {
    let fixture = fixture().await;
    fixture.store.create_task(&draft()).await.expect("task");
    let lease = fixture
        .store
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim")
        .expect("lease");
    let occurrence = fixture
        .store
        .materialize_occurrence(&lease, 100)
        .await
        .expect("durable occurrence");
    fixture
        .store
        .prepare_occurrence_taskflow(&occurrence, &lease, 100, 60_000)
        .await
        .expect("durable step claim");
    fixture
        .store
        .record_dispatch_uncertain(&lease, 101)
        .await
        .expect("durable unknown");
    let (mut tasks, stop) = host();
    tasks.spawn_required("core", pending()).expect("sibling");
    install(&fixture, &mut tasks, &stop).await;
    assert!(
        tasks
            .retire_optional_generation(
                "automation.taskflow",
                Generation::new(1).expect("generation"),
            )
            .await
            .is_err()
    );
    assert!(!stop.is_cancelled());
    assert!(
        tasks
            .spawn_optional_service_generation(
                "automation.taskflow",
                Generation::new(2).expect("successor"),
                Some(Generation::new(1).expect("predecessor")),
                |_| pending(),
                || Ok(()),
                || Ok(()),
            )
            .is_err()
    );
    tasks.shutdown().await;
    fixture.store.close().await;
    let reopened = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("reopen owner");
    let status = reopened.timer_status().await.expect("status");
    assert_eq!(status.uncertain_dispatches, 1);
    assert!(!status.can_handoff());
    assert!(reopened.handoff_timer().await.is_err());
    reopened.close().await;
}

struct DelayedQueue {
    entered: Notify,
    release: Notify,
    completed: AtomicUsize,
}

impl AutomationTurnQueue for DelayedQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.entered.notify_one();
            self.release.notified().await;
            self.completed.fetch_add(1, Ordering::SeqCst);
            Ok(AutomationQueueReceipt {
                queued_submission_id: "queue.acknowledged".to_string(),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

#[tokio::test]
async fn cancellation_preserves_in_flight_queue_ack_before_scheduler_exit() {
    let fixture = fixture().await;
    fixture
        .registry
        .compare_and_transition(&fixture.identity.agent_id, 1, AgentLifecycle::Running)
        .expect("running");
    fixture.state.refresh_generation().expect("generation");
    let cognitive = codex_hepta_agent_components::cognitive_store::DurableCognitiveStore::open(
        &fixture.identity.layout,
    )
    .await
    .expect("real cognitive owner");
    fixture
        .state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("owner attachment");
    fixture
        .state
        .mark_runtime_prerequisites_ready()
        .expect("owner prerequisites");
    fixture.state.mark_app_server_ready().expect("ready");
    fixture.store.create_task(&draft()).await.expect("task");
    let queue = Arc::new(DelayedQueue {
        entered: Notify::new(),
        release: Notify::new(),
        completed: AtomicUsize::new(0),
    });
    let scheduler = AutomationScheduler::new(
        fixture.store.clone(),
        Arc::clone(&queue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("real scheduler");
    let stop = CancellationToken::new();
    let mut task = tokio::spawn(run_scheduler_loop(
        scheduler,
        Arc::clone(&fixture.state),
        stop.clone(),
        Duration::from_millis(1),
    ));
    timeout(Duration::from_secs(2), queue.entered.notified())
        .await
        .expect("queue admission");
    stop.cancel();
    assert!(timeout(Duration::from_millis(30), &mut task).await.is_err());
    queue.release.notify_one();
    timeout(Duration::from_secs(2), task)
        .await
        .expect("bounded drain")
        .expect("task join")
        .expect("scheduler exit");
    assert_eq!(queue.completed.load(Ordering::SeqCst), 1);
    let status = fixture.store.timer_status().await.expect("owner outcome");
    assert_eq!(status.uncertain_dispatches, 0);
    assert_eq!(status.leased_occurrences, 0);
    fixture.store.close().await;
}

#[tokio::test]
async fn production_constructor_keeps_retired_timer_absent_after_reopen() {
    let fixture = fixture().await;
    let original = fixture.store.create_task(&draft()).await.expect("task");
    fixture.store.quiesce_timer().await.expect("quiesce");
    let retired = fixture.store.retire_timer().await.expect("retire");
    fixture.store.close().await;
    drop(fixture.state);

    // This is the same durable owner and the same constructor used at daemon
    // startup, not an in-memory retirement flag or a separately built scheduler.
    let reopened = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("reopen retired owner");
    let state = Arc::new(
        AgentdState::new(fixture.identity.clone(), fixture.registry.clone(), 128)
            .expect("restarted host"),
    );
    let service =
        AutomationService::open(Arc::clone(&state), crate::RuntimeModuleProfileV1::Compiled)
            .await
            .expect("readable owner factory");
    let (mut tasks, stop) = host();
    tasks.spawn_required("core", pending()).expect("sibling");
    service
        .spawn(&mut tasks, stop.clone())
        .await
        .expect("retired module must not prevent core startup");

    assert_eq!(tasks.active_count(), 1);
    assert!(!stop.is_cancelled());
    assert!(!state.is_fenced().expect("host fence"));
    assert!(!state.automation_is_available().expect("live route"));
    assert_eq!(
        reopened.timer_status().await.expect("durable status"),
        retired
    );
    assert_eq!(
        reopened.task(original.task_id).await.expect("history"),
        Some(original)
    );
    assert_eq!(
        reopened.create_task(&draft()).await,
        Err(AutomationError::TimerFenced)
    );
    tasks.shutdown().await;
    reopened.close().await;
}

#[tokio::test]
async fn production_constructor_never_resumes_a_draining_owner() {
    let fixture = fixture().await;
    let before = fixture.store.quiesce_timer().await.expect("drain");
    let (mut tasks, stop) = host();
    install(&fixture, &mut tasks, &stop).await;
    assert_eq!(tasks.active_count(), 1);
    assert_eq!(fixture.store.timer_status().await.expect("status"), before);
    assert_eq!(
        fixture.store.create_task(&draft()).await,
        Err(AutomationError::Conflict)
    );
    tasks.shutdown().await;
    assert!(!fixture.state.is_fenced().expect("host fence"));
    fixture.store.close().await;
}

#[path = "automation_factory_tests.rs"]
mod factory_tests;

#[tokio::test]
async fn scheduler_cadence_waits_before_first_tick_without_busy_polling() {
    let period = Duration::from_secs(3_600);
    let mut ticks = super::scheduler_ticks(period).expect("bounded cadence");
    assert_eq!(ticks.period(), period);
    assert_eq!(
        ticks.missed_tick_behavior(),
        tokio::time::MissedTickBehavior::Skip
    );
    let pending = std::future::poll_fn(|context| {
        std::task::Poll::Ready(ticks.poll_tick(context).is_pending())
    })
    .await;
    assert!(pending, "startup must not dispatch an immediate extra tick");
}

#[tokio::test]
async fn scheduler_cadence_skips_overrun_without_catch_up_dispatch_burst() {
    let period = Duration::from_secs(3_600);
    let mut ticks = super::scheduler_ticks(period).expect("bounded cadence");
    // Move only this test timer's schedule, not the runtime clock or owner
    // generation. The returned deadline is deterministic despite host load.
    let overdue = tokio::time::Instant::now() - period * 3;
    ticks.reset_at(overdue);
    assert_eq!(ticks.tick().await, overdue);
    let pending = std::future::poll_fn(|context| {
        std::task::Poll::Ready(ticks.poll_tick(context).is_pending())
    })
    .await;
    assert!(
        pending,
        "missed ticks must not become an immediate dispatch burst"
    );
}

#[tokio::test]
async fn scheduler_cadence_rejects_zero_and_overflow_instead_of_panicking() {
    for period in [Duration::ZERO, Duration::MAX] {
        assert!(matches!(
            super::scheduler_ticks(period),
            Err(crate::AgentdError::Invalid(_))
        ));
    }
}
