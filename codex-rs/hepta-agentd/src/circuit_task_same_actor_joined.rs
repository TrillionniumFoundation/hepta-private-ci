//! Actual C joined-owner bindings, with the original private ownership intact.

use super::*;

impl OriginalSameActorCJoined {
    pub(crate) fn require_original_phase(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        self.original
            .origin
            .require_original_binding(identity, gate)?;
        self.original
            .slot
            .require_original_retired_slot(&self.original.origin)?;
        let route = self.original.origin.original_route()?;
        if !Arc::ptr_eq(&route, &self.route) {
            return Err(retirement_error(
                "original C terminal route custody differs",
            ));
        }
        OriginalRetiredLearningOwners::require_original_work(&self.learning, &self.work)?;
        let state = route.state.lock().map_err(|_| poisoned_route())?;
        if state.closed || state.tickets != 0 || !matches!(state.phase, Phase::RetiredC) {
            return Err(retirement_error("original C route has not been retired"));
        }
        Ok(())
    }

    pub(crate) fn original_completion(&self) -> &PublishedCircuitFeatureCompletionV1 {
        &self.original.completion
    }

    pub(crate) fn original_status(&self) -> &OriginalCellQ24TaskLedgerStatusV1 {
        &self.original.status
    }

    /// Keep the real CURRENT/Cell/Source/Ledger owners until Root's exact
    /// retirement intent permits their purpose streams to be released.
    pub(crate) fn require_retained_original_owners(&self) -> Result<(), AgentdError> {
        OriginalSameActorCJoined::require_original_phase(
            self,
            &self.original.origin.identity,
            &self.original.origin.gate,
        )?;
        let installed = &self.original.installed;
        if installed.identity != self.original.origin.identity {
            return Err(retirement_error("retained original C identity differs"));
        }
        Ok(())
    }
}
