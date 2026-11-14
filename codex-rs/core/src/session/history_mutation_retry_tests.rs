use super::*;
use crate::agent::AgentStatus;
use crate::rollout::recorder::RolloutRecorder;
use crate::session::TurnInput;
use crate::session::handlers;
use crate::session::session_loop_termination_from_handle;
use crate::session::tests::attach_thread_persistence;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::tests::raw_history_items;
use crate::session::turn_context::TurnContext;
use crate::state::ActiveTurn;
use crate::state::StartTransitionCompletion;
use crate::state::TaskKind;
use crate::state::TaskTerminalizationKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use crate::tasks::TaskSpawnOutcome;
use codex_features::Feature;
use codex_history::InitialHistory;
use codex_history::RolloutItem;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::TurnAbortReason;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use test_case::test_case;
use tokio::sync::Notify;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;

fn trace() -> Option<W3cTraceContext> {
    Some(W3cTraceContext {
        traceparent: Some("00-00000000000000000000000000000033-0000000000000044-01".to_string()),
        tracestate: None,
    })
}

fn install_fence(
    session: &Session,
    kind: TaskTerminalizationKind,
) -> Arc<StartTransitionCompletion> {
    let completion = StartTransitionCompletion::new();
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalization registry")
        .push((
            Arc::new(()),
            Arc::clone(&completion),
            kind,
            None,
            None,
            None,
        ));
    completion
}

fn finish_fence(session: &Session, completion: &Arc<StartTransitionCompletion>) {
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalization registry")
        .retain(|(_, current, _, _, _, _)| !Arc::ptr_eq(current, completion));
    completion.complete();
}

async fn route(session: &Arc<Session>, submission: Submission) -> String {
    assert_eq!(submission.trace, trace());
    assert_eq!(submission.parent_turn_id, None);
    assert_eq!(submission.root_turn_id, None);
    let id = submission.id;
    let handled = match submission.op {
        Op::ThreadRollback { num_turns } => {
            handlers::thread_rollback(session, id.clone(), num_turns).await
        }
        Op::Compact => handlers::compact(session, id.clone()).await,
        _ => panic!("expected an ordered history mutation"),
    };
    if let HistoryMutationHandling::Complete = handled {
        session.pending_history_mutation_retries.complete(&id);
    }
    id
}

