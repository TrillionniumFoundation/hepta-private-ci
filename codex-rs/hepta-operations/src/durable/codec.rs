use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::sqlite::SqliteRow;

use crate::ReconciliationOutcome;

use super::DestinationReceipt;
use super::DurableOperationError;
use super::DurableOperationRecord;
use super::DurableOperationState;
use super::DurableOutboxState;
use super::DurableOutboxStatus;
use super::unavailable;

pub(crate) const OPERATION_SELECT: &str =
    "SELECT * FROM operation_ledger WHERE scope = ? AND operation_id = ?";
pub(crate) const OUTBOX_SELECT: &str =
    "SELECT * FROM cross_owner_outbox WHERE scope = ? AND operation_id = ?";
pub(crate) const DESTINATION_SELECT: &str =
    "SELECT * FROM destination_operation_dedup WHERE destination = ? AND operation_id = ?";

pub(crate) fn decode_operation(
    row: SqliteRow,
) -> Result<DurableOperationRecord, DurableOperationError> {
    let state: String = row.try_get("state").map_err(unavailable)?;
    Ok(DurableOperationRecord {
        scope: stable_id(row.try_get("scope").map_err(unavailable)?, "scope")?,
        operation_id: stable_id(
            row.try_get("operation_id").map_err(unavailable)?,
            "operation_id",
        )?,
        semantic_digest: digest(row.try_get("semantic_digest").map_err(unavailable)?, "semantic")?,
        predecessor_digest: optional_digest(
            row.try_get("predecessor_digest").map_err(unavailable)?,
            "predecessor",
        )?,
        payload_digest: digest(row.try_get("payload_digest").map_err(unavailable)?, "payload")?,
        destination: stable_id(
            row.try_get("destination").map_err(unavailable)?,
            "destination",
        )?,
        owner_generation: generation(
            row.try_get("owner_generation").map_err(unavailable)?,
            "owner_generation",
        )?,
        authority_epoch: generation(
            row.try_get("authority_epoch").map_err(unavailable)?,
            "authority_epoch",
        )?,
        revision: revision(row.try_get("revision").map_err(unavailable)?)?,
        state: DurableOperationState::parse(&state)?,
        dispatch_digest: optional_digest(
            row.try_get("dispatch_digest").map_err(unavailable)?,
            "dispatch",
        )?,
        indeterminate_digest: optional_digest(
            row.try_get("indeterminate_digest").map_err(unavailable)?,
            "indeterminate",
        )?,
        terminal_evidence_digest: optional_digest(
            row.try_get("terminal_evidence_digest").map_err(unavailable)?,
            "terminal evidence",
        )?,
        created_at_ms: row.try_get("created_at_ms").map_err(unavailable)?,
        updated_at_ms: row.try_get("updated_at_ms").map_err(unavailable)?,
        terminal_at_ms: row.try_get("terminal_at_ms").map_err(unavailable)?,
    })
}

pub(crate) fn decode_outbox(
    row: SqliteRow,
) -> Result<DurableOutboxStatus, DurableOperationError> {
    let state: String = row.try_get("state").map_err(unavailable)?;
    let fence: i64 = row.try_get("fence").map_err(unavailable)?;
    let attempts: i64 = row.try_get("attempts").map_err(unavailable)?;
    let worker: Option<String> = row.try_get("worker_id").map_err(unavailable)?;
    Ok(DurableOutboxStatus {
        scope: stable_id(row.try_get("scope").map_err(unavailable)?, "scope")?,
        operation_id: stable_id(
            row.try_get("operation_id").map_err(unavailable)?,
            "operation_id",
        )?,
        destination: stable_id(
            row.try_get("destination").map_err(unavailable)?,
            "destination",
        )?,
        semantic_digest: digest(row.try_get("semantic_digest").map_err(unavailable)?, "semantic")?,
        state: DurableOutboxState::parse(&state)?,
        fence: u64::try_from(fence)
            .map_err(|_| DurableOperationError::Corrupt("negative outbox fence".to_string()))?,
        attempts: u32::try_from(attempts)
            .map_err(|_| DurableOperationError::Corrupt("invalid outbox attempts".to_string()))?,
        available_at_ms: row.try_get("available_at_ms").map_err(unavailable)?,
        worker_id: worker.map(|value| stable_id(value, "worker_id")).transpose()?,
        lease_until_ms: row.try_get("lease_until_ms").map_err(unavailable)?,
        claim_generation: optional_generation(
            row.try_get("claim_generation").map_err(unavailable)?,
            "claim_generation",
        )?,
        acknowledgement_digest: optional_digest(
            row.try_get("acknowledgement_digest").map_err(unavailable)?,
            "acknowledgement",
        )?,
        last_error_digest: optional_digest(
            row.try_get("last_error_digest").map_err(unavailable)?,
            "last_error",
        )?,
        created_at_ms: row.try_get("created_at_ms").map_err(unavailable)?,
        updated_at_ms: row.try_get("updated_at_ms").map_err(unavailable)?,
        terminal_at_ms: row.try_get("terminal_at_ms").map_err(unavailable)?,
    })
}

