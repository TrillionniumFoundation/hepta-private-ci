use super::*;
use pretty_assertions::assert_eq;

struct FinishOnSignal {
    finish: Arc<tokio::sync::Notify>,
}

impl SessionTask for FinishOnSignal {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }
    fn span_name(&self) -> &'static str {
        "session_task.terminal_publication_test"
    }
    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation: CancellationToken,
    ) -> SessionTaskResult {
        self.finish.notified().await;
        Ok(Some("finished once".to_string()))
    }
}

struct BlockFirstIdle {
    entered: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
    calls: Arc<std::sync::atomic::AtomicUsize>,
}

impl codex_extension_api::ThreadLifecycleContributor<crate::config::Config> for BlockFirstIdle {
    fn on_thread_idle<'a>(
        &'a self,
        _input: codex_extension_api::ThreadIdleInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

async fn next_terminal(rx: &async_channel::Receiver<Event>) -> Event {
    timeout(Duration::from_secs(3), async {
        loop {
            let event = rx.recv().await.expect("Core event receiver remains open");
            if matches!(
                event.msg,
                EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
            ) {
                return event;
            }
        }
    })
    .await
    .expect("the original terminal event should be delivered")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_notification_waits_for_cleanup_and_allows_immediate_next_input() {
    let (mut session, context, rx) = make_session_and_context_with_rx().await;
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("fresh owner")).await;
    let entered = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Notify::new());
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut extensions =
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    extensions.thread_lifecycle_contributor(Arc::new(BlockFirstIdle {
        entered: Arc::clone(&entered),
        release: Arc::clone(&release),
        calls: Arc::clone(&calls),
    }));
    Arc::get_mut(&mut session)
        .expect("unique test owner")
        .services
        .extensions = Arc::new(extensions.build());
    session
        .spawn_task(Arc::clone(&context), Vec::new(), CompletingTask)
        .await
        .expect("original task");
    timeout(Duration::from_secs(3), entered.notified())
        .await
        .expect("old idle cleanup paused");
    assert!(session.active_turn.lock().await.is_none());
    assert!(session.has_pending_admission_fence());
    assert!(
        !matches!(
            *session.agent_status.borrow(),
            AgentStatus::Completed(_) | AgentStatus::Errored(_)
        ),
        "status must not be terminal while admission is fenced"
    );
    while let Ok(event) = rx.try_recv() {
        assert!(
            !matches!(
                event.msg,
                EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
            ),
            "live terminal must wait for cleanup"
        );
    }
    let history = store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("durable history");
    assert_eq!(history.items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnComplete(event)) if event.turn_id == context.sub_id
    )).count(), 1, "terminal persisted once before publication");
    let refused = handle(
        &session,
        TurnInputRequest::user_input(vec![UserInput::Text {
            text: "still fenced".to_string(),
            text_elements: Vec::new(),
        }]),
        TurnInputMode::StartOrSteer,
        "still-fenced".to_string(),
    )
    .await
    .expect("valid input");
    assert_eq!(
        refused,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle
        }
    );
    release.notify_one();
    let terminal = next_terminal(&rx).await;
    assert!(
        matches!(terminal.msg, EventMsg::TurnComplete(event) if event.turn_id == context.sub_id)
    );
    assert!(!session.has_pending_admission_fence());
    assert_eq!(
        calls.load(Ordering::SeqCst),
        1,
        "old idle cleanup must not replay"
    );
    // No idle polling, sleep, retry, or join of the old task before this call.
    let next = handle(
        &session,
        TurnInputRequest::new(SubmittedTurnInput::UserInput {
            content: vec![UserInput::Text {
                text: "next input once".to_string(),
                text_elements: Vec::new(),
            }],
            client_id: Some("next-client-input".to_string()),
        }),
        TurnInputMode::StartOrSteer,
        "next-after-terminal".to_string(),
    )
    .await
    .expect("next input");
    assert_eq!(
        next,
        TurnInputSubmission::Started {
            turn_id: "next-after-terminal".to_string()
        }
    );
    session.begin_shutdown();
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_notification_precedes_the_pending_mailbox_successor_started_event() {
    let (session, context, rx) = make_session_and_context_with_rx().await;
    let finish = Arc::new(tokio::sync::Notify::new());
    session
        .spawn_task(
            Arc::clone(&context),
            Vec::new(),
            FinishOnSignal {
                finish: Arc::clone(&finish),
            },
        )
        .await
        .expect("controlled original task");
    session
        .input_queue
        .enqueue_mailbox_communication(
            InterAgentCommunication::new(
                AgentPath::root(),
                AgentPath::root(),
                Vec::new(),
                "pending successor input".to_string(),
                true,
            ),
            Some("mailbox-parent".to_string()),
            Some("mailbox-root".to_string()),
        )
        .await;
    finish.notify_one();
    let mut original_completed = false;
    timeout(Duration::from_secs(3), async {
        loop {
            let event = rx.recv().await.expect("Core event receiver remains open");
            match event.msg {
                EventMsg::TurnComplete(done) if done.turn_id == context.sub_id => {
                    assert!(!original_completed, "one completion for the original turn");
                    original_completed = true;
                }
                EventMsg::TurnStarted(started) if started.turn_id != context.sub_id => {
                    assert!(
                        original_completed,
                        "successor cannot overtake original completion"
                    );
                    break;
                }
                _ => {}
            }
        }
    })
    .await
    .expect("pending mailbox successor");
    session.begin_shutdown();
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[tokio::test]
async fn deferred_parent_notification_cannot_publish_early_or_overwrite_a_new_running_status() {
    let (session, mut context, rx) = make_session_and_context_with_rx().await;
    let context_mut = Arc::get_mut(&mut context).expect("unique test turn context");
    context_mut.multi_agent_version = codex_protocol::protocol::MultiAgentVersion::V2;
    context_mut.session_source = codex_protocol::protocol::SessionSource::SubAgent(
        codex_protocol::protocol::SubAgentSource::ThreadSpawn {
            parent_thread_id: codex_protocol::ThreadId::new(),
            depth: 1,
            agent_path: Some(AgentPath::root().join("worker").expect("worker path")),
            agent_nickname: None,
            agent_role: None,
        },
    );
    let error = CodexErr::InvalidRequest("original child failed".to_string()).to_error_event(None);
    context.terminal_error.lock().await.replace(error.clone());
    session.agent_status.send_replace(AgentStatus::Running);
    let mut prepared = session
        .prepare_terminal_event(
            context.as_ref(),
            EventMsg::TurnComplete(codex_protocol::protocol::TurnCompleteEvent {
                turn_id: context.sub_id.clone(),
                last_agent_message: None,
                error: Some(error),
                started_at: None,
                completed_at: None,
                duration_ms: None,
                time_to_first_token_ms: None,
            }),
        )
        .await;
    assert_eq!(
        *session.agent_status.borrow(),
        AgentStatus::Running,
        "preparing the V2 parent error cannot publish terminal status"
    );
    assert!(
        rx.try_recv().is_err(),
        "preparation cannot publish the protocol terminal"
    );
    session.publish_prepared_terminal_event(&mut prepared);
    assert!(matches!(
        *session.agent_status.borrow(),
        AgentStatus::Errored(_)
    ));
    assert!(matches!(
        rx.try_recv().expect("one terminal event").msg,
        EventMsg::TurnComplete(_)
    ));
    session.agent_status.send_replace(AgentStatus::Running);
    session
        .notify_prepared_terminal_parent(context.as_ref(), &mut prepared)
        .await;
    // Consumed prepared fields cannot replay an event or a stale status write.
    session.publish_prepared_terminal_event(&mut prepared);
    session
        .notify_prepared_terminal_parent(context.as_ref(), &mut prepared)
        .await;
    assert_eq!(*session.agent_status.borrow(), AgentStatus::Running);
    assert!(rx.try_recv().is_err());
}

struct BlockFirstAbort {
    entered: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
    calls: Arc<std::sync::atomic::AtomicUsize>,
}

impl codex_extension_api::TurnLifecycleContributor for BlockFirstAbort {
    fn on_turn_abort<'a>(
        &'a self,
        _input: codex_extension_api::TurnAbortInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn aborted_notification_waits_for_cleanup_and_allows_immediate_next_input() {
    let (mut session, context, rx) = make_session_and_context_with_rx().await;
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("fresh owner")).await;
    let entered = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Notify::new());
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut extensions =
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    extensions.turn_lifecycle_contributor(Arc::new(BlockFirstAbort {
        entered: Arc::clone(&entered),
        release: Arc::clone(&release),
        calls: Arc::clone(&calls),
    }));
    Arc::get_mut(&mut session)
        .expect("unique test owner")
        .services
        .extensions = Arc::new(extensions.build());
    session
        .spawn_task(
            Arc::clone(&context),
            Vec::new(),
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: true,
            },
        )
        .await
        .expect("interruptible original task");
    let abort_owner = tokio::spawn({
        let session = Arc::clone(&session);
        let turn_id = context.sub_id.clone();
        async move {
            session
                .abort_turn_if_active(&turn_id, TurnAbortReason::Interrupted)
                .await
        }
    });
    timeout(Duration::from_secs(3), entered.notified())
        .await
        .expect("old abort cleanup paused");
    assert!(session.has_pending_admission_fence());
    // Abort admission immediately exposes the existing cancellation intent.
    // Interrupted is explicitly nonfinal to the agent wait consumer; protocol
    // terminal delivery and next-input admission still wait for cleanup.
    let cancellation_status = session.agent_status.borrow().clone();
    assert_eq!(cancellation_status, AgentStatus::Interrupted);
    assert!(
        !crate::agent::status::is_final(&cancellation_status),
        "cancellation intent must not satisfy a final-status waiter"
    );
    while let Ok(event) = rx.try_recv() {
        assert!(!matches!(
            event.msg,
            EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_)
        ));
    }
    let history = store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("durable abort history");
    assert_eq!(history.items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(event)) if event.turn_id.as_deref() == Some(context.sub_id.as_str())
    )).count(), 1, "original cancellation is persisted once");
    let refused = handle(
        &session,
        TurnInputRequest::user_input(vec![UserInput::Text {
            text: "not yet admissible".to_string(),
            text_elements: Vec::new(),
        }]),
        TurnInputMode::StartOrSteer,
        "during-abort".to_string(),
    )
    .await
    .expect("valid input");
    assert_eq!(
        refused,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle
        }
    );
    release.notify_one();
    assert!(
        matches!(next_terminal(&rx).await.msg, EventMsg::TurnAborted(event)
        if event.turn_id.as_deref() == Some(context.sub_id.as_str()))
    );
    assert!(!session.has_pending_admission_fence());
    // Deliberately do not join the abort owner or poll idle before admission.
    let next = handle(
        &session,
        TurnInputRequest::user_input(vec![UserInput::Text {
            text: "input immediately after cancellation".to_string(),
            text_elements: Vec::new(),
        }]),
        TurnInputMode::StartOrSteer,
        "next-after-abort".to_string(),
    )
    .await
    .expect("next input");
    assert_eq!(
        next,
        TurnInputSubmission::Started {
            turn_id: "next-after-abort".to_string()
        }
    );
    assert!(abort_owner.await.expect("original abort owner joins"));
    session.begin_shutdown();
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

