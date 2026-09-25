use super::*;
use crate::session::session::RecoveryCandidate;
use crate::session::session::RolloutPersistenceFault;
use crate::session::tests::attach_in_memory_thread_store;
use crate::session::tests::make_session_and_context_with_rx;
use crate::state::DurableRecoveryState;
use crate::state::TaskKind;
use crate::state::TurnRecoveryAuthority;
use crate::tasks::RecoveryReadyForSampling;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use codex_app_server_protocol::ThreadHistoryBuilder;
use codex_history::RolloutItem;
use codex_protocol::AgentPath;
use codex_protocol::config_types::CollaborationMode;
use codex_protocol::config_types::ModeKind;
use codex_protocol::config_types::Settings;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::InterAgentCommunication;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnRecoveryCandidateState;
use codex_protocol::protocol::WarningEvent;
use codex_protocol::turn_input::TurnInput as SubmittedTurnInput;
use codex_protocol::user_input::UserInput;
use codex_thread_store::InMemoryThreadStore;
use codex_thread_store::LoadThreadHistoryParams;
use codex_thread_store::ThreadStore;
use core_test_support::test_codex::local_selections;
use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy)]
struct CompletingTask;

impl SessionTask for CompletingTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.turn_input_completing_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        Ok(None)
    }
}

#[derive(Clone, Copy)]
struct NeverEndingTask {
    kind: TaskKind,
    listen_to_cancellation_token: bool,
}

struct RecoverableNeverEndingModelTask {
    authority: Arc<TurnRecoveryAuthority>,
}

impl RecoverableNeverEndingModelTask {
    fn new(ready: bool) -> Self {
        let authority = Arc::new(TurnRecoveryAuthority::default());
        let mut state = authority
            .state
            .try_lock()
            .expect("fresh recovery authority must be unlocked");
        state.durable_state = if ready {
            DurableRecoveryState::Ready
        } else {
            DurableRecoveryState::Unready
        };
        state.ready_persistence_failure_generation = ready.then_some(0);
        drop(state);
        authority.ready.store(ready, Ordering::Release);
        Self { authority }
    }
}

struct RecoverableRevokingOnCancelTask {
    authority: Arc<TurnRecoveryAuthority>,
}

struct RecoverableFinishOnSignalTask {
    authority: Arc<TurnRecoveryAuthority>,
    finish: Arc<tokio::sync::Notify>,
}

impl RecoverableFinishOnSignalTask {
    fn new() -> Self {
        Self {
            authority: Arc::new(TurnRecoveryAuthority::default()),
            finish: Arc::new(tokio::sync::Notify::new()),
        }
    }
}

impl RecoverableRevokingOnCancelTask {
    fn new() -> Self {
        let authority = Arc::new(TurnRecoveryAuthority::default());
        let mut state = authority
            .state
            .try_lock()
            .expect("fresh recovery authority must be unlocked");
        state.durable_state = DurableRecoveryState::Ready;
        state.ready_persistence_failure_generation = Some(0);
        drop(state);
        authority.ready.store(true, Ordering::Release);
        Self { authority }
    }
}

impl SessionTask for RecoverableRevokingOnCancelTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn recovery_eligible_model_turn(&self) -> bool {
        true
    }

    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> {
        Some(Arc::clone(&self.authority))
    }

    fn span_name(&self) -> &'static str {
        "session_task.recovery_revoking_on_cancel_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        cancellation_token.cancelled().await;
        let mut state = self.authority.state.lock().await;
        self.authority.ready.store(false, Ordering::Release);
        state.generation = state.generation.saturating_add(1);
        state.durable_state = DurableRecoveryState::Unready;
        state.ready_persistence_failure_generation = None;
        Ok(None)
    }
}

impl SessionTask for RecoverableNeverEndingModelTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn recovery_eligible_model_turn(&self) -> bool {
        true
    }

    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> {
        Some(Arc::clone(&self.authority))
    }

    fn span_name(&self) -> &'static str {
        "session_task.recoverable_model_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        cancellation_token.cancelled().await;
        Ok(None)
    }
}

impl SessionTask for RecoverableFinishOnSignalTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn recovery_eligible_model_turn(&self) -> bool {
        true
    }

    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> {
        Some(Arc::clone(&self.authority))
    }

    fn span_name(&self) -> &'static str {
        "session_task.recoverable_finish_on_signal_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        self.finish.notified().await;
        Err(CodexErr::TurnAborted)
    }
}

impl SessionTask for NeverEndingTask {
    fn kind(&self) -> TaskKind {
        self.kind
    }

    fn span_name(&self) -> &'static str {
        "session_task.turn_input_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        if self.listen_to_cancellation_token {
            cancellation_token.cancelled().await;
            return Ok(None);
        }
        loop {
            sleep(std::time::Duration::from_secs(60)).await;
        }
    }
}

