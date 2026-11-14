use super::*;
use crate::agent::AgentStatus;
use crate::session::session_loop_termination_from_handle;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::turn_input;
use crate::user_message_admission::PendingUserMessageAdmissionState;
use crate::user_message_admission::UserMessageAdmission;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::Submission;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::W3cTraceContext;
use codex_protocol::turn_input::TurnInput;
use codex_protocol::user_input::UserInput;
use pretty_assertions::assert_eq;
use std::time::Duration;
use test_case::test_case;
use tokio::sync::oneshot;
use tokio::sync::watch;

fn request() -> TurnInputRequest {
    TurnInputRequest::new(TurnInput::UserInput {
        content: vec![UserInput::Text {
            text: "one exact user message".to_string(),
            text_elements: Vec::new(),
        }],
        client_id: Some("finish-retry-client-message".to_string()),
    })
    .with_trace(Some(W3cTraceContext {
        traceparent: Some("00-00000000000000000000000000000011-0000000000000022-01".to_string()),
        tracestate: None,
    }))
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

async fn route(session: &Arc<Session>, sub: Submission, expected_id: &str) -> TurnInputSubmission {
    assert_eq!(sub.id, expected_id);
    let Op::TurnInput {
        request: actual,
        mode,
        reply,
    } = sub.op
    else {
        panic!("expected ordered turn-input operation");
    };
    let expected = request();
    assert_eq!(actual.input, expected.input);
    assert_eq!(actual.thread_settings, expected.thread_settings);
    assert_eq!(actual.additional_context, expected.additional_context);
    assert_eq!(
        actual.responsesapi_client_metadata,
        expected.responsesapi_client_metadata
    );
    assert_eq!(
        actual.start.final_output_json_schema,
        expected.start.final_output_json_schema
    );
    assert_eq!(actual.start.parent_turn_id, expected.start.parent_turn_id);
    assert_eq!(actual.start.root_turn_id, expected.start.root_turn_id);
    assert_eq!(sub.trace, expected.trace);
    let result = turn_input::handle(session, *actual, mode, sub.id)
        .await
        .expect("turn-input routing");
    let returned = result.clone();
    let _ = reply.send(Ok(result));
    returned
}

#[test_case(false; "completion_after_reply")]
#[test_case(true; "completion_before_reply")]
#[tokio::test]
async fn finish_retry_preserves_exact_admission_and_control_progress(complete_before_reply: bool) {
    let (session, _turn_context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let id = "exact-finish-retry".to_string();
    let (_admission_guard, admission) = session.pending_user_message_admissions.register(
        id.clone(),
        Some("finish-retry-client-message".to_string()),
        PendingUserMessageAdmissionState::Immediate,
    );
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let (rejected_tx, rejected_rx) = oneshot::channel();
    let (control_tx, control_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        let fence = Arc::clone(&fence);
        let id = id.clone();
        async move {
            let sub = rx_sub.recv().await.expect("first admission");
            let deferred_reply = if complete_before_reply {
                assert_eq!(sub.id, id);
                let Op::TurnInput {
                    request,
                    mode,
                    reply,
                } = sub.op
                else {
                    panic!("first operation must be turn input");
                };
                let result = turn_input::handle(&session, *request, mode, sub.id)
                    .await
                    .expect("first routing");
                assert_eq!(
                    result,
                    TurnInputSubmission::NotSubmitted {
                        reason: NotSubmittedReason::NotIdle,
                    }
                );
                Some((reply, result))
            } else {
                assert_eq!(
                    route(&session, sub, &id).await,
                    TurnInputSubmission::NotSubmitted {
                        reason: NotSubmittedReason::NotIdle,
                    }
                );
                None
            };
            rejected_tx.send(()).expect("rejection observer");
            let control = rx_sub
                .recv()
                .await
                .expect("control operation while caller waits");
            assert!(matches!(control.op, Op::ThreadSettings { .. }));
            control_tx.send(()).expect("control observer");
            finish_fence(&session, &fence);
            if let Some((reply, result)) = deferred_reply {
                let _ = reply.send(Ok(result));
            }
            let result = route(&session, rx_sub.recv().await.expect("retried input"), &id).await;
            assert_eq!(result, TurnInputSubmission::Started { turn_id: id });
        }
    });
    let io = Arc::new(SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    });
    // Queue the control operation behind the first attempt without requiring
    // the blocked start caller to return. The session actor must keep polling.
    let waiter = tokio::spawn({
        let io = Arc::clone(&io);
        let session = Arc::clone(&session);
        let id = id.clone();
        async move {
            io.submit_turn_input_after_terminalization(
                &session,
                id,
                request(),
                TurnInputMode::StartOrSteer,
            )
            .await
        }
    });
    rejected_rx
        .await
        .expect("first request was rejected by the exact fence");
    io.submit(Op::ThreadSettings {
        thread_settings: ThreadSettingsOverrides::default(),
    })
    .await
    .expect("control operation enqueue");
    tokio::time::timeout(Duration::from_secs(2), control_rx)
        .await
        .expect("finish wait must leave the control channel live")
        .expect("control operation handled");
    let result = tokio::time::timeout(Duration::from_secs(2), waiter)
        .await
        .expect("finish retry should complete")
        .expect("caller join")
        .expect("caller result");
    assert_eq!(
        result,
        TurnInputSubmission::Started {
            turn_id: id.clone()
        }
    );
    let admitted = admission
        .await
        .expect("exact admission sender")
        .expect("exact context");
    assert_eq!(
        admitted.into_admission(),
        UserMessageAdmission::Started { turn_id: id }
    );
    assert!(
        session
            .pending_turn_input_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[tokio::test]
async fn cancelling_finish_wait_does_not_admit_input_or_release_the_fence() {
    let (session, _turn_context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let (rejected_tx, rejected_rx) = oneshot::channel();
    let (stop_tx, stop_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            let result = route(
                &session,
                rx_sub.recv().await.expect("first input"),
                "cancelled-finish",
            )
            .await;
            assert_eq!(
                result,
                TurnInputSubmission::NotSubmitted {
                    reason: NotSubmittedReason::NotIdle
                }
            );
            rejected_tx.send(()).expect("rejection observer");
            let _ = stop_rx.await;
            assert!(
                rx_sub.try_recv().is_err(),
                "cancellation must not resubmit input"
            );
        }
    });
    let io = Arc::new(SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    });
    let waiter = tokio::spawn({
        let session = Arc::clone(&session);
        let io = Arc::clone(&io);
        async move {
            io.submit_turn_input_after_terminalization(
                &session,
                "cancelled-finish".to_string(),
                request(),
                TurnInputMode::StartOrSteer,
            )
            .await
        }
    });
    rejected_rx.await.expect("fenced admission");
    waiter.abort();
    assert!(waiter.await.expect_err("cancelled waiter").is_cancelled());
    assert!(
        session
            .pending_turn_input_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(session.has_pending_task_terminalization());
    assert!(!fence.is_complete());
    assert!(session.active_turn.lock().await.is_none());
    stop_tx.send(()).expect("stop actor");
    io.session_loop_termination.clone().await;
    finish_fence(&session, &fence);
}

#[test_case(TaskTerminalizationKind::Abort, TurnInputMode::StartOrSteer, false; "abort")]
#[test_case(TaskTerminalizationKind::Suspend, TurnInputMode::StartOrSteer, false; "suspend")]
#[test_case(TaskTerminalizationKind::Finish, TurnInputMode::StartIfIdle, false; "idle_only")]
#[test_case(TaskTerminalizationKind::Finish, TurnInputMode::StartOrSteer, true; "shutdown")]
#[tokio::test]
async fn other_admission_fences_are_not_retried(
    kind: TaskTerminalizationKind,
    mode: TurnInputMode,
    shutting_down: bool,
) {
    let (session, _turn_context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, kind);
    if shutting_down {
        session.begin_shutdown();
    }
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(
                &session,
                rx_sub.recv().await.expect("fenced input"),
                "not-retryable",
            )
            .await;
        }
    });
    let io = SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    };
    let result = io
        .submit_turn_input_after_terminalization(
            &session,
            "not-retryable".to_string(),
            request(),
            mode,
        )
        .await
        .expect("ordinary admission rejection");
    assert_eq!(
        result,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle
        }
    );
    assert!(
        session
            .pending_turn_input_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn session_termination_releases_a_waiter_without_admitting_input() {
    let (session, _turn_context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(
                &session,
                rx_sub.recv().await.expect("first input"),
                "terminated-finish",
            )
            .await;
        }
    });
    let io = SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    };
    let error = io
        .submit_turn_input_after_terminalization(
            &session,
            "terminated-finish".to_string(),
            request(),
            TurnInputMode::StartOrSteer,
        )
        .await
        .expect_err("the session ended without completing its fence");
    assert!(matches!(
        error.details(),
        codex_protocol::error::CodexErrorDetails::InternalAgentDied
    ));
    assert!(
        session
            .pending_turn_input_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(!fence.is_complete());
    assert!(session.active_turn.lock().await.is_none());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn finish_marker_captures_a_retry_before_the_active_slot_is_cleared() {
    struct PendingTask;

    impl crate::tasks::SessionTask for PendingTask {
        fn kind(&self) -> crate::state::TaskKind {
            crate::state::TaskKind::Regular
        }

        fn span_name(&self) -> &'static str {
            "session_task.finish_retry_marker"
        }

        async fn run(
            self: Arc<Self>,
            _session: Arc<Session>,
            _ctx: Arc<crate::session::turn_context::TurnContext>,
            _input: Vec<crate::session::TurnInput>,
            _cancellation_token: tokio_util::sync::CancellationToken,
        ) -> crate::tasks::SessionTaskResult {
            std::future::pending().await
        }
    }

    let (session, turn_context, _rx_event) = make_session_and_context_with_rx().await;
    session
        .spawn_task(Arc::clone(&turn_context), Vec::new(), PendingTask)
        .await
        .expect("initial active task");
    let _handoff = session
        .claim_finish_handoff_for_test(Arc::clone(&turn_context), Ok(None))
        .await
        .expect("finish owner claim");
    let completion = {
        let active = session.active_turn.lock().await;
        let active = active
            .as_ref()
            .expect("finish marker retains the active slot");
        assert!(active.task.is_none());
        Arc::clone(
            &active
                .task_terminalization
                .as_ref()
                .expect("exact marker")
                .completion,
        )
    };
    let retry = session
        .pending_turn_input_retries
        .register("active-finish".to_string());
    let result = turn_input::handle(
        &session,
        request(),
        TurnInputMode::StartOrSteer,
        "active-finish".to_string(),
    )
    .await
    .expect("steering refusal");
    assert_eq!(
        result,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle
        }
    );
    let fences = retry
        .take()
        .expect("the exact refusal must carry its finish witness");
    assert_eq!(fences.len(), 1);
    assert!(Arc::ptr_eq(&fences[0], &completion));
    assert!(!completion.is_complete());
    session
        .drain_task_terminalizations_for_shutdown_except(None)
        .await;
    assert!(completion.is_complete());
}
