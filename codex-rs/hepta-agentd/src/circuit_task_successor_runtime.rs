//! The original required blocking worker owns the pending installation too.
//! No caller-supplied loop or provider can construct this bootstrap.

use super::*;
use crate::circuit_q24_successor::PendingSuccessorOwner;
use crate::circuit_q24_successor::SuccessorSlot;

impl CircuitTaskHandleV1 {
    pub(crate) fn original_pending_successor_handle(slot: Arc<SuccessorSlot>) -> Self {
        Self { route: TaskHandleRoute::OriginalQ24 { slot } }
    }
}

impl CircuitTaskRuntimeBootstrapV1 {
    pub(crate) fn from_original_successor_worker(
        identity: &AgentdIdentity,
        slot: Arc<SuccessorSlot>,
        pending: PendingSuccessorOwner,
    ) -> Self {
        Self {
            identity: identity.clone(),
            handle: CircuitTaskHandleV1::original_pending_successor_handle(slot),
            owner: Box::new(move |store, state, cancellation| {
                Box::pin(pending.run(store, state, cancellation))
            }),
        }
    }

    pub(crate) async fn run_in_original_successor_lane(
        self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        self.require_identity(state.identity())?;
        self.handle.require_direct_original_handle().map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced("successor Automation owner differs".into()));
        }
        // Already inside the same required spawn_blocking worker. This is the
        // actual channel loop, not another detached task or substitute driver.
        (self.owner)(store, state, cancellation).await
    }
}
