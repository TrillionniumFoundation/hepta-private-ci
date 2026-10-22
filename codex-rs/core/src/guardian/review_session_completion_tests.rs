use super::*;
use crate::session::TurnInput;
use crate::session::tests::attach_in_memory_thread_store;
use crate::session::tests::make_session_and_context_with_rx;
use crate::state::TaskKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::Submission;
use std::pin::Pin;
use std::task::Poll;
use tokio::sync::Notify;

const REVIEW_MESSAGE: &str = "completed review";
const FOLLOWUP_REMINDER: &str = "Use prior reviews as context, not binding precedent.";

#[derive(Default)]
struct FinishOwnerGate {
    entered: Notify,
    release: Notify,
}

impl codex_extension_api::ThreadLifecycleContributor<Config> for FinishOwnerGate {
    fn on_thread_idle<'a>(
        &'a self,
        _input: codex_extension_api::ThreadIdleInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.entered.notify_one();
            self.release.notified().await;
        })
    }
}

struct CompletingReviewTask;

impl SessionTask for CompletingReviewTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.guardian_finish_owner_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        Ok(Some(REVIEW_MESSAGE.to_string()))
    }
}

struct ReviewFixture {
    manager: GuardianReviewSessionManager,
    review_session: Arc<GuardianReviewSession>,
    submissions: async_channel::Receiver<Submission>,
    gate: Arc<FinishOwnerGate>,
}

impl ReviewFixture {
    async fn new(params: &GuardianReviewSessionParams) -> Self {
        let (mut session, _turn, rx_event) = make_session_and_context_with_rx().await;
        let gate = Arc::new(FinishOwnerGate::default());
        let mut builder = codex_extension_api::ExtensionRegistryBuilder::<Config>::new();
        builder.thread_lifecycle_contributor(gate.clone());
        let session_mut =
            Arc::get_mut(&mut session).expect("unique session before starting a task");
        attach_in_memory_thread_store(session_mut).await;
        session_mut.services.extensions = Arc::new(builder.build());
        let (tx_sub, submissions) = async_channel::bounded(/*cap*/ 4);
        let (_agent_status_tx, agent_status) =
            tokio::sync::watch::channel(AgentStatus::PendingInit);
        let reuse_key = GuardianReviewSessionReuseKey::from_spawn_config(
            &params.spawn_config,
            params.parent_session.user_instructions().await,
            params
                .parent_session
                .clone_history()
                .await
                .history_version(),
        )
        .with_environments(params.parent_context.environments())
        .with_node_repl_policy_eligibility(
            params
                .parent_context
                .turn()
                .model_info
                .node_repl_auto_review_required,
        );
        let review_session = Arc::new(GuardianReviewSession {
            session,
            io: SessionIo {
                tx_sub,
                rx_event,
                agent_status,
                session_loop_termination: crate::session::completed_session_loop_termination(),
            },
            cancel_token: CancellationToken::new(),
            reuse_key,
            review_lock: Semaphore::new(/*permits*/ 1),
            state: Mutex::new(GuardianReviewState {
                prior_review_count: 0,
                last_reviewed_transcript_cursor: None,
                last_admitted_node_repl_response_sequence: 0,
                pending_node_repl_evidence_admission: None,
                last_committed_fork_snapshot: None,
            }),
        });
        let manager = GuardianReviewSessionManager {
            state: Arc::new(Mutex::new(GuardianReviewSessionState {
                trunk: Some(Arc::clone(&review_session)),
                ephemeral_reviews: Vec::new(),
            })),
            ..Default::default()
        };
        Self {
            manager,
            review_session,
            submissions,
            gate,
        }
    }

    async fn start_task_and_hold_finish_owner(&self, submission: Submission) -> String {
        let turn_id = submission.id;
        let Op::TurnInput { reply, .. } = submission.op else {
            panic!("expected Guardian turn-input submission");
        };
        let turn = self
            .review_session
            .session
            .new_default_turn_with_sub_id(turn_id.clone())
            .await;
        self.review_session
            .session
            .spawn_task(turn, Vec::new(), CompletingReviewTask)
            .await
            .expect("start the real Core task behind the Guardian submission");
        self.gate.entered.notified().await;
        assert!(
            self.review_session
                .session
                .pending_normal_turn_finish_completion(&turn_id)
                .is_some(),
            "the real finish owner must remain behind the idle callback"
        );
        reply
            .send(Ok(TurnInputSubmission::Started {
                turn_id: turn_id.clone(),
            }))
            .expect("acknowledge the submitted turn using its actual task identity");
        turn_id
    }