fn user_message(text: &str) -> ResponseItem {
    ResponseItem::Message {
        id: None,
        role: "user".to_string(),
        content: vec![ContentItem::InputText {
            text: text.to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

#[tokio::test]
async fn turn_input_dispatch_future_stays_bounded() {
    let (session, _turn_context, _rx) = make_session_and_context_with_rx().await;
    let future = handle(
        &session,
        TurnInputRequest::user_input(vec![UserInput::Text {
            text: "bounded future".to_string(),
            text_elements: Vec::new(),
        }]),
        TurnInputMode::StartOrSteer,
        "future-size".to_string(),
    );
    let size = std::mem::size_of_val(&future);

    assert!(
        size < 64 * 1024,
        "turn-input dispatch future is {size} bytes"
    );
}

async fn submit_start_only(
    session: &Arc<Session>,
    input: SubmittedTurnInput,
) -> TurnInputSubmission {
    handle(
        session,
        TurnInputRequest::new(input),
        TurnInputMode::StartIfIdle,
        "test-submission".to_string(),
    )
    .await
    .expect("start-only submission should be valid")
}

async fn submit_steer_only(
    session: &Arc<Session>,
    input: Vec<UserInput>,
    expected_turn_id: &str,
) -> TurnInputSubmission {
    handle(
        session,
        TurnInputRequest::new(SubmittedTurnInput::UserInput {
            content: input,
            client_id: None,
        }),
        TurnInputMode::Steer {
            expected_turn_id: expected_turn_id.to_string(),
        },
        "test-submission".to_string(),
    )
    .await
    .expect("steer-only submission should be valid")
}

#[tokio::test]
async fn accepted_input_applies_thread_settings() {
    let (session, turn_context, _rx) = make_session_and_context_with_rx().await;
    let config = session.get_config().await;
    handle(
        &session,
        TurnInputRequest::user_input(vec![UserInput::Text {
            text: "hello".to_string(),
            text_elements: Vec::new(),
        }])
        .with_thread_settings(ThreadSettingsOverrides {
            environments: Some(local_selections(config.cwd.clone())),
            approval_policy: Some(config.permissions.approval_policy.value()),
            approvals_reviewer: Some(codex_config::types::ApprovalsReviewer::AutoReview),
            sandbox_policy: Some(config.legacy_sandbox_policy()),
            summary: config.model_reasoning_summary,
            personality: config.personality,
            collaboration_mode: Some(CollaborationMode {
                mode: ModeKind::Default,
                settings: Settings {
                    model: turn_context.model_info.slug.clone(),
                    reasoning_effort: config.model_reasoning_effort.clone(),
                    developer_instructions: None,
                },
            }),
            ..Default::default()
        }),
        TurnInputMode::StartOrSteer,
        "sub-1".to_string(),
    )
    .await
    .expect("submit user turn");

    let state = session.state.lock().await;
    assert_eq!(
        state.session_configuration.approvals_reviewer,
        codex_config::types::ApprovalsReviewer::AutoReview
    );
    assert!(
        session.mcp_refresh.is_pending(),
        "server elicitation authority changes must refresh MCP state"
    );
}

#[tokio::test]
async fn start_only_rejects_active_turn_without_injecting() {
    let (session, turn_context, _rx) = make_session_and_context_with_rx().await;
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
        .expect("active task should start");

    let input = SubmittedTurnInput::ResponseItem(user_message("synthetic idle input"));
    let submission = submit_start_only(&session, input).await;

    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        },
        submission
    );
    assert_eq!(
        (Vec::<TurnInput>::new(), None, None),
        session
            .input_queue
            .get_pending_input(&session.active_turn)
            .await
    );

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[expect(
    clippy::await_holding_invalid_type,
    reason = "the recovery consumption contract requires active_turn to stay held"
)]
#[tokio::test]
async fn shutdown_fence_settles_consumed_recovery_before_caller_reservation() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let turn_id = "shutdown-before-recovery-reservation";
    seed_recovery_candidate(&session, turn_id).await;

    // Model the completion of the async recovery preamble while retaining the
    // active-turn lock. Shutdown wins before the final reserve_start window;
    // the shared helper must reject and settle the consumed authority.
    let mut active_turn = session.active_turn.lock().await;
    let consumed_recovery = session
        .consume_recovery_candidate_for_mutation()
        .await
        .expect("recovery authority should be consumed");
    assert!(consumed_recovery);
    session.begin_shutdown();

    let reservation = reserve_start_after_admission(
        &session,
        &mut active_turn,
        turn_id.to_string(),
        consumed_recovery,
    );
    assert!(reservation.is_none());
    assert!(active_turn.is_none());
    drop(active_turn);
    assert!(!session.is_interrupted());
}

#[tokio::test]
async fn steer_rejects_after_shutdown_without_injecting() {
    let (session, turn_context, _rx) = make_session_and_context_with_rx().await;
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
        .expect("active task should start");

    session.begin_shutdown();
    let steer_input = vec![UserInput::Text {
        text: "shutdown steer".to_string(),
        text_elements: Vec::new(),
    }];
    let steer_submission =
        submit_steer_only(&session, steer_input.clone(), &turn_context.sub_id).await;
    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        },
        steer_submission
    );

    let start_or_steer_submission = handle(
        &session,
        TurnInputRequest::user_input(steer_input),
        TurnInputMode::StartOrSteer,
        "shutdown-steer-submission".to_string(),
    )
    .await
    .expect("start-or-steer submission should be valid");
    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        },
        start_or_steer_submission
    );
    assert_eq!(
        (Vec::<TurnInput>::new(), None, None),
        session
            .input_queue
            .get_pending_input(&session.active_turn)
            .await
    );

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[tokio::test]
async fn recovery_rejects_active_turn_without_injecting_or_applying_settings() {
    let (session, turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let original_approval_policy = session
        .get_config()
        .await
        .permissions
        .approval_policy
        .value();
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
        .expect("active recovery task should start");

    let submission = handle_recovery(
        &session,
        /*expected_epoch*/ 0,
        ThreadSettingsOverrides {
            approval_policy: Some(AskForApproval::Never),
            ..Default::default()
        },
        "recovered-turn".to_string(),
    )
    .await
    .expect("recovery should return a typed rejection");

    assert_eq!(
        submission,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        }
    );
    assert_eq!(
        session
            .get_config()
            .await
            .permissions
            .approval_policy
            .value(),
        original_approval_policy
    );
    assert_eq!(
        session
            .input_queue
            .get_pending_input(&session.active_turn)
            .await,
        (Vec::<TurnInput>::new(), None, None)
    );

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

async fn wait_until_idle(session: &Session) {
    timeout(Duration::from_secs(2), async {
        loop {
            if session.active_turn.lock().await.is_none() {
                break;
            }
            sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("session should become idle");
}

async fn make_turn_recovery_session_and_context_with_rx() -> (
    Arc<Session>,
    Arc<TurnContext>,
    async_channel::Receiver<Event>,
) {
    let (mut session, mut turn_context, rx) = make_session_and_context_with_rx().await;
    Arc::get_mut(&mut session)
        .expect("fresh test session should be uniquely owned")
        .features
        .enable(Feature::HeptaTurnRecovery)
        .expect("enable Hepta turn recovery on the test session");
    {
        let mut state = session.state.lock().await;
        let mut config = (*state.session_configuration.original_config_do_not_use).clone();
        config
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable Hepta turn recovery in the test session config");
        state.session_configuration.original_config_do_not_use = Arc::new(config);
    }
    Arc::make_mut(
        &mut Arc::get_mut(&mut turn_context)
            .expect("fresh turn context should be uniquely owned")
            .config,
    )
    .features
    .enable(Feature::HeptaTurnRecovery)
    .expect("enable Hepta turn recovery on the test turn");
    (session, turn_context, rx)
}

async fn seed_recovery_candidate(session: &Session, turn_id: &str) -> u64 {
    let turn_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    session
        .state
        .lock()
        .await
        .set_reference_context_item(Some(turn_context.to_turn_context_item()));
    let epoch = session.turn_epoch.load(Ordering::Acquire);
    let persistence_failure_generation = session.rollout_persistence_failure_generation();
    let history_boundary = session
        .current_recovery_history_boundary()
        .await
        .expect("history boundary");
    let turn_context_sha256 =
        crate::model_provider_policy::canonical_sha256(&turn_context.to_turn_context_item())
            .expect("turn context digest")
            .as_str()
            .to_string();
    let environments =
        super::super::turn::turn_recovery_environment_selections(&turn_context.environments)
            .expect("thread-derived environments");
    *session
        .recovery_candidate
        .lock()
        .expect("recovery candidate mutex poisoned") = Some(RecoveryCandidate {
        turn_id: turn_id.to_string(),
        marker_generation: 0,
        epoch,
        persistence_failure_generation,
        request_fingerprint_sha256: "turn-input-test-request-fingerprint".to_string(),
        replay: codex_history::TurnRecoveryReplayV1 {
            history_boundary,
            turn_context_sha256,
            start: codex_history::TurnRecoveryStartState {
                final_output_json_schema: None,
                parent_turn_id: None,
                root_turn_id: Some(turn_id.to_string()),
                responses_metadata_extra: Default::default(),
            },
            environments,
        },
    });
    session.mark_interrupted();
    epoch
}

#[tokio::test]
async fn recovery_rejects_stale_epoch_after_intervening_completed_turn() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let interrupted_turn_id = "stale-interrupted-turn";
    seed_recovery_candidate(session.as_ref(), interrupted_turn_id).await;
    let expected_epoch = session
        .recovery_epoch_if_idle(interrupted_turn_id)
        .await
        .expect("interrupted idle session should expose a recovery epoch");

    let intervening_turn = session
        .new_default_turn_with_sub_id("intervening-completed-turn".to_string())
        .await;
    session
        .spawn_task(intervening_turn, Vec::new(), CompletingTask)
        .await
        .expect("intervening completing task should start");
    wait_until_idle(session.as_ref()).await;

    let current_epoch = session.turn_epoch.load(Ordering::Acquire);
    assert!(current_epoch > expected_epoch);
    let submission = handle_recovery(
        &session,
        expected_epoch,
        ThreadSettingsOverrides::default(),
        "stale-interrupted-turn".to_string(),
    )
    .await
    .expect("stale recovery should return a typed rejection");

    assert_eq!(
        submission,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::RecoveryStateChanged,
        }
    );
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), current_epoch);
}

