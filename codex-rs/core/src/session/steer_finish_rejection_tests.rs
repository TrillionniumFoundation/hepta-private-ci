use super::*;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::tests::raw_history_items;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalization;
use crate::state::TaskTerminalizationPhase;
use codex_protocol::protocol::AskForApproval;
use pretty_assertions::assert_eq;
use test_case::test_case;

#[derive(Clone, Copy)]
enum FenceState {
    Pending,
    Retired,
    ShuttingDown,
    MixedAbort,
}

#[test_case(TaskTerminalizationKind::Finish, FenceState::Pending, NotSubmittedReason::NoActiveTurn; "pending_finish")]
#[test_case(TaskTerminalizationKind::Finish, FenceState::Retired, NotSubmittedReason::NoActiveTurn; "retired_finish")]
#[test_case(TaskTerminalizationKind::Abort, FenceState::Pending, NotSubmittedReason::NotIdle; "abort")]
#[test_case(TaskTerminalizationKind::Suspend, FenceState::Pending, NotSubmittedReason::NotIdle; "suspend")]
#[test_case(TaskTerminalizationKind::Finish, FenceState::ShuttingDown, NotSubmittedReason::NotIdle; "shutdown")]
#[test_case(TaskTerminalizationKind::Finish, FenceState::MixedAbort, NotSubmittedReason::NotIdle; "mixed_abort")]
#[tokio::test]
async fn directed_steer_classifies_finished_task_without_mutating_or_admitting(
    kind: TaskTerminalizationKind,
    state: FenceState,
    reason: NotSubmittedReason,
) {
    let (session, context, _events) = make_session_and_context_with_rx().await;
    let before = session.thread_settings_snapshot().await;
    let history = raw_history_items(&session.clone_history().await);
    let epoch = session.turn_epoch.load(Ordering::Acquire);
    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new();
    let mut active = ActiveTurn::default();
    active.task_terminalization = Some(TaskTerminalization {
        identity: Arc::clone(&identity),
        task_identity: Arc::new(RegularTask::new(TurnRunOrigin::NewTurn)),
        turn_context: context,
        turn_state: Arc::clone(&active.turn_state),
        attach_epoch: epoch,
        kind,
        phase: TaskTerminalizationPhase::Terminalizing,
        completion: Arc::clone(&completion),
    });
    *session.active_turn.lock().await = Some(active);
    if !matches!(state, FenceState::Retired) {
        session
            .pending_task_terminalization_completions
            .lock()
            .expect("terminalization registry")
            .push((identity, Arc::clone(&completion), kind, None, None, None));
    }
    if matches!(state, FenceState::MixedAbort) {
        session
            .pending_task_terminalization_completions
            .lock()
            .expect("terminalization registry")
            .push((
                Arc::new(()),
                StartTransitionCompletion::new(),
                TaskTerminalizationKind::Abort,
                None,
                None,
                None,
            ));
    }
    if matches!(state, FenceState::ShuttingDown) {
        session.begin_shutdown();
    }
    let requested_policy = if before.approval_policy == AskForApproval::Never {
        AskForApproval::OnRequest
    } else {
        AskForApproval::Never
    };
    let request = TurnInputRequest::user_input(vec![UserInput::Text {
        text: "this rejected input must not be queued".to_string(),
        text_elements: Vec::new(),
    }])
    .with_thread_settings(ThreadSettingsOverrides {
        approval_policy: Some(requested_policy),
        ..Default::default()
    });
    for (mode, expected) in [
        (
            TurnInputMode::Steer {
                expected_turn_id: "missing-turn".to_string(),
            },
            reason,
        ),
        (TurnInputMode::StartIfIdle, NotSubmittedReason::NotIdle),
    ] {
        let response = handle(
            &session,
            request.clone(),
            mode,
            "rejected-input".to_string(),
        )
        .await
        .expect("typed admission result");
        assert_eq!(
            response,
            TurnInputSubmission::NotSubmitted { reason: expected }
        );
        assert_eq!(session.thread_settings_snapshot().await, before);
        assert_eq!(raw_history_items(&session.clone_history().await), history);
        assert_eq!(session.turn_epoch.load(Ordering::Acquire), epoch);
        assert!(
            !completion.is_complete(),
            "rejection cannot release the Finish owner"
        );
        assert_eq!(
            session
                .input_queue
                .get_pending_input(&session.active_turn)
                .await,
            (Vec::new(), None, None)
        );
    }
    *session.active_turn.lock().await = None;
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalization registry")
        .clear();
    completion.complete();
}
