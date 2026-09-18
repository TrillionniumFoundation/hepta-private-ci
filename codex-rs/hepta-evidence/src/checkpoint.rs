use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

pub const EVIDENCE_EXTERNAL_CHECKPOINT_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceExternalCheckpointBodyV1 {
    schema_version: u32,
    migration_count: u32,
    migration_prefix_sha256: Sha256Digest,
    qualification_max_seq: u64,
    qualification_receipt_count: u64,
    qualification_prefix_sha256: Sha256Digest,
    frontier_receipt_id: Option<String>,
    frontier_envelope_sha256: Option<Sha256Digest>,
    observed_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceExternalCheckpointV1 {
    pub schema_version: u32,
    pub migration_count: u32,
    pub migration_prefix_sha256: Sha256Digest,
    pub qualification_max_seq: u64,
    pub qualification_receipt_count: u64,
    pub qualification_prefix_sha256: Sha256Digest,
    pub frontier_receipt_id: Option<String>,
    pub frontier_envelope_sha256: Option<Sha256Digest>,
    pub observed_unix_ms: u64,
    pub checkpoint_sha256: Sha256Digest,
}

impl EvidenceExternalCheckpointV1 {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        if self.schema_version != EVIDENCE_EXTERNAL_CHECKPOINT_SCHEMA_VERSION
            || self.migration_count == 0
            || self.observed_unix_ms == 0
            || (self.frontier_receipt_id.is_some() != self.frontier_envelope_sha256.is_some())
            || (self.qualification_receipt_count == 0
                && (self.qualification_max_seq != 0 || self.frontier_receipt_id.is_some()))
            || (self.qualification_receipt_count != 0
                && (self.qualification_max_seq == 0 || self.frontier_receipt_id.is_none()))
        {
            return Err(EvidenceError::InvalidRecord(
                "external evidence checkpoint has an invalid shape".to_string(),
            ));
        }
        let expected = self.body_digest()?;
        if expected != self.checkpoint_sha256 {
            return Err(EvidenceError::InvalidRecord(
                "external evidence checkpoint digest is invalid".to_string(),
            ));
        }
        Ok(())
    }

    fn body(&self) -> EvidenceExternalCheckpointBodyV1 {
        EvidenceExternalCheckpointBodyV1 {
            schema_version: self.schema_version,
            migration_count: self.migration_count,
            migration_prefix_sha256: self.migration_prefix_sha256.clone(),
            qualification_max_seq: self.qualification_max_seq,
            qualification_receipt_count: self.qualification_receipt_count,
            qualification_prefix_sha256: self.qualification_prefix_sha256.clone(),
            frontier_receipt_id: self.frontier_receipt_id.clone(),
            frontier_envelope_sha256: self.frontier_envelope_sha256.clone(),
            observed_unix_ms: self.observed_unix_ms,
        }
    }

    fn body_digest(&self) -> Result<Sha256Digest, EvidenceError> {
        Ok(Sha256Digest::for_bytes(&canonical_json(&self.body())?))
    }
}

