//! Whole-owner publication for irreversible metadata retirement.

use super::*;
use crate::cognitive_store::capture_recovery_anchor;
use sqlx::Sqlite;
use sqlx::Transaction;

impl ProductionDurableWriter {
    /// Runs under the original lock-only BEGIN IMMEDIATE transaction, so publication
    /// and the following synchronous metadata retirement refer to one cut.
    pub(super) async fn acknowledge_bound_owner_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<(), ProductionWriterError> {
        let lease = self.lease.require_current_transaction(transaction).await?;
        if !self.store.commit_gate.is_managed() {
            return Ok(());
        }
        let attempt = self.store.commit_gate.checkpoint_attempt();
        let checkpoint = self.store.bound_owner_publication().ok_or_else(|| {
            ProductionWriterError::Durability(
                "managed owner has no bound publication capability".to_string(),
            )
        })?;
        let fence = ObjectiveSenderWriterFence {
            owner_agent_id: self.owner_agent_id().clone(),
            lease_id: self.lease_id().to_string(),
            lease_sha256: lease.lease_sha256,
            generation: self.generation(),
            authority_epoch: self.authority.authority_epoch,
            owner_epoch: self.authority.owner_epoch,
            authority_grant_digest: self.authority.grant_digest.clone(),
            fencing_token_digest: self.authority.fencing_token_digest()?,
            expires_at_unix_seconds: self.authority.lease_expires_at_unix_seconds,
        };
        let cut = capture_recovery_anchor(transaction, self.owner_agent_id())
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.retirement_live_check()?;
        let acknowledged =
            tokio::time::timeout(checkpoint.deadline(), checkpoint.acknowledge(&cut, &fence))
                .await
                .map_err(|_| ProductionWriterError::CheckpointFenced)?
                .map_err(|_| ProductionWriterError::CheckpointFenced)?;
        if acknowledged != cut {
            return Err(ProductionWriterError::CheckpointFenced);
        }
        self.retirement_live_check()?;
        attempt.acknowledge();
        Ok(())
    }

    pub(super) fn retirement_live_check(&self) -> Result<(), ProductionWriterError> {
        self.authority
            .validate_for_agent(self.store.owner_agent_id())?;
        self.live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify(&self.authority, self.store.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)
    }
}
