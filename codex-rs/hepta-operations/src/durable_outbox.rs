use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::MAX_MODEL_OUTBOX_RECORDS;
use crate::OperationError;
use crate::OutboxIntent;

use super::DurableOperationBinding;
use super::DurableOperationLedger;
use super::DurableOperationRecord;
use super::insert_record;
use super::load_in_transaction;

const MAX_CLAIM_ATTEMPTS: u32 = 64;
const MAX_LEASE_MS: u64 = 60_000;
pub const MAX_DURABLE_OUTBOX_PAYLOAD_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOutboxState {
    Pending,
    Claimed {
        owner_generation: Generation,
        lease_expires_at_ms: u64,
        attempts: u32,
    },
    Acknowledged {
        owner_generation: Generation,
        acknowledgement_digest: Digest32,
        attempts: u32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOutboxRecord {
    pub intent: OutboxIntent,
    pub payload: Vec<u8>,
    pub state: DurableOutboxState,
}

pub(super) async fn initialize(pool: &SqlitePool) -> Result<(), OperationError> {
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS hepta_operation_outbox_v1 (
            intent_id TEXT PRIMARY KEY NOT NULL,
            operation_id TEXT NOT NULL UNIQUE,
            destination TEXT NOT NULL,
            payload_digest BLOB NOT NULL CHECK(length(payload_digest) = 32),
            payload BLOB NOT NULL CHECK(length(payload) BETWEEN 1 AND 65536),
            state TEXT NOT NULL CHECK(state IN ('pending', 'claimed', 'acknowledged')),
            owner_generation TEXT,
            lease_expires_at_ms TEXT,
            attempts INTEGER NOT NULL CHECK(attempts >= 0 AND attempts <= 64),
            acknowledgement_digest BLOB CHECK(
                acknowledgement_digest IS NULL OR length(acknowledgement_digest) = 32
            )
        )
        "#,
    )
    .execute(pool)
    .await
    .map_err(|_| OperationError::StorageUnavailable)?;
    Ok(())
}

impl DurableOperationLedger {
    pub async fn begin_bound_with_outbox(
        &self,
        binding: DurableOperationBinding,
        owner_generation: Generation,
        intent: OutboxIntent,
        payload: Vec<u8>,
    ) -> Result<(DurableOperationRecord, DurableOutboxRecord), OperationError> {
        binding.validate()?;
        validate_intent(&intent, &payload)?;
        if intent.operation_id != binding.key.id || intent.destination != binding.destination_id {
            return Err(OperationError::Conflict(intent.intent_id));
        }

        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;

        let operation = if let Some(existing) =
            load_in_transaction(&mut tx, &binding.key.id).await?
        {
            if existing.operation.key != binding.key
                || existing.destination_id != binding.destination_id
                || existing.context_digest != binding.context_digest
                || existing.operation.owner_generation != owner_generation
            {
                return Err(OperationError::Conflict(binding.key.id));
            }
            existing
        } else {
            let operation_count =
                sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM hepta_operation_ledger_v1")
                    .fetch_one(&mut *tx)
                    .await
                    .map_err(|_| OperationError::StorageUnavailable)?;
            if operation_count >= super::MAX_DURABLE_OPERATION_RECORDS {
                return Err(OperationError::CapacityExceeded {
                    resource: "durable operation ledger",
                    maximum: crate::MAX_MODEL_OPERATION_RECORDS,
                });
            }
            let record = DurableOperationRecord {
                operation: crate::OperationRecord {
                    key: binding.key.clone(),
                    owner_generation,
                    revision: codex_hepta_types::Revision::new(1)
                        .map_err(|_| OperationError::CorruptStore("revision"))?,
                    state: crate::OperationState::Pending,
                },
                destination_id: binding.destination_id.clone(),
                context_digest: binding.context_digest,
                authority_evidence_digest: None,
                authority_generation: None,
                dispatch_digest: None,
                indeterminate_reason_digest: None,
                terminal_evidence_digest: None,
            };
            insert_record(&mut tx, &record).await?;
            record
        };

        let existing_outbox = load_outbox_in_transaction(&mut tx, &intent.intent_id).await?;
        let outbox = if let Some(existing) = existing_outbox {
            if existing.intent != intent || existing.payload != payload {
                return Err(OperationError::Conflict(intent.intent_id));
            }
            existing
        } else if load_outbox_by_operation_in_transaction(&mut tx, &intent.operation_id)
            .await?
            .is_some()
        {
            // One immutable operation identity owns exactly one dispatch intent.
            // Retrying with a fresh intent_id must not create a second physical
            // dispatch path for the same operation.
            return Err(OperationError::Conflict(intent.operation_id));
        } else {
            let outbox_count =
                sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM hepta_operation_outbox_v1")
                    .fetch_one(&mut *tx)
                    .await
                    .map_err(|_| OperationError::StorageUnavailable)?;
            if outbox_count >= MAX_MODEL_OUTBOX_RECORDS as i64 {
                return Err(OperationError::CapacityExceeded {
                    resource: "durable operation outbox",
                    maximum: MAX_MODEL_OUTBOX_RECORDS,
                });
            }
            sqlx::query(
                r#"
                INSERT INTO hepta_operation_outbox_v1(
                    intent_id, operation_id, destination, payload_digest, payload, state,
                    owner_generation, lease_expires_at_ms, attempts, acknowledgement_digest
                ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL, 0, NULL)
                "#,
            )
            .bind(intent.intent_id.as_str())
            .bind(intent.operation_id.as_str())
            .bind(intent.destination.as_str())
            .bind(intent.payload_digest.as_array().to_vec())
            .bind(&payload)
            .execute(&mut *tx)
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
            DurableOutboxRecord {
                intent,
                payload,
                state: DurableOutboxState::Pending,
            }
        };

        tx.commit()
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        Ok((operation, outbox))
    }

    pub async fn claim_outbox(
        &self,
        intent_id: &StableId,
        owner_generation: Generation,
        now_ms: u64,
        lease_ms: u64,
    ) -> Result<DurableOutboxRecord, OperationError> {
        if lease_ms == 0 || lease_ms > MAX_LEASE_MS {
            return Err(OperationError::CapacityExceeded {
                resource: "outbox claim lease milliseconds",
                maximum: MAX_LEASE_MS as usize,
            });
        }
        let lease_expires_at_ms = now_ms
            .checked_add(lease_ms)
            .ok_or(OperationError::CorruptStore("outbox lease overflow"))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        let current = load_outbox_in_transaction(&mut tx, intent_id)
            .await?
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;

        let attempts = match current.state {
            DurableOutboxState::Pending => 1,
            DurableOutboxState::Claimed {
                owner_generation: existing,
                lease_expires_at_ms: existing_expiry,
                attempts,
            } if existing == owner_generation && existing_expiry > now_ms => {
                tx.commit()
                    .await
                    .map_err(|_| OperationError::StorageUnavailable)?;
                return Ok(current);
            }
            DurableOutboxState::Claimed {
                owner_generation: existing,
                lease_expires_at_ms: existing_expiry,
                attempts,
            } if existing_expiry <= now_ms && owner_generation.get() > existing.get() => {
                attempts
                    .checked_add(1)
                    .ok_or(OperationError::CapacityExceeded {
                        resource: "outbox claim attempts",
                        maximum: MAX_CLAIM_ATTEMPTS as usize,
                    })?
            }
            DurableOutboxState::Claimed { .. } => return Err(OperationError::StaleGeneration),
            DurableOutboxState::Acknowledged { .. } => return Err(OperationError::Terminal),
        };
        if attempts > MAX_CLAIM_ATTEMPTS {
            return Err(OperationError::CapacityExceeded {
                resource: "outbox claim attempts",
                maximum: MAX_CLAIM_ATTEMPTS as usize,
            });
        }

        sqlx::query(
            r#"
            UPDATE hepta_operation_outbox_v1
            SET state = 'claimed', owner_generation = ?, lease_expires_at_ms = ?,
                attempts = ?, acknowledgement_digest = NULL
            WHERE intent_id = ?
            "#,
        )
        .bind(owner_generation.get().to_string())
        .bind(lease_expires_at_ms.to_string())
        .bind(i64::from(attempts))
        .bind(intent_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(|_| OperationError::StorageUnavailable)?;
        tx.commit()
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;

        Ok(DurableOutboxRecord {
            intent: current.intent,
            payload: current.payload,
            state: DurableOutboxState::Claimed {
                owner_generation,
                lease_expires_at_ms,
                attempts,
            },
        })
    }

    pub async fn acknowledge_outbox(
        &self,
        intent_id: &StableId,
        owner_generation: Generation,
        acknowledgement_digest: Digest32,
        now_ms: u64,
    ) -> Result<DurableOutboxRecord, OperationError> {
        if acknowledgement_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox acknowledgement"));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;
        let current = load_outbox_in_transaction(&mut tx, intent_id)
            .await?
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        let attempts = match current.state {
            DurableOutboxState::Claimed {
                owner_generation: existing,
                lease_expires_at_ms,
                attempts,
            } if existing == owner_generation && lease_expires_at_ms > now_ms => attempts,
            DurableOutboxState::Claimed {
                owner_generation: existing,
                ..
            } if existing == owner_generation => return Err(OperationError::StaleGeneration),
            DurableOutboxState::Claimed { .. } => return Err(OperationError::StaleGeneration),
            DurableOutboxState::Pending => return Err(OperationError::NotClaimed),
            DurableOutboxState::Acknowledged {
                owner_generation: existing,
                acknowledgement_digest: existing_digest,
                ..
            } if existing == owner_generation && existing_digest == acknowledgement_digest => {
                tx.commit()
                    .await
                    .map_err(|_| OperationError::StorageUnavailable)?;
                return Ok(current);
            }
            DurableOutboxState::Acknowledged {
                owner_generation: existing,
                ..
            } if existing != owner_generation => return Err(OperationError::StaleGeneration),
            DurableOutboxState::Acknowledged { .. } => {
                return Err(OperationError::Conflict(intent_id.clone()));
            }
        };

        sqlx::query(
            r#"
            UPDATE hepta_operation_outbox_v1
            SET state = 'acknowledged', lease_expires_at_ms = NULL,
                acknowledgement_digest = ?
            WHERE intent_id = ?
            "#,
        )
        .bind(acknowledgement_digest.as_array().to_vec())
        .bind(intent_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(|_| OperationError::StorageUnavailable)?;
        tx.commit()
            .await
            .map_err(|_| OperationError::StorageUnavailable)?;

        Ok(DurableOutboxRecord {
            intent: current.intent,
            payload: current.payload,
            state: DurableOutboxState::Acknowledged {
                owner_generation,
                acknowledgement_digest,
                attempts,
            },
        })
    }

    pub async fn get_outbox(
        &self,
        intent_id: &StableId,
    ) -> Result<Option<DurableOutboxRecord>, OperationError> {
        let row = sqlx::query(
            r#"
            SELECT intent_id, operation_id, destination, payload_digest, payload, state,
                   owner_generation, lease_expires_at_ms, attempts, acknowledgement_digest
            FROM hepta_operation_outbox_v1
            WHERE intent_id = ?
            "#,
        )
        .bind(intent_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| OperationError::StorageUnavailable)?;
        row.map(decode_outbox).transpose()
    }
}

async fn load_outbox_by_operation_in_transaction(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    operation_id: &StableId,
) -> Result<Option<DurableOutboxRecord>, OperationError> {
    let row = sqlx::query(
        r#"
        SELECT intent_id, operation_id, destination, payload_digest, payload, state,
               owner_generation, lease_expires_at_ms, attempts, acknowledgement_digest
        FROM hepta_operation_outbox_v1
        WHERE operation_id = ?
        "#,
    )
    .bind(operation_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(|_| OperationError::StorageUnavailable)?;
    row.map(decode_outbox).transpose()
}

async fn load_outbox_in_transaction(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    intent_id: &StableId,
) -> Result<Option<DurableOutboxRecord>, OperationError> {
    let row = sqlx::query(
        r#"
        SELECT intent_id, operation_id, destination, payload_digest, payload, state,
               owner_generation, lease_expires_at_ms, attempts, acknowledgement_digest
        FROM hepta_operation_outbox_v1
        WHERE intent_id = ?
        "#,
    )
    .bind(intent_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(|_| OperationError::StorageUnavailable)?;
    row.map(decode_outbox).transpose()
}

fn decode_outbox(row: sqlx::sqlite::SqliteRow) -> Result<DurableOutboxRecord, OperationError> {
    let intent_id = stable_id(
        row.try_get("intent_id")
            .map_err(|_| OperationError::StorageUnavailable)?,
        "outbox intent id",
    )?;
    let operation_id = stable_id(
        row.try_get("operation_id")
            .map_err(|_| OperationError::StorageUnavailable)?,
        "outbox operation id",
    )?;
    let destination = stable_id(
        row.try_get("destination")
            .map_err(|_| OperationError::StorageUnavailable)?,
        "outbox destination",
    )?;
    let payload_digest = digest_blob(
        row.try_get("payload_digest")
            .map_err(|_| OperationError::StorageUnavailable)?,
        "outbox payload digest",
    )?;
    let payload: Vec<u8> = row
        .try_get("payload")
        .map_err(|_| OperationError::StorageUnavailable)?;
    if payload.is_empty()
        || payload.len() > MAX_DURABLE_OUTBOX_PAYLOAD_BYTES
        || Digest32::of_bytes(&payload) != payload_digest
    {
        return Err(OperationError::CorruptStore("outbox payload"));
    }
    let state: String = row
        .try_get("state")
        .map_err(|_| OperationError::StorageUnavailable)?;
    let attempts_i64: i64 = row
        .try_get("attempts")
        .map_err(|_| OperationError::StorageUnavailable)?;
    let attempts = u32::try_from(attempts_i64)
        .map_err(|_| OperationError::CorruptStore("outbox attempts"))?;
    if attempts > MAX_CLAIM_ATTEMPTS {
        return Err(OperationError::CorruptStore("outbox attempts"));
    }
    let owner_generation = optional_generation(
        row.try_get("owner_generation")
            .map_err(|_| OperationError::StorageUnavailable)?,
        "outbox owner generation",
    )?;
    let lease_expires_at_ms = optional_u64(
        row.try_get("lease_expires_at_ms")
            .map_err(|_| OperationError::StorageUnavailable)?,
        "outbox lease expiry",
    )?;
    let acknowledgement_digest = optional_digest(
        row.try_get("acknowledgement_digest")
            .map_err(|_| OperationError::StorageUnavailable)?,
        "outbox acknowledgement",
    )?;

    let state = match state.as_str() {
        "pending" if owner_generation.is_none()
            && lease_expires_at_ms.is_none()
            && attempts == 0
            && acknowledgement_digest.is_none() =>
        {
            DurableOutboxState::Pending
        }
        "claimed" => DurableOutboxState::Claimed {
            owner_generation: owner_generation
                .ok_or(OperationError::CorruptStore("outbox claimed generation"))?,
            lease_expires_at_ms: lease_expires_at_ms
                .ok_or(OperationError::CorruptStore("outbox claimed lease"))?,
            attempts,
        },
        "acknowledged" => DurableOutboxState::Acknowledged {
            owner_generation: owner_generation
                .ok_or(OperationError::CorruptStore("outbox ack generation"))?,
            acknowledgement_digest: acknowledgement_digest
                .ok_or(OperationError::CorruptStore("outbox ack digest"))?,
            attempts,
        },
        _ => return Err(OperationError::CorruptStore("outbox state")),
    };

    Ok(DurableOutboxRecord {
        intent: OutboxIntent {
            intent_id,
            operation_id,
            destination,
            payload_digest,
        },
        payload,
        state,
    })
}

fn validate_intent(intent: &OutboxIntent, payload: &[u8]) -> Result<(), OperationError> {
    if intent.payload_digest.is_zero()
        || payload.is_empty()
        || payload.len() > MAX_DURABLE_OUTBOX_PAYLOAD_BYTES
        || Digest32::of_bytes(payload) != intent.payload_digest
    {
        return Err(OperationError::InvalidDigest("outbox payload"));
    }
    Ok(())
}

fn stable_id(value: String, field: &'static str) -> Result<StableId, OperationError> {
    StableId::new(value).map_err(|_| OperationError::CorruptStore(field))
}

fn digest_blob(value: Vec<u8>, field: &'static str) -> Result<Digest32, OperationError> {
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| OperationError::CorruptStore(field))?;
    let digest = Digest32::from_array(bytes);
    if digest.is_zero() {
        return Err(OperationError::CorruptStore(field));
    }
    Ok(digest)
}

fn optional_digest(
    value: Option<Vec<u8>>,
    field: &'static str,
) -> Result<Option<Digest32>, OperationError> {
    value.map(|value| digest_blob(value, field)).transpose()
}

fn optional_generation(
    value: Option<String>,
    field: &'static str,
) -> Result<Option<Generation>, OperationError> {
    value
        .map(|value| {
            let parsed = value
                .parse::<u64>()
                .map_err(|_| OperationError::CorruptStore(field))?;
            Generation::new(parsed).map_err(|_| OperationError::CorruptStore(field))
        })
        .transpose()
}

fn optional_u64(
    value: Option<String>,
    field: &'static str,
) -> Result<Option<u64>, OperationError> {
    value
        .map(|value| {
            value
                .parse::<u64>()
                .map_err(|_| OperationError::CorruptStore(field))
        })
        .transpose()
}

#[cfg(test)]
#[path = "durable_outbox_tests.rs"]
mod tests;
