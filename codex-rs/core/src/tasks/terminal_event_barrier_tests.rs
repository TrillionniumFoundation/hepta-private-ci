use super::*;
use crate::session::tests::make_session_and_context_with_rx;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use futures::poll;
use std::time::Duration;

fn receiver_io(events: async_channel::Receiver<Event>) -> crate::session::SessionIo {
    let (tx_sub, _rx_sub) = async_channel::unbounded();
    crate::session::SessionIo {
        tx_sub,
        rx_event: events,
        agent_status: tokio::sync::watch::channel(crate::agent::AgentStatus::PendingInit).1,
        session_loop_termination: futures::future::ready(()).boxed().shared(),
    }
}

struct BlockingIdle {
    entered: Arc<Notify>,
    release: Arc<Notify>,
}

impl ThreadLifecycleContributor<crate::config::Config> for BlockingIdle {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.entered.notify_one();
            self.release.notified().await;
        })
    }
}

struct CompletingTask;

impl SessionTask for CompletingTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.terminal_event_barrier_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation: CancellationToken,
    ) -> SessionTaskResult {
        Ok(None)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn terminal_event_barrier_waits_for_real_finish_handoff() {
    let (mut session, context, events) = make_session_and_context_with_rx().await;
    let idle_entered = Arc::new(Notify::new());
    let idle_release = Arc::new(Notify::new());
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::new();
    builder.thread_lifecycle_contributor(Arc::new(BlockingIdle {
        entered: Arc::clone(&idle_entered),
        release: Arc::clone(&idle_release),
    }));
    Arc::get_mut(&mut session)
        .expect("unique test session")
        .services
        .extensions = Arc::new(builder.build());
    session
        .spawn_task(Arc::clone(&context), Vec::new(), CompletingTask)
        .await
        .expect("completing task starts");

    let terminal = tokio::time::timeout(Duration::from_secs(2), async {
        let terminal = loop {
            let event = events.recv().await.expect("core event receiver open");
            if matches!(event.msg, EventMsg::TurnComplete(_)) {
                break event;
            }
        };
        idle_entered.notified().await;
        terminal
    })
    .await
    .expect("terminal event precedes the gated idle callback");
    let completion = session.take_terminal_event_completion(&terminal);
    tokio::pin!(completion);
    assert!(poll!(completion.as_mut()).is_pending());
    assert!(session.has_pending_task_terminalization());
    assert!(session.active_turn.lock().await.is_none());

    idle_release.notify_one();
    tokio::time::timeout(Duration::from_secs(2), completion)
        .await
        .expect("barrier observes the actual owner retiring its fence");
    assert!(!session.has_pending_task_terminalization());
}

#[tokio::test]
async fn terminal_event_barrier_keeps_exact_captured_owners() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let start_id = Arc::new(());
    let start = StartTransitionCompletion::new("finished-turn".to_string());
    session.register_start_transition(
        Arc::clone(&start_id),
        Arc::clone(&start),
        Arc::new(std::sync::Mutex::new(None)),
    );
    let finish_id = Arc::new(());
    let finish = StartTransitionCompletion::new("finished-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&finish_id),
        Arc::clone(&finish),
        TaskTerminalizationKind::Finish,
        None,
        None,
        None,
    );
    let unrelated_id = Arc::new(());
    let unrelated = StartTransitionCompletion::new("another-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&unrelated_id),
        Arc::clone(&unrelated),
        TaskTerminalizationKind::Abort,
        None,
        None,
        None,
    );
    let completion = session.turn_completion_barrier(Some("finished-turn"));
    tokio::pin!(completion);
    assert!(poll!(completion.as_mut()).is_pending());

    // Even reuse of the logical turn id cannot attach a later generation to an
    // already captured barrier. The waiter owns the original completion Arcs.
    let later_id = Arc::new(());
    let later = StartTransitionCompletion::new("finished-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&later_id),
        Arc::clone(&later),
        TaskTerminalizationKind::Finish,
        None,
        None,
        None,
    );
    session.finish_task_terminalization(&finish_id, &finish);
    assert!(poll!(completion.as_mut()).is_pending());
    session.finish_start_transition(&start_id, &start);
    assert!(poll!(completion.as_mut()).is_ready());
    assert!(!later.is_complete());
    assert!(!unrelated.is_complete());
    assert!(session.has_pending_task_terminalization());
    // Dropping another observer is also read-only and cannot open admission.
    drop(session.turn_completion_barrier(None));
    assert!(session.has_pending_task_terminalization());
    session.finish_task_terminalization(&later_id, &later);
    session.finish_task_terminalization(&unrelated_id, &unrelated);
}

fn terminal_event(turn_id: &str) -> Event {
    Event {
        id: turn_id.to_string(),
        msg: EventMsg::TurnComplete(TurnCompleteEvent {
            turn_id: turn_id.to_string(),
            last_agent_message: None,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
            time_to_first_token_ms: None,
        }),
    }
}