#[test_case(false, false; "ordinary_finish")]
#[test_case(true, false; "recovery_enabled")]
#[test_case(false, true; "finish_before_wait")]
#[tokio::test]
async fn rollback_finish_retry_preserves_identity_and_mutates_once(
    recovery_enabled: bool,
    complete_before_wait: bool,
) {
    let (mut session, context, rx_event) = make_session_and_context_with_rx().await;
    if recovery_enabled {
        Arc::get_mut(&mut session)
            .expect("fresh session")
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable recovery");
    }
    let rollout_path =
        attach_thread_persistence(Arc::get_mut(&mut session).expect("fresh session")).await;
    let messages = ["retain this turn", "roll back this turn"].map(|text| ResponseItem::Message {
        id: None,
        role: "user".to_string(),
        content: vec![ContentItem::InputText {
            text: text.to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    });
    session
        .record_conversation_items(context.as_ref(), &messages)
        .await;
    let retained_item = raw_history_items(&session.clone_history().await)
        .into_iter()
        .find(|item| matches!(item, ResponseItem::Message { role, .. } if role == "user"))
        .expect("canonical first user message");
    let epoch = session.turn_epoch.load(Ordering::Acquire);
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(/*cap*/ 4);
    let (deferred_tx, deferred_rx) = oneshot::channel();
    let (control_tx, control_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        let events = rx_event.clone();
        let fence = Arc::clone(&fence);
        async move {
            let first = rx_sub.recv().await.expect("initial rollback");
            let id = first.id.clone();
            deferred_tx.send(id.clone()).expect("initial observer");
            let control = rx_sub.recv().await.expect("control queued after rollback");
            assert_eq!(route(&session, first).await, id);
            assert_eq!(session.turn_epoch.load(Ordering::Acquire), epoch);
            while let Ok(event) = events.try_recv() {
                assert_ne!(event.id, id, "a deferred rollback cannot publish a result");
            }
            if complete_before_wait {
                finish_fence(&session, &fence);
            }
            assert!(matches!(control.op, Op::Interrupt));
            control_tx.send(()).expect("control observer");
            if !complete_before_wait {
                finish_fence(&session, &fence);
            }
            assert_eq!(
                route(&session, rx_sub.recv().await.expect("retried rollback")).await,
                id
            );
        }
    });
    let io = Arc::new(SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    });
    let caller = tokio::spawn({
        let io = Arc::clone(&io);
        let session = Arc::clone(&session);
        async move {
            io.submit_history_mutation_after_terminalization(
                &session,
                HistoryMutation::Rollback { num_turns: 1 },
                trace(),
            )
            .await
        }
    });
    let id = deferred_rx.await.expect("first routing decision");
    io.submit(Op::Interrupt).await.expect("control enqueue");
    tokio::time::timeout(Duration::from_secs(/*secs*/ 2), control_rx)
        .await
        .expect("the actor must remain available")
        .expect("control processed");
    let returned = tokio::time::timeout(Duration::from_secs(/*secs*/ 5), caller)
        .await
        .expect("rollback retry deadline")
        .expect("caller join")
        .expect("rollback routing");
    assert_eq!(returned, id);
    let mut results = Vec::new();
    while let Ok(event) = io.rx_event.try_recv() {
        if event.id == id {
            results.push(event.msg);
        }
    }
    let (info, rate_limits) = session.state.lock().await.token_info_and_rate_limits();
    assert_eq!(
        serde_json::to_value(results).expect("serialize actual results"),
        serde_json::to_value(vec![
            EventMsg::TokenCount(codex_protocol::protocol::TokenCountEvent { info, rate_limits }),
            EventMsg::ThreadRolledBack(codex_protocol::protocol::ThreadRolledBackEvent {
                num_turns: 1
            },),
        ])
        .expect("serialize expected results")
    );
    let history = raw_history_items(&session.clone_history().await);
    let user_messages = history
        .into_iter()
        .filter(|item| {
            matches!(item,
                ResponseItem::Message { role, .. } if role == "user"
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(user_messages, vec![retained_item]);
    session
        .flush_rollout()
        .await
        .expect("flush final rollback marker");
    let InitialHistory::Resumed(persisted) = RolloutRecorder::get_rollout_history(&rollout_path)
        .await
        .expect("read persisted history")
    else {
        panic!("persistent fixture");
    };
    let markers = persisted
        .history
        .iter()
        .filter(|item| matches!(item, RolloutItem::EventMsg(EventMsg::ThreadRolledBack(_))))
        .count();
    assert_eq!(markers, 1);
}

#[test_case(HistoryMutation::Rollback { num_turns: 1 }, TaskTerminalizationKind::Abort, false; "rollback_abort")]
#[test_case(HistoryMutation::Rollback { num_turns: 1 }, TaskTerminalizationKind::Suspend, false; "rollback_suspend")]
#[test_case(HistoryMutation::Rollback { num_turns: 1 }, TaskTerminalizationKind::Finish, true; "rollback_shutdown")]
#[test_case(HistoryMutation::Compact, TaskTerminalizationKind::Abort, false; "compact_abort")]
#[test_case(HistoryMutation::Compact, TaskTerminalizationKind::Suspend, false; "compact_suspend")]
#[test_case(HistoryMutation::Compact, TaskTerminalizationKind::Finish, true; "compact_shutdown")]
#[tokio::test]
async fn non_finish_history_mutations_remain_rejected(
    mutation: HistoryMutation,
    kind: TaskTerminalizationKind,
    shutting_down: bool,
) {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, kind);
    let epoch = session.turn_epoch.load(Ordering::Acquire);
    if shutting_down {
        session.begin_shutdown();
    }
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(/*cap*/ 4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("mutation")).await;
        }
    });
    let io = SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    };
    let id = tokio::time::timeout(
        Duration::from_secs(/*secs*/ 2),
        io.submit_history_mutation_after_terminalization(&session, mutation, trace()),
    )
    .await
    .expect("rejection must not wait")
    .expect("correlation ID");
    let event = io.rx_event.recv().await.expect("final rejection");
    assert_eq!(event.id, id);
    assert!(matches!(event.msg, EventMsg::Error(_)));
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), epoch);
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[test_case(HistoryMutation::Rollback { num_turns: 1 }; "rollback")]
#[test_case(HistoryMutation::Compact; "compact")]
#[tokio::test]
async fn cancelled_history_mutation_keeps_finish_owner_and_does_not_resubmit(
    mutation: HistoryMutation,
) {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let epoch = session.turn_epoch.load(Ordering::Acquire);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(/*cap*/ 4);
    let (deferred_tx, deferred_rx) = oneshot::channel();
    let (stop_tx, stop_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("mutation")).await;
            deferred_tx.send(()).expect("deferred observer");
            let _ = stop_rx.await;
            assert!(
                rx_sub.try_recv().is_err(),
                "cancelled mutation must not resubmit"
            );
        }
    });
    let io = Arc::new(SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    });
    let caller = tokio::spawn({
        let session = Arc::clone(&session);
        let io = Arc::clone(&io);
        async move {
            io.submit_history_mutation_after_terminalization(&session, mutation, trace())
                .await
        }
    });
    deferred_rx.await.expect("deferred attempt");
    caller.abort();
    assert!(caller.await.expect_err("cancelled caller").is_cancelled());
    assert!(
        session
            .pending_history_mutation_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), epoch);
    assert!(!fence.is_complete());
    stop_tx.send(()).expect("stop actor");
    io.session_loop_termination.clone().await;
    finish_fence(&session, &fence);
}

