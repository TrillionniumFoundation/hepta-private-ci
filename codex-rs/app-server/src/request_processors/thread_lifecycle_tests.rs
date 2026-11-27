use super::ListenerTaskContext;
use super::ensure_listener_task_running;
use crate::error_code::invalid_request;
use crate::outgoing_message::ConnectionId;
use crate::outgoing_message::ConnectionRequestId;
use crate::outgoing_message::OutgoingEnvelope;
use crate::outgoing_message::OutgoingError;
use crate::outgoing_message::OutgoingMessage;
use crate::outgoing_message::OutgoingMessageSender;
use crate::request_processors::summary_to_thread;
use crate::skills_watcher::SkillsWatcher;
use crate::thread_state::ConnectionCapabilities;
use crate::thread_state::PendingThreadResumeRequest;
use crate::thread_state::ThreadListenerCommand;
use crate::thread_state::ThreadStateManager;
use crate::thread_status::ThreadWatchManager;
use anyhow::Context;
use anyhow::Result;
use codex_app_server_protocol::ClientResponsePayload;
use codex_app_server_protocol::ConversationSummary;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadStatus;
use codex_core::CodexThread;
use codex_core::StartThreadOptions;
use codex_protocol::ThreadId;
use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::SessionSource;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use std::collections::HashSet;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio::sync::Semaphore;
use tokio::sync::mpsc;

struct ResumeFixture {
    core: TestCodex,
    context: ListenerTaskContext,
    outgoing_rx: mpsc::Receiver<OutgoingEnvelope>,
    _server: wiremock::MockServer,
}

impl ResumeFixture {
    async fn new() -> Result<Self> {
        let server = start_mock_server().await;
        let core = test_codex().build(&server).await?;
        let (outgoing_tx, outgoing_rx) = mpsc::channel(/*buffer*/ 32);
        let outgoing = Arc::new(OutgoingMessageSender::new(
            outgoing_tx,
            codex_analytics::AnalyticsEventsClient::disabled(),
        ));
        let thread_state_manager = ThreadStateManager::new();
        thread_state_manager
            .connection_initialized(ConnectionId(1), ConnectionCapabilities::default())
            .await;
        let context = ListenerTaskContext {
            thread_manager: Arc::clone(&core.thread_manager),
            thread_state_manager,
            outgoing: Arc::clone(&outgoing),
            pending_thread_unloads: Arc::new(Mutex::new(HashSet::new())),
            thread_watch_manager: ThreadWatchManager::new(),
            thread_list_state_permit: Arc::new(Semaphore::new(/*permits*/ 1)),
            fallback_model_provider: core.config.model_provider_id.clone(),
            codex_home: core.config.codex_home.to_path_buf(),
            skills_watcher: SkillsWatcher::new(
                core.thread_manager.skills_service(),
                &core.config.codex_home,
                outgoing,
            ),
            turn_cost_worker: None,
        };
        Ok(Self {
            core,
            context,
            outgoing_rx,
            _server: server,
        })
    }

    fn thread_id(&self) -> ThreadId {
        self.core.session_configured.thread_id
    }

    async fn start_resume(&self, conversation: Arc<CodexThread>) -> Result<()> {
        let thread_id = self.thread_id();
        let config_snapshot = self.core.codex.config_snapshot().await;
        let thread_summary = summary_to_thread(
            ConversationSummary {
                conversation_id: thread_id,
                path: self.core.codex.rollout_path().unwrap_or_default(),
                preview: String::new(),
                timestamp: None,
                updated_at: None,
                model_provider: config_snapshot.model_provider_id.clone(),
                cwd: self.core.config.cwd.to_path_buf(),
                cli_version: String::new(),
                source: SessionSource::Exec,
                git_info: None,
            },
            &self.core.config.cwd,
        );
        let pending = PendingThreadResumeRequest {
            request_id: ConnectionRequestId {
                connection_id: ConnectionId(1),
                request_id: RequestId::Integer(1),
            },
            history_items: Vec::new(),
            cold_resume_token_usage_turn_id: None,
            config_snapshot,
            instruction_sources: Vec::new(),
            thread_summary,
            emit_thread_goal_update: false,
            thread_goal_state_db: None,
            include_turns: false,
            initial_turns_page: None,
            paginated_turns: None,
            paginated_initial_turns_page: None,
            paginated_initial_turns_page_with_active_slot: None,
            resume_cursor_store: None,
            redact_resume_payloads: false,
        };
        let thread_state = self
            .context
            .thread_state_manager
            .thread_state(thread_id)
            .await;
        let status = self
            .context
            .thread_watch_manager
            .subscribe(thread_id)
            .await
            .context("observe the unregistered thread")?;
        assert_eq!(*status.borrow(), ThreadStatus::NotLoaded);
        ensure_listener_task_running(self.context.clone(), thread_id, conversation, thread_state)
            .await
            .map_err(|error| anyhow::anyhow!("start listener: {}", error.message))?;
        assert_eq!(*status.borrow(), ThreadStatus::NotLoaded);
        // These tests use Tokio's current-thread runtime. Enqueue without yielding
        // after listener creation; its biased command branch runs before queued events.
        self.context
            .thread_state_manager
            .current_listener_command_tx(thread_id)
            .context("listener must be registered before sending the resume")?
            .send(ThreadListenerCommand::SendThreadResumeResponse(Box::new(
                pending,
            )))
            .map_err(|_| anyhow::anyhow!("listener command channel closed"))?;
        Ok(())
    }

