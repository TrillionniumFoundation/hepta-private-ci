use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::provider_record::verify_provider_intent;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

pub(crate) async fn insert_provider_intent(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &ProviderInvocationIntent,
    payload_json: &str,
    payload_sha256: &str,
) -> Result<AppendDisposition, EvidenceError> {
    let binding = &intent.binding;
    let insert = sqlx::query(
        "INSERT INTO provider_invocation_intents (
            attempt_id, request_binding_id, attempt_nonce_sha256,
            host_request_binding_id_sha256, thread_id, turn_id,
            request_kind, provider_id, provider_config_sha256, model, transport,
            endpoint_sha256, logical_request_sha256, wire_semantic_sha256,
            ephemeral_input_sha256, ephemeral_input_witness_sha256,
            previous_response_id_sha256, generate, schema_version,
            payload_json, payload_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT DO NOTHING",
    )
    .bind(intent.attempt_id.as_str())
    .bind(intent.request_binding_id.as_str())
    .bind(intent.attempt_nonce_sha256.as_str())
    .bind(binding.host_request_binding_id_sha256.as_str())
    .bind(&binding.thread_id)
    .bind(&binding.turn_id)
    .bind(binding.request_kind.as_str())
    .bind(&binding.provider_id)
    .bind(binding.provider_config_sha256.as_str())
    .bind(&binding.model)
    .bind(binding.transport.as_str())
    .bind(binding.endpoint_sha256.as_str())
    .bind(binding.logical_request_sha256.as_str())
    .bind(binding.wire_semantic_sha256.as_str())
    .bind(
        binding
            .ephemeral_input_sha256
            .as_ref()
            .map(Sha256Digest::as_str),
    )
    .bind(
        binding
            .ephemeral_input_witness_sha256
            .as_ref()
            .map(Sha256Digest::as_str),
    )
    .bind(
        binding
            .previous_response_id_sha256
            .as_ref()
            .map(Sha256Digest::as_str),
    )
    .bind(binding.generate)
    .bind(i64::from(PROVIDER_EVIDENCE_SCHEMA_VERSION))
    .bind(payload_json)
    .bind(payload_sha256)
    .bind(now_millis()?)
    .execute(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    verify_provider_intent(
        transaction,
        intent,
        payload_json,
        payload_sha256,
        insert.rows_affected() == 1,
    )
    .await
}
