use super::*;
use crate::agent::AgentStatus;
use crate::session::session_loop_termination_from_handle;
use crate::session::tests::attach_in_memory_thread_store;
use crate::session::tests::make_session_and_context_with_rx;
use crate::state::StartTransitionCompletion;
use crate::state::TaskKind;
use crate::state::TaskTerminalizationKind;
use crate::state::TurnRecoveryAuthority;
use crate::tasks::RecoveryReadyForSampling;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use codex_history::RolloutItem;
use codex_protocol::ResponseItemId;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::models::ContentItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Submission;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnRecoveryCandidateState;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;
use std::time::Duration;
use test_case::test_case;
use tokio::sync::watch;
use tokio::task::AbortHandle;

struct Fixture {
    session: Arc<Session>,
    turn_context: Arc<TurnContext>,
    io: Arc<SessionIo>,
    store: Arc<codex_thread_store::InMemoryThreadStore>,
    _submissions: async_channel::Receiver<Submission>,
    actor: AbortHandle,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.actor.abort();
    }
}

async fn fixture(initial_context: bool) -> Fixture {
    let (mut session, mut turn_context, rx_event) = make_session_and_context_with_rx().await;
    for feature in [
        Feature::RetainClientDeveloperMessages,
        Feature::HeptaTurnRecovery,
    ] {
        let _ = Arc::get_mut(&mut session)
            .expect("fresh session")
            .features
            .enable(feature);
        let _ = Arc::make_mut(&mut Arc::get_mut(&mut turn_context).expect("fresh turn").config)
            .features
            .enable(feature);
    }
    Arc::get_mut(&mut turn_context).expect("fresh turn").sub_id =
        "client-injection-live".to_string();
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("fresh session")).await;
    if initial_context {
        session
            .state
            .lock()
            .await
            .set_reference_context_item(Some(turn_context.to_turn_context_item()));
    }
    let (tx_sub, submissions) = async_channel::bounded(4);
    let actor = tokio::spawn(std::future::pending::<()>());
    let actor_abort = actor.abort_handle();
    let io = Arc::new(SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    });
    Fixture {
        session,
        turn_context,
        io,
        store,
        _submissions: submissions,
        actor: actor_abort,
    }
}

fn item() -> ResponseItem {
    ResponseItem::Message {
        id: Some(ResponseItemId::with_suffix(
            "client",
            "injection-exact-item",
        )),
        role: "developer".to_string(),
        content: vec![ContentItem::InputText {
            text: "preserve these exact client-authored bytes".to_string(),
        }],
        phase: None,
        // A complete canonical input makes full-envelope equality stable and
        // proves that retries do not replace its original metadata.
        internal_chat_message_metadata_passthrough: Some(
            serde_json::from_value(serde_json::json!({
                "turn_id": "client-origin-turn",
                "create_time": 1_700_000_000,
                "content_item_kinds": ["unknown"],
            }))
            .expect("complete original message metadata"),
        ),
    }
}

fn expected_envelope() -> ResponseItemEnvelope {
    ResponseItemEnvelope {
        item: item(),
        metadata: Some(CodexHarnessMetadata {
            client_authored: true,
        }),
    }
}

async fn recorded_items(fixture: &Fixture) -> Vec<ResponseItemEnvelope> {
    fixture
        .session
        .live_thread()
        .expect("attached history store")
        .load_history(/*include_archived*/ true)
        .await
        .expect("history snapshot")
        .items
        .into_iter()
        .filter_map(|item| match item {
            RolloutItem::ResponseItem(envelope)
                if matches!(&envelope.item, ResponseItem::Message { id: Some(id), .. }
                    if id.as_str() == "client_injection-exact-item") =>
            {
                Some(envelope)
            }
            _ => None,
        })
        .collect()
}

fn serialized_envelopes(items: Vec<ResponseItemEnvelope>) -> serde_json::Value {
    serde_json::to_value(
        items
            .into_iter()
            .map(RolloutItem::ResponseItem)
            .collect::<Vec<_>>(),
    )
    .expect("complete rollout envelopes")
}

fn assert_invalid_request(result: CodexResult<()>) {
    let error = result.expect_err("ordinary admission must reject");
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InvalidRequest(_)
    ));
}

