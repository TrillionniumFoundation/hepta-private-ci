use super::*;

struct BlockingPollAbortTask {
    entered: Arc<Notify>,
    release: std::sync::Mutex<std::sync::mpsc::Receiver<()>>,
}

impl SessionTask for BlockingPollAbortTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }
    fn span_name(&self) -> &'static str {
        "session_task.terminal_shutdown_blocking_poll"
    }
    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        self.entered.notify_one();
        // A real blocked poll cannot be quiesced by JoinHandle::abort. The
        // test's sender closes on panic too, so this worker cannot leak.
        let _ = self.release.lock().expect("release mutex healthy").recv();
        Ok(None)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn nonquiescent_abort_shutdown_waits_for_terminal_delivery() {
    let (mut session, context, old_rx) = make_session_and_context_with_rx().await;
    drop(old_rx);
    let (tx, rx) = async_channel::bounded(/*cap*/ 1);
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique session")).await;
    Arc::get_mut(&mut session).expect("unique session").tx_event = tx;
    let entered = Arc::new(Notify::new());
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    session
        .spawn_task(
            Arc::clone(&context),
            Vec::new(),
            BlockingPollAbortTask {
                entered: Arc::clone(&entered),
                release: std::sync::Mutex::new(release_rx),
            },
        )
        .await
        .expect("blocking task attaches");
    timeout(Duration::from_secs(2), entered.notified())
        .await
        .expect("actual task poll entered");
    let abort = tokio::spawn({
        let session = Arc::clone(&session);
        async move { session.abort_all_tasks(TurnAbortReason::Interrupted).await }
    });
    let completion = timeout(Duration::from_secs(2), async {
        loop {
            let completion = session
                .pending_task_terminalization_completions
                .lock()
                .expect("registry healthy")
                .first()
                .map(|entry| Arc::clone(&entry.1));
            if let Some(completion) = completion {
                break completion;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("original abort owner is registered");
    timeout(Duration::from_secs(3), async {
        loop {
            if store.calls().await.flush_thread >= 3 && session.active_turn.lock().await.is_none() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("terminal is durable before outward notification");
    // The original interrupted history event occupies the real bounded
    // delivery channel. TurnAborted cannot yet be delivered to its observer.
    session.begin_shutdown();
    let mut drain = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            session
                .drain_task_terminalizations_for_shutdown_except(/*excluded_identity*/ None)
                .await
        }
    });
    assert!(
        timeout(Duration::from_millis(100), &mut drain)
            .await
            .is_err(),
        "shutdown must wait for blocked terminal delivery"
    );
    assert!(
        !completion.is_complete(),
        "shutdown must retain the exact owner through terminal delivery"
    );
    assert!(!session.has_pending_admission_fence());
    release_tx.send(()).expect("release actual task poll");
    assert!(matches!(
        rx.recv().await.expect("original interrupted event").msg,
        EventMsg::RawResponseItem(_)
    ));
    assert!(matches!(
        rx.recv().await.expect("actual terminal event").msg,
        EventMsg::TurnAborted(_)
    ));
    timeout(Duration::from_secs(2), &mut drain)
        .await
        .expect("shutdown drain retires")
        .expect("drain joins");
    abort.await.expect("abort owner joins");
    assert!(completion.is_complete());
}

struct BlockingIdleAfterStartAbort {
    entered: Arc<Notify>,
    release: Arc<Notify>,
}

impl codex_extension_api::ThreadLifecycleContributor<crate::config::Config>
    for BlockingIdleAfterStartAbort
{
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
async fn unstarted_abort_shutdown_waits_for_terminal_delivery_and_idle_callback() {
    let (mut session, context, old_rx) = make_session_and_context_with_rx().await;
    drop(old_rx);
    let (tx, rx) = async_channel::bounded(/*cap*/ 1);
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique session")).await;
    Arc::get_mut(&mut session).expect("unique session").tx_event = tx;
    let idle_entered = Arc::new(Notify::new());
    let idle_release = Arc::new(Notify::new());
    let mut registry =
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    registry.thread_lifecycle_contributor(Arc::new(BlockingIdleAfterStartAbort {
        entered: Arc::clone(&idle_entered),
        release: Arc::clone(&idle_release),
    }));
    Arc::get_mut(&mut session)
        .expect("unique session")
        .services
        .extensions = Arc::new(registry.build());
    let identity = Arc::new(());
    let mut active = ActiveTurn::default();
    let state = Arc::clone(&active.turn_state);
    let mut transition = StartTransition::new(context.sub_id.clone(), Arc::clone(&identity));
    transition.request_deferred_idle(codex_extension_api::ThreadIdleCause::Interrupted);
    let completion = Arc::clone(&transition.completion);
    active.start_transition = Some(transition);
    *session.active_turn.lock().await = Some(active);
    let slot = Arc::new(std::sync::Mutex::new(Some(StartTransitionCleanup::new(
        &session,
        Arc::new(NeverEndingTask {
            kind: TaskKind::Regular,
            listen_to_cancellation_token: true,
        }),
        Arc::clone(&context),
        state,
        Arc::clone(&identity),
        Arc::clone(&completion),
        /*recovery_history_restore*/ None,
    ))));
    session
        .pending_start_transition_completions
        .lock()
        .expect("registry healthy")
        .push((identity, Arc::clone(&completion), Arc::clone(&slot)));
    let mut owner = StartTransitionOwner::new(slot);
    let terminalizer = owner
        .spawn_cleanup_for_test(TurnAbortReason::Interrupted)
        .expect("original cleanup starts");
    drop(owner);
    timeout(Duration::from_secs(3), async {
        loop {
            if store.calls().await.flush_thread >= 3 && session.active_turn.lock().await.is_none() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("unstarted terminal persisted and exact active slot cleared");
    let idle_before_admission_release = timeout(Duration::from_secs(2), async {
        tokio::select! {
            _ = idle_entered.notified() => true,
            _ = async {
                while session.has_pending_admission_fence() {
                    tokio::task::yield_now().await;
                }
            } => false,
        }
    })
    .await
    .expect("original terminal owner reaches release or idle callback");
    assert!(
        !idle_before_admission_release,
        "original idle callback must follow terminal admission release and notification"
    );
    assert!(
        !completion.is_complete(),
        "shutdown must retain start completion before terminal notification"
    );
    assert!(
        !session.has_pending_admission_fence(),
        "terminal notification must already allow successor admission"
    );
    assert!(
        session.has_pending_start_transition(),
        "shutdown still owns the full start registry"
    );
    session.begin_shutdown();
    let mut drain = tokio::spawn({
        let session = Arc::clone(&session);
        async move { session.drain_start_transition_for_shutdown().await }
    });
    assert!(
        timeout(Duration::from_millis(100), &mut drain)
            .await
            .is_err()
    );
    assert!(matches!(
        rx.recv().await.expect("original interrupted event").msg,
        EventMsg::RawResponseItem(_)
    ));
    assert!(matches!(
        rx.recv().await.expect("actual terminal event").msg,
        EventMsg::TurnAborted(_)
    ));
    timeout(Duration::from_secs(2), idle_entered.notified())
        .await
        .expect("original idle callback begins after terminal notification");
    assert!(!completion.is_complete());
    assert!(
        timeout(Duration::from_millis(100), &mut drain)
            .await
            .is_err(),
        "shutdown includes the actual idle callback"
    );
    idle_release.notify_one();
    timeout(Duration::from_secs(2), &mut drain)
        .await
        .expect("shutdown drain retires")
        .expect("drain joins");
    terminalizer.await.expect("original terminalizer joins");
    assert!(completion.is_complete());
}
