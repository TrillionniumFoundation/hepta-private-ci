use codex_hepta_contracts::SecretLeaseBindingError;
use codex_hepta_contracts::SecretLeaseFuture;
use codex_hepta_contracts::SecretLeaseRecord;
use codex_hepta_contracts::SecretLeaseState;
use codex_hepta_contracts::SecretLeaseStore;
use codex_hepta_contracts::SecretLeaseStoreError;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

impl HeptaEvidenceStore {
    pub async fn load_secret_lease_record(
        &self,
        lease_key: &str,
    ) -> Result<Option<SecretLeaseRecord>, SecretLeaseStoreError> {
        let row = sqlx::query(
            "SELECT lease_key, provider_id, provider_path, request_sha256,
                    provider_lease_id, state, revision, schema_version,
                    record_json, record_sha256, updated_at_ms
             FROM secret_lease_records WHERE lease_key = ?",
        )
        .bind(lease_key)
        .fetch_optional(&self.pool)
        .await
        .map_err(map_sqlx)?;
        row.map(|row| decode_record(&row)).transpose()
    }

    pub async fn create_secret_lease_record(
        &self,
        record: &SecretLeaseRecord,
    ) -> Result<(), SecretLeaseStoreError> {
        record.validate().map_err(SecretLeaseStoreError::InvalidRecord)?;
        let (payload_json, record_sha256) = encode_record(record)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(map_sqlx)?;
        sqlx::query(
            "INSERT INTO secret_lease_records (
                lease_key, provider_id, provider_path, request_sha256,
                provider_lease_id, state, revision, schema_version,
                record_json, record_sha256, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(lease_key) DO NOTHING",
        )
        .bind(&record.lease_key)
        .bind(&record.provider_id)
        .bind(&record.provider_path)
        .bind(record.request_sha256.as_str())
        .bind(record.provider_lease_id.as_deref())
        .bind(state_as_str(record.state))
        .bind(revision_i64(record.revision)?)
        .bind(i64::from(record.schema_version))
        .bind(&payload_json)
        .bind(record_sha256.as_str())
        .bind(now_millis().map_err(map_evidence)?)
        .execute(&mut *transaction)
        .await
        .map_err(map_sqlx)?;

        let stored = load_in_transaction(&mut transaction, &record.lease_key)
            .await?
            .ok_or(SecretLeaseStoreError::Corrupt)?;
        if stored != *record {
            return Err(SecretLeaseStoreError::Conflict);
        }
        transaction.commit().await.map_err(map_sqlx)?;
        Ok(())
    }

    pub async fn compare_and_swap_secret_lease_record(
        &self,
        expected_revision: u64,
        next: &SecretLeaseRecord,
    ) -> Result<(), SecretLeaseStoreError> {
        next.validate()
            .map_err(SecretLeaseStoreError::InvalidRecord)?;
        let (payload_json, record_sha256) = encode_record(next)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(map_sqlx)?;
        let current = load_in_transaction(&mut transaction, &next.lease_key)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if current.revision != expected_revision {
            return Err(SecretLeaseStoreError::StaleRevision);
        }
        next.validate_transition_from(&current)
            .map_err(SecretLeaseStoreError::InvalidRecord)?;

        let update = sqlx::query(
            "UPDATE secret_lease_records SET
                provider_lease_id = ?,
                state = ?,
                revision = ?,
                schema_version = ?,
                record_json = ?,
                record_sha256 = ?,
                updated_at_ms = ?
             WHERE lease_key = ? AND revision = ?",
        )
        .bind(next.provider_lease_id.as_deref())
        .bind(state_as_str(next.state))
        .bind(revision_i64(next.revision)?)
        .bind(i64::from(next.schema_version))
        .bind(&payload_json)
        .bind(record_sha256.as_str())
        .bind(now_millis().map_err(map_evidence)?)
        .bind(&next.lease_key)
        .bind(revision_i64(expected_revision)?)
        .execute(&mut *transaction)
        .await
        .map_err(map_sqlx)?;
        if update.rows_affected() != 1 {
            return Err(SecretLeaseStoreError::StaleRevision);
        }

        let stored = load_in_transaction(&mut transaction, &next.lease_key)
            .await?
            .ok_or(SecretLeaseStoreError::Corrupt)?;
        if stored != *next {
            return Err(SecretLeaseStoreError::Corrupt);
        }
        transaction.commit().await.map_err(map_sqlx)?;
        Ok(())
    }
}

