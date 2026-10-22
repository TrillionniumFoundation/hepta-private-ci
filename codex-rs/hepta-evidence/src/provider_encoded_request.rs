use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::provider_record::ensure_provider_intent;
use crate::schema_validation::classify_sqlx_error;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

impl HeptaEvidenceStore {
    /// Append-only, one-to-one extension of the original durable attempt.
    pub async fn bind_provider_encoded_request_v1(
        &self,
        intent: &ProviderInvocationIntent,
        digest: &Sha256Digest,
        bytes: u64,
    ) -> Result<AppendDisposition, EvidenceError> {
        let length = i64::try_from(bytes)
            .ok()
            .filter(|length| *length > 0)
            .ok_or_else(|| EvidenceError::InvalidRecord("invalid encoded request length".into()))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        ensure_provider_intent(&mut tx, intent).await?;
        let terminal: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM provider_invocation_terminals WHERE attempt_id = ?)",
        )
        .bind(intent.attempt_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if terminal {
            return Err(EvidenceError::InvalidRecord(
                "provider attempt is terminal".into(),
            ));
        }
        let inserted = sqlx::query(
            "INSERT INTO provider_encoded_requests_v1 VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        )
        .bind(intent.attempt_id.as_str())
        .bind(digest.as_str())
        .bind(length)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?
        .rows_affected()
            == 1;
        let row = sqlx::query("SELECT body_sha256, byte_length FROM provider_encoded_requests_v1 WHERE attempt_id = ?")
            .bind(intent.attempt_id.as_str()).fetch_one(&mut *tx).await.map_err(classify_sqlx_error)?;
        if row
            .try_get::<String, _>("body_sha256")
            .map_err(classify_sqlx_error)?
            != digest.as_str()
            || row
                .try_get::<i64, _>("byte_length")
                .map_err(classify_sqlx_error)?
                != length
        {
            return Err(EvidenceError::IdempotencyConflict {
                record_id: intent.attempt_id.as_str().into(),
            });
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(if inserted {
            AppendDisposition::Inserted
        } else {
            AppendDisposition::AlreadyPresent
        })
    }

    pub async fn get_provider_encoded_request_v1(
        &self,
        intent: &ProviderInvocationIntent,
    ) -> Result<Option<(Sha256Digest, u64)>, EvidenceError> {
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        ensure_provider_intent(&mut tx, intent).await?;
        let row = sqlx::query("SELECT body_sha256, byte_length FROM provider_encoded_requests_v1 WHERE attempt_id = ?")
            .bind(intent.attempt_id.as_str()).fetch_optional(&mut *tx).await.map_err(classify_sqlx_error)?;
        let binding = row
            .map(|row| {
                let digest = Sha256Digest::parse(
                    row.try_get::<String, _>("body_sha256")
                        .map_err(classify_sqlx_error)?,
                )
                .map_err(EvidenceError::Corrupt)?;
                let bytes = u64::try_from(
                    row.try_get::<i64, _>("byte_length")
                        .map_err(classify_sqlx_error)?,
                )
                .ok()
                .filter(|n| *n > 0)
                .ok_or_else(|| EvidenceError::Corrupt("invalid encoded request length".into()))?;
                Ok((digest, bytes))
            })
            .transpose()?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(binding)
    }
}
