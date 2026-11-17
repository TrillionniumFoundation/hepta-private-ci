use super::CodexThread;
use crate::agent::AgentStatus;
use crate::config::Config;
use crate::session::FinishRetryState;
use crate::session::SessionIo;
use crate::session::TurnInput;
use crate::session::session::Session;
use crate::session::session_loop_termination_from_handle;
use crate::session::tests::attach_in_memory_thread_store;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::turn_context::TurnContext;
use crate::state::ActiveTurn;
use crate::state::StartTransitionCompletion;
use crate::state::TaskKind;
use crate::state::TaskTerminalizationKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_protocol::ResponseItemId;
use codex_protocol::error::CodexErr;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ContentItemKind;
use codex_protocol::models::InternalChatMessageMetadataPassthrough;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SessionConfiguredEvent;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::Submission;
use codex_thread_store::InMemoryThreadStore;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use test_case::test_case;
use tokio::sync::Notify;
use tokio::sync::oneshot;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;

#[derive(Default)]
struct FinishGate {
    entered: Notify,
    release: Notify,
}

impl ThreadLifecycleContributor<Config> for FinishGate {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.entered.notify_one();
            self.release.notified().await;
        })
    }
}

struct HeldTask {
    release: Arc<Notify>,
}

impl SessionTask for HeldTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.standalone_inject_regression"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        tokio::select! {
            () = self.release.notified() => {},
            () = cancellation_token.cancelled() => {},
        }
        Ok(None)
    }
}

struct Fixture {
    thread: CodexThread,
    context: Arc<TurnContext>,
    store: Arc<InMemoryThreadStore>,
    gate: Arc<FinishGate>,
    stop: oneshot::Sender<()>,
    submissions: async_channel::Receiver<Submission>,
}

impl Fixture {
    async fn new() -> Self {
        let (mut session, context, rx_event) = make_session_and_context_with_rx().await;
        let gate = Arc::new(FinishGate::default());
        let mut extensions = ExtensionRegistryBuilder::<Config>::new();
        extensions.thread_lifecycle_contributor(gate.clone());
        let unique = Arc::get_mut(&mut session).expect("fresh test session");
        unique.services.extensions = Arc::new(extensions.build());
        let store = attach_in_memory_thread_store(unique).await;
        let history = session.clone_history().await;
        assert!(history.raw_items().next().is_none());
        assert!(session.reference_context_item().await.is_none());
        session
            .replace_history(Vec::new(), Some(context.to_turn_context_item()))
            .await;
        let configured = SessionConfiguredEvent {
            session_id: session.session_id(),
            thread_id: session.thread_id,
            forked_from_id: None,
            parent_thread_id: None,
            thread_source: None,
            thread_name: None,
            model: context.model_info.slug.clone(),
            model_provider_id: context.config.model_provider_id.clone(),
            service_tier: None,
            approval_policy: context.approval_policy(),
            approvals_reviewer: context.config.approvals_reviewer,
            permission_profile: context.permission_profile(),
            active_permission_profile: None,
            cwd: context.config.cwd.clone(),
            reasoning_effort: None,
            initial_messages: None,
            network_proxy: None,
            rollout_path: None,
        };
        let (tx_sub, submissions) = async_channel::unbounded();
        let (stop, stopped) = oneshot::channel();
        let actor = tokio::spawn(async move {
            let _ = stopped.await;
        });
        let io = SessionIo {
            tx_sub,
            rx_event,
            agent_status: watch::channel(AgentStatus::PendingInit).1,
            session_loop_termination: session_loop_termination_from_handle(actor),
        };
        let thread = CodexThread::new(
            session,
            io,
            configured,
            /*rollout_path*/ None,
            SessionSource::Exec,
        );
        Self {
            thread,
            context,
            store,
            gate,
            stop,
            submissions,
        }
    }

    async fn history(&self) -> Vec<ResponseItem> {
        self.thread
            .session
            .clone_history()
            .await
            .raw_items()
            .cloned()
            .collect()
    }
}