#[tokio::test]
async fn recovery_rejects_stale_epoch_after_intervening_interrupted_turn() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let interrupted_turn_id = "stale-interrupted-turn";
    seed_recovery_candidate(session.as_ref(), interrupted_turn_id).await;
    let expected_epoch = session
        .recovery_epoch_if_idle(interrupted_turn_id)
        .await
        .expect("interrupted idle session should expose a recovery epoch");

    let intervening_turn = session
        .new_default_turn_with_sub_id("intervening-interrupted-turn".to_string())
        .await;
    session
        .spawn_task(
            intervening_turn,
            Vec::new(),
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: true,
            },
        )
        .await
        .expect("intervening task should start");
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    wait_until_idle(session.as_ref()).await;
    assert!(session.is_interrupted());

    let current_epoch = session.turn_epoch.load(Ordering::Acquire);
    assert!(current_epoch > expected_epoch);
    let submission = handle_recovery(
        &session,
        expected_epoch,
        ThreadSettingsOverrides::default(),
        "stale-interrupted-turn".to_string(),
    )
    .await
    .expect("stale recovery should return a typed rejection");

    assert_eq!(
        submission,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::RecoveryStateChanged,
        }
    );
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), current_epoch);
}

#[tokio::test]
async fn recovery_rejects_and_consumes_candidate_after_execution_context_drift() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("fresh session should remain uniquely owned"),
    )
    .await;
    let turn_id = "context-drift-interrupted-turn";
    let expected_epoch = seed_recovery_candidate(session.as_ref(), turn_id).await;

    let original_context = session
        .reference_context_item()
        .await
        .expect("seeded recovery context");
    let original_model = session.collaboration_mode().await.model().to_string();
    let drifted_model = if original_model == "gpt-5.4" {
        "gpt-5.2"
    } else {
        "gpt-5.4"
    };
    let drifted_mode = session.collaboration_mode().await.with_updates(
        Some(drifted_model.to_string()),
        /*reasoning_effort*/ None,
        /*developer_instructions*/ None,
    );
    session
        .update_settings(SessionSettingsUpdate {
            collaboration_mode: Some(drifted_mode),
            ..Default::default()
        })
        .await
        .expect("simulate a valid offline model/config change");
    let drifted_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await
        .to_turn_context_item();
    assert_ne!(
        drifted_context.model, original_context.model,
        "test setup must change a model-visible recovery input"
    );
    assert_ne!(
        drifted_context, original_context,
        "test setup must make the exact recovery context drift"
    );

    let submission = handle_recovery(
        &session,
        expected_epoch,
        ThreadSettingsOverrides::default(),
        turn_id.to_string(),
    )
    .await
    .expect("context drift should return a typed rejection");
    assert_eq!(
        submission,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::RecoveryStateChanged,
        }
    );
    assert!(session.active_turn.lock().await.is_none());
    assert!(
        session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned")
            .is_none()
    );
    assert_eq!(
        *session.agent_status.borrow(),
        AgentStatus::Completed(/*last_agent_message*/ None)
    );
    let persisted = session
        .live_thread()
        .expect("test session has persistence")
        .load_history(/*include_archived*/ true)
        .await
        .expect("load context drift tombstone");
    assert!(persisted.items.iter().any(|item| {
        matches!(
            item,
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                if marker.turn_id == turn_id
                    && marker.generation == 1
                    && marker.state == TurnRecoveryCandidateState::Unready
        )
    }));
}

#[tokio::test]
async fn recovery_context_digest_mismatch_tombstones_without_installing_rewind() {
    let (mut session, turn_context, rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("fresh session should remain uniquely owned"),
    )
    .await;
    let turn_id = "context-digest-mismatch-interrupted-turn";
    let expected_epoch = seed_recovery_candidate(session.as_ref(), turn_id).await;

    // Keep a logical tail after the provider Ready boundary. A successful
    // recovery would install the staged rewind and remove this item.
    session
        .record_conversation_items(
            turn_context.as_ref(),
            std::slice::from_ref(&user_message("post-boundary interrupted tail")),
        )
        .await;
    let history_before_recovery = session.clone_history().await;
    let history_items_before_recovery = history_before_recovery.annotated_items().to_vec();
    let history_version_before_recovery = history_before_recovery.history_version();
    assert!(
        history_before_recovery.raw_items().any(|item| {
            matches!(
                item,
                ResponseItem::Message { content, .. }
                    if content.iter().any(|content| {
                        matches!(
                            content,
                            ContentItem::InputText { text }
                                if text == "post-boundary interrupted tail"
                        )
                    })
            )
        }),
        "test setup must include a logical item after the bound prefix"
    );

    {
        let mut candidate = session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned");
        candidate
            .as_mut()
            .expect("seeded recovery candidate")
            .replay
            .turn_context_sha256 = "tampered-turn-context-digest".to_string();
    }
    while rx.try_recv().is_ok() {}

    let submission = handle_recovery(
        &session,
        expected_epoch,
        ThreadSettingsOverrides::default(),
        turn_id.to_string(),
    )
    .await
    .expect("context digest mismatch should return a typed rejection");

    assert_eq!(
        submission,
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::RecoveryStateChanged,
        }
    );
    assert!(
        session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned")
            .is_none(),
        "a mismatched candidate must be consumed instead of remaining retryable"
    );
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(
        *session.agent_status.borrow(),
        AgentStatus::Completed(/*last_agent_message*/ None)
    );
    assert_eq!(
        session.turn_epoch.load(Ordering::Acquire),
        expected_epoch.saturating_add(1)
    );

    let history_after_recovery = session.clone_history().await;
    assert_eq!(
        history_after_recovery.annotated_items(),
        history_items_before_recovery.as_slice(),
        "digest rejection must not install the staged rewind snapshot"
    );
    assert_eq!(
        history_after_recovery.history_version(),
        history_version_before_recovery,
        "digest rejection must leave logical history state untouched"
    );

    let persisted = store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("load context digest mismatch tombstone");
    assert!(persisted.items.iter().any(|item| {
        matches!(
            item,
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                if marker.turn_id == turn_id
                    && marker.generation == 1
                    && marker.state == TurnRecoveryCandidateState::Unready
        )
    }));
    assert!(
        !persisted.items.iter().any(|item| {
            matches!(
                item,
                RolloutItem::EventMsg(EventMsg::TurnStarted(event))
                    if event.turn_id == turn_id
            )
        }),
        "digest rejection must not persist a restarted physical turn"
    );
    while let Ok(event) = rx.try_recv() {
        assert!(
            !matches!(event.msg, EventMsg::TurnStarted(_)),
            "digest rejection must not dispatch a recovery task"
        );
    }
}

