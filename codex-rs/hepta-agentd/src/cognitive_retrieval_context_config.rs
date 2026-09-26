use std::path::PathBuf;
use std::sync::Arc;

use crate::AgentdConfig;
use crate::AgentdError;

use super::file::FileCurrentMemoryRetrievalContextV1;
use super::file::MemoryRetrievalContextVerifierV1;

impl AgentdConfig {
    /// Attach the ordinary-process signed HNMF context provider.
    ///
    /// The provider reopens and verifies the owner file for every currentness
    /// check, so an in-place revocation or generation rotation takes effect
    /// before the next retrieval publication.
    pub fn with_signed_memory_retrieval_context_file(
        self,
        path: PathBuf,
        signer_id: String,
        verifying_key: [u8; 32],
    ) -> Result<Self, AgentdError> {
        let identity = self.identity().clone();
        let provider = FileCurrentMemoryRetrievalContextV1::new(
            path,
            identity.agent_id,
            identity.spawn_generation,
            identity.home_root,
            MemoryRetrievalContextVerifierV1 {
                signer_id,
                verifying_key,
            },
        )
        .map_err(|error| {
            AgentdError::Invalid(format!("memory.retrieval context provider: {error}"))
        })?;
        self.with_cognitive_retrieval_context(Arc::new(provider))
    }
}