fn injected_item() -> ResponseItem {
    let id = "msg.standalone-injected-context".to_string();
    let mut item = ResponseItem::Message {
        id: Some(ResponseItemId::from_server(id)),
        role: "assistant".to_string(),
        content: vec![ContentItem::OutputText {
            text: "exact standalone context".to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: Some(InternalChatMessageMetadataPassthrough {
            content_item_kinds: Some(vec![ContentItemKind("unknown".to_string())]),
            ..Default::default()
        }),
    };
    item.set_turn_id_if_missing("injected-context-origin");
    item
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

fn assert_invalid(error: CodexErr, expected: &str) {
    assert!(
        matches!(error.details(), CodexErrorDetails::InvalidRequest(message) if message == expected)
    );
}

#[tokio::test]
async fn standalone_injection_waits_after_turn_complete_and_persists_once() {
    let fixture = Fixture::new().await;
    let session = &fixture.thread.session;
    let task_release = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&fixture.context),
            Vec::new(),
            HeldTask {
                release: Arc::clone(&task_release),
            },
        )
        .await
        .expect("start held task");
    task_release.notify_one();
    fixture.gate.entered.notified().await;
    let mut completed = false;
    while let Ok(event) = fixture.thread.io.rx_event.try_recv() {
        if matches!(event.msg, EventMsg::TurnComplete(_)) {
            completed = true;
        }
    }
    assert!(
        completed,
        "the public terminal event precedes this Finish gate"
    );
    assert!(session.active_turn.lock().await.is_none());
    let finish_state = {
        let active = session.active_turn.lock().await;
        session.finish_retry_state(active.as_ref())
    };
    let FinishRetryState::Finishing(fences) = finish_state else {
        panic!("exact Finish witness");
    };
    assert_eq!(fences.len(), 1);
    let fence = &fences[0];
    let references = Arc::strong_count(fence);
    let before = fixture.store.calls().await;
    let mut expected_history = fixture.history().await;
    let item = injected_item();
    let mut injection = Box::pin(fixture.thread.inject_response_items(vec![item.clone()]));
    assert!(futures::poll!(&mut injection).is_pending());
    assert_eq!(Arc::strong_count(fence), references + 1);
    assert!(session.active_turn.try_lock().is_ok());
    assert!(session.start_admission_gate.try_lock().is_ok());
    assert!(
        session
            .pending_task_terminalization_completions
            .try_lock()
            .is_ok()
    );
    assert_eq!(fixture.history().await, expected_history);
    assert_eq!(fixture.store.calls().await, before);
    assert!(fixture.submissions.is_empty());

    fixture.gate.release.notify_one();
    injection.await.expect("one injection after exact Finish");
    assert!(fence.is_complete());
    expected_history.push(item);
    assert_eq!(fixture.history().await, expected_history);
    let after = fixture.store.calls().await;
    assert_eq!(
        (after.append_items, after.flush_thread),
        (before.append_items + 1, before.flush_thread + 1)
    );
    assert!(fixture.submissions.is_empty());
}

#[tokio::test]
async fn standalone_injection_normalizes_missing_content_kinds_and_persists_once() {
    let fixture = Fixture::new().await;
    let before = fixture.store.calls().await;
    let expected_item = injected_item();
    let mut item = expected_item.clone();
    let ResponseItem::Message {
        internal_chat_message_metadata_passthrough: Some(metadata),
        ..
    } = &mut item
    else {
        panic!("message metadata");
    };
    metadata.content_item_kinds = None;

    fixture
        .thread
        .inject_response_items(vec![item])
        .await
        .expect("normalize missing content classifications");
    assert_eq!(fixture.history().await, vec![expected_item]);
    let after = fixture.store.calls().await;
    assert_eq!(
        (after.append_items, after.flush_thread),
        (before.append_items + 1, before.flush_thread + 1)
    );
    assert!(fixture.submissions.is_empty());
}

#[tokio::test]
async fn standalone_injection_with_a_retired_finish_preserves_the_clear_path() {
    let fixture = Fixture::new().await;
    let fence = install_fence(&fixture.thread.session, TaskTerminalizationKind::Finish);
    finish_fence(&fixture.thread.session, &fence);
    let before = fixture.store.calls().await;
    let item = injected_item();
    fixture
        .thread
        .inject_response_items(vec![item.clone()])
        .await
        .expect("clear admission");
    assert_eq!(fixture.history().await, vec![item]);
    let after = fixture.store.calls().await;
    assert_eq!(
        (after.append_items, after.flush_thread),
        (before.append_items + 1, before.flush_thread + 1)
    );
}

#[tokio::test]
async fn cancelled_standalone_waiter_never_injects_later() {
    let fixture = Fixture::new().await;
    let fence = install_fence(&fixture.thread.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await;
    let references = Arc::strong_count(&fence);
    let mut injection = Box::pin(fixture.thread.inject_response_items(vec![injected_item()]));
    assert!(futures::poll!(&mut injection).is_pending());
    assert_eq!(Arc::strong_count(&fence), references + 1);
    drop(injection);
    assert_eq!(Arc::strong_count(&fence), references);
    finish_fence(&fixture.thread.session, &fence);
    assert!(fixture.history().await.is_empty());
    assert_eq!(fixture.store.calls().await, before);
    assert!(fixture.submissions.is_empty());
}

#[tokio::test]
async fn session_termination_escapes_finish_wait_and_preserves_rejection() {
    let fixture = Fixture::new().await;
    let fence = install_fence(&fixture.thread.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await;
    let mut injection = Box::pin(fixture.thread.inject_response_items(vec![injected_item()]));
    assert!(futures::poll!(&mut injection).is_pending());
    fixture.stop.send(()).expect("stop actor");
    fixture.thread.wait_until_terminated().await;
    assert_invalid(
        injection.await.expect_err("pending Finish still rejects"),
        "turn is terminalizing or shutting down and cannot accept injected context",
    );
    assert!(!fence.is_complete());
    assert!(
        fixture
            .thread
            .session
            .clone_history()
            .await
            .raw_items()
            .next()
            .is_none()
    );
    assert_eq!(fixture.store.calls().await, before);
    finish_fence(&fixture.thread.session, &fence);
}

#[derive(Clone, Copy)]
enum Boundary {
    Finish,
    Abort,
    Suspend,
    StartReservation,
    Shutdown,
}

async fn install_boundary(
    session: &Session,
    boundary: Boundary,
) -> Option<Arc<StartTransitionCompletion>> {
    match boundary {
        Boundary::Finish => Some(install_fence(session, TaskTerminalizationKind::Finish)),
        Boundary::Abort => Some(install_fence(session, TaskTerminalizationKind::Abort)),
        Boundary::Suspend => Some(install_fence(session, TaskTerminalizationKind::Suspend)),
        Boundary::StartReservation => {
            session
                .active_turn
                .lock()
                .await
                .get_or_insert_with(ActiveTurn::default)
                .reserve_start("successor-start".to_string())
                .expect("start reservation");
            None
        }
        Boundary::Shutdown => {
            session.begin_shutdown();
            None
        }
    }
}

#[test_case(Boundary::Finish; "successor_finish_is_not_recaptured")]
#[test_case(Boundary::Abort; "successor_abort")]
#[test_case(Boundary::Suspend; "successor_suspend")]
#[test_case(Boundary::StartReservation; "successor_start")]
#[test_case(Boundary::Shutdown; "shutdown_after_capture")]
#[tokio::test]
async fn original_guards_reject_changes_after_the_captured_finish(boundary: Boundary) {
    let fixture = Fixture::new().await;
    let session = &fixture.thread.session;
    let old = install_fence(session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await;
    let mut injection = Box::pin(fixture.thread.inject_response_items(vec![injected_item()]));
    assert!(futures::poll!(&mut injection).is_pending());
    let successor = install_boundary(session, boundary).await;
    finish_fence(session, &old);
    let error = injection.await.expect_err("fresh guards must reject");
    let expected = if matches!(boundary, Boundary::StartReservation) {
        "turn is transitioning and cannot accept injected context"
    } else {
        "turn is terminalizing or shutting down and cannot accept injected context"
    };
    assert_invalid(error, expected);
    assert!(fixture.history().await.is_empty());
    assert_eq!(fixture.store.calls().await, before);
    assert!(fixture.submissions.is_empty());
    if let Some(successor) = successor {
        assert!(!successor.is_complete(), "a new fence must not be awaited");
        finish_fence(session, &successor);
    }
}

#[test_case(Boundary::Abort; "abort")]
#[test_case(Boundary::Suspend; "suspend")]
#[test_case(Boundary::StartReservation; "start_reservation")]
#[test_case(Boundary::Shutdown; "shutdown")]
#[tokio::test]
async fn blocked_terminalizers_do_not_wait_and_empty_input_keeps_priority(boundary: Boundary) {
    let fixture = Fixture::new().await;
    let session = &fixture.thread.session;
    let fence = install_fence(session, TaskTerminalizationKind::Finish);
    let blocker = install_boundary(session, boundary).await;
    let before = fixture.store.calls().await;
    assert_invalid(
        fixture
            .thread
            .inject_response_items(Vec::new())
            .await
            .expect_err("empty input"),
        "items must not be empty",
    );
    assert_invalid(
        fixture
            .thread
            .inject_response_items(vec![injected_item()])
            .await
            .expect_err("blocked"),
        "turn is terminalizing or shutting down and cannot accept injected context",
    );
    assert!(!fence.is_complete());
    assert!(fixture.history().await.is_empty());
    assert_eq!(fixture.store.calls().await, before);
    finish_fence(session, &fence);
    if let Some(blocker) = blocker {
        finish_fence(session, &blocker);
    }
}

#[tokio::test]
async fn empty_and_associated_turn_injection_do_not_wait_for_finish() {
    let fixture = Fixture::new().await;
    let fence = install_fence(&fixture.thread.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await;
    assert_invalid(
        fixture
            .thread
            .inject_response_items(Vec::new())
            .await
            .expect_err("empty input"),
        "items must not be empty",
    );
    assert_invalid(
        fixture
            .thread
            .inject_response_items_for_turn(vec![injected_item()])
            .await
            .expect_err("associated-turn path stays strict"),
        "turn is terminalizing or shutting down and cannot accept injected context",
    );
    assert!(!fence.is_complete());
    assert!(fixture.history().await.is_empty());
    assert_eq!(fixture.store.calls().await, before);
    finish_fence(&fixture.thread.session, &fence);
}