async fn assert_recorded_once(fixture: &Fixture) {
    assert_eq!(
        serialized_envelopes(recorded_items(fixture).await),
        serialized_envelopes(vec![expected_envelope()]),
    );
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

async fn captured(completion: &Arc<StartTransitionCompletion>) {
    tokio::time::timeout(Duration::from_secs(2), async {
        // The local observer and registry own two references. A third is the
        // actual admission result retained by the external waiting caller.
        while Arc::strong_count(completion) < 3 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("the actual injection decision must capture its exact Finish owner");
}

fn spawn_injection(fixture: &Fixture) -> tokio::task::JoinHandle<CodexResult<()>> {
    let io = Arc::clone(&fixture.io);
    let session = Arc::clone(&fixture.session);
    tokio::spawn(async move {
        io.inject_response_items_after_finish(&session, vec![item()])
            .await
    })
}

async fn join(waiter: tokio::task::JoinHandle<CodexResult<()>>) -> CodexResult<()> {
    tokio::time::timeout(Duration::from_secs(2), waiter)
        .await
        .expect("injection caller must complete")
        .expect("injection caller task")
}

#[tokio::test]
async fn external_injection_waits_for_all_exact_finish_owners_and_records_once() {
    let fixture = fixture(/*initial_context*/ true).await;
    let first = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let second = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await.append_items;
    let waiter = spawn_injection(&fixture);
    captured(&first).await;
    captured(&second).await;
    assert_eq!(fixture.store.calls().await.append_items, before);
    finish_fence(&fixture.session, &first);
    assert!(!waiter.is_finished());
    assert!(!second.is_complete());
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &second);
    join(waiter)
        .await
        .expect("ordinary admission after both exact owners");
    assert_recorded_once(&fixture).await;
}

#[tokio::test]
async fn retired_finish_before_admission_does_not_leave_a_stale_rejection() {
    let fixture = fixture(/*initial_context*/ true).await;
    let retired = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    finish_fence(&fixture.session, &retired);
    join(spawn_injection(&fixture))
        .await
        .expect("fresh clear admission");
    assert_recorded_once(&fixture).await;
}

#[tokio::test]
async fn replacement_finish_owner_requires_its_own_new_admission_and_wait() {
    let fixture = fixture(/*initial_context*/ true).await;
    let old = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let waiter = spawn_injection(&fixture);
    captured(&old).await;
    let new = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    finish_fence(&fixture.session, &old);
    captured(&new).await;
    assert!(recorded_items(&fixture).await.is_empty());
    assert!(!waiter.is_finished());
    finish_fence(&fixture.session, &new);
    join(waiter).await.expect("fresh admission after new owner");
    assert_recorded_once(&fixture).await;
}

#[tokio::test]
async fn replacement_abort_owner_does_not_inherit_finish_retry_authority() {
    let fixture = fixture(/*initial_context*/ true).await;
    let old = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let waiter = spawn_injection(&fixture);
    captured(&old).await;
    let abort = install_fence(&fixture.session, TaskTerminalizationKind::Abort);
    finish_fence(&fixture.session, &old);
    assert_invalid_request(join(waiter).await);
    assert!(recorded_items(&fixture).await.is_empty());
    assert!(!abort.is_complete());
    finish_fence(&fixture.session, &abort);
}

#[tokio::test]
async fn cancelled_injection_does_not_write_initial_context_or_release_the_owner() {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await.append_items;
    let waiter = spawn_injection(&fixture);
    captured(&fence).await;
    waiter.abort();
    assert!(waiter.await.expect_err("cancelled caller").is_cancelled());
    assert_eq!(Arc::strong_count(&fence), 2);
    assert!(!fence.is_complete());
    assert!(fixture.session.reference_context_item().await.is_none());
    assert_eq!(fixture.store.calls().await.append_items, before);
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &fence);
}

#[tokio::test]
async fn actor_termination_releases_the_waiter_without_injecting() {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await.append_items;
    let waiter = spawn_injection(&fixture);
    captured(&fence).await;
    fixture.actor.abort();
    let error = join(waiter).await.expect_err("actor terminated");
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InternalAgentDied
    ));
    assert_eq!(Arc::strong_count(&fence), 2);
    assert!(!fence.is_complete());
    assert!(fixture.session.reference_context_item().await.is_none());
    assert_eq!(fixture.store.calls().await.append_items, before);
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &fence);
}

#[tokio::test]
async fn shutdown_after_captured_finish_rejects_the_fresh_attempt() {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await.append_items;
    let waiter = spawn_injection(&fixture);
    captured(&fence).await;
    fixture.session.begin_shutdown();
    finish_fence(&fixture.session, &fence);
    assert_invalid_request(join(waiter).await);
    assert!(fixture.session.reference_context_item().await.is_none());
    assert_eq!(fixture.store.calls().await.append_items, before);
    assert!(recorded_items(&fixture).await.is_empty());
}

