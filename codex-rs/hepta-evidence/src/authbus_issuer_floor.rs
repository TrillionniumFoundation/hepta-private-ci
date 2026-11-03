//! Durable current-issuer fencing for owner-file based PQ admission.

use codex_hepta_authbus::AuthBusAlgorithm;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAdmissionError;
use crate::HeptaEvidenceStore;
use crate::authbus_crypto_profile::require_algorithm;
use crate::authbus_recovery::replay_checkpoint_pending;
use crate::authbus_recovery::stage_replay_checkpoint_after_mutation;
use crate::authbus_recovery::verify_replay_frontier;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

const MAX_ISSUERS: i64 = 4096;
const MAX_MESSAGE_TTL_MS: u64 = 300_000;

type IssuerFloorFrontierRow = (String, Vec<u8>, Vec<u8>, bool, i64);

impl HeptaEvidenceStore {
    /// Apply a newly read trusted-owner registration before admission/dispatch.
    /// Publish the resulting replay checkpoint before using this registration.
    pub async fn pin_authbus_issuer(
        &self,
        issuer: &IssuerRegistration,
    ) -> Result<(), AuthBusAdmissionError> {
        self.pin_authbus_issuer_and_policy(issuer, None).await
    }

    /// Pin the current text-owner policy and its issuer in the same write
    /// transaction. The policy revision spans issuer names and key generations.
    /// Publish the resulting external checkpoint before using this snapshot.
    pub async fn pin_authbus_issuer_with_owner_policy(
        &self,
        issuer: &IssuerRegistration,
        policy_revision: Generation,
        policy_digest: Digest32,
    ) -> Result<(), AuthBusAdmissionError> {
        if issuer.verifying_key.algorithm() != AuthBusAlgorithm::MlDsa65V2 {
            return Err(AuthBusAdmissionError::CryptoProfileMismatch);
        }
        self.pin_authbus_issuer_and_policy(issuer, Some((policy_revision, policy_digest)))
            .await
    }

