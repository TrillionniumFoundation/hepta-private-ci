use std::future::Future;
use std::sync::Arc;

use codex_hepta_agent_components::automation::AutomationError;
use codex_hepta_agent_components::automation::AutomationStore;
use codex_hepta_agent_components::automation::AutomationTurnQueue;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;
use crate::RuntimeTasks;

/// Opens and attaches the existing durable automation owner without starting work.
/// Storage availability and generation fencing stay inside this capability.
/// The caller retains the Agent writer lock throughout preparation and execution.
pub(crate) struct AutomationService {
    store: Option<AutomationStore>,
    state: Arc<AgentdState>,
}

impl AutomationService {
    pub(crate) async fn open(state: Arc<AgentdState>) -> Result<Self, AgentdError> {
        let layout = state.identity().layout.clone();
        let store = open_automation_store_after_generation_fence(&state, || async move {
            AutomationStore::open(&layout).await
        })
        .await?;
        if let Some(store) = store.as_ref() {
            state.attach_automation_store(store.clone())?;
        }
        Ok(Self { store, state })
    }

    /// Default product composition chooses its adapter here, not in Agentd's
    /// generic lifecycle host. Alternative reviewed implementations use the
    /// same typed queue seam and the same owner/recovery/task lifecycle below.
    pub(crate) async fn spawn(
        self,
        tasks: &mut RuntimeTasks,
        host_cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let queue = Arc::new(super::AgentdAutomationQueue::new(
            Arc::clone(&self.state),
            self.state.identity().clone(),
        ));
        self.spawn_with_queue(tasks, queue, host_cancellation).await
    }

    pub(super) async fn spawn_with_queue<Q: AutomationTurnQueue + 'static>(
        self,
        tasks: &mut RuntimeTasks,
        queue: Arc<Q>,
        host_cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let identity = self.state.identity().clone();
        super::spawn_automation_service(
            tasks,
            self.store,
            self.state,
            identity,
            queue,
            host_cancellation,
        )
        .await
    }
}

pub(crate) async fn open_automation_store_after_generation_fence<Open, OpenFuture>(
    state: &AgentdState,
    open: Open,
) -> Result<Option<AutomationStore>, AgentdError>
where
    Open: FnOnce() -> OpenFuture,
    OpenFuture: Future<Output = Result<AutomationStore, AutomationError>>,
{
    state.refresh_generation()?;
    let opened = open().await;
    state.refresh_generation()?;
    match opened {
        Ok(store) => Ok(Some(store)),
        Err(AutomationError::Unavailable | AutomationError::Corrupt) => Ok(None),
        Err(error) => Err(error.into()),
    }
}
