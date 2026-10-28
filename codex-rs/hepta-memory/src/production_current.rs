//! Ordinary FinalUse boundaries use the original protected SQLite Current cut.

use super::*;
use crate::CheckpointDiagnostics;
use crate::CheckpointFailureCause;
use crate::ObjectiveSenderWriterFence;
use crate::cognitive_store::capture_recovery_anchor;
use sqlx::Sqlite;
use sqlx::Transaction;

impl ProductionDurableWriter {
    /// Confirm this live owner's complete SQLite cut with its already-bound
    /// protected Current publisher. The original write barrier remains held
    /// through acknowledgement; an uncertain reply permanently fences this
    /// generation. A local hash, an unprotected writer, or an expired/replaced
    /// authority cannot supply the missing protected acknowledgement.
    ///
    /// Stop and join background owner mutations before using the returned cut
    /// as a shutdown/crash boundary. This method does not stop other clones,
    /// close SQLite, adopt an old publisher, or authorize another delivery.
    pub async fn checkpoint_current(
        &self,
    ) -> Result<crate::CognitiveRecoveryAnchor, ProductionWriterError> {
        if self.store.current_publisher.is_none() {
            return Err(ProductionWriterError::AuthorityRejected(
                "protected Current publisher is required".into(),
            ));
        }
        self.verify_current_authority().await?;
        let mut transaction = self
            .store
            .observation_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let cut = capture_recovery_anchor(&mut transaction, self.owner_agent_id())
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.acknowledge_external_current_transaction(&mut transaction)
            .await?;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.sender_live_check()?;
        Ok(cut)
    }

    pub(crate) async fn current_writer_fence(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<ObjectiveSenderWriterFence, ProductionWriterError> {
        let lease = self.lease.require_current_transaction(transaction).await?;
        self.sender_live_check()?;
        Ok(ObjectiveSenderWriterFence {
            owner_agent_id: self.owner_agent_id().clone(),
            lease_id: self.lease_id().to_string(),
            lease_sha256: lease.lease_sha256,
            generation: self.generation(),
            authority_epoch: self.authority.authority_epoch,
            owner_epoch: self.authority.owner_epoch,
            authority_grant_digest: self.authority.grant_digest.clone(),
            fencing_token_digest: self.authority.fencing_token_digest()?,
            expires_at_unix_seconds: self.authority.lease_expires_at_unix_seconds,
        })
    }

    /// Publish while the original database-wide write lock excludes competing
    /// commits. This is not an independently manufactured Current witness.
    pub(crate) async fn acknowledge_external_current(&self) -> Result<(), ProductionWriterError> {
        if self.store.current_publisher.is_none() {
            return Ok(());
        }
        let mut transaction = self
            .store
            .observation_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.acknowledge_external_current_transaction(&mut transaction)
            .await?;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.sender_live_check()?;
        Ok(())
    }

    /// Also used by receipt retirement while its original read transaction
    /// remains held through the metadata-only destination acknowledgement.
    pub(crate) async fn acknowledge_external_current_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<(), ProductionWriterError> {
        let Some(publisher) = &self.store.current_publisher else {
            return Ok(());
        };
        self.store
            .commit_gate
            .require_open()
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let attempt = self.store.commit_gate.checkpoint_attempt();
        let writer = self.current_writer_fence(transaction).await?;
        let cut = capture_recovery_anchor(transaction, self.owner_agent_id())
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.sender_live_check()?;
        let diagnostics = std::sync::Arc::new(CheckpointDiagnostics::default());
        let acknowledged = tokio::time::timeout(
            publisher.deadline,
            publisher.acknowledge(cut.clone(), writer, std::sync::Arc::clone(&diagnostics)),
        )
        .await
        .map_err(|_| {
            publication_unknown(
                "outer_timeout",
                &diagnostics,
                CheckpointFailureCause::OuterTimeout,
            )
        })?
        .map_err(|error| {
            let (stage, cause) = match error {
                crate::ObjectiveSenderCheckpointError::Refused => (
                    "publisher_refused",
                    CheckpointFailureCause::PublisherRefused,
                ),
                crate::ObjectiveSenderCheckpointError::Unavailable => (
                    "publisher_unavailable",
                    CheckpointFailureCause::PublisherUnavailable,
                ),
            };
            publication_unknown(stage, &diagnostics, cause)
        })?;
        if acknowledged != cut {
            return Err(publication_unknown(
                "cut_mismatch",
                &diagnostics,
                CheckpointFailureCause::CutMismatch,
            ));
        }
        self.sender_live_check()?;
        attempt.acknowledge();
        Ok(())
    }
}

fn publication_unknown(
    stage: &'static str,
    diagnostics: &CheckpointDiagnostics,
    cause: CheckpointFailureCause,
) -> ProductionWriterError {
    diagnostics.fail(cause);
    ProductionWriterError::Durability(format!(
        "independent original Current acknowledgement is unknown; owner remains fenced; publication_stage={stage} checkpoint_failure={:?}",
        diagnostics.first()
    ))
}
