use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::AuthBusControlError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

impl HeptaEvidenceStore {
    /// Bind the evidence lineage to an independently retained monotonic checkpoint.
    /// On reopen after backup restore the host must present the same generation/digest;
    /// an older database therefore fails closed against a newer external checkpoint.
    pub async fn initialize_authbus_restore_checkpoint(
        &self,
        generation: u64,
        checkpoint_digest: Digest32,
    ) -> Result<(), AuthBusControlError> {
        if generation == 0 || checkpoint_digest.is_zero() {
            return Err(AuthBusControlError::Invalid("invalid restore checkpoint"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT generation, checkpoint_digest FROM authbus_restore_checkpoint WHERE singleton=1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(row) = row {
            let stored_generation =
                decode_u64(row.try_get("generation").map_err(classify_sqlx_error)?)?;
            let stored_digest = digest(
                row.try_get("checkpoint_digest")
                    .map_err(classify_sqlx_error)?,
            )?;
            if stored_generation != generation || stored_digest != checkpoint_digest {
                return Err(AuthBusControlError::RollbackDetected);
            }
        } else {
            sqlx::query(
                "INSERT INTO authbus_restore_checkpoint(singleton,generation,checkpoint_digest,updated_at_ms)
                 VALUES(1,?,?,?)",
            )
            .bind(generation.to_be_bytes().as_slice())
            .bind(checkpoint_digest.as_array().as_slice())
            .bind(now_millis()?)
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn advance_authbus_restore_checkpoint(
        &self,
        expected_generation: u64,
        next_generation: u64,
        next_digest: Digest32,
    ) -> Result<(), AuthBusControlError> {
        if next_generation <= expected_generation || next_digest.is_zero() {
            return Err(AuthBusControlError::Invalid("checkpoint must advance"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let row =
            sqlx::query("SELECT generation FROM authbus_restore_checkpoint WHERE singleton=1")
                .fetch_optional(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?
                .ok_or(AuthBusControlError::RollbackDetected)?;
        if decode_u64(row.try_get("generation").map_err(classify_sqlx_error)?)?
            != expected_generation
        {
            return Err(AuthBusControlError::RollbackDetected);
        }
        sqlx::query(
            "UPDATE authbus_restore_checkpoint SET generation=?, checkpoint_digest=?, updated_at_ms=?
             WHERE singleton=1",
        )
        .bind(next_generation.to_be_bytes().as_slice())
        .bind(next_digest.as_array().as_slice())
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn verify_authbus_restore_checkpoint(
        &self,
        generation: u64,
        checkpoint_digest: Digest32,
    ) -> Result<(), AuthBusControlError> {
        let row = sqlx::query(
            "SELECT generation, checkpoint_digest FROM authbus_restore_checkpoint WHERE singleton=1",
        )
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusControlError::RollbackDetected)?;
        let stored_generation =
            decode_u64(row.try_get("generation").map_err(classify_sqlx_error)?)?;
        let stored_digest = digest(
            row.try_get("checkpoint_digest")
                .map_err(classify_sqlx_error)?,
        )?;
        if stored_generation != generation || stored_digest != checkpoint_digest {
            return Err(AuthBusControlError::RollbackDetected);
        }
        Ok(())
    }

    /// Retire one issuer epoch only after the independently retained checkpoint
    /// is verified and no active delivery still references the epoch. The durable
    /// tombstone is checked by replay admission so pruning cannot reopen replay.
    pub async fn retire_authbus_replay_epoch(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
        checkpoint_generation: u64,
        checkpoint_digest: Digest32,
    ) -> Result<u64, AuthBusControlError> {
        self.verify_authbus_restore_checkpoint(checkpoint_generation, checkpoint_digest)
            .await?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_outbox
             WHERE issuer_id=? AND key_epoch=? AND state IN ('queued','leased')",
        )
        .bind(issuer_id.as_str())
        .bind(key_epoch.get().to_be_bytes().as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if active != 0 {
            return Err(AuthBusControlError::InvalidTransition);
        }
        sqlx::query(
            "INSERT INTO authbus_retired_epochs
             (issuer_id,key_epoch,checkpoint_generation,checkpoint_digest,retired_at_ms)
             VALUES(?,?,?,?,?)
             ON CONFLICT(issuer_id,key_epoch) DO NOTHING",
        )
        .bind(issuer_id.as_str())
        .bind(key_epoch.get().to_be_bytes().as_slice())
        .bind(checkpoint_generation.to_be_bytes().as_slice())
        .bind(checkpoint_digest.as_array().as_slice())
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let removed =
            sqlx::query("DELETE FROM authbus_replay_sequences WHERE issuer_id=? AND key_epoch=?")
                .bind(issuer_id.as_str())
                .bind(key_epoch.get().to_be_bytes().as_slice())
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?
                .rows_affected();
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(removed)
    }
}

fn decode_u64(bytes: Vec<u8>) -> Result<u64, AuthBusControlError> {
    let bytes: [u8; 8] = bytes
        .try_into()
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus checkpoint integer".into()))?;
    Ok(u64::from_be_bytes(bytes))
}

fn digest(bytes: Vec<u8>) -> Result<Digest32, AuthBusControlError> {
    let bytes: [u8; 32] = bytes
        .try_into()
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus checkpoint digest".into()))?;
    Ok(Digest32::from_array(bytes))
}
