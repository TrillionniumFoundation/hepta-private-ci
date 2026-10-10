use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderAttemptId;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderReceiptId;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::RequestBindingId;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::canonical::canonical_json;
use crate::schema_validation::classify_sqlx_error;

pub(crate) async fn ensure_provider_intent(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &ProviderInvocationIntent,
) -> Result<(), EvidenceError> {
    let payload = canonical_json(intent)?;
    let payload_json = String::from_utf8(payload.clone())
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(&payload);
    verify_provider_intent(
        transaction,
        intent,
        &payload_json,
        digest.as_str(),
        /*inserted*/ false,
    )
    .await
    .map(|_| ())
}

pub(crate) async fn verify_provider_intent(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &ProviderInvocationIntent,
    payload_json: &str,
    payload_sha256: &str,
    inserted: bool,
) -> Result<AppendDisposition, EvidenceError> {
    let rows = sqlx::query(
        "SELECT attempt_id, request_binding_id, attempt_nonce_sha256,
                host_request_binding_id_sha256, thread_id, turn_id,
                request_kind, provider_id, provider_config_sha256, model, transport,
                endpoint_sha256, logical_request_sha256, wire_semantic_sha256,
                ephemeral_input_sha256, ephemeral_input_witness_sha256,
                previous_response_id_sha256, generate, schema_version,
                payload_json, payload_sha256
         FROM provider_invocation_intents WHERE attempt_id = ?",
    )
    .bind(intent.attempt_id.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() != 1 {
        return Err(EvidenceError::Corrupt(format!(
            "expected one provider intent row for {} but found {}",
            intent.attempt_id.as_str(),
            rows.len()
        )));
    }
    let row = &rows[0];
    let stored = decode_provider_intent_row(row)?;
    let exact = row.get::<String, _>("attempt_id") == intent.attempt_id.as_str()
        && row.get::<String, _>("request_binding_id") == intent.request_binding_id.as_str()
        && row.get::<String, _>("payload_json") == payload_json
        && row.get::<String, _>("payload_sha256") == payload_sha256
        && stored == *intent;
    if !exact {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: intent.attempt_id.as_str().to_string(),
        });
    }
    Ok(if inserted {
        AppendDisposition::Inserted
    } else {
        AppendDisposition::AlreadyPresent
    })
}

pub(crate) async fn verify_provider_receipt(
    transaction: &mut Transaction<'_, Sqlite>,
    receipt: &ProviderInvocationReceipt,
    payload_json: &str,
    payload_sha256: &str,
    inserted: bool,
) -> Result<AppendDisposition, EvidenceError> {
    let rows = sqlx::query(
        "SELECT receipt_id, attempt_id, request_binding_id, thread_id, turn_id,
                terminal_kind, schema_version, payload_json, payload_sha256
         FROM provider_invocation_terminals
         WHERE receipt_id = ? OR attempt_id = ?",
    )
    .bind(receipt.receipt_id.as_str())
    .bind(receipt.attempt_id.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() != 1 {
        return Err(EvidenceError::Corrupt(format!(
            "expected one provider terminal row for {} but found {}",
            receipt.receipt_id.as_str(),
            rows.len()
        )));
    }
    let row = &rows[0];
    let stored = decode_provider_receipt_row(row)?;
    let exact = row.get::<String, _>("receipt_id") == receipt.receipt_id.as_str()
        && row.get::<String, _>("attempt_id") == receipt.attempt_id.as_str()
        && row.get::<String, _>("request_binding_id") == receipt.request_binding_id.as_str()
        && row.get::<String, _>("payload_json") == payload_json
        && row.get::<String, _>("payload_sha256") == payload_sha256
        && stored == *receipt;
    if !exact {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: receipt.receipt_id.as_str().to_string(),
        });
    }
    Ok(if inserted {
        AppendDisposition::Inserted
    } else {
        AppendDisposition::AlreadyPresent
    })
}