#[tokio::test]
async fn live_recovery_candidate_requires_exact_recoverable_model_task_and_is_invalidated() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let config = session.get_config().await;
    session
        .update_settings(SessionSettingsUpdate {
            environments: Some(local_selections(config.cwd.clone())),
            ..Default::default()
        })
        .await
        .expect("install an explicit thread-derived recovery environment");
    let turn_id = "recoverable-model-turn";
    let turn_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    let environments =
        super::super::turn::turn_recovery_environment_selections(&turn_context.environments)
            .expect("positive fixture must have nonempty FromThread environments");
    assert!(!environments.is_empty());
    let task = RecoverableNeverEndingModelTask::new(/*ready*/ false);
    let authority = Arc::clone(&task.authority);
    session
        .spawn_task(Arc::clone(&turn_context), Vec::new(), task)
        .await
        .expect("spawn recoverable model task");
    let replay = codex_history::TurnRecoveryReplayV1 {
        history_boundary: session
            .current_recovery_history_boundary()
            .await
            .expect("history boundary"),
        turn_context_sha256: crate::model_provider_policy::canonical_sha256(
            &turn_context.to_turn_context_item(),
        )
        .expect("turn context digest")
        .as_str()
        .to_string(),
        start: codex_history::TurnRecoveryStartState {
            final_output_json_schema: None,
            parent_turn_id: None,
            root_turn_id: Some(turn_id.to_string()),
            responses_metadata_extra: Default::default(),
        },
        environments,
    };
    assert_eq!(
        session
            .mark_recovery_ready_for_sampling_with_replay(
                turn_id,
                &authority,
                session.rollout_persistence_failure_generation(),
                "turn-input-test-request-fingerprint",
                &replay,
            )
            .await
            .expect("Ready marker should append and flush"),
        RecoveryReadyForSampling::Ready,
    );
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    wait_until_idle(session.as_ref()).await;

    let epoch = session
        .recovery_epoch_if_idle(turn_id)
        .await
        .expect("recoverable model interrupt should publish an exact candidate");
    assert_eq!(session.recovery_epoch_if_idle("wrong-turn").await, None);

    let reservation = session
        .reserve_history_mutation_if_idle()
        .await
        .expect("recovery authority should be consumed")
        .expect("idle session should reserve history mutation");
    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
    assert!(session.turn_epoch.load(Ordering::Acquire) > epoch);
    session
        .settle_and_clear_reserved_idle_turn(&reservation)
        .await;
    assert!(matches!(
        *session.agent_status.borrow(),
        AgentStatus::Completed(None)
    ));

    let auxiliary_id = "regular-kind-but-not-model";
    let auxiliary_context = session
        .new_default_turn_with_sub_id(auxiliary_id.to_string())
        .await;
    session
        .spawn_task(
            auxiliary_context,
            Vec::new(),
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: true,
            },
        )
        .await
        .expect("auxiliary task should start");
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    wait_until_idle(session.as_ref()).await;
    assert_eq!(session.recovery_epoch_if_idle(auxiliary_id).await, None);
}

#[tokio::test]
async fn graceful_abort_before_ready_does_not_publish_recovery_candidate() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let turn_id = "pre-ready-model-turn";
    let turn_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    session
        .spawn_task(
            turn_context,
            Vec::new(),
            RecoverableNeverEndingModelTask::new(/*ready*/ false),
        )
        .await
        .expect("pre-ready recoverable task should start");

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    wait_until_idle(session.as_ref()).await;

    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn recovery_abort_during_start_restores_pre_rewind_history() {
    struct BlockingStartContributor {
        entered: Arc<tokio::sync::Notify>,
        release: Arc<tokio::sync::Notify>,
    }

    impl codex_extension_api::TurnLifecycleContributor for BlockingStartContributor {
        fn on_turn_start<'a>(
            &'a self,
            input: codex_extension_api::TurnStartInput<'a>,
        ) -> codex_extension_api::ExtensionFuture<'a, ()> {
            Box::pin(async move {
                let _ = input;
                self.entered.notify_one();
                self.release.notified().await;
            })
        }
    }

    let (mut session, turn_context, rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("fresh session should remain uniquely owned"),
    )
    .await;
    let turn_id = "recovery-start-abort-history";
    let expected_epoch = seed_recovery_candidate(session.as_ref(), turn_id).await;
    session
        .record_conversation_items(
            turn_context.as_ref(),
            std::slice::from_ref(&user_message("recovery tail must survive abort")),
        )
        .await;

    let entered = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Notify::new());
    let mut extensions =
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    extensions.turn_lifecycle_contributor(Arc::new(BlockingStartContributor {
        entered: Arc::clone(&entered),
        release: Arc::clone(&release),
    }));
    Arc::get_mut(&mut session)
        .expect("session should still have a unique test owner")
        .services
        .extensions = Arc::new(extensions.build());

    let recovery = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            handle_recovery(
                &session,
                expected_epoch,
                ThreadSettingsOverrides::default(),
                turn_id.to_string(),
            )
            .await
            .expect("recovery start should be accepted before the abort");
        }
    });

    timeout(Duration::from_secs(2), entered.notified())
        .await
        .expect("recovery turn-start contributor should block");
    assert!(
        session
            .active_turn
            .lock()
            .await
            .as_ref()
            .is_some_and(|active| active.task.is_none() && active.start_transition.is_some())
    );
    assert!(
        session
            .abort_turn_if_active(turn_id, TurnAbortReason::Interrupted)
            .await
    );
    release.notify_one();
    recovery
        .await
        .expect("recovery start task should join after abort");

    let mut saw_turn_started = false;
    let mut saw_turn_aborted = false;
    for _ in 0..16 {
        let event = timeout(Duration::from_secs(2), rx.recv())
            .await
            .expect("expected recovery terminal event")
            .expect("event channel open");
        match event.msg {
            EventMsg::TurnStarted(_) => saw_turn_started = true,
            EventMsg::TurnAborted(event) => {
                assert_eq!(event.turn_id.as_deref(), Some(turn_id));
                assert_eq!(event.reason, TurnAbortReason::Interrupted);
                saw_turn_aborted = true;
                break;
            }
            _ => {}
        }
    }
    assert!(
        !saw_turn_started,
        "aborted recovery must not prove TurnStarted"
    );
    assert!(
        saw_turn_aborted,
        "recovery abort must publish a terminal event"
    );
    assert!(session.active_turn.lock().await.is_none());
    assert!(session.is_interrupted());
    assert!(
        session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned")
            .is_none()
    );

    let in_memory = session.clone_history().await;
    assert!(in_memory.raw_items().any(|item| {
        matches!(
            item,
            ResponseItem::Message { content, .. }
                if content.iter().any(|content| {
                    matches!(
                        content,
                        ContentItem::InputText { text }
                            if text == "recovery tail must survive abort"
                    )
                })
        )
    }));
    let durable = store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("load durable recovery-abort history");
    assert!(durable.items.iter().any(|item| {
        matches!(
            item,
            RolloutItem::ResponseItem(envelope)
                if matches!(&envelope.item, ResponseItem::Message { content, .. }
                    if content.iter().any(|content| {
                    matches!(
                        content,
                        ContentItem::InputText { text }
                            if text == "recovery tail must survive abort"
                    )
                }))
        )
    }));
    assert!(durable.items.iter().any(|item| {
        matches!(item, RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn_id)
    }));
    assert!(!durable.items.iter().any(|item| {
        matches!(
            item,
            RolloutItem::EventMsg(EventMsg::TurnStarted(started))
                if started.turn_id == turn_id
        )
    }));
}

#[tokio::test]
async fn abort_all_revalidates_ready_after_task_quiesces() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let turn_id = "abort-all-revokes-stale-ready";
    let turn_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    session
        .spawn_task(
            turn_context,
            Vec::new(),
            RecoverableRevokingOnCancelTask::new(),
        )
        .await
        .expect("revoking recovery task should start");

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    wait_until_idle(session.as_ref()).await;

    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
}

