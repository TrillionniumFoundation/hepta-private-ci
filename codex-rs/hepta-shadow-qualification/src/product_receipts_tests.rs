use serde_json::Value;

use super::product_receipts::validate_row;
use crate::FrozenOracle;
use crate::QualificationError;
use crate::digest::sha256;
use crate::product_database::ProductReceiptRow;
use crate::test_support::dynamic_receipt;

#[test]
fn validates_exact_row_and_rejects_index_drift() -> Result<(), QualificationError> {
    let oracle = FrozenOracle::load_embedded()?;
    let payload = dynamic_receipt(&oracle)?;
    let value: Value = serde_json::from_slice(&payload)
        .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    let mut row = ProductReceiptRow {
        action_id: string(&value, "/action_id")?,
        admission_decision_id: string(&value, "/admission/decision_id")?,
        authorization_decision_id: string(&value, "/authorization/decision_id")?,
        call_id: "call-live-1".to_string(),
        payload_json: String::from_utf8(payload.clone())
            .map_err(|error| QualificationError::Serialization(error.to_string()))?,
        payload_sha256: sha256(&payload),
        receipt_id: string(&value, "/receipt_id")?,
        schema_version: 1,
        seq: 1,
        thread_id: "thread-live-1".to_string(),
        turn_id: "turn-live-1".to_string(),
    };
    validate_row(
        &row,
        &oracle,
        1,
        "thread-live-1",
        Some("turn-live-1"),
        "call-live-1",
    )?;
    row.payload_sha256 = "0".repeat(64);
    assert!(
        validate_row(
            &row,
            &oracle,
            1,
            "thread-live-1",
            Some("turn-live-1"),
            "call-live-1",
        )
        .is_err()
    );
    Ok(())
}

fn string(value: &Value, pointer: &str) -> Result<String, QualificationError> {
    value
        .pointer(pointer)
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| QualificationError::Invalid(format!("missing fixture field {pointer}")))
}
