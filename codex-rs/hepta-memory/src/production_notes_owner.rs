//! Notes receipt retirement belongs to the original recovered source writer.
//! Reuses its immutable outbox and event chain; no additional ledger or signer.

use super::*;
use crate::production_notes::NotesTerminalReceipt;

/// Borrowed, non-serializable permission to discard one exact application
/// receipt. Only a live original writer can construct this after verifying the
/// existing durable terminal event and its immutable operation binding.
pub struct NotesRetirementPermit {
    request: ProductionDispatchRequest,
    receipt: String,
}

impl NotesRetirementPermit {
    pub(crate) fn request(&self) -> &ProductionDispatchRequest {
        &self.request
    }
    pub(crate) fn receipt(&self) -> &str {
        &self.receipt
    }
}

impl ProductionDurableWriter {
    pub(super) async fn settle_notes_terminal(
        &self,
        request: &ProductionDispatchRequest,
        evidence: &str,
        expected: LocalReconcileOutcome,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        if request.topic != crate::NOTES_REPLACE_TOPIC_V1 {
            return Err(ProductionWriterError::Invalid(
                "Notes evidence targets another topic".to_string(),
            ));
        }
        let receipt = NotesTerminalReceipt::from_json(&request.payload_json, evidence)
            .map_err(ProductionWriterError::Invalid)?;
        if receipt.outcome() != expected {
            return Err(ProductionWriterError::Invalid(
                "Notes disposition differs from terminal evidence".to_string(),
            ));
        }
        Ok(self
            .lease
            .reconcile_notes_terminal(&request.occurrence_key, &receipt)
            .await?
            .into())
    }

    /// Retry only receipt retirement, never application dispatch. Failure does
    /// not undo a durable source result; the application keeps its pending
    /// receipt until it accepts this exact ACK. A lost ACK is safely repeatable.
    pub async fn retire_notes_receipt<T: FinalUseProductionOutboxTarget + ?Sized>(
        &self,
        target: &T,
        operation_id: &str,
    ) -> Result<(), ProductionWriterError> {
        self.verify_authority().await?;
        self.lease.verify_current().await?;
        let request = self
            .reconciliation_request(operation_id, target.destination_id())
            .await?;
        if request.topic != crate::NOTES_REPLACE_TOPIC_V1 {
            return Err(ProductionWriterError::Invalid(
                "Notes retirement targets another topic".to_string(),
            ));
        }
        let (kind, receipt, digest): (String, String, String) = sqlx::query_as(
            "SELECT event_kind, payload_json, payload_sha256 FROM cognitive_local_events
             WHERE lease_id = ? AND occurrence_key = ? ORDER BY event_sequence DESC LIMIT 1",
        )
        .bind(self.lease_id())
        .bind(operation_id)
        .fetch_optional(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?
        .ok_or_else(|| {
            ProductionWriterError::Invalid("Notes terminal event is absent".to_string())
        })?;
        if kind != "reconcile_committed"
            || Sha256Digest::for_bytes(receipt.as_bytes()).as_str() != digest
        {
            return Err(ProductionWriterError::Invalid(
                "Notes terminal receipt is not durably committed".to_string(),
            ));
        }
        let checked = NotesTerminalReceipt::from_json(&request.payload_json, &receipt)
            .map_err(ProductionWriterError::Invalid)?;
        if checked.outcome() != LocalReconcileOutcome::Committed {
            return Err(ProductionWriterError::Invalid(
                "Notes terminal event is not applied".to_string(),
            ));
        }
        self.verify_authority().await?;
        let permit = NotesRetirementPermit { request, receipt };
        // Recheck the original verifier after all SQLite awaits and immediately
        // before the synchronous metadata-only destination call.
        self.authority
            .validate_for_agent(self.store.owner_agent_id())?;
        self.live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify(&self.authority, self.store.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)?;
        target
            .retire_notes_receipt(&permit)
            .map_err(ProductionWriterError::Durability)
    }

    pub(super) async fn retry_notes_retirement<T: FinalUseProductionOutboxTarget + ?Sized>(
        &self,
        target: &T,
    ) -> Result<(), ProductionWriterError> {
        if !target.destination_id().starts_with("trill.notes:") {
            return Ok(());
        }
        // Capacity is one at the application. Its only potentially pending
        // applied receipt is therefore the latest committed operation for this
        // exact incarnation. Older source receipts remain in the same journal.
        let latest: Option<String> = sqlx::query_scalar(
            "SELECT e.occurrence_key FROM cognitive_local_events e
             JOIN cognitive_operation_ledger o ON o.lease_id = e.lease_id AND o.operation_id = e.occurrence_key
             JOIN cognitive_local_outbox b ON b.lease_id = e.lease_id AND b.occurrence_key = e.occurrence_key
             WHERE e.lease_id = ? AND o.destination_id = ? AND b.topic = ?
               AND e.event_kind = 'reconcile_committed'
             ORDER BY e.event_sequence DESC LIMIT 1",
        ).bind(self.lease_id()).bind(target.destination_id()).bind(crate::NOTES_REPLACE_TOPIC_V1)
            .fetch_optional(&self.store.pool).await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        if let Some(operation_id) = latest {
            self.retire_notes_receipt(target, &operation_id).await?;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "production_notes_owner_tests.rs"]
mod tests;
