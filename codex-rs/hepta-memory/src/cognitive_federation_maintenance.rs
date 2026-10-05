use std::time::Duration;

use crate::CognitiveRuntime;
use crate::CognitiveStoreError;

impl CognitiveRuntime {
    /// Performs complete, read-only integrity checks of enrolled peer stores.
    /// Call at host startup and every 60 seconds with an explicit time budget.
    /// Visits rotate when a budget admits only part of the enrollment. A source
    /// without a successful full check for 300 seconds fails closed on reads.
    /// Errors quarantine the affected pool and already-issued attachments;
    /// this operation never changes grants, memory, or writer authority.
    pub async fn maintain_federation_integrity(
        &self,
        budget: Duration,
    ) -> Result<usize, CognitiveStoreError> {
        match self {
            Self::AvailableFederatedV2 {
                store,
                owner_layouts,
                ..
            } => {
                store
                    .federation_peer_pools
                    .maintain(owner_layouts, budget)
                    .await
            }
            Self::Absent
            | Self::Unavailable(_)
            | Self::Available(_)
            | Self::AvailableFederated { .. } => Ok(0),
        }
    }
}
