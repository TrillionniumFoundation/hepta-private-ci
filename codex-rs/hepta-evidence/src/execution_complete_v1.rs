//! Complete, atomic, original-DB recovery for the **non-executing** P2a intent.
//!
//! These functions add no writer or database. The original Evidence SQLite
//! transaction persists the existing ProviderEffectIntent AND the complete
//! typed execution envelope, or neither. Digest-only orphan rows are rejected.
//! Reconstructing a request is not permission to execute it: this module has
//! no Final-use token, physical tool transport, send, retry, or success API.

use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteRow;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::execution_preparation_v1::ExecutionPreparationReadbackStatusV1;
use crate::execution_preparation_v1::ExecutionPreparationReadbackV1;
use crate::execution_preparation_v1::validate_preparation;
use crate::provider_effect_store::verify_effect_intent;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

const MAX_COMPLETE_ENVELOPE_BYTES: usize = 4096;

/// A typed immutable original, reconstructed from the Evidence database itself.
///
/// Neither possession of this structure nor a correct digest conveys an effect
/// capability, approval, original provider outcome or safe retry permission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecoveredExecutionPreparationV1 {
    pub intent: ExecutionIntentV1,
    pub readback: ExecutionPreparationReadbackV1,
}

fn serialize_complete_intent(intent: &ExecutionIntentV1) -> Result<String, EvidenceError> {
    let bytes = serde_json::to_vec(intent)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    if bytes.is_empty() || bytes.len() > MAX_COMPLETE_ENVELOPE_BYTES {
        return Err(EvidenceError::InvalidRecord(
            "execution original exceeds bounded SQLite envelope".to_owned(),
        ));
    }
    String::from_utf8(bytes).map_err(|error| EvidenceError::Serialization(error.to_string()))
}

/// Validate every row and column against the exact stored original effect
/// binding, including canonical field order and nonzero scope/generation.
fn decode_complete_row(
    row: &SqliteRow,
    original: &ProviderEffectIntent,
) -> Result<ExecutionIntentV1, EvidenceError> {
    let key: String = row.try_get("effect_key").map_err(classify_sqlx_error)?;
    let version: i64 = row.try_get("schema_version").map_err(classify_sqlx_error)?;
    let json: String = row.try_get("intent_json").map_err(classify_sqlx_error)?;
    let digest: String = row.try_get("intent_sha256").map_err(classify_sqlx_error)?;
    let request: Vec<u8> = row.try_get("request_sha256").map_err(classify_sqlx_error)?;
    let recorded_at: i64 = row.try_get("recorded_at_ms").map_err(classify_sqlx_error)?;
    if key != original.key.as_str()
        || version != 1
        || recorded_at <= 0
        || json.is_empty()
        || json.len() > MAX_COMPLETE_ENVELOPE_BYTES
        || digest != Sha256Digest::for_bytes(json.as_bytes()).as_str()
        || original.payload_sha256.as_str() != digest
    {
        return Err(EvidenceError::Corrupt(
            "execution complete intent fields failed original digest/readback".to_owned(),
        ));
    }
    let intent: ExecutionIntentV1 = serde_json::from_str(&json)
        .map_err(|error| EvidenceError::Corrupt(format!("execution envelope decode: {error}")))?;
    let prepared = validate_preparation(&intent)
        .map_err(|error| EvidenceError::Corrupt(format!("execution envelope binding: {error}")))?;
    let serialized = serialize_complete_intent(&intent)
        .map_err(|error| EvidenceError::Corrupt(format!("execution serialization: {error}")))?;
    if serialized != json
        || prepared.original != *original
        || request.as_slice() != prepared.request_sha256.as_slice()
    {
        return Err(EvidenceError::Corrupt(
            "execution complete envelope does not match original binding".to_owned(),
        ));
    }
    Ok(intent)
}