#[tokio::test]
async fn abort_turn_if_active_revalidates_ready_after_task_quiesces() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let turn_id = "abort-exact-revokes-stale-ready";
    let turn_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    session
        .spawn_task(
            turn_context,
            Vec::new(),
            RecoverableRevokingOnCancelTask::new(),
        )
        .await
        .expect("revoking recovery task should start");

    assert!(
        session
            .abort_turn_if_active(turn_id, TurnAbortReason::Interrupted)
            .await
    );
    wait_until_idle(session.as_ref()).await;

    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
}

#[tokio::test]
async fn abort_turn_if_active_publishes_unchanged_in_flight_ready() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let turn_id = "abort-exact-preserves-ready";
    // Use the same valid replay/fingerprint fixture as the other recovery
    // tests.  Constructing only a durable Ready bit is intentionally
    // fail-closed and cannot authorize a recovery candidate.
    let _authority = spawn_ready_recoverable_task(&session, turn_id).await;

    assert!(
        session
            .abort_turn_if_active(turn_id, TurnAbortReason::Interrupted)
            .await
    );
    wait_until_idle(session.as_ref()).await;

    assert!(session.recovery_epoch_if_idle(turn_id).await.is_some());
}

#[tokio::test]
async fn recovery_candidate_uses_task_attach_epoch_not_later_global_epoch() {
    let (session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let turn_id = "attach-epoch-model-turn";
    let _authority = spawn_ready_recoverable_task(&session, turn_id).await;
    let attach_epoch = session
        .active_turn
        .lock()
        .await
        .as_ref()
        .and_then(|active| active.task.as_ref())
        .map(|task| task.attach_epoch)
        .expect("recoverable task should be attached");
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), attach_epoch);

    // Simulate an interleaving history generation after the task attached.
    session.turn_epoch.fetch_add(1, Ordering::AcqRel);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    wait_until_idle(session.as_ref()).await;

    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
}

async fn spawn_ready_recoverable_task(
    session: &Arc<Session>,
    turn_id: &str,
) -> Arc<TurnRecoveryAuthority> {
    let turn_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    let task = RecoverableNeverEndingModelTask::new(/*ready*/ false);
    let authority = Arc::clone(&task.authority);
    session
        .spawn_task(turn_context, Vec::new(), task)
        .await
        .expect("recoverable task should start");
    let persistence_failure_baseline = session.rollout_persistence_failure_generation();
    assert_eq!(
        session
            .mark_recovery_ready_for_sampling(
                turn_id,
                &authority,
                persistence_failure_baseline,
                "turn-input-test-request-fingerprint",
            )
            .await
            .expect("Ready marker should append and flush"),
        RecoveryReadyForSampling::Ready,
    );
    authority
}

