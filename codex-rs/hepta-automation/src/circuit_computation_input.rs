//! Bounded original input retained with a sealed Circuit computation claim.
//! This data is not an execution grant; only the Circuit owner issues admission.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::TaskFlowError;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;

const MAX_INPUT_BYTES: usize = 65_536;

/// Exact versioned downstream bytes. A bridge must recognize the schema and
/// verify its decoded request against the admission's execution request digest.
/// Neither construction nor possession of this value admits any computation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitComputationInputV1 {
    schema: String,
    bytes: Vec<u8>,
}

impl CircuitComputationInputV1 {
    pub fn new(schema: impl Into<String>, bytes: Vec<u8>) -> Result<Self, TaskFlowError> {
        let schema = schema.into();
        text(&schema)?;
        if bytes.is_empty() || bytes.len() > MAX_INPUT_BYTES {
            return Err(invalid("computation input exceeds byte bound"));
        }
        Ok(Self { schema, bytes })
    }

    pub fn schema(&self) -> &str {
        &self.schema
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        hash(
            "hepta.circuit.computation-input.v1",
            &(&self.schema, &self.bytes),
        )
    }
}

pub(crate) async fn retain(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    run_id: &str,
    activation_id: u64,
    input: &CircuitComputationInputV1,
) -> Result<(), TaskFlowError> {
    sqlx::query(
        "INSERT INTO circuit_v2_computation_inputs
         (owner_agent_id, run_id, activation_id, schema_id, input_bytes)
         VALUES (?, ?, ?, ?, ?)",
    )
    .bind(owner.as_str())
    .bind(run_id)
    .bind(i64::try_from(activation_id).map_err(|_| invalid("activation overflow"))?)
    .bind(input.schema())
    .bind(input.bytes())
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
) -> Result<Option<CircuitComputationInputV1>, TaskFlowError> {
    let row: Option<(String, Vec<u8>)> = sqlx::query_as(
        "SELECT CASE WHEN length(CAST(schema_id AS BLOB)) <= 128 THEN schema_id ELSE '' END,
                CASE WHEN length(input_bytes) <= 65536 THEN input_bytes ELSE X'' END
         FROM circuit_v2_computation_inputs
         WHERE owner_agent_id = ? AND run_id = ? AND activation_id = ?",
    )
    .bind(owner.as_str())
    .bind(run_id)
    .bind(i64::try_from(activation_id).map_err(|_| invalid("activation overflow"))?)
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    match (row, expected) {
        (None, None) => Ok(None),
        (Some((schema, bytes)), Some(expected)) => {
            let input = CircuitComputationInputV1::new(schema, bytes).map_err(|_| corrupt())?;
            if &input.digest()? != expected {
                return Err(corrupt());
            }
            Ok(Some(input))
        }
        _ => Err(corrupt()),
    }
}

fn corrupt() -> TaskFlowError {
    TaskFlowError::Corrupt("retained computation input differs from its claim history".into())
}
