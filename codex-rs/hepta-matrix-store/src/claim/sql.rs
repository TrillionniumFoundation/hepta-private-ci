use std::fmt;

use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::MatrixDurableError;

use super::*;

pub(super) struct ActiveClaim {
    pub(super) stable_txn_id: MatrixTransactionId,
    pub(super) attempt: u64,
    pub(super) lease_epoch: u64,
    pub(super) token_sha256: String,
    pub(super) phase: String,
    pub(super) claimed_at_ms: u64,
    pub(super) lease_until_ms: u64,
}

impl ActiveClaim {
    pub(super) fn identity(&self) -> ClaimIdentity<'_> {
        ClaimIdentity {
            stable_txn_id: &self.stable_txn_id,
            attempt: self.attempt,
            lease_epoch: self.lease_epoch,
            token_sha256: &self.token_sha256,
        }
    }
}

pub(super) async fn active_claim_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<ActiveClaim>, MatrixDurableError> {
    sqlx::query(
        "SELECT stable_txn_id, attempt, lease_epoch, claim_token_sha256,
                phase, claimed_at_ms, lease_until_ms
         FROM matrix_dispatch_active_claims WHERE stable_txn_id = ?",
    )
    .bind(txn_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| {
        Ok(ActiveClaim {
            stable_txn_id: MatrixTransactionId::parse(
                row.try_get::<String, _>("stable_txn_id")
                    .map_err(unavailable)?,
            )
            .map_err(|_| MatrixDurableError::Corrupt)?,
            attempt: to_u64(row.try_get("attempt").map_err(unavailable)?)?,
            lease_epoch: to_u64(row.try_get("lease_epoch").map_err(unavailable)?)?,
            token_sha256: row.try_get("claim_token_sha256").map_err(unavailable)?,
            phase: {
                let phase: String = row.try_get("phase").map_err(unavailable)?;
                if !matches!(phase.as_str(), "claimed" | "authorized" | "dispatching") {
                    return Err(MatrixDurableError::Corrupt);
                }
                phase
            },
            claimed_at_ms: to_u64(row.try_get("claimed_at_ms").map_err(unavailable)?)?,
            lease_until_ms: to_u64(row.try_get("lease_until_ms").map_err(unavailable)?)?,
        })
    })
    .transpose()
}

pub(super) async fn require_active_claim_identity_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    expected: &ClaimIdentity<'_>,
) -> Result<ActiveClaim, MatrixDurableError> {
    let active = active_claim_tx(transaction, expected.stable_txn_id)
        .await?
        .ok_or(MatrixDurableError::Conflict)?;
    if active.attempt != expected.attempt
        || active.lease_epoch != expected.lease_epoch
        || active.token_sha256 != expected.token_sha256
        || active.claimed_at_ms >= active.lease_until_ms
    {
        return Err(MatrixDurableError::Conflict);
    }
    Ok(active)
}

pub(super) async fn require_live_active_claim_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    expected: &ClaimIdentity<'_>,
    recorded_at_ms: u64,
) -> Result<ActiveClaim, MatrixDurableError> {
    let active = require_active_claim_identity_tx(transaction, expected).await?;
    if recorded_at_ms < active.claimed_at_ms || recorded_at_ms >= active.lease_until_ms {
        return Err(MatrixDurableError::Conflict);
    }
    Ok(active)
}

pub(super) async fn authority_witness_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    identity: &ClaimIdentity<'_>,
) -> Result<Option<MatrixOutboxAuthorityWitness>, MatrixDurableError> {
    sqlx::query(
        "SELECT authority_epoch, revocation_revision, grant_id,
                verified_use_witness_sha256, revocation_head_sha256
         FROM matrix_dispatch_authority_witnesses
         WHERE stable_txn_id = ? AND attempt = ?
           AND lease_epoch = ? AND claim_token_sha256 = ?",
    )
    .bind(identity.stable_txn_id.as_str())
    .bind(to_i64(identity.attempt)?)
    .bind(to_i64(identity.lease_epoch)?)
    .bind(identity.token_sha256)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| {
        Ok(MatrixOutboxAuthorityWitness {
            authority_epoch: to_u64(row.try_get("authority_epoch").map_err(unavailable)?)?,
            revocation_revision: to_u64(
                row.try_get("revocation_revision").map_err(unavailable)?,
            )?,
            grant_id: row.try_get("grant_id").map_err(unavailable)?,
            verified_use_witness_sha256: row
                .try_get("verified_use_witness_sha256")
                .map_err(unavailable)?,
            revocation_head_sha256: row
                .try_get("revocation_head_sha256")
                .map_err(unavailable)?,
        })
    })
    .transpose()
}

pub(super) async fn attempt_event_exists_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    identity: &ClaimIdentity<'_>,
    kind: MatrixDispatchAttemptEventKind,
) -> Result<bool, MatrixDurableError> {
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM matrix_dispatch_attempt_events
         WHERE stable_txn_id = ? AND attempt = ? AND lease_epoch = ?
           AND claim_token_sha256 = ? AND event_kind = ?",
    )
    .bind(identity.stable_txn_id.as_str())
    .bind(to_i64(identity.attempt)?)
    .bind(to_i64(identity.lease_epoch)?)
    .bind(identity.token_sha256)
    .bind(kind.as_str())
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(count == 1)
}

