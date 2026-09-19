use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerRetirement;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

#[derive(Debug, thiserror::Error)]
pub enum AuthBusReplayRetirementError {
    #[error(transparent)]
    Storage(#[from] EvidenceError),
    #[error("AuthBus replay retirement must come from a retired message issuer epoch")]
    InvalidRetirement,
    #[error("AuthBus issuer epoch still has active queued or leased deliveries")]
    ActiveDeliveries,
    #[error("AuthBus issuer epoch retirement conflicts with an existing tombstone")]
    Conflict,
}

impl HeptaEvidenceStore {
    /// Permanently fences one retired message-issuer epoch and releases only its
    /// replay high-water rows. The tombstone is retained indefinitely, so a
    /// stale host registration cannot revive the retired epoch after capacity
    /// is reclaimed. Active queued/leased deliveries must be quarantined first.
    pub async fn retire_authbus_issuer_epoch(
        &self,
        retirement: &IssuerRetirement,
    ) -> Result<(), AuthBusReplayRetirementError> {
        if retirement.purpose() != IssuerPurpose::Message {
            return Err(AuthBusReplayRetirementError::InvalidRetirement);
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let epoch = retirement.key_epoch().get().to_be_bytes();
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_outbox
             WHERE issuer_id = ? AND key_epoch = ? AND state IN ('queued', 'leased')",
        )
        .bind(retirement.issuer_id().as_str())
        .bind(epoch.as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if active != 0 {
            return Err(AuthBusReplayRetirementError::ActiveDeliveries);
        }
        let previous: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT retirement_digest FROM authbus_retired_epochs
             WHERE issuer_id = ? AND key_epoch = ?",
        )
        .bind(retirement.issuer_id().as_str())
        .bind(epoch.as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(previous) = previous {
            if previous.as_slice() != retirement.retirement_digest().as_array().as_slice() {
                return Err(AuthBusReplayRetirementError::Conflict);
            }
        } else {
            sqlx::query(
                "INSERT INTO authbus_retired_epochs
                 (issuer_id, key_epoch, retirement_digest) VALUES (?, ?, ?)",
            )
            .bind(retirement.issuer_id().as_str())
            .bind(epoch.as_slice())
            .bind(retirement.retirement_digest().as_array().as_slice())
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        sqlx::query(
            "DELETE FROM authbus_replay_sequences WHERE issuer_id = ? AND key_epoch = ?",
        )
        .bind(retirement.issuer_id().as_str())
        .bind(epoch.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }
}