struct BlockStartAndAbort {
    start_entered: Arc<tokio::sync::Notify>,
    start_release: Arc<tokio::sync::Notify>,
    abort_entered: Arc<tokio::sync::Notify>,
    abort_release: Arc<tokio::sync::Notify>,
    starts: std::sync::atomic::AtomicUsize,
    aborts: std::sync::atomic::AtomicUsize,
}

impl codex_extension_api::TurnLifecycleContributor for BlockStartAndAbort {
    fn on_turn_start<'a>(
        &'a self,
        _input: codex_extension_api::TurnStartInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.starts.fetch_add(1, Ordering::SeqCst) == 0 {
                self.start_entered.notify_one();
                self.start_release.notified().await;
            }
        })
    }
    fn on_turn_abort<'a>(
        &'a self,
        _input: codex_extension_api::TurnAbortInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.aborts.fetch_add(1, Ordering::SeqCst) == 0 {
                self.abort_entered.notify_one();
                self.abort_release.notified().await;
            }
        })
    }
}

struct CountOriginalRun(Arc<std::sync::atomic::AtomicUsize>);

impl SessionTask for CountOriginalRun {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }
    fn span_name(&self) -> &'static str {
        "session_task.unstarted_publication_test"
    }
    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation: CancellationToken,
    ) -> SessionTaskResult {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(None)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unstarted_abort_publishes_after_exact_transition_retirement_without_running_task() {
    let (mut session, context, rx) = make_session_and_context_with_rx().await;
    let start_entered = Arc::new(tokio::sync::Notify::new());
    let abort_entered = Arc::new(tokio::sync::Notify::new());
    let abort_release = Arc::new(tokio::sync::Notify::new());
    let runs = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut extensions =
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    extensions.turn_lifecycle_contributor(Arc::new(BlockStartAndAbort {
        start_entered: Arc::clone(&start_entered),
        start_release: Arc::new(tokio::sync::Notify::new()),
        abort_entered: Arc::clone(&abort_entered),
        abort_release: Arc::clone(&abort_release),
        starts: std::sync::atomic::AtomicUsize::new(0),
        aborts: std::sync::atomic::AtomicUsize::new(0),
    }));
    Arc::get_mut(&mut session)
        .expect("unique test owner")
        .services
        .extensions = Arc::new(extensions.build());
    let starter = tokio::spawn({
        let session = Arc::clone(&session);
        let context = Arc::clone(&context);
        let runs = Arc::clone(&runs);
        async move {
            session
                .spawn_task(context, Vec::new(), CountOriginalRun(runs))
                .await
        }
    });
    timeout(Duration::from_secs(3), start_entered.notified())
        .await
        .expect("original start is paused");
    assert!(
        session
            .abort_turn_if_active(&context.sub_id, TurnAbortReason::Interrupted)
            .await
    );
    starter.abort();
    let _ = starter.await;
    timeout(Duration::from_secs(3), abort_entered.notified())
        .await
        .expect("detached start cleanup paused");
    assert!(session.has_pending_admission_fence());
    assert_eq!(runs.load(Ordering::SeqCst), 0);
    while let Ok(event) = rx.try_recv() {
        assert!(!matches!(
            event.msg,
            EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
        ));
    }
    abort_release.notify_one();
    assert!(
        matches!(next_terminal(&rx).await.msg, EventMsg::TurnAborted(event)
        if event.turn_id.as_deref() == Some(context.sub_id.as_str()))
    );
    assert!(!session.has_pending_admission_fence());
    assert_eq!(
        runs.load(Ordering::SeqCst),
        0,
        "the original provider-facing task never ran"
    );
    let next = handle(
        &session,
        TurnInputRequest::user_input(vec![UserInput::Text {
            text: "after unstarted cancellation".to_string(),
            text_elements: Vec::new(),
        }]),
        TurnInputMode::StartOrSteer,
        "next-after-unstarted".to_string(),
    )
    .await
    .expect("next input");
    assert_eq!(
        next,
        TurnInputSubmission::Started {
            turn_id: "next-after-unstarted".to_string()
        }
    );
    session.begin_shutdown();
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

struct SleepSuccessorProbe {
    starts: std::sync::atomic::AtomicUsize,
    idle_calls: Arc<std::sync::atomic::AtomicUsize>,
    successor_entered: Arc<tokio::sync::Notify>,
    successor_release: Arc<tokio::sync::Notify>,
}

impl codex_extension_api::TurnLifecycleContributor for SleepSuccessorProbe {
    fn on_turn_start<'a>(
        &'a self,
        _input: codex_extension_api::TurnStartInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.starts.fetch_add(1, Ordering::SeqCst) == 1 {
                self.successor_entered.notify_one();
                self.successor_release.notified().await;
            }
        })
    }
}

