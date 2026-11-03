//! Transport faults around the real Core queue and its automatic dispatch.

use super::*;
use std::sync::{Mutex, OnceLock};

use codex_app_server_protocol::{QueuedSubmission, ThreadQueueReconcileOutcome, ThreadQueueReconcileParams, ThreadQueueReconcileResponse};
use codex_core::hosted_turn::{HostedTurnExecutor, HostedTurnMode};
use codex_extension_api::{ExtensionFuture, ExtensionRegistryBuilder, NoopExtensionEventSink, ThreadIdleInput, ThreadLifecycleContributor, ThreadResumeInput, ThreadStartInput};
use codex_features::Feature;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_queue_extension::{QueueReconcileMode, QueueReconcileOutcome, QueuedItemService};
use core_test_support::test_codex::test_codex;

use crate::authbus_trust::invalid;
use crate::objective_queue_relay::{ObjectiveQueueFuture, ObjectiveQueueTransport, require_current_route};

#[derive(Clone, Copy)]
pub(super) enum ReplyFault { None, BeforeQueue, AfterQueue, AfterCompletion, HoldBeforeQueue, HoldAfterQueue }

pub(super) struct OriginalQueueTransport {
    service: OnceLock<Arc<QueuedItemService>>,
    executor: OnceLock<Arc<dyn HostedTurnExecutor>>,
    pub(super) modes: Mutex<Vec<ThreadQueueReconcileMode>>,
    fault: ReplyFault,
    fault_used: AtomicBool,
    held: tokio::sync::Notify,
    release: tokio::sync::Notify,
    pub(super) reconciles: AtomicUsize,
    pub(super) acknowledged: AtomicUsize,
}

impl OriginalQueueTransport {
    pub(super) fn new(fault: ReplyFault) -> Self {
        Self { service: OnceLock::new(), executor: OnceLock::new(), modes: Mutex::new(Vec::new()),
            fault, fault_used: AtomicBool::new(false), held: tokio::sync::Notify::new(),
            release: tokio::sync::Notify::new(), reconciles: AtomicUsize::new(0),
            acknowledged: AtomicUsize::new(0) }
    }

    pub(super) async fn wait_until_held(&self) {
        self.held.notified().await;
    }

    pub(super) fn release_reply(&self) {
        self.release.notify_one();
    }

    pub(super) fn service(&self) -> Result<&Arc<QueuedItemService>, AgentdError> {
        self.service.get().ok_or_else(|| invalid("original Core queue installed before signed ingress"))
    }
}

impl ObjectiveQueueTransport for OriginalQueueTransport {
    fn reconcile<'a>(&'a self, state: &'a AgentdState, record: &'a RunStartRecordV1,
        params: ThreadQueueReconcileParams) -> ObjectiveQueueFuture<'a> {
        Box::pin(async move {
            // The production UDS transport performs the same final check
            // after connecting and before its original queue request.
            require_current_route(state, record, &params)?;
            self.modes.lock().map_err(|error| invalid(&format!("queue modes: {error}")))?.push(params.mode);
            let fault = !self.fault_used.swap(true, Ordering::SeqCst);
            if fault && matches!(self.fault, ReplyFault::BeforeQueue) {
                return Err(invalid("fixture lost transport before original queue admission"));
            }
            if fault && matches!(self.fault, ReplyFault::HoldBeforeQueue) {
                // The original Objective owner has already returned from its
                // fsynced prepared publication. Hold only this transport future;
                // dropping submit cannot touch the real QueueStore.
                self.held.notify_one();
                std::future::pending::<()>().await;
            }
            let content = params.input.iter().cloned().map(codex_app_server_protocol::UserInput::into_core).collect::<Vec<_>>();
            let input = TurnInput::UserInput { content, client_id: Some(params.client_user_message_id.clone()) };
            let mode = match params.mode {
                ThreadQueueReconcileMode::AllowIfAbsent => QueueReconcileMode::AllowIfAbsent,
                ThreadQueueReconcileMode::ReconcileOnly => QueueReconcileMode::ReconcileOnly,
            };
            self.reconciles.fetch_add(1, Ordering::SeqCst);
            let reply = self.service()?.reconcile(ThreadId::from_string(&params.thread_id)
                .map_err(|error| invalid(&format!("fixture original thread: {error}")))?, /*rollout_path*/ None,
                input.clone(), params.expected_payload_sha256.clone(), mode).await
                .map_err(|error| invalid(&format!("original Core queue: {error}")))?;
            if fault && matches!(self.fault, ReplyFault::AfterQueue) {
                return Err(invalid("fixture lost reply after original queue admission"));
            }
            if fault && matches!(self.fault, ReplyFault::HoldAfterQueue) {
                // The actual QueueStore operation is complete. Hold its existing
                // reply until the test observes the socket boundary, without
                // manufacturing a queue receipt or changing the owner's timeout.
                self.held.notify_one();
                self.release.notified().await;
            }
            if fault && matches!(self.fault, ReplyFault::AfterCompletion) {
                // Delay only the real transport ACK until the actual original
                // coordinator has durably completed; never fabricate terminal
                // evidence or a queue receipt to exercise this close race.
                tokio::time::timeout(Duration::from_secs(10), async {
                    loop {
                        if state.native_run_receipt(record.snapshot.run_id.as_str())?.phase == RunPhase::Succeeded {
                            return Ok::<(), AgentdError>(());
                        }
                        tokio::task::yield_now().await;
                    }
                }).await.map_err(|_| invalid("fixture original turn did not close before its queue ACK"))??;
            }
            let outcome = match reply.outcome {
                QueueReconcileOutcome::Queued { item, created } => {
                    if item.input != input { return Err(invalid("original queue input changed")); }
                    ThreadQueueReconcileOutcome::Queued {
                        queued_submission: QueuedSubmission { id: item.id, input: params.input,
                            client_user_message_id: params.client_user_message_id }, created,
                    }
                }
                QueueReconcileOutcome::Persisted { turn_id } => ThreadQueueReconcileOutcome::Persisted { turn_id },
                QueueReconcileOutcome::Missing => ThreadQueueReconcileOutcome::Missing,
                QueueReconcileOutcome::Cancelled => ThreadQueueReconcileOutcome::Cancelled,
            };
            self.acknowledged.fetch_add(1, Ordering::SeqCst);
            Ok(ThreadQueueReconcileResponse { client_user_message_id: reply.client_user_message_id,
                payload_sha256: reply.payload_sha256, outcome })
        })
    }
}

