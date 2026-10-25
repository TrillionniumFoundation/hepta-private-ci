//! Private type erasure for the one coordinator installed by consuming bind.

use super::*;
use std::pin::Pin;

/// Allows original owner cleanup to acknowledge a whole cut without creating
/// an Objective sender or ticket. Only the bound protected coordinator supplies
/// this capability; it contains neither a store handle nor another ledger.
pub(crate) trait BoundOwnerPublication: Send + Sync {
    fn deadline(&self) -> Duration;
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
