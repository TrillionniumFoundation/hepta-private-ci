use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::OperationError;
use crate::ReconciliationOutcome;

/// Destination owners include an equivalent table in their own migration and
/// call the helpers below inside the *same transaction* as the domain mutation.
/// kernel.operations does not open, commit or own the destination database.
pub const DESTINATION_DEDUPE_SCHEMA_V1: &str = r#"
CREATE TABLE kernel_operation_dedupe (
    destination_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    state TEXT NOT NULL CHECK (state IN ('reserved', 'applied', 'not_applied', 'quarantined')),
    evidence_digest BLOB CHECK (evidence_digest IS NULL OR length(evidence_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    PRIMARY KEY (destination_id, scope_id, operation_id),
    CHECK ((state = 'reserved' AND evidence_digest IS NULL)
        OR (state != 'reserved' AND evidence_digest IS NOT NULL))
) WITHOUT ROWID;
CREATE TRIGGER kernel_operation_dedupe_identity_immutable BEFORE UPDATE OF
    destination_id, scope_id, operation_id, payload_digest, created_at_ms
    ON kernel_operation_dedupe
BEGIN
    SELECT RAISE(ABORT, 'destination operation identity is immutable');
END;
CREATE TRIGGER kernel_operation_dedupe_terminal_immutable BEFORE UPDATE ON kernel_operation_dedupe
WHEN OLD.state != 'reserved'
BEGIN
    SELECT RAISE(ABORT, 'destination terminal receipt is immutable');
END;
"#;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationDedupeKey {
    pub destination_id: StableId,
    pub scope_id: StableId,
    pub operation_id: StableId,
    pub payload_digest: Digest32,
}

impl DestinationDedupeKey {
    fn validate(&self) -> Result<(), OperationError> {
        if self.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("destination payload"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DestinationDedupeState {
    Reserved,
    Applied,
    NotApplied,
    Quarantined,
}

impl DestinationDedupeState {
    fn parse(value: &str) -> Option<Self> {
        match value {
            "reserved" => Some(Self::Reserved),
            "applied" => Some(Self::Applied),
            "not_applied" => Some(Self::NotApplied),
            "quarantined" => Some(Self::Quarantined),
            _ => None,
        }
    }

    const fn terminal_for(outcome: ReconciliationOutcome) -> Self {
        match outcome {
            ReconciliationOutcome::Applied => Self::Applied,
            ReconciliationOutcome::NotApplied => Self::NotApplied,
            ReconciliationOutcome::Quarantined => Self::Quarantined,
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::Reserved => "reserved",
            Self::Applied => "applied",
            Self::NotApplied => "not_applied",
            Self::Quarantined => "quarantined",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationDedupeRecord {
    pub key: DestinationDedupeKey,
    pub state: DestinationDedupeState,
    pub evidence_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DestinationReserveDisposition {
    Reserved,
    Existing(DestinationDedupeRecord),
}

/// Reserve one semantic identity inside a destination-owned transaction. The
/// destination must perform its domain mutation and call
/// `record_destination_terminal` before committing this same transaction. A
/// rollback therefore rolls back both the mutation and the reservation.
pub async fn reserve_destination_effect(
    tx: &mut Transaction<'_, Sqlite>,
    key: &DestinationDedupeKey,
    now_ms: i64,
) -> Result<DestinationReserveDisposition, OperationError> {
    key.validate()?;
    if now_ms < 0 {
        return Err(OperationError::Unavailable(
            "destination clock predates Unix epoch".into(),
        ));
    }
    if let Some(record) = load_destination_record(tx, key).await? {
        if record.key.payload_digest != key.payload_digest {
            return Err(OperationError::Conflict(key.operation_id.clone()));
        }
        return Ok(DestinationReserveDisposition::Existing(record));
    }
    sqlx::query(
        "INSERT INTO kernel_operation_dedupe
         (destination_id, scope_id, operation_id, payload_digest, state, created_at_ms, updated_at_ms)
         VALUES (?, ?, ?, ?, 'reserved', ?, ?)",
    )
    .bind(key.destination_id.as_str())
    .bind(key.scope_id.as_str())
    .bind(key.operation_id.as_str())
    .bind(key.payload_digest.as_array().as_slice())
    .bind(now_ms)
    .bind(now_ms)
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(DestinationReserveDisposition::Reserved)
}

/// Record the destination's terminal result before the destination-owned
/// transaction commits. Exact replay is idempotent; changed terminal semantics
/// conflict instead of reapplying the domain mutation.
pub async fn record_destination_terminal(
    tx: &mut Transaction<'_, Sqlite>,
    key: &DestinationDedupeKey,
    outcome: ReconciliationOutcome,
    evidence_digest: Digest32,
    now_ms: i64,
) -> Result<DestinationDedupeRecord, OperationError> {
    if evidence_digest.is_zero() {
        return Err(OperationError::InvalidDigest("destination terminal evidence"));
    }
    let existing = load_destination_record(tx, key)
        .await?
        .ok_or_else(|| OperationError::Missing(key.operation_id.clone()))?;
    if existing.key.payload_digest != key.payload_digest {
        return Err(OperationError::Conflict(key.operation_id.clone()));
    }
    let target = DestinationDedupeState::terminal_for(outcome);
    if existing.state != DestinationDedupeState::Reserved {
        if existing.state == target && existing.evidence_digest == Some(evidence_digest) {
            return Ok(existing);
        }
        return Err(OperationError::Terminal);
    }
    if now_ms < existing.updated_at_ms {
        return Err(OperationError::Unavailable(
            "destination clock moved behind dedupe watermark".into(),
        ));
    }
    sqlx::query(
        "UPDATE kernel_operation_dedupe SET state = ?, evidence_digest = ?, updated_at_ms = ?
         WHERE destination_id = ? AND scope_id = ? AND operation_id = ?",
    )
    .bind(target.as_str())
    .bind(evidence_digest.as_array().as_slice())
    .bind(now_ms)
    .bind(key.destination_id.as_str())
    .bind(key.scope_id.as_str())
    .bind(key.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    load_destination_record(tx, key)
        .await?
        .ok_or_else(|| OperationError::Corrupt("destination dedupe receipt disappeared".into()))
}

pub async fn load_destination_record(
    tx: &mut Transaction<'_, Sqlite>,
    key: &DestinationDedupeKey,
) -> Result<Option<DestinationDedupeRecord>, OperationError> {
    let row = sqlx::query(
        "SELECT destination_id, scope_id, operation_id, payload_digest, state,
                evidence_digest, created_at_ms, updated_at_ms
         FROM kernel_operation_dedupe
         WHERE destination_id = ? AND scope_id = ? AND operation_id = ?",
    )
    .bind(key.destination_id.as_str())
    .bind(key.scope_id.as_str())
    .bind(key.operation_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let payload = digest(
        row.try_get::<Vec<u8>, _>("payload_digest")
            .map_err(storage)?,
        "destination payload digest",
    )?;
    let state_text = row.try_get::<String, _>("state").map_err(storage)?;
    let state = DestinationDedupeState::parse(&state_text).ok_or_else(|| {
        OperationError::Corrupt(format!("unknown destination dedupe state {state_text:?}"))
    })?;
    let evidence = row
        .try_get::<Option<Vec<u8>>, _>("evidence_digest")
        .map_err(storage)?
        .map(|value| digest(value, "destination evidence digest"))
        .transpose()?;
    Ok(Some(DestinationDedupeRecord {
        key: DestinationDedupeKey {
            destination_id: StableId::new(
                row.try_get::<String, _>("destination_id")
                    .map_err(storage)?,
            )
            .map_err(|error| OperationError::Corrupt(error.to_string()))?,
            scope_id: StableId::new(row.try_get::<String, _>("scope_id").map_err(storage)?)
                .map_err(|error| OperationError::Corrupt(error.to_string()))?,
            operation_id: StableId::new(
                row.try_get::<String, _>("operation_id")
                    .map_err(storage)?,
            )
            .map_err(|error| OperationError::Corrupt(error.to_string()))?,
            payload_digest: payload,
        },
        state,
        evidence_digest: evidence,
        created_at_ms: row.try_get("created_at_ms").map_err(storage)?,
        updated_at_ms: row.try_get("updated_at_ms").map_err(storage)?,
    }))
}

fn digest(bytes: Vec<u8>, label: &'static str) -> Result<Digest32, OperationError> {
    let array: [u8; 32] = bytes.try_into().map_err(|_| {
        OperationError::Corrupt(format!("{label} has an invalid encoded length"))
    })?;
    let digest = Digest32::from_array(array);
    if digest.is_zero() {
        return Err(OperationError::Corrupt(format!("{label} is zero")));
    }
    Ok(digest)
}

fn storage(error: sqlx::Error) -> OperationError {
    OperationError::Storage(error.to_string())
}