async fn assert_recovery_authority_poisoned(authority: &TurnRecoveryAuthority) {
    timeout(Duration::from_secs(2), async {
        loop {
            if !authority.ready.load(Ordering::Acquire)
                && let Ok(state) = authority.state.try_lock()
                && state.poisoned
                && state.ready_persistence_failure_generation.is_none()
            {
                return;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("detached recovery authority should become poisoned");
}

async fn assert_cold_replay_has_no_recovery_candidate(
    store: &InMemoryThreadStore,
    session: &Session,
) {
    let history = store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("persisted recovery history should load");
    let mut builder = ThreadHistoryBuilder::new();
    for item in &history.items {
        builder.handle_rollout_item(item);
    }
    assert_eq!(builder.recovery_candidate_turn_id(), None);
}

async fn wait_for_persisted_recovery_marker(
    store: &InMemoryThreadStore,
    session: &Session,
    expected_state: TurnRecoveryCandidateState,
) {
    timeout(Duration::from_secs(2), async {
        loop {
            let history = store
                .load_history(LoadThreadHistoryParams {
                    thread_id: session.thread_id,
                    include_archived: true,
                })
                .await
                .expect("persisted recovery history should load");
            if history.items.iter().any(|item| {
                matches!(
                    item,
                    RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                        if marker.state == expected_state
                )
            }) {
                return;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("expected recovery marker should become durable");
}

async fn test_recovery_replay(
    session: &Session,
    turn_id: &str,
) -> codex_history::TurnRecoveryReplayV1 {
    codex_history::TurnRecoveryReplayV1 {
        history_boundary: session
            .current_recovery_history_boundary()
            .await
            .expect("test history boundary"),
        turn_context_sha256: "crash-window-test-turn-context".to_string(),
        start: codex_history::TurnRecoveryStartState {
            final_output_json_schema: None,
            parent_turn_id: None,
            root_turn_id: Some(turn_id.to_string()),
            responses_metadata_extra: Default::default(),
        },
        environments: Vec::new(),
    }
}

async fn persisted_recovery_markers(
    store: &InMemoryThreadStore,
    session: &Session,
) -> Vec<(u64, TurnRecoveryCandidateState)> {
    store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("persisted recovery history should load")
        .items
        .into_iter()
        .filter_map(|item| {
            let RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker)) = item else {
                return None;
            };
            Some((marker.generation, marker.state))
        })
        .collect()
}

async fn assert_ready_direct_persistence_fault_is_revoked(
    fault: RolloutPersistenceFault,
    positive_marker_was_appended: bool,
) {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "ready-direct-persistence-fault";
    let authority = TurnRecoveryAuthority::default();
    let replay = test_recovery_replay(session.as_ref(), turn_id).await;
    session.inject_rollout_persistence_fault(fault).await;

    let err = session
        .mark_turn_recovery_ready(
            turn_id,
            &authority,
            /*persistence_failure_baseline*/ 0,
            "ready-direct-persistence-fingerprint",
            &replay,
        )
        .await
        .expect_err("a direct Ready persistence fault must fail closed");

    assert!(err.to_string().contains("recovery provenance"));
    assert!(!authority.ready.load(Ordering::Acquire));
    {
        let state = authority.state.lock().await;
        assert_eq!(state.generation, 1);
        assert_eq!(state.durable_state, DurableRecoveryState::Unready);
        assert!(state.poisoned);
        assert!(state.ready_persistence_failure_generation.is_none());
        assert!(state.request_fingerprint_sha256.is_none());
        assert!(state.replay.is_none());
    }
    assert!(
        session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned")
            .is_none()
    );
    let markers = persisted_recovery_markers(store.as_ref(), session.as_ref()).await;
    assert_eq!(
        markers
            .iter()
            .any(|(generation, state)| *generation == 0
                && *state == TurnRecoveryCandidateState::Ready),
        positive_marker_was_appended
    );
    assert_eq!(
        markers.last(),
        Some(&(1, TurnRecoveryCandidateState::Unready))
    );
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

async fn assert_confirmed_direct_persistence_fault_is_revoked(
    fault: RolloutPersistenceFault,
    positive_marker_was_appended: bool,
) {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "confirmed-direct-persistence-fault";
    let authority = TurnRecoveryAuthority::default();
    let replay = test_recovery_replay(session.as_ref(), turn_id).await;
    session
        .mark_turn_recovery_ready(
            turn_id,
            &authority,
            /*persistence_failure_baseline*/ 0,
            "confirmed-direct-persistence-fingerprint",
            &replay,
        )
        .await
        .expect("initial Ready should be durable");
    let generation = session
        .prepare_turn_recovery_for_controlled_detach(turn_id, &authority)
        .await
        .expect("pre-confirmation Unready should be durable");
    assert_eq!(generation, 1);
    session.inject_rollout_persistence_fault(fault).await;

    let err = session
        .confirm_interrupted_turn_recovery(
            turn_id,
            &authority,
            generation,
            /*persistence_failure_generation*/ 0,
            "confirmed-direct-persistence-fingerprint",
            &replay,
        )
        .await
        .expect_err("a direct InterruptedConfirmed persistence fault must fail closed");

    assert!(err.to_string().contains("recovery provenance"));
    assert!(!authority.ready.load(Ordering::Acquire));
    {
        let state = authority.state.lock().await;
        assert_eq!(state.generation, 2);
        assert_eq!(state.durable_state, DurableRecoveryState::Unready);
        assert!(state.poisoned);
        assert!(state.ready_persistence_failure_generation.is_none());
        assert!(state.request_fingerprint_sha256.is_none());
        assert!(state.replay.is_none());
    }
    assert!(
        session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned")
            .is_none()
    );
    let markers = persisted_recovery_markers(store.as_ref(), session.as_ref()).await;
    assert_eq!(
        markers.iter().any(|(marker_generation, state)| {
            *marker_generation == generation
                && *state == TurnRecoveryCandidateState::InterruptedConfirmed
        }),
        positive_marker_was_appended
    );
    assert_eq!(
        markers.last(),
        Some(&(2, TurnRecoveryCandidateState::Unready))
    );
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn ready_append_error_persists_strictly_newer_unready() {
    assert_ready_direct_persistence_fault_is_revoked(
        RolloutPersistenceFault::TurnRecoveryReadyAppend,
        /*positive_marker_was_appended*/ false,
    )
    .await;
}

#[tokio::test]
async fn ready_flush_error_persists_strictly_newer_unready() {
    assert_ready_direct_persistence_fault_is_revoked(
        RolloutPersistenceFault::TurnRecoveryReadyFlush,
        /*positive_marker_was_appended*/ true,
    )
    .await;
}

#[tokio::test]
async fn interrupted_confirmed_append_error_persists_strictly_newer_unready() {
    assert_confirmed_direct_persistence_fault_is_revoked(
        RolloutPersistenceFault::TurnRecoveryInterruptedConfirmedAppend,
        /*positive_marker_was_appended*/ false,
    )
    .await;
}

#[tokio::test]
async fn interrupted_confirmed_flush_error_persists_strictly_newer_unready() {
    assert_confirmed_direct_persistence_fault_is_revoked(
        RolloutPersistenceFault::TurnRecoveryInterruptedConfirmedFlush,
        /*positive_marker_was_appended*/ true,
    )
    .await;
}

#[tokio::test]
async fn ready_and_successor_unready_append_errors_remain_poisoned_fail_stop() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "ready-and-successor-unready-append-errors";
    let authority = TurnRecoveryAuthority::default();
    let replay = test_recovery_replay(session.as_ref(), turn_id).await;
    session
        .inject_rollout_persistence_fault(RolloutPersistenceFault::TurnRecoveryReadyAppend)
        .await;
    session
        .inject_rollout_persistence_fault(RolloutPersistenceFault::TurnRecoveryUnreadyAppend)
        .await;

    session
        .mark_turn_recovery_ready(
            turn_id,
            &authority,
            /*persistence_failure_baseline*/ 0,
            "ready-double-persistence-fingerprint",
            &replay,
        )
        .await
        .expect_err("positive and successor persistence failures must remain fail-stop");

    assert!(!authority.ready.load(Ordering::Acquire));
    {
        let state = authority.state.lock().await;
        assert_eq!(state.generation, 0);
        assert_eq!(state.durable_state, DurableRecoveryState::Unknown);
        assert!(state.poisoned);
        assert!(state.ready_persistence_failure_generation.is_none());
        assert!(state.request_fingerprint_sha256.is_none());
        assert!(state.replay.is_none());
    }
    assert_eq!(session.rollout_persistence_failure_generation(), 2);
    assert!(
        persisted_recovery_markers(store.as_ref(), session.as_ref())
            .await
            .is_empty()
    );
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn ready_post_flush_generation_race_persists_strictly_newer_unready() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "ready-post-flush-generation-race";
    let authority = Arc::new(TurnRecoveryAuthority::default());
    let replay = test_recovery_replay(session.as_ref(), turn_id).await;
    let session_for_ready = Arc::clone(&session);
    let authority_for_ready = Arc::clone(&authority);
    let ready = tokio::spawn(async move {
        session_for_ready
            .mark_turn_recovery_ready(
                turn_id,
                authority_for_ready.as_ref(),
                /*persistence_failure_baseline*/ 0,
                "ready-post-flush-fingerprint",
                &replay,
            )
            .await
    });

    wait_for_persisted_recovery_marker(
        store.as_ref(),
        session.as_ref(),
        TurnRecoveryCandidateState::Ready,
    )
    .await;
    session.mark_rollout_persistence_failure();

    let err = ready
        .await
        .expect("Ready publisher should join")
        .expect_err("post-flush failure generation drift must reject Ready");
    assert!(err.to_string().contains("changed while publishing Ready"));
    assert!(!authority.ready.load(Ordering::Acquire));
    {
        let state = authority.state.lock().await;
        assert_eq!(state.generation, 1);
        assert_eq!(state.durable_state, DurableRecoveryState::Unready);
        assert!(state.poisoned);
        assert!(state.request_fingerprint_sha256.is_none());
        assert!(state.replay.is_none());
    }
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn confirmed_post_flush_generation_race_persists_strictly_newer_unready() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "confirmed-post-flush-generation-race";
    let authority = Arc::new(TurnRecoveryAuthority::default());
    let replay = test_recovery_replay(session.as_ref(), turn_id).await;
    session
        .mark_turn_recovery_ready(
            turn_id,
            authority.as_ref(),
            /*persistence_failure_baseline*/ 0,
            "confirmed-post-flush-fingerprint",
            &replay,
        )
        .await
        .expect("initial Ready should be durable");
    let generation = session
        .prepare_turn_recovery_for_controlled_detach(turn_id, authority.as_ref())
        .await
        .expect("pre-confirmation Unready should be durable");
    assert_eq!(generation, 1);

    let session_for_confirmation = Arc::clone(&session);
    let authority_for_confirmation = Arc::clone(&authority);
    let replay_for_confirmation = replay.clone();
    let confirmation = tokio::spawn(async move {
        session_for_confirmation
            .confirm_interrupted_turn_recovery(
                turn_id,
                authority_for_confirmation.as_ref(),
                generation,
                /*persistence_failure_generation*/ 0,
                "confirmed-post-flush-fingerprint",
                &replay_for_confirmation,
            )
            .await
    });

    wait_for_persisted_recovery_marker(
        store.as_ref(),
        session.as_ref(),
        TurnRecoveryCandidateState::InterruptedConfirmed,
    )
    .await;
    session.mark_rollout_persistence_failure();

    let err = confirmation
        .await
        .expect("confirmation publisher should join")
        .expect_err("post-flush failure generation drift must reject confirmation");
    assert!(
        err.to_string()
            .contains("changed while confirming interruption")
    );
    assert!(!authority.ready.load(Ordering::Acquire));
    {
        let state = authority.state.lock().await;
        assert_eq!(state.generation, 2);
        assert_eq!(state.durable_state, DurableRecoveryState::Unready);
        assert!(state.poisoned);
        assert!(state.request_fingerprint_sha256.is_none());
        assert!(state.replay.is_none());
    }
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn exhausted_generation_never_persists_positive_recovery_authority() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "generation-exhausted";
    let replay = test_recovery_replay(session.as_ref(), turn_id).await;

    let ready_authority = TurnRecoveryAuthority::resumed_at_unready_generation(u64::MAX);
    let ready_err = session
        .mark_turn_recovery_ready(
            turn_id,
            &ready_authority,
            /*persistence_failure_baseline*/ 0,
            "generation-exhausted-ready",
            &replay,
        )
        .await
        .expect_err("Ready at the maximum generation must fail closed");
    assert!(ready_err.to_string().contains("generation exhausted"));

    let confirmed_authority = TurnRecoveryAuthority::resumed_at_unready_generation(u64::MAX);
    let confirmed_err = session
        .confirm_interrupted_turn_recovery(
            turn_id,
            &confirmed_authority,
            u64::MAX,
            /*persistence_failure_generation*/ 0,
            "generation-exhausted-confirmed",
            &replay,
        )
        .await
        .expect_err("confirmation at the maximum generation must fail closed");
    assert!(confirmed_err.to_string().contains("generation exhausted"));

    let history = store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("persisted recovery history should load");
    assert!(!history.items.iter().any(|item| {
        matches!(
            item,
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                if matches!(
                    marker.state,
                    TurnRecoveryCandidateState::Ready
                        | TurnRecoveryCandidateState::InterruptedConfirmed
                )
        )
    }));
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn exhausted_recovery_candidate_rejects_restart_consume_and_replay_handoff() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "candidate-generation-exhausted";
    let expected_epoch = seed_recovery_candidate(session.as_ref(), turn_id).await;
    let candidate = {
        let mut candidate = session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned");
        let candidate = candidate.as_mut().expect("seeded recovery candidate");
        candidate.marker_generation = u64::MAX;
        candidate.clone()
    };

    let restart_err = handle_recovery(
        &session,
        expected_epoch,
        ThreadSettingsOverrides::default(),
        turn_id.to_string(),
    )
    .await
    .expect_err("an exhausted candidate must not reserve or restart a turn");
    assert!(restart_err.to_string().contains("generation exhausted"));
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), expected_epoch);

    let consume_err = session
        .consume_recovery_candidate_for_mutation()
        .await
        .expect_err("an exhausted candidate must not be consumed with a saturated generation");
    assert!(consume_err.to_string().contains("generation exhausted"));
    assert_eq!(session.turn_epoch.load(Ordering::Acquire), expected_epoch);
    assert_eq!(
        session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned")
            .as_ref(),
        Some(&candidate)
    );

    let handoff_err = session
        .persist_recovery_replay_applied(
            turn_id,
            u64::MAX,
            u64::MAX,
            &candidate.request_fingerprint_sha256,
            &candidate.replay,
        )
        .await
        .expect_err("an exhausted source generation must not mint a replay-applied binding");
    assert!(handoff_err.to_string().contains("generation exhausted"));

    let persisted = store
        .load_history(LoadThreadHistoryParams {
            thread_id: session.thread_id,
            include_archived: true,
        })
        .await
        .expect("persisted recovery history should load");
    assert!(!persisted.items.iter().any(|item| {
        matches!(
            item,
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(_))
                | RolloutItem::TurnRecoveryRequestBinding(_)
        )
    }));
}

#[tokio::test]
async fn abort_all_does_not_publish_when_turn_aborted_append_fails_but_flush_succeeds() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "abort-all-terminal-append-failure";
    let authority = spawn_ready_recoverable_task(&session, turn_id).await;
    let ready_failure_generation = session.rollout_persistence_failure_generation();
    let flushes_before_abort = store.calls().await.flush_thread;
    session
        .inject_rollout_persistence_fault(RolloutPersistenceFault::TurnAbortedAppend)
        .await;

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    wait_until_idle(session.as_ref()).await;

    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
    assert_eq!(
        session.rollout_persistence_failure_generation(),
        ready_failure_generation + 1
    );
    assert!(
        store.calls().await.flush_thread > flushes_before_abort,
        "terminal durability barrier should still run after the injected append failure"
    );
    assert_recovery_authority_poisoned(authority.as_ref()).await;
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn abort_turn_if_active_does_not_publish_when_interrupt_marker_append_fails() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "abort-exact-marker-append-failure";
    let authority = spawn_ready_recoverable_task(&session, turn_id).await;
    let ready_failure_generation = session.rollout_persistence_failure_generation();
    let flushes_before_abort = store.calls().await.flush_thread;
    session
        .inject_rollout_persistence_fault(RolloutPersistenceFault::InterruptedMarkerAppend)
        .await;

    assert!(
        session
            .abort_turn_if_active(turn_id, TurnAbortReason::Interrupted)
            .await
    );
    wait_until_idle(session.as_ref()).await;

    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
    assert_eq!(
        session.rollout_persistence_failure_generation(),
        ready_failure_generation + 1
    );
    assert!(
        store.calls().await.flush_thread > flushes_before_abort,
        "marker and terminal durability barriers should run after the injected append failure"
    );
    assert_recovery_authority_poisoned(authority.as_ref()).await;
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn on_task_finished_does_not_publish_after_ordinary_append_fails_post_ready() {
    let (mut session, _turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let store = attach_in_memory_thread_store(
        Arc::get_mut(&mut session).expect("session should be uniquely owned"),
    )
    .await;
    let turn_id = "task-finished-post-ready-append-failure";
    let turn_context = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    let task = RecoverableFinishOnSignalTask::new();
    let authority = Arc::clone(&task.authority);
    let finish = Arc::clone(&task.finish);
    session
        .spawn_task(Arc::clone(&turn_context), Vec::new(), task)
        .await
        .expect("finishing recovery task should start");
    let persistence_failure_baseline = session.rollout_persistence_failure_generation();
    assert_eq!(
        session
            .mark_recovery_ready_for_sampling(
                turn_id,
                &authority,
                persistence_failure_baseline,
                "turn-input-test-request-fingerprint",
            )
            .await
            .expect("Ready marker should append and flush"),
        RecoveryReadyForSampling::Ready,
    );
    let flushes_before_finish = store.calls().await.flush_thread;
    session
        .inject_rollout_persistence_fault(RolloutPersistenceFault::WarningAppend)
        .await;
    session
        .send_event(
            turn_context.as_ref(),
            EventMsg::Warning(WarningEvent {
                message: "post-Ready ordinary persistence fault".to_string(),
            }),
        )
        .await;
    assert_eq!(
        session.rollout_persistence_failure_generation(),
        persistence_failure_baseline + 1
    );

    finish.notify_one();
    wait_until_idle(session.as_ref()).await;

    assert_eq!(session.recovery_epoch_if_idle(turn_id).await, None);
    assert!(
        store.calls().await.flush_thread > flushes_before_finish,
        "task-runner and terminal durability barriers should succeed after the ordinary append fault"
    );
    assert_recovery_authority_poisoned(authority.as_ref()).await;
    assert_cold_replay_has_no_recovery_candidate(store.as_ref(), session.as_ref()).await;
}

#[tokio::test]
async fn start_only_rejects_plan_mode_without_injecting() {
    let (session, _turn_context, _rx) = make_session_and_context_with_rx().await;
    let mut collaboration_mode = session.collaboration_mode().await;
    collaboration_mode.mode = ModeKind::Plan;
    {
        let mut state = session.state.lock().await;
        state.session_configuration.collaboration_mode = collaboration_mode;
    }

    let submission = submit_start_only(
        &session,
        SubmittedTurnInput::ResponseItem(user_message("synthetic idle input")),
    )
    .await;

    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::PlanMode,
        },
        submission
    );
    assert!(session.active_turn.lock().await.is_none());
    assert_eq!(
        (Vec::<TurnInput>::new(), None, None),
        session
            .input_queue
            .get_pending_input(&session.active_turn)
            .await
    );
}

#[tokio::test]
async fn start_only_accepts_user_input_in_plan_mode() {
    let (session, _turn_context, _rx) = make_session_and_context_with_rx().await;
    let mut collaboration_mode = session.collaboration_mode().await;
    collaboration_mode.mode = ModeKind::Plan;
    {
        let mut state = session.state.lock().await;
        state.session_configuration.collaboration_mode = collaboration_mode;
        state.merge_connector_selection(["calendar".to_string()]);
    }

    let submission = submit_start_only(
        &session,
        SubmittedTurnInput::UserInput {
            content: vec![UserInput::Text {
                text: "queued user input".to_string(),
                text_elements: Vec::new(),
            }],
            client_id: Some("queued-user-message".to_string()),
        },
    )
    .await;
    assert!(matches!(submission, TurnInputSubmission::Started { .. }));
    assert!(
        session
            .state
            .lock()
            .await
            .get_connector_selection()
            .is_empty()
    );

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[tokio::test]
async fn start_only_rejects_empty_user_input_in_plan_mode() {
    let (session, _turn_context, _rx) = make_session_and_context_with_rx().await;
    let mut collaboration_mode = session.collaboration_mode().await;
    collaboration_mode.mode = ModeKind::Plan;
    {
        let mut state = session.state.lock().await;
        state.session_configuration.collaboration_mode = collaboration_mode;
    }

    let submission = submit_start_only(
        &session,
        SubmittedTurnInput::UserInput {
            content: Vec::new(),
            client_id: Some("empty-queued-user-message".to_string()),
        },
    )
    .await;

    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::PlanMode,
        },
        submission
    );
    assert!(session.active_turn.lock().await.is_none());
}

#[tokio::test]
async fn start_only_rejects_pending_trigger_turn_without_injecting() {
    let (session, _turn_context, _rx) = make_session_and_context_with_rx().await;
    session
        .input_queue
        .enqueue_mailbox_communication(
            InterAgentCommunication::new(
                AgentPath::root(),
                AgentPath::root(),
                Vec::new(),
                "pending trigger".to_string(),
                /*trigger_turn*/ true,
            ),
            /*parent_turn_id*/ None,
            /*root_turn_id*/ None,
        )
        .await;

    let submission = submit_start_only(
        &session,
        SubmittedTurnInput::ResponseItem(user_message("synthetic idle input")),
    )
    .await;

    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::PendingTriggerTurn,
        },
        submission
    );
    assert!(session.active_turn.lock().await.is_none());
    assert!(session.input_queue.has_trigger_turn_mailbox_items().await);
}

