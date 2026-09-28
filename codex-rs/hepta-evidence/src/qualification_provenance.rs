use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

const PROVENANCE_PAGE_ROWS: i64 = 256;
const PROVENANCE_MAX_ROWS: i64 = 1_000_000;

impl HeptaEvidenceStore {
    /// Verify every retained qualification admission through one stable,
    /// bounded SQLite read epoch before production host publication.
    ///
    /// A row is production-admissible only when it retains the original
    /// 64-byte AuthBus signature and a positive trust-registry generation plus
    /// digest. The current signed registry is accepted directly. Older
    /// generations must have an immutable acceptance for this exact enrolled
    /// store; an acceptance belonging to another store cannot satisfy the
    /// join. Keyset paging bounds memory and avoids one acceptance query per
    /// evidence row. Accepted history cannot authorize a newer generation or
    /// a different digest at the currently selected generation.
    pub async fn verify_production_qualification_provenance_bounded(
        &self,
        current_registry_generation: u64,
        current_registry_sha256: &Sha256Digest,
    ) -> Result<(), EvidenceError> {
        if current_registry_generation == 0 {
            return Err(EvidenceError::InvalidRecord(
                "production qualification provenance requires a positive trust generation"
                    .to_string(),
            ));
        }

        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let store_id: Option<String> = sqlx::query_scalar(
            "SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let store_id = store_id.ok_or_else(|| {
            EvidenceError::InvalidRecord(
                "production qualification provenance requires an enrolled store identity"
                    .to_string(),
            )
        })?;

        let expected_rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM qualification_evidence")
            .fetch_one(&mut *transaction)
            .await
            .map_err(classify_sqlx_error)?;
        if !(0..=PROVENANCE_MAX_ROWS).contains(&expected_rows) {
            return Err(EvidenceError::Unavailable(
                "qualification provenance scan exceeds one million rows".to_string(),
            ));
        }

        let mut last_seq = 0_i64;
        let mut observed_rows = 0_i64;
        loop {
            let rows = sqlx::query(
                "SELECT q.seq, q.evidence_id, q.auth_signature,
                        q.trust_registry_generation, q.trust_registry_sha256,
                        a.seq AS accepted_trust_seq
                 FROM qualification_evidence AS q
                 LEFT JOIN evidence_trust_acceptance AS a
                   ON a.store_id = ?
                  AND a.registry_generation = q.trust_registry_generation
                  AND a.registry_sha256 = q.trust_registry_sha256
                 WHERE q.seq > ?
                 ORDER BY q.seq ASC
                 LIMIT ?",
            )
            .bind(&store_id)
            .bind(last_seq)
            .bind(PROVENANCE_PAGE_ROWS)
            .fetch_all(&mut *transaction)
            .await
            .map_err(classify_sqlx_error)?;
            if rows.is_empty() {
                break;
            }

            for row in rows {
                let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
                if seq <= last_seq {
                    return Err(EvidenceError::Corrupt(
                        "qualification provenance sequence is not strictly increasing".to_string(),
                    ));
                }
                let evidence_id: String =
                    row.try_get("evidence_id").map_err(classify_sqlx_error)?;
                let signature: Option<Vec<u8>> =
                    row.try_get("auth_signature").map_err(classify_sqlx_error)?;
                let generation_bytes: Option<Vec<u8>> = row
                    .try_get("trust_registry_generation")
                    .map_err(classify_sqlx_error)?;
                let digest = row
                    .try_get::<Option<String>, _>("trust_registry_sha256")
                    .map_err(classify_sqlx_error)?
                    .map(Sha256Digest::parse)
                    .transpose()
                    .map_err(EvidenceError::Corrupt)?;
                let accepted_trust_seq: Option<i64> = row
                    .try_get("accepted_trust_seq")
                    .map_err(classify_sqlx_error)?;

                let generation = generation_bytes
                    .map(|bytes| -> Result<u64, EvidenceError> {
                        let bytes: [u8; 8] = bytes.try_into().map_err(|_| {
                            EvidenceError::Corrupt(
                                "qualification trust generation has invalid width".to_string(),
                            )
                        })?;
                        Ok(u64::from_be_bytes(bytes))
                    })
                    .transpose()?;
                let (generation, digest) = match (signature.as_ref(), generation, digest) {
                    (Some(signature), Some(generation), Some(digest))
                        if signature.len() == 64 && generation > 0 =>
                    {
                        (generation, digest)
                    }
                    _ => {
                        return Err(EvidenceError::InvalidRecord(format!(
                            "qualification evidence {evidence_id} lacks complete authentication provenance"
                        )));
                    }
                };
                let current =
                    generation == current_registry_generation && digest == *current_registry_sha256;
                let accepted_prior =
                    generation < current_registry_generation && accepted_trust_seq.is_some();
                if !current && !accepted_prior {
                    return Err(EvidenceError::InvalidRecord(format!(
                        "qualification evidence {evidence_id} references an unaccepted trust generation or conflicts with the current registry for store {store_id}"
                    )));
                }

                last_seq = seq;
                observed_rows = observed_rows.checked_add(1).ok_or_else(|| {
                    EvidenceError::Unavailable(
                        "qualification provenance row count overflow".to_string(),
                    )
                })?;
            }
        }

        if observed_rows != expected_rows {
            return Err(EvidenceError::Corrupt(
                "qualification provenance scan did not cover the stable row set".to_string(),
            ));
        }
        transaction.commit().await.map_err(classify_sqlx_error)
    }
}
