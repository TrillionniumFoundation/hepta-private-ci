//! Ordinary FinalUse boundaries use the original protected SQLite Current cut.

use super::*;
use crate::ObjectiveSenderWriterFence;
use crate::cognitive_store::capture_recovery_anchor;
use sqlx::Sqlite;
use sqlx::Transaction;

impl ProductionDurableWriter {
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
        let acknowledged = tokio::time::timeout(
            publisher.deadline,
            publisher.acknowledge(cut.clone(), writer),
        )
        .await
        .map_err(|_| publication_unknown())?
        .map_err(|_| publication_unknown())?;
        if acknowledged != cut {
            return Err(publication_unknown());
        }
        self.sender_live_check()?;
        attempt.acknowledge();
        Ok(())
    }
}

fn publication_unknown() -> ProductionWriterError {
    ProductionWriterError::Durability(
        "independent original Current acknowledgement is unknown; owner remains fenced".to_string(),
    )
}