impl HeptaEvidenceStore {
    /// Capture a logical monotonic checkpoint for the migration lineage and
    /// append-only qualification evidence prefix. The returned record grants
    /// no authority and becomes anti-rollback evidence only after an operator
    /// retains it outside the SQLite failure domain.
    pub async fn capture_external_checkpoint(
        &self,
    ) -> Result<EvidenceExternalCheckpointV1, EvidenceError> {
        let migration_count_i64: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations")
            .fetch_one(&self.pool)
            .await
            .map_err(classify_sqlx_error)?;
        let migration_count = u32::try_from(migration_count_i64).map_err(|_| {
            EvidenceError::Corrupt("migration count does not fit checkpoint".to_string())
        })?;
        let migration_prefix_sha256 = migration_prefix_sha256(&self.pool, migration_count).await?;

        let qualification_receipt_count_i64: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM qualification_evidence")
                .fetch_one(&self.pool)
                .await
                .map_err(classify_sqlx_error)?;
        let qualification_receipt_count =
            u64::try_from(qualification_receipt_count_i64).map_err(|_| {
                EvidenceError::Corrupt(
                    "qualification receipt count does not fit checkpoint".to_string(),
                )
            })?;
        let qualification_max_seq_i64: i64 =
            sqlx::query_scalar("SELECT COALESCE(MAX(seq), 0) FROM qualification_evidence")
                .fetch_one(&self.pool)
                .await
                .map_err(classify_sqlx_error)?;
        let qualification_max_seq = u64::try_from(qualification_max_seq_i64).map_err(|_| {
            EvidenceError::Corrupt(
                "qualification evidence sequence does not fit checkpoint".to_string(),
            )
        })?;
        let qualification_prefix_sha256 = qualification_prefix_sha256(
            &self.pool,
            qualification_max_seq,
            qualification_receipt_count,
        )
        .await?;
        let frontier = if qualification_max_seq == 0 {
            None
        } else {
            sqlx::query(
                "SELECT receipt_id, envelope_sha256
                 FROM qualification_evidence WHERE seq = ?",
            )
            .bind(i64::try_from(qualification_max_seq).map_err(|_| {
                EvidenceError::Corrupt(
                    "qualification evidence sequence exceeds SQLite INTEGER".to_string(),
                )
            })?)
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?
        };
        let (frontier_receipt_id, frontier_envelope_sha256) = match frontier {
            Some(row) => {
                let receipt_id: String = row.try_get("receipt_id").map_err(classify_sqlx_error)?;
                let digest = Sha256Digest::parse(
                    row.try_get::<String, _>("envelope_sha256")
                        .map_err(classify_sqlx_error)?,
                )
                .map_err(EvidenceError::Corrupt)?;
                (Some(receipt_id), Some(digest))
            }
            None if qualification_max_seq == 0 => (None, None),
            None => {
                return Err(EvidenceError::Corrupt(
                    "qualification checkpoint frontier row is missing".to_string(),
                ));
            }
        };
        let observed_unix_ms = u64::try_from(now_millis()?)
            .map_err(|_| EvidenceError::Unavailable("system time is negative".to_string()))?;
        let body = EvidenceExternalCheckpointBodyV1 {
            schema_version: EVIDENCE_EXTERNAL_CHECKPOINT_SCHEMA_VERSION,
            migration_count,
            migration_prefix_sha256,
            qualification_max_seq,
            qualification_receipt_count,
            qualification_prefix_sha256,
            frontier_receipt_id,
            frontier_envelope_sha256,
            observed_unix_ms,
        };
        let checkpoint_sha256 = Sha256Digest::for_bytes(&canonical_json(&body)?);
        Ok(EvidenceExternalCheckpointV1 {
            schema_version: body.schema_version,
            migration_count: body.migration_count,
            migration_prefix_sha256: body.migration_prefix_sha256,
            qualification_max_seq: body.qualification_max_seq,
            qualification_receipt_count: body.qualification_receipt_count,
            qualification_prefix_sha256: body.qualification_prefix_sha256,
            frontier_receipt_id: body.frontier_receipt_id,
            frontier_envelope_sha256: body.frontier_envelope_sha256,
            observed_unix_ms: body.observed_unix_ms,
            checkpoint_sha256,
        })
    }

    /// Reject a store that is behind or differs from an externally retained
    /// checkpoint. A newer store may extend the retained prefix but cannot
    /// replace, truncate or rewrite it.
    pub async fn verify_external_checkpoint(
        &self,
        checkpoint: &EvidenceExternalCheckpointV1,
    ) -> Result<(), EvidenceError> {
        checkpoint.validate()?;
        let current_migration_count_i64: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations")
                .fetch_one(&self.pool)
                .await
                .map_err(classify_sqlx_error)?;
        let current_migration_count = u32::try_from(current_migration_count_i64).map_err(|_| {
            EvidenceError::Corrupt("migration count does not fit checkpoint".to_string())
        })?;
        if current_migration_count < checkpoint.migration_count {
            return Err(EvidenceError::Corrupt(
                "evidence store migration lineage is behind the external checkpoint".to_string(),
            ));
        }
        let migration_digest =
            migration_prefix_sha256(&self.pool, checkpoint.migration_count).await?;
        if migration_digest != checkpoint.migration_prefix_sha256 {
            return Err(EvidenceError::Corrupt(
                "evidence store migration prefix differs from the external checkpoint".to_string(),
            ));
        }

        let current_count_i64: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM qualification_evidence")
                .fetch_one(&self.pool)
                .await
                .map_err(classify_sqlx_error)?;
        let current_count = u64::try_from(current_count_i64).map_err(|_| {
            EvidenceError::Corrupt(
                "qualification receipt count does not fit checkpoint".to_string(),
            )
        })?;
        let current_max_seq_i64: i64 =
            sqlx::query_scalar("SELECT COALESCE(MAX(seq), 0) FROM qualification_evidence")
                .fetch_one(&self.pool)
                .await
                .map_err(classify_sqlx_error)?;
        let current_max_seq = u64::try_from(current_max_seq_i64).map_err(|_| {
            EvidenceError::Corrupt(
                "qualification evidence sequence does not fit checkpoint".to_string(),
            )
        })?;
        if current_count < checkpoint.qualification_receipt_count
            || current_max_seq < checkpoint.qualification_max_seq
        {
            return Err(EvidenceError::Corrupt(
                "qualification evidence is behind the external checkpoint".to_string(),
            ));
        }

        let prefix = qualification_prefix_sha256(
            &self.pool,
            checkpoint.qualification_max_seq,
            checkpoint.qualification_receipt_count,
        )
        .await?;
        if prefix != checkpoint.qualification_prefix_sha256 {
            return Err(EvidenceError::Corrupt(
                "qualification evidence prefix differs from the external checkpoint".to_string(),
            ));
        }
        if checkpoint.qualification_max_seq != 0 {
            let row = sqlx::query(
                "SELECT receipt_id, envelope_sha256
                 FROM qualification_evidence WHERE seq = ?",
            )
            .bind(
                i64::try_from(checkpoint.qualification_max_seq).map_err(|_| {
                    EvidenceError::Corrupt(
                        "qualification checkpoint frontier exceeds SQLite INTEGER".to_string(),
                    )
                })?,
            )
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?
            .ok_or_else(|| {
                EvidenceError::Corrupt(
                    "qualification checkpoint frontier row is missing".to_string(),
                )
            })?;
            let receipt_id: String = row.try_get("receipt_id").map_err(classify_sqlx_error)?;
            let envelope_sha256 = Sha256Digest::parse(
                row.try_get::<String, _>("envelope_sha256")
                    .map_err(classify_sqlx_error)?,
            )
            .map_err(EvidenceError::Corrupt)?;
            if checkpoint.frontier_receipt_id.as_deref() != Some(receipt_id.as_str())
                || checkpoint.frontier_envelope_sha256.as_ref() != Some(&envelope_sha256)
            {
                return Err(EvidenceError::Corrupt(
                    "qualification checkpoint frontier identity differs".to_string(),
                ));
            }
        }
        Ok(())
    }