// Hold the already-installed executor before the infallible lifecycle callback.
// This adapter delegates to the same original transport/service.
struct InstalledOriginalQueue {
    transport: Arc<OriginalQueueTransport>,
    executor: Arc<dyn HostedTurnExecutor>,
    queue_owner: Arc<dyn codex_thread_store::QueueStore>,
}

impl ThreadLifecycleContributor<codex_core::config::Config> for InstalledOriginalQueue {
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, codex_core::config::Config>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            input.session_store.insert(HostedTurnMode::with_queue_owner(
                self.executor.clone(), self.queue_owner.clone()));
        })
    }

    fn on_thread_resume<'a>(&'a self, input: ThreadResumeInput<'a>) -> ExtensionFuture<'a, ()> {
        match self.transport.service.get() {
            Some(service) => <QueuedItemService as ThreadLifecycleContributor<codex_core::config::Config>>::on_thread_resume(service, input),
            None => Box::pin(async {}),
        }
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        match self.transport.service.get() {
            Some(service) => <QueuedItemService as ThreadLifecycleContributor<codex_core::config::Config>>::on_thread_idle(service, input),
            None => Box::pin(async {}),
        }
    }
}

pub(super) async fn original_core(server: &MockServer, transport: &Arc<OriginalQueueTransport>,
    executor: Arc<dyn HostedTurnExecutor>, identity: &crate::AgentdIdentity,
    queue_owner: Arc<dyn codex_thread_store::QueueStore>) -> Result<TestCodex> {
    ensure!(transport.executor.set(executor.clone()).is_ok(), "original executor already installed");
    let mut registry = ExtensionRegistryBuilder::new();
    registry.thread_lifecycle_contributor(Arc::new(InstalledOriginalQueue {
        transport: transport.clone(),
        executor: transport.executor.get().context("installed executor")?.clone(),
        queue_owner: queue_owner.clone(),
    }));
    let home = AbsolutePathBuf::try_from(identity.home_root.clone())?;
    let workspace = AbsolutePathBuf::try_from(identity.workspace.clone())?;
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(identity.home_root.join("state"))?);
    let test = test_codex().with_extensions(Arc::new(registry.build()))
        .with_history_mode(ThreadHistoryMode::Paginated).with_config(move |config| {
            config.codex_home = home;
            config.cwd = workspace;
            config.sqlite = sqlite;
            config.include_environment_context = false;
            let _ = config.features.enable(Feature::HeptaTurnRecovery);
        }).build_with_auto_env(server).await?;
    ensure!(test.codex_home_path() == identity.home_root, "Core and original Agentd home differ");
    let service = Arc::new(QueuedItemService::new(queue_owner, Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink)).with_hosted_turn_executor(Some(executor)));
    ensure!(transport.service.set(service).is_ok(), "original queue already installed");
    Ok(test)
}
