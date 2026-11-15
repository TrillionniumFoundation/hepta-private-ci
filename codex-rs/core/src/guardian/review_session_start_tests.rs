use super::*;
use crate::guardian::review_session::GuardianReviewSessionOutcome;
use crate::guardian::review_session::run_before_review_deadline;
use crate::guardian::review_session::tests::test_review_session;
use crate::session::session::Session;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalizationKind;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::W3cTraceContext;
use codex_protocol::turn_input::NotSubmittedReason;
use codex_protocol::turn_input::TurnStartOptions;
use codex_protocol::user_input::UserInput;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::time::Duration;
use test_case::test_case;
use tokio_util::sync::CancellationToken;

fn request() -> TurnInputRequest {
    TurnInputRequest::user_input(vec![UserInput::Text {
        text: "review exactly this action".to_string(),
        text_elements: Vec::new(),
    }])
    .with_thread_settings(ThreadSettingsOverrides {
        approval_policy: Some(AskForApproval::Never),
        ..Default::default()
    })
    .on_start(TurnStartOptions {
        final_output_json_schema: Some(serde_json::json!({"type": "object"})),
        parent_turn_id: Some("parent-turn".to_string()),
        root_turn_id: Some("root-turn".to_string()),
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

#[tokio::test]
async fn reused_review_waits_for_exact_finish_fences_before_idle_only_submission() {
    let (mut review, _events, submissions) = test_review_session().await;
    review.io.session_loop_termination = std::future::pending().boxed().shared();
    let first = install_fence(&review.session, TaskTerminalizationKind::Finish);
    let pending = review.submit_review_input(request());
    tokio::pin!(pending);
    assert!(futures::poll!(pending.as_mut()).is_pending());
    assert!(submissions.try_recv().is_err());

    // A second identity must not be released by completion of the first one.
    let second = install_fence(&review.session, TaskTerminalizationKind::Finish);
    finish_fence(&review.session, &first);
    assert!(futures::poll!(pending.as_mut()).is_pending());
    assert!(submissions.try_recv().is_err());

    // Waiting never occupies the actor's input channel.
    review
        .io
        .submit(Op::ThreadSettings {
            thread_settings: ThreadSettingsOverrides::default(),
        })
        .await
        .expect("control input");
    assert!(matches!(
        submissions.try_recv().expect("control remains live").op,
        Op::ThreadSettings { .. }
    ));

    finish_fence(&review.session, &second);
    assert!(futures::poll!(pending.as_mut()).is_pending());
    let submission = submissions.try_recv().expect("review after exact finish");
    let Op::TurnInput {
        request: actual,
        mode,
        reply,
    } = submission.op
    else {
        panic!("expected one ordered review input");
    };
    let expected = request();
    assert_eq!(
        (
            mode,
            actual.input,
            actual.thread_settings,
            actual.start.final_output_json_schema,
            actual.start.parent_turn_id,
            actual.start.root_turn_id,
            actual.additional_context,
            actual.responsesapi_client_metadata,
            actual.trace,
            submission.trace,
        ),
        (
            TurnInputMode::StartIfIdle,
            expected.input,
            expected.thread_settings,
            expected.start.final_output_json_schema,
            expected.start.parent_turn_id,
            expected.start.root_turn_id,
            expected.additional_context,
            expected.responsesapi_client_metadata,
            None,
            expected.trace,
        )
    );
    let started = TurnInputSubmission::Started {
        turn_id: submission.id,
    };
    reply.send(Ok(started.clone())).expect("review reply");
    assert_eq!(pending.await.expect("review admission"), started);
    assert!(submissions.try_recv().is_err());
    assert!(!review.session.has_pending_task_terminalization());
}

#[test_case(TaskTerminalizationKind::Abort; "abort")]
#[test_case(TaskTerminalizationKind::Suspend; "suspend")]
#[tokio::test]
async fn non_finish_owners_keep_normal_idle_only_rejection(kind: TaskTerminalizationKind) {
    let (review, _events, submissions) = test_review_session().await;
    let fence = install_fence(&review.session, kind);
    let pending = review.submit_review_input(request());
    tokio::pin!(pending);
    assert!(futures::poll!(pending.as_mut()).is_pending());
    let Op::TurnInput { mode, reply, .. } = submissions.try_recv().expect("normal admission").op
    else {
        panic!("expected idle-only input");
    };
    assert_eq!(mode, TurnInputMode::StartIfIdle);
    let denied = TurnInputSubmission::NotSubmitted {
        reason: NotSubmittedReason::NotIdle,
    };
    reply.send(Ok(denied.clone())).expect("rejection reply");
    assert_eq!(pending.await.expect("normal admission result"), denied);
    assert!(!fence.is_complete());
    assert!(submissions.try_recv().is_err());
}

#[tokio::test]
async fn cancelled_finish_wait_never_submits_review_input() {
    let (mut review, _events, submissions) = test_review_session().await;
    review.io.session_loop_termination = std::future::pending().boxed().shared();
    let fence = install_fence(&review.session, TaskTerminalizationKind::Finish);
    let cancel = CancellationToken::new();
    let pending = run_before_review_deadline(
        tokio::time::Instant::now() + Duration::from_secs(30),
        Some(&cancel),
        review.submit_review_input(request()),
    );
    tokio::pin!(pending);
    assert!(futures::poll!(pending.as_mut()).is_pending());
    cancel.cancel();
    assert!(matches!(
        pending.await,
        Err(GuardianReviewSessionOutcome::Aborted)
    ));
    assert!(submissions.try_recv().is_err());
    assert!(!fence.is_complete());
}

#[tokio::test(start_paused = true)]
async fn finish_wait_uses_existing_review_deadline_without_submitting_input() {
    let (mut review, _events, submissions) = test_review_session().await;
    review.io.session_loop_termination = std::future::pending().boxed().shared();
    let fence = install_fence(&review.session, TaskTerminalizationKind::Finish);
    let pending = run_before_review_deadline(
        tokio::time::Instant::now() + Duration::from_secs(30),
        /*external_cancel*/ None,
        review.submit_review_input(request()),
    );
    tokio::pin!(pending);
    assert!(futures::poll!(pending.as_mut()).is_pending());
    tokio::time::advance(Duration::from_secs(30)).await;
    assert!(matches!(
        pending.await,
        Err(GuardianReviewSessionOutcome::TimedOut)
    ));
    assert!(submissions.try_recv().is_err());
    assert!(!fence.is_complete());
}

#[tokio::test]
async fn terminated_review_session_does_not_wait_or_enqueue_input() {
    let (review, _events, submissions) = test_review_session().await;
    let fence = install_fence(&review.session, TaskTerminalizationKind::Finish);
    let error = review
        .submit_review_input(request())
        .await
        .expect_err("terminated review session");
    assert!(matches!(
        error.details(),
        codex_protocol::error::CodexErrorDetails::InternalAgentDied
    ));
    assert!(submissions.try_recv().is_err());
    assert!(!fence.is_complete());
}
