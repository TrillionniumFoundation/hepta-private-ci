use super::*;
use crate::agent::AgentStatus;
use crate::session::TurnInput;
use crate::session::handlers;
use crate::session::session_loop_termination_from_handle;
use crate::session::tests::make_session_and_context_with_rx;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalizationKind;
use codex_features::Feature;
use codex_protocol::AgentPath;
use codex_protocol::ResponseItemId;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::time::Duration;
use test_case::test_case;
use tokio::sync::watch;

fn message() -> InterAgentCommunication {
    let mut message = InterAgentCommunication::new_encrypted(
        AgentPath::root(),
        AgentPath::try_from("/root/worker").expect("recipient path"),
        Vec::new(),
        "test-encrypted-mailbox-payload".to_string(),
        false,
    );
    message.id = Some(ResponseItemId::with_suffix("msg", "mailbox-retry"));
    message.set_turn_id_if_missing("sender-turn");
    message
}

fn trace() -> Option<W3cTraceContext> {
    Some(W3cTraceContext {
        traceparent: Some("00-00000000000000000000000000000011-0000000000000022-01".to_string()),
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

fn io(
    tx_sub: async_channel::Sender<Submission>,
    rx_event: async_channel::Receiver<Event>,
    actor: tokio::task::JoinHandle<()>,
) -> SessionIo {
    SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    }
}

async fn submit(io: &SessionIo, session: &Session) -> CodexResult<String> {
    io.submit_mailbox_after_terminalization(
        session,
        message(),
        trace(),
        Some("parent-turn".to_string()),
        Some("root-turn".to_string()),
    )
    .await
}

async fn route(session: &Arc<Session>, submission: Submission) -> String {
    assert_eq!(submission.trace, trace());
    assert_eq!(submission.parent_turn_id.as_deref(), Some("parent-turn"));
    assert_eq!(submission.root_turn_id.as_deref(), Some("root-turn"));
    let Op::InterAgentCommunication { communication } = submission.op else {
        panic!("expected the ordered mailbox operation");
    };
    assert_eq!(
        communication,
        message(),
        "payload, ciphertext, IDs and metadata survive retries"
    );
    let id = submission.id;
    handlers::inter_agent_communication(
        session,
        id.clone(),
        communication,
        submission.parent_turn_id,
        submission.root_turn_id,
    )
    .await;
    id
}

async fn assert_accepted_once(session: &Session) {
    let (items, parent, root) = session.input_queue.drain_mailbox_input_items().await;
    assert_eq!(items, vec![TurnInput::InterAgentCommunication(message())]);
    assert_eq!(
        parent, None,
        "non-triggering mail must not select a new turn parent"
    );
    assert_eq!(
        root, None,
        "non-triggering mail must not select a new turn root"
    );
    assert!(!session.input_queue.has_pending_mailbox_items().await);
}

async fn assert_rejected(io: &SessionIo, id: &str) {
    let event = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let event = io.rx_event.recv().await.expect("event channel");
            if event.id == id {
                break event;
            }
        }
    })
    .await
    .expect("mailbox rejection event");
    assert!(matches!(event.msg, EventMsg::Error(_)));
    while let Ok(event) = io.rx_event.try_recv() {
        assert_ne!(event.id, id, "one final rejection per submission");
    }
}

#[test_case(false, false; "ordinary_finish")]
#[test_case(true, false; "recovery_enabled")]
#[test_case(false, true; "retired_before_wait")]
#[test_case(true, true; "recovery_retired_before_wait")]
#[tokio::test]
async fn mailbox_finish_retry_preserves_input_and_actor_progress(
    recovery: bool,
    complete_before_wait: bool,
) {
    let (mut session, _context, rx_event) = make_session_and_context_with_rx().await;
    if recovery {
        Arc::get_mut(&mut session)
            .expect("fresh session")
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable recovery");
    }
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let (first_tx, first_rx) = oneshot::channel();
    let (control_tx, control_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        let events = rx_event.clone();
        let fence = Arc::clone(&fence);
        async move {
            let first = rx_sub.recv().await.expect("initial mail");
            let id = first.id.clone();
            first_tx.send(id.clone()).expect("first attempt observer");
            let control = rx_sub.recv().await.expect("control queued after mail");
            assert_eq!(route(&session, first).await, id);
            assert!(!session.input_queue.has_pending_mailbox_items().await);
            while let Ok(event) = events.try_recv() {
                assert_ne!(event.id, id, "deferral has no error or completion event");
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
                route(&session, rx_sub.recv().await.expect("retried mail")).await,
                id
            );
            assert!(
                rx_sub.try_recv().is_err(),
                "accepted mail must not be resubmitted"
            );
        }
    });
    let io = Arc::new(io(tx_sub, rx_event, actor));
    let caller = tokio::spawn({
        let io = Arc::clone(&io);
        let session = Arc::clone(&session);
        async move { submit(&io, &session).await }
    });
    let id = first_rx.await.expect("first attempt");
    io.submit(Op::Interrupt).await.expect("control enqueue");
    tokio::time::timeout(Duration::from_secs(2), control_rx)
        .await
        .expect("actor remains available")
        .expect("control received");
    let returned = tokio::time::timeout(Duration::from_secs(2), caller)
        .await
        .expect("retry deadline")
        .expect("caller joined")
        .expect("accepted mail");
    assert_eq!(returned, id);
    assert_accepted_once(&session).await;
    while let Ok(event) = io.rx_event.try_recv() {
        assert_ne!(event.id, id, "acceptance does not publish an error");
    }
    assert!(
        session
            .pending_mailbox_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
}

