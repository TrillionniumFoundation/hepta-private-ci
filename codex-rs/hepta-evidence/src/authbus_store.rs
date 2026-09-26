use codex_hepta_authbus::AuthenticatedMessage;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::VerificationReceipt;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::authbus_recovery::replay_checkpoint_pending;
use crate::authbus_recovery::replay_epoch_retired;
use crate::authbus_recovery::stage_replay_checkpoint_after_mutation;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

const MAX_AUTHBUS_REPLAY_KEYS: i64 = 16_384;

#[derive(Debug, thiserror::Error)]
pub enum AuthBusAdmissionError {
    #[error("AuthBus message rejected: {0}")]
    Authentication(#[from] codex_hepta_authbus::Error),
    #[error(transparent)]
    Storage(#[from] EvidenceError),
}

impl HeptaEvidenceStore {
    /// Resolve the claimed issuer from the persistent AuthBus registry, verify
    /// the message and atomically consume its durable replay sequence. The
    /// authenticated value retains the issuer lifecycle read fence through the
    /// SQLite commit, so rotation/revocation cannot race the admission.
    pub async fn admit_authbus_message(
        &self,
        authority: &AuthBusAuthorityHost,
        message: &SignedMessage,
        expected_subject: &StableId,
        expected_scope: Digest32,
        expected_payload: Digest32,
    ) -> Result<VerificationReceipt, AuthBusAdmissionError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        // Read time after the SQLite wait; a queued message cannot outlive its
        // expiry merely because signature verification happened before a lock.
        let now = u64::try_from(now_millis()?)
            .map_err(|_| EvidenceError::Unavailable("clock predates Unix epoch".into()))?;
        if &message.claims.subject_id != expected_subject {
            return Err(codex_hepta_authbus::Error::SubjectMismatch.into());
        }
        let authenticated = authority
            .authenticate_message(message, expected_scope, expected_payload, now)
            .await?;
        advance_replay(&mut transaction, &authenticated).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(authenticated.receipt().clone())
    }
}

// Both direct admission and durable enqueue advance the same owner-held replay
// fence. Enqueue must call this inside its insertion transaction, never admit
// first and try to upgrade the resulting receipt.
pub(crate) async fn advance_replay(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    authenticated: &AuthenticatedMessage,
) -> Result<(), AuthBusAdmissionError> {
    if replay_checkpoint_pending(transaction).await? {
        return Err(codex_hepta_authbus::Error::ExternalCheckpointRequired.into());
    }
    let claims = authenticated.claims();
    let epoch = claims.key_epoch.get().to_be_bytes();
    if replay_epoch_retired(transaction, claims.issuer_id.as_str(), epoch.as_slice()).await? {
        return Err(codex_hepta_authbus::Error::Revoked.into());
    }
    let previous: Option<Vec<u8>> = sqlx::query_scalar(
        "SELECT sequence FROM authbus_replay_sequences
             WHERE issuer_id = ? AND key_epoch = ? AND subject_id = ? AND scope_digest = ?",
    )
    .bind(claims.issuer_id.as_str())
    .bind(epoch.as_slice())
    .bind(claims.subject_id.as_str())
    .bind(claims.scope_digest.as_array().as_slice())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if let Some(previous) = previous {
        let previous: [u8; 8] = previous
            .try_into()
            .map_err(|_| EvidenceError::Corrupt("AuthBus replay sequence width".into()))?;
        if u64::from_be_bytes(previous) >= claims.sequence {
            return Err(codex_hepta_authbus::Error::Replay.into());
        }
    } else {
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_replay_sequences")
            .fetch_one(&mut **transaction)
            .await
            .map_err(classify_sqlx_error)?;
        if count >= MAX_AUTHBUS_REPLAY_KEYS {
            return Err(codex_hepta_authbus::Error::CapacityExceeded.into());
        }
    }
    sqlx::query(
        "INSERT INTO authbus_replay_sequences
             (issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest)
             VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT(issuer_id, key_epoch, subject_id, scope_digest) DO UPDATE
             SET sequence = excluded.sequence, envelope_digest = excluded.envelope_digest",
    )
    .bind(claims.issuer_id.as_str())
    .bind(epoch.as_slice())
    .bind(claims.subject_id.as_str())
    .bind(claims.scope_digest.as_array().as_slice())
    .bind(claims.sequence.to_be_bytes().as_slice())
    .bind(
        authenticated
            .receipt()
            .envelope_digest
            .as_array()
            .as_slice(),
    )
    .execute(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    stage_replay_checkpoint_after_mutation(transaction).await?;
    Ok(())
}

#[cfg(test)]
#[path = "authbus_store_tests.rs"]
mod tests;
