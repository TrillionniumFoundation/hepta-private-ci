use super::*;
use crate::test_support::TurnRetirementObservationError;
use crate::test_support::wait_for_session_turn_retirement;
use pretty_assertions::assert_eq;
use tokio::time::Instant;
use tokio::time::timeout_at;

use codex_thread_store as thread_store;
use codex_thread_store::ThreadStore;
use codex_thread_store::ThreadStoreFuture;

// Delegate persistence unchanged, but hold the flush following TurnComplete.
// This test must distinguish event delivery, durability, and fence retirement.
#[derive(Default)]
struct PausedTerminalFlushStore {
    inner: thread_store::InMemoryThreadStore,
    terminal_appended: AtomicBool,
    fail_terminal_flush: bool,
    flush_entered: Notify,
    flush_release: Notify,
}

impl ThreadStore for PausedTerminalFlushStore {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn create_thread(&self, params: CreateThreadParams) -> ThreadStoreFuture<'_, ()> {
        ThreadStore::create_thread(&self.inner, params)
    }

    fn resume_thread(&self, params: thread_store::ResumeThreadParams) -> ThreadStoreFuture<'_, ()> {
        ThreadStore::resume_thread(&self.inner, params)
    }

    fn is_thread_hard_delete_fenced(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, bool> {
        self.inner.is_thread_hard_delete_fenced(thread_id)
    }

    fn append_items(
        &self,
        params: thread_store::AppendThreadItemsParams,
    ) -> ThreadStoreFuture<'_, ()> {
        Box::pin(async move {
            let terminal_appended = params
                .items
                .iter()
                .any(|item| matches!(item, RolloutItem::EventMsg(EventMsg::TurnComplete(_))));
            ThreadStore::append_items(&self.inner, params).await?;
            if terminal_appended {
                self.terminal_appended.store(true, Ordering::SeqCst);
            }
            Ok(())
        })
    }

    fn persist_thread(
        &self,
        thread_id: ThreadId,
        context: PersistContext,
    ) -> ThreadStoreFuture<'_, ()> {
        self.inner.persist_thread(thread_id, context)
    }

    fn flush_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()> {
        Box::pin(async move {
            if self.terminal_appended.swap(false, Ordering::SeqCst) {
                self.flush_entered.notify_one();
                self.flush_release.notified().await;
                if self.fail_terminal_flush {
                    return Err(thread_store::ThreadStoreError::Internal {
                        message: "injected terminal flush failure".to_string(),
                    });
                }
            }
            self.inner.flush_thread(thread_id).await
        })
    }

    fn shutdown_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()> {
        self.inner.shutdown_thread(thread_id)
    }

    fn discard_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()> {
        self.inner.discard_thread(thread_id)
    }

    fn load_history(
        &self,
        params: thread_store::LoadThreadHistoryParams,
    ) -> ThreadStoreFuture<'_, thread_store::StoredThreadHistory> {
        ThreadStore::load_history(&self.inner, params)
    }

    fn load_latest_model_context(
        &self,
        params: thread_store::LoadThreadHistoryParams,
    ) -> ThreadStoreFuture<'_, thread_store::StoredModelContext> {
        ThreadStore::load_latest_model_context(&self.inner, params)
    }

    fn read_thread(
        &self,
        params: thread_store::ReadThreadParams,
    ) -> ThreadStoreFuture<'_, thread_store::StoredThread> {
        ThreadStore::read_thread(&self.inner, params)
    }

    fn read_thread_by_rollout_path(
        &self,
        params: thread_store::ReadThreadByRolloutPathParams,
    ) -> ThreadStoreFuture<'_, thread_store::StoredThread> {
        ThreadStore::read_thread_by_rollout_path(&self.inner, params)
    }

    fn list_threads(
        &self,
        params: thread_store::ListThreadsParams,
    ) -> ThreadStoreFuture<'_, thread_store::ThreadPage> {
        ThreadStore::list_threads(&self.inner, params)
    }

    fn update_thread_metadata(
        &self,
        params: thread_store::UpdateThreadMetadataParams,
    ) -> ThreadStoreFuture<'_, Option<thread_store::StoredThread>> {
        ThreadStore::update_thread_metadata(&self.inner, params)
    }

    fn move_thread_to_section(
        &self,
        params: thread_store::MoveThreadToSectionParams,
    ) -> ThreadStoreFuture<'_, ()> {
        ThreadStore::move_thread_to_section(&self.inner, params)
    }

    fn archive_thread(
        &self,
        params: thread_store::ArchiveThreadParams,
    ) -> ThreadStoreFuture<'_, ()> {
        ThreadStore::archive_thread(&self.inner, params)
    }

    fn unarchive_thread(
        &self,
        params: thread_store::ArchiveThreadParams,
    ) -> ThreadStoreFuture<'_, thread_store::StoredThread> {
        ThreadStore::unarchive_thread(&self.inner, params)
    }

    fn delete_thread(&self, params: thread_store::DeleteThreadParams) -> ThreadStoreFuture<'_, ()> {
        ThreadStore::delete_thread(&self.inner, params)
    }
}