#[tokio::test]
async fn mailbox_after_already_retired_finish_is_admitted_once() {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    finish_fence(&session, &fence);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("mail")).await;
            assert!(rx_sub.try_recv().is_err());
        }
    });
    let io = io(tx_sub, rx_event, actor);
    tokio::time::timeout(Duration::from_secs(2), submit(&io, &session))
        .await
        .expect("retired finish does not fence mail")
        .expect("accepted mail");
    assert_accepted_once(&session).await;
}

#[test_case(TaskTerminalizationKind::Abort, false; "abort")]
#[test_case(TaskTerminalizationKind::Suspend, false; "suspend")]
#[test_case(TaskTerminalizationKind::Finish, true; "shutdown")]
#[tokio::test]
async fn mailbox_non_finish_fences_remain_rejected(kind: TaskTerminalizationKind, shutdown: bool) {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, kind);
    if shutdown {
        session.begin_shutdown();
    }
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("mail")).await;
        }
    });
    let io = io(tx_sub, rx_event, actor);
    let id = tokio::time::timeout(Duration::from_secs(2), submit(&io, &session))
        .await
        .expect("rejection must not wait for an abort or suspension")
        .expect("queued mail ID");
    assert_rejected(&io, &id).await;
    assert!(!session.input_queue.has_pending_mailbox_items().await);
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn mailbox_retry_revalidates_a_new_abort_fence() {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let finish = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let (abort_tx, abort_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            let id = route(&session, rx_sub.recv().await.expect("initial mail")).await;
            finish_fence(&session, &finish);
            let abort = install_fence(&session, TaskTerminalizationKind::Abort);
            assert_eq!(
                route(&session, rx_sub.recv().await.expect("retried mail")).await,
                id
            );
            assert!(abort_tx.send(abort).is_ok(), "abort observer");
        }
    });
    let io = io(tx_sub, rx_event, actor);
    let id = tokio::time::timeout(Duration::from_secs(2), submit(&io, &session))
        .await
        .expect("retry deadline")
        .expect("mail ID");
    assert_rejected(&io, &id).await;
    assert!(!session.input_queue.has_pending_mailbox_items().await);
    let abort = abort_rx.await.expect("new abort fence");
    assert!(!abort.is_complete());
    finish_fence(&session, &abort);
}

#[tokio::test]
async fn cancelled_mailbox_wait_cannot_enqueue_after_finish() {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let (deferred_tx, deferred_rx) = oneshot::channel();
    let (stop_tx, stop_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("initial mail")).await;
            deferred_tx.send(()).expect("deferred observer");
            stop_rx.await.expect("stop actor");
            assert!(
                rx_sub.try_recv().is_err(),
                "cancelled caller must not resubmit"
            );
        }
    });
    let io = Arc::new(io(tx_sub, rx_event, actor));
    let caller = tokio::spawn({
        let io = Arc::clone(&io);
        let session = Arc::clone(&session);
        async move { submit(&io, &session).await }
    });
    deferred_rx.await.expect("deferred mail");
    caller.abort();
    assert!(caller.await.expect_err("cancelled caller").is_cancelled());
    assert!(
        session
            .pending_mailbox_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(!fence.is_complete());
    assert!(!session.input_queue.has_pending_mailbox_items().await);
    finish_fence(&session, &fence);
    stop_tx.send(()).expect("release actor");
    io.session_loop_termination.clone().await;
    assert!(!session.input_queue.has_pending_mailbox_items().await);
}

#[test_case(false; "before_ack")]
#[test_case(true; "after_finish_ack")]
#[tokio::test]
async fn mailbox_wait_ends_when_actor_exits(reply_before_exit: bool) {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            let submission = rx_sub.recv().await.expect("mail");
            if reply_before_exit {
                route(&session, submission).await;
            }
        }
    });
    let io = io(tx_sub, rx_event, actor);
    let error = tokio::time::timeout(Duration::from_secs(2), submit(&io, &session))
        .await
        .expect("actor exit releases caller")
        .expect_err("actor terminated");
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InternalAgentDied
    ));
    assert!(
        session
            .pending_mailbox_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(!session.input_queue.has_pending_mailbox_items().await);
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn unregistered_mailbox_submission_does_not_bypass_finish() {
    let (session, _context, events) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    handlers::inter_agent_communication(
        &session,
        "unregistered-mail".to_string(),
        message(),
        None,
        None,
    )
    .await;
    let event = events.recv().await.expect("rejection");
    assert_eq!(event.id, "unregistered-mail");
    assert!(matches!(event.msg, EventMsg::Error(_)));
    assert!(!session.input_queue.has_pending_mailbox_items().await);
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}
