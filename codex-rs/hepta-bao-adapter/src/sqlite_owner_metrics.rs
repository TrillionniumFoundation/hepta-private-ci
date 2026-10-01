//! Existing durable owner metrics implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn metrics(
        &self,
        now_unix_ms: u64,
    ) -> Result<SqliteBaoOwnerMetricsV1, SqliteBaoOwnerErrorV1> {
        if now_unix_ms == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let operation_count = count_tx(&mut tx, "bao_operation").await?;
        let active_consumption_count = count_tx(&mut tx, "bao_consumption").await?;
        let terminal_archive_count = count_tx(&mut tx, "bao_terminal_archive").await?;
        let transition_count = count_tx(&mut tx, "bao_transition").await?;
        let reconciliation_queue_count = count_tx(&mut tx, "bao_reconciliation_queue").await?;
        let claimed_reconciliation_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM bao_reconciliation_queue
             WHERE claim_owner IS NOT NULL AND claim_until_unix_ms > ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let oldest_due_reconciliation: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT MIN(next_attempt_at_unix_ms) FROM bao_reconciliation_queue
             WHERE next_attempt_at_unix_ms <= ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let max_reconciliation_attempts: Option<Vec<u8>> =
            sqlx::query_scalar("SELECT MAX(attempt_count) FROM bao_reconciliation_queue")
                .fetch_one(&mut *tx)
                .await
                .map_err(storage)?;
        let mut rows = sqlx::Executor::fetch(
            &mut *tx,
            "SELECT row_json, updated_at_unix_ms FROM bao_consumption
             WHERE state NOT IN ('succeeded', 'failed')
             ORDER BY updated_at_unix_ms, operation_id",
        );
        let mut pending_by_state = BTreeMap::new();
        let mut pending_by_recovery_action = BTreeMap::new();
        let mut pending_quota_amount = 0_u64;
        let mut post_dispatch_without_receipt = 0_u64;
        let mut observer_pending = 0_u64;
        let mut settlement_pending = 0_u64;
        let mut oldest_pending_at = None::<u64>;
        while let Some(row) = std::future::poll_fn(|context| rows.as_mut().poll_next(context)).await
        {
            let row = row.map_err(storage)?;
            let operation: BaoConsumptionOperationV1 =
                decode_row(&row.try_get::<Vec<u8>, _>("row_json").map_err(storage)?)?;
            validate_consumption_stored(&operation)?;
            if operation.state.is_terminal() {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "terminal row returned by pending query",
                ));
            }
            *pending_by_state.entry(operation.state).or_insert(0) += 1;
            *pending_by_recovery_action
                .entry(operation.state.recovery_action())
                .or_insert(0) += 1;
            if operation.reservation_id.is_some() {
                pending_quota_amount = pending_quota_amount
                    .checked_add(operation.amount)
                    .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
            }
            if operation.state.has_dispatch_fence() && operation.receipt.is_none() {
                post_dispatch_without_receipt += 1;
            }
            if matches!(
                operation.state,
                BaoConsumptionStateV1::DispatchFenced
                    | BaoConsumptionStateV1::DeliveryPrepared
                    | BaoConsumptionStateV1::Indeterminate
            ) {
                observer_pending += 1;
            }
            if matches!(
                operation.state.phase(),
                crate::BaoConsumptionPhaseV1::TerminalEvidence
            ) {
                settlement_pending += 1;
            }
            let updated_at = fixed_u64(
                &row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                    .map_err(storage)?,
            )?;
            oldest_pending_at =
                Some(oldest_pending_at.map_or(updated_at, |oldest| oldest.min(updated_at)));
        }
        drop(rows);
        tx.commit().await.map_err(storage)?;
        let oldest_pending_age_ms =
            oldest_pending_at.map(|value| now_unix_ms.saturating_sub(value));
        let oldest_due_reconciliation_age_ms = oldest_due_reconciliation
            .as_deref()
            .map(fixed_u64)
            .transpose()?
            .map(|value| now_unix_ms.saturating_sub(value));
        let max_reconciliation_attempts = max_reconciliation_attempts
            .as_deref()
            .map(fixed_u64_allow_zero)
            .transpose()?
            .unwrap_or(0);
        let runtime = self
            .runtime_metrics
            .lock()
            .map(|metrics| metrics.snapshot())
            .unwrap_or_else(|_| SqliteBaoOwnerRuntimeMetricsOwnerV1::default().snapshot());
        let database_bytes = metadata_len(self.path.as_path())?;
        let wal_bytes = metadata_len(&sidecar_path(self.path.as_path(), "-wal"))?;
        let shm_bytes = metadata_len(&sidecar_path(self.path.as_path(), "-shm"))?;
        Ok(SqliteBaoOwnerMetricsV1 {
            operation_count,
            active_consumption_count,
            terminal_archive_count,
            transition_count,
            reconciliation_queue_count,
            claimed_reconciliation_count: u64::try_from(claimed_reconciliation_count)
                .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("negative claim count"))?,
            oldest_due_reconciliation_age_ms,
            max_reconciliation_attempts,
            pending_by_state,
            pending_by_recovery_action,
            pending_quota_amount,
            post_dispatch_without_receipt,
            observer_pending,
            settlement_pending,
            oldest_pending_age_ms,
            database_bytes,
            wal_bytes,
            shm_bytes,
            fenced: self.is_fenced(),
            provider_dynamic_execution_blocked: true,
            runtime,
        })
    }
}
