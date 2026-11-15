use super::*;
use crate::session::tests::make_session_and_context_with_rx;
use crate::user_message_admission::PendingUserMessageAdmissionState;
use crate::user_message_admission::UserMessageAdmission;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::turn_input::TurnInput;
use codex_protocol::user_input::UserInput;
use pretty_assertions::assert_eq;
use std::time::Duration;
use test_case::test_case;

fn request() -> TurnInputRequest {
    TurnInputRequest::new(TurnInput::UserInput {
        content: vec![UserInput::Text {
            text: "one realtime handoff".to_string(),
            text_elements: Vec::new(),
        }],
        client_id: Some("realtime-finish-client".to_string()),
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

async fn wait_for_captured_fence(completion: &Arc<StartTransitionCompletion>) {
    tokio::time::timeout(Duration::from_secs(2), async {
        // The registry and this test retain two references. A third belongs
        // to the actual retry's captured witness, not an elapsed-time guess.
        while Arc::strong_count(completion) < 3 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("the real routing decision must capture its exact Finish owner");
}

fn assert_no_retry_registration(session: &Session) {
    assert!(
        session
            .pending_turn_input_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
}

#[tokio::test]
async fn realtime_finish_retry_waits_for_each_exact_owner_and_admits_once() {
    let (session, _turn_context, _events) = make_session_and_context_with_rx().await;
    let first = install_fence(&session, TaskTerminalizationKind::Finish);
    let second = install_fence(&session, TaskTerminalizationKind::Finish);
    let id = "realtime-exact-finish".to_string();
    let (_admission_guard, admission) = session.pending_user_message_admissions.register(
        id.clone(),
        Some("realtime-finish-client".to_string()),
        PendingUserMessageAdmissionState::Immediate,
    );
    let waiter = tokio::spawn({
        let session = Arc::clone(&session);
        let id = id.clone();
        async move {
            session
                .submit_realtime_turn_input_after_finish(id, request(), &CancellationToken::new())
                .await
        }
    });
    wait_for_captured_fence(&first).await;
    wait_for_captured_fence(&second).await;
    assert!(session.active_turn.lock().await.is_none());
    finish_fence(&session, &first);
    assert!(!waiter.is_finished());
    assert!(!second.is_complete());
    assert!(session.active_turn.lock().await.is_none());
    finish_fence(&session, &second);
    let result = tokio::time::timeout(Duration::from_secs(2), waiter)
        .await
        .expect("exact Finish retry")
        .expect("retry task")
        .expect("normal routing");
    assert_eq!(
        result,
        TurnInputSubmission::Started {
            turn_id: id.clone()
        }
    );
    assert_eq!(
        admission
            .await
            .expect("admission reply")
            .expect("exact context")
            .into_admission(),
        UserMessageAdmission::Started { turn_id: id }
    );
    assert_no_retry_registration(&session);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[tokio::test]
async fn stopping_realtime_releases_only_the_waiter_and_keeps_the_finish_fence() {
    let (session, _turn_context, _events) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let stop = CancellationToken::new();
    let waiter = tokio::spawn({
        let session = Arc::clone(&session);
        let stop = stop.clone();
        async move {
            session
                .submit_realtime_turn_input_after_finish(
                    "realtime-stopped".to_string(),
                    request(),
                    &stop,
                )
                .await
        }
    });
    wait_for_captured_fence(&fence).await;
    stop.cancel();
    let result = tokio::time::timeout(Duration::from_secs(2), waiter)
        .await
        .expect("conversation stop must not wait on its own fanout")
        .expect("retry task")
        .expect("ordinary admission refusal");
    assert_eq!(
        result,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        }
    );
    assert_no_retry_registration(&session);
    assert!(session.has_pending_task_terminalization());
    assert!(!fence.is_complete());
    assert!(session.active_turn.lock().await.is_none());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn dropping_realtime_fanout_does_not_leave_a_retry_or_admit_input() {
    let (session, _turn_context, _events) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let waiter = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            session
                .submit_realtime_turn_input_after_finish(
                    "realtime-dropped".to_string(),
                    request(),
                    &CancellationToken::new(),
                )
                .await
        }
    });
    wait_for_captured_fence(&fence).await;
    waiter.abort();
    assert!(waiter.await.expect_err("cancelled fanout").is_cancelled());
    assert_no_retry_registration(&session);
    assert!(!fence.is_complete());
    assert!(session.active_turn.lock().await.is_none());
    finish_fence(&session, &fence);
}

#[test_case(TaskTerminalizationKind::Abort, false; "abort")]
#[test_case(TaskTerminalizationKind::Suspend, false; "suspend")]
#[test_case(TaskTerminalizationKind::Finish, true; "shutdown")]
#[tokio::test]
async fn realtime_does_not_retry_other_admission_barriers(
    kind: TaskTerminalizationKind,
    shutting_down: bool,
) {
    let (session, _turn_context, _events) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, kind);
    if shutting_down {
        session.begin_shutdown();
    }
    let result = tokio::time::timeout(
        Duration::from_secs(2),
        session.submit_realtime_turn_input_after_finish(
            "realtime-not-retryable".to_string(),
            request(),
            &CancellationToken::new(),
        ),
    )
    .await
    .expect("non-Finish barriers must not wait")
    .expect("ordinary admission refusal");
    assert_eq!(
        result,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        }
    );
    assert_no_retry_registration(&session);
    assert!(!fence.is_complete());
    assert!(session.active_turn.lock().await.is_none());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn stopped_conversation_still_routes_its_already_parsed_tail_when_idle() {
    let (session, _turn_context, _events) = make_session_and_context_with_rx().await;
    let stop = CancellationToken::new();
    stop.cancel();
    let result = session
        .submit_realtime_turn_input_after_finish("realtime-tail".to_string(), request(), &stop)
        .await
        .expect("normal admission for already parsed input");
    assert_eq!(
        result,
        TurnInputSubmission::Started {
            turn_id: "realtime-tail".to_string(),
        }
    );
    assert_no_retry_registration(&session);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}