    async fn reply(&mut self) -> Result<OutgoingMessage> {
        loop {
            match self.outgoing_rx.recv().await.context("outgoing closed")? {
                OutgoingEnvelope::ToConnection {
                    connection_id,
                    message: message @ (OutgoingMessage::Response(_) | OutgoingMessage::Error(_)),
                    ..
                } => {
                    assert_eq!(connection_id, ConnectionId(1));
                    return Ok(message);
                }
                OutgoingEnvelope::Broadcast {
                    message: OutgoingMessage::AppServerNotification(_),
                }
                | OutgoingEnvelope::ToConnection {
                    message: OutgoingMessage::AppServerNotification(_),
                    ..
                } => {}
                other => anyhow::bail!("unexpected listener output: {other:?}"),
            }
        }
    }

    async fn assert_closing_without_registration(&mut self) -> Result<()> {
        let thread_id = self.thread_id();
        let OutgoingMessage::Error(actual) = self.reply().await? else {
            anyhow::bail!("expected the original closing error");
        };
        assert_eq!(
            actual,
            OutgoingError {
                id: RequestId::Integer(1),
                error: invalid_request(format!(
                    "thread {thread_id} is closing; retry thread/resume after the thread is closed"
                )),
            }
        );
        assert_eq!(
            self.context
                .thread_watch_manager
                .loaded_status_for_thread(&thread_id.to_string())
                .await,
            ThreadStatus::NotLoaded
        );
        Ok(())
    }

    async fn close(self) -> Result<()> {
        self.core.codex.shutdown_and_wait().await?;
        self.context
            .thread_state_manager
            .remove_thread_state(self.thread_id())
            .await;
        self.context.skills_watcher.shutdown();
        Ok(())
    }
}

#[tokio::test]
async fn listener_resume_registers_loaded_runtime_and_observes_shutdown() -> Result<()> {
    let mut fixture = ResumeFixture::new().await?;
    fixture
        .start_resume(Arc::clone(&fixture.core.codex))
        .await?;
    let OutgoingMessage::Response(response) = fixture.reply().await? else {
        anyhow::bail!("expected a running-thread resume response");
    };
    assert_eq!(response.id, RequestId::Integer(1));
    let ClientResponsePayload::ThreadResume(response) = *response.result else {
        anyhow::bail!("expected thread/resume payload");
    };
    assert_eq!(
        (
            response.thread.id,
            response.thread.status,
            response.thread.turns
        ),
        (
            fixture.thread_id().to_string(),
            ThreadStatus::Idle,
            Vec::new()
        )
    );
    let mut statuses = fixture
        .context
        .thread_watch_manager
        .subscribe(fixture.thread_id())
        .await
        .context("thread status subscription")?;
    assert_eq!(*statuses.borrow(), ThreadStatus::Idle);
    fixture.core.codex.shutdown_and_wait().await?;
    while *statuses.borrow_and_update() != ThreadStatus::NotLoaded {
        statuses.changed().await?;
    }
    fixture.close().await
}

#[tokio::test]
async fn listener_resume_rejects_observed_shutdown_without_registration() -> Result<()> {
    let mut fixture = ResumeFixture::new().await?;
    fixture.core.codex.shutdown_and_wait().await?;
    assert_eq!(
        fixture.core.codex.agent_status().await,
        AgentStatus::Shutdown
    );
    fixture
        .start_resume(Arc::clone(&fixture.core.codex))
        .await?;
    fixture.assert_closing_without_registration().await?;
    fixture.close().await
}

#[tokio::test]
async fn listener_resume_rejects_missing_runtime_without_registration() -> Result<()> {
    let mut fixture = ResumeFixture::new().await?;
    let removed = fixture
        .core
        .thread_manager
        .remove_thread(&fixture.thread_id())
        .await
        .context("remove the actual runtime before the resume command")?;
    assert!(Arc::ptr_eq(&removed, &fixture.core.codex));
    assert_ne!(removed.agent_status().await, AgentStatus::Shutdown);
    fixture.start_resume(removed).await?;
    fixture.assert_closing_without_registration().await?;
    fixture.close().await
}

#[tokio::test]
async fn listener_resume_rejects_mismatched_runtime_arc_without_registration() -> Result<()> {
    let mut fixture = ResumeFixture::new().await?;
    let other = fixture
        .core
        .thread_manager
        .start_thread(StartThreadOptions::new(fixture.core.config.clone()))
        .await?;
    let current = fixture
        .core
        .thread_manager
        .get_thread(fixture.thread_id())
        .await?;
    assert!(Arc::ptr_eq(&current, &fixture.core.codex));
    assert!(!Arc::ptr_eq(&current, &other.thread));
    assert_ne!(other.thread.agent_status().await, AgentStatus::Shutdown);
    // This is a live Arc mismatch control, not a same-ID eviction/reload experiment.
    fixture.start_resume(Arc::clone(&other.thread)).await?;
    fixture.assert_closing_without_registration().await?;
    other.thread.shutdown_and_wait().await?;
    fixture.close().await
}