#[tokio::test]
async fn steer_only_requires_active_turn() {
    let (session, _turn_context, _rx) = make_session_and_context_with_rx().await;
    let submission = submit_steer_only(
        &session,
        vec![UserInput::Text {
            text: "steer".to_string(),
            text_elements: Vec::new(),
        }],
        "missing-turn-id",
    )
    .await;

    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NoActiveTurn,
        },
        submission
    );
}

#[tokio::test]
async fn steer_only_enforces_expected_turn_id() {
    let (session, turn_context, _rx) = make_session_and_context_with_rx().await;
    session
        .spawn_task(
            Arc::clone(&turn_context),
            vec![TurnInput::UserInput {
                content: vec![UserInput::Text {
                    text: "hello".to_string(),
                    text_elements: Vec::new(),
                }],
                client_id: None,
            }],
            NeverEndingTask {
                kind: TaskKind::Regular,
                listen_to_cancellation_token: false,
            },
        )
        .await
        .expect("active task should start");

    let submission = submit_steer_only(
        &session,
        vec![UserInput::Text {
            text: "steer".to_string(),
            text_elements: Vec::new(),
        }],
        "different-turn-id",
    )
    .await;
    assert_eq!(
        TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::ExpectedTurnMismatch {
                expected: "different-turn-id".to_string(),
                actual: turn_context.sub_id.clone(),
            },
        },
        submission
    );
}