#[derive(Default)]
struct PausedThreadIdle {
    entered: Notify,
    release: Notify,
}

impl codex_extension_api::ThreadLifecycleContributor<crate::config::Config> for PausedThreadIdle {
    fn on_thread_idle<'a>(
        &'a self,
        _input: codex_extension_api::ThreadIdleInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.entered.notify_one();
            self.release.notified().await;
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn compact_after_turn_complete_rejects_while_terminalization_pending() {
    let server = start_mock_server().await;
    let (mut session, turn_context, rx) = make_session_and_context_with_auth_and_config_and_rx(
        CodexAuth::from_api_key("Test API Key"),
        Vec::new(),
        |config| config.model_provider.base_url = Some(server.uri()),
    )
    .await;
    let store = Arc::new(PausedTerminalFlushStore::default());
    let idle = Arc::new(PausedThreadIdle::default());
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.thread_lifecycle_contributor(idle.clone());
    let unique_session = Arc::get_mut(&mut session).expect("session should be uniquely owned");
    unique_session.services.extensions = Arc::new(builder.build());
    attach_thread_store(unique_session, store.clone()).await;
    let persistence_generation = session.rollout_persistence_failure_generation();
    session
        .spawn_task(Arc::clone(&turn_context), Vec::new(), CompletingTask)
        .await
        .expect("seed task should start");
    let seed_epoch = session.turn_epoch.load(Ordering::SeqCst);

    let terminal = recv_terminal_event(&rx, TerminalEventKind::TurnComplete).await;
    assert_eq!(terminal.id, turn_context.sub_id);
    assert!(matches!(
        terminal.msg,
        EventMsg::TurnComplete(TurnCompleteEvent { turn_id, error: None, .. })
            if turn_id == turn_context.sub_id
    ));
    timeout(StdDuration::from_secs(2), store.flush_entered.notified())
        .await
        .expect("terminal durability barrier should be held after event delivery");
    let completion = {
        let pending = session
            .pending_task_terminalization_completions
            .lock()
            .expect("terminalization registry should not be poisoned");
        assert_eq!(pending.len(), 1);
        Arc::clone(&pending[0].1)
    };

    for compact_id in [
        "compact-during-terminal-flush",
        "compact-during-idle-publication",
    ] {
        if compact_id == "compact-during-idle-publication" {
            store.flush_release.notify_one();
            timeout(StdDuration::from_secs(2), idle.entered.notified())
                .await
                .expect("finish should reach the held idle lifecycle callback");
            assert_eq!(store.inner.calls().await.flush_thread, 2);
            assert!(session.active_turn.lock().await.is_none());
        } else {
            assert_eq!(store.inner.calls().await.flush_thread, 1);
            assert!(
                session
                    .active_turn
                    .lock()
                    .await
                    .as_ref()
                    .is_some_and(|active| {
                        active.task.is_none() && active.task_terminalization.is_some()
                    })
            );
        }
        assert!(!completion.is_complete());
        assert!(session.has_pending_task_terminalization());
        timeout(
            StdDuration::from_secs(2),
            handlers::compact(&session, compact_id.to_string()),
        )
        .await
        .expect("Compact should report the held admission fence without waiting for it");
        let error = timeout(StdDuration::from_secs(2), rx.recv())
            .await
            .expect("Compact rejection should be delivered")
            .expect("event receiver should remain open");
        assert_eq!(
            serde_json::to_value(&error).expect("rejection event should serialize"),
            serde_json::to_value(Event {
                id: compact_id.to_string(),
                msg: EventMsg::Error(ErrorEvent {
                    message: "failed to start compaction: cannot start a task while the previous turn is terminalizing".to_string(),
                    codex_error_info: Some(CodexErrorInfo::Other),
                }),
            })
            .expect("expected event should serialize")
        );
        assert_eq!(session.turn_epoch.load(Ordering::SeqCst), seed_epoch);
        assert!(
            server
                .received_requests()
                .await
                .expect("request recording enabled")
                .is_empty()
        );
        assert!(
            rx.try_recv().is_err(),
            "rejected Compact must not emit TurnComplete"
        );
    }

    idle.release.notify_one();
    // This signal proves retirement only. Verify the successful test-store flush
    // and unchanged persistence-failure generation separately.
    timeout(StdDuration::from_secs(2), completion.wait())
        .await
        .expect("the exact seed terminalization fence should retire after release");
    assert!(!session.has_pending_task_terminalization());
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(store.inner.calls().await.flush_thread, 2);
    assert_eq!(
        session.rollout_persistence_failure_generation(),
        persistence_generation
    );
    assert!(
        rx.try_recv().is_err(),
        "rejected Compact must not run after fence retirement"
    );
}

struct PausedRetirement {
    session: Arc<Session>,
    store: Arc<PausedTerminalFlushStore>,
    idle: Arc<PausedThreadIdle>,
    completion: Arc<crate::state::StartTransitionCompletion>,
    deadline: Instant,
    _rx: async_channel::Receiver<Event>,
}

impl PausedRetirement {
    async fn start(store: PausedTerminalFlushStore) -> Self {
        let (mut session, turn_context, rx) = make_session_and_context_with_rx().await;
        let store = Arc::new(store);
        let idle = Arc::new(PausedThreadIdle::default());
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.thread_lifecycle_contributor(idle.clone());
        let unique_session = Arc::get_mut(&mut session).expect("unique test session");
        unique_session.services.extensions = Arc::new(builder.build());
        attach_thread_store(unique_session, store.clone()).await;
        let deadline = Instant::now() + StdDuration::from_secs(2);
        session
            .spawn_task(turn_context, Vec::new(), CompletingTask)
            .await
            .expect("seed task should start");
        recv_terminal_event(&rx, TerminalEventKind::TurnComplete).await;
        timeout_at(deadline, store.flush_entered.notified())
            .await
            .expect("terminal flush should be paused");
        let completion = {
            let pending = session
                .pending_task_terminalization_completions
                .lock()
                .expect("terminalization registry should not be poisoned");
            assert_eq!(pending.len(), 1);
            Arc::clone(&pending[0].1)
        };
        Self {
            session,
            store,
            idle,
            completion,
            deadline,
            _rx: rx,
        }
    }

