use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Context;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_protocol::protocol::TurnAbortReason;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::config::Config;
use crate::session::TurnInput;
use crate::session::session::Session;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::turn_context::TurnContext;
use crate::state::TaskKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;

#[derive(Clone, Copy)]
enum Gate {
    Observer,
    FirstReady,
    None,
}

struct LifecycleProbe {
    gate: Gate,
    observed: AtomicUsize,
    ready: AtomicUsize,
    entered: Notify,
    release: Notify,
    ready_seen: Notify,
}

impl LifecycleProbe {
    fn new(gate: Gate) -> Arc<Self> {
        Arc::new(Self {
            gate,
            observed: AtomicUsize::new(0),
            ready: AtomicUsize::new(0),
            entered: Notify::new(),
            release: Notify::new(),
            ready_seen: Notify::new(),
        })
    }
}

impl ThreadLifecycleContributor<Config> for LifecycleProbe {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.observed.fetch_add(1, Ordering::SeqCst);
            if matches!(self.gate, Gate::Observer) {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }

    fn on_thread_idle_ready<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let previous = self.ready.fetch_add(1, Ordering::SeqCst);
            self.ready_seen.notify_one();
            if matches!(self.gate, Gate::FirstReady) && previous == 0 {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

struct HeldTask {
    release: Arc<Notify>,
}

impl SessionTask for HeldTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.idle_ready_regression"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        tokio::select! {
            _ = self.release.notified() => {}
            _ = cancellation_token.cancelled() => {}
        }
        Ok(None)
    }
}

