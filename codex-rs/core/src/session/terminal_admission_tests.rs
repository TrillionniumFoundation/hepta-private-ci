use super::*;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_protocol::turn_input::NotSubmittedReason;
use pretty_assertions::assert_eq;
use std::sync::OnceLock;
use std::sync::Weak;

type IdleObservation = (ThreadIdleCause, bool);

struct RecheckProbe {
    session: OnceLock<Weak<Session>>,
    idle: async_channel::Sender<IdleObservation>,
    recheck: async_channel::Sender<IdleObservation>,
    dispatch: async_channel::Sender<TurnInputSubmission>,
    idle_gate: std::sync::Mutex<Option<Arc<Notify>>>,
    recheck_gate: std::sync::Mutex<Option<Arc<Notify>>>,
    start_entered: std::sync::Mutex<Option<Arc<Notify>>>,
}

impl ThreadLifecycleContributor<crate::config::Config> for RecheckProbe {
    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let session = self.session.get().unwrap().upgrade().unwrap();
            self.idle
                .send((input.cause, session.has_pending_admission_fence()))
                .await
                .unwrap();
            let gate = self.idle_gate.lock().unwrap().take();
            if let Some(gate) = gate {
                gate.notified().await;
            }
        })
    }

    fn on_thread_admission_recheck<'a>(
        &'a self,
        input: ThreadIdleInput<'a>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let session = self.session.get().unwrap().upgrade().unwrap();
            self.recheck
                .send((input.cause, session.has_pending_admission_fence()))
                .await
                .unwrap();
            let gate = self.recheck_gate.lock().unwrap().take();
            if let Some(gate) = gate {
                gate.notified().await;
                self.dispatch
                    .send(try_ordinary_start(&session).await)
                    .await
                    .unwrap();
            }
        })
    }
}

impl codex_extension_api::TurnLifecycleContributor for RecheckProbe {
    fn on_turn_start<'a>(
        &'a self,
        _input: codex_extension_api::TurnStartInput<'a>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let entered = self.start_entered.lock().unwrap().clone();
            if let Some(entered) = entered {
                entered.notify_one();
                std::future::pending::<()>().await;
            }
        })
    }
}

struct RecheckHarness {
    session: Arc<Session>,
    context: Arc<TurnContext>,
    probe: Arc<RecheckProbe>,
    idle: async_channel::Receiver<IdleObservation>,
    recheck: async_channel::Receiver<IdleObservation>,
    dispatch: async_channel::Receiver<TurnInputSubmission>,
    _events: crate::event_delivery::EventReceiver,
}

async fn recheck_harness() -> RecheckHarness {
    let (mut session, context, events) = make_session_and_context_with_rx().await;
    attach_in_memory_thread_store(Arc::get_mut(&mut session).unwrap()).await;
    let (idle_tx, idle) = async_channel::unbounded();
    let (recheck_tx, recheck) = async_channel::unbounded();
    let (dispatch_tx, dispatch) = async_channel::unbounded();
    let probe = Arc::new(RecheckProbe {
        session: OnceLock::new(),
        idle: idle_tx,
        recheck: recheck_tx,
        dispatch: dispatch_tx,
        idle_gate: std::sync::Mutex::new(None),
        recheck_gate: std::sync::Mutex::new(None),
        start_entered: std::sync::Mutex::new(None),
    });
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::new();
    builder.thread_lifecycle_contributor(probe.clone());
    builder.turn_lifecycle_contributor(probe.clone());
    Arc::get_mut(&mut session).unwrap().services.extensions = Arc::new(builder.build());
    probe.session.set(Arc::downgrade(&session)).unwrap();
    RecheckHarness {
        session,
        context,
        probe,
        idle,
        recheck,
        dispatch,
        _events: events,
    }
}

async fn receive<T>(receiver: &async_channel::Receiver<T>) -> T {
    timeout(StdDuration::from_secs(/*secs*/ 2), receiver.recv())
        .await
        .expect("lifecycle observation should arrive")
        .expect("lifecycle receiver should remain open")
}

async fn assert_no_recheck(receiver: &async_channel::Receiver<IdleObservation>) {
    assert!(
        timeout(StdDuration::from_millis(/*millis*/ 100), receiver.recv())
            .await
            .is_err(),
        "this path must not request automatic admission"
    );
}

