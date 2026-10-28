use super::*;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;

#[derive(Clone, Copy)]
enum GatePoint {
    ThreadIdle,
    TurnAbort,
}

struct TerminalCleanupGate {
    point: GatePoint,
    armed: AtomicBool,
    entered: Notify,
    release: Notify,
}

impl codex_extension_api::ThreadLifecycleContributor<crate::config::Config>
    for TerminalCleanupGate
{
    fn on_thread_idle<'a>(
        &'a self,
        _input: codex_extension_api::ThreadIdleInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if matches!(self.point, GatePoint::ThreadIdle)
                && self.armed.swap(false, Ordering::AcqRel)
            {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

impl codex_extension_api::TurnLifecycleContributor for TerminalCleanupGate {
    fn on_turn_abort<'a>(
        &'a self,
        _input: codex_extension_api::TurnAbortInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if matches!(self.point, GatePoint::TurnAbort)
                && self.armed.swap(false, Ordering::AcqRel)
            {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

struct StartedThenWaitTask;

impl SessionTask for StartedThenWaitTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.terminal_publication_successor"
    }

    async fn run(
        self: Arc<Self>,
        session: Arc<Session>,
        context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        session
            .send_event(
                context.as_ref(),
                EventMsg::TurnStarted(TurnStartedEvent {
                    turn_id: context.sub_id.clone(),
                    trace_id: context.trace_id.clone(),
                    started_at: None,
                    model_context_window: context.model_context_window(),
                    collaboration_mode_kind: context.mode,
                }),
            )
            .await;
        cancellation_token.cancelled().await;
        Ok(None)
    }
}

async fn persisted_terminals(session: &Session) -> Vec<serde_json::Value> {
    session
        .services
        .live_thread
        .as_ref()
        .expect("test thread persistence")
        .load_history(/*include_archived*/ false)
        .await
        .expect("read persisted thread")
        .items
        .into_iter()
        .filter_map(|item| match item {
            RolloutItem::EventMsg(
                event @ (EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)),
            ) => Some(serde_json::to_value(event).expect("serialize terminal event")),
            _ => None,
        })
        .collect()
}

async fn assert_terminal_publication_follows_cleanup(point: GatePoint) {
    let (mut session, turn_context, rx) = make_session_and_context_with_rx().await;
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique test session"))
            .await;
    let gate = Arc::new(TerminalCleanupGate {
        point,
        armed: AtomicBool::new(true),
        entered: Notify::new(),
        release: Notify::new(),
    });
    let mut extensions =
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    extensions.thread_lifecycle_contributor(gate.clone());
    extensions.turn_lifecycle_contributor(gate.clone());
    Arc::get_mut(&mut session)
        .expect("unique test session")
        .services
        .extensions = Arc::new(extensions.build());
    let initial_status = session.agent_status.borrow().clone();

    let abort_owner = match point {
        GatePoint::ThreadIdle => {
            session
                .spawn_task(Arc::clone(&turn_context), Vec::new(), CompletingTask)
                .await
                .expect("first task should start");
            None
        }
        GatePoint::TurnAbort => {
            session
                .spawn_task(
                    Arc::clone(&turn_context),
                    Vec::new(),
                    NeverEndingTask {
                        kind: TaskKind::Regular,
                        listen_to_cancellation_token: true,
                    },
                )
                .await
                .expect("first task should start");
            Some(tokio::spawn({
                let session = Arc::clone(&session);
                async move { session.abort_all_tasks(TurnAbortReason::Interrupted).await }
            }))
        }
    };
    timeout(Duration::from_secs(2), gate.entered.notified())
        .await
        .expect("terminalizer must reach the deterministic cleanup gate");

    // The previous implementation has already enqueued its terminal here.
    // No sleep or scheduler-dependent event timeout is used to detect that.
    let events: Vec<EventMsg> = std::iter::from_fn(|| rx.try_recv().ok())
        .map(|event| event.msg)
        .collect();
    assert!(
        events
            .iter()
            .all(|event| !matches!(event, EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)))
    );
    let expected_flushes = match point {
        GatePoint::ThreadIdle => 2,
        GatePoint::TurnAbort => 3,
    };
    assert_eq!(
        (
            session.has_pending_admission_fence(),
            store.calls().await.flush_thread,
            session.agent_status.borrow().clone(),
        ),
        (true, expected_flushes, initial_status),
    );
    let persisted_before_release = persisted_terminals(&session).await;
    assert_eq!(persisted_before_release.len(), 1);
    assert!(
        session
            .drain_task_terminalizations_for_shutdown_except(/*excluded_identity*/ None)
            .now_or_never()
            .is_none(),
        "shutdown must still wait for the gated terminalizer"
    );
    let next_context = session
        .new_default_turn_with_sub_id("next-after-terminal".to_string())
        .await;
    session
        .spawn_task(Arc::clone(&next_context), Vec::new(), CompletingTask)
        .await
        .expect_err("cleanup must still reject admission before publication");

    gate.release.notify_one();
    let expected = match point {
        GatePoint::ThreadIdle => TerminalEventKind::TurnComplete,
        GatePoint::TurnAbort => TerminalEventKind::TurnAborted,
    };
    let terminal = recv_terminal_event(&rx, expected).await;
    assert_eq!(terminal.id, turn_context.sub_id);
    assert_eq!(
        persisted_before_release,
        vec![serde_json::to_value(&terminal.msg).expect("serialize delivered terminal")],
    );
    assert!(!session.has_pending_admission_fence());
    // Exercise real admission immediately, without retrying NotIdle or
    // polling a fence. This is the client-visible boundary under test.
    let next_id = next_context.sub_id.clone();
    session
        .spawn_task(next_context, Vec::new(), StartedThenWaitTask)
        .await
        .expect("terminal delivery must permit the next task immediately");
    let next_boundary = timeout(Duration::from_secs(2), async {
        loop {
            let event = rx.recv().await.expect("session event stream");
            if matches!(
                event.msg,
                EventMsg::TurnStarted(_) | EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
            ) {
                break event;
            }
        }
    })
    .await
    .expect("successor should publish its start");
    assert!(matches!(
        next_boundary.msg,
        EventMsg::TurnStarted(ref event) if event.turn_id == next_id
    ));
    if let Some(owner) = abort_owner {
        owner.await.expect("abort owner should finish");
    }
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    let next_terminal = recv_terminal_event(&rx, TerminalEventKind::TurnAborted).await;
    assert_eq!(next_terminal.id, next_id);
    assert_eq!(
        persisted_terminals(&session).await,
        vec![
            serde_json::to_value(terminal.msg).expect("serialize first terminal"),
            serde_json::to_value(next_terminal.msg).expect("serialize second terminal"),
        ],
    );
    assert!(
        std::iter::from_fn(|| rx.try_recv().ok()).all(|event| !matches!(
            event.msg,
            EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
        ))
    );
}

#[tokio::test]
async fn turn_complete_is_published_after_durable_cleanup_and_admission_release() {
    assert_terminal_publication_follows_cleanup(GatePoint::ThreadIdle).await;
}

#[tokio::test]
async fn turn_aborted_is_published_after_durable_cleanup_and_admission_release() {
    assert_terminal_publication_follows_cleanup(GatePoint::TurnAbort).await;
}
