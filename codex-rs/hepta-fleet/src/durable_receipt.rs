use sqlx::Sqlite;
use sqlx::Transaction;

use crate::DurableFleetError;
use crate::FleetOperationReceiptV1;
use crate::durable_rows::encode_json;
use crate::durable_rows::to_i64;
use crate::durable_schema::sqlx_error;

pub(crate) async fn insert_receipt_tx(
    tx: &mut Transaction<'_, Sqlite>,
    receipt: &FleetOperationReceiptV1,
) -> Result<(), DurableFleetError> {
    let witness_json = receipt
        .authority_witness
        .as_ref()
        .map(encode_json)
        .transpose()?;
    let payload_json = encode_json(receipt)?;
    sqlx::query(
        "INSERT INTO fleet_operation_receipts(
            operation_id, operation_kind, subject_id, outcome, semantic_digest,
            authority_witness_json, payload_json, committed_at_ms
         ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(operation_id) DO NOTHING",
    )
    .bind(&receipt.operation_id)
    .bind(receipt.kind.as_str())
    .bind(&receipt.subject_id)
    .bind(receipt.outcome.as_str())
    .bind(&receipt.semantic_digest)
    .bind(witness_json)
    .bind(payload_json)
    .bind(to_i64(receipt.committed_at_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

pub(crate) async fn increment_counter_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation: &str,
    result: &str,
) -> Result<(), DurableFleetError> {
    sqlx::query(
        "INSERT INTO fleet_metric_counters(operation, result, value) VALUES(?, ?, 1)
         ON CONFLICT(operation, result) DO UPDATE SET value = value + 1",
    )
    .bind(operation)
    .bind(result)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

pub(crate) async fn load_receipt_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<FleetOperationReceiptV1>, DurableFleetError> {
    use sqlx::Row as _;

    let row =
        sqlx::query("SELECT payload_json FROM fleet_operation_receipts WHERE operation_id = ?")
            .bind(operation_id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(sqlx_error)?;
    row.map(|row| {
        let json: String = row.try_get("payload_json").map_err(sqlx_error)?;
        crate::durable_rows::decode_json(&json)
    })
    .transpose()
}
