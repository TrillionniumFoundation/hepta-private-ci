//! Binding of the actual retired Session observation purpose.

use super::*;

impl OriginalRootSessionObservationRetired {
    pub(crate) fn require_original_origin(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        if self.original.resources._stream.is_some() || self.original.resources._stop.is_some() {
            return Err(join_error(
                "actual original observation purpose is still held open",
            ));
        }
        self.original
            .require_original_joined_custody(identity, gate)
    }
}
