//! Native account-checkpoint observation for an owner-normalized empty sync.
//! This makes no room-fence, server-provenance, or admission-authority claim.

use codex_hepta_contracts::AgentId;

use super::sync_v2::checkpoint_tx;
use super::sync_v2::verify_checkpoint;
use super::sync_v2_tombstone::has_commit_capacity_tx;
use super::sync_v2_tombstone::valid_sync_token;
use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::MatrixSyncCheckpoint;

/// An unchanged account token observed after the caller normalizes a full sync.
/// No operation identity is accepted or reserved by this observation.
#[derive(Clone)]
pub struct MatrixSyncUnchangedRequestV1 {
    pub owner_agent_id: AgentId,
    pub checkpoint_revision: u64,
    pub checkpoint_generation: u64,
    pub expected_next_batch: String,
    pub observed_next_batch: String,
}

/// A fresh local observation, not a durable V2 decision or replay receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MatrixSyncUnchangedResultV1 {
    Verified { checkpoint: MatrixSyncCheckpoint },
    CapacityExhausted,
}

impl MatrixDurableStore {
    /// Verify the current account checkpoint and ordinary empty-commit capacity.
    ///
    /// Success leaves checkpoint timestamps, journals and operation-id lookup
    /// unchanged. It cannot bootstrap a missing checkpoint, validate rooms or
    /// prove the caller's response completeness. The caller retains those duties.
    #[doc(hidden)]
    pub async fn verify_unchanged_sync_v1(
        &self,
        request: &MatrixSyncUnchangedRequestV1,
    ) -> Result<MatrixSyncUnchangedResultV1, MatrixDurableError> {
        if request.checkpoint_revision == 0
            || request.checkpoint_generation == 0
            || !valid_sync_token(&request.expected_next_batch)
            || !valid_sync_token(&request.observed_next_batch)
            || request.expected_next_batch != request.observed_next_batch
        {
            return Err(MatrixDurableError::Invalid);
        }
        if &request.owner_agent_id != self.owner_agent_id() {
            return Err(MatrixDurableError::AccessDenied);
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let checkpoint = checkpoint_tx(&mut transaction)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        verify_checkpoint(
            Some(&checkpoint),
            self.owner_agent_id(),
            request.checkpoint_revision,
            request.checkpoint_generation,
            Some(&request.expected_next_batch),
        )?;
        // Reuse every V2 ceiling/reserve check, including its requirement for
        // one ordinary decision slot, without consuming that slot.
        let capacity = has_commit_capacity_tx(&mut transaction, &[]).await?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        Ok(if capacity {
            MatrixSyncUnchangedResultV1::Verified { checkpoint }
        } else {
            MatrixSyncUnchangedResultV1::CapacityExhausted
        })
    }
}
