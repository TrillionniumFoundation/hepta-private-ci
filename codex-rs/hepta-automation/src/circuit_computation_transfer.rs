//! Bounded immutable output and original receipt bytes retained by the Circuit
//! owner. These bytes are data, not an authenticated meter or an ACK capability.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::CircuitCompletionV2;
use crate::CircuitEventV2;
use crate::TaskFlowError;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;

/// A bridge must recognize this schema and obtain the receipt and its cost
/// from the actual computation owner. Construction cannot grant computation,
/// authenticate cost observations or acknowledge a Generation outbox.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitComputationTransferV1 {
    schema: String,
    receipt_bytes: Vec<u8>,
    output_bytes: Vec<u8>,
}

impl CircuitComputationTransferV1 {
    pub fn new(
        schema: impl Into<String>,
        receipt_bytes: Vec<u8>,
        output_bytes: Vec<u8>,
    ) -> Result<Self, TaskFlowError> {
        let schema = schema.into();
        text(&schema)?;
        if receipt_bytes.is_empty() || receipt_bytes.len() > 131_072 || output_bytes.len() > 65_536
        {
            return Err(invalid("computation transfer exceeds byte bound"));
        }
        Ok(Self {
            schema,
            receipt_bytes,
            output_bytes,
        })
    }

    pub fn schema(&self) -> &str {
        &self.schema
    }
    pub fn receipt_bytes(&self) -> &[u8] {
        &self.receipt_bytes
    }
    pub fn output_bytes(&self) -> &[u8] {
        &self.output_bytes
    }
    pub fn output_digest(&self) -> Sha256Digest {
        Sha256Digest::for_bytes(&self.output_bytes)
    }

    pub fn digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        hash(
            "hepta.circuit.computation-transfer.v1",
            &(&self.schema, &self.receipt_bytes, &self.output_bytes),
        )
    }
}

pub(crate) fn completion(event: &CircuitEventV2) -> Result<&CircuitCompletionV2, TaskFlowError> {
    match event {
        CircuitEventV2::Complete { completion } | CircuitEventV2::Reconcile { completion } => {
            Ok(completion)
        }
        CircuitEventV2::Advance { .. }
        | CircuitEventV2::MarkIndeterminate { .. }
        | CircuitEventV2::Cancel => Err(invalid(
            "a transfer requires an original computation completion",
        )),
    }
}

pub(crate) async fn retain(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    run_id: &str,
    activation_id: u64,
    transfer: &CircuitComputationTransferV1,
) -> Result<(), TaskFlowError> {
    sqlx::query(
        "INSERT INTO circuit_v2_computation_transfers
        (owner_agent_id, run_id, activation_id, schema_id, receipt_bytes, output_bytes)
        VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(owner.as_str())
    .bind(run_id)
    .bind(i64::try_from(activation_id).map_err(|_| invalid("activation overflow"))?)
    .bind(transfer.schema())
    .bind(transfer.receipt_bytes())
    .bind(transfer.output_bytes())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn load(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    run_id: &str,
    activation_id: u64,
    expected: Option<&Sha256Digest>,
    expected_output: Option<&Sha256Digest>,
) -> Result<Option<CircuitComputationTransferV1>, TaskFlowError> {
    let row: Option<(String, Vec<u8>, Vec<u8>, bool)> = sqlx::query_as(
        "SELECT CASE WHEN typeof(schema_id) = 'text' AND length(CAST(schema_id AS BLOB)) <= 128
                    THEN schema_id ELSE '' END,
                CASE WHEN typeof(receipt_bytes) = 'blob' AND length(receipt_bytes) <= 131072
                    THEN receipt_bytes ELSE X'' END,
                CASE WHEN typeof(output_bytes) = 'blob' AND length(output_bytes) <= 65536
                    THEN output_bytes ELSE X'' END,
                typeof(output_bytes) = 'blob' AND length(output_bytes) <= 65536
         FROM circuit_v2_computation_transfers
         WHERE owner_agent_id = ? AND run_id = ? AND activation_id = ?",
    )
    .bind(owner.as_str())
    .bind(run_id)
    .bind(i64::try_from(activation_id).map_err(|_| invalid("activation overflow"))?)
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    match (row, expected, expected_output) {
        (None, None, _) => Ok(None),
        (Some((schema, receipt, output, true)), Some(expected), Some(expected_output)) => {
            let transfer = CircuitComputationTransferV1::new(schema, receipt, output)
                .map_err(|_| corrupt())?;
            if &transfer.digest()? != expected || &transfer.output_digest() != expected_output {
                return Err(corrupt());
            }
            Ok(Some(transfer))
        }
        _ => Err(corrupt()),
    }
}

fn corrupt() -> TaskFlowError {
    TaskFlowError::Corrupt("retained computation transfer differs from completion history".into())
}
