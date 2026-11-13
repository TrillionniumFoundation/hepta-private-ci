//! Read original Root learning trust only while this actual published task,
//! its selected artifacts and its consumed FinalUse remain current.

use super::*;

impl PublishedCircuitFeatureTaskV1 {
    pub(crate) fn read_original_initial_learning_trust(
        &self,
        session: &crate::AgentdRootAuthoritySession,
        identity: &AgentdIdentity,
    ) -> Result<crate::OriginalRootInitialLearningTrustV1, AgentdError> {
        self.require_current()?;
        let trust = self
            .0
            .current
            .read_initial_learning_trust(session, identity)?;
        self.require_current()?;
        Ok(trust)
    }
}