    async fn release_flush(&self) {
        self.store.flush_release.notify_one();
        timeout_at(self.deadline, self.idle.entered.notified())
            .await
            .expect("terminalizer should reach idle callback");
    }

    async fn retire(&self) {
        self.release_flush().await;
        self.idle.release.notify_one();
        timeout_at(self.deadline, self.completion.wait())
            .await
            .expect("exact terminalizer should retire");
    }
}

#[tokio::test]
async fn retirement_observation_waits_for_flush_and_idle_fence() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
    let mut observation = Box::pin(wait_for_session_turn_retirement(
        &fixture.session,
        fixture.deadline,
    ));
    // One poll establishes the captured generation and proves the held fence
    // blocks observation; this is not a polling-based readiness wait.
    assert!(futures::poll!(observation.as_mut()).is_pending());
    assert!(fixture.session.active_turn.try_lock().is_ok());
    assert!(!fixture.completion.is_complete());

    fixture.release_flush().await;
    assert!(fixture.session.active_turn.lock().await.is_none());
    assert!(futures::poll!(observation.as_mut()).is_pending());
    fixture.idle.release.notify_one();
    assert_eq!(observation.await, Ok(()));
    assert!(fixture.completion.is_complete());
    assert!(!fixture.session.has_pending_admission_fence());
}