pub(crate) fn decode_provider_intent_row(
    row: &SqliteRow,
) -> Result<ProviderInvocationIntent, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    verify_stored_digest(&payload_json, row.get("payload_sha256"), "provider intent")?;
    let intent: ProviderInvocationIntent = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    validate_provider_intent(&intent).map_err(invalid_as_corrupt)?;
    verify_canonical_payload(&intent, &payload_json, "provider intent")?;
    let binding = &intent.binding;
    if row.get::<String, _>("attempt_id") != intent.attempt_id.as_str()
        || row.get::<String, _>("request_binding_id") != intent.request_binding_id.as_str()
        || row.get::<String, _>("attempt_nonce_sha256") != intent.attempt_nonce_sha256.as_str()
        || row
            .get::<Option<String>, _>("host_request_binding_id_sha256")
            .as_deref()
            != Some(binding.host_request_binding_id_sha256.as_str())
        || row.get::<String, _>("thread_id") != binding.thread_id
        || row.get::<String, _>("turn_id") != binding.turn_id
        || row.get::<String, _>("request_kind") != binding.request_kind.as_str()
        || row.get::<String, _>("provider_id") != binding.provider_id
        || row.get::<String, _>("provider_config_sha256") != binding.provider_config_sha256.as_str()
        || row.get::<String, _>("model") != binding.model
        || row.get::<String, _>("transport") != binding.transport.as_str()
        || row.get::<String, _>("endpoint_sha256") != binding.endpoint_sha256.as_str()
        || row.get::<String, _>("logical_request_sha256") != binding.logical_request_sha256.as_str()
        || row.get::<String, _>("wire_semantic_sha256") != binding.wire_semantic_sha256.as_str()
        || row
            .get::<Option<String>, _>("ephemeral_input_sha256")
            .as_deref()
            != binding
                .ephemeral_input_sha256
                .as_ref()
                .map(Sha256Digest::as_str)
        || row
            .get::<Option<String>, _>("ephemeral_input_witness_sha256")
            .as_deref()
            != binding
                .ephemeral_input_witness_sha256
                .as_ref()
                .map(Sha256Digest::as_str)
        || row
            .get::<Option<String>, _>("previous_response_id_sha256")
            .as_deref()
            != binding
                .previous_response_id_sha256
                .as_ref()
                .map(Sha256Digest::as_str)
        || row.get::<bool, _>("generate") != binding.generate
        || row.get::<i64, _>("schema_version") != i64::from(intent.schema_version)
    {
        return Err(EvidenceError::Corrupt(
            "provider intent columns do not match canonical payload".to_string(),
        ));
    }
    Ok(intent)
}

pub(crate) fn decode_provider_receipt_row(
    row: &SqliteRow,
) -> Result<ProviderInvocationReceipt, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    verify_stored_digest(
        &payload_json,
        row.get("payload_sha256"),
        "provider terminal",
    )?;
    let receipt: ProviderInvocationReceipt = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    validate_provider_receipt(&receipt).map_err(invalid_as_corrupt)?;
    verify_canonical_payload(&receipt, &payload_json, "provider terminal")?;
    if row.get::<String, _>("receipt_id") != receipt.receipt_id.as_str()
        || row.get::<String, _>("attempt_id") != receipt.attempt_id.as_str()
        || row.get::<String, _>("request_binding_id") != receipt.request_binding_id.as_str()
        || row.get::<String, _>("thread_id") != receipt.intent.binding.thread_id
        || row.get::<String, _>("turn_id") != receipt.intent.binding.turn_id
        || row.get::<String, _>("terminal_kind") != receipt.terminal.kind()
        || row.get::<i64, _>("schema_version") != i64::from(receipt.schema_version)
    {
        return Err(EvidenceError::Corrupt(
            "provider terminal columns do not match canonical payload".to_string(),
        ));
    }
    Ok(receipt)
}

