use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::ReplayCheckpoint;
use codex_hepta_authbus::TrustedTime;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use sqlx::Row;

use crate::AuthBusAuthorityError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

const MAX_TRUSTED_TIME_UNCERTAINTY_MS: u64 = 5_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusTrustRevision {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub revoked: bool,
    pub revision: u64,
    pub recorded_at_ms: u64,
}

impl HeptaEvidenceStore {
    /// Append an immutable issuer/key revision. Exact retries are idempotent.
    /// A key epoch cannot silently change its public key.
    pub async fn publish_authbus_trust(
        &self,
        issuer: &IssuerRegistration,
        revision: u64,
        time: &TrustedTime,
    ) -> Result<AuthBusTrustRevision, AuthBusAuthorityError> {
        time.validate(MAX_TRUSTED_TIME_UNCERTAINTY_MS)?;
        if revision == 0 {
            return Err(AuthBusAuthorityError::Invalid("trust revision must be non-zero"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT public_key, revoked, revision, recorded_at_ms
             FROM authbus_trust_epochs
             WHERE issuer_id = ? AND key_epoch = ?
             ORDER BY revision DESC LIMIT 1",
        )
        .bind(issuer.issuer_id.as_str())
        .bind(issuer.key_epoch.get().to_be_bytes().as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(row) = row {
            let current_revision = positive_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?;
            let key: Vec<u8> = row.try_get("public_key").map_err(classify_sqlx_error)?;
            let same_key = key.as_slice() == issuer.verifying_key.to_bytes().as_slice();
            let revoked: bool = row.try_get("revoked").map_err(classify_sqlx_error)?;
            if revision == current_revision {
                if same_key && revoked == issuer.revoked {
                    let recorded_at_ms =
                        positive_u64(row.try_get("recorded_at_ms").map_err(classify_sqlx_error)?)?;
                    tx.commit().await.map_err(classify_sqlx_error)?;
                    return Ok(AuthBusTrustRevision {
                        issuer_id: issuer.issuer_id.clone(),
                        key_epoch: issuer.key_epoch,
                        revoked,
                        revision,
                        recorded_at_ms,
                    });
                }
                return Err(AuthBusAuthorityError::Conflict);
            }
            if !same_key
                || revision
                    != current_revision
                        .checked_add(1)
                        .ok_or(AuthBusAuthorityError::StaleRevision)?
                || (revoked && !issuer.revoked)
            {
                return Err(AuthBusAuthorityError::StaleRevision);
            }
        } else if revision != 1 {
            return Err(AuthBusAuthorityError::StaleRevision);
        }

        sqlx::query(
            "INSERT INTO authbus_trust_epochs
             (issuer_id, key_epoch, public_key, revoked, revision, recorded_at_ms)
             VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(issuer.issuer_id.as_str())
        .bind(issuer.key_epoch.get().to_be_bytes().as_slice())
        .bind(issuer.verifying_key.to_bytes().as_slice())
        .bind(issuer.revoked)
        .bind(to_i64(revision)?)
        .bind(to_i64(time.now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(AuthBusTrustRevision {
            issuer_id: issuer.issuer_id.clone(),
            key_epoch: issuer.key_epoch,
            revoked: issuer.revoked,
            revision,
            recorded_at_ms: time.now_ms,
        })
    }

    pub async fn resolve_authbus_trust(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<(IssuerRegistration, AuthBusTrustRevision), AuthBusAuthorityError> {
        let row = sqlx::query(
            "SELECT public_key, revoked, revision, recorded_at_ms
             FROM authbus_trust_epochs
             WHERE issuer_id = ? AND key_epoch = ?
             ORDER BY revision DESC LIMIT 1",
        )
        .bind(issuer_id.as_str())
        .bind(key_epoch.get().to_be_bytes().as_slice())
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(AuthBusAuthorityError::MissingTrust)?;
        let key: Vec<u8> = row.try_get("public_key").map_err(classify_sqlx_error)?;
        let key: [u8; 32] = key
            .try_into()
            .map_err(|_| EvidenceError::Corrupt("invalid AuthBus trust key width".into()))?;
        let revoked: bool = row.try_get("revoked").map_err(classify_sqlx_error)?;
        let revision = positive_u64(row.try_get("revision").map_err(classify_sqlx_error)?)?;
        let recorded_at_ms =
            positive_u64(row.try_get("recorded_at_ms").map_err(classify_sqlx_error)?)?;
        let registration = IssuerRegistration {
            issuer_id: issuer_id.clone(),
            key_epoch,
            verifying_key: VerifyingKey::from_bytes(&key)
                .map_err(|_| EvidenceError::Corrupt("invalid AuthBus stored public key".into()))?,
            revoked,
        };
        Ok((
            registration,
            AuthBusTrustRevision {
                issuer_id: issuer_id.clone(),
                key_epoch,
                revoked,
                revision,
                recorded_at_ms,
            },
        ))
    }

    /// Compute a deterministic root over the complete durable replay frontier.
    /// The returned digest is intended to be retained by an independent store.
    pub async fn authbus_replay_root(&self) -> Result<Digest32, AuthBusAuthorityError> {
        replay_root_from_executor(&self.pool).await
    }

    /// Compare the locally reconstructed replay root with a checkpoint supplied
    /// by an independent retention boundary. Restoring an older SQLite file
    /// therefore fails closed when the external checkpoint is current.
    pub async fn verify_authbus_replay_checkpoint(
        &self,
        checkpoint: &ReplayCheckpoint,
    ) -> Result<(), AuthBusAuthorityError> {
        checkpoint.validate()?;
        let local = self.authbus_replay_root().await?;
        if local != checkpoint.replay_root {
            return Err(AuthBusAuthorityError::Conflict);
        }
        let local_row = sqlx::query(
            "SELECT checkpoint_id, generation, replay_root, observed_at_ms
             FROM authbus_replay_checkpoint_state WHERE singleton = 1",
        )
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(row) = local_row {
            let generation = positive_u64(row.try_get("generation").map_err(classify_sqlx_error)?)?;
            if generation > checkpoint.generation {
                return Err(AuthBusAuthorityError::StaleRevision);
            }
        }
        Ok(())
    }

    /// Record the latest externally retained checkpoint acknowledgement. This
    /// local row is diagnostic only; rollback resistance comes from the caller
    /// retaining the supplied checkpoint outside this SQLite lineage.
    pub async fn record_authbus_replay_checkpoint(
        &self,
        checkpoint: &ReplayCheckpoint,
    ) -> Result<(), AuthBusAuthorityError> {
        self.verify_authbus_replay_checkpoint(checkpoint).await?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let previous: Option<i64> = sqlx::query_scalar(
            "SELECT generation FROM authbus_replay_checkpoint_state WHERE singleton = 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if previous
            .map(positive_u64)
            .transpose()?
            .is_some_and(|generation| generation >= checkpoint.generation)
        {
            return Err(AuthBusAuthorityError::StaleRevision);
        }
        sqlx::query(
            "INSERT INTO authbus_replay_checkpoint_state
             (singleton, checkpoint_id, generation, replay_root, observed_at_ms)
             VALUES (1, ?, ?, ?, ?)
             ON CONFLICT(singleton) DO UPDATE SET
               checkpoint_id = excluded.checkpoint_id,
               generation = excluded.generation,
               replay_root = excluded.replay_root,
               observed_at_ms = excluded.observed_at_ms",
        )
        .bind(checkpoint.checkpoint_id.as_str())
        .bind(to_i64(checkpoint.generation)?)
        .bind(checkpoint.replay_root.as_array().as_slice())
        .bind(to_i64(checkpoint.observed_at_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    /// Retire one replay identity only after its issuer epoch is revoked, no
    /// active delivery references it, and an external checkpoint proves the
    /// exact pre-retirement frontier. The new root must be retained externally
    /// before admitting new identities.
    pub async fn retire_authbus_replay_key(
        &self,
        issuer: &IssuerRegistration,
        subject_id: &StableId,
        scope_digest: Digest32,
        checkpoint: &ReplayCheckpoint,
    ) -> Result<Digest32, AuthBusAuthorityError> {
        if !issuer.revoked {
            return Err(AuthBusAuthorityError::Invalid("issuer epoch must be revoked"));
        }
        self.verify_authbus_replay_checkpoint(checkpoint).await?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let active: bool = sqlx::query_scalar(
            "SELECT EXISTS(
                SELECT 1 FROM authbus_outbox
                WHERE issuer_id = ? AND key_epoch = ? AND subject_id = ?
                  AND scope_digest = ? AND state IN ('queued', 'leased')
             )",
        )
        .bind(issuer.issuer_id.as_str())
        .bind(issuer.key_epoch.get().to_be_bytes().as_slice())
        .bind(subject_id.as_str())
        .bind(scope_digest.as_array().as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if active {
            return Err(AuthBusAuthorityError::InvalidReservationState);
        }
        sqlx::query(
            "DELETE FROM authbus_replay_sequences
             WHERE issuer_id = ? AND key_epoch = ? AND subject_id = ? AND scope_digest = ?",
        )
        .bind(issuer.issuer_id.as_str())
        .bind(issuer.key_epoch.get().to_be_bytes().as_slice())
        .bind(subject_id.as_str())
        .bind(scope_digest.as_array().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        self.authbus_replay_root().await
    }
}

async fn replay_root_from_executor<'e, E>(executor: E) -> Result<Digest32, AuthBusAuthorityError>
where
    E: sqlx::Executor<'e, Database = sqlx::Sqlite>,
{
    let rows = sqlx::query(
        "SELECT issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest
         FROM authbus_replay_sequences
         ORDER BY issuer_id, key_epoch, subject_id, scope_digest",
    )
    .fetch_all(executor)
    .await
    .map_err(classify_sqlx_error)?;
    let mut bytes = b"hepta.authbus.replay-root.v1\0".to_vec();
    for row in rows {
        push_text(
            &mut bytes,
            &row.try_get::<String, _>("issuer_id")
                .map_err(classify_sqlx_error)?,
        );
        push_blob(
            &mut bytes,
            &row.try_get::<Vec<u8>, _>("key_epoch")
                .map_err(classify_sqlx_error)?,
        );
        push_text(
            &mut bytes,
            &row.try_get::<String, _>("subject_id")
                .map_err(classify_sqlx_error)?,
        );
        push_blob(
            &mut bytes,
            &row.try_get::<Vec<u8>, _>("scope_digest")
                .map_err(classify_sqlx_error)?,
        );
        push_blob(
            &mut bytes,
            &row.try_get::<Vec<u8>, _>("sequence")
                .map_err(classify_sqlx_error)?,
        );
        push_blob(
            &mut bytes,
            &row.try_get::<Vec<u8>, _>("envelope_digest")
                .map_err(classify_sqlx_error)?,
        );
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_blob(bytes, value.as_bytes());
}

fn push_blob(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn to_i64(value: u64) -> Result<i64, AuthBusAuthorityError> {
    i64::try_from(value).map_err(|_| AuthBusAuthorityError::Invalid("value exceeds SQLite i64"))
}

fn positive_u64(value: i64) -> Result<u64, AuthBusAuthorityError> {
    if value <= 0 {
        return Err(EvidenceError::Corrupt("invalid non-positive AuthBus revision/time".into()).into());
    }
    Ok(value as u64)
}
