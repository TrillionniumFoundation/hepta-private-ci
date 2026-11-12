//! Binding of the actual retained C purpose owners after Root intent.

use super::*;

impl OriginalSameActorCPurposesRetired {
    /// Validate the already sealed terminal route/slot and actual returned
    /// Learning owners. CURRENT and ordinary Session admission stay stopped.
    pub(crate) fn require_original_phase(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        let checked = (|| {
            self.original.origin.require_original_binding(identity, gate)?;
            self.original
                .slot
                .require_original_retired_slot(&self.original.origin)?;
            let route = self.original.origin.original_route()?;
            if !Arc::ptr_eq(&route, &self.route)
                || self.original.installed.identity != self.original.origin.identity
            {
                return Err(retirement_error("original C retired purpose custody differs"));
            }
            OriginalRetiredLearningPurposes::require_original_work(&self.learning, &self.work)?;
            let state = route.state.lock().map_err(|_| poisoned_route())?;
            if state.closed || state.tickets != 0 || !matches!(state.phase, Phase::RetiredC) {
                return Err(retirement_error("original C purpose route is not retired"));
            }
            self.original.origin.gate.require_open().map_err(phase_error)?;
            Ok(())
        })();
        if checked.is_err() {
            self.original.origin.gate.close();
        }
        checked
    }
}
