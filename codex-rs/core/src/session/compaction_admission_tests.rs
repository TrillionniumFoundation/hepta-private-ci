use super::*;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn compact_after_turn_complete_rejects_while_terminalization_pending() {
    use codex_thread_store as thread_store;
    use codex_thread_store::ThreadStore;
    use codex_thread_store::ThreadStoreFuture;

    // Delegate persistence unchanged, but hold the flush following TurnComplete.
    // This test must distinguish event delivery, durability, and fence retirement.
    #[derive(Default)]
    struct PausedTerminalFlushStore {
        inner: thread_store::InMemoryThreadStore,
        terminal_appended: AtomicBool,
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

        fn resume_thread(
            &self,
            params: thread_store::ResumeThreadParams,
        ) -> ThreadStoreFuture<'_, ()> {
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

        fn delete_thread(
            &self,
            params: thread_store::DeleteThreadParams,
        ) -> ThreadStoreFuture<'_, ()> {
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
