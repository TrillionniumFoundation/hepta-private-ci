use std::time::Duration;

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
    /// Claim this exact Prepared operation. A possible dispatch remains
    /// reconcile-only, including when an interactive caller reopens the store.
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
        // Use the existing recovery state machine: only an unused Prepared
        // lease can become queued. Dispatching becomes Indeterminate instead.
        self.recover_expired_leases().await?;
        let operation = self
            .operation(scope_id, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        let mut intent = operation.intent;
        let semantic_digest = intent.semantic_digest();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let now = self.now_millis()?;
        crate::durable_store::ensure_clock_not_behind(&mut tx, now).await?;
        // The pre-read supplies only immutable intent fields. Compare their
        // complete semantic identity inside the transaction before using them.
        let candidate = sqlx::query(
            "SELECT l.state AS operation_state, l.owner_generation AS ledger_generation,
                    l.revision, l.updated_at_ms AS ledger_updated,
                    o.state AS outbox_state, o.owner_generation AS outbox_generation,
                    o.fence, o.attempts, o.next_eligible_at_ms,
                    o.updated_at_ms AS outbox_updated
             FROM operation_ledger l
             JOIN cross_owner_outbox o ON o.scope_id = l.scope_id
               AND o.operation_id = l.operation_id AND o.destination = l.destination
               AND o.payload_digest = l.payload_digest
             WHERE l.scope_id = ? AND l.operation_id = ? AND l.semantic_digest = ?",
        )
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .bind(semantic_digest.as_array().as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        let Some(candidate) = candidate else {
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        };
        let ledger_updated: i64 = candidate.try_get("ledger_updated").map_err(unavailable)?;
        let outbox_updated: i64 = candidate.try_get("outbox_updated").map_err(unavailable)?;
        if now < ledger_updated || now < outbox_updated {
            return Err(DurableOperationError::ClockRollback);
        }
        let operation_state: String = candidate.try_get("operation_state").map_err(unavailable)?;
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
        if owner_generation.get() < ledger_generation.max(outbox_generation) {
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
        let expires_at_unix_ms =
            u64::try_from(lease_until).map_err(|_| DurableOperationError::Capacity)?;
        let outbox = sqlx::query(
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
        .bind(intent.destination.as_str())
        .bind(scope_id.as_str())
        .bind(operation_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let ledger = sqlx::query(
            "UPDATE operation_ledger SET owner_generation = ?, writer_fence = ?, revision = ?,
                    updated_at_ms = ?
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
        if outbox.rows_affected() != 1 || ledger.rows_affected() != 1 {
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        intent.owner_generation = owner_generation;
        let claim = DispatchClaim {
            intent,
            worker_id: worker_id.clone(),
            owner_generation,
            fence,
            attempts: attempts + 1,
            expires_at_unix_ms,
        };
        tx.commit().await.map_err(unavailable)?;
        // No post-commit read: a successor may already have adopted the row.
        // Its identity must never be mixed into this generation's old claim.
        Ok(Some(claim))
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

fn unavailable(error: sqlx::Error) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

#[cfg(test)]
#[path = "durable_claim_clock_tests.rs"]
mod clock_tests;

#[cfg(test)]
mod recovery_tests {
    use codex_hepta_types::Digest32;

    use super::*;
    use crate::DurableOperationIntentV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn intent() -> DurableOperationIntentV1 {
        DurableOperationIntentV1 {
            scope_id: id("run.exact"),
            operation_id: id("decision.exact"),
            expected_predecessor: None,
            destination: id("learning.ledger"),
            payload_digest: Digest32::of_bytes(b"immutable decision"),
            owner_generation: Generation::new(1).expect("generation"),
        }
    }

    #[tokio::test]
    async fn exact_claim_freezes_the_adopted_intent_generation() {
        let directory = tempfile::tempdir().expect("directory");
        let store = DurableOperationStore::open(&directory.path().join("operations.sqlite"))
            .await
            .expect("store");
        let original = intent();
        store.prepare_intent(&original).await.expect("prepare");
        let generation = Generation::new(2).expect("generation");
        let claim = store
            .claim_operation(
                &original.scope_id,
                &original.operation_id,
                &id("worker"),
                generation,
                Duration::from_secs(30),
            )
            .await
            .expect("claim")
            .expect("prepared operation");
        let mut expected = original.clone();
        expected.owner_generation = generation;
        assert_eq!(claim.intent, expected);
        assert_eq!(claim.owner_generation, generation);
        assert_eq!(claim.intent.semantic_digest(), original.semantic_digest());
        store.close().await;
    }

    #[tokio::test]
    async fn exact_claim_recovers_only_an_unused_expired_lease() {
        let directory = tempfile::tempdir().expect("directory");
        let store = DurableOperationStore::open(&directory.path().join("operations.sqlite"))
            .await
            .expect("store");
        let original = intent();
        store.prepare_intent(&original).await.expect("prepare");
        let old = store
            .claim_operation(
                &original.scope_id,
                &original.operation_id,
                &id("old"),
                original.owner_generation,
                Duration::from_millis(1),
            )
            .await
            .expect("claim")
            .expect("operation");
        // Let a valid unused lease expire. Never rewrite immutable creation
        // metadata or disable SQL constraints merely to simulate process loss.
        tokio::time::sleep(Duration::from_millis(5)).await;
        let new = store
            .claim_operation(
                &original.scope_id,
                &original.operation_id,
                &id("new"),
                Generation::new(2).expect("generation"),
                Duration::from_millis(1),
            )
            .await
            .expect("reclaim")
            .expect("unused operation is reclaimable");
        assert!(new.fence > old.fence);
        assert_eq!(new.intent.semantic_digest(), old.intent.semantic_digest());
        assert!(
            store
                .defer_pre_dispatch_claim_v1(&old, Duration::from_millis(100))
                .await
                .is_err()
        );
        sqlx::query(
            "UPDATE operation_ledger SET state = 'dispatching', authority_epoch = ?,
                    authority_digest = ?",
        )
        .bind(1_u64.to_be_bytes().to_vec())
        .bind(Digest32::of_bytes(b"authority").as_array().to_vec())
        .execute(&store.pool)
        .await
        .expect("possible dispatch cut");
        tokio::time::sleep(Duration::from_millis(5)).await;
        assert!(
            store
                .claim_operation(
                    &original.scope_id,
                    &original.operation_id,
                    &id("successor"),
                    Generation::new(3).expect("generation"),
                    Duration::from_millis(1),
                )
                .await
                .expect("observe unresolved operation")
                .is_none()
        );
        assert_eq!(
            store
                .operation(&original.scope_id, &original.operation_id)
                .await
                .expect("read")
                .expect("operation")
                .state,
            DurableOperationState::Indeterminate
        );
        store.close().await;
    }
}
