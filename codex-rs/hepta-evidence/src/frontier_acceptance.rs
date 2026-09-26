use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceAcceptedFrontierV1 {
    pub store_id: String,
    pub frontier_generation: u64,
    pub frontier_sha256: Sha256Digest,
    pub backend_identity_sha256: Sha256Digest,
    pub accepted_at_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvidenceFrontierAcceptanceDisposition {
    Inserted,
    AlreadyPresent,
}

impl HeptaEvidenceStore {
    pub async fn latest_accepted_frontier(
        &self,
        store_id: &str,
    ) -> Result<Option<EvidenceAcceptedFrontierV1>, EvidenceError> {
        validate_store_id(store_id)?;
        let row = sqlx::query(
            "SELECT store_id, frontier_generation, frontier_sha256,
                    backend_identity_sha256, accepted_at_ms
             FROM evidence_frontier_acceptance
             WHERE store_id = ?
             ORDER BY seq DESC
             LIMIT 1",
        )
        .bind(store_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        row.map(decode_row).transpose()
    }

    /// Persist one verified external frontier under a database write lock.
    ///
    /// The first accepted generation may be any positive value because a node
    /// can bootstrap from a later independently published backup. Thereafter
    /// generations may only increase. Re-admitting the exact same generation,
    /// frontier digest and backend identity is an idempotent no-op; any other
    /// same-generation value is an identity conflict.
    pub async fn accept_recovery_frontier(
        &self,
        accepted: &EvidenceAcceptedFrontierV1,
    ) -> Result<EvidenceFrontierAcceptanceDisposition, EvidenceError> {
        validate_accepted(accepted)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;

        let bound_store_id: Option<String> = sqlx::query_scalar(
            "SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        match bound_store_id {
            Some(existing) if existing != accepted.store_id => {
                transaction.rollback().await.map_err(classify_sqlx_error)?;
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: "evidence_recovery_identity".to_string(),
                });
            }
            Some(_) => {}
            None => {
                sqlx::query(
                    "INSERT INTO evidence_recovery_identity (singleton, store_id)
                     VALUES (1, ?)",
                )
                .bind(&accepted.store_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
            }
        }

        let existing = sqlx::query(
            "SELECT store_id, frontier_generation, frontier_sha256,
                    backend_identity_sha256, accepted_at_ms
             FROM evidence_frontier_acceptance
             WHERE store_id = ?
             ORDER BY seq DESC
             LIMIT 1",
        )
        .bind(&accepted.store_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?
        .map(decode_row)
        .transpose()?;

        if let Some(existing) = existing {
            if existing.frontier_generation > accepted.frontier_generation {
                transaction.rollback().await.map_err(classify_sqlx_error)?;
                return Err(EvidenceError::InvalidRecord(format!(
                    "evidence recovery frontier generation {} rolls back accepted generation {}",
                    accepted.frontier_generation, existing.frontier_generation
                )));
            }
            if existing.frontier_generation == accepted.frontier_generation {
                transaction.rollback().await.map_err(classify_sqlx_error)?;
                if existing.frontier_sha256 == accepted.frontier_sha256
                    && existing.backend_identity_sha256 == accepted.backend_identity_sha256
                {
                    return Ok(EvidenceFrontierAcceptanceDisposition::AlreadyPresent);
                }
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: format!(
                        "evidence_frontier_acceptance:{}:{}",
                        accepted.store_id, accepted.frontier_generation
                    ),
                });
            }
        }

        sqlx::query(
            "INSERT INTO evidence_frontier_acceptance (
                store_id,
                frontier_generation,
                frontier_sha256,
                backend_identity_sha256,
                accepted_at_ms
             ) VALUES (?, ?, ?, ?, ?)",
        )
        .bind(&accepted.store_id)
        .bind(accepted.frontier_generation.to_be_bytes().to_vec())
        .bind(accepted.frontier_sha256.as_str())
        .bind(accepted.backend_identity_sha256.as_str())
        .bind(accepted.accepted_at_unix_ms.to_be_bytes().to_vec())
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(EvidenceFrontierAcceptanceDisposition::Inserted)
    }
}

fn validate_store_id(store_id: &str) -> Result<(), EvidenceError> {
    StableId::new(store_id.to_string()).map_err(|error| {
        EvidenceError::InvalidRecord(format!("invalid evidence recovery store id: {error}"))
    })?;
    Ok(())
}

fn validate_accepted(accepted: &EvidenceAcceptedFrontierV1) -> Result<(), EvidenceError> {
    validate_store_id(&accepted.store_id)?;
    if accepted.frontier_generation == 0 || accepted.accepted_at_unix_ms == 0 {
        return Err(EvidenceError::InvalidRecord(
            "accepted recovery frontier generation and timestamp must be positive".to_string(),
        ));
    }
    Ok(())
}

fn decode_row(row: sqlx::sqlite::SqliteRow) -> Result<EvidenceAcceptedFrontierV1, EvidenceError> {
    let generation: Vec<u8> = row
        .try_get("frontier_generation")
        .map_err(classify_sqlx_error)?;
    let accepted_at: Vec<u8> = row.try_get("accepted_at_ms").map_err(classify_sqlx_error)?;
    Ok(EvidenceAcceptedFrontierV1 {
        store_id: row.try_get("store_id").map_err(classify_sqlx_error)?,
        frontier_generation: decode_u64(&generation, "frontier generation")?,
        frontier_sha256: Sha256Digest::parse(
            row.try_get::<String, _>("frontier_sha256")
                .map_err(classify_sqlx_error)?,
        )
        .map_err(EvidenceError::Corrupt)?,
        backend_identity_sha256: Sha256Digest::parse(
            row.try_get::<String, _>("backend_identity_sha256")
                .map_err(classify_sqlx_error)?,
        )
        .map_err(EvidenceError::Corrupt)?,
        accepted_at_unix_ms: decode_u64(&accepted_at, "accepted-at timestamp")?,
    })
}

fn decode_u64(bytes: &[u8], label: &str) -> Result<u64, EvidenceError> {
    let encoded: [u8; 8] = bytes.try_into().map_err(|_| {
        EvidenceError::Corrupt(format!("{label} is not an eight-byte unsigned integer"))
    })?;
    Ok(u64::from_be_bytes(encoded))
}

#[cfg(test)]
#[path = "frontier_acceptance_tests.rs"]
mod tests;
