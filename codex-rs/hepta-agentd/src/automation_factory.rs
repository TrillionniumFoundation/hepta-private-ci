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
    selection: Option<codex_hepta_agent_protocol::RuntimeModuleSelectionV1>,
}

impl AutomationService {
    pub(crate) async fn open(
        state: Arc<AgentdState>,
        profile: crate::RuntimeModuleProfileV1,
    ) -> Result<Self, AgentdError> {
        state.refresh_generation()?;
        let selection = match profile {
            crate::RuntimeModuleProfileV1::Compiled => None,
            crate::RuntimeModuleProfileV1::SupervisorSelected => Some(
                crate::module_selection::observe_compiled_selection(
                    state.identity(),
                    "automation.taskflow",
                )
                .await?,
            ),
        };
        state.refresh_generation()?;
        // An explicitly unselected optional module does not even open/migrate
        // its store. This does not delete its history or mint a retirement receipt.
        if selection
            .as_ref()
            .is_some_and(|value| value.selected.is_none())
        {
            // Switching profiles is not a stateful-retirement operation. The
            // existing Agent writer lock excludes another admitted host while
            // this bounded directory check distinguishes a new optional module
            // from retained state that still needs its own recovery/retirement.
            let mut entries = std::fs::read_dir(state.identity().layout.automation_root())?;
            if entries.next().transpose()?.is_some() {
                return Err(AgentdError::GenerationFenced(
                    "unselected Automation retains owner state; explicit owner recovery or retirement is required".to_string(),
                ));
            }
            return Ok(Self {
                store: None,
                state,
                selection,
            });
        }
        let layout = state.identity().layout.clone();
        let store = open_automation_store_after_generation_fence(&state, || async move {
            AutomationStore::open(&layout).await
        })
        .await?;
        // An explicitly selected module is a required startup binding. Preserve
        // the legacy compiled profile's optional degradation, but never convert
        // selected corrupt/unavailable state into absence and false readiness.
        if selection
            .as_ref()
            .is_some_and(|value| value.selected.is_some())
            && store.is_none()
        {
            return Err(AgentdError::Protocol(
                "selected Automation owner is unavailable or corrupt; explicit owner recovery is required".to_string(),
            ));
        }
        if selection.is_none()
            && let Some(store) = store.as_ref()
        {
            state.attach_automation_store(store.clone())?;
        }
        Ok(Self {
            store,
            state,
            selection,
        })
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
        self.state.refresh_generation()?;
        if let Some(expected) = &self.selection {
            let current = crate::module_selection::observe_compiled_selection(
                &identity,
                "automation.taskflow",
            )
            .await?;
            if &current != expected {
                return Err(AgentdError::GenerationFenced(
                    "module selection changed during owner startup".to_string(),
                ));
            }
        }
        self.state.refresh_generation()?;
        if self
            .selection
            .as_ref()
            .is_some_and(|selection| selection.selected.is_none())
        {
            self.state.mark_automation_absent()?;
        }
        let generation = self
            .selection
            .as_ref()
            .and_then(|selection| selection.selected.as_ref())
            .map_or(identity.spawn_generation, |binding| binding.generation);
        let generation = codex_hepta_agent_components::types::Generation::new(generation)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        // Selected owners remain unpublished until both sides of bounded
        // startup I/O have observed the same selection and process generation.
        if self.selection.is_some()
            && let Some(store) = self.store.as_ref()
        {
            self.state.attach_automation_store(store.clone())?;
        }
        let state = Arc::clone(&self.state);
        let selected_profile = self.selection.is_some();
        let result = super::spawn_automation_service(
            tasks,
            self.store,
            self.state,
            identity,
            queue,
            host_cancellation,
            generation,
        )
        .await;
        if result.is_err() && selected_profile {
            state.mark_automation_unavailable()?;
        }
        result
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
