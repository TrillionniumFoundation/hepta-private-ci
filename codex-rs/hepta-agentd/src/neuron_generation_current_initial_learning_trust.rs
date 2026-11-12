//! Closed bridge from the actual CURRENT store to its retained Initial client.

use super::*;

impl NeuronGenerationCurrentOwnerV1 {
    pub(crate) fn read_original_initial_learning_trust(
        &self,
        session: &crate::AgentdRootAuthoritySession,
        identity: &crate::AgentdIdentity,
    ) -> Result<crate::OriginalRootInitialLearningTrustV1, AgentdError> {
        self.store
            .original_initial_client()?
            .read_original_learning_trust(session, identity)
    }
}
