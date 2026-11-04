use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceAcceptedFrontierV1;
use crate::EvidenceError;
use crate::EvidenceFrontierAcceptanceDisposition;
use crate::EvidenceRecoverySnapshotV1;
use crate::HeptaEvidenceStore;
use crate::frontier_acceptance::accept_in_transaction;
use crate::recovery_frontier::authenticated_snapshot_in_transaction;
use crate::schema_validation::classify_sqlx_error;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceTrustGenerationAcceptanceV1 {
    pub store_id: String,
    pub agent_id: String,
    pub registry_generation: u64,
    pub registry_sha256: Sha256Digest,
    pub predecessor_sha256: Option<Sha256Digest>,
    pub accepted_frontier_generation: u64,
    pub accepted_frontier_sha256: Sha256Digest,
    pub backend_identity_sha256: Sha256Digest,
    pub accepted_at_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvidenceTrustAcceptanceDisposition {
    Inserted,
    AlreadyPresent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EvidenceProductionAcceptanceDispositionV1 {
    pub trust: EvidenceTrustAcceptanceDisposition,
    pub frontier: EvidenceFrontierAcceptanceDisposition,
}

impl HeptaEvidenceStore {
    pub async fn latest_accepted_trust_generation(
        &self,
        store_id: &str,
    ) -> Result<Option<EvidenceTrustGenerationAcceptanceV1>, EvidenceError> {
        validate_stable_id(store_id, "trust acceptance store")?;
        let row = sqlx::query(
            "SELECT store_id, agent_id, registry_generation, registry_sha256,
                    predecessor_sha256, accepted_frontier_generation,
                    accepted_frontier_sha256, backend_identity_sha256, accepted_at_ms
             FROM evidence_trust_acceptance
             WHERE store_id = ? ORDER BY seq DESC LIMIT 1",
        )
        .bind(store_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        row.as_ref().map(decode_row).transpose()
    }

    /// Atomically compare the authenticated database snapshot, advance the
    /// monotonic issuer-trust lineage and accept the independently signed
    /// external frontier. No one of these facts can commit without the others.
    pub async fn accept_production_generation_at_snapshot(
        &self,
        frontier: &EvidenceAcceptedFrontierV1,
        expected_snapshot: &EvidenceRecoverySnapshotV1,
        trust: &EvidenceTrustGenerationAcceptanceV1,
    ) -> Result<EvidenceProductionAcceptanceDispositionV1, EvidenceError> {
        validate_trust(trust)?;
        if expected_snapshot.schema_version != 2 {
            return Err(invalid(
                "production trust acceptance requires authenticated snapshot V2",
            ));
        }
        if trust.store_id != frontier.store_id
            || trust.accepted_frontier_generation != frontier.frontier_generation
            || trust.accepted_frontier_sha256 != frontier.frontier_sha256
            || trust.backend_identity_sha256 != frontier.backend_identity_sha256
            || trust.accepted_at_unix_ms != frontier.accepted_at_unix_ms
        {
            return Err(invalid(
                "trust generation and external frontier are not one atomic authority subject",
            ));
        }
        self.verify_production_qualification_provenance(
            trust.registry_generation,
            &trust.registry_sha256,
        )
        .await?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let actual = authenticated_snapshot_in_transaction(&mut transaction).await?;
        if actual != *expected_snapshot {
            return Err(invalid(
                "evidence changed before atomic trust/frontier acceptance",
            ));
        }
        let trust_disposition = accept_trust_in_transaction(&mut transaction, trust).await?;
        let frontier_disposition = accept_in_transaction(&mut transaction, frontier, false).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(EvidenceProductionAcceptanceDispositionV1 {
            trust: trust_disposition,
            frontier: frontier_disposition,
        })
    }
}

async fn accept_trust_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    accepted: &EvidenceTrustGenerationAcceptanceV1,
) -> Result<EvidenceTrustAcceptanceDisposition, EvidenceError> {
    validate_trust(accepted)?;
    let bound: Option<String> =
        sqlx::query_scalar("SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1")
            .fetch_optional(&mut **transaction)
            .await
            .map_err(classify_sqlx_error)?;
    if bound.as_deref() != Some(accepted.store_id.as_str()) {
        return Err(invalid(
            "trust acceptance does not match the enrolled recovery store",
        ));
    }
    let existing = sqlx::query(
        "SELECT store_id, agent_id, registry_generation, registry_sha256,
                predecessor_sha256, accepted_frontier_generation,
                accepted_frontier_sha256, backend_identity_sha256, accepted_at_ms
         FROM evidence_trust_acceptance
         WHERE store_id = ? ORDER BY seq DESC LIMIT 1",
    )
    .bind(&accepted.store_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?
    .as_ref()
    .map(decode_row)
    .transpose()?;
    if let Some(existing) = existing {
        if existing.agent_id != accepted.agent_id {
            return Err(invalid(
                "accepted evidence trust cannot change the owning agent",
            ));
        }
        if existing.backend_identity_sha256 != accepted.backend_identity_sha256 {
            return Err(invalid(
                "accepted evidence trust cannot substitute the rollback backend",
            ));
        }
        if accepted.registry_generation < existing.registry_generation {
            return Err(invalid("evidence trust registry generation rollback"));
        }
        if accepted.registry_generation == existing.registry_generation {
            if existing.registry_sha256 == accepted.registry_sha256
                && existing.predecessor_sha256 == accepted.predecessor_sha256
            {
                return Ok(EvidenceTrustAcceptanceDisposition::AlreadyPresent);
            }
            return Err(EvidenceError::IdempotencyConflict {
                record_id: format!(
                    "evidence_trust_acceptance:{}:{}",
                    accepted.store_id, accepted.registry_generation
                ),
            });
        }
        let expected_generation = existing
            .registry_generation
            .checked_add(1)
            .ok_or_else(|| invalid("evidence trust registry generation exhausted"))?;
        if accepted.registry_generation != expected_generation
            || accepted.predecessor_sha256.as_ref() != Some(&existing.registry_sha256)
            || accepted.accepted_frontier_generation <= existing.accepted_frontier_generation
        {
            return Err(invalid(
                "evidence trust rotation skips a generation, breaks predecessor linkage or reuses an old frontier",
            ));
        }
    } else if accepted.registry_generation != 1 || accepted.predecessor_sha256.is_some() {
        return Err(invalid(
            "first accepted evidence trust registry must be generation one without a predecessor",
        ));
    }
    sqlx::query(
        "INSERT INTO evidence_trust_acceptance (
            store_id, agent_id, registry_generation, registry_sha256,
            predecessor_sha256, accepted_frontier_generation,
            accepted_frontier_sha256, backend_identity_sha256, accepted_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&accepted.store_id)
    .bind(&accepted.agent_id)
    .bind(accepted.registry_generation.to_be_bytes().to_vec())
    .bind(accepted.registry_sha256.as_str())
    .bind(
        accepted
            .predecessor_sha256
            .as_ref()
            .map(Sha256Digest::as_str),
    )
    .bind(accepted.accepted_frontier_generation.to_be_bytes().to_vec())
    .bind(accepted.accepted_frontier_sha256.as_str())
    .bind(accepted.backend_identity_sha256.as_str())
    .bind(accepted.accepted_at_unix_ms.to_be_bytes().to_vec())
    .execute(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(EvidenceTrustAcceptanceDisposition::Inserted)
}

fn validate_trust(accepted: &EvidenceTrustGenerationAcceptanceV1) -> Result<(), EvidenceError> {
    validate_stable_id(&accepted.store_id, "trust acceptance store")?;
    validate_stable_id(&accepted.agent_id, "trust acceptance agent")?;
    if accepted.registry_generation == 0
        || accepted.accepted_frontier_generation == 0
        || accepted.accepted_at_unix_ms == 0
    {
        return Err(invalid(
            "trust and frontier generations and acceptance time must be positive",
        ));
    }
    match (
        accepted.registry_generation,
        accepted.predecessor_sha256.as_ref(),
    ) {
        (1, None) => {}
        (1, Some(_)) | (_, None) => {
            return Err(invalid(
                "trust predecessor is inconsistent with the registry generation",
            ));
        }
        (_, Some(_)) => {}
    }
    Ok(())
}

fn decode_row(row: &SqliteRow) -> Result<EvidenceTrustGenerationAcceptanceV1, EvidenceError> {
    Ok(EvidenceTrustGenerationAcceptanceV1 {
        store_id: row.try_get("store_id").map_err(classify_sqlx_error)?,
        agent_id: row.try_get("agent_id").map_err(classify_sqlx_error)?,
        registry_generation: read_u64(row, "registry_generation")?,
        registry_sha256: parse_digest(row, "registry_sha256")?,
        predecessor_sha256: row
            .try_get::<Option<String>, _>("predecessor_sha256")
            .map_err(classify_sqlx_error)?
            .map(Sha256Digest::parse)
            .transpose()
            .map_err(EvidenceError::Corrupt)?,
        accepted_frontier_generation: read_u64(row, "accepted_frontier_generation")?,
        accepted_frontier_sha256: parse_digest(row, "accepted_frontier_sha256")?,
        backend_identity_sha256: parse_digest(row, "backend_identity_sha256")?,
        accepted_at_unix_ms: read_u64(row, "accepted_at_ms")?,
    })
}

fn read_u64(row: &SqliteRow, column: &str) -> Result<u64, EvidenceError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(classify_sqlx_error)?;
    let bytes: [u8; 8] = bytes.try_into().map_err(|_| {
        EvidenceError::Corrupt(format!("{column} is not an eight-byte unsigned integer"))
    })?;
    Ok(u64::from_be_bytes(bytes))
}

fn parse_digest(row: &SqliteRow, column: &str) -> Result<Sha256Digest, EvidenceError> {
    Sha256Digest::parse(
        row.try_get::<String, _>(column)
            .map_err(classify_sqlx_error)?,
    )
    .map_err(EvidenceError::Corrupt)
}

fn validate_stable_id(value: &str, label: &str) -> Result<(), EvidenceError> {
    StableId::new(value.to_string())
        .map(|_| ())
        .map_err(|error| invalid(&format!("invalid {label}: {error}")))
}

fn invalid(message: &str) -> EvidenceError {
    EvidenceError::InvalidRecord(message.to_string())
}

#[cfg(test)]
#[path = "trust_acceptance_tests.rs"]
mod tests;
