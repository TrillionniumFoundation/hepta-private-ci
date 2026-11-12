//! An actual live-session read capability for the independent B purpose. It
//! retains the original verifier object; public bootstrap data cannot create it.

use super::*;

pub(crate) struct OriginalRootBEvaluationConnectionV1 {
    original: RootGenerationPublicationConnectionV1,
}

impl RootGenerationPublicationConnectionV1 {
    pub(crate) fn capture_original_b_connection(
        &self,
    ) -> Result<OriginalRootBEvaluationConnectionV1, AgentdError> {
        self.require_original_publication_session()?;
        let original = RootGenerationPublicationConnectionV1 {
            original: self.original.clone(),
            identity: self.identity.clone(),
            authority: self.authority.clone(),
            verifier: Arc::clone(&self.verifier),
        };
        original.require_original_publication_session()?;
        Ok(OriginalRootBEvaluationConnectionV1 { original })
    }
}

impl OriginalRootBEvaluationConnectionV1 {
    pub(crate) fn require_original(&self) -> Result<(), AgentdError> {
        self.original.require_original_publication_session()
    }
    pub(crate) fn original_launch_binding(
        &self,
    ) -> (&HostAuthorityPublicBootstrapV1, &AgentdIdentity) {
        self.original.original_launch_binding()
    }
}