#[test_case(TaskTerminalizationKind::Abort, false; "abort")]
#[test_case(TaskTerminalizationKind::Suspend, false; "suspend")]
#[test_case(TaskTerminalizationKind::Finish, true; "shutdown")]
#[tokio::test]
async fn non_finish_barriers_keep_strict_refusal_without_context_writes(
    kind: TaskTerminalizationKind,
    shutting_down: bool,
) {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, kind);
    if shutting_down {
        fixture.session.begin_shutdown();
    }
    let before = fixture.store.calls().await.append_items;
    assert_invalid_request(join(spawn_injection(&fixture)).await);
    assert!(!fence.is_complete());
    assert!(fixture.session.reference_context_item().await.is_none());
    assert_eq!(fixture.store.calls().await.append_items, before);
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &fence);
}

#[tokio::test]
async fn internal_injection_still_refuses_finish_immediately() {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let result = {
        let _active = fixture.session.active_turn.lock().await;
        fixture
            .session
            .inject_client_response_items(vec![item()], fixture.turn_context.as_ref())
            .now_or_never()
    }
    .expect("strict internal injection must refuse before waiting for the active lock");
    assert_invalid_request(result);
    assert_eq!(Arc::strong_count(&fence), 2);
    assert!(recorded_items(&fixture).await.is_empty());
    assert!(fixture.session.reference_context_item().await.is_none());
    finish_fence(&fixture.session, &fence);
}

struct PendingRecoverableTask {
    authority: Arc<TurnRecoveryAuthority>,
}

impl SessionTask for PendingRecoverableTask {
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
        "session_task.client_injection_finish_test"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<PendingTurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        cancellation_token.cancelled().await;
        Ok(None)
    }
}

#[test_case(false; "accepted_after_durable_revoke")]
#[test_case(true; "refused_when_revoke_fails")]
#[tokio::test]
async fn external_live_injection_preserves_durable_recovery_revocation(poisoned: bool) {
    let fixture = fixture(/*initial_context*/ true).await;
    let authority = Arc::new(TurnRecoveryAuthority::default());
    fixture
        .session
        .spawn_task(
            Arc::clone(&fixture.turn_context),
            Vec::new(),
            PendingRecoverableTask {
                authority: Arc::clone(&authority),
            },
        )
        .await
        .expect("live recovery task");
    assert_eq!(
        fixture
            .session
            .mark_recovery_ready_for_sampling(
                &fixture.turn_context.sub_id,
                &authority,
                fixture.session.rollout_persistence_failure_generation(),
                "client-injection-finish-test",
            )
            .await
            .expect("durable Ready marker"),
        RecoveryReadyForSampling::Ready
    );
    authority.state.lock().await.poisoned = poisoned;
    let result = join(spawn_injection(&fixture)).await;
    let pending = fixture
        .session
        .input_queue
        .get_pending_input(&fixture.session.active_turn)
        .await
        .0;
    let markers = fixture
        .session
        .live_thread()
        .expect("attached history store")
        .load_history(/*include_archived*/ true)
        .await
        .expect("history snapshot")
        .items
        .into_iter()
        .filter_map(|item| match item {
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                if marker.turn_id == fixture.turn_context.sub_id =>
            {
                Some(marker.state)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    if poisoned {
        assert!(
            result
                .expect_err("failed revoke must reject")
                .to_string()
                .contains("recovery provenance is poisoned")
        );
        assert!(pending.is_empty());
        assert_eq!(markers, vec![TurnRecoveryCandidateState::Ready]);
    } else {
        result.expect("accepted live injection");
        assert!(!authority.ready.load(Ordering::Acquire));
        assert_eq!(
            markers,
            vec![
                TurnRecoveryCandidateState::Ready,
                TurnRecoveryCandidateState::Unready
            ]
        );
        let [PendingTurnInput::ResponseItem(envelope)] = pending.as_slice() else {
            panic!("exactly one original client item must enter the live turn");
        };
        assert_eq!(
            serialized_envelopes(vec![envelope.clone()]),
            serialized_envelopes(vec![expected_envelope()]),
        );
    }
    authority.state.lock().await.poisoned = false;
    fixture
        .session
        .abort_all_tasks(TurnAbortReason::Interrupted)
        .await;
}

#[path = "context_fragment_retry_tests.rs"]
mod context_fragment_tests;
