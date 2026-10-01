//! Release an unused claim without inventing a destination outcome.

use std::time::Duration;

use sqlx::Row;

use crate::DispatchClaim;
use crate::DurableOperationError;
use crate::DurableOperationStore;

impl DurableOperationStore {
    /// Defer a claim only while its operation is still Prepared and its exact
    /// lease is live. This is not available after authorize_dispatch: unknown
    /// external work can never be returned to the ordinary dispatch queue.
    pub async fn defer_pre_dispatch_claim_v1(
        &self,
        claim: &DispatchClaim,
        retry_after: Duration,
    ) -> Result<(), DurableOperationError> {
        let delay = u64::try_from(retry_after.as_millis())
            .map_err(|_| DurableOperationError::Invalid("pre-dispatch retry delay"))?;
        if !(1..=3_600_000).contains(&delay) {
            return Err(DurableOperationError::Invalid("pre-dispatch retry delay"));
        }
        let fence = i64::try_from(claim.fence).map_err(|_| DurableOperationError::Capacity)?;
        let next_fence = fence
            .checked_add(1)
            .ok_or(DurableOperationError::Capacity)?;
        let expiry =
            i64::try_from(claim.expires_at_unix_ms).map_err(|_| DurableOperationError::Capacity)?;
        let generation = claim.owner_generation.get().to_be_bytes().to_vec();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let now = self.now_millis()?;
        crate::durable_store::ensure_clock_not_behind(&mut tx, now).await?;
        let eligible = now
            .checked_add(i64::try_from(delay).map_err(|_| DurableOperationError::Capacity)?)
            .ok_or(DurableOperationError::Capacity)?;
        let row = sqlx::query(
            "SELECT l.revision FROM operation_ledger l
             JOIN cross_owner_outbox o ON o.scope_id = l.scope_id
               AND o.operation_id = l.operation_id AND o.destination = l.destination
             WHERE l.scope_id = ? AND l.operation_id = ? AND l.destination = ?
               AND l.semantic_digest = ? AND l.owner_generation = ?
               AND l.state = 'prepared' AND l.writer_fence = ?
               AND o.state = 'leased' AND o.worker_id = ? AND o.fence = ?
               AND o.owner_generation = ? AND o.lease_until_ms = ?
               AND o.lease_until_ms > ? AND l.updated_at_ms <= ?
               AND o.updated_at_ms <= ?",
        )
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .bind(claim.intent.destination.as_str())
        .bind(claim.intent.semantic_digest().as_array().as_slice())
        .bind(&generation)
        .bind(fence)
        .bind(claim.worker_id.as_str())
        .bind(fence)
        .bind(&generation)
        .bind(expiry)
        .bind(now)
        .bind(now)
        .bind(now)
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Err(DurableOperationError::Conflict(
                claim.intent.operation_id.clone(),
            ));
        };
        let revision: i64 = row.try_get("revision").map_err(unavailable)?;
        let revision = revision
            .checked_add(1)
            .ok_or(DurableOperationError::Capacity)?;
        sqlx::query(
            "UPDATE cross_owner_outbox SET state = 'queued', fence = ?,
             worker_id = NULL, lease_until_ms = NULL, next_eligible_at_ms = ?,
             updated_at_ms = ?, attempts = CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END
             WHERE scope_id = ? AND operation_id = ? AND destination = ?",
        )
        .bind(next_fence)
        .bind(eligible)
        .bind(now)
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .bind(claim.intent.destination.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "UPDATE operation_ledger SET writer_fence = ?, revision = ?, updated_at_ms = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(next_fence)
        .bind(revision)
        .bind(now)
        .bind(claim.intent.scope_id.as_str())
        .bind(claim.intent.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)
    }
}

fn unavailable(error: sqlx::Error) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::DurableOperationIntentV1;
    use crate::DurableOperationState;
    use crate::DurableOutboxState;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    #[tokio::test]
    async fn unused_claim_deferral_preserves_identity_and_fences_old_claim() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let store = DurableOperationStore::open(&directory.path().join("operations.sqlite"))
            .await
            .expect("operations");
        let intent = DurableOperationIntentV1 {
            scope_id: id("run"),
            operation_id: id("decision"),
            expected_predecessor: None,
            destination: id("learning.ledger"),
            payload_digest: Digest32::of_bytes(b"immutable payload"),
            owner_generation: Generation::new(1).expect("generation"),
        };
        store.prepare_intent(&intent).await.expect("prepare");
        let claim = store
            .claim_next(
                &intent.destination,
                &id("worker"),
                intent.owner_generation,
                Duration::from_secs(30),
            )
            .await
            .expect("claim")
            .expect("queued operation");
        store
            .defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100))
            .await
            .expect("defer unused claim");
        assert!(
            store
                .defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100))
                .await
                .is_err()
        );
        let record = store
            .operation(&intent.scope_id, &intent.operation_id)
            .await
            .expect("read")
            .expect("operation");
        assert_eq!(record.intent, intent);
        assert_eq!(record.state, DurableOperationState::Prepared);
        assert!(record.writer_fence > claim.fence);
        let outbox = store
            .outbox_status(&intent.destination, &intent.scope_id, &intent.operation_id)
            .await
            .expect("outbox")
            .expect("outbox row");
        assert_eq!(outbox.state, DurableOutboxState::Queued);
        assert_eq!(outbox.attempts, 0);
        store.close().await;
    }

    #[tokio::test]
    async fn post_dispatch_claim_cannot_be_deferred_for_reexecution() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let store = DurableOperationStore::open(&directory.path().join("operations.sqlite"))
            .await
            .expect("operations");
        let intent = DurableOperationIntentV1 {
            scope_id: id("run"),
            operation_id: id("decision"),
            expected_predecessor: None,
            destination: id("learning.ledger"),
            payload_digest: Digest32::of_bytes(b"payload"),
            owner_generation: Generation::new(1).expect("generation"),
        };
        store.prepare_intent(&intent).await.expect("prepare");
        let claim = store
            .claim_next(
                &intent.destination,
                &id("worker"),
                intent.owner_generation,
                Duration::from_secs(30),
            )
            .await
            .expect("claim")
            .expect("operation");
        sqlx::query(
            "UPDATE operation_ledger
             SET state = 'dispatching', authority_epoch = ?, authority_digest = ?
             WHERE scope_id = ? AND operation_id = ?",
        )
        .bind(1_u64.to_be_bytes().to_vec())
        .bind(Digest32::of_bytes(b"authority").as_array().to_vec())
        .bind(intent.scope_id.as_str())
        .bind(intent.operation_id.as_str())
        .execute(&store.pool)
        .await
        .expect("dispatch cut");
        assert!(
            store
                .defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100))
                .await
                .is_err()
        );
        assert_eq!(
            store
                .operation(&intent.scope_id, &intent.operation_id)
                .await
                .expect("read")
                .expect("row")
                .state,
            DurableOperationState::Dispatching
        );
        store.close().await;
    }
}
