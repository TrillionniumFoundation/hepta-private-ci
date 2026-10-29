use crate::config::Config;
use crate::session::TurnInput;
use crate::session::session::Session;
use crate::session::tests::make_session_and_context;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::turn_context::TurnContext;
use crate::state::StartTransitionCompletion;
use crate::state::TaskKind;
use crate::state::TaskTerminalizationKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleContinuations;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn snapshot_wait_requires_both_start_and_terminal_completion() {
    let (session, _turn_context) = make_session_and_context().await;
    let start_identity = Arc::new(());
    let start_completion = StartTransitionCompletion::new();
    session.register_start_transition(
        Arc::clone(&start_identity),
        Arc::clone(&start_completion),
        Arc::new(Mutex::new(None)),
    );
    let terminal_identity = Arc::new(());
    let terminal_completion = StartTransitionCompletion::new();
    session.register_task_terminalization(
        Arc::clone(&terminal_identity),
        Arc::clone(&terminal_completion),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    let observation = session.wait_for_pending_admission_transitions();
    tokio::pin!(observation);
    assert!(futures::poll!(observation.as_mut()).is_pending());

    session.finish_start_transition(&start_identity, &start_completion);
    assert!(futures::poll!(observation.as_mut()).is_pending());
    assert!(session.has_pending_task_terminalization());
    session.finish_task_terminalization(&terminal_identity, &terminal_completion);
    assert!(futures::poll!(observation.as_mut()).is_ready());
    assert!(!session.has_pending_admission_fence());
}

#[tokio::test]
async fn cancelled_observer_does_not_release_or_adopt_any_owner() {
    let (session, _turn_context) = make_session_and_context().await;
    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new();
    session.register_task_terminalization(
        Arc::clone(&identity),
        Arc::clone(&completion),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    {
        let observation = session.wait_for_pending_admission_transitions();
        tokio::pin!(observation);
        assert!(futures::poll!(observation.as_mut()).is_pending());
    }
    assert!(session.has_pending_admission_fence());
    assert!(!completion.is_complete());
    session.finish_task_terminalization(&identity, &completion);
    assert!(!session.has_pending_admission_fence());
}

#[tokio::test]
async fn snapshot_observer_does_not_follow_later_transitions_or_grant_admission() {
    let (session, _turn_context) = make_session_and_context().await;
    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new();
    session.register_task_terminalization(
        Arc::clone(&identity),
        Arc::clone(&completion),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    let observation = session.wait_for_pending_admission_transitions();
    tokio::pin!(observation);
    assert!(futures::poll!(observation.as_mut()).is_pending());
    let later_identity = Arc::new(());
    let later_completion = StartTransitionCompletion::new();
    session.register_start_transition(
        Arc::clone(&later_identity),
        Arc::clone(&later_completion),
        Arc::new(Mutex::new(None)),
    );
    session.finish_task_terminalization(&identity, &completion);
    assert!(futures::poll!(observation.as_mut()).is_ready());
    // Observation is not an admission reservation. The later transition still
    // owns the gate and every normal start must continue to check it.
    assert!(session.has_pending_admission_fence());
    assert!(!later_completion.is_complete());
    session.finish_start_transition(&later_identity, &later_completion);
}

struct CompletingTask;

impl SessionTask for CompletingTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.admission_readiness_regression"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        Ok(None)
    }
}

struct BlockingIdle {
    entered: Arc<Notify>,
    release: Arc<Notify>,
    calls: Arc<AtomicUsize>,
}

impl ThreadLifecycleContributor<Config> for BlockingIdle {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.entered.notify_one();
            self.release.notified().await;
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cleared_active_slot_remains_unready_until_the_real_idle_owner_returns() {
    let (mut session, turn_context, _events) = make_session_and_context_with_rx().await;
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let calls = Arc::new(AtomicUsize::new(0));
    let mut builder = ExtensionRegistryBuilder::<Config>::new();
    builder.thread_lifecycle_contributor(Arc::new(BlockingIdle {
        entered: Arc::clone(&entered),
        release: Arc::clone(&release),
        calls: Arc::clone(&calls),
    }));
    Arc::get_mut(&mut session)
        .expect("test session has a unique owner")
        .services
        .extensions = Arc::new(builder.build());
    session
        .spawn_task(turn_context, Vec::new(), CompletingTask)
        .await
        .expect("task should start");
    tokio::time::timeout(Duration::from_secs(/*secs*/ 1), entered.notified())
        .await
        .expect("terminalizer should enter the idle callback");
    assert!(session.active_turn.lock().await.is_none());
    assert!(session.has_pending_admission_fence());
    let observation = session.wait_for_pending_admission_transitions();
    tokio::pin!(observation);
    assert!(futures::poll!(observation.as_mut()).is_pending());
    assert!(session.has_pending_admission_fence());

    release.notify_one();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 1), observation)
        .await
        .expect("readiness follows the exact owner's completed lifecycle");
    assert!(!session.has_pending_admission_fence());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn deferred_admissions_preserve_registration_order_after_the_owner_completes() {
    let (session, _turn_context) = make_session_and_context().await;
    let session = Arc::new(session);
    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new();
    session.register_task_terminalization(
        Arc::clone(&identity),
        Arc::clone(&completion),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let order = Arc::new(Mutex::new(Vec::new()));
    let continuations = ThreadIdleContinuations::default();
    continuations.push(Box::pin({
        let entered = Arc::clone(&entered);
        let release = Arc::clone(&release);
        let order = Arc::clone(&order);
        async move {
            order.lock().expect("order mutex").push(1);
            entered.notify_one();
            release.notified().await;
        }
    }));
    continuations.push(Box::pin({
        let order = Arc::clone(&order);
        async move {
            order.lock().expect("order mutex").push(2);
        }
    }));
    let driver = session
        .run_idle_continuations(continuations, session.turn_epoch.load(Ordering::Acquire))
        .expect("registered continuations have a driver");
    tokio::task::yield_now().await;
    assert!(order.lock().expect("order mutex").is_empty());
    assert!(session.has_pending_admission_fence());
    session.finish_task_terminalization(&identity, &completion);
    tokio::time::timeout(Duration::from_secs(/*secs*/ 1), entered.notified())
        .await
        .expect("first continuation should start after cleanup");
    assert_eq!(*order.lock().expect("order mutex"), vec![1]);
    release.notify_one();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 1), driver)
        .await
        .expect("ordered continuations should finish")
        .expect("continuations should not panic");
    assert_eq!(*order.lock().expect("order mutex"), vec![1, 2]);
}

