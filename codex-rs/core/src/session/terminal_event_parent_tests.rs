use super::super::TurnInput;
use super::super::session::Session;
use super::super::tests::attach_in_memory_thread_store;
use super::super::tests::make_session_and_context_with_rx;
use super::super::turn_context::TurnContext;
use crate::ThreadManager;
use crate::agent::AgentStatus;
use crate::config::ConfigBuilder;
use crate::state::TaskKind;
use crate::tasks::SessionTask;
use crate::tasks::SessionTaskResult;
use crate::thread_manager::StartThreadOptions;
use codex_extension_api::empty_extension_registry;
use codex_history::RolloutItem;
use codex_login::AuthManager;
use codex_login::CodexAuth;
use codex_protocol::AgentPath;
use codex_protocol::ThreadId;
use codex_protocol::items::TurnItem;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::MultiAgentVersion;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnStartedEvent;
use codex_thread_store as store;
use codex_thread_store::ThreadStore;
use pretty_assertions::assert_eq;
use std::any::Any;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::task::Poll;
use std::time::Duration;
use tempfile::TempDir;
use tokio::sync::Notify;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

const DEADLINE: Duration = Duration::from_secs(5);

/// A real parent persistence boundary. All storage behavior delegates to the
/// existing in-memory implementation; only its first completed-child activity
/// is held until the test explicitly releases it.
#[derive(Default)]
struct ParentStore {
    inner: store::InMemoryThreadStore,
    parent: OnceLock<ThreadId>,
    entered: Notify,
    release: Notify,
    blocked: AtomicBool,
}

macro_rules! delegate_store {
    ($(fn $name:ident($($arg:ident: $ty:ty),*) -> $out:ty;)*) => {
        $(fn $name(&self, $($arg: $ty),*) -> store::ThreadStoreFuture<'_, $out> {
            ThreadStore::$name(&self.inner, $($arg),*)
        })*
    };
}

impl ThreadStore for ParentStore {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn append_items(
        &self,
        params: store::AppendThreadItemsParams,
    ) -> store::ThreadStoreFuture<'_, ()> {
        Box::pin(async move {
            let completed_child_activity = self.parent.get() == Some(&params.thread_id)
                && params.items.iter().any(|item| {
                    matches!(
                        item,
                        RolloutItem::EventMsg(EventMsg::ItemStarted(event))
                            if matches!(&event.item, TurnItem::SubAgentActivity(_))
                    )
                });
            if completed_child_activity && !self.blocked.swap(true, Ordering::SeqCst) {
                self.entered.notify_one();
                self.release.notified().await;
            }
            ThreadStore::append_items(&self.inner, params).await
        })
    }

    delegate_store! {
        fn create_thread(params: store::CreateThreadParams) -> ();
        fn resume_thread(params: store::ResumeThreadParams) -> ();
        fn is_thread_hard_delete_fenced(thread_id: ThreadId) -> bool;
        fn persist_thread(thread_id: ThreadId, context: store::PersistContext) -> ();
        fn flush_thread(thread_id: ThreadId) -> ();
        fn shutdown_thread(thread_id: ThreadId) -> ();
        fn discard_thread(thread_id: ThreadId) -> ();
        fn load_history(params: store::LoadThreadHistoryParams) -> store::StoredThreadHistory;
        fn load_latest_model_context(params: store::LoadThreadHistoryParams) -> store::StoredModelContext;
        fn read_thread(params: store::ReadThreadParams) -> store::StoredThread;
        fn read_thread_by_rollout_path(params: store::ReadThreadByRolloutPathParams) -> store::StoredThread;
        fn list_threads(params: store::ListThreadsParams) -> store::ThreadPage;
        fn update_thread_metadata(params: store::UpdateThreadMetadataParams) -> Option<store::StoredThread>;
        fn archive_thread(params: store::ArchiveThreadParams) -> ();
        fn unarchive_thread(params: store::ArchiveThreadParams) -> store::StoredThread;
        fn delete_thread(params: store::DeleteThreadParams) -> ();
    }
}

struct ProbeTask {
    running: Option<Arc<Notify>>,
}

impl SessionTask for ProbeTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.terminal_parent_probe"
    }

    async fn run(
        self: Arc<Self>,
        session: Arc<Session>,
        context: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        if let Some(running) = &self.running {
            session
                .send_event(
                    &context,
                    EventMsg::TurnStarted(TurnStartedEvent {
                        turn_id: context.sub_id.clone(),
                        trace_id: None,
                        started_at: None,
                        model_context_window: None,
                        collaboration_mode_kind: Default::default(),
                    }),
                )
                .await;
            running.notify_one();
            cancellation_token.cancelled().await;
        }
        Ok(Some("completed child".to_string()))
    }
}

struct ParentFixture {
    _home: TempDir,
    _manager: ThreadManager,
    parent: Arc<crate::CodexThread>,
    store: Arc<ParentStore>,
    child: Arc<Session>,
    context: Arc<TurnContext>,
    events: async_channel::Receiver<Event>,
}

