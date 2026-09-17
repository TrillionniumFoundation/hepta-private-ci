use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::DispatchClaim;
use crate::DurableOperationError;
use crate::DurableOperationState;
use crate::DurableOperationStore;
use crate::MAX_DURABLE_LEASE_MS;
use crate::MAX_DURABLE_OUTBOX_ATTEMPTS;

impl DurableOperationStore {
    /// Claim one exact prepared operation rather than whichever destination row
    /// sorts first. Interactive product callers use this after `prepare_intent`
    /// so a final-use grant can never be accidentally consumed for an older
    /// queued operation.
    pub async fn claim_operation(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        worker_id: &StableId,
        owner_generation: Generation,
        lease: Duration,
    ) -> Result<Option<DispatchClaim>, DurableOperationError> {
        let lease_ms = u64::try_from(lease.as_millis())
            .map_err(|_| DurableOperationError::Invalid("lease duration"))?;
        if !(1..=MAX_DURABLE_LEASE_MS).contains(&lease_ms) {
            return Err(DurableOperationError::Invalid("lease duration"));
        }
        let now = now_millis()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let candidate = sqlx::query(
            "SELECT l.destination, l.state AS operation_state, l.owner_generation AS ledger_generation,
                    l.revision, o.state AS outbox_state, o.owner_generation AS outbox_generation,
                    o.fence, o.attempts, o.next_eligible_at_ms
             FROM operation_ledger l
             JOIN cross_owner_outbox o ON o.scope_id = l.scope_id AND o.operation_id = l.operation_id
             WHERE l.scope_id = ? AND l.operation_id = ?",
        )
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        let Some(candidate) = candidate else {
            return Err(DurableOperationError::Missing(operation_id.clone()));
        };
        let operation_state: String = candidate
            .try_get("operation_state")
            .map_err(unavailable)?;
        let operation_state = DurableOperationState::parse(&operation_state)?;
        let outbox_state: String = candidate.try_get("outbox_state").map_err(unavailable)?;
        let next_eligible: i64 = candidate
            .try_get("next_eligible_at_ms")
            .map_err(unavailable)?;
        if operation_state != DurableOperationState::Prepared
            || outbox_state != "queued"
            || next_eligible > now
        {
            tx.commit().await.map_err(unavailable)?;
            return Ok(None);
        }
        let ledger_generation = decode_u64(
            candidate
                .try_get::<Vec<u8>, _>("ledger_generation")
                .map_err(unavailable)?,
        )?;
        let outbox_generation = decode_u64(
            candidate
                .try_get::<Vec<u8>, _>("outbox_generation")
                .map_err(unavailable)?,
        )?;
        let current_generation = ledger_generation.max(outbox_generation);
        if owner_generation.get() < current_generation {
            return Err(DurableOperationError::StaleGeneration);
        }
        let attempts: i64 = candidate.try_get("attempts").map_err(unavailable)?;
        let attempts = u32::try_from(attempts)
            .map_err(|_| DurableOperationError::Corrupt("invalid outbox attempts".to_owned()))?;
        if attempts >= MAX_DURABLE_OUTBOX_ATTEMPTS {
            return Err(DurableOperationError::Capacity);
        }
        let fence: i64 = candidate.try_get("fence").map_err(unavailable)?;
        let fence = u64::try_from(fence)
            .map_err(|_| DurableOperationError::Corrupt("invalid outbox fence".to_owned()))?
            .checked_add(1)
            .ok_or(DurableOperationError::Capacity)?;
        let revision: i64 = candidate.try_get("revision").map_err(unavailable)?;
        let revision = u64::try_from(revision)
            .map_err(|_| DurableOperationError::Corrupt("invalid operation revision".to_owned()))?
            .checked_add(1)
            .ok_or(DurableOperationError::Capacity)?;
        let lease_until = now
            .checked_add(i64::try_from(lease_ms).map_err(|_| DurableOperationError::Capacity)?)
            .ok_or(DurableOperationError::Capacity)?;
        let destination: String = candidate.try_get("destination").map_err(unavailable)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'leased', fence = ?, attempts = ?, worker_id = ?,
                    owner_generation = ?, lease_until_ms = ?, updated_at_ms = ?
             WHERE destination = ? AND scope_id = ? AND operation_id = ? AND state = 'queued'",
        )
        .bind(to_i64(fence)?)
        .bind(i64::from(attempts + 1))
        .bind(worker_id.as_str())
        .bind(owner_generation.get().to_be_bytes().to_vec())
        .bind(lease_until)
        .bind(now)
        .bind(&destination)
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "UPDATE operation_ledger SET owner_generation = ?, writer_fence = ?, revision = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ? AND state = 'prepared'",
        )
        .bind(owner_generation.get().to_be_bytes().to_vec())
        .bind(to_i64(fence)?)
        .bind(to_i64(revision)?)
        .bind(now)
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        let operation = self
            .operation(scope_id, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        Ok(Some(DispatchClaim {
            intent: operation.intent,
            worker_id: worker_id.clone(),
            owner_generation,
            fence,
            attempts: attempts + 1,
            expires_at_unix_ms: u64::try_from(lease_until)
                .map_err(|_| DurableOperationError::Capacity)?,
        }))
    }
}

fn decode_u64(value: Vec<u8>) -> Result<u64, DurableOperationError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| DurableOperationError::Corrupt("invalid generation width".to_owned()))?;
    Ok(u64::from_be_bytes(bytes))
}

fn to_i64(value: u64) -> Result<i64, DurableOperationError> {
    i64::try_from(value).map_err(|_| DurableOperationError::Capacity)
}

fn now_millis() -> Result<i64, DurableOperationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?
        .as_millis();
    i64::try_from(millis).map_err(|_| DurableOperationError::Capacity)
}

fn unavailable(error: sqlx::Error) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}