async fn try_ordinary_start(session: &Arc<Session>) -> TurnInputSubmission {
    crate::session::turn_input::handle(
        session,
        TurnInputRequest::new(SubmittedTurnInput::UserInput {
            content: vec![UserInput::Text {
                text: "queued follow-up".to_string(),
                text_elements: Vec::new(),
            }],
            client_id: None,
        }),
        TurnInputMode::StartIfIdle,
        "queue-recheck-test".to_string(),
    )
    .await
    .expect("ordinary admission request should be valid")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn finish_recheck_follows_fenced_housekeeping_and_preserves_cause() {
    for cause in [ThreadIdleCause::Completed, ThreadIdleCause::Failed] {
        let harness = recheck_harness().await;
        let release = Arc::new(Notify::new());
        *harness.probe.idle_gate.lock().unwrap() = Some(Arc::clone(&release));
        if cause == ThreadIdleCause::Completed {
            harness
                .session
                .spawn_task(Arc::clone(&harness.context), Vec::new(), CompletingTask)
                .await
                .unwrap();
        } else {
            harness
                .session
                .spawn_task(Arc::clone(&harness.context), Vec::new(), PanickingTask)
                .await
                .unwrap();
        }
        assert_eq!(receive(&harness.idle).await, (cause, true));
        assert!(harness.recheck.is_empty());
        assert_eq!(
            try_ordinary_start(&harness.session).await,
            TurnInputSubmission::NotSubmitted {
                reason: NotSubmittedReason::NotIdle,
            }
        );
        release.notify_one();
        assert_eq!(receive(&harness.recheck).await, (cause, false));
        assert!(harness.idle.is_empty(), "housekeeping must run only once");
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abort_recheck_preserves_deferred_idle_and_does_not_invent_one_for_replacement() {
    for deferred in [true, false] {
        let harness = recheck_harness().await;
        harness
            .session
            .spawn_task(
                Arc::clone(&harness.context),
                Vec::new(),
                NeverEndingTask {
                    kind: TaskKind::Regular,
                    listen_to_cancellation_token: true,
                },
            )
            .await
            .unwrap();
        if deferred {
            let state = Arc::clone(
                &harness
                    .session
                    .active_turn
                    .lock()
                    .await
                    .as_ref()
                    .unwrap()
                    .turn_state,
            );
            harness
                .session
                .abort_turn_if_active_for_guardian(
                    &harness.context.sub_id,
                    &state,
                    TurnAbortReason::Interrupted,
                )
                .await;
            assert_eq!(
                receive(&harness.idle).await,
                (ThreadIdleCause::Interrupted, true)
            );
            assert_eq!(
                receive(&harness.recheck).await,
                (ThreadIdleCause::Interrupted, false)
            );
        } else {
            harness
                .session
                .abort_all_tasks(TurnAbortReason::Replaced)
                .await;
            assert!(!harness.session.has_pending_admission_fence());
            assert!(harness.idle.is_empty());
            assert_no_recheck(&harness.recheck).await;
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn start_transition_recheck_follows_exact_completion_and_respects_shutdown() {
    for shutdown in [false, true] {
        let harness = recheck_harness().await;
        let entered = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        *harness.probe.start_entered.lock().unwrap() = Some(Arc::clone(&entered));
        *harness.probe.idle_gate.lock().unwrap() = Some(Arc::clone(&release));
        let start = tokio::spawn({
            let session = Arc::clone(&harness.session);
            let context = Arc::clone(&harness.context);
            async move {
                session
                    .spawn_task(context, Vec::new(), CompletingTask)
                    .await
            }
        });
        timeout(StdDuration::from_secs(/*secs*/ 2), entered.notified())
            .await
            .unwrap();
        let (state, completion) = {
            let active = harness.session.active_turn.lock().await;
            let active = active.as_ref().unwrap();
            (
                Arc::clone(&active.turn_state),
                Arc::clone(&active.start_transition.as_ref().unwrap().completion),
            )
        };
        if shutdown {
            harness.session.begin_shutdown();
        }
        harness
            .session
            .abort_turn_if_active_for_guardian(
                &harness.context.sub_id,
                &state,
                TurnAbortReason::Interrupted,
            )
            .await;
        start.abort();
        let _ = start.await;
        assert_eq!(
            receive(&harness.idle).await,
            (ThreadIdleCause::Interrupted, true)
        );
        assert!(harness.recheck.is_empty());
        assert!(!completion.is_complete());
        release.notify_one();
        timeout(StdDuration::from_secs(/*secs*/ 2), completion.wait())
            .await
            .unwrap();
        assert!(!harness.session.has_pending_admission_fence());
        if shutdown {
            assert_no_recheck(&harness.recheck).await;
        } else {
            assert_eq!(
                receive(&harness.recheck).await,
                (ThreadIdleCause::Interrupted, false)
            );
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn recheck_losing_to_a_new_owner_uses_ordinary_admission_and_gets_a_later_hint() {
    let harness = recheck_harness().await;
    let release = Arc::new(Notify::new());
    *harness.probe.recheck_gate.lock().unwrap() = Some(Arc::clone(&release));
    harness
        .session
        .spawn_task(Arc::clone(&harness.context), Vec::new(), CompletingTask)
        .await
        .unwrap();
    assert_eq!(
        receive(&harness.idle).await,
        (ThreadIdleCause::Completed, true)
    );
    assert_eq!(
        receive(&harness.recheck).await,
        (ThreadIdleCause::Completed, false)
    );
    // Reuse the protocol id/context deliberately: only the new physical owner
    // and ordinary admission guard decide whether this attempt may start.
    harness
        .session
        .spawn_task(
            Arc::clone(&harness.context),
            Vec::new(),
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: true,
            },
        )
        .await
        .unwrap();
    release.notify_one();
    assert_eq!(
        receive(&harness.dispatch).await,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        }
    );
    harness
        .session
        .on_task_finished(Arc::clone(&harness.context), Ok(None))
        .await;
    assert_eq!(
        receive(&harness.idle).await,
        (ThreadIdleCause::Completed, true)
    );
    assert_eq!(
        receive(&harness.recheck).await,
        (ThreadIdleCause::Completed, false)
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn suspension_closes_admission_without_a_recheck() {
    let harness = recheck_harness().await;
    harness
        .session
        .spawn_task(
            Arc::clone(&harness.context),
            Vec::new(),
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: true,
            },
        )
        .await
        .unwrap();
    let outcome = crate::session::turn_suspension::suspend_turn_and_shutdown_for_test(
        &harness.session,
        "queue-suspend-test".to_string(),
    )
    .await
    .unwrap();
    assert_eq!(
        outcome,
        codex_protocol::turn_input::SuspendTurnOutcome::Suspended {
            turn_id: harness.context.sub_id.clone(),
        }
    );
    assert!(harness.session.shutdown_started());
    assert!(!harness.session.has_pending_admission_fence());
    assert!(harness.idle.is_empty());
    assert_no_recheck(&harness.recheck).await;
}
