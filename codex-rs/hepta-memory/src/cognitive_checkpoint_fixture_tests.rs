//! Fault injection for an explicit stale-receipt fixture; no production API.

use super::CognitiveCheckpointTransport;
use super::ProtectedCognitiveCheckpoint;
use crate::cognitive_checkpoint_wire::CognitiveCheckpointReceipt;

impl<T: CognitiveCheckpointTransport> ProtectedCognitiveCheckpoint<T> {
    pub(crate) async fn replace_receipt_for_fixture(&self, receipt: CognitiveCheckpointReceipt) {
        *self.receipt.lock().await = receipt;
    }
}
