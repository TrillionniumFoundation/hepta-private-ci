//! Binding checks for the two actual returned purpose-retired owner bundles.
//! Keep their methods separate so the original joined-owner function guards
//! retain unique function extents. No constructor or new authority lives here.

use super::*;

impl OriginalRetiredLearningPurposes {
    pub(crate) fn require_original_work(
        &self,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        OriginalRetiredLearningOwners::require_original_work(&self.owners, work)
    }
}

impl OriginalSameActorLearningPurposesRetired {
    pub(crate) fn require_original_phase(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        crate::circuit_task::OriginalSameActorCPurposesRetired::require_original_phase(
            &self.original, identity, gate,
        )
    }
}

