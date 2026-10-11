use codex_hepta_contracts::GOVERNANCE_SCHEMA_VERSION;
use codex_hepta_contracts::GovernanceDecisionRecord;
use codex_hepta_contracts::GovernanceReceipt;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::canonical::canonical_json;
use crate::governance_validation::validate_decision;
use crate::governance_validation::validate_receipt_binding;
use crate::schema_validation::classify_sqlx_error;

pub(crate) async fn ensure_decision(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &GovernanceDecisionRecord,
) -> Result<(), EvidenceError> {
    let payload = canonical_json(record)?;
    let payload_json = String::from_utf8(payload.clone())
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(&payload);
    verify_decision(
        transaction,
        record,
        &payload_json,
        digest.as_str(),
        /*inserted*/ false,
    )
    .await
    .map(|_| ())
}

pub(crate) async fn verify_decision(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &GovernanceDecisionRecord,
    payload_json: &str,
    payload_sha256: &str,
    inserted: bool,
) -> Result<AppendDisposition, EvidenceError> {
    let rows = sqlx::query(
        "SELECT decision_id, action_id, thread_id, turn_id, call_id, phase,
                schema_version, payload_json, payload_sha256
         FROM governance_decisions
         WHERE decision_id = ? OR (action_id = ? AND phase = ?)",
    )
    .bind(record.decision_id.as_str())
    .bind(record.action.action_id.as_str())
    .bind(record.phase.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() != 1 {
        return Err(EvidenceError::Corrupt(format!(
            "expected one decision row for {} but found {}",
            record.decision_id.as_str(),
            rows.len()
        )));
    }
    let row = &rows[0];
    let stored = decode_decision_row(row)?;
    let exact = row.get::<String, _>("decision_id") == record.decision_id.as_str()
        && row.get::<String, _>("action_id") == record.action.action_id.as_str()
        && row.get::<String, _>("phase") == record.phase.as_str()
        && row.get::<String, _>("payload_json") == payload_json
        && row.get::<String, _>("payload_sha256") == payload_sha256
        && stored == *record;
    if !exact {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: record.decision_id.as_str().to_string(),
        });
    }
    Ok(if inserted {
        AppendDisposition::Inserted
    } else {
        AppendDisposition::AlreadyPresent
    })
}

pub(crate) async fn verify_receipt(
    transaction: &mut Transaction<'_, Sqlite>,
    receipt: &GovernanceReceipt,
    payload_json: &str,
    payload_sha256: &str,
    inserted: bool,
) -> Result<AppendDisposition, EvidenceError> {
    let rows = sqlx::query(
        "SELECT receipt_id, action_id, thread_id, turn_id, call_id,
                admission_decision_id, admission_phase,
                authorization_decision_id, authorization_phase,
                schema_version, payload_json, payload_sha256
         FROM governance_receipts
         WHERE receipt_id = ? OR action_id = ?",
    )
    .bind(receipt.receipt_id.as_str())
    .bind(receipt.action_id.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() != 1 {
        return Err(EvidenceError::Corrupt(format!(
            "expected one receipt row for {} but found {}",
            receipt.receipt_id.as_str(),
            rows.len()
        )));
    }
    let row = &rows[0];
    let stored = decode_receipt_row(row)?;
    let exact = row.get::<String, _>("receipt_id") == receipt.receipt_id.as_str()
        && row.get::<String, _>("action_id") == receipt.action_id.as_str()
        && row.get::<String, _>("admission_decision_id") == receipt.admission.decision_id.as_str()
        && row.get::<String, _>("admission_phase") == receipt.admission.phase.as_str()
        && row
            .get::<Option<String>, _>("authorization_decision_id")
            .as_deref()
            == receipt
                .authorization
                .as_ref()
                .map(|record| record.decision_id.as_str())
        && row
            .get::<Option<String>, _>("authorization_phase")
            .as_deref()
            == receipt
                .authorization
                .as_ref()
                .map(|record| record.phase.as_str())
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

fn verify_stored_digest(payload_json: &str, expected: &str) -> Result<(), EvidenceError> {
    let actual = Sha256Digest::for_bytes(payload_json.as_bytes());
    if actual.as_str() == expected {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(
            "stored governance payload digest mismatch".to_string(),
        ))
    }
}

pub(crate) fn decode_decision_row(
    row: &SqliteRow,
) -> Result<GovernanceDecisionRecord, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    verify_stored_digest(&payload_json, row.get("payload_sha256"))?;
    let record: GovernanceDecisionRecord = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    validate_decision(&record).map_err(invalid_as_corrupt)?;
    verify_canonical_payload(&record, &payload_json)?;
    if row.get::<String, _>("decision_id") != record.decision_id.as_str()
        || row.get::<String, _>("action_id") != record.action.action_id.as_str()
        || row.get::<String, _>("thread_id") != record.action.thread_id.as_str()
        || row.get::<String, _>("turn_id") != record.action.turn_id.as_str()
        || row.get::<String, _>("call_id") != record.action.call_id.as_str()
        || row.get::<String, _>("phase") != record.phase.as_str()
        || row.get::<i64, _>("schema_version") != i64::from(record.action.schema_version)
    {
        return Err(EvidenceError::Corrupt(
            "decision columns do not match canonical payload".to_string(),
        ));
    }
    Ok(record)
}

pub(crate) fn decode_receipt_row(row: &SqliteRow) -> Result<GovernanceReceipt, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    verify_stored_digest(&payload_json, row.get("payload_sha256"))?;
    let receipt: GovernanceReceipt = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    validate_receipt_binding(&receipt).map_err(invalid_as_corrupt)?;
    verify_canonical_payload(&receipt, &payload_json)?;
    let action = receipt
        .authorization
        .as_ref()
        .map_or(&receipt.admission.action, |record| &record.action);
    if row.get::<String, _>("receipt_id") != receipt.receipt_id.as_str()
        || row.get::<String, _>("action_id") != receipt.action_id.as_str()
        || row.get::<String, _>("thread_id") != action.thread_id.as_str()
        || row.get::<String, _>("turn_id") != action.turn_id.as_str()
        || row.get::<String, _>("call_id") != action.call_id.as_str()
        || row.get::<String, _>("admission_decision_id") != receipt.admission.decision_id.as_str()
        || row.get::<String, _>("admission_phase") != receipt.admission.phase.as_str()
        || row
            .get::<Option<String>, _>("authorization_decision_id")
            .as_deref()
            != receipt
                .authorization
                .as_ref()
                .map(|record| record.decision_id.as_str())
        || row
            .get::<Option<String>, _>("authorization_phase")
            .as_deref()
            != receipt
                .authorization
                .as_ref()
                .map(|record| record.phase.as_str())
        || row.get::<i64, _>("schema_version") != i64::from(GOVERNANCE_SCHEMA_VERSION)
    {
        return Err(EvidenceError::Corrupt(
            "receipt columns do not match canonical payload".to_string(),
        ));
    }
    Ok(receipt)
}

fn verify_canonical_payload<T: serde::Serialize>(
    value: &T,
    stored: &str,
) -> Result<(), EvidenceError> {
    let canonical = canonical_json(value)?;
    if canonical == stored.as_bytes() {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(
            "stored governance JSON is not canonical".to_string(),
        ))
    }
}

fn invalid_as_corrupt(error: EvidenceError) -> EvidenceError {
    match error {
        EvidenceError::InvalidRecord(detail) => EvidenceError::Corrupt(detail),
        other => other,
    }
}