#[tokio::test]
async fn accepted_steer_revokes_ready_before_enqueue_and_blocks_stale_ready_checkpoint() {
    let (session, turn_context, _rx) = make_turn_recovery_session_and_context_with_rx().await;
    let task = RecoverableNeverEndingModelTask::new(/*ready*/ true);
    let authority = Arc::clone(&task.authority);
    {
        let mut state = authority.state.lock().await;
        state.durable_state = DurableRecoveryState::Ready;
    }
    session
        .spawn_task(Arc::clone(&turn_context), Vec::new(), task)
        .await
        .expect("recoverable task should start");

    let submission = submit_steer_only(
        &session,
        vec![UserInput::Text {
            text: "accepted steer".to_string(),
            text_elements: Vec::new(),
        }],
        &turn_context.sub_id,
    )
    .await;

    assert_eq!(
        submission,
        TurnInputSubmission::Steered {
            turn_id: turn_context.sub_id.clone(),
        }
    );
    assert!(!authority.ready.load(Ordering::Acquire));
    {
        let state = authority.state.lock().await;
        assert_eq!(state.generation, 1);
        assert_eq!(state.durable_state, DurableRecoveryState::Unready);
    }
    assert_eq!(
        session
            .mark_recovery_ready_for_sampling(
                &turn_context.sub_id,
                &authority,
                session.rollout_persistence_failure_generation(),
                "turn-input-test-request-fingerprint",
            )
            .await
            .expect("pending steer must fail closed without a persistence error"),
        RecoveryReadyForSampling::PendingInput,
    );
    assert!(!authority.ready.load(Ordering::Acquire));

    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
}

#[tokio::test]
async fn rejects_non_regular_turns() {
    for (task_kind, turn_kind) in [
        (TaskKind::Review, NonSteerableTurnKind::Review),
        (TaskKind::Compact, NonSteerableTurnKind::Compact),
    ] {
        let (session, incoming_turn_context, _rx) = make_session_and_context_with_rx().await;
        incoming_turn_context
            .turn_metadata_state
            .set_root_turn_id("incoming-root".to_string());
        let turn_context = session
            .new_default_turn_with_sub_id("turn".to_string())
            .await;
        turn_context
            .turn_metadata_state
            .set_root_turn_id("active-root".to_string());
        session
            .spawn_task(
                Arc::clone(&turn_context),
                vec![TurnInput::UserInput {
                    content: vec![UserInput::Text {
                        text: "hello".to_string(),
                        text_elements: Vec::new(),
                    }],
                    client_id: None,
                }],
                NeverEndingTask {
                    kind: task_kind,
                    listen_to_cancellation_token: true,
                },
            )
            .await
            .expect("non-regular task should start");

        let steer_input = vec![UserInput::Text {
            text: "steer".to_string(),
            text_elements: Vec::new(),
        }];
        let steer_submission = submit_steer_only(&session, steer_input.clone(), "turn").await;
        assert_eq!(
            TurnInputSubmission::NotSubmitted {
                reason: NotSubmittedReason::ActiveTurnNotSteerable { turn_kind },
            },
            steer_submission
        );
        let start_or_steer_submission = handle(
            &session,
            TurnInputRequest::user_input(steer_input),
            TurnInputMode::StartOrSteer,
            "test-submission".to_string(),
        )
        .await
        .expect("start-or-steer submission should be valid");
        assert_eq!(
            TurnInputSubmission::NotSubmitted {
                reason: NotSubmittedReason::ActiveTurnNotSteerable { turn_kind },
            },
            start_or_steer_submission
        );
        assert_eq!(
            turn_context.turn_metadata_state.root_turn_id().as_deref(),
            Some("active-root")
        );

        session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    }
}
