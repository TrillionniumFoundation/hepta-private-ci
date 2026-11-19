//! Notes receipt retirement belongs to the original recovered source writer.
//! Reuses its immutable outbox and event chain; no additional ledger or signer.

use super::*;
use crate::production_notes::NotesTerminalReceipt;

/// Non-serializable evidence created only by the original writer when FinalUse
/// rejects synchronously before the target is entered. This is not an
/// application receipt and cannot be supplied by a target or public caller.
pub(crate) struct NotesPreDispatchRejection {
    request: ProductionDispatchRequest,
    dispatch_event_id: String,
    reason: String,
}

impl NotesPreDispatchRejection {
    pub(super) fn at_rejected_entry(
        request: &ProductionDispatchRequest,
        dispatch_event_id: &str,
        reason: String,
    ) -> Self {
        Self {
            request: request.clone(),
            dispatch_event_id: dispatch_event_id.to_string(),
            reason,
        }
    }

    pub(crate) fn parts(&self) -> (&ProductionDispatchRequest, &str, &str) {
        (&self.request, &self.dispatch_event_id, &self.reason)
    }
}

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
    /// Read an exact application receipt from this original writer's existing
    /// terminal event. This creates no permit, event, dispatch, or retirement.
    /// A source-side refusal without an application receipt returns `None`.
    pub async fn retained_notes_terminal_receipt(
        &self,
        operation_id: &str,
    ) -> Result<Option<String>, ProductionWriterError> {
        let retained = self
            .retained_operation(operation_id)
            .await?
            .ok_or_else(|| {
                ProductionWriterError::Invalid("Notes observation has no original operation".into())
            })?;
        if !crate::production_notes::is_notes_topic(&retained.topic) {
            return Err(ProductionWriterError::Invalid(
                "not a Notes operation".into(),
            ));
        }
        if !matches!(
            retained.state,
            LocalOutcomeState::Committed | LocalOutcomeState::Rejected
        ) {
            return Ok(None);
        }
        let row: Option<(String, String, String)> = sqlx::query_as(
            "SELECT event_kind, payload_json, payload_sha256 FROM cognitive_local_events
             WHERE lease_id = ? AND occurrence_key = ? AND event_kind IN ('reconcile_committed', 'reconcile_rejected') ORDER BY event_sequence DESC LIMIT 1",
        )
        .bind(self.lease_id())
        .bind(operation_id)
        .fetch_optional(self.store.observation_pool())
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let Some((kind, receipt, digest)) = row else {
            let fenced: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM cognitive_local_events
                 WHERE lease_id = ? AND occurrence_key = ?
                   AND event_kind = 'notes_fence_excluded'",
            )
            .bind(self.lease_id())
            .bind(operation_id)
            .fetch_one(self.store.observation_pool())
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
            if retained.state == LocalOutcomeState::Rejected && fenced == 1 {
                self.verify_authority().await?;
                return Ok(None);
            }
            return Err(ProductionWriterError::Invalid(
                "original terminal event disappeared".into(),
            ));
        };
        if Sha256Digest::for_bytes(receipt.as_bytes()).as_str() != digest {
            return Err(ProductionWriterError::Invalid(
                "terminal event digest mismatch".into(),
            ));
        }
        let expected = match (retained.state, kind.as_str()) {
            (LocalOutcomeState::Committed, "reconcile_committed") => {
                LocalReconcileOutcome::Committed
            }
            (LocalOutcomeState::Rejected, "reconcile_rejected") => LocalReconcileOutcome::Rejected,
            _ => return Ok(None),
        };
        let checked = NotesTerminalReceipt::from_json(&retained.payload_json, &receipt)
            .map_err(ProductionWriterError::Invalid)?;
        if checked.outcome() != expected {
            return Err(ProductionWriterError::Invalid(
                "terminal disposition mismatch".into(),
            ));
        }
        self.verify_authority().await?;
        Ok(Some(receipt))
    }

    pub(super) async fn settle_notes_terminal(
        &self,
        request: &ProductionDispatchRequest,
        evidence: &str,
        expected: LocalReconcileOutcome,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        if !crate::production_notes::is_notes_topic(&request.topic) {
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

    /// Settle one indeterminate original Notes replacement only after this
    /// original writer has a committed, exactly bound fence operation in its
    /// own append-only journal.  The persisted source event is a typed causal
    /// exclusion record, never a fabricated `NotApplied` application receipt.
    pub async fn settle_notes_original_from_fence(
        &self,
        original_operation_id: &str,
        cancellation_operation_id: &str,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        if original_operation_id == cancellation_operation_id {
            return Err(ProductionWriterError::Invalid(
                "Notes fence must be a distinct operation".to_string(),
            ));
        }
        let original = self
            .retained_operation(original_operation_id)
            .await?
            .ok_or_else(|| {
                ProductionWriterError::Invalid(
                    "Notes fence has no retained original operation".to_string(),
                )
            })?;
        let cancellation = self
            .retained_operation(cancellation_operation_id)
            .await?
            .ok_or_else(|| {
                ProductionWriterError::Invalid(
                    "Notes fence has no retained cancellation operation".to_string(),
                )
            })?;
        if original.topic != crate::NOTES_REPLACE_TOPIC_V1
            || original.state != LocalOutcomeState::Indeterminate
            || cancellation.topic != crate::NOTES_FENCE_TOPIC_V1
            || cancellation.state != LocalOutcomeState::Committed
        {
            return Err(ProductionWriterError::Invalid(
                "Notes fence source states do not permit original settlement".to_string(),
            ));
        }
        let (event_id, receipt, receipt_digest, event_digest): (String, String, String, String) =
            sqlx::query_as(
                "SELECT event_id, payload_json, payload_sha256, event_sha256
             FROM cognitive_local_events
             WHERE lease_id = ? AND occurrence_key = ?
               AND event_kind = 'reconcile_committed'
             LIMIT 1",
            )
            .bind(self.lease_id())
            .bind(cancellation_operation_id)
            .fetch_optional(self.store.observation_pool())
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?
            .ok_or_else(|| {
                ProductionWriterError::Invalid("committed Notes fence event is absent".to_string())
            })?;
        if Sha256Digest::for_bytes(receipt.as_bytes()).as_str() != receipt_digest {
            return Err(ProductionWriterError::Invalid(
                "committed Notes fence event digest mismatch".to_string(),
            ));
        }
        let event_digest =
            Sha256Digest::parse(&event_digest).map_err(ProductionWriterError::Invalid)?;
        let proof = crate::production_notes::NotesFenceProof::from_committed_event(
            original_operation_id,
            &original.payload_json,
            cancellation_operation_id,
            &cancellation.payload_json,
            &event_id,
            &event_digest,
            &receipt,
        )
        .map_err(ProductionWriterError::Invalid)?;
        self.verify_authority().await?;
        Ok(self
            .lease
            .reconcile_notes_fenced_original(&proof)
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
        if !crate::production_notes::is_notes_topic(&request.topic) {
            return Err(ProductionWriterError::Invalid(
                "Notes retirement targets another topic".to_string(),
            ));
        }
        // Keep the original write-serialization lock through publication and
        // the synchronous metadata ACK. A physical READONLY connection cannot
        // provide this lock; the original managed store owns a lock-only role.
        let mut transaction = self
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let (kind, receipt, digest): (String, String, String) = sqlx::query_as(
            "SELECT event_kind, payload_json, payload_sha256 FROM cognitive_local_events
             WHERE lease_id = ? AND occurrence_key = ? AND event_kind IN ('reconcile_committed', 'reconcile_rejected') ORDER BY event_sequence DESC LIMIT 1",
        )
        .bind(self.lease_id())
        .bind(operation_id)
        .fetch_optional(&mut *transaction)
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
        let already_recorded = self
            .lease
            .retained_application_retirement_ack_transaction(
                &mut transaction,
                operation_id,
                &request.topic,
            )
            .await?
            .is_some();
        self.acknowledge_bound_owner_transaction(&mut transaction)
            .await?;
        let permit = NotesRetirementPermit { request, receipt };
        // Recheck the original verifier after all SQLite awaits and immediately
        // before the synchronous metadata-only destination call.
        self.retirement_live_check()?;
        let retired = target
            .retire_notes_receipt(&permit)
            .map_err(ProductionWriterError::Durability);
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let acknowledgement = retired?;
        acknowledgement.matches(permit.request(), permit.receipt())?;
        self.finish_application_retirement(&acknowledgement, already_recorded)
            .await
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
             WHERE e.lease_id = ? AND o.destination_id = ? AND b.topic IN (?, ?)
               AND e.event_kind = 'reconcile_committed'
             ORDER BY e.event_sequence DESC LIMIT 1",
        ).bind(self.lease_id()).bind(target.destination_id()).bind(crate::NOTES_REPLACE_TOPIC_V1).bind(crate::NOTES_FENCE_TOPIC_V1)
            .fetch_optional(self.store.observation_pool()).await
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
