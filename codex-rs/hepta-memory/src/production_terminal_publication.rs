//! Publish only a terminal row just produced by the same sole writer.
use super::*;
use crate::cognitive_store::capture_recovery_anchor;

impl ProductionDurableWriter {
    /// The caller retains the original writer lock and an armed whole-pool
    /// cancellation fence, starting before the terminal commit. This method
    /// creates no writer, Objective ticket, dispatch claim or replay right.
    pub(super) async fn acknowledge_terminal_owner_cut(
        &self,
        expected: &LocalLease,
    ) -> Result<(), ProductionWriterError> {
        if !self.store.commit_gate.is_managed() {
            return Ok(());
        }
        // The terminal commit already happened. Every later error is Unknown;
        // its candidate/head is retained and this generation stays fenced.
        let result = async {
            let mut transaction = self.store.begin_checkpoint_barrier().await
                .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
            let attempt = self.store.commit_gate.checkpoint_attempt();
            let terminal = self.lease.require_terminal_publication_transaction(&mut transaction, expected).await?;
            if terminal.owner_agent_id != *self.owner_agent_id()
                || terminal.lease_id != self.lease_id()
                || terminal.generation != self.generation()
                || terminal.authority_epoch != Some(self.authority.authority_epoch)
                || terminal.owner_epoch != Some(self.authority.owner_epoch)
                || terminal.lease_expires_at_unix_seconds != Some(self.authority.lease_expires_at_unix_seconds)
                || terminal.fencing_token != self.authority.fencing_token_digest()?.as_str()
            {
                return Err(ProductionWriterError::StaleReceipt);
            }
            let fence = ObjectiveSenderWriterFence {
                owner_agent_id: terminal.owner_agent_id,
                lease_id: terminal.lease_id,
                lease_sha256: terminal.lease_sha256,
                generation: terminal.generation,
                authority_epoch: self.authority.authority_epoch,
                owner_epoch: self.authority.owner_epoch,
                authority_grant_digest: self.authority.grant_digest.clone(),
                fencing_token_digest: self.authority.fencing_token_digest()?,
                expires_at_unix_seconds: self.authority.lease_expires_at_unix_seconds,
            };
            let cut = capture_recovery_anchor(&mut transaction, self.owner_agent_id()).await
                .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
            let checkpoint = self.store.bound_owner_publication()
                .ok_or(ProductionWriterError::CheckpointFenced)?;
            self.store.commit_gate.require_open()?;
            self.retirement_live_check()?;
            let acknowledged = tokio::time::timeout(checkpoint.deadline(), checkpoint.acknowledge(&cut, &fence))
                .await.map_err(|_| ProductionWriterError::CheckpointFenced)?
                .map_err(|_| ProductionWriterError::CheckpointFenced)?;
            if acknowledged != cut {
                return Err(ProductionWriterError::CheckpointFenced);
            }
            // No active-lease verification is weakened: this final check only
            // validates the original retained authority after all publication
            // I/O. The exact terminal handle cannot enqueue, claim or enter.
            self.retirement_live_check()?;
            self.store.commit_gate.require_open()?;
            transaction.rollback().await
                .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
            self.retirement_live_check()?;
            self.store.commit_gate.require_open()?;
            attempt.acknowledge();
            Ok(())
        }.await;
        result.map_err(|_| ProductionWriterError::CheckpointFenced)
    }
}