#[test_case(HistoryMutation::Rollback { num_turns: 1 }, false; "rollback_before_ack")]
#[test_case(HistoryMutation::Rollback { num_turns: 1 }, true; "rollback_after_ack")]
#[test_case(HistoryMutation::Compact, false; "compact_before_ack")]
#[test_case(HistoryMutation::Compact, true; "compact_after_ack")]
#[tokio::test]
async fn history_mutation_wait_ends_with_actor_death(mutation: HistoryMutation, acknowledge: bool) {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(/*cap*/ 4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            let submission = rx_sub.recv().await.expect("mutation");
            if acknowledge {
                route(&session, submission).await;
            }
        }
    });
    let io = SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    };
    let error = tokio::time::timeout(
        Duration::from_secs(/*secs*/ 2),
        io.submit_history_mutation_after_terminalization(&session, mutation, trace()),
    )
    .await
    .expect("actor death releases waiter")
    .expect_err("dead actor");
    assert!(matches!(
        error.details(),
        codex_protocol::error::CodexErrorDetails::InternalAgentDied
    ));
    assert!(
        session
            .pending_history_mutation_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn rollback_reservation_captures_finish_before_consuming_authority() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let first = install_fence(&session, TaskTerminalizationKind::Finish);
    let second = install_fence(&session, TaskTerminalizationKind::Finish);
    let epoch = session.turn_epoch.load(Ordering::Acquire);
    let HistoryMutationReservation::Finishing(fences) = session
        .reserve_history_mutation_or_finish()
        .await
        .expect("typed reservation")
    else {
        panic!("two exact Finish owners");
    };
    assert_eq!(fences.len(), 2);
    assert!(Arc::ptr_eq(&fences[0], &first));
    assert!(Arc::ptr_eq(&fences[1], &second));
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), epoch);
    assert!(session.active_turn.lock().await.is_none());
    finish_fence(&session, &first);
    finish_fence(&session, &second);
    for fence in fences {
        fence.wait().await;
    }
    let HistoryMutationReservation::Reserved(reserved) = session
        .reserve_history_mutation_or_finish()
        .await
        .expect("fresh reservation")
    else {
        panic!("retired Finish must not reject");
    };
    assert!(session.turn_epoch.load(Ordering::Acquire) > epoch);
    session.settle_and_clear_reserved_idle_turn(&reserved).await;
    // A detached start owner can outlive the cleared active slot without
    // installing a task-terminalization entry. It still owns its side effects.
    let start_completion = StartTransitionCompletion::new();
    session
        .pending_start_transition_completions
        .lock()
        .expect("start registry")
        .push((
            Arc::new(()),
            Arc::clone(&start_completion),
            Arc::new(Mutex::new(None)),
        ));
    let epoch_before_blocked = session.turn_epoch.load(Ordering::Acquire);
    assert!(session.has_pending_start_transition());
    assert!(!session.has_pending_task_terminalization());
    assert!(session.active_turn.lock().await.is_none());
    assert!(matches!(
        session
            .reserve_history_mutation_or_finish()
            .await
            .expect("detached start owner"),
        HistoryMutationReservation::Busy
    ));
    assert_eq!(
        session.turn_epoch.load(Ordering::Acquire),
        epoch_before_blocked
    );
    assert!(!start_completion.is_complete());
    session
        .pending_start_transition_completions
        .lock()
        .expect("start registry")
        .retain(|(_, current, _)| !Arc::ptr_eq(current, &start_completion));
    start_completion.complete();
    *session.active_turn.lock().await = Some(ActiveTurn::default());
    assert!(matches!(
        session
            .reserve_history_mutation_or_finish()
            .await
            .expect("active reservation"),
        HistoryMutationReservation::Busy
    ));
}