pub(super) async fn delete_active_claim_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    identity: &ClaimIdentity<'_>,
) -> Result<(), MatrixDurableError> {
    let deleted = sqlx::query(
        "DELETE FROM matrix_dispatch_active_claims
         WHERE stable_txn_id = ? AND attempt = ? AND lease_epoch = ?
           AND claim_token_sha256 = ?",
    )
    .bind(identity.stable_txn_id.as_str())
    .bind(to_i64(identity.attempt)?)
    .bind(to_i64(identity.lease_epoch)?)
    .bind(identity.token_sha256)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if deleted.rows_affected() != 1 {
        return Err(MatrixDurableError::Conflict);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub(super) async fn append_attempt_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    identity: &ClaimIdentity<'_>,
    event_kind: MatrixDispatchAttemptEventKind,
    failure_class: Option<MatrixAttemptFailureClass>,
    retry_after_ms: Option<u64>,
    event_id: Option<&MatrixEventId>,
    recorded_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    let detail_sha256 = event_detail_digest(
        identity,
        event_kind,
        failure_class,
        retry_after_ms,
        event_id,
        recorded_at_ms,
    );
    sqlx::query(
        "INSERT INTO matrix_dispatch_attempt_events (
            stable_txn_id, attempt, lease_epoch, claim_token_sha256,
            event_kind, failure_class, retry_after_ms, event_id,
            detail_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(identity.stable_txn_id.as_str())
    .bind(to_i64(identity.attempt)?)
    .bind(to_i64(identity.lease_epoch)?)
    .bind(identity.token_sha256)
    .bind(event_kind.as_str())
    .bind(failure_class.map(MatrixAttemptFailureClass::as_str))
    .bind(retry_after_ms.map(to_i64).transpose()?)
    .bind(event_id.map(MatrixEventId::as_str))
    .bind(detail_sha256.as_str())
    .bind(to_i64(recorded_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn event_detail_digest(
    identity: &ClaimIdentity<'_>,
    event_kind: MatrixDispatchAttemptEventKind,
    failure_class: Option<MatrixAttemptFailureClass>,
    retry_after_ms: Option<u64>,
    event_id: Option<&MatrixEventId>,
    recorded_at_ms: u64,
) -> Sha256Digest {
    let mut bytes = b"hepta.matrix.dispatch-attempt-event.v1\0".to_vec();
    push_text(&mut bytes, identity.stable_txn_id.as_str());
    bytes.extend_from_slice(&identity.attempt.to_be_bytes());
    bytes.extend_from_slice(&identity.lease_epoch.to_be_bytes());
    push_text(&mut bytes, identity.token_sha256);
    push_text(&mut bytes, event_kind.as_str());
    push_text(
        &mut bytes,
        failure_class
            .map(MatrixAttemptFailureClass::as_str)
            .unwrap_or(""),
    );
    bytes.extend_from_slice(&retry_after_ms.unwrap_or(0).to_be_bytes());
    push_text(&mut bytes, event_id.map(MatrixEventId::as_str).unwrap_or(""));
    bytes.extend_from_slice(&recorded_at_ms.to_be_bytes());
    Sha256Digest::for_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

pub(super) fn attempt_event_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<MatrixDispatchAttemptEvent, MatrixDurableError> {
    let event_kind = MatrixDispatchAttemptEventKind::parse(
        row.try_get::<String, _>("event_kind")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let failure_class = row
        .try_get::<Option<String>, _>("failure_class")
        .map_err(unavailable)?
        .map(|value| {
            MatrixAttemptFailureClass::parse(&value).ok_or(MatrixDurableError::Corrupt)
        })
        .transpose()?;
    let event_id = row
        .try_get::<Option<String>, _>("event_id")
        .map_err(unavailable)?
        .map(MatrixEventId::parse)
        .transpose()
        .map_err(|_| MatrixDurableError::Corrupt)?;
    let detail_sha256: Option<String> = row.try_get("detail_sha256").map_err(unavailable)?;
    if detail_sha256
        .as_deref()
        .is_some_and(|value| !valid_sha256(value))
    {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(MatrixDispatchAttemptEvent {
        event_seq: to_u64(row.try_get("event_seq").map_err(unavailable)?)?,
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        attempt: to_u64(row.try_get("attempt").map_err(unavailable)?)?,
        lease_epoch: to_u64(row.try_get("lease_epoch").map_err(unavailable)?)?,
        event_kind,
        failure_class,
        retry_after_ms: row
            .try_get::<Option<i64>, _>("retry_after_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        event_id,
        detail_sha256,
        recorded_at_ms: to_u64(row.try_get("recorded_at_ms").map_err(unavailable)?)?,
    })
}

pub(super) fn validate_witness(
    witness: &MatrixOutboxAuthorityWitness,
) -> Result<(), MatrixDurableError> {
    if witness.authority_epoch == 0
        || witness.revocation_revision == 0
        || witness.grant_id.is_empty()
        || witness.grant_id.len() > MAX_GRANT_ID_BYTES
        || !witness
            .grant_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
        || !valid_sha256(&witness.verified_use_witness_sha256)
        || !valid_sha256(&witness.revocation_head_sha256)
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

pub(super) fn to_i64(value: u64) -> Result<i64, MatrixDurableError> {
    i64::try_from(value).map_err(|_| MatrixDurableError::Invalid)
}

pub(super) fn to_u64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

pub(super) fn unavailable(_error: impl fmt::Display) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}