#[tokio::test]
async fn an_admitted_turn_retires_the_previous_idle_batch() {
    let (session, _turn_context) = make_session_and_context().await;
    let session = Arc::new(session);
    let idle_epoch = session.turn_epoch.load(Ordering::Acquire);
    let calls = Arc::new(AtomicUsize::new(0));
    let continuations = ThreadIdleContinuations::default();
    continuations.push(Box::pin({
        let session = Arc::clone(&session);
        let calls = Arc::clone(&calls);
        async move {
            calls.fetch_add(1, Ordering::SeqCst);
            // Model the epoch advance performed by an accepted queue turn.
            session.turn_epoch.fetch_add(1, Ordering::AcqRel);
        }
    }));
    continuations.push(Box::pin({
        let calls = Arc::clone(&calls);
        async move {
            calls.fetch_add(100, Ordering::SeqCst);
        }
    }));
    session
        .run_idle_continuations(continuations, idle_epoch)
        .expect("registered continuations have a driver")
        .await
        .expect("continuations should not panic");
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn shutdown_discards_deferred_admissions_without_releasing_the_owner_fence() {
    let (session, _turn_context) = make_session_and_context().await;
    let session = Arc::new(session);
    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new();
    session.register_task_terminalization(
        Arc::clone(&identity),
        Arc::clone(&completion),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    let calls = Arc::new(AtomicUsize::new(0));
    let continuations = ThreadIdleContinuations::default();
    continuations.push(Box::pin({
        let calls = Arc::clone(&calls);
        async move {
            calls.fetch_add(1, Ordering::SeqCst);
        }
    }));
    let driver = session
        .run_idle_continuations(continuations, session.turn_epoch.load(Ordering::Acquire))
        .expect("registered continuations have a driver");
    session.begin_shutdown();
    assert!(session.has_pending_admission_fence());
    assert!(!completion.is_complete());
    session.finish_task_terminalization(&identity, &completion);
    driver.await.expect("continuations should not panic");
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}