    async fn assert_no_commit(&self, completed_reviews: usize) {
        assert!(
            self.review_session.io.rx_event.is_empty(),
            "the review must consume the real TurnComplete before this assertion"
        );
        assert!(
            self.review_session
                .session
                .has_pending_task_terminalization()
        );
        assert!(self.review_session.review_lock.try_acquire().is_err());
        let state = self.review_session.state.lock().await;
        assert_eq!(state.prior_review_count, completed_reviews);
        assert_eq!(
            state
                .last_committed_fork_snapshot
                .as_ref()
                .map(|snapshot| snapshot.prior_review_count),
            (completed_reviews > 0).then_some(completed_reviews),
            "a pending finish owner must not advance the committed fork snapshot"
        );
    }

    async fn release_finish_owner(&self, turn_id: &str) {
        let completion = self
            .review_session
            .session
            .pending_normal_turn_finish_completion(turn_id)
            .expect("only the original finish owner can release its completion");
        self.gate.release.notify_one();
        completion.await;
    }
}

async fn next_submission<F>(
    review: &mut F,
    submissions: &async_channel::Receiver<Submission>,
) -> Submission
where
    F: Future<Output = (GuardianReviewSessionOutcome, GuardianReviewAnalyticsResult)> + Unpin,
{
    tokio::select! {
        outcome = review => panic!("review finished before submitting its task: {:?}", outcome.0),
        submission = submissions.recv() => submission.expect("Guardian submission channel open"),
    }
}

async fn assert_review_pending<F: Future + Unpin>(review: &mut F) {
    let result =
        std::future::poll_fn(|context| Poll::Ready(Pin::new(&mut *review).poll(context))).await;
    assert!(
        result.is_pending(),
        "the finish owner must still block completion"
    );
}

fn reminder_count(items: &[RolloutItem]) -> usize {
    items
        .iter()
        .filter(|item| {
            let RolloutItem::ResponseItem(ResponseItem::Message { content, .. }) = item else {
                return false;
            };
            content.iter().any(|part| match part {
                ContentItem::InputText { text } | ContentItem::OutputText { text } => {
                    text.contains(FOLLOWUP_REMINDER)
                }
                ContentItem::InputImage { .. } | ContentItem::InputAudio { .. } => false,
            })
        })
        .count()
}

fn assert_completed(outcome: GuardianReviewSessionOutcome) {
    let GuardianReviewSessionOutcome::Completed(Ok(message)) = outcome else {
        panic!("expected normal Guardian completion: {outcome:?}");
    };
    assert_eq!(message.as_deref(), Some(REVIEW_MESSAGE));
}