#[tokio::test]
async fn queued_terminal_event_does_not_wait_for_recovered_same_id_owner() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let old_id = Arc::new(());
    let old = StartTransitionCompletion::new("recovered-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&old_id),
        Arc::clone(&old),
        TaskTerminalizationKind::Finish,
        None,
        None,
        None,
    );
    let event = terminal_event("recovered-turn");
    session
        .capture_terminal_event_completion(&event)
        .await
        .expect("terminal event has a publication sidecar");
    session.finish_task_terminalization(&old_id, &old);

    // Recovery reuses the logical id and reaches a later terminalization before
    // the old queued event is consumed. The old notification must remain ready.
    let recovered_id = Arc::new(());
    let recovered = StartTransitionCompletion::new("recovered-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&recovered_id),
        Arc::clone(&recovered),
        TaskTerminalizationKind::Finish,
        None,
        None,
        None,
    );
    let old_observer = session.take_terminal_event_completion(&event);
    tokio::pin!(old_observer);
    assert!(poll!(old_observer.as_mut()).is_ready());
    assert!(!recovered.is_complete());
    let queue = session
        .services
        .thread_extension_data
        .get::<TerminalEventCompletionQueue>()
        .expect("runtime sidecar queue");
    assert!(queue.entries.lock().unwrap().is_empty());

    session
        .capture_terminal_event_completion(&event)
        .await
        .expect("recovered generation has its own sidecar");
    let mut recovered_observer = Box::pin(session.take_terminal_event_completion(&event));
    assert!(poll!(recovered_observer.as_mut()).is_pending());
    drop(recovered_observer);
    assert!(queue.entries.lock().unwrap().is_empty());
    assert!(!recovered.is_complete());
    assert!(session.has_pending_task_terminalization());
    session.finish_task_terminalization(&recovered_id, &recovered);
}

#[tokio::test]
async fn undeliverable_terminal_event_drops_only_its_observation() {
    let (session, context, events) = make_session_and_context_with_rx().await;
    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new(context.sub_id.clone());
    session.register_task_terminalization(
        Arc::clone(&identity),
        Arc::clone(&completion),
        TaskTerminalizationKind::Finish,
        None,
        None,
        None,
    );
    events.close();
    session
        .send_event(&context, terminal_event(&context.sub_id).msg)
        .await;
    let queue = session
        .services
        .thread_extension_data
        .get::<TerminalEventCompletionQueue>()
        .expect("runtime sidecar queue");
    assert!(queue.entries.lock().unwrap().is_empty());
    assert!(!completion.is_complete());
    assert!(session.has_pending_task_terminalization());
    session.finish_task_terminalization(&identity, &completion);
}

/// Force the exact capture-before-send gap on the real sender. Only the first
/// terminal publication in the instrumented session pauses; all other tests
/// and production builds have no publication pause.
#[derive(Default)]
struct TerminalPublicationPause {
    entered: AtomicBool,
    release: Notify,
}

impl Session {
    pub(crate) async fn pause_terminal_event_publication_for_test(&self, event: &Event) {
        if terminal_event_turn_id(event).is_none() {
            return;
        }
        if let Some(pause) = self
            .services
            .thread_extension_data
            .get::<TerminalPublicationPause>()
            && !pause.entered.swap(true, Ordering::AcqRel)
        {
            pause.release.notified().await;
        }
    }
}

#[tokio::test]
async fn concurrent_terminal_publishers_keep_sidecars_in_event_order() {
    let (session, _context, events) = make_session_and_context_with_rx().await;
    let pause = session
        .services
        .thread_extension_data
        .get_or_init::<TerminalPublicationPause>(Default::default);
    let old_id = Arc::new(());
    let old = StartTransitionCompletion::new("reused-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&old_id),
        Arc::clone(&old),
        TaskTerminalizationKind::Finish,
        None,
        None,
        None,
    );
    let mut first_event = terminal_event("reused-turn");
    first_event.id = "first-publication".to_string();
    let mut first = Box::pin(session.deliver_event_raw(first_event));
    assert!(poll!(first.as_mut()).is_pending());
    assert!(pause.entered.load(Ordering::Acquire));

    // First has captured old but has not enqueued its event. A recovered owner
    // now reuses the logical id, and a second real sender attempts to publish.
    session.finish_task_terminalization(&old_id, &old);
    let recovered_id = Arc::new(());
    let recovered = StartTransitionCompletion::new("reused-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&recovered_id),
        Arc::clone(&recovered),
        TaskTerminalizationKind::Finish,
        None,
        None,
        None,
    );
    let mut second_event = terminal_event("reused-turn");
    second_event.id = "second-publication".to_string();
    let mut second = Box::pin(session.deliver_event_raw(second_event));
    assert!(poll!(second.as_mut()).is_pending());
    assert!(events.try_recv().is_err());
    let queue = session
        .services
        .thread_extension_data
        .get::<TerminalEventCompletionQueue>()
        .expect("runtime sidecar queue");
    assert_eq!(queue.entries.lock().unwrap().len(), 1);

    pause.release.notify_one();
    tokio::time::timeout(Duration::from_secs(2), async {
        tokio::join!(first, second);
    })
    .await
    .expect("both real publishers finish without a receiver or owner lock cycle");
    let first_event = events.try_recv().expect("first event delivered");
    let second_event = events.try_recv().expect("second event delivered");
    assert_eq!(first_event.id, "first-publication");
    assert_eq!(second_event.id, "second-publication");
    let mut first_observer = Box::pin(session.take_terminal_event_completion(&first_event));
    let mut second_observer = Box::pin(session.take_terminal_event_completion(&second_event));
    assert!(poll!(first_observer.as_mut()).is_ready());
    assert!(poll!(second_observer.as_mut()).is_pending());
    assert!(queue.entries.lock().unwrap().is_empty());
    assert!(!recovered.is_complete());
    session.finish_task_terminalization(&recovered_id, &recovered);
    assert!(poll!(second_observer.as_mut()).is_ready());
}