#[tokio::test]
async fn retirement_observation_rejects_newer_active_and_retired_turns() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
    let mut active_observation = Box::pin(wait_for_session_turn_retirement(
        &fixture.session,
        fixture.deadline,
    ));
    let mut idle_observation = Box::pin(wait_for_session_turn_retirement(
        &fixture.session,
        fixture.deadline,
    ));
    assert!(futures::poll!(active_observation.as_mut()).is_pending());
    assert!(futures::poll!(idle_observation.as_mut()).is_pending());
    fixture.retire().await;

    let successor = fixture
        .session
        .new_default_turn_with_sub_id("retirement-observer-successor".to_string())
        .await;
    fixture
        .session
        .spawn_task(
            successor,
            Vec::new(),
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: true,
            },
        )
        .await
        .expect("ordinary admission should attach a real successor");
    assert_eq!(
        active_observation.await,
        Err(TurnRetirementObservationError::Stale)
    );
    assert_eq!(
        wait_for_session_turn_retirement(&fixture.session, fixture.deadline).await,
        Err(TurnRetirementObservationError::Busy)
    );
    assert!(
        fixture
            .session
            .active_turn
            .lock()
            .await
            .as_ref()
            .is_some_and(|turn| turn.task.is_some())
    );
    // Normal test cleanup, not a replacement or retry by the observer.
    fixture.idle.release.notify_one();
    fixture
        .session
        .abort_all_tasks(TurnAbortReason::Interrupted)
        .await;
    assert!(fixture.session.active_turn.lock().await.is_none());
    assert!(!fixture.session.has_pending_admission_fence());
    assert_eq!(
        idle_observation.await,
        Err(TurnRetirementObservationError::Stale)
    );
}

#[tokio::test]
async fn retirement_observation_rejects_registry_contention_at_capture_and_recheck() {
    enum Registry {
        StartTransition,
        TaskTerminalization,
    }
    // Four independent scenarios, not a readiness polling or retry loop.
    for after_retirement in [false, true] {
        for registry in [Registry::StartTransition, Registry::TaskTerminalization] {
            let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
            let mut observation = Box::pin(wait_for_session_turn_retirement(
                &fixture.session,
                fixture.deadline,
            ));
            if after_retirement {
                assert!(futures::poll!(observation.as_mut()).is_pending());
                fixture.retire().await;
            }
            // Poll synchronously once while holding the chosen registry. There
            // is no await with a std mutex guard, and even an empty contended
            // registry after legitimate retirement must report Busy.
            let mut context = std::task::Context::from_waker(futures::task::noop_waker_ref());
            let result = match registry {
                Registry::StartTransition => {
                    let _guard = fixture
                        .session
                        .pending_start_transition_completions
                        .lock()
                        .expect("start registry should not be poisoned");
                    std::future::Future::poll(observation.as_mut(), &mut context)
                }
                Registry::TaskTerminalization => {
                    let _guard = fixture
                        .session
                        .pending_task_terminalization_completions
                        .lock()
                        .expect("terminalization registry should not be poisoned");
                    std::future::Future::poll(observation.as_mut(), &mut context)
                }
            };
            assert_eq!(
                result,
                std::task::Poll::Ready(Err(TurnRetirementObservationError::Busy))
            );
            if !after_retirement {
                fixture.retire().await;
            }
            assert!(!fixture.session.has_pending_admission_fence());
        }
    }
}

#[tokio::test]
async fn cancelled_retirement_observation_preserves_terminalizer() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
    let mut observation = Box::pin(wait_for_session_turn_retirement(
        &fixture.session,
        fixture.deadline,
    ));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    drop(observation);
    assert!(!fixture.completion.is_complete());
    assert!(fixture.session.has_pending_task_terminalization());
    fixture.retire().await;
    assert_eq!(fixture.store.inner.calls().await.flush_thread, 2);
    assert!(!fixture.session.has_pending_admission_fence());
}