    async fn pin_authbus_issuer_and_policy(
        &self,
        issuer: &IssuerRegistration,
        policy: Option<(Generation, Digest32)>,
    ) -> Result<(), AuthBusAdmissionError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        require_algorithm(&mut tx, issuer.verifying_key.algorithm()).await?;
        verify_replay_frontier(&mut tx).await?;
        if issuer.verifying_key.algorithm() == AuthBusAlgorithm::Ed25519V1 {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(());
        }
        let policy_changed = match policy {
            Some((revision, digest)) => {
                crate::authbus_owner_policy::update_required(&mut tx, revision, digest).await?
            }
            None => false,
        };
        let now = now_millis()?;
        // Persist at most one clock-floor update per second of stable identity.
        let floor = now / 1000 * 1000;
        let epoch = issuer.key_epoch.get().to_be_bytes();
        let issuer_changed = if let Some((prior_epoch, prior_key, prior_revoked, prior_floor)) =
            load(&mut tx, issuer).await?
        {
            if epoch.as_slice() < prior_epoch.as_slice()
                || now < prior_floor
                || (epoch.as_slice() == prior_epoch.as_slice()
                    && (prior_key != issuer.verifying_key.as_bytes()
                        || (prior_revoked && !issuer.revoked)))
            {
                return Err(AuthBusAdmissionError::IssuerFloorMismatch);
            }
            epoch.as_slice() != prior_epoch.as_slice()
                || issuer.revoked != prior_revoked
                || floor != prior_floor
        } else {
            let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_issuer_floor")
                .fetch_one(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
            if count >= MAX_ISSUERS {
                return Err(codex_hepta_authbus::Error::CapacityExceeded.into());
            }
            true
        };
        if !issuer_changed && !policy_changed {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(());
        }
        if replay_checkpoint_pending(&mut tx).await? {
            return Err(codex_hepta_authbus::Error::ExternalCheckpointRequired.into());
        }
        if issuer_changed {
            sqlx::query("INSERT INTO authbus_issuer_floor (issuer_id, key_epoch, public_key, revoked, wall_time_floor_ms)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(issuer_id) DO UPDATE SET
            key_epoch = excluded.key_epoch, public_key = excluded.public_key,
            revoked = excluded.revoked, wall_time_floor_ms = excluded.wall_time_floor_ms")
            .bind(issuer.issuer_id.as_str()).bind(epoch.as_slice())
            .bind(issuer.verifying_key.as_bytes()).bind(issuer.revoked).bind(floor)
            .execute(&mut *tx).await.map_err(classify_sqlx_error)?;
        }
        if policy_changed && let Some((revision, digest)) = policy {
            crate::authbus_owner_policy::store(&mut tx, revision, digest).await?;
        }
        stage_replay_checkpoint_after_mutation(&mut tx).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }
}

pub(crate) async fn require_current_issuer(
    tx: &mut Transaction<'_, Sqlite>,
    issuer: &IssuerRegistration,
) -> Result<(), AuthBusAdmissionError> {
    require_algorithm(tx, issuer.verifying_key.algorithm()).await?;
    // All public admission and worker entry points pass here before writes,
    // including exact idempotent retries that never reach advance_replay.
    verify_replay_frontier(tx).await?;
    if issuer.verifying_key.algorithm() == AuthBusAlgorithm::Ed25519V1 {
        return Ok(());
    }
    let Some((epoch, key, revoked, floor)) = load(tx, issuer).await? else {
        return Err(AuthBusAdmissionError::IssuerFloorMismatch);
    };
    if epoch != issuer.key_epoch.get().to_be_bytes()
        || key != issuer.verifying_key.as_bytes()
        || revoked != issuer.revoked
        || now_millis()? < floor
    {
        return Err(AuthBusAdmissionError::IssuerFloorMismatch);
    }
    Ok(())
}

pub(crate) fn require_bounded_deadline(
    issuer: &IssuerRegistration,
    expiry: u64,
    now: u64,
) -> Result<(), AuthBusAdmissionError> {
    if issuer.verifying_key.algorithm() == AuthBusAlgorithm::MlDsa65V2
        && (expiry <= now || expiry.saturating_sub(now) > MAX_MESSAGE_TTL_MS)
    {
        return Err(codex_hepta_authbus::Error::Expired.into());
    }
    Ok(())
}

async fn load(
    tx: &mut Transaction<'_, Sqlite>,
    issuer: &IssuerRegistration,
) -> Result<Option<(Vec<u8>, Vec<u8>, bool, i64)>, AuthBusAdmissionError> {
    Ok(sqlx::query_as("SELECT key_epoch, public_key, revoked, wall_time_floor_ms FROM authbus_issuer_floor WHERE issuer_id = ?")
        .bind(issuer.issuer_id.as_str()).fetch_optional(&mut **tx).await.map_err(classify_sqlx_error)?)
}

pub(crate) async fn append_frontier(
    tx: &mut Transaction<'_, Sqlite>,
    bytes: &mut Vec<u8>,
) -> Result<(), crate::EvidenceError> {
    let rows: Vec<IssuerFloorFrontierRow> = sqlx::query_as(
        "SELECT issuer_id, key_epoch, public_key, revoked, wall_time_floor_ms FROM authbus_issuer_floor ORDER BY issuer_id",
    ).fetch_all(&mut **tx).await.map_err(classify_sqlx_error)?;
    bytes.extend_from_slice(&(rows.len() as u64).to_be_bytes());
    for (id, epoch, key, revoked, floor) in rows {
        for field in [id.as_bytes(), epoch.as_slice(), key.as_slice()] {
            bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
            bytes.extend_from_slice(field);
        }
        bytes.push(u8::from(revoked));
        bytes.extend_from_slice(&floor.to_be_bytes());
    }
    Ok(())
}

#[cfg(test)]
#[path = "authbus_issuer_floor_tests.rs"]
mod tests;
