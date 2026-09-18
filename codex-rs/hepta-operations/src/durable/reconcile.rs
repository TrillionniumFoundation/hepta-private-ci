use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::ReconciliationOutcome;

use super::DestinationReceipt;
use super::DurableOperationError;
use super::DurableOperationRecord;
use super::DurableOperationState;
use super::codec::DESTINATION_SELECT;
use super::codec::blob;
use super::codec::decode_destination;
use super::codec::now_millis;
use super::codec::outcome_label;
use super::codec::state_for_outcome;
use super::codec::u64_blob;
use super::store::DurableOperationStore;
use super::store::begin_immediate;
use super::store::load_operation_tx;
use super::unavailable;

impl DurableOperationStore {
    pub async fn record_destination_outcome(
        &self,
        destination: &StableId,
        operation_id: &StableId,
        semantic_digest: Digest32,
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
    ) -> Result<DestinationReceipt, DurableOperationError> {
        if semantic_digest.is_zero() || evidence_digest.is_zero() {
            return Err(DurableOperationError::Invalid(
                "destination semantic/evidence digest is zero",
            ));
        }
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        if let Some(existing) = load_destination_tx(&mut tx, destination, operation_id).await? {
            if existing.semantic_digest == semantic_digest
                && existing.outcome == outcome
                && existing.evidence_digest == evidence_digest
            {
                tx.commit().await.map_err(unavailable)?;
                return Ok(existing);
            }
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        if let Some(existing) =
            load_destination_tombstone_tx(&mut tx, destination, operation_id).await?
        {
            if existing.semantic_digest == semantic_digest
                && existing.outcome == outcome
                && existing.evidence_digest == evidence_digest
            {
                tx.commit().await.map_err(unavailable)?;
                return Ok(existing);
            }
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        sqlx::query(
            "INSERT INTO destination_operation_dedup
             (destination, operation_id, semantic_digest, outcome, evidence_digest, recorded_at_ms)
             VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(destination.as_str())
        .bind(operation_id.as_str())
        .bind(blob(semantic_digest))
        .bind(outcome_label(outcome))
        .bind(blob(evidence_digest))
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let receipt = load_destination_tx(&mut tx, destination, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        tx.commit().await.map_err(unavailable)?;
        Ok(receipt)
    }

    pub async fn destination_receipt(
        &self,
        destination: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<DestinationReceipt>, DurableOperationError> {
        if let Some(receipt) = sqlx::query(DESTINATION_SELECT)
            .bind(destination.as_str())
            .bind(operation_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(unavailable)?
            .map(decode_destination)
            .transpose()?
        {
            return Ok(Some(receipt));
        }
        sqlx::query(
            "SELECT destination, operation_id, semantic_digest, outcome, evidence_digest,
                    recorded_at_ms
             FROM destination_operation_tombstones
             WHERE destination = ? AND operation_id = ?",
        )
        .bind(destination.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?
        .map(decode_destination)
        .transpose()
    }

    pub async fn reconcile_from_destination(
        &self,
        destination_store: &DurableOperationStore,
        scope: &StableId,
        operation_id: &StableId,
        observer_generation: Generation,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        let operation = self
            .get_operation(scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        let receipt = destination_store
            .destination_receipt(&operation.destination, operation_id)
            .await?
            .ok_or(DurableOperationError::UnavailableState)?;
        if receipt.semantic_digest != operation.semantic_digest {
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        self.settle_from_receipt(scope, operation_id, observer_generation, &receipt)
            .await
    }

    async fn settle_from_receipt(
        &self,
        scope: &StableId,
        operation_id: &StableId,
        observer_generation: Generation,
        receipt: &DestinationReceipt,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        let mut tx = begin_immediate(&self.pool).await?;
        let now = now_millis()?;
        let operation = load_operation_tx(&mut tx, scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        if operation.destination != receipt.destination
            || operation.semantic_digest != receipt.semantic_digest
        {
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        let terminal_state = state_for_outcome(receipt.outcome);
        if operation.state.is_terminal() {
            if operation.owner_generation != observer_generation {
                return Err(DurableOperationError::StaleLease);
            }
            if operation.state == terminal_state
                && operation.terminal_evidence_digest == Some(receipt.evidence_digest)
            {
                tx.commit().await.map_err(unavailable)?;
                return Ok(operation);
            }
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        if observer_generation < operation.owner_generation {
            return Err(DurableOperationError::StaleLease);
        }
        if !matches!(
            operation.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(DurableOperationError::UnavailableState);
        }
        let revision = operation
            .revision
            .next()
            .map_err(|_| DurableOperationError::Conflict(operation_id.clone()))?;
        sqlx::query(
            "UPDATE operation_ledger SET owner_generation = ?, state = ?,
             terminal_evidence_digest = ?, revision = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(u64_blob(observer_generation.get()))
        .bind(terminal_state.label())
        .bind(blob(receipt.evidence_digest))
        .bind(u64_blob(revision.get()))
        .bind(now)
        .bind(now)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'settled', worker_id = NULL,
             lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?
             WHERE scope = ? AND operation_id = ?",
        )
        .bind(now)
        .bind(now)
        .bind(scope.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let record = load_operation_tx(&mut tx, scope, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        tx.commit().await.map_err(unavailable)?;
        Ok(record)
    }
}

async fn load_destination_tx(
    tx: &mut Transaction<'_, Sqlite>,
    destination: &StableId,
    operation_id: &StableId,
) -> Result<Option<DestinationReceipt>, DurableOperationError> {
    sqlx::query(DESTINATION_SELECT)
        .bind(destination.as_str())
        .bind(operation_id.as_str())
        .fetch_optional(&mut **tx)
        .await
        .map_err(unavailable)?
        .map(decode_destination)
        .transpose()
}

async fn load_destination_tombstone_tx(
    tx: &mut Transaction<'_, Sqlite>,
    destination: &StableId,
    operation_id: &StableId,
) -> Result<Option<DestinationReceipt>, DurableOperationError> {
    sqlx::query(
        "SELECT destination, operation_id, semantic_digest, outcome, evidence_digest,
                recorded_at_ms
         FROM destination_operation_tombstones
         WHERE destination = ? AND operation_id = ?",
    )
    .bind(destination.as_str())
    .bind(operation_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?
    .map(decode_destination)
    .transpose()
}