pub(crate) fn decode_destination(
    row: SqliteRow,
) -> Result<DestinationReceipt, DurableOperationError> {
    let outcome: String = row.try_get("outcome").map_err(unavailable)?;
    Ok(DestinationReceipt {
        destination: stable_id(
            row.try_get("destination").map_err(unavailable)?,
            "destination",
        )?,
        operation_id: stable_id(
            row.try_get("operation_id").map_err(unavailable)?,
            "operation_id",
        )?,
        semantic_digest: digest(row.try_get("semantic_digest").map_err(unavailable)?, "semantic")?,
        outcome: parse_outcome(&outcome)?,
        evidence_digest: digest(row.try_get("evidence_digest").map_err(unavailable)?, "evidence")?,
        recorded_at_ms: row.try_get("recorded_at_ms").map_err(unavailable)?,
    })
}

pub(crate) fn state_for_outcome(outcome: ReconciliationOutcome) -> DurableOperationState {
    match outcome {
        ReconciliationOutcome::Applied => DurableOperationState::Applied,
        ReconciliationOutcome::NotApplied => DurableOperationState::NotApplied,
        ReconciliationOutcome::Quarantined => DurableOperationState::Quarantined,
    }
}

pub(crate) fn outcome_label(outcome: ReconciliationOutcome) -> &'static str {
    match outcome {
        ReconciliationOutcome::Applied => "applied",
        ReconciliationOutcome::NotApplied => "not_applied",
        ReconciliationOutcome::Quarantined => "quarantined",
    }
}

fn parse_outcome(value: &str) -> Result<ReconciliationOutcome, DurableOperationError> {
    match value {
        "applied" => Ok(ReconciliationOutcome::Applied),
        "not_applied" => Ok(ReconciliationOutcome::NotApplied),
        "quarantined" => Ok(ReconciliationOutcome::Quarantined),
        _ => Err(DurableOperationError::Corrupt(format!(
            "unknown destination outcome {value}"
        ))),
    }
}

pub(crate) fn blob(value: Digest32) -> Vec<u8> {
    value.into_array().to_vec()
}

pub(crate) fn optional_blob(value: Option<Digest32>) -> Option<Vec<u8>> {
    value.map(blob)
}

pub(crate) fn u64_blob(value: u64) -> Vec<u8> {
    value.to_be_bytes().to_vec()
}

fn digest(bytes: Vec<u8>, field: &str) -> Result<Digest32, DurableOperationError> {
    let array: [u8; 32] = bytes.try_into().map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} digest is not 32 bytes"))
    })?;
    let value = Digest32::from_array(array);
    if value.is_zero() {
        return Err(DurableOperationError::Corrupt(format!(
            "{field} digest is zero"
        )));
    }
    Ok(value)
}

fn optional_digest(
    bytes: Option<Vec<u8>>,
    field: &str,
) -> Result<Option<Digest32>, DurableOperationError> {
    bytes.map(|value| digest(value, field)).transpose()
}

fn decode_u64(bytes: Vec<u8>, field: &str) -> Result<u64, DurableOperationError> {
    let array: [u8; 8] = bytes.try_into().map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} is not an 8-byte u64"))
    })?;
    Ok(u64::from_be_bytes(array))
}

fn generation(bytes: Vec<u8>, field: &str) -> Result<Generation, DurableOperationError> {
    Generation::new(decode_u64(bytes, field)?).map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} is not a valid generation"))
    })
}

fn optional_generation(
    bytes: Option<Vec<u8>>,
    field: &str,
) -> Result<Option<Generation>, DurableOperationError> {
    bytes.map(|value| generation(value, field)).transpose()
}

fn revision(bytes: Vec<u8>) -> Result<Revision, DurableOperationError> {
    Revision::new(decode_u64(bytes, "revision")?).map_err(|_| {
        DurableOperationError::Corrupt("revision is not a valid monotonic value".to_string())
    })
}

fn stable_id(value: String, field: &str) -> Result<StableId, DurableOperationError> {
    StableId::new(value).map_err(|_| {
        DurableOperationError::Corrupt(format!("{field} is not a valid stable identifier"))
    })
}

pub(crate) fn first_revision() -> Revision {
    match Revision::new(1) {
        Ok(value) => value,
        Err(error) => unreachable!("constant first revision is invalid: {error}"),
    }
}

pub(crate) fn now_millis() -> Result<i64, DurableOperationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| DurableOperationError::Unavailable("clock predates Unix epoch".to_string()))?
        .as_millis();
    i64::try_from(millis)
        .map_err(|_| DurableOperationError::Unavailable("clock overflow".to_string()))
}

pub(crate) fn nonnegative_u64(value: i64) -> Result<u64, DurableOperationError> {
    u64::try_from(value)
        .map_err(|_| DurableOperationError::Corrupt("negative aggregate count".to_string()))
}