impl SecretLeaseStore for HeptaEvidenceStore {
    fn load<'a>(
        &'a self,
        lease_key: &'a str,
    ) -> SecretLeaseFuture<'a, Option<SecretLeaseRecord>> {
        Box::pin(async move { self.load_secret_lease_record(lease_key).await })
    }

    fn create<'a>(&'a self, record: &'a SecretLeaseRecord) -> SecretLeaseFuture<'a, ()> {
        Box::pin(async move { self.create_secret_lease_record(record).await })
    }

    fn compare_and_swap<'a>(
        &'a self,
        expected_revision: u64,
        next: &'a SecretLeaseRecord,
    ) -> SecretLeaseFuture<'a, ()> {
        Box::pin(async move {
            self.compare_and_swap_secret_lease_record(expected_revision, next)
                .await
        })
    }
}

async fn load_in_transaction(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    lease_key: &str,
) -> Result<Option<SecretLeaseRecord>, SecretLeaseStoreError> {
    let row = sqlx::query(
        "SELECT lease_key, provider_id, provider_path, request_sha256,
                provider_lease_id, state, revision, schema_version,
                record_json, record_sha256, updated_at_ms
         FROM secret_lease_records WHERE lease_key = ?",
    )
    .bind(lease_key)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(map_sqlx)?;
    row.map(|row| decode_record(&row)).transpose()
}

fn decode_record(row: &sqlx::sqlite::SqliteRow) -> Result<SecretLeaseRecord, SecretLeaseStoreError> {
    let payload_json: String = row.get("record_json");
    let expected_digest: String = row.get("record_sha256");
    let actual_digest = Sha256Digest::for_bytes(payload_json.as_bytes());
    if actual_digest.as_str() != expected_digest {
        return Err(SecretLeaseStoreError::Corrupt);
    }
    let record: SecretLeaseRecord =
        serde_json::from_str(&payload_json).map_err(|_| SecretLeaseStoreError::Corrupt)?;
    record.validate().map_err(|_| SecretLeaseStoreError::Corrupt)?;

    let revision: i64 = row.get("revision");
    let schema_version: i64 = row.get("schema_version");
    if row.get::<String, _>("lease_key") != record.lease_key
        || row.get::<String, _>("provider_id") != record.provider_id
        || row.get::<String, _>("provider_path") != record.provider_path
        || row.get::<String, _>("request_sha256") != record.request_sha256.as_str()
        || row.try_get::<Option<String>, _>("provider_lease_id").map_err(map_sqlx)?
            != record.provider_lease_id
        || row.get::<String, _>("state") != state_as_str(record.state)
        || u64::try_from(revision).ok() != Some(record.revision)
        || u32::try_from(schema_version).ok() != Some(record.schema_version)
    {
        return Err(SecretLeaseStoreError::Corrupt);
    }
    Ok(record)
}

fn encode_record(
    record: &SecretLeaseRecord,
) -> Result<(String, Sha256Digest), SecretLeaseStoreError> {
    let payload = canonical_json(record).map_err(map_evidence)?;
    let payload_json =
        String::from_utf8(payload).map_err(|_| SecretLeaseStoreError::Unavailable)?;
    let digest = Sha256Digest::for_bytes(payload_json.as_bytes());
    Ok((payload_json, digest))
}

fn state_as_str(state: SecretLeaseState) -> &'static str {
    match state {
        SecretLeaseState::Requesting => "requesting",
        SecretLeaseState::Active => "active",
        SecretLeaseState::Renewing => "renewing",
        SecretLeaseState::RevokePending => "revoke_pending",
        SecretLeaseState::Revoked => "revoked",
        SecretLeaseState::Expired => "expired",
        SecretLeaseState::Unknown => "unknown",
        SecretLeaseState::Rejected => "rejected",
    }
}

fn revision_i64(value: u64) -> Result<i64, SecretLeaseStoreError> {
    i64::try_from(value).map_err(|_| {
        SecretLeaseStoreError::InvalidRecord(SecretLeaseBindingError::InvalidRevision)
    })
}

fn map_sqlx(error: sqlx::Error) -> SecretLeaseStoreError {
    map_evidence(classify_sqlx_error(error))
}

fn map_evidence(error: EvidenceError) -> SecretLeaseStoreError {
    match error {
        EvidenceError::IdempotencyConflict { .. } => SecretLeaseStoreError::Conflict,
        EvidenceError::Corrupt(_) => SecretLeaseStoreError::Corrupt,
        EvidenceError::InvalidRecord(_) => SecretLeaseStoreError::Conflict,
        EvidenceError::Serialization(_) | EvidenceError::Unavailable(_) => {
            SecretLeaseStoreError::Unavailable
        }
    }
}