#[tokio::test]
async fn retirement_observation_deadline_does_not_cancel_terminalizer() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
    tokio::time::pause();
    // Expire the observer before the existing 2s terminalizer watchdog.
    let now = Instant::now();
    let deadline = now + fixture.deadline.saturating_duration_since(now) / 2;
    let mut observation = Box::pin(wait_for_session_turn_retirement(&fixture.session, deadline));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    tokio::time::advance(deadline.saturating_duration_since(Instant::now())).await;
    assert_eq!(
        observation.await,
        Err(TurnRetirementObservationError::Deadline)
    );
    assert!(!fixture.completion.is_complete());
    assert!(fixture.session.has_pending_task_terminalization());

    // Release the owner for cleanup without renewing the observer's deadline.
    fixture.store.flush_release.notify_one();
    fixture.idle.release.notify_one();
    timeout_at(fixture.deadline, fixture.completion.wait())
        .await
        .expect("owner cleanup should complete within the original fixture budget");
    assert!(!fixture.session.has_pending_admission_fence());
    assert_eq!(
        wait_for_session_turn_retirement(&fixture.session, deadline).await,
        Err(TurnRetirementObservationError::Deadline)
    );
}

#[tokio::test]
async fn retirement_observation_deadline_bounds_capture_lock() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
    tokio::time::pause();
    // Expire the observer before the existing 2s terminalizer watchdog.
    let now = Instant::now();
    let deadline = now + fixture.deadline.saturating_duration_since(now) / 2;
    let active = fixture.session.active_turn.lock().await;
    let mut observation = Box::pin(wait_for_session_turn_retirement(&fixture.session, deadline));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    tokio::time::advance(deadline.saturating_duration_since(Instant::now())).await;
    assert_eq!(
        observation.await,
        Err(TurnRetirementObservationError::Deadline)
    );
    drop(active);
    fixture.store.flush_release.notify_one();
    fixture.idle.release.notify_one();
    timeout_at(fixture.deadline, fixture.completion.wait())
        .await
        .expect("owner cleanup should complete within the original fixture budget");
}

#[tokio::test]
async fn retirement_observation_deadline_bounds_recheck_lock() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
    tokio::time::pause();
    // Expire the observer before the existing 2s terminalizer watchdog.
    let now = Instant::now();
    let deadline = now + fixture.deadline.saturating_duration_since(now) / 2;
    let mut observation = Box::pin(wait_for_session_turn_retirement(&fixture.session, deadline));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    fixture.retire().await;
    let active = fixture.session.active_turn.lock().await;
    assert!(futures::poll!(observation.as_mut()).is_pending());
    tokio::time::advance(deadline.saturating_duration_since(Instant::now())).await;
    assert_eq!(
        observation.await,
        Err(TurnRetirementObservationError::Deadline)
    );
    drop(active);
    assert!(!fixture.session.has_pending_admission_fence());
}

#[tokio::test]
async fn retirement_observation_rechecks_shutdown() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore::default()).await;
    let mut observation = Box::pin(wait_for_session_turn_retirement(
        &fixture.session,
        fixture.deadline,
    ));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    fixture.session.begin_shutdown();
    fixture.store.flush_release.notify_one();
    fixture.idle.release.notify_one();
    assert_eq!(
        observation.await,
        Err(TurnRetirementObservationError::Shutdown)
    );
    assert!(fixture.completion.is_complete());
}

#[tokio::test]
async fn retirement_observation_does_not_imply_successful_terminal_flush() {
    let fixture = PausedRetirement::start(PausedTerminalFlushStore {
        fail_terminal_flush: true,
        ..Default::default()
    })
    .await;
    let failure_generation = fixture.session.rollout_persistence_failure_generation();
    let mut observation = Box::pin(wait_for_session_turn_retirement(
        &fixture.session,
        fixture.deadline,
    ));
    assert!(futures::poll!(observation.as_mut()).is_pending());
    fixture.retire().await;
    assert_eq!(observation.await, Ok(()));
    assert_eq!(fixture.store.inner.calls().await.flush_thread, 1);
    assert!(fixture.session.rollout_persistence_failure_generation() > failure_generation);
}