struct PendingCompactTask {
    starts: Arc<AtomicUsize>,
    started: Arc<Notify>,
}

impl SessionTask for PendingCompactTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Compact
    }
    fn span_name(&self) -> &'static str {
        "history_retry.pending_compact"
    }
    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        self.starts.fetch_add(/*val*/ 1, Ordering::SeqCst);
        self.started.notify_one();
        cancellation_token.cancelled().await;
        Err(CodexErr::TurnAborted)
    }
}

#[tokio::test]
async fn compact_start_keeps_finish_fences_and_existing_active_replacement() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let starts = Arc::new(AtomicUsize::new(/*v*/ 0));
    let started = Arc::new(Notify::new());
    let task = || PendingCompactTask {
        starts: Arc::clone(&starts),
        started: Arc::clone(&started),
    };
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let context = session
        .new_default_turn_with_sub_id("compact-first".to_string())
        .await;
    let outcome = session
        .spawn_task_with_finish_retry(Arc::clone(&context), Vec::new(), task())
        .await
        .expect("typed compact admission");
    let TaskSpawnOutcome::RetryAfterFinish { fences, .. } = outcome else {
        panic!("exact Finish");
    };
    assert_eq!(fences.len(), 1);
    assert!(Arc::ptr_eq(&fences[0], &fence));
    assert_eq!(starts.load(Ordering::SeqCst), 0);
    finish_fence(&session, &fence);
    assert!(matches!(
        session
            .spawn_task_with_finish_retry(context, Vec::new(), task())
            .await
            .expect("compact starts after Finish"),
        TaskSpawnOutcome::Started
    ));
    tokio::time::timeout(Duration::from_secs(/*secs*/ 2), started.notified())
        .await
        .expect("first task runs");
    let replacement = session
        .new_default_turn_with_sub_id("compact-replacement".to_string())
        .await;
    assert!(matches!(
        session
            .spawn_task_with_finish_retry(replacement, Vec::new(), task())
            .await
            .expect("existing active replacement is preserved"),
        TaskSpawnOutcome::Started
    ));
    tokio::time::timeout(Duration::from_secs(/*secs*/ 2), started.notified())
        .await
        .expect("replacement runs");
    assert_eq!(starts.load(Ordering::SeqCst), 2);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}
