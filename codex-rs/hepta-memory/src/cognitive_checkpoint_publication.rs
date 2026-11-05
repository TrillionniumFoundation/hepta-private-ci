//! Private type erasure for the one coordinator installed by consuming bind.

use super::*;
use std::pin::Pin;

/// Allows original owner cleanup to acknowledge a whole cut without creating
/// an Objective sender or ticket. Only the bound protected coordinator supplies
/// this capability; it contains neither a store handle nor another ledger.
pub(crate) trait BoundOwnerPublication: Send + Sync {
    fn deadline(&self) -> Duration;
    /// Observe the actual authenticated peer without publishing or dirtying.
    fn observe_current<'a>(
        &'a self,
        cut: &'a CognitiveRecoveryAnchor,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError>>
                + Send
                + 'a,
        >,
    >;

    fn acknowledge<'a>(
        &'a self,
        cut: &'a CognitiveRecoveryAnchor,
        fence: &'a ObjectiveSenderWriterFence,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError>>
                + Send
                + 'a,
        >,
    >;
}

impl<T: CognitiveCheckpointTransport> BoundOwnerPublication for ProtectedCognitiveCheckpoint<T> {
    fn deadline(&self) -> Duration {
        self.deadline
    }
    fn observe_current<'a>(
        &'a self,
        cut: &'a CognitiveRecoveryAnchor,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<CognitiveCheckpointReceipt, ObjectiveSenderCheckpointError>>
                + Send
                + 'a,
        >,
    > {
        Box::pin(async move {
            let current = self.observed_current_receipt().await?;
            if current.head.last_current != *cut {
                return Err(ObjectiveSenderCheckpointError::Refused);
            }
            Ok(current)
        })
    }

    fn acknowledge<'a>(
        &'a self,
        cut: &'a CognitiveRecoveryAnchor,
        fence: &'a ObjectiveSenderWriterFence,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError>>
                + Send
                + 'a,
        >,
    > {
        Box::pin(self.acknowledge_current(cut, fence))
    }
}
