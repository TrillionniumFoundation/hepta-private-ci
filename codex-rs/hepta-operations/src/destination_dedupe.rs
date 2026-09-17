use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::DurableOperationError;
use crate::OperationIdentity;

/// Destination owners may copy this exact table definition into their own
/// migration. `kernel.operations` never opens or owns the destination store.
/// All helper functions below operate on a transaction supplied by the actual
/// destination owner so dedupe and the domain mutation can commit atomically.
pub const DESTINATION_DEDUPE_SCHEMA_V1: &str = r#"
CREATE TABLE kernel_operation_dedupe (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    destination_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK(length(semantic_digest) = 32),
    receipt_digest BLOB CHECK(receipt_digest IS NULL OR length(receipt_digest) = 32),
    state TEXT NOT NULL CHECK(state IN ('reserved','applied')),
    recorded_at_ms INTEGER NOT NULL CHECK(recorded_at_ms >= 0),
    PRIMARY KEY(scope_id, operation_id, destination_id),
    CHECK((state = 'applied') = (receipt_digest IS NOT NULL))
) STRICT;
"#;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationDedupeKey {
    pub identity: OperationIdentity,
    pub destination_id: StableId,
    pub semantic_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DestinationReservation {
    Reserved,
    AlreadyApplied { receipt_digest: Digest32 },
}

/// Reserve one semantic operation inside the destination owner's write
/// transaction. The caller must perform its domain mutation and call
/// `finish_destination_effect` before committing this same transaction.
///
/// Use a serialized/IMMEDIATE write transaction. A rollback (including process
/// crash) removes the reservation together with the domain mutation.
pub async fn reserve_destination_effect(
    tx: &mut Transaction<'_, Sqlite>,
    key: &DestinationDedupeKey,
    now_ms: i64,
) -> Result<DestinationReservation, DurableOperationError> {
    if key.semantic_digest.is_zero() || now_ms < 0 {
        return Err(DurableOperationError::InvalidRequest(
            "invalid destination dedupe reservation",
        ));
    }
    let existing = sqlx::query(
        "SELECT semantic_digest, receipt_digest, state FROM kernel_operation_dedupe
         WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
    )
    .bind(key.identity.scope_id.as_str())
    .bind(key.identity.operation_id.as_str())
    .bind(key.destination_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(DurableOperationError::from)?;
    if let Some(row) = existing {
        let semantic = decode_digest(row.try_get::<Vec<u8>, _>("semantic_digest")?)?;
        if semantic != key.semantic_digest {
            return Err(DurableOperationError::Conflict(
                key.identity.operation_id.clone(),
            ));
        }
        let state: String = row.try_get("state")?;
        let receipt = row.try_get::<Option<Vec<u8>>, _>("receipt_digest")?;
        return match (state.as_str(), receipt) {
            ("applied", Some(receipt)) => Ok(DestinationReservation::AlreadyApplied {
                receipt_digest: decode_digest(receipt)?,
            }),
            ("reserved", None) => Err(DurableOperationError::Unavailable(
                "destination dedupe reservation is already active".into(),
            )),
            _ => Err(DurableOperationError::Corrupt(
                "destination dedupe row has an invalid state".into(),
            )),
        };
    }
    sqlx::query(
        "INSERT INTO kernel_operation_dedupe
         (scope_id, operation_id, destination_id, semantic_digest, state, recorded_at_ms)
         VALUES (?, ?, ?, ?, 'reserved', ?)",
    )
    .bind(key.identity.scope_id.as_str())
    .bind(key.identity.operation_id.as_str())
    .bind(key.destination_id.as_str())
    .bind(key.semantic_digest.as_array().as_slice())
    .bind(now_ms)
    .execute(&mut **tx)
    .await
    .map_err(DurableOperationError::from)?;
    Ok(DestinationReservation::Reserved)
}

/// Finalize the dedupe receipt after the destination mutation but before the
/// destination transaction commits. Exact replay of an already-applied row is
/// idempotent; changed receipt semantics conflict.
pub async fn finish_destination_effect(
    tx: &mut Transaction<'_, Sqlite>,
    key: &DestinationDedupeKey,
    receipt_digest: Digest32,
    now_ms: i64,
) -> Result<(), DurableOperationError> {
    if receipt_digest.is_zero() || now_ms < 0 {
        return Err(DurableOperationError::InvalidRequest(
            "invalid destination receipt",
        ));
    }
    let row = sqlx::query(
        "SELECT semantic_digest, receipt_digest, state FROM kernel_operation_dedupe
         WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
    )
    .bind(key.identity.scope_id.as_str())
    .bind(key.identity.operation_id.as_str())
    .bind(key.destination_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(DurableOperationError::from)?
    .ok_or_else(|| DurableOperationError::Missing(key.identity.operation_id.clone()))?;
    let semantic = decode_digest(row.try_get::<Vec<u8>, _>("semantic_digest")?)?;
    if semantic != key.semantic_digest {
        return Err(DurableOperationError::Conflict(
            key.identity.operation_id.clone(),
        ));
    }
    let state: String = row.try_get("state")?;
    let existing = row.try_get::<Option<Vec<u8>>, _>("receipt_digest")?;
    match (state.as_str(), existing) {
        ("reserved", None) => {
            sqlx::query(
                "UPDATE kernel_operation_dedupe SET state = 'applied', receipt_digest = ?,
                 recorded_at_ms = ? WHERE scope_id = ? AND operation_id = ? AND destination_id = ?",
            )
            .bind(receipt_digest.as_array().as_slice())
            .bind(now_ms)
            .bind(key.identity.scope_id.as_str())
            .bind(key.identity.operation_id.as_str())
            .bind(key.destination_id.as_str())
            .execute(&mut **tx)
            .await
            .map_err(DurableOperationError::from)?;
            Ok(())
        }
        ("applied", Some(existing)) if decode_digest(existing)? == receipt_digest => Ok(()),
        ("applied", Some(_)) => Err(DurableOperationError::Conflict(
            key.identity.operation_id.clone(),
        )),
        _ => Err(DurableOperationError::Corrupt(
            "destination dedupe row has an invalid state".into(),
        )),
    }
}

fn decode_digest(value: Vec<u8>) -> Result<Digest32, DurableOperationError> {
    let bytes: [u8; 32] = value.try_into().map_err(|_| {
        DurableOperationError::Corrupt("destination dedupe digest has invalid length".into())
    })?;
    let digest = Digest32::from_array(bytes);
    if digest.is_zero() {
        return Err(DurableOperationError::Corrupt(
            "destination dedupe digest is zero".into(),
        ));
    }
    Ok(digest)
}
