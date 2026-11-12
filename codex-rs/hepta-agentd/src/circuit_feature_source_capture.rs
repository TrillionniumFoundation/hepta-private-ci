//! Retain only the exact original Initial CURRENT connection. Keeping the
//! PublishedTask itself would retain the original Cell journal across drain.

use std::sync::Arc;

use super::PublishedCircuitFeatureTaskV1;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdRootAuthoritySession;
use crate::NeuronGenerationCurrentOwnerV1;

impl PublishedCircuitFeatureTaskV1 {
    pub(crate) fn original_initial_source_current(
        &self,
        session: &AgentdRootAuthoritySession,
        identity: &AgentdIdentity,
    ) -> Result<Arc<NeuronGenerationCurrentOwnerV1>, AgentdError> {
        self.0.current.original_initial_source_current(session, identity)
    }
}
