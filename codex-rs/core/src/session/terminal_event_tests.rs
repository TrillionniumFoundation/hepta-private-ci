use super::super::TurnInput;
use super::super::session::Session;
use super::super::tests::attach_in_memory_thread_store;
use super::super::tests::make_session_and_context_with_rx;
use super::super::thread_settings;
use super::super::turn_context::TurnContext;
use crate::config::Config;
use crate::state::TaskKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::TurnAbortInput;
use codex_extension_api::TurnLifecycleContributor;
use codex_extension_api::TurnStopInput;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::TurnAbortReason;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::task::Poll;
use std::time::Duration;
use tokio::sync::Notify;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

struct LifecycleGate {
    entered: Notify,
    release: Notify,
    seen: AtomicBool,
}

impl LifecycleGate {
    async fn block_once(&self) {
        if !self.seen.swap(true, Ordering::SeqCst) {
            self.entered.notify_one();
            self.release.notified().await;
        }
    }
}

impl TurnLifecycleContributor for LifecycleGate {
    fn on_turn_stop<'a>(&'a self, _input: TurnStopInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(self.block_once())
    }
    fn on_turn_abort<'a>(&'a self, _input: TurnAbortInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(self.block_once())
    }
}

#[derive(Clone, Copy)]
enum TaskEnd {
    Complete,
    WaitForInterrupt,
}

struct ProbeTask(TaskEnd);

impl SessionTask for ProbeTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.terminal_readiness_probe"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        if matches!(self.0, TaskEnd::WaitForInterrupt) {
            cancellation_token.cancelled().await;
        }
        Ok(None)
    }
}

async fn assert_terminal_readiness(end: TaskEnd) {
    let (mut session, context, events) = make_session_and_context_with_rx().await;
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique session owner"))
            .await;
    let gate = Arc::new(LifecycleGate {
        entered: Notify::new(),
        release: Notify::new(),
        seen: AtomicBool::new(false),
    });
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.turn_lifecycle_contributor(gate.clone());
    Arc::get_mut(&mut session)
        .expect("unique session owner")
        .services
        .extensions = Arc::new(extensions.build());
    session
        .spawn_task(Arc::clone(&context), Vec::new(), ProbeTask(end))
        .await
        .expect("initial task starts");
    let abort_owner = if matches!(end, TaskEnd::WaitForInterrupt) {
        Some(tokio::spawn({
            let session = Arc::clone(&session);
            async move { session.abort_all_tasks(TurnAbortReason::Interrupted).await }
        }))
    } else {
        None
    };

    timeout(Duration::from_secs(2), gate.entered.notified())
        .await
        .expect("terminal lifecycle reaches its deterministic barrier");
    assert!(session.has_pending_admission_fence());
    if matches!(end, TaskEnd::WaitForInterrupt) {
        assert!(store.calls().await.flush_thread >= 2);
    }
    while let Ok(event) = events.try_recv() {
        assert!(
            !matches!(
                event.msg,
                EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
            ),
            "terminal notification must wait for lifecycle and recovery cleanup"
        );
    }
    let next = session
        .new_default_turn_with_sub_id("after-terminal-readiness".to_string())
        .await;
    assert!(
        session
            .spawn_task(Arc::clone(&next), Vec::new(), ProbeTask(TaskEnd::Complete))
            .await
            .is_err(),
        "unfinished cleanup must continue to reject admission"
    );

    gate.release.notify_one();
    timeout(Duration::from_secs(2), async {
        loop {
            let event = events.recv().await.expect("terminal event channel open");
            if matches!(
                event.msg,
                EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
            ) {
                assert_eq!(event.id, context.sub_id);
                break;
            }
        }
    })
    .await
    .expect("terminal event follows barrier release");
    assert!(store.calls().await.flush_thread >= 2);

    // No polling or settling delay: receipt itself is the readiness boundary.
    assert!(!session.has_pending_admission_fence());
    thread_settings::update(
        &session,
        "settings-after-terminal".to_string(),
        ThreadSettingsOverrides::default(),
    )
    .await;
    let applied = events.recv().await.expect("settings response");
    assert_eq!(applied.id, "settings-after-terminal");
    assert!(matches!(applied.msg, EventMsg::ThreadSettingsApplied(_)));
    session
        .spawn_task(next, Vec::new(), ProbeTask(TaskEnd::Complete))
        .await
        .expect("the next task starts immediately after terminal receipt");
    if let Some(abort_owner) = abort_owner {
        abort_owner.await.expect("abort terminalizer completes");
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completion_waits_for_turn_cleanup_then_admits_settings_and_next_task() {
    assert_terminal_readiness(TaskEnd::Complete).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abort_waits_for_lifecycle_cleanup_then_admits_settings_and_next_task() {
    assert_terminal_readiness(TaskEnd::WaitForInterrupt).await;
}

struct IdleFollowup {
    session: OnceLock<Weak<Session>>,
    admitted: async_channel::Sender<bool>,
    release: Notify,
    seen: AtomicBool,
}

impl ThreadLifecycleContributor<Config> for IdleFollowup {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.seen.swap(true, Ordering::SeqCst) {
                return;
            }
            let session = self
                .session
                .get()
                .and_then(Weak::upgrade)
                .expect("live test session");
            let next = session
                .new_default_turn_with_sub_id("idle-followup".to_string())
                .await;
            let admitted = session
                .spawn_task(next, Vec::new(), ProbeTask(TaskEnd::WaitForInterrupt))
                .await
                .is_ok();
            self.admitted.send(admitted).await.expect("test receiver");
            self.release.notified().await;
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn idle_callback_admits_followup_while_shutdown_retains_completion_owner() {
    let (mut session, context, events) = make_session_and_context_with_rx().await;
    attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique session owner")).await;
    let (admitted_tx, admitted_rx) = async_channel::bounded(1);
    let followup = Arc::new(IdleFollowup {
        session: OnceLock::new(),
        admitted: admitted_tx,
        release: Notify::new(),
        seen: AtomicBool::new(false),
    });
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(followup.clone());
    Arc::get_mut(&mut session)
        .expect("unique session owner")
        .services
        .extensions = Arc::new(extensions.build());
    assert!(followup.session.set(Arc::downgrade(&session)).is_ok());
    session
        .spawn_task(
            Arc::clone(&context),
            Vec::new(),
            ProbeTask(TaskEnd::Complete),
        )
        .await
        .expect("initial task starts");
    assert!(
        timeout(Duration::from_secs(2), admitted_rx.recv())
            .await
            .expect("idle callback attempts the followup")
            .expect("admission result"),
        "idle consumers must be able to use ordinary admission without an owner exemption"
    );
    let mut terminal_seen = false;
    while let Ok(event) = events.try_recv() {
        if let EventMsg::TurnComplete(_) = event.msg {
            assert_eq!(event.id, context.sub_id);
            terminal_seen = true;
        }
    }
    assert!(
        terminal_seen,
        "terminal delivery precedes the idle followup"
    );
    assert!(!session.has_pending_admission_fence());

    session.begin_shutdown();
    let mut drain = std::pin::pin!(
        session.drain_task_terminalizations_for_shutdown_except(/*excluded_identity*/ None)
    );
    assert!(matches!(futures::poll!(drain.as_mut()), Poll::Pending));
    followup.release.notify_one();
    timeout(Duration::from_secs(2), drain)
        .await
        .expect("shutdown drains the callback after admission opened");
    assert!(
        session
            .pending_task_terminalization_completions
            .lock()
            .expect("completion registry")
            .is_empty()
    );
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}
