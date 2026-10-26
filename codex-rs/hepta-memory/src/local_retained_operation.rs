//! Reuse the original ledger's checks; no alternate operation history.
use super::*;
use crate::ProductionNotesTerminalObservation;
use crate::ProductionRetainedOperation;
use crate::production_notes::NotesTerminalReceipt;

impl LocalLeaseOutbox {
    pub(crate) async fn retained_operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<ProductionRetainedOperation>, LocalLeaseOutboxError> {
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        let mut transaction = self
            .store
            .observation_pool()
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let result = self
            .retained_operation_in(&mut transaction, operation_id)
            .await;
        transaction
            .rollback()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        result
    }

    pub(crate) async fn retained_notes_terminal(
        &self,
        operation_id: &str,
    ) -> Result<Option<ProductionNotesTerminalObservation>, LocalLeaseOutboxError> {
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        let mut transaction = self
            .store
            .observation_pool()
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let result = async {
            let Some(retained) = self
                .retained_operation_in(&mut transaction, operation_id)
                .await?
            else {
                return Ok(None);
            };
            if retained.topic != crate::NOTES_REPLACE_TOPIC_V1 {
                return Err(LocalLeaseOutboxError::Invalid(
                    "Notes observation targets another operation topic".into(),
                ));
            }
            let (kind, outcome) = match retained.state {
                LocalOutcomeState::Committed => {
                    ("reconcile_committed", LocalReconcileOutcome::Committed)
                }
                LocalOutcomeState::Rejected => {
                    ("reconcile_rejected", LocalReconcileOutcome::Rejected)
                }
                LocalOutcomeState::Queued
                | LocalOutcomeState::Indeterminate
                | LocalOutcomeState::RolledBack => return Ok(None),
            };
            let event = latest_occurrence_event(
                &mut transaction,
                &self.lease_id,
                operation_id,
                &self.owner_agent_id,
            )
            .await?
            .ok_or_else(|| corrupt("Notes terminal event is absent"))?;
            if event.kind != kind
                || retained.payload_json.len() > crate::NOTES_REQUEST_MAX_BYTES
                || event.payload_json.len() > crate::NOTES_RESPONSE_MAX_BYTES
            {
                return Err(corrupt(
                    "Notes terminal event differs from original outcome",
                ));
            }
            let receipt =
                NotesTerminalReceipt::from_json(&retained.payload_json, &event.payload_json)
                    .map_err(LocalLeaseOutboxError::Invalid)?;
            if receipt.outcome() != outcome {
                return Err(corrupt(
                    "Notes application receipt differs from original outcome",
                ));
            }
            let payload: serde_json::Value = serde_json::from_str(&retained.payload_json)
                .map_err(|_| corrupt("Notes operation payload is invalid"))?;
            let target: crate::NotesTargetIdentity =
                serde_json::from_value(payload["target"].clone())
                    .map_err(|_| corrupt("Notes operation target is invalid"))?;
            let operation = crate::notes_operation_intent(
                &target,
                &retained.payload_json,
                StableId::new(self.owner_agent_id.as_str())
                    .map_err(|error| LocalLeaseOutboxError::Invalid(error.to_string()))?,
                retained.operation.policy_generation(),
            )
            .map_err(LocalLeaseOutboxError::Invalid)?;
            if operation != retained.operation {
                return Err(corrupt(
                    "Notes payload differs from the original operation intent",
                ));
            }
            Ok(Some(ProductionNotesTerminalObservation {
                operation,
                payload_json: retained.payload_json,
                state: retained.state,
                application_receipt_json: event.payload_json,
                application_receipt_sha256: event.payload_sha256,
                terminal_event_id: event.event_id,
                terminal_event_sha256: event.event_sha256,
                terminal_generation: event.generation,
            }))
        }
        .await;
        transaction
            .rollback()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        result
    }

    async fn retained_operation_in(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        operation_id: &str,
    ) -> Result<Option<ProductionRetainedOperation>, LocalLeaseOutboxError> {
        let lease = self.current_lease(transaction).await?;
        ensure_current_active(&lease, self)?;
        let Some(admission) = find_admission(
            transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?
        else {
            return Ok(None);
        };
        let outbox = find_outbox(
            transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("operation admission has no paired outbox row"))?;
        let stored = find_operation(transaction, operation_id)
            .await?
            .ok_or_else(|| corrupt("operation admission has no operation row"))?;
        let operation = verify_operation_row_incremental(
            &stored,
            &self.lease_id,
            &self.owner_agent_id,
            &admission,
            &outbox,
        )?;
        ensure_occurrence_readable(transaction, self, &admission, &outbox).await?;
        let state = current_outcome(
            transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?;
        Ok(Some(ProductionRetainedOperation {
            operation,
            topic: outbox.topic,
            payload_json: outbox.payload_json,
            state,
        }))
    }
}