#[tokio::test]
async fn normal_finish_owner_blocks_reuse_and_fork_before_followup_reminder() {
    let params = super::tests::test_review_params().await;
    let second_params = GuardianReviewSessionParams {
        parent_session: Arc::clone(&params.parent_session),
        parent_context: params.parent_context.clone(),
        spawn_config: params.spawn_config.clone(),
        request: params.request.clone(),
        reasons: params.reasons.clone(),
        schema: params.schema.clone(),
        model: params.model.clone(),
        reasoning_effort: params.reasoning_effort.clone(),
        guardian_default_review_model_id: params.guardian_default_review_model_id.clone(),
        guardian_catalog_contains_auto_review: params.guardian_catalog_contains_auto_review,
        guardian_review_model_overridden: params.guardian_review_model_overridden,
        guardian_review_model_override: params.guardian_review_model_override.clone(),
        reasoning_summary: params.reasoning_summary,
        personality: params.personality,
        external_cancel: params.external_cancel.clone(),
        deadline: params.deadline,
    };
    let fixture = ReviewFixture::new(&params).await;
    let mut first_review = Box::pin(fixture.manager.run_review(params));
    let submission = next_submission(&mut first_review, &fixture.submissions).await;
    let first_turn = fixture.start_task_and_hold_finish_owner(submission).await;

    // The event is real and already queued; the original idle callback owns the
    // barrier. One poll must consume it without publishing completion or a fork.
    assert_review_pending(&mut first_review).await;
    fixture.assert_no_commit(/*completed_reviews*/ 0).await;
    fixture.release_finish_owner(&first_turn).await;
    let (outcome, _) = first_review.await;
    assert_completed(outcome);

    let mut second_review = Box::pin(fixture.manager.run_review(second_params));
    let submission = next_submission(&mut second_review, &fixture.submissions).await;
    let persisted_items = load_rollout_items_for_fork(&fixture.review_session.session)
        .await
        .expect("load the original live thread")
        .expect("review thread persistence exists");
    assert_eq!(
        reminder_count(&persisted_items),
        1,
        "the original second-review injection must persist exactly one reminder"
    );
    let second_turn = fixture.start_task_and_hold_finish_owner(submission).await;
    assert_ne!(first_turn, second_turn);
    assert_review_pending(&mut second_review).await;
    fixture.assert_no_commit(/*completed_reviews*/ 1).await;
    fixture.release_finish_owner(&second_turn).await;
    let (outcome, _) = second_review.await;
    assert_completed(outcome);

    let committed = fixture
        .manager
        .committed_fork_rollout_items_for_test()
        .await
        .expect("original manager committed the second review snapshot");
    assert_eq!(reminder_count(&committed), 1);
    assert_eq!(
        fixture.review_session.state.lock().await.prior_review_count,
        2
    );
    let state = fixture.manager.state.lock().await;
    assert!(Arc::ptr_eq(
        state.trunk.as_ref().expect("reuse the original trunk"),
        &fixture.review_session,
    ));
}

#[tokio::test]
async fn cancel_after_turn_complete_does_not_reuse_or_retire_finish_owner() {
    let mut params = super::tests::test_review_params().await;
    let cancel = CancellationToken::new();
    params.external_cancel = Some(cancel.clone());
    let fixture = ReviewFixture::new(&params).await;
    let mut review = Box::pin(fixture.manager.run_review(params));
    let submission = next_submission(&mut review, &fixture.submissions).await;
    let turn_id = fixture.start_task_and_hold_finish_owner(submission).await;
    assert_review_pending(&mut review).await;
    fixture.assert_no_commit(/*completed_reviews*/ 0).await;

    cancel.cancel();
    let (outcome, _) = review.await;
    assert!(matches!(outcome, GuardianReviewSessionOutcome::Aborted));
    assert!(fixture.manager.state.lock().await.trunk.is_none());
    let state = fixture.review_session.state.lock().await;
    assert_eq!(state.prior_review_count, 0);
    assert!(state.last_committed_fork_snapshot.is_none());
    drop(state);
    fixture.release_finish_owner(&turn_id).await;
}

#[tokio::test]
async fn expired_deadline_does_not_complete_or_retire_normal_finish_owner() {
    let params = super::tests::test_review_params().await;
    let fixture = ReviewFixture::new(&params).await;
    let mut review = Box::pin(fixture.manager.run_review(params));
    let submission = next_submission(&mut review, &fixture.submissions).await;
    let turn_id = fixture.start_task_and_hold_finish_owner(submission).await;
    assert_review_pending(&mut review).await;
    fixture.assert_no_commit(/*completed_reviews*/ 0).await;

    let completion = fixture
        .review_session
        .session
        .pending_normal_turn_finish_completion(&turn_id)
        .expect("observe the same original finish owner without taking ownership");
    let outcome = run_before_review_deadline(
        tokio::time::Instant::now(),
        /*external_cancel*/ None,
        completion,
    )
    .await;
    assert!(matches!(
        outcome,
        Err(GuardianReviewSessionOutcome::TimedOut)
    ));
    fixture.assert_no_commit(/*completed_reviews*/ 0).await;

    // Expiring this observer cannot release the owner or complete another observer.
    assert_review_pending(&mut review).await;
    fixture.release_finish_owner(&turn_id).await;
    let (outcome, _) = review.await;
    assert_completed(outcome);
}