impl codex_extension_api::ThreadLifecycleContributor<crate::config::Config>
    for SleepSuccessorProbe
{
    fn on_thread_idle<'a>(
        &'a self,
        _input: codex_extension_api::ThreadIdleInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.idle_calls.fetch_add(1, Ordering::SeqCst);
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abort_with_durable_sleep_and_queue_only_mail_keeps_idle_suppressed_before_successor() {
    let (mut session, context, rx) = make_session_and_context_with_rx().await;
    let idle_calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let successor_entered = Arc::new(tokio::sync::Notify::new());
    let successor_release = Arc::new(tokio::sync::Notify::new());
    let probe = Arc::new(SleepSuccessorProbe {
        starts: std::sync::atomic::AtomicUsize::new(0),
        idle_calls: Arc::clone(&idle_calls),
        successor_entered: Arc::clone(&successor_entered),
        successor_release: Arc::clone(&successor_release),
    });
    let mut extensions =
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    extensions.turn_lifecycle_contributor(probe.clone());
    extensions.thread_lifecycle_contributor(probe);
    Arc::get_mut(&mut session)
        .expect("unique test owner")
        .services
        .extensions = Arc::new(extensions.build());
    session
        .spawn_task(
            Arc::clone(&context),
            Vec::new(),
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: true,
            },
        )
        .await
        .expect("interruptible original task");
    session
        .services
        .thread_extension_data
        .insert(codex_extension_items::sleep::SleepItem {
            id: "sleep-original".to_string(),
            duration_ms: 60_000,
        });
    session
        .input_queue
        .enqueue_mailbox_communication(
            InterAgentCommunication::new(
                AgentPath::root(),
                AgentPath::root(),
                Vec::new(),
                "queue-only while asleep".to_string(),
                false,
            ),
            Some("sleep-mailbox-parent".to_string()),
            Some("sleep-mailbox-root".to_string()),
        )
        .await;
    let turn_state = {
        let active = session.active_turn.lock().await;
        Arc::clone(&active.as_ref().expect("original active turn").turn_state)
    };
    let abort_owner = tokio::spawn({
        let session = Arc::clone(&session);
        let turn_id = context.sub_id.clone();
        async move {
            session
                .abort_turn_if_active_for_guardian(
                    &turn_id,
                    &turn_state,
                    TurnAbortReason::Interrupted,
                )
                .await
        }
    });
    timeout(Duration::from_secs(3), successor_entered.notified())
        .await
        .expect("queue-only mail wakes the durable sleep");
    assert_eq!(
        idle_calls.load(Ordering::SeqCst),
        0,
        "eligible pending successor suppresses the original guardian idle callback"
    );
    assert!(
        matches!(next_terminal(&rx).await.msg, EventMsg::TurnAborted(event)
        if event.turn_id.as_deref() == Some(context.sub_id.as_str()))
    );
    // Stop before releasing the successor's start hook: this check requires
    // actual mailbox admission but never needs a provider request.
    session.begin_shutdown();
    successor_release.notify_one();
    let _ = abort_owner.await.expect("original guardian abort joins");
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}
