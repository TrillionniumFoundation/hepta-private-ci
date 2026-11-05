//! A target-validated retirement ACK retained by the original source owner.
//! Public callers cannot construct or deserialize this observation.

use super::*;
use crate::cognitive_store::capture_recovery_anchor;

#[derive(Clone, Debug)]
pub struct ProductionRetirementAck {
    record: RecordedRetirementAck,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RecordedRetirementAck {
    pub(crate) schema_version: u16,
    pub(crate) lease_id: String,
    pub(crate) operation_id: String,
    pub(crate) destination_id: String,
    pub(crate) topic: String,
    pub(crate) payload_sha256: Sha256Digest,
    pub(crate) terminal_receipt_sha256: Sha256Digest,
}

impl ProductionRetirementAck {
    /// Called only after the original application adapter validated an actual
    /// ACK, or its exact process-local already-validated ACK cache.
    pub(crate) fn from_validated_target(
        request: &ProductionDispatchRequest,
        terminal: &str,
    ) -> Result<Self, String> {
        if !matches!(
            request.topic.as_str(),
            crate::NOTES_REPLACE_TOPIC_V1 | crate::CALCULATOR_EVALUATE_TOPIC_V1
        ) || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
        {
            return Err("retirement ACK has invalid original application binding".into());
        }
        Ok(Self {
            record: RecordedRetirementAck {
                schema_version: 1,
                lease_id: request.lease_id.clone(),
                operation_id: request.occurrence_key.clone(),
                destination_id: request.operation_destination_id.clone(),
                topic: request.topic.clone(),
                payload_sha256: request.payload_sha256.clone(),
                terminal_receipt_sha256: Sha256Digest::for_bytes(terminal.as_bytes()),
            },
        })
    }

    pub(crate) fn record(&self) -> &RecordedRetirementAck {
        &self.record
    }

    pub(crate) fn matches(
        &self,
        request: &ProductionDispatchRequest,
        terminal: &str,
    ) -> Result<(), ProductionWriterError> {
        let expected = RecordedRetirementAck {
            schema_version: 1,
            lease_id: request.lease_id.clone(),
            operation_id: request.occurrence_key.clone(),
            destination_id: request.operation_destination_id.clone(),
            topic: request.topic.clone(),
            payload_sha256: request.payload_sha256.clone(),
            terminal_receipt_sha256: Sha256Digest::for_bytes(terminal.as_bytes()),
        };
        if self.record != expected
            || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
        {
            return Err(ProductionWriterError::Invalid(
                "target retirement ACK changed its original operation".into(),
            ));
        }

        Ok(())
    }
}

impl ProductionDurableWriter {
    /// Read the actual bound protected Current while holding the original
    /// lock-only SQLite barrier. No source event or protected head is changed.
    pub async fn observed_current_owner_receipt(
        &self,
    ) -> Result<crate::CognitiveCheckpointReceipt, ProductionWriterError> {
        self.require_protected_retirement_reader().await?;
        let mut transaction = self
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let observed = self
            .observe_bound_current_transaction(&mut transaction)
            .await?;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.verify_authority().await?;
        Ok(observed)
    }

    /// Observe one original Notes ACK under the original SQLite barrier and
    /// the actual bound protected Current. This cannot publish, dispatch or ACK.
    /// Missing ACK is false; unknown operation, non-Committed state, corruption
    /// and an unmanaged/Dirty/uncertain owner are errors.
    pub async fn retained_notes_retirement_ack(
        &self,
        operation_id: &str,
    ) -> Result<bool, ProductionWriterError> {
        self.retained_application_retirement_ack(operation_id, crate::NOTES_REPLACE_TOPIC_V1)
            .await
    }

    /// The Calculator counterpart of retained_notes_retirement_ack.
    pub async fn retained_calculator_retirement_ack(
        &self,
        operation_id: &str,
    ) -> Result<bool, ProductionWriterError> {
        self.retained_application_retirement_ack(operation_id, crate::CALCULATOR_EVALUATE_TOPIC_V1)
            .await
    }

    async fn require_protected_retirement_reader(&self) -> Result<(), ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        self.verify_authority().await?;
        if !self.store.commit_gate.is_managed() {
            return Err(ProductionWriterError::Durability(
                "retirement observation requires the original protected owner".into(),
            ));
        }
        if self.store.commit_gate.is_fenced() {
            return Err(ProductionWriterError::CheckpointFenced);
        }
        Ok(())
    }

    async fn observe_bound_current_transaction(
        &self,
        transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    ) -> Result<crate::CognitiveCheckpointReceipt, ProductionWriterError> {
        self.lease.require_current_transaction(transaction).await?;
        let cut = capture_recovery_anchor(transaction, self.owner_agent_id())
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let publication = self.store.bound_owner_publication().ok_or_else(|| {
            ProductionWriterError::Durability(
                "protected retirement observation has no bound coordinator".into(),
            )
        })?;
        self.retirement_live_check()?;
        let observed =
            tokio::time::timeout(publication.deadline(), publication.observe_current(&cut))
                .await
                .map_err(|_| ProductionWriterError::CheckpointFenced)?
                .map_err(|_| ProductionWriterError::CheckpointFenced)?;
        self.retirement_live_check()?;
        if self.store.commit_gate.is_fenced() {
            return Err(ProductionWriterError::CheckpointFenced);
        }
        Ok(observed)
    }

    async fn retained_application_retirement_ack(
        &self,
        operation_id: &str,
        topic: &str,
    ) -> Result<bool, ProductionWriterError> {
        self.require_protected_retirement_reader().await?;
        let mut transaction = self
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let retained = self
            .lease
            .retained_application_retirement_ack_transaction(&mut transaction, operation_id, topic)
            .await?;
        self.observe_bound_current_transaction(&mut transaction)
            .await?;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.verify_authority().await?;
        Ok(retained.is_some())
    }

    pub(super) async fn finish_application_retirement(
        &self,
        acknowledgement: &ProductionRetirementAck,
        already_recorded: bool,
    ) -> Result<(), ProductionWriterError> {
        self.retirement_live_check()?;
        // Re-ACK of the same original operation is metadata-only. It must not
        // append another event or dirty an already protected Current.
        if already_recorded {
            return Ok(());
        }
        self.verify_authority().await?;
        self.lease
            .record_application_retirement_ack(acknowledgement, || {
                self.retirement_live_check()
                    .map_err(|error| error.to_string())
            })
            .await?;
        // The guarded checkout performed durable Dirty before the source COMMIT.
        // Publish the new whole owner cut through its existing bound capability.
        // Any uncertain publication leaves the source generation fenced.
        let mut transaction = self
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.acknowledge_bound_owner_transaction(&mut transaction)
            .await?;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        Ok(())
    }
}
