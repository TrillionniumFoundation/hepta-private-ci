//! File identity is not a monotonic trust oracle. Check the durable owner
//! generation in the SAME transaction as the qualification read or write.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::EvidenceError;
use crate::schema_validation::classify_sqlx_error;

pub(super) async fn require_admitted_trust(
    transaction: &mut Transaction<'_, Sqlite>,
    generation: Option<u64>,
    digest: Option<&Sha256Digest>,
) -> Result<(), EvidenceError> {
    if generation.is_some() != digest.is_some() || generation == Some(0) {
        return Err(EvidenceError::InvalidRecord(
            "qualification trust identity is incomplete".to_string(),
        ));
    }
    let bound: Option<String> = sqlx::query_scalar(
        "SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1",
    )
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let Some(store_id) = bound else {
        let retained: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM evidence_trust_acceptance")
            .fetch_one(&mut **transaction)
            .await
            .map_err(classify_sqlx_error)?;
        if retained != 0 {
            return Err(EvidenceError::Corrupt(
                "accepted evidence trust has no enrolled store identity".to_string(),
            ));
        }
        return Ok(());
    };
    let row = sqlx::query(
        "SELECT registry_generation, registry_sha256 FROM evidence_trust_acceptance
         WHERE store_id = ? ORDER BY seq DESC LIMIT 1",
    )
    .bind(store_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let Some(row) = row else {
        // Development before the first independently admitted production
        // generation remains supported. Once accepted, it cannot downgrade.
        return Ok(());
    };
    let bytes: Vec<u8> = row.try_get("registry_generation").map_err(classify_sqlx_error)?;
    let bytes: [u8; 8] = bytes.try_into().map_err(|_| {
        EvidenceError::Corrupt("accepted trust generation has invalid width".to_string())
    })?;
    let accepted_generation = u64::from_be_bytes(bytes);
    let accepted_digest: String = row.try_get("registry_sha256").map_err(classify_sqlx_error)?;
    let accepted_digest = Sha256Digest::parse(accepted_digest).map_err(EvidenceError::Corrupt)?;
    if accepted_generation == 0 {
        return Err(EvidenceError::Corrupt(
            "accepted trust generation must be positive".to_string(),
        ));
    }
    if generation != Some(accepted_generation) || digest != Some(&accepted_digest) {
        return Err(EvidenceError::InvalidRecord(
            "qualification trust is not the currently admitted production generation".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "qualification_trust_guard_tests.rs"]
mod tests;
