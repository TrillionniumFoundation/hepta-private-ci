use super::AdmissionFenceObservationError as Error;
use super::observe;
use crate::config::Config;
use crate::session::TurnInput;
use crate::session::session::Session;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::turn_context::TurnContext;
use crate::state::TaskKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::TurnLifecycleContributor;
use codex_extension_api::TurnStartInput;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::turn_input::NotSubmittedReason;
use codex_protocol::turn_input::TurnInputMode;
use codex_protocol::turn_input::TurnInputRequest;
use codex_protocol::turn_input::TurnInputSubmission;
use codex_protocol::user_input::UserInput;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::future::pending;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;
use tokio::time::Instant;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

const BUDGET: Duration = Duration::from_secs(/*secs*/ 5);

#[derive(Default)]
struct LifecycleGate {
    idle_entered: Notify,
    idle_release: Notify,
    hold_start: AtomicBool,
    start_entered: Notify,
    start_release: Notify,
}

impl ThreadLifecycleContributor<Config> for LifecycleGate {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.idle_entered.notify_one();
            self.idle_release.notified().await;
        })
    }
}

impl TurnLifecycleContributor for LifecycleGate {
    fn on_turn_start<'a>(&'a self, _input: TurnStartInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.hold_start.swap(/*val*/ false, Ordering::AcqRel) {
                self.start_entered.notify_one();
                self.start_release.notified().await;
            }
        })
    }
}

enum ProbeTask {
    Complete,
    UntilCancelled,
}

impl SessionTask for ProbeTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.admission_fence_observation_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        if matches!(self.as_ref(), Self::UntilCancelled) {
            cancellation_token.cancelled().await;
        }
        Ok(None)
    }
}

async fn held_finish() -> (
    Arc<Session>,
    Arc<LifecycleGate>,
    async_channel::Receiver<Event>,
) {
    let (mut session, context, rx) = make_session_and_context_with_rx().await;
    let gate = Arc::new(LifecycleGate::default());
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(gate.clone());
    extensions.turn_lifecycle_contributor(gate.clone());
    Arc::get_mut(&mut session)
        .expect("fixture has one Session owner")
        .services
        .extensions = Arc::new(extensions.build());
    session
        .spawn_task(context, Vec::new(), ProbeTask::Complete)
        .await
        .expect("fixture task admitted");
    timeout(BUDGET, gate.idle_entered.notified())
        .await
        .expect("real finish owner reached idle callback");
    assert!(session.active_turn.lock().await.is_none());
    assert!(session.has_pending_task_terminalization());
    (session, gate, rx)
}

async fn retire_finish(session: &Session, gate: &LifecycleGate) {
    let completion = session
        .pending_admission_fence_completion()
        .expect("owner still has its fence");
    gate.idle_release.notify_one();
    timeout(BUDGET, completion)
        .await
        .expect("owner retired its exact fence");
    assert!(!session.has_pending_admission_fence());
}

async fn assert_start_refused(session: &Arc<Session>) {
    let submission = crate::session::turn_input::handle(
        session,
        TurnInputRequest::user_input(Vec::new()),
        TurnInputMode::StartIfIdle,
        "observation-negative".to_string(),
    )
    .await
    .expect("normal routing returned an admission decision");
    assert_eq!(
        submission,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        }
    );
}

async fn stop_running_task(session: &Arc<Session>, gate: &LifecycleGate) {
    gate.idle_release.notify_one();
    timeout(
        BUDGET,
        session.abort_all_tasks(TurnAbortReason::Interrupted),
    )
    .await
    .expect("normal abort completed");
    if let Some(completion) = session.pending_admission_fence_completion() {
        timeout(BUDGET, completion)
            .await
            .expect("abort fence retired");
    }
}

#[tokio::test]
async fn held_fence_waits_and_success_does_not_authorize_later_start() {
    let (session, gate, _rx) = held_finish().await;
    let mut observation = Box::pin(observe(&session, pending(), Instant::now() + BUDGET));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    assert_start_refused(&session).await;
    retire_finish(&session, &gate).await;
    assert_eq!(observation.await, Ok(()));

    // A real admission after observation must still defeat a later StartIfIdle.
    session
        .spawn_task(
            session.new_default_turn().await,
            Vec::new(),
            ProbeTask::UntilCancelled,
        )
        .await
        .expect("a later caller admitted its own task");
    assert_start_refused(&session).await;
    stop_running_task(&session, &gate).await;
}

#[tokio::test]
async fn cancelling_observation_does_not_cancel_owner_or_retire_fence() {
    let (session, gate, _rx) = held_finish().await;
    let mut observation = Box::pin(observe(&session, pending(), Instant::now() + BUDGET));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    drop(observation);
    assert!(session.has_pending_task_terminalization());
    assert_start_refused(&session).await;
    retire_finish(&session, &gate).await;
}