impl HeptaEvidenceStore {
    /// One ORIGINAL Evidence writer and one SQLite BEGIN IMMEDIATE for both
    /// the existing provider-effect intent and the full recoverable control
    /// envelope. No physical tool, no final-use grant, no ACK or replay.
    ///
    /// A digest-only preexisting intent without a complete row fails closed
    /// instead of being laundered into a new complete/executable occurrence.
    pub(crate) async fn append_complete_execution_preparation_v1(
        &self,
        intent: &ExecutionIntentV1,
    ) -> Result<AppendDisposition, EvidenceError> {
        let prepared = validate_preparation(intent)?;
        let json = serialize_complete_intent(intent)?;
        let canonical = canonical_json(&prepared.original)?;
        let original_json = String::from_utf8(canonical.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let original_record_sha256 = Sha256Digest::for_bytes(&canonical);
        let complete_sha256 = Sha256Digest::for_bytes(json.as_bytes());
        if prepared.original.payload_sha256 != complete_sha256 {
            return Err(EvidenceError::InvalidRecord(
                "prepared envelope digest differs from complete original".to_owned(),
            ));
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let insert = sqlx::query(
            "INSERT INTO provider_effect_intents (
                effect_key, payload_sha256, schema_version, payload_json,
                record_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(prepared.original.key.as_str())
        .bind(prepared.original.payload_sha256.as_str())
        .bind(i64::from(prepared.original.schema_version))
        .bind(&original_json)
        .bind(original_record_sha256.as_str())
        .bind(now_millis()?)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let disposition = verify_effect_intent(
            &mut transaction,
            &prepared.original,
            &original_json,
            original_record_sha256.as_str(),
            insert.rows_affected() == 1,
        )
        .await?;
        let existing = sqlx::query(
            "SELECT effect_key, schema_version, intent_json, intent_sha256,
                    request_sha256, recorded_at_ms
             FROM execution_prepared_envelopes WHERE effect_key = ?",
        )
        .bind(prepared.original.key.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        match (disposition, existing) {
            (AppendDisposition::Inserted, None) => {
                sqlx::query(
                    "INSERT INTO execution_prepared_envelopes (
                        effect_key, schema_version, intent_json, intent_sha256,
                        request_sha256, recorded_at_ms
                     ) VALUES (?, 1, ?, ?, ?, ?)",
                )
                .bind(prepared.original.key.as_str())
                .bind(&json)
                .bind(complete_sha256.as_str())
                .bind(prepared.request_sha256.as_slice())
                .bind(now_millis()?)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
            }
            (AppendDisposition::AlreadyPresent, Some(row)) => {
                let recovered = decode_complete_row(&row, &prepared.original)?;
                if recovered != *intent {
                    return Err(EvidenceError::IdempotencyConflict {
                        record_id: prepared.original.key.as_str().to_owned(),
                    });
                }
            }
            _ => {
                return Err(EvidenceError::Corrupt(
                    "digest-only or mismatched execution preparation is not recoverable".to_owned(),
                ));
            }
        }
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(disposition)
    }

    /// Recover the complete exact typed intent solely by its ORIGINAL durable
    /// operation key, without caller-supplied request or physical payload.
    /// All status fields are read-only observations, never execution grants.
    pub async fn recover_execution_preparation_by_key_v1(
        &self,
        key: &ProviderEffectKey,
    ) -> Result<Option<RecoveredExecutionPreparationV1>, EvidenceError> {
        let original = self.get_provider_effect(key).await?;
        let row = sqlx::query(
            "SELECT effect_key, schema_version, intent_json, intent_sha256,
                    request_sha256, recorded_at_ms
             FROM execution_prepared_envelopes WHERE effect_key = ?",
        )
        .bind(key.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        let (original, row) = match (original, row) {
            (None, None) => return Ok(None),
            (Some(original), Some(row)) => (original, row),
            _ => {
                return Err(EvidenceError::Corrupt(
                    "execution complete envelope and original intent are not atomic".to_owned(),
                ));
            }
        };
        let intent = decode_complete_row(&row, &original.intent.intent)?;
        let prepared = validate_preparation(&intent)?;
        let status = if original.acknowledgements.is_empty()
            && original.uncertainties.is_empty()
        {
            ExecutionPreparationReadbackStatusV1::RecordedOnly
        } else {
            ExecutionPreparationReadbackStatusV1::OriginalOwnerReconciliationRequired
        };
        Ok(Some(RecoveredExecutionPreparationV1 {
            intent,
            readback: ExecutionPreparationReadbackV1 {
                provider_effect_key: prepared.original.key,
                request_sha256: prepared.request_sha256,
                stored_envelope_sha256: prepared.original.payload_sha256,
                status,
            },
        }))
    }
}

/// On every Evidence reopen, verify all complete-envelope rows and their
/// original provider-effect digests. A local hash is still not an independent
/// anti-rollback oracle or a signed effect outcome.
pub(crate) async fn verify_execution_prepared_rows(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let rows = sqlx::query(
        "SELECT e.effect_key, e.schema_version, e.intent_json,
                e.intent_sha256, e.request_sha256, e.recorded_at_ms,
                p.payload_json AS original_payload_json,
                p.record_sha256 AS original_record_sha256
         FROM execution_prepared_envelopes AS e
         JOIN provider_effect_intents AS p ON e.effect_key = p.effect_key
         ORDER BY e.effect_key",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let expected_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM execution_prepared_envelopes",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if i64::try_from(rows.len()).ok() != Some(expected_count) {
        return Err(EvidenceError::Corrupt(
            "orphan complete execution envelope escaped original foreign key".to_owned(),
        ));
    }
    for row in &rows {
        let original_json: String = row.try_get("original_payload_json")
            .map_err(classify_sqlx_error)?;
        let sha: String = row.try_get("original_record_sha256").map_err(classify_sqlx_error)?;
        if sha != Sha256Digest::for_bytes(original_json.as_bytes()).as_str() {
            return Err(EvidenceError::Corrupt(
                "original execution effect row was tampered".to_owned(),
            ));
        }
        let original: ProviderEffectIntent = serde_json::from_str(&original_json)
            .map_err(|error| EvidenceError::Corrupt(format!("effect decode: {error}")))?;
        original.validate().map_err(|error| {
            EvidenceError::Corrupt(format!("effect original validation: {error:?}"))
        })?;
        decode_complete_row(row, &original)?;
    }
    Ok(())
}
