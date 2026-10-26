//! Read-only projection of an original Notes application terminal receipt.

use super::ProductionDurableWriter;
use super::ProductionWriterError;
use crate::LocalOutcomeState;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;

/// Exact bytes read from the original operation/event/outbox snapshot. This
/// observation is not a grant, dispatch ticket or receipt-retirement permit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionNotesTerminalObservation {
    pub operation: OperationIntentV1,
    pub payload_json: String,
    pub state: LocalOutcomeState,
    pub application_receipt_json: String,
    pub application_receipt_sha256: Sha256Digest,
    pub terminal_event_id: String,
    pub terminal_event_sha256: Sha256Digest,
    pub terminal_generation: u64,
}

impl ProductionDurableWriter {
    /// Verify the immutable operation and application receipt in one original
    /// read-only transaction, with live authority checks before and after it.
    /// `None` means no retained application terminal observation is available;
    /// neither absence nor an error permits dispatch or repetition of an effect.
    /// A source-only rejection reason is not accepted as an application receipt.
    pub async fn observe_notes_terminal(
        &self,
        operation_id: &str,
    ) -> Result<Option<ProductionNotesTerminalObservation>, ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        self.verify_authority().await?;
        let result = self.lease.retained_notes_terminal(operation_id).await?;
        self.verify_authority().await?;
        Ok(result)
    }
}
