use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::provider_insert::insert_provider_intent;
use crate::provider_record::decode_provider_intent_row;
use crate::provider_record::decode_provider_receipt_row;
use crate::provider_record::validate_provider_intent;
use crate::schema_validation::classify_sqlx_error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderBindingState {
    Pending,
    Completed,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderIntentClaimDisposition {
    Inserted,
    ExactReplay,
    BlockedByBinding(ProviderBindingState),
}

impl HeptaEvidenceStore {
    /// Atomically claims one enforce-mode provider attempt.
    ///
    /// A host logical-request binding with a pending, completed, or
    /// indeterminate attempt cannot be sent again, even if a retry changes
    /// transport or incremental wire encoding. Rejected and
    /// provably-not-dispatched attempts do not prevent a fresh physical send.
    /// The binding check and insert share one `BEGIN IMMEDIATE` transaction,
    /// so concurrent pools cannot both win.
    pub async fn claim_provider_intent(
        &self,
        intent: &ProviderInvocationIntent,
    ) -> Result<ProviderIntentClaimDisposition, EvidenceError> {
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
        if let Some(state) = blocking_provider_binding_state(&mut transaction, intent).await? {
            transaction.commit().await.map_err(classify_sqlx_error)?;
            return Ok(ProviderIntentClaimDisposition::BlockedByBinding(state));
        }
        let inserted = insert_provider_intent(
            &mut transaction,
            intent,
            &payload_json,
            payload_sha256.as_str(),
        )
        .await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(if inserted == AppendDisposition::Inserted {
            ProviderIntentClaimDisposition::Inserted
        } else {
            ProviderIntentClaimDisposition::ExactReplay
        })
    }
}

async fn blocking_provider_binding_state(
    transaction: &mut Transaction<'_, Sqlite>,
    requested: &ProviderInvocationIntent,
) -> Result<Option<ProviderBindingState>, EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, attempt_id, request_binding_id, attempt_nonce_sha256,
                host_request_binding_id_sha256, thread_id, turn_id,
                request_kind, provider_id, provider_config_sha256, model, transport,
                endpoint_sha256, logical_request_sha256, wire_semantic_sha256,
                ephemeral_input_sha256, ephemeral_input_witness_sha256,
                previous_response_id_sha256, generate, schema_version,
                payload_json, payload_sha256
         FROM provider_invocation_intents
         WHERE host_request_binding_id_sha256 = ? AND attempt_id <> ?
         ORDER BY seq ASC",
    )
    .bind(requested.binding.host_request_binding_id_sha256.as_str())
    .bind(requested.attempt_id.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    for row in rows {
        let existing = decode_provider_intent_row(&row)?;
        let terminal_row = sqlx::query(
            "SELECT seq, receipt_id, attempt_id, request_binding_id, thread_id, turn_id,
                    terminal_kind, schema_version, payload_json, payload_sha256
             FROM provider_invocation_terminals WHERE attempt_id = ?",
        )
        .bind(existing.attempt_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let Some(terminal_row) = terminal_row else {
            return Ok(Some(ProviderBindingState::Pending));
        };
        let receipt = decode_provider_receipt_row(&terminal_row)?;
        if receipt.intent != existing {
            return Err(EvidenceError::Corrupt(
                "provider binding terminal differs from its authoritative intent".to_string(),
            ));
        }
        match receipt.terminal {
            ProviderTerminal::Completed { .. } | ProviderTerminal::CompletedUnary { .. } => {
                return Ok(Some(ProviderBindingState::Completed));
            }
            ProviderTerminal::Indeterminate { .. } => {
                return Ok(Some(ProviderBindingState::Indeterminate));
            }
            ProviderTerminal::Rejected { .. } | ProviderTerminal::NotDispatched { .. } => {}
        }
    }
    Ok(None)
}
