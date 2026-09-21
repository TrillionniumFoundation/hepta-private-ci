//! TaskFlow's module-owned constructor for the existing RuntimeTasks host.
//!
//! Local service retirement is not permanent timer retirement, writer handoff,
//! state migration, topology selection or external-effect completion. The
//! durable owner must still hand off/resume or permanently retire its timer.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationStore;
use codex_hepta_types::Generation;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::RuntimeTasks;

/// Construct one real scheduler through the same versioned lifecycle used by
/// other admitted optional services. Validation never starts a task. Callers
/// retain the Agent writer lock; no additional authority is issued here.
pub(crate) fn spawn_automation_service(
    tasks: &mut RuntimeTasks,
    store: Option<AutomationStore>,
    state: Arc<AgentdState>,
    identity: AgentdIdentity,
    host_cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    if state.identity() != &identity
        || store
            .as_ref()
            .is_some_and(|store| store.owner_agent_id() != &identity.agent_id)
    {
        return Err(AgentdError::GenerationFenced(
            "automation service identity does not match its host or owner".to_string(),
        ));
    }
    state.refresh_generation()?;
    let generation = Generation::new(identity.spawn_generation)
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    // This acknowledgement is private to the worker and its retirement
    // callback. A caller cannot submit a boolean as durable drain evidence.
    let drained = Arc::new(AtomicBool::new(false));
    let worker_drained = Arc::clone(&drained);
    let quarantine_state = Arc::clone(&state);
    let retirement_state = Arc::clone(&state);
    tasks.spawn_optional_service_generation(
        "automation.taskflow",
        generation,
        None,
        move |service_cancellation| async move {
            let owner = store.clone();
            match store {
                Some(store) => {
                    super::run_automation_scheduler(
                        store,
                        Arc::clone(&state),
                        identity,
                        service_cancellation.clone(),
                    )
                    .await?;
                }
                None => service_cancellation.cancelled().await,
            }
            // Ordinary process shutdown must not permanently disable a timer
            // or manufacture a service-retirement acknowledgement. A restart
            // continues to use the existing durable recovery protocol.
            if host_cancellation.is_cancelled() {
                return Ok(());
            }
            if !service_cancellation.is_cancelled() {
                return Err(AgentdError::Protocol(
                    "automation service stopped without a retirement request".to_string(),
                ));
            }
            if let Some(owner) = owner {
                if !state.automation_is_available()? {
                    return Err(AgentdError::Protocol(
                        "quarantined automation cannot acknowledge retirement".to_string(),
                    ));
                }
                // The scheduler has completed its last tick before this point.
                // Quiesce and inspect the actual destination-owned SQLite state;
                // an expired lease or unknown queue response is not drain.
                let status = owner.quiesce_timer().await?;
                if !status.can_handoff() {
                    return Err(AgentdError::Protocol(
                        "automation retirement has unresolved owner dispatches".to_string(),
                    ));
                }
            }
            worker_drained.store(true, Ordering::Release);
            Ok(())
        },
        move || quarantine_state.mark_automation_unavailable(),
        move || {
            if !drained.load(Ordering::Acquire) {
                return Err(AgentdError::Protocol(
                    "automation owner drain has not been acknowledged".to_string(),
                ));
            }
            // Remove the product attachment only after drain. Quarantine keeps
            // its module writer reservation: task retirement alone must not
            // authorize a replacement module or a second durable writer.
            retirement_state.mark_automation_unavailable()
        },
    )
}