async fn test_session(
    probes: &[Arc<LifecycleProbe>],
) -> anyhow::Result<(
    Arc<Session>,
    Arc<TurnContext>,
    async_channel::Receiver<codex_protocol::protocol::Event>,
)> {
    let (mut session, turn_context, rx) = make_session_and_context_with_rx().await;
    let mut builder = ExtensionRegistryBuilder::<Config>::new();
    for probe in probes {
        builder.thread_lifecycle_contributor(probe.clone());
    }
    Arc::get_mut(&mut session)
        .context("test session must have a unique owner")?
        .services
        .extensions = Arc::new(builder.build());
    Ok((session, turn_context, rx))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn finish_idle_ready_runs_once_after_its_observer_and_fence() -> anyhow::Result<()> {
    let probe = LifecycleProbe::new(Gate::Observer);
    let (session, turn_context, _rx) = test_session(&[Arc::clone(&probe)]).await?;
    let task_release = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&turn_context),
            Vec::new(),
            HeldTask {
                release: Arc::clone(&task_release),
            },
        )
        .await?;
    let finish = tokio::spawn({
        let session = Arc::clone(&session);
        let turn_context = Arc::clone(&turn_context);
        async move { session.on_task_finished(turn_context, Ok(None)).await }
    });
    timeout(Duration::from_secs(2), probe.entered.notified()).await?;
    assert!(session.has_pending_task_terminalization());
    assert_eq!(probe.ready.load(Ordering::SeqCst), 0);
    probe.release.notify_one();
    timeout(Duration::from_secs(2), probe.ready_seen.notified()).await?;
    timeout(Duration::from_secs(2), finish).await??;
    assert!(!session.has_pending_admission_fence());
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(
        (
            probe.observed.load(Ordering::SeqCst),
            probe.ready.load(Ordering::SeqCst)
        ),
        (1, 1)
    );

    session.on_task_finished(turn_context, Ok(None)).await;
    assert_eq!(
        (
            probe.observed.load(Ordering::SeqCst),
            probe.ready.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
    task_release.notify_one();
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn later_turn_invalidates_remaining_idle_ready_callbacks() -> anyhow::Result<()> {
    let first = LifecycleProbe::new(Gate::FirstReady);
    let second = LifecycleProbe::new(Gate::None);
    let (session, turn_context, _rx) =
        test_session(&[Arc::clone(&first), Arc::clone(&second)]).await?;
    let old_release = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&turn_context),
            Vec::new(),
            HeldTask {
                release: Arc::clone(&old_release),
            },
        )
        .await?;
    let finish = tokio::spawn({
        let session = Arc::clone(&session);
        async move { session.on_task_finished(turn_context, Ok(None)).await }
    });
    timeout(Duration::from_secs(2), first.entered.notified()).await?;
    assert!(!session.has_pending_admission_fence());
    let next_context = session
        .new_default_turn_with_sub_id("next-idle-generation".to_string())
        .await;
    let next_release = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&next_context),
            Vec::new(),
            HeldTask {
                release: Arc::clone(&next_release),
            },
        )
        .await?;
    session.on_task_finished(next_context, Ok(None)).await;
    timeout(Duration::from_secs(2), second.ready_seen.notified()).await?;
    assert!(session.active_turn.lock().await.is_none());
    first.release.notify_one();
    timeout(Duration::from_secs(2), finish).await??;
    assert_eq!(
        (
            first.ready.load(Ordering::SeqCst),
            second.ready.load(Ordering::SeqCst)
        ),
        (2, 1)
    );
    old_release.notify_one();
    next_release.notify_one();
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_finish_caller_does_not_cancel_idle_ready() -> anyhow::Result<()> {
    let first = LifecycleProbe::new(Gate::FirstReady);
    let second = LifecycleProbe::new(Gate::None);
    let (session, turn_context, _rx) =
        test_session(&[Arc::clone(&first), Arc::clone(&second)]).await?;
    let task_release = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&turn_context),
            Vec::new(),
            HeldTask {
                release: Arc::clone(&task_release),
            },
        )
        .await?;
    let finish = tokio::spawn({
        let session = Arc::clone(&session);
        async move { session.on_task_finished(turn_context, Ok(None)).await }
    });
    timeout(Duration::from_secs(2), first.entered.notified()).await?;
    assert!(!session.has_pending_admission_fence());
    finish.abort();
    assert!(finish.await.is_err());

    // A completed Finish no longer owns the idle callback's time budget. The
    // original watchdog must neither cancel this callback nor fence admission.
    assert!(
        timeout(
            crate::tasks::TERMINALIZER_WATCHDOG_TIMEOUT + Duration::from_millis(/*millis*/ 10),
            second.ready_seen.notified(),
        )
        .await
        .is_err()
    );
    first.release.notify_one();
    timeout(Duration::from_secs(2), second.ready_seen.notified()).await?;
    assert_eq!(
        (
            first.ready.load(Ordering::SeqCst),
            second.ready.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
    assert!(!session.has_pending_admission_fence());
    task_release.notify_one();
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shutdown_during_finish_observation_suppresses_idle_ready() -> anyhow::Result<()> {
    let probe = LifecycleProbe::new(Gate::Observer);
    let (session, turn_context, _rx) = test_session(&[Arc::clone(&probe)]).await?;
    let task_release = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&turn_context),
            Vec::new(),
            HeldTask {
                release: Arc::clone(&task_release),
            },
        )
        .await?;
    let finish = tokio::spawn({
        let session = Arc::clone(&session);
        async move { session.on_task_finished(turn_context, Ok(None)).await }
    });
    timeout(Duration::from_secs(2), probe.entered.notified()).await?;
    session.begin_shutdown();
    probe.release.notify_one();
    timeout(Duration::from_secs(2), finish).await??;
    assert!(!session.has_pending_task_terminalization());
    assert_eq!(probe.ready.load(Ordering::SeqCst), 0);
    task_release.notify_one();
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn interrupted_task_does_not_dispatch_idle_ready() -> anyhow::Result<()> {
    let probe = LifecycleProbe::new(Gate::None);
    let (session, turn_context, _rx) = test_session(&[Arc::clone(&probe)]).await?;
    session
        .spawn_task(
            turn_context,
            Vec::new(),
            HeldTask {
                release: Arc::new(Notify::new()),
            },
        )
        .await?;
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(probe.ready.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn idle_without_a_terminalizer_dispatches_ready_after_observation() -> anyhow::Result<()> {
    let probe = LifecycleProbe::new(Gate::None);
    let (session, _turn_context, _rx) = test_session(&[Arc::clone(&probe)]).await?;
    session
        .emit_thread_idle_lifecycle_if_idle(ThreadIdleCause::Completed)
        .await;
    assert_eq!(
        (
            probe.observed.load(Ordering::SeqCst),
            probe.ready.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
    Ok(())
}
