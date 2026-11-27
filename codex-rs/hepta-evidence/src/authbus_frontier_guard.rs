//! Verify the predecessor before any caller can authorize or mutate replay state.

use sqlx::Sqlite;
use sqlx::Transaction;

use super::load_checkpoint_storage;
use super::load_pending_checkpoint;
use super::replay_frontier_digest_tx;
use crate::EvidenceError;

/// This is a pre-mutation check. A later staged checkpoint must never bless
/// rows that had already drifted from their clean or pending witness.
/// Callers independently decide whether an exact pending state is usable.
pub(crate) async fn verify_replay_frontier(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<(), EvidenceError> {
    let current = load_checkpoint_storage(tx).await?;
    let pending = load_pending_checkpoint(tx).await?;
    let Some(current) = current else {
        if pending.is_some() {
            return Err(EvidenceError::Corrupt(
                "AuthBus pending checkpoint has no predecessor".into(),
            ));
        }
        return Ok(());
    };
    if pending.is_some_and(|next| current.generation.checked_add(1) != Some(next.generation)) {
        return Err(EvidenceError::Corrupt(
            "AuthBus pending checkpoint skips its predecessor".into(),
        ));
    }
    if replay_frontier_digest_tx(tx).await? != pending.unwrap_or(current).digest {
        return Err(EvidenceError::Corrupt(
            "AuthBus replay frontier differs from its checkpoint before mutation".into(),
        ));
    }
    Ok(())
}