    pub async fn open_with_external_checkpoint(
        sqlite: &codex_state::SqliteConfig,
        checkpoint: &EvidenceExternalCheckpointV1,
    ) -> Result<Self, EvidenceError> {
        let store = Self::open(sqlite).await?;
        if let Err(error) = store.verify_external_checkpoint(checkpoint).await {
            store.pool.close().await;
            return Err(error);
        }
        Ok(store)
    }
}

async fn migration_prefix_sha256(
    pool: &SqlitePool,
    count: u32,
) -> Result<Sha256Digest, EvidenceError> {
    let rows = sqlx::query(
        "SELECT version, description, checksum
         FROM _sqlx_migrations ORDER BY version LIMIT ?",
    )
    .bind(i64::from(count))
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let expected_count = usize::try_from(count).map_err(|_| {
        EvidenceError::Corrupt("migration checkpoint count does not fit usize".to_string())
    })?;
    if rows.len() != expected_count {
        return Err(EvidenceError::Corrupt(
            "migration prefix is shorter than the external checkpoint".to_string(),
        ));
    }
    let mut hasher = Sha256::new();
    hasher.update(b"hepta.kernel.evidence.migration-prefix.v1\0");
    for row in rows {
        let version: i64 = row.try_get("version").map_err(classify_sqlx_error)?;
        let description: String = row.try_get("description").map_err(classify_sqlx_error)?;
        let checksum: Vec<u8> = row.try_get("checksum").map_err(classify_sqlx_error)?;
        hasher.update(version.to_be_bytes());
        update_len_bytes(&mut hasher, description.as_bytes())?;
        update_len_bytes(&mut hasher, &checksum)?;
    }
    digest_output(hasher)
}

async fn qualification_prefix_sha256(
    pool: &SqlitePool,
    max_seq: u64,
    expected_count: u64,
) -> Result<Sha256Digest, EvidenceError> {
    let max_seq_i64 = i64::try_from(max_seq).map_err(|_| {
        EvidenceError::Corrupt(
            "qualification checkpoint sequence exceeds SQLite INTEGER".to_string(),
        )
    })?;
    let rows = sqlx::query(
        "SELECT seq, receipt_id, envelope_sha256
         FROM qualification_evidence
         WHERE seq <= ? ORDER BY seq ASC",
    )
    .bind(max_seq_i64)
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let expected_count = usize::try_from(expected_count).map_err(|_| {
        EvidenceError::Corrupt(
            "qualification checkpoint receipt count does not fit usize".to_string(),
        )
    })?;
    if rows.len() != expected_count {
        return Err(EvidenceError::Corrupt(
            "qualification checkpoint prefix count differs".to_string(),
        ));
    }
    let mut hasher = Sha256::new();
    hasher.update(b"hepta.kernel.evidence.qualification-prefix.v1\0");
    for row in rows {
        let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
        let receipt_id: String = row.try_get("receipt_id").map_err(classify_sqlx_error)?;
        let envelope_sha256: String = row
            .try_get("envelope_sha256")
            .map_err(classify_sqlx_error)?;
        hasher.update(seq.to_be_bytes());
        update_len_bytes(&mut hasher, receipt_id.as_bytes())?;
        update_len_bytes(&mut hasher, envelope_sha256.as_bytes())?;
    }
    digest_output(hasher)
}

fn update_len_bytes(hasher: &mut Sha256, bytes: &[u8]) -> Result<(), EvidenceError> {
    let length = u64::try_from(bytes.len()).map_err(|_| {
        EvidenceError::Corrupt("checkpoint field length does not fit u64".to_string())
    })?;
    hasher.update(length.to_be_bytes());
    hasher.update(bytes);
    Ok(())
}

fn digest_output(hasher: Sha256) -> Result<Sha256Digest, EvidenceError> {
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}
