//! Protect the original entered claim before any synchronous external entry.

use super::*;
use crate::cognitive_store::CheckpointAttempt;
use sqlx::Sqlite;
use sqlx::Transaction;

/// Field order makes cancellation fence the owner before releasing SQLite.
/// This contains no new effect permit, authority or durable state.
pub(super) struct BoundEffectEntry {
    attempt: CheckpointAttempt,
    transaction: Transaction<'static, Sqlite>,
}
impl BoundEffectEntry {
    /// Called only after a known synchronous entry or FinalUse non-entry result.
    /// No publisher remains pending; release SQLite before original writeback.
    pub(super) async fn release(self) -> Result<(), ProductionWriterError> {
        self.attempt.acknowledge();
        self.transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))
    }
}

impl ProductionDurableWriter {
    pub(super) async fn begin_bound_effect_entry(
        &self,
        entered: &DurableDispatchClaim,
        request: &ProductionDispatchRequest,
        dispatch_event_id: &str,
    ) -> Result<Option<BoundEffectEntry>, ProductionWriterError> {
        if !self.store.commit_gate.is_managed() {
            return Ok(None);
        }
        // Cancellation while waiting for SQLite also stops this publisher.
        // Before the lock no Current proposal exists, so this pre-lock fence
        // cannot cause an older cut to be published after a concurrent commit.
        let attempt = self.store.commit_gate.transition_attempt();
        let transaction = self
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let mut entry = BoundEffectEntry {
            attempt,
            transaction,
        };
        operation_claims::require_entered_transaction(&mut entry.transaction, &self.store, entered)
            .await?;
        self.lease
            .require_dispatch_entry_transaction(
                &mut entry.transaction,
                &request.occurrence_key,
                dispatch_event_id,
                &request.operation_digest,
            )
            .await?;
        self.effect_entry_live_check(entered)?;
        self.acknowledge_bound_owner_transaction(&mut entry.transaction)
            .await?;
        self.effect_entry_live_check(entered)?;
        Ok(Some(entry))
    }

    /// This must run again inside the synchronous FinalUse closure: consuming
    /// its nonce may itself take enough time to expire the original claim.
    pub(super) fn effect_entry_live_check(
        &self,
        entered: &DurableDispatchClaim,
    ) -> Result<(), ProductionWriterError> {
        self.store
            .commit_gate
            .require_open()
            .map_err(|_| ProductionWriterError::CheckpointFenced)?;
        self.retirement_live_check()?;
        if now_unix_ms()? >= entered.lease_expires_at_unix_ms {
            return Err(ProductionWriterError::StaleReceipt);
        }
        Ok(())
    }
}