impl ParentFixture {
    async fn new() -> Self {
        let home = TempDir::new().expect("parent temporary home");
        let config = ConfigBuilder::without_managed_config_for_tests()
            .codex_home(home.path().to_path_buf())
            .build()
            .await
            .expect("parent test config");
        let store = Arc::new(ParentStore::default());
        let auth = AuthManager::from_auth_for_testing(CodexAuth::from_api_key("dummy"));
        let manager = ThreadManager::new(
            &config,
            Arc::clone(&auth),
            crate::thread_manager::build_models_manager(&config, auth),
            crate::CodexAppsToolsCache::default(),
            SessionSource::Exec,
            Arc::new(codex_exec_server::EnvironmentManager::default_for_tests()),
            empty_extension_registry(),
            Arc::new(crate::test_support::EmptyUserInstructionsProvider),
            /*analytics_events_client*/ None,
            store.clone(),
            /*agent_graph_store*/ None,
            uuid::Uuid::new_v4().to_string(),
            /*attestation_provider*/ None,
            /*external_time_provider*/ None,
        );
        let parent = manager
            .start_thread(StartThreadOptions::new(config))
            .await
            .expect("registered real parent thread");
        store.parent.set(parent.thread_id).expect("parent id once");
        let (mut child, mut context, events) = make_session_and_context_with_rx().await;
        let child_mut = Arc::get_mut(&mut child).expect("unique child session");
        attach_in_memory_thread_store(child_mut).await;
        child_mut.services.agent_control = manager.agent_control();
        let context_mut = Arc::get_mut(&mut context).expect("unique child context");
        context_mut.multi_agent_version = MultiAgentVersion::V2;
        context_mut.session_source = SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
            parent_thread_id: parent.thread_id,
            depth: 1,
            agent_path: Some(
                AgentPath::root()
                    .join("terminal_probe")
                    .expect("child path"),
            ),
            agent_nickname: None,
            agent_role: None,
        });
        context_mut
            .turn_metadata_state
            .set_parent_turn_id("parent-turn".to_string());
        Self {
            _home: home,
            _manager: manager,
            parent: parent.thread,
            store,
            child,
            context,
            events,
        }
    }

    async fn reach_blocked_parent_after_terminal(&self) {
        self.child
            .spawn_task(
                Arc::clone(&self.context),
                Vec::new(),
                ProbeTask { running: None },
            )
            .await
            .expect("initial child task starts");
        timeout(DEADLINE, self.store.entered.notified())
            .await
            .expect("real parent persistence reaches the barrier");
        timeout(DEADLINE, async {
            loop {
                let event = self.events.recv().await.expect("child events open");
                if matches!(event.msg, EventMsg::TurnComplete(_)) {
                    assert_eq!(event.id, self.context.sub_id);
                    break;
                }
            }
        })
        .await
        .expect("child terminal is public while parent delivery is blocked");
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn blocked_parent_notification_admits_next_turn_without_stale_status() {
    let fixture = ParentFixture::new().await;
    fixture.reach_blocked_parent_after_terminal().await;
    assert!(!fixture.child.has_pending_admission_fence());

    let running = Arc::new(Notify::new());
    let next = fixture
        .child
        .new_default_turn_with_sub_id("new-child-turn".to_string())
        .await;
    fixture
        .child
        .spawn_task(
            next,
            Vec::new(),
            ProbeTask {
                running: Some(Arc::clone(&running)),
            },
        )
        .await
        .expect("next turn admission does not wait for the parent");
    timeout(DEADLINE, running.notified())
        .await
        .expect("new turn runs");
    assert_eq!(*fixture.child.agent_status.borrow(), AgentStatus::Running);

    // Exercise the actual shutdown drain, not a private marker assertion. Its
    // first poll must wait even though terminal receipt opened admission.
    let mut drain = std::pin::pin!(
        fixture
            .child
            .drain_task_terminalizations_for_shutdown_except(/*excluded_identity*/ None)
    );
    assert!(matches!(futures::poll!(drain.as_mut()), Poll::Pending));
    fixture.store.release.notify_one();
    timeout(DEADLINE, drain)
        .await
        .expect("old parent delivery drains");
    assert_eq!(
        *fixture.child.agent_status.borrow(),
        AgentStatus::Running,
        "finishing the previous parent's notification must not replace the new turn's status"
    );
    fixture
        .child
        .abort_all_tasks(TurnAbortReason::Interrupted)
        .await;
    fixture
        .parent
        .shutdown_and_wait()
        .await
        .expect("parent shutdown");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shutdown_still_drains_parent_delivery_after_terminal_admission_opens() {
    let fixture = ParentFixture::new().await;
    fixture.reach_blocked_parent_after_terminal().await;
    assert!(!fixture.child.has_pending_admission_fence());
    fixture.child.begin_shutdown();
    let next = fixture
        .child
        .new_default_turn_with_sub_id("rejected-after-shutdown".to_string())
        .await;
    assert!(
        fixture
            .child
            .spawn_task(next, Vec::new(), ProbeTask { running: None })
            .await
            .is_err()
    );

    let mut drain = std::pin::pin!(
        fixture
            .child
            .drain_task_terminalizations_for_shutdown_except(/*excluded_identity*/ None)
    );
    assert!(matches!(futures::poll!(drain.as_mut()), Poll::Pending));
    fixture.store.release.notify_one();
    timeout(DEADLINE, drain)
        .await
        .expect("shutdown drains the complete old owner");
    assert!(
        fixture
            .child
            .pending_task_terminalization_completions
            .lock()
            .expect("completion registry")
            .is_empty()
    );
    fixture
        .parent
        .shutdown_and_wait()
        .await
        .expect("parent shutdown");
}