pub(crate) fn validate_provider_intent(
    intent: &ProviderInvocationIntent,
) -> Result<(), EvidenceError> {
    if intent.schema_version != PROVIDER_EVIDENCE_SCHEMA_VERSION
        || intent.binding.schema_version != PROVIDER_EVIDENCE_SCHEMA_VERSION
    {
        return invalid("unsupported provider evidence schema version");
    }
    for (label, value) in [
        ("attempt nonce digest", intent.attempt_nonce_sha256.as_str()),
        ("thread id", intent.binding.thread_id.as_str()),
        ("turn id", intent.binding.turn_id.as_str()),
        ("provider id", intent.binding.provider_id.as_str()),
        ("model", intent.binding.model.as_str()),
    ] {
        if value.trim().is_empty() {
            return invalid(format!("provider intent requires a non-empty {label}"));
        }
    }
    match (
        intent.binding.ephemeral_input_sha256.as_ref(),
        intent.binding.ephemeral_input_witness_sha256.as_ref(),
    ) {
        (Some(input), Some(witness)) => {
            validate_digest("ephemeral input", input)?;
            validate_digest("ephemeral input witness", witness)?;
        }
        (None, None) => {}
        _ => {
            return invalid(
                "provider intent requires both ephemeral input and witness digests or neither",
            );
        }
    }
    let expected_binding = RequestBindingId::for_request(&intent.binding);
    if intent.request_binding_id != expected_binding {
        return invalid("request binding id does not bind provider request semantics");
    }
    let expected_attempt =
        ProviderAttemptId::for_send(&intent.request_binding_id, &intent.attempt_nonce_sha256);
    if intent.attempt_id != expected_attempt {
        return invalid("provider attempt id does not bind request and send nonce");
    }
    for (label, digest) in [
        ("attempt nonce", &intent.attempt_nonce_sha256),
        (
            "host request binding id",
            &intent.binding.host_request_binding_id_sha256,
        ),
        ("provider config", &intent.binding.provider_config_sha256),
        ("endpoint", &intent.binding.endpoint_sha256),
        ("logical request", &intent.binding.logical_request_sha256),
        ("wire semantic", &intent.binding.wire_semantic_sha256),
    ] {
        validate_digest(label, digest)?;
    }
    if let Some(digest) = intent.binding.previous_response_id_sha256.as_ref() {
        validate_digest("previous response id", digest)?;
    }
    Ok(())
}

pub(crate) fn validate_provider_receipt(
    receipt: &ProviderInvocationReceipt,
) -> Result<(), EvidenceError> {
    validate_provider_intent(&receipt.intent)?;
    if receipt.schema_version != PROVIDER_EVIDENCE_SCHEMA_VERSION {
        return invalid("unsupported provider terminal schema version");
    }
    if receipt.attempt_id != receipt.intent.attempt_id
        || receipt.request_binding_id != receipt.intent.request_binding_id
    {
        return invalid("provider terminal does not bind its exact intent");
    }
    if receipt.receipt_id != ProviderReceiptId::for_attempt(&receipt.attempt_id) {
        return invalid("provider receipt id does not bind its attempt id");
    }
    match &receipt.terminal {
        ProviderTerminal::Completed {
            response_id_sha256,
            response_items_sha256,
            token_usage_sha256,
            ..
        } => {
            validate_digest("response id", response_id_sha256)?;
            validate_digest("response items", response_items_sha256)?;
            validate_digest("token usage", token_usage_sha256)?;
        }
        ProviderTerminal::CompletedUnary {
            response_items_sha256,
        } => validate_digest("response items", response_items_sha256)?,
        ProviderTerminal::Rejected { reason_code }
        | ProviderTerminal::NotDispatched { reason_code }
        | ProviderTerminal::Indeterminate { reason_code, .. } => {
            if reason_code.trim().is_empty() {
                return invalid("provider terminal requires a non-empty reason code");
            }
            if let ProviderTerminal::Indeterminate {
                partial_response_sha256: Some(digest),
                ..
            } = &receipt.terminal
            {
                validate_digest("partial response", digest)?;
            }
        }
    }
    Ok(())
}

fn validate_digest(label: &str, digest: &Sha256Digest) -> Result<(), EvidenceError> {
    if is_canonical_sha256(digest.as_str()) {
        Ok(())
    } else {
        invalid(format!("{label} digest is not canonical lowercase SHA-256"))
    }
}

fn verify_stored_digest(
    payload_json: &str,
    expected: &str,
    record_kind: &str,
) -> Result<(), EvidenceError> {
    let actual = Sha256Digest::for_bytes(payload_json.as_bytes());
    if actual.as_str() == expected {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(format!(
            "stored {record_kind} payload digest mismatch"
        )))
    }
}

fn verify_canonical_payload<T: serde::Serialize>(
    value: &T,
    stored: &str,
    record_kind: &str,
) -> Result<(), EvidenceError> {
    let canonical = canonical_json(value)?;
    if canonical == stored.as_bytes() {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(format!(
            "stored {record_kind} JSON is not canonical"
        )))
    }
}

fn invalid_as_corrupt(error: EvidenceError) -> EvidenceError {
    match error {
        EvidenceError::InvalidRecord(detail) => EvidenceError::Corrupt(detail),
        other => other,
    }
}

fn is_canonical_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn invalid<T>(detail: impl Into<String>) -> Result<T, EvidenceError> {
    Err(EvidenceError::InvalidRecord(detail.into()))
}
