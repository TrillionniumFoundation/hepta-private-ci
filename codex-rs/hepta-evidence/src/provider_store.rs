use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderAttemptId;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderReceiptId;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::provider_insert::insert_provider_intent;
use crate::provider_record::decode_provider_intent_row;
use crate::provider_record::decode_provider_receipt_row;
use crate::provider_record::ensure_provider_intent;
use crate::provider_record::validate_provider_intent;
use crate::provider_record::validate_provider_receipt;
use crate::provider_record::verify_provider_receipt;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredProviderIntent {
    pub seq: i64,
    pub intent: ProviderInvocationIntent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredProviderReceipt {
    pub seq: i64,
    pub receipt: ProviderInvocationReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredProviderAttemptEvidence {
    pub intent: StoredProviderIntent,
    pub receipt: Option<StoredProviderReceipt>,
}

impl HeptaEvidenceStore {
    pub async fn append_provider_intent(
        &self,
        intent: &ProviderInvocationIntent,
    ) -> Result<AppendDisposition, EvidenceError> {
        validate_provider_intent(intent)?;
        let payload = canonical_json(intent)?;
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let payload_sha256 = Sha256Digest::for_bytes(&payload);
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let disposition = insert_provider_intent(
            &mut transaction,
            intent,
            &payload_json,
            payload_sha256.as_str(),
        )
        .await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(disposition)
    }

    pub async fn append_provider_receipt(
        &self,
        receipt: &ProviderInvocationReceipt,
    ) -> Result<AppendDisposition, EvidenceError> {
        validate_provider_receipt(receipt)?;
        let payload = canonical_json(receipt)?;
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let payload_sha256 = Sha256Digest::for_bytes(&payload);
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        ensure_provider_intent(&mut transaction, &receipt.intent).await?;
        let insert = sqlx::query(
            "INSERT INTO provider_invocation_terminals (
                receipt_id, attempt_id, request_binding_id, thread_id, turn_id,
                terminal_kind, schema_version, payload_json, payload_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(receipt.receipt_id.as_str())
        .bind(receipt.attempt_id.as_str())
        .bind(receipt.request_binding_id.as_str())
        .bind(&receipt.intent.binding.thread_id)
        .bind(&receipt.intent.binding.turn_id)
        .bind(receipt.terminal.kind())
        .bind(i64::from(PROVIDER_EVIDENCE_SCHEMA_VERSION))
        .bind(&payload_json)
        .bind(payload_sha256.as_str())
        .bind(now_millis()?)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let disposition = verify_provider_receipt(
            &mut transaction,
            receipt,
            &payload_json,
            payload_sha256.as_str(),
            insert.rows_affected() == 1,
        )
        .await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(disposition)
    }

    pub async fn get_provider_attempt(
        &self,
        attempt_id: &ProviderAttemptId,
    ) -> Result<Option<StoredProviderAttemptEvidence>, EvidenceError> {
        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let evidence = load_provider_attempt_in_transaction(&mut transaction, attempt_id).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(evidence)
    }

    pub async fn get_provider_receipt(
        &self,
        receipt_id: &ProviderReceiptId,
    ) -> Result<Option<StoredProviderReceipt>, EvidenceError> {
        let row = sqlx::query(
            "SELECT seq, receipt_id, attempt_id, request_binding_id, thread_id, turn_id,
                    terminal_kind, schema_version, payload_json, payload_sha256
             FROM provider_invocation_terminals WHERE receipt_id = ?",
        )
        .bind(receipt_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let receipt = decode_provider_receipt_row(&row)?;
        let authoritative = self
            .load_provider_intent(&receipt.attempt_id)
            .await?
            .ok_or_else(|| {
                EvidenceError::Corrupt("provider terminal references a missing intent".to_string())
            })?;
        if authoritative.intent != receipt.intent {
            return Err(EvidenceError::Corrupt(
                "provider terminal intent differs from authoritative intent row".to_string(),
            ));
        }
        Ok(Some(StoredProviderReceipt {
            seq: row.get("seq"),
            receipt,
        }))
    }

    pub async fn list_pending_provider_intents(
        &self,
        thread_id: &str,
        after_seq: i64,
        limit: u32,
    ) -> Result<Vec<StoredProviderIntent>, EvidenceError> {
        if thread_id.trim().is_empty() {
            return Err(EvidenceError::InvalidRecord(
                "pending provider query requires a thread id".to_string(),
            ));
        }
        if !(1..=1_000).contains(&limit) {
            return Err(EvidenceError::InvalidRecord(
                "pending provider query limit must be between 1 and 1000".to_string(),
            ));
        }
        let rows = sqlx::query(
            "SELECT intents.seq, intents.attempt_id, intents.request_binding_id,
                    intents.attempt_nonce_sha256, intents.host_request_binding_id_sha256,
                    intents.thread_id, intents.turn_id,
                    intents.request_kind, intents.provider_id,
                    intents.provider_config_sha256, intents.model, intents.transport,
                    intents.endpoint_sha256, intents.logical_request_sha256,
                    intents.wire_semantic_sha256, intents.ephemeral_input_sha256,
                    intents.ephemeral_input_witness_sha256,
                    intents.previous_response_id_sha256,
                    intents.generate, intents.schema_version,
                    intents.payload_json, intents.payload_sha256
             FROM provider_invocation_intents AS intents
             LEFT JOIN provider_invocation_terminals AS terminals
               ON terminals.attempt_id = intents.attempt_id
             WHERE intents.thread_id = ? AND intents.seq > ? AND terminals.attempt_id IS NULL
             ORDER BY intents.seq ASC LIMIT ?",
        )
        .bind(thread_id)
        .bind(after_seq)
        .bind(i64::from(limit))
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        rows.into_iter()
            .map(|row| {
                let seq = row.get("seq");
                decode_provider_intent_row(&row).map(|intent| StoredProviderIntent { seq, intent })
            })
            .collect()
    }

    pub async fn pending_provider_attempt_count(&self) -> Result<i64, EvidenceError> {
        sqlx::query_scalar(
            "SELECT COUNT(*)
             FROM provider_invocation_intents AS intents
             LEFT JOIN provider_invocation_terminals AS terminals
               ON terminals.attempt_id = intents.attempt_id
             WHERE terminals.attempt_id IS NULL",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(classify_sqlx_error)
    }

    async fn load_provider_intent(
        &self,
        attempt_id: &ProviderAttemptId,
    ) -> Result<Option<StoredProviderIntent>, EvidenceError> {
        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let intent = load_provider_intent_in_transaction(&mut transaction, attempt_id).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(intent)
    }
}

async fn load_provider_intent_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    attempt_id: &ProviderAttemptId,
) -> Result<Option<StoredProviderIntent>, EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, attempt_id, request_binding_id, attempt_nonce_sha256,
                host_request_binding_id_sha256, thread_id, turn_id,
                request_kind, provider_id, provider_config_sha256, model, transport,
                endpoint_sha256, logical_request_sha256, wire_semantic_sha256,
                ephemeral_input_sha256, ephemeral_input_witness_sha256,
                previous_response_id_sha256, generate, schema_version,
                payload_json, payload_sha256
         FROM provider_invocation_intents WHERE attempt_id = ?",
    )
    .bind(attempt_id.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() > 1 {
        return Err(EvidenceError::Corrupt(
            "multiple provider intents exist for one attempt".to_string(),
        ));
    }
    rows.into_iter()
        .next()
        .map(|row| {
            let seq = row.get("seq");
            decode_provider_intent_row(&row).map(|intent| StoredProviderIntent { seq, intent })
        })
        .transpose()
}

pub(crate) async fn load_provider_attempt_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    attempt_id: &ProviderAttemptId,
) -> Result<Option<StoredProviderAttemptEvidence>, EvidenceError> {
    let intent = load_provider_intent_in_transaction(transaction, attempt_id).await?;
    let receipt_rows = sqlx::query(
        "SELECT seq, receipt_id, attempt_id, request_binding_id, thread_id, turn_id,
                terminal_kind, schema_version, payload_json, payload_sha256
         FROM provider_invocation_terminals WHERE attempt_id = ?",
    )
    .bind(attempt_id.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if receipt_rows.len() > 1 {
        return Err(EvidenceError::Corrupt(
            "multiple provider terminals exist for one attempt".to_string(),
        ));
    }
    let receipt = receipt_rows
        .into_iter()
        .next()
        .map(|row| {
            let seq = row.get("seq");
            decode_provider_receipt_row(&row).map(|receipt| StoredProviderReceipt { seq, receipt })
        })
        .transpose()?;
    let Some(intent) = intent else {
        return if receipt.is_some() {
            Err(EvidenceError::Corrupt(
                "provider terminal exists without an authoritative intent".to_string(),
            ))
        } else {
            Ok(None)
        };
    };
    if receipt
        .as_ref()
        .is_some_and(|stored| stored.receipt.intent != intent.intent)
    {
        return Err(EvidenceError::Corrupt(
            "provider terminal intent differs from authoritative intent row".to_string(),
        ));
    }
    Ok(Some(StoredProviderAttemptEvidence { intent, receipt }))
}
