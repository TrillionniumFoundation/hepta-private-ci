use codex_hepta_types::Digest32;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::ReservationState;
use crate::authority_store::begin;
use crate::authority_store::next_revision;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;
use crate::quota_store::load_reservation;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthorityCheckpoint {
    pub generation: u64,
    pub digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(i64)]
pub(crate) enum FrontierVersion {
    LegacyV4 = 1,
    DispatchV5 = 2,
}

impl AuthBusAuthorityStore {
    pub async fn authority_frontier_digest(&self) -> Result<Digest32, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let digest = authority_frontier_digest_tx(&mut tx).await?;
        tx.commit().await.map_err(storage)?;
        Ok(digest)
    }

    pub async fn authority_checkpoint(
        &self,
    ) -> Result<Option<AuthorityCheckpoint>, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let checkpoint = load_checkpoint(&mut tx).await?;
        tx.commit().await.map_err(storage)?;
        Ok(checkpoint)
    }

    pub async fn initialize_authority_checkpoint(
        &self,
        checkpoint: AuthorityCheckpoint,
    ) -> Result<(), AuthBusAuthorityError> {
        if checkpoint.generation == 0 || checkpoint.digest.is_zero() {
            return Err(AuthBusAuthorityError::InvalidInput(
                "authority checkpoint is empty",
            ));
        }
        let mut tx = begin(&self.pool).await?;
        if authority_frontier_digest_tx(&mut tx).await? != checkpoint.digest {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        match load_checkpoint(&mut tx).await? {
            Some(current) if current != checkpoint => {
                return Err(AuthBusAuthorityError::RollbackDetected);
            }
            Some(_) => {}
            None => {
                sqlx::query(
                    "INSERT INTO authbus_authority_checkpoint
                     (singleton, generation, checkpoint_digest, frontier_version) VALUES (1, ?, ?, 2)",
                )
                .bind(u64_bytes(checkpoint.generation).as_slice())
                .bind(checkpoint.digest.as_array().as_slice())
                .execute(&mut *tx)
                .await
                .map_err(storage)?;
            }
        }
        set_dirty(&mut tx, false).await?;
        tx.commit().await.map_err(storage)
    }

    /// Compare the independently retained witness with the local committed
    /// checkpoint. A dirty local frontier means a SQLite mutation committed
    /// after the last external publication. The host may publish exactly the
    /// returned successor. If the external witness already names that successor,
    /// this method promotes it locally after recomputing the complete frontier.
    pub async fn reconcile_authority_checkpoint(
        &self,
        external: AuthorityCheckpoint,
    ) -> Result<Option<AuthorityCheckpoint>, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let current = load_checkpoint(&mut tx)
            .await?
            .ok_or(AuthBusAuthorityError::RollbackDetected)?;
        let dirty = is_dirty(&mut tx).await?;
        let version: i64 = sqlx::query_scalar(
            "SELECT frontier_version FROM authbus_authority_checkpoint WHERE singleton = 1",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let version = match version {
            1 => FrontierVersion::LegacyV4,
            2 => FrontierVersion::DispatchV5,
            _ => {
                return Err(AuthBusAuthorityError::CorruptState(
                    "invalid frontier version",
                ));
            }
        };
        if external == current {
            if !dirty {
                if authority_frontier_digest_for_version(&mut tx, version).await? != current.digest
                {
                    return Err(AuthBusAuthorityError::RollbackDetected);
                }
                tx.commit().await.map_err(storage)?;
                return Ok(None);
            }
            let next = AuthorityCheckpoint {
                generation: current
                    .generation
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::CapacityExceeded)?,
                digest: authority_frontier_digest_tx(&mut tx).await?,
            };
            tx.commit().await.map_err(storage)?;
            return Ok(Some(next));
        }
        if dirty
            && external.generation
                == current
                    .generation
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::CapacityExceeded)?
            && external.digest == authority_frontier_digest_tx(&mut tx).await?
        {
            persist_checkpoint(&mut tx, external, FrontierVersion::DispatchV5).await?;
            set_dirty(&mut tx, false).await?;
            tx.commit().await.map_err(storage)?;
            return Ok(None);
        }
        if dirty
            && version == FrontierVersion::LegacyV4
            && current.generation.checked_add(1) == Some(external.generation)
            && authority_frontier_digest_for_version(&mut tx, FrontierVersion::LegacyV4).await?
                == external.digest
        {
            let successor = AuthorityCheckpoint {
                generation: external
                    .generation
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::CapacityExceeded)?,
                digest: authority_frontier_digest_tx(&mut tx).await?,
            };
            // The old publication is real. Retain its dialect until the new
            // digest has separately crossed the external publication boundary.
            persist_checkpoint(&mut tx, external, FrontierVersion::LegacyV4).await?;
            tx.commit().await.map_err(storage)?;
            return Ok(Some(successor));
        }
        Err(AuthBusAuthorityError::RollbackDetected)
    }

    pub async fn advance_authority_checkpoint(
        &self,
        expected_generation: u64,
        external: AuthorityCheckpoint,
    ) -> Result<(), AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let current = load_checkpoint(&mut tx)
            .await?
            .ok_or(AuthBusAuthorityError::RollbackDetected)?;
        if !is_dirty(&mut tx).await?
            || current.generation != expected_generation
            || external.generation
                != expected_generation
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::CapacityExceeded)?
            || external.digest != authority_frontier_digest_tx(&mut tx).await?
        {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        persist_checkpoint(&mut tx, external, FrontierVersion::DispatchV5).await?;
        set_dirty(&mut tx, false).await?;
        tx.commit().await.map_err(storage)
    }

    #[cfg(test)]
    pub async fn recovery_required(&self) -> Result<bool, AuthBusAuthorityError> {
        let value: i64 = sqlx::query_scalar(
            "SELECT recovery_required FROM authbus_recovery_state WHERE singleton = 1",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(value != 0)
    }

    /// Classify pre-crash dispatch attempts as indeterminate before new quota
    /// issuance. Held reservations remain safe and indeterminate reservations
    /// retain their quota until authenticated terminal evidence arrives.
    pub async fn reconcile_after_restart(&self, limit: u32) -> Result<bool, AuthBusAuthorityError> {
        if limit == 0 || limit > 1024 {
            return Err(AuthBusAuthorityError::InvalidInput(
                "recovery batch must be in 1..=1024",
            ));
        }
        let mut tx = begin(&self.pool).await?;
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT reservation_id FROM authbus_quota_reservation
             WHERE state = 'dispatch_attempted'
             ORDER BY reservation_id LIMIT ?",
        )
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        for raw in ids {
            let id = crate::authority_store::stable_id(raw)?;
            let mut reservation = load_reservation(&mut tx, &id).await?;
            if reservation.state != ReservationState::DispatchAttempted {
                continue;
            }
            reservation.state = ReservationState::Indeterminate;
            reservation.revision = next_revision(reservation.revision)?;
            sqlx::query(
                "UPDATE authbus_quota_reservation
                 SET state = 'indeterminate', revision = ? WHERE reservation_id = ?",
            )
            .bind(u64_bytes(reservation.revision).as_slice())
            .bind(reservation.reservation_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        }
        let remaining: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservation
             WHERE state = 'dispatch_attempted'",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if remaining == 0 {
            sqlx::query(
                "UPDATE authbus_recovery_state SET recovery_required = 0 WHERE singleton = 1",
            )
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        }
        tx.commit().await.map_err(storage)?;
        Ok(remaining == 0)
    }
}

