use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerRetirement;
use codex_hepta_types::Digest32;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReplayCheckpoint {
    pub generation: u64,
    pub digest: Digest32,
}

#[derive(Debug, thiserror::Error)]
pub enum AuthBusRecoveryError {
    #[error("invalid AuthBus recovery request: {0}")]
    Invalid(&'static str),
    #[error("AuthBus external replay checkpoint indicates rollback or drift")]
    RollbackDetected,
    #[error("AuthBus replay checkpoint handshake is already pending")]
    CheckpointPending,
    #[error("AuthBus replay retirement proof is inconsistent with durable state")]
    RetirementConflict,
    #[error("AuthBus replay epoch still has active deliveries")]
    ActiveDeliveries,
    #[error(transparent)]
    Storage(#[from] EvidenceError),
}

impl HeptaEvidenceStore {
    /// Enable rollback-resistant replay handling against an independently
    /// retained witness. The initial witness must bind the exact current
    /// replay/tombstone frontier; an arbitrary digest is never accepted.
    pub async fn initialize_authbus_restore_checkpoint(
        &self,
        checkpoint: ReplayCheckpoint,
    ) -> Result<(), AuthBusRecoveryError> {
        if checkpoint.generation == 0 || checkpoint.digest.is_zero() {
            return Err(AuthBusRecoveryError::Invalid("checkpoint is empty"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        if replay_checkpoint_pending(&mut tx).await? {
            return Err(AuthBusRecoveryError::CheckpointPending);
        }
        let frontier = replay_frontier_digest_tx(&mut tx).await?;
        if frontier != checkpoint.digest {
            return Err(AuthBusRecoveryError::RollbackDetected);
        }
        if let Some(current) = load_checkpoint(&mut tx).await? {
            if current != checkpoint {
                return Err(AuthBusRecoveryError::RollbackDetected);
            }
        } else {
            sqlx::query(
                "INSERT INTO authbus_restore_checkpoint
                 (singleton, generation, checkpoint_digest, updated_at_ms)
                 VALUES (1, ?, ?, ?)",
            )
            .bind(checkpoint.generation.to_be_bytes().as_slice())
            .bind(checkpoint.digest.as_array().as_slice())
            .bind(now_millis()?)
            .execute(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn authbus_replay_frontier_digest(
        &self,
    ) -> Result<Digest32, AuthBusRecoveryError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let digest = replay_frontier_digest_tx(&mut tx).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(digest)
    }

    pub async fn authbus_restore_checkpoint(
        &self,
    ) -> Result<Option<ReplayCheckpoint>, AuthBusRecoveryError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let checkpoint = load_checkpoint(&mut tx).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(checkpoint)
    }

    pub async fn pending_authbus_restore_checkpoint(
        &self,
    ) -> Result<Option<ReplayCheckpoint>, AuthBusRecoveryError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let checkpoint = load_pending_checkpoint(&mut tx).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(checkpoint)
    }

    /// Reconcile a protected external witness on startup. If the witness names
    /// the committed local checkpoint, a locally pending newer frontier is
    /// returned so the host can persist it externally. If the witness already
    /// names that exact pending frontier, the pending transition is committed.
    /// Any other relation is rollback/uncertainty and fails closed.
    pub async fn reconcile_authbus_restore_checkpoint(
        &self,
        external: ReplayCheckpoint,
    ) -> Result<Option<ReplayCheckpoint>, AuthBusRecoveryError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_checkpoint(&mut tx)
            .await?
            .ok_or(AuthBusRecoveryError::RollbackDetected)?;
        let pending = load_pending_checkpoint(&mut tx).await?;
        if external == current {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(pending);
        }
        if pending == Some(external)
            && external.generation == current.generation.checked_add(1).ok_or(
                AuthBusRecoveryError::Invalid("checkpoint generation overflow"),
            )?
        {
            let frontier = replay_frontier_digest_tx(&mut tx).await?;
            if frontier != external.digest {
                return Err(AuthBusRecoveryError::RollbackDetected);
            }
            promote_pending_checkpoint(&mut tx, external).await?;
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(None);
        }
        Err(AuthBusRecoveryError::RollbackDetected)
    }

    /// Confirm that the host durably wrote the exact pending witness. A caller
    /// cannot advance or substitute a checkpoint without matching both the
    /// local predecessor generation and the current replay frontier.
    pub async fn advance_authbus_restore_checkpoint(
        &self,
        expected_generation: u64,
        external: ReplayCheckpoint,
    ) -> Result<(), AuthBusRecoveryError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_checkpoint(&mut tx)
            .await?
            .ok_or(AuthBusRecoveryError::RollbackDetected)?;
        if current.generation != expected_generation
            || external.generation
                != expected_generation
                    .checked_add(1)
                    .ok_or(AuthBusRecoveryError::Invalid(
                        "checkpoint generation overflow",
                    ))?
            || load_pending_checkpoint(&mut tx).await? != Some(external)
        {
            return Err(AuthBusRecoveryError::RollbackDetected);
        }
        if replay_frontier_digest_tx(&mut tx).await? != external.digest {
            return Err(AuthBusRecoveryError::RollbackDetected);
        }
        promote_pending_checkpoint(&mut tx, external).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    /// Retire replay rows only after the authoritative message issuer lifecycle
    /// has produced an opaque retirement proof and the external checkpoint is
    /// current. The tombstone is retained permanently and itself participates
    /// in the next checkpoint root.
    pub async fn retire_authbus_replay_epoch(
        &self,
        retirement: &IssuerRetirement,
        external: ReplayCheckpoint,
    ) -> Result<ReplayCheckpoint, AuthBusRecoveryError> {
        if retirement.purpose() != IssuerPurpose::Message
            || retirement.retirement_digest().is_zero()
        {
            return Err(AuthBusRecoveryError::Invalid(
                "retirement must be for a message issuer epoch",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        if replay_checkpoint_pending(&mut tx).await? {
            return Err(AuthBusRecoveryError::CheckpointPending);
        }
        let current = load_checkpoint(&mut tx)
            .await?
            .ok_or(AuthBusRecoveryError::RollbackDetected)?;
        if current != external || replay_frontier_digest_tx(&mut tx).await? != external.digest {
            return Err(AuthBusRecoveryError::RollbackDetected);
        }
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_outbox
             WHERE issuer_id = ? AND key_epoch = ? AND state IN ('queued', 'leased')",
        )
        .bind(retirement.issuer_id().as_str())
        .bind(retirement.key_epoch().get().to_be_bytes().as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if active != 0 {
            return Err(AuthBusRecoveryError::ActiveDeliveries);
        }

        let existing = sqlx::query(
            "SELECT retirement_digest FROM authbus_retired_epochs
             WHERE issuer_id = ? AND key_epoch = ?",
        )
        .bind(retirement.issuer_id().as_str())
        .bind(retirement.key_epoch().get().to_be_bytes().as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(existing) = existing {
            let digest = digest32(
                existing
                    .try_get("retirement_digest")
                    .map_err(classify_sqlx_error)?,
            )?;
            if digest != retirement.retirement_digest() {
                return Err(AuthBusRecoveryError::RetirementConflict);
            }
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(current);
        }

        sqlx::query(
            "INSERT INTO authbus_retired_epochs
             (issuer_id, key_epoch, retirement_digest, retired_at_ms)
             VALUES (?, ?, ?, ?)",
        )
        .bind(retirement.issuer_id().as_str())
        .bind(retirement.key_epoch().get().to_be_bytes().as_slice())
        .bind(retirement.retirement_digest().as_array().as_slice())
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "DELETE FROM authbus_replay_sequences WHERE issuer_id = ? AND key_epoch = ?",
        )
        .bind(retirement.issuer_id().as_str())
        .bind(retirement.key_epoch().get().to_be_bytes().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        stage_replay_checkpoint_after_mutation(&mut tx).await?;
        let pending = load_pending_checkpoint(&mut tx)
            .await?
            .ok_or(AuthBusRecoveryError::RollbackDetected)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(pending)
    }
}

pub(crate) async fn replay_checkpoint_pending(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<bool, EvidenceError> {
    sqlx::query_scalar(
        "SELECT EXISTS(
             SELECT 1 FROM authbus_restore_checkpoint_pending WHERE singleton = 1
         )",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)
}

pub(crate) async fn replay_epoch_retired(
    tx: &mut Transaction<'_, Sqlite>,
    issuer_id: &str,
    key_epoch: &[u8],
) -> Result<bool, EvidenceError> {
    sqlx::query_scalar(
        "SELECT EXISTS(
             SELECT 1 FROM authbus_retired_epochs
             WHERE issuer_id = ? AND key_epoch = ?
         )",
    )
    .bind(issuer_id)
    .bind(key_epoch)
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)
}

pub(crate) async fn stage_replay_checkpoint_after_mutation(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<(), EvidenceError> {
    let Some(current) = load_checkpoint_storage(tx).await? else {
        return Ok(());
    };
    if replay_checkpoint_pending(tx).await? {
        return Err(EvidenceError::Corrupt(
            "AuthBus replay mutation attempted while checkpoint is pending".into(),
        ));
    }
    let generation = current
        .generation
        .checked_add(1)
        .ok_or_else(|| EvidenceError::Corrupt("AuthBus checkpoint generation overflow".into()))?;
    let digest = replay_frontier_digest_tx(tx).await?;
    sqlx::query(
        "INSERT INTO authbus_restore_checkpoint_pending
         (singleton, generation, checkpoint_digest, created_at_ms)
         VALUES (1, ?, ?, ?)",
    )
    .bind(generation.to_be_bytes().as_slice())
    .bind(digest.as_array().as_slice())
    .bind(now_millis()?)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn promote_pending_checkpoint(
    tx: &mut Transaction<'_, Sqlite>,
    checkpoint: ReplayCheckpoint,
) -> Result<(), AuthBusRecoveryError> {
    sqlx::query(
        "UPDATE authbus_restore_checkpoint
         SET generation = ?, checkpoint_digest = ?, updated_at_ms = ?
         WHERE singleton = 1",
    )
    .bind(checkpoint.generation.to_be_bytes().as_slice())
    .bind(checkpoint.digest.as_array().as_slice())
    .bind(now_millis()?)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    sqlx::query("DELETE FROM authbus_restore_checkpoint_pending WHERE singleton = 1")
        .execute(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?;
    Ok(())
}

async fn load_checkpoint(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Option<ReplayCheckpoint>, AuthBusRecoveryError> {
    load_checkpoint_storage(tx).await.map_err(Into::into)
}

async fn load_checkpoint_storage(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Option<ReplayCheckpoint>, EvidenceError> {
    sqlx::query(
        "SELECT generation, checkpoint_digest
         FROM authbus_restore_checkpoint WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .map(|row| checkpoint_from_row(&row))
    .transpose()
}

async fn load_pending_checkpoint(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Option<ReplayCheckpoint>, AuthBusRecoveryError> {
    sqlx::query(
        "SELECT generation, checkpoint_digest
         FROM authbus_restore_checkpoint_pending WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .map(|row| checkpoint_from_row(&row))
    .transpose()
    .map_err(Into::into)
}

fn checkpoint_from_row(row: &SqliteRow) -> Result<ReplayCheckpoint, EvidenceError> {
    let generation = u64::from_be_bytes(blob::<8>(row, "generation")?);
    if generation == 0 {
        return Err(EvidenceError::Corrupt(
            "AuthBus checkpoint generation is zero".into(),
        ));
    }
    let digest = Digest32::from_array(blob::<32>(row, "checkpoint_digest")?);
    if digest.is_zero() {
        return Err(EvidenceError::Corrupt(
            "AuthBus checkpoint digest is empty".into(),
        ));
    }
    Ok(ReplayCheckpoint { generation, digest })
}

async fn replay_frontier_digest_tx(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Digest32, EvidenceError> {
    let replay_rows = sqlx::query(
        "SELECT issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest
         FROM authbus_replay_sequences
         ORDER BY issuer_id, key_epoch, subject_id, scope_digest",
    )
    .fetch_all(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    let retired_rows = sqlx::query(
        "SELECT issuer_id, key_epoch, retirement_digest
         FROM authbus_retired_epochs ORDER BY issuer_id, key_epoch",
    )
    .fetch_all(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;

    let mut bytes = b"hepta.authbus.replay-frontier.v1\0".to_vec();
    bytes.extend_from_slice(&(replay_rows.len() as u64).to_be_bytes());
    for row in replay_rows {
        push_text(
            &mut bytes,
            row.try_get::<String, _>("issuer_id")
                .map_err(classify_sqlx_error)?
                .as_bytes(),
        );
        bytes.extend_from_slice(&blob::<8>(&row, "key_epoch")?);
        push_text(
            &mut bytes,
            row.try_get::<String, _>("subject_id")
                .map_err(classify_sqlx_error)?
                .as_bytes(),
        );
        bytes.extend_from_slice(&blob::<32>(&row, "scope_digest")?);
        bytes.extend_from_slice(&blob::<8>(&row, "sequence")?);
        bytes.extend_from_slice(&blob::<32>(&row, "envelope_digest")?);
    }
    bytes.extend_from_slice(&(retired_rows.len() as u64).to_be_bytes());
    for row in retired_rows {
        push_text(
            &mut bytes,
            row.try_get::<String, _>("issuer_id")
                .map_err(classify_sqlx_error)?
                .as_bytes(),
        );
        bytes.extend_from_slice(&blob::<8>(&row, "key_epoch")?);
        bytes.extend_from_slice(&blob::<32>(&row, "retirement_digest")?);
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_text(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn blob<const N: usize>(row: &SqliteRow, column: &str) -> Result<[u8; N], EvidenceError> {
    row.try_get::<Vec<u8>, _>(column)
        .map_err(classify_sqlx_error)?
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {column} width")))
}

fn digest32(value: Vec<u8>) -> Result<Digest32, AuthBusRecoveryError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt("invalid AuthBus recovery digest".into()))?;
    Ok(Digest32::from_array(bytes))
}

#[cfg(test)]
#[path = "authbus_recovery_tests.rs"]
mod tests;
