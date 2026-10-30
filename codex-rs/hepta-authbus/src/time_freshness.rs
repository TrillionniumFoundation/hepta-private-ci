//! PQ authentication does not make an old clock sample fresh. The owner issues
//! bounded, one-use challenges and checks its independent wall clock on use.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAlgorithm;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::TrustedTimeSample;
use crate::authority_store::begin;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;

const ROUND_TRIP_MS: u64 = 30_000;
const CLOCK_SKEW_MS: u64 = 5_000;
const MAX_CHALLENGES: i64 = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedTimeChallenge {
    pub nonce: Digest32,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
}

impl AuthBusAuthorityStore {
    pub async fn trusted_time_challenge(
        &self,
    ) -> Result<Option<TrustedTimeChallenge>, AuthBusAuthorityError> {
        if self.algorithm() == AuthBusAlgorithm::Ed25519V1 {
            return Ok(None);
        }
        let now = wall_clock_ms()?;
        let challenge = TrustedTimeChallenge {
            nonce: Digest32::from_array(rand::random()),
            issued_at_ms: now,
            expires_at_ms: now
                .checked_add(ROUND_TRIP_MS)
                .ok_or(AuthBusAuthorityError::CapacityExceeded)?,
        };
        if challenge.nonce.is_zero() {
            return Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness);
        }
        let mut tx = begin(&self.pool).await?;
        sqlx::query("DELETE FROM authbus_time_challenge WHERE expires_at_ms <= ?")
            .bind(u64_bytes(now).as_slice())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_time_challenge")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if count >= MAX_CHALLENGES {
            return Err(AuthBusAuthorityError::CapacityExceeded);
        }
        sqlx::query("INSERT INTO authbus_time_challenge(nonce, issued_at_ms, expires_at_ms) VALUES (?, ?, ?)")
            .bind(challenge.nonce.as_array().as_slice())
            .bind(u64_bytes(challenge.issued_at_ms).as_slice())
            .bind(u64_bytes(challenge.expires_at_ms).as_slice())
            .execute(&mut *tx).await.map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(Some(challenge))
    }
}

pub(crate) async fn consume_challenge(
    tx: &mut Transaction<'_, Sqlite>,
    challenge: &TrustedTimeChallenge,
    sample: &mut TrustedTimeSample,
) -> Result<(), AuthBusAuthorityError> {
    let now = wall_clock_ms()?;
    if challenge.nonce.is_zero()
        || challenge.expires_at_ms.checked_sub(challenge.issued_at_ms) != Some(ROUND_TRIP_MS)
        || now < challenge.issued_at_ms
        || now >= challenge.expires_at_ms
        || now.abs_diff(sample.wall_time_ms) > CLOCK_SKEW_MS
    {
        return Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness);
    }
    let deleted = sqlx::query(
        "DELETE FROM authbus_time_challenge WHERE nonce = ? AND issued_at_ms = ? AND expires_at_ms = ?",
    )
    .bind(challenge.nonce.as_array().as_slice())
    .bind(u64_bytes(challenge.issued_at_ms).as_slice())
    .bind(u64_bytes(challenge.expires_at_ms).as_slice())
    .execute(&mut **tx).await.map_err(storage)?;
    if deleted.rows_affected() != 1 {
        return Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness);
    }
    sample.valid_until_ms = Some(
        challenge
            .expires_at_ms
            .min(sample.wall_time_ms.saturating_add(CLOCK_SKEW_MS)),
    );
    Ok(())
}

pub(crate) async fn require_fresh_sample(
    tx: &mut Transaction<'_, Sqlite>,
    sample: &TrustedTimeSample,
) -> Result<(), AuthBusAuthorityError> {
    let version: i64 =
        sqlx::query_scalar("SELECT auth_version FROM authbus_crypto_profile WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(storage)?;
    match (version, sample.valid_until_ms) {
        (1, None) => Ok(()),
        (2, Some(deadline)) => {
            let now = wall_clock_ms()?;
            if now >= deadline || now.abs_diff(sample.wall_time_ms) > CLOCK_SKEW_MS {
                return Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness);
            }
            Ok(())
        }
        _ => Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness),
    }
}

pub(crate) fn wall_clock_ms() -> Result<u64, AuthBusAuthorityError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AuthBusAuthorityError::InvalidTrustedTimeFreshness)?
        .as_millis()
        .try_into()
        .map_err(|_| AuthBusAuthorityError::InvalidTrustedTimeFreshness)
}

#[cfg(test)]
#[path = "time_freshness_tests.rs"]
mod tests;
