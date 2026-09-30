//! Signed retrieval publications with a bounded, product-composable transport.

#[path = "cognitive_retrieval_bootstrap.rs"]
mod bootstrap;
#[path = "cognitive_retrieval_provider_core.rs"]
mod implementation;
#[path = "cognitive_retrieval_transport.rs"]
mod transport;

pub use implementation::LeasedMemoryRetrievalProviderV1;
pub use implementation::MemoryRetrievalFrontierOwnerV1;
pub use implementation::MemoryRetrievalFrontierV1;
pub use implementation::SignedMemoryRetrievalContextV1;

impl LeasedMemoryRetrievalProviderV1 {
    /// Compose explicitly pinned, protected host inputs. No authority keys or
    /// independent owner state are created by this loader.
    pub fn load_process_bootstrap(
        path: &std::path::Path,
        expected_digest: codex_hepta_types::Digest32,
        identity: &crate::AgentdIdentity,
    ) -> Result<std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>, String> {
        bootstrap::load(path, expected_digest, identity)
    }

    /// The separately managed frontier owner must retain monotonic state
    /// outside the Agent home's rollback domain.
    #[allow(clippy::too_many_arguments)]
    pub fn from_loopback_frontier(
        owner: codex_hepta_contracts::AgentId,
        body_generation: u64,
        context_public_key: [u8; 32],
        frontier_public_key: [u8; 32],
        endpoint: std::net::SocketAddr,
        request_timeout: std::time::Duration,
        maximum_lease_ms: u64,
    ) -> Result<Self, String> {
        let transport = transport::LoopbackFrontierClient::new(endpoint, request_timeout)?;
        Self::new(
            owner,
            body_generation,
            context_public_key,
            frontier_public_key,
            std::sync::Arc::new(transport),
            maximum_lease_ms,
        )
    }
}

#[cfg(test)]
#[path = "cognitive_retrieval_acquisition_tests.rs"]
mod acquisition_tests;