async fn load_checkpoint(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Option<AuthorityCheckpoint>, AuthBusAuthorityError> {
    let row: Option<(Vec<u8>, Vec<u8>)> = sqlx::query_as(
        "SELECT generation, checkpoint_digest
         FROM authbus_authority_checkpoint WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    row.map(|(generation, digest)| {
        let generation: [u8; 8] = generation
            .try_into()
            .map_err(|_| AuthBusAuthorityError::CorruptState("invalid checkpoint generation"))?;
        let digest: [u8; 32] = digest
            .try_into()
            .map_err(|_| AuthBusAuthorityError::CorruptState("invalid checkpoint digest"))?;
        let checkpoint = AuthorityCheckpoint {
            generation: u64::from_be_bytes(generation),
            digest: Digest32::from_array(digest),
        };
        if checkpoint.generation == 0 || checkpoint.digest.is_zero() {
            return Err(AuthBusAuthorityError::CorruptState(
                "empty authority checkpoint",
            ));
        }
        Ok(checkpoint)
    })
    .transpose()
}

async fn persist_checkpoint(
    tx: &mut Transaction<'_, Sqlite>,
    checkpoint: AuthorityCheckpoint,
    version: FrontierVersion,
) -> Result<(), AuthBusAuthorityError> {
    sqlx::query(
        "UPDATE authbus_authority_checkpoint
         SET generation = ?, checkpoint_digest = ?, frontier_version = ? WHERE singleton = 1",
    )
    .bind(u64_bytes(checkpoint.generation).as_slice())
    .bind(checkpoint.digest.as_array().as_slice())
    .bind(version as i64)
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn is_dirty(tx: &mut Transaction<'_, Sqlite>) -> Result<bool, AuthBusAuthorityError> {
    let value: i64 = sqlx::query_scalar(
        "SELECT dirty FROM authbus_authority_checkpoint_dirty WHERE singleton = 1",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(value != 0)
}

async fn set_dirty(
    tx: &mut Transaction<'_, Sqlite>,
    dirty: bool,
) -> Result<(), AuthBusAuthorityError> {
    sqlx::query("UPDATE authbus_authority_checkpoint_dirty SET dirty = ? WHERE singleton = 1")
        .bind(if dirty { 1_i64 } else { 0_i64 })
        .execute(&mut **tx)
        .await
        .map_err(storage)?;
    Ok(())
}

async fn authority_frontier_digest_tx(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Digest32, AuthBusAuthorityError> {
    authority_frontier_digest_for_version(tx, FrontierVersion::DispatchV5).await
}

pub(crate) async fn authority_frontier_digest_for_version(
    tx: &mut Transaction<'_, Sqlite>,
    version: FrontierVersion,
) -> Result<Digest32, AuthBusAuthorityError> {
    let mut bytes = match version {
        FrontierVersion::LegacyV4 => b"hepta.authbus.authority-frontier.v1\0",
        FrontierVersion::DispatchV5 => b"hepta.authbus.authority-frontier.v2\0",
    }
    .to_vec();
    append_rows(
        tx,
        &mut bytes,
        "trusted_time",
        "SELECT hex(wall_time_ms)||'|'||hex(source_revision)||'|'||hex(source_digest)
         FROM authbus_trusted_time ORDER BY singleton",
    )
    .await?;
    append_rows(
        tx,
        &mut bytes,
        "policy",
        "SELECT policy_id||'|'||principal||'|'||action||'|'||hex(scope_digest)||'|'||
                effect||'|'||hex(revision)||'|'||hex(not_before_ms)||'|'||
                hex(expires_at_ms)||'|'||CAST(revoked AS TEXT)
         FROM authbus_policy ORDER BY policy_id",
    )
    .await?;
    append_rows(
        tx,
        &mut bytes,
        "policy_history",
        "SELECT policy_id||'|'||principal||'|'||action||'|'||hex(scope_digest)||'|'||
                effect||'|'||hex(revision)||'|'||hex(not_before_ms)||'|'||
                hex(expires_at_ms)||'|'||CAST(revoked AS TEXT)
         FROM authbus_policy_history ORDER BY policy_id, revision",
    )
    .await?;
    append_rows(
        tx,
        &mut bytes,
        "policy_archive",
        "SELECT policy_id||'|'||principal||'|'||action||'|'||hex(scope_digest)||'|'||
                effect||'|'||hex(revision)||'|'||hex(not_before_ms)||'|'||
                hex(expires_at_ms)||'|'||CAST(revoked AS TEXT)||'|'||hex(retired_at_ms)
         FROM authbus_policy_archive ORDER BY policy_id",
    )
    .await?;
    append_rows(
        tx,
        &mut bytes,
        "quota",
        "SELECT quota_key||'|'||principal||'|'||hex(scope_digest)||'|'||unit||'|'||
                period_id||'|'||hex(limit_amount)||'|'||hex(available)||'|'||
                hex(reserved)||'|'||hex(consumed)||'|'||hex(revision)
         FROM authbus_quota_registry ORDER BY quota_key",
    )
    .await?;
    // Legacy hashing is only for validating an outstanding v4 witness.
    // Every newly published checkpoint uses DispatchV5 and binds dispatch time.
    let (reservation_sql, archive_sql) = match version {
        FrontierVersion::LegacyV4 => (LEGACY_RESERVATION_FRONTIER_SQL, LEGACY_ARCHIVE_FRONTIER_SQL),
        FrontierVersion::DispatchV5 => (RESERVATION_FRONTIER_SQL, ARCHIVE_FRONTIER_SQL),
    };
    append_rows(tx, &mut bytes, "reservation", reservation_sql).await?;
    append_rows(tx, &mut bytes, "reservation_archive", archive_sql).await?;
    append_rows(
        tx,
        &mut bytes,
        "issuer",
        "SELECT issuer_id||'|'||purpose||'|'||hex(key_epoch)||'|'||hex(public_key)||'|'||
                state||'|'||hex(revision)
         FROM authbus_issuer_registry ORDER BY issuer_id, purpose, key_epoch",
    )
    .await?;
    Ok(Digest32::of_bytes(&bytes))
}

const RESERVATION_FRONTIER_SQL: &str =
    "SELECT reservation_id||'|'||operation_id||'|'||quota_key||'|'||period_id||'|'||
            principal||'|'||hex(amount)||'|'||hex(effect_digest)||'|'||policy_id||'|'||
            hex(policy_revision)||'|'||hex(policy_decision_digest)||'|'||state||'|'||
            hex(revision)||'|'||hex(expires_at_ms)||'|'||hex(created_at_ms)||'|'||
            hex(updated_at_ms)||'|'||COALESCE(hex(dispatched_at_ms),'-')||'|'||
            COALESCE(hex(dispatch_digest),'-')||'|'||COALESCE(hex(terminal_evidence),'-')||'|'||
            COALESCE(hex(observed_cost),'-')||'|'||
            COALESCE(hex(settlement_digest),'-')
     FROM authbus_quota_reservation ORDER BY reservation_id";

const ARCHIVE_FRONTIER_SQL: &str =
    "SELECT reservation_id||'|'||operation_id||'|'||quota_key||'|'||period_id||'|'||
            principal||'|'||hex(amount)||'|'||hex(effect_digest)||'|'||policy_id||'|'||
            hex(policy_revision)||'|'||hex(policy_decision_digest)||'|'||state||'|'||
            hex(revision)||'|'||hex(expires_at_ms)||'|'||hex(created_at_ms)||'|'||
            hex(updated_at_ms)||'|'||COALESCE(hex(dispatched_at_ms),'-')||'|'||
            COALESCE(hex(dispatch_digest),'-')||'|'||COALESCE(hex(terminal_evidence),'-')||'|'||
            COALESCE(hex(observed_cost),'-')||'|'||
            COALESCE(hex(settlement_digest),'-')||'|'||hex(archived_at_ms)
     FROM authbus_quota_reservation_archive ORDER BY reservation_id";

const LEGACY_RESERVATION_FRONTIER_SQL: &str =
    "SELECT reservation_id||'|'||operation_id||'|'||quota_key||'|'||period_id||'|'||
            principal||'|'||hex(amount)||'|'||hex(effect_digest)||'|'||policy_id||'|'||
            hex(policy_revision)||'|'||hex(policy_decision_digest)||'|'||state||'|'||
            hex(revision)||'|'||hex(expires_at_ms)||'|'||hex(created_at_ms)||'|'||
            hex(updated_at_ms)||'|'||
            COALESCE(hex(dispatch_digest),'-')||'|'||COALESCE(hex(terminal_evidence),'-')||'|'||
            COALESCE(hex(observed_cost),'-')||'|'||
            COALESCE(hex(settlement_digest),'-')
     FROM authbus_quota_reservation ORDER BY reservation_id";

const LEGACY_ARCHIVE_FRONTIER_SQL: &str =
    "SELECT reservation_id||'|'||operation_id||'|'||quota_key||'|'||period_id||'|'||
            principal||'|'||hex(amount)||'|'||hex(effect_digest)||'|'||policy_id||'|'||
            hex(policy_revision)||'|'||hex(policy_decision_digest)||'|'||state||'|'||
            hex(revision)||'|'||hex(expires_at_ms)||'|'||hex(created_at_ms)||'|'||
            hex(updated_at_ms)||'|'||
            COALESCE(hex(dispatch_digest),'-')||'|'||COALESCE(hex(terminal_evidence),'-')||'|'||
            COALESCE(hex(observed_cost),'-')||'|'||
            COALESCE(hex(settlement_digest),'-')||'|'||hex(archived_at_ms)
     FROM authbus_quota_reservation_archive ORDER BY reservation_id";

async fn append_rows(
    tx: &mut Transaction<'_, Sqlite>,
    bytes: &mut Vec<u8>,
    tag: &str,
    query: &'static str,
) -> Result<(), AuthBusAuthorityError> {
    push(bytes, tag.as_bytes());
    let rows: Vec<String> = sqlx::query_scalar(query)
        .fetch_all(&mut **tx)
        .await
        .map_err(storage)?;
    bytes.extend_from_slice(&(rows.len() as u64).to_be_bytes());
    for row in rows {
        push(bytes, row.as_bytes());
    }
    Ok(())
}

fn push(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
#[path = "recovery_tests.rs"]
mod tests;