#[tokio::test]
async fn deadline_does_not_release_a_stuck_owner() {
    let (session, gate, _rx) = held_finish().await;
    assert_eq!(
        observe(
            &session,
            pending(),
            Instant::now() + Duration::from_millis(/*millis*/ 1),
        )
        .await,
        Err(Error::Deadline)
    );
    assert!(session.has_pending_task_terminalization());
    assert_start_refused(&session).await;
    retire_finish(&session, &gate).await;
}

#[tokio::test]
async fn shutdown_during_retirement_remains_closed() {
    let (session, gate, _rx) = held_finish().await;
    let mut observation = Box::pin(observe(&session, pending(), Instant::now() + BUDGET));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    session.begin_shutdown();
    retire_finish(&session, &gate).await;
    assert_eq!(observation.await, Err(Error::Shutdown));
    assert_start_refused(&session).await;
}

#[tokio::test]
async fn terminated_dispatcher_does_not_release_a_live_fence() {
    let (session, gate, _rx) = held_finish().await;
    assert_eq!(
        observe(&session, std::future::ready(()), Instant::now() + BUDGET).await,
        Err(Error::Shutdown)
    );
    assert!(session.has_pending_task_terminalization());
    assert_start_refused(&session).await;
    retire_finish(&session, &gate).await;
}

#[tokio::test]
async fn a_replacement_turn_invalidates_the_original_observation() {
    let (session, gate, _rx) = held_finish().await;
    let mut observation = Box::pin(observe(&session, pending(), Instant::now() + BUDGET));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    retire_finish(&session, &gate).await;
    session
        .spawn_task(
            session.new_default_turn().await,
            Vec::new(),
            ProbeTask::UntilCancelled,
        )
        .await
        .expect("replacement admitted before observer resumes");
    assert_eq!(observation.await, Err(Error::Stale));
    assert_start_refused(&session).await;
    assert!(session.active_turn.lock().await.is_some());
    stop_running_task(&session, &gate).await;
}

#[tokio::test]
async fn a_new_start_fence_is_not_adopted_or_waited_by_old_observation() {
    let (session, gate, _rx) = held_finish().await;
    let epoch = session.turn_epoch.load(Ordering::Acquire);
    let mut observation = Box::pin(observe(&session, pending(), Instant::now() + BUDGET));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    retire_finish(&session, &gate).await;
    gate.hold_start.store(/*val*/ true, Ordering::Release);
    let new_start = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            session
                .spawn_task(
                    session.new_default_turn().await,
                    Vec::new(),
                    ProbeTask::UntilCancelled,
                )
                .await
        }
    });
    timeout(BUDGET, gate.start_entered.notified())
        .await
        .expect("new real start owner is held before attachment");
    // The real spawn owner consumes recovery mutation authority before its
    // start callback. That advances the epoch once, before task attachment.
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), epoch + 1);
    assert!(!new_start.is_finished());
    assert_eq!(observation.await, Err(Error::Stale));
    assert!(session.has_pending_start_transition());
    assert_start_refused(&session).await;
    gate.start_release.notify_one();
    timeout(BUDGET, new_start)
        .await
        .expect("start released")
        .expect("start task joined")
        .expect("new owner retained normal admission");
    stop_running_task(&session, &gate).await;
}

#[tokio::test]
async fn no_fence_does_not_await_or_cancel_an_active_task() {
    let (session, gate, _rx) = held_finish().await;
    retire_finish(&session, &gate).await;
    let context = session.new_default_turn().await;
    let turn_id = context.sub_id.clone();
    session
        .spawn_task(context, Vec::new(), ProbeTask::UntilCancelled)
        .await
        .expect("active task admitted");
    assert_eq!(
        observe(&session, pending(), Instant::now() + BUDGET).await,
        Ok(())
    );
    let submission = crate::session::turn_input::handle(
        &session,
        TurnInputRequest::user_input(vec![UserInput::Text {
            text: "steer the existing task".to_string(),
            text_elements: Vec::new(),
        }]),
        TurnInputMode::StartOrSteer,
        "observation-steer".to_string(),
    )
    .await
    .expect("ordinary steering remains available");
    assert_eq!(submission, TurnInputSubmission::Steered { turn_id });
    assert_start_refused(&session).await;
    assert!(session.active_turn.lock().await.is_some());
    stop_running_task(&session, &gate).await;
}

#[tokio::test]
async fn synchronous_registry_contention_fails_without_blocking_the_executor() {
    let (session, _context, _rx) = make_session_and_context_with_rx().await;
    let registry = session
        .pending_start_transition_completions
        .lock()
        .expect("registry is healthy");
    let result = observe(&session, pending(), Instant::now() + BUDGET).now_or_never();
    drop(registry);
    assert_eq!(result, Some(Err(Error::Busy)));
}