#[tokio::test]
async fn concurrent_receivers_pair_reused_turn_sidecars_in_receive_order() -> anyhow::Result<()> {
    let (session, _context, events) = make_session_and_context_with_rx().await;
    let io = receiver_io(events);
    let mut first = Box::pin(session.receive_event_with_completion(&io));
    let mut second = Box::pin(session.receive_event_with_completion(&io));
    assert!(poll!(first.as_mut()).is_pending());
    assert!(poll!(second.as_mut()).is_pending());

    let old_id = Arc::new(());
    let old = StartTransitionCompletion::new("reused-receive-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&old_id),
        Arc::clone(&old),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    let mut first_event = terminal_event("reused-receive-turn");
    first_event.id = "first-receive".to_string();
    session.deliver_event_raw(first_event.clone()).await;
    session.finish_task_terminalization(&old_id, &old);

    let later_id = Arc::new(());
    let later = StartTransitionCompletion::new("reused-receive-turn".to_string());
    session.register_task_terminalization(
        Arc::clone(&later_id),
        Arc::clone(&later),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    let mut second_event = terminal_event("reused-receive-turn");
    second_event.id = "second-receive".to_string();
    session.deliver_event_raw(second_event.clone()).await;

    // Even with both events ready, polling the later waiter first cannot let it
    // consume the earlier event or claim the earlier generation's sidecar.
    assert!(poll!(second.as_mut()).is_pending());
    let (received_first, first_completion) = first.await?;
    assert_eq!(
        serde_json::to_value(received_first)?,
        serde_json::to_value(first_event)?
    );
    let (received_second, second_completion) = second.await?;
    assert_eq!(
        serde_json::to_value(received_second)?,
        serde_json::to_value(second_event)?
    );
    tokio::pin!(first_completion, second_completion);
    assert!(poll!(first_completion.as_mut()).is_ready());
    assert!(poll!(second_completion.as_mut()).is_pending());
    session.finish_task_terminalization(&later_id, &later);
    assert!(poll!(second_completion.as_mut()).is_ready());
    Ok(())
}

#[tokio::test]
async fn cancelled_receivers_preserve_the_next_event_and_release_admission() -> anyhow::Result<()> {
    let (session, _context, events) = make_session_and_context_with_rx().await;
    let io = receiver_io(events);
    let mut active = Box::pin(session.receive_event_with_completion(&io));
    let mut queued = Box::pin(session.receive_event_with_completion(&io));
    assert!(poll!(active.as_mut()).is_pending());
    assert!(poll!(queued.as_mut()).is_pending());
    drop(queued);
    let mut replacement = Box::pin(session.receive_event_with_completion(&io));
    assert!(poll!(replacement.as_mut()).is_pending());
    drop(active);
    assert!(poll!(replacement.as_mut()).is_pending());

    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new("after-receive-cancellation".to_string());
    session.register_task_terminalization(
        Arc::clone(&identity),
        Arc::clone(&completion),
        TaskTerminalizationKind::Finish,
        /*suspension_handoff*/ None,
        /*abort_handoff*/ None,
        /*finish_handoff*/ None,
    );
    let event = terminal_event("after-receive-cancellation");
    session.deliver_event_raw(event.clone()).await;
    let (received, observer) = replacement.await?;
    assert_eq!(
        serde_json::to_value(received)?,
        serde_json::to_value(event)?
    );
    tokio::pin!(observer);
    assert!(poll!(observer.as_mut()).is_pending());

    // Completion observation no longer holds the receive permit. Both the
    // first closed-channel error and its successor must finish immediately.
    io.rx_event.close();
    for _ in 0..2 {
        let mut closed = Box::pin(session.receive_event_with_completion(&io));
        assert!(matches!(
            poll!(closed.as_mut()),
            std::task::Poll::Ready(Err(_))
        ));
    }
    assert!(!completion.is_complete());
    session.finish_task_terminalization(&identity, &completion);
    assert!(poll!(observer.as_mut()).is_ready());
    Ok(())
}
