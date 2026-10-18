//! Existing durable owner reconciliation implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn due_reconciliation(
        &self,
        now_unix_ms: u64,
        limit: u32,
    ) -> Result<Vec<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
        if now_unix_ms == 0 || limit == 0 || limit > 1024 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT operation_id FROM bao_reconciliation_queue
             WHERE next_attempt_at_unix_ms <= ?
               AND (claim_owner IS NULL OR claim_until_unix_ms <= ?)
             ORDER BY next_attempt_at_unix_ms, attempt_count, operation_id LIMIT ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut rows = Vec::with_capacity(ids.len());
        for id in ids {
            rows.push(load_consumption_current_tx(&mut tx, &id).await?.ok_or(
                SqliteBaoOwnerErrorV1::CorruptState("reconciliation row is missing"),
            )?);
        }
        tx.commit().await.map_err(storage)?;
        Ok(rows)
    }

    /// Lease one named recovery operation. This is used by explicit operator
    /// reconciliation; batch workers should use `claim_due_reconciliation`.
    pub async fn claim_reconciliation_operation(
        &self,
        worker_id: &str,
        operation_id: &str,
        now_unix_ms: u64,
        lease_ms: u64,
    ) -> Result<SqliteReconciliationClaimV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(worker_id)?;
        validate_identifier(operation_id)?;
        if now_unix_ms == 0 || lease_ms == 0 || lease_ms > MAX_RECOVERY_LEASE_MS {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let claim_until_unix_ms = now_unix_ms
            .checked_add(lease_ms)
            .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
        let mut tx = self.begin().await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let record = load_consumption_current_tx(&mut tx, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if record.operation.state.is_terminal() {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        let claim_row = sqlx::query(
            "SELECT claim_generation, attempt_count
             FROM bao_reconciliation_queue WHERE operation_id = ?",
        )
        .bind(operation_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let claim_generation = fixed_u64_allow_zero(
            &claim_row
                .try_get::<Vec<u8>, _>("claim_generation")
                .map_err(storage)?,
        )?
        .checked_add(1)
        .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
        let changed = sqlx::query(
            "UPDATE bao_reconciliation_queue
             SET claim_owner = ?, claim_until_unix_ms = ?, claim_generation = ?
             WHERE operation_id = ?
               AND (claim_owner IS NULL OR claim_until_unix_ms <= ?)",
        )
        .bind(worker_id)
        .bind(u64_bytes(claim_until_unix_ms).as_slice())
        .bind(u64_bytes(claim_generation).as_slice())
        .bind(operation_id)
        .bind(u64_bytes(now_unix_ms).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::WriterBusy);
        }
        self.commit(tx).await?;
        Ok(SqliteReconciliationClaimV1 {
            worker_id: worker_id.to_owned(),
            record,
            claim_generation,
            claim_until_unix_ms,
            attempt_count: fixed_u64_allow_zero(
                &claim_row
                    .try_get::<Vec<u8>, _>("attempt_count")
                    .map_err(storage)?,
            )?,
        })
    }

    /// Atomically lease a fair, bounded batch of due recovery work. Claims are
    /// operational coordination state and expire automatically after a worker
    /// crash; they do not enter the authoritative checkpoint digest.
    pub async fn claim_due_reconciliation(
        &self,
        worker_id: &str,
        now_unix_ms: u64,
        lease_ms: u64,
        limit: u32,
    ) -> Result<Vec<SqliteReconciliationClaimV1>, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(worker_id)?;
        if now_unix_ms == 0
            || lease_ms == 0
            || lease_ms > MAX_RECOVERY_LEASE_MS
            || limit == 0
            || limit > 1024
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let claim_until_unix_ms = now_unix_ms
            .checked_add(lease_ms)
            .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
        let mut tx = self.begin().await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT operation_id FROM bao_reconciliation_queue
             WHERE next_attempt_at_unix_ms <= ?
               AND (claim_owner IS NULL OR claim_until_unix_ms <= ?)
             ORDER BY next_attempt_at_unix_ms, attempt_count, operation_id LIMIT ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut claims = Vec::with_capacity(ids.len());
        for operation_id in ids {
            let claim_row = sqlx::query(
                "SELECT claim_generation, attempt_count
                 FROM bao_reconciliation_queue WHERE operation_id = ?",
            )
            .bind(&operation_id)
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
            let claim_generation = fixed_u64_allow_zero(
                &claim_row
                    .try_get::<Vec<u8>, _>("claim_generation")
                    .map_err(storage)?,
            )?
            .checked_add(1)
            .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
            let changed = sqlx::query(
                "UPDATE bao_reconciliation_queue
                 SET claim_owner = ?, claim_until_unix_ms = ?, claim_generation = ?
                 WHERE operation_id = ?
                   AND (claim_owner IS NULL OR claim_until_unix_ms <= ?)",
            )
            .bind(worker_id)
            .bind(u64_bytes(claim_until_unix_ms).as_slice())
            .bind(u64_bytes(claim_generation).as_slice())
            .bind(&operation_id)
            .bind(u64_bytes(now_unix_ms).as_slice())
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?
            .rows_affected();
            if changed != 1 {
                return Err(SqliteBaoOwnerErrorV1::WriterBusy);
            }
            let record = load_consumption_current_tx(&mut tx, &operation_id)
                .await?
                .ok_or(SqliteBaoOwnerErrorV1::CorruptState(
                    "claimed reconciliation row is missing",
                ))?;
            claims.push(SqliteReconciliationClaimV1 {
                worker_id: worker_id.to_owned(),
                record,
                claim_generation,
                claim_until_unix_ms,
                attempt_count: fixed_u64_allow_zero(
                    &claim_row
                        .try_get::<Vec<u8>, _>("attempt_count")
                        .map_err(storage)?,
                )?,
            });
        }
        self.commit(tx).await?;
        Ok(claims)
    }

    pub async fn release_reconciliation_claim(
        &self,
        worker_id: &str,
        operation_id: &str,
        claim_generation: u64,
    ) -> Result<(), SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(worker_id)?;
        validate_identifier(operation_id)?;
        if claim_generation == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.begin().await?;
        let changed = sqlx::query(
            "UPDATE bao_reconciliation_queue
             SET claim_owner = NULL, claim_until_unix_ms = NULL
             WHERE operation_id = ? AND claim_owner = ? AND claim_generation = ?",
        )
        .bind(operation_id)
        .bind(worker_id)
        .bind(u64_bytes(claim_generation).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::WriterBusy);
        }
        self.commit(tx).await
    }

    pub async fn record_reconciliation_failure(
        &self,
        operation_id: &str,
        expected_revision: u64,
        observed_at_unix_ms: u64,
        next_attempt_at_unix_ms: u64,
        error_sha256: [u8; 32],
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        self.record_reconciliation_failure_inner(
            operation_id,
            expected_revision,
            observed_at_unix_ms,
            next_attempt_at_unix_ms,
            error_sha256,
            None,
        )
        .await
    }

    pub async fn record_claimed_reconciliation_failure(
        &self,
        claim: &SqliteReconciliationClaimV1,
        observed_at_unix_ms: u64,
        next_attempt_at_unix_ms: u64,
        error_sha256: [u8; 32],
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        validate_identifier(&claim.worker_id)?;
        if claim.claim_generation == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        self.record_reconciliation_failure_inner(
            &claim.record.operation.operation_id,
            claim.record.revision,
            observed_at_unix_ms,
            next_attempt_at_unix_ms,
            error_sha256,
            Some((&claim.worker_id, claim.claim_generation)),
        )
        .await
    }

    pub(super) async fn record_reconciliation_failure_inner(
        &self,
        operation_id: &str,
        expected_revision: u64,
        observed_at_unix_ms: u64,
        next_attempt_at_unix_ms: u64,
        error_sha256: [u8; 32],
        claim: Option<(&str, u64)>,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(operation_id)?;
        if expected_revision == 0
            || observed_at_unix_ms == 0
            || next_attempt_at_unix_ms < observed_at_unix_ms
            || error_sha256 == [0; 32]
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.begin().await?;
        advance_time(&mut tx, observed_at_unix_ms).await?;
        let current = load_consumption_current_tx(&mut tx, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.revision != expected_revision
            || matches!(
                current.operation.state,
                BaoConsumptionStateV1::Succeeded | BaoConsumptionStateV1::Failed
            )
        {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        let claim_row = sqlx::query(
            "SELECT claim_owner, claim_until_unix_ms, claim_generation
             FROM bao_reconciliation_queue WHERE operation_id = ?",
        )
        .bind(operation_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        let claim_owner = claim_row
            .try_get::<Option<String>, _>("claim_owner")
            .map_err(storage)?;
        let claim_until = claim_row
            .try_get::<Option<Vec<u8>>, _>("claim_until_unix_ms")
            .map_err(storage)?
            .as_deref()
            .map(fixed_u64)
            .transpose()?;
        let persisted_generation = fixed_u64_allow_zero(
            &claim_row
                .try_get::<Vec<u8>, _>("claim_generation")
                .map_err(storage)?,
        )?;
        match claim {
            Some((worker_id, claim_generation)) => {
                if claim_owner.as_deref() != Some(worker_id)
                    || persisted_generation != claim_generation
                    || claim_until.is_none_or(|until| until < observed_at_unix_ms)
                {
                    return Err(SqliteBaoOwnerErrorV1::WriterBusy);
                }
            }
            None => {
                if claim_owner.is_some()
                    && claim_until.is_some_and(|until| until > observed_at_unix_ms)
                {
                    return Err(SqliteBaoOwnerErrorV1::WriterBusy);
                }
            }
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_reconciliation_queue")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        let exists: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM bao_reconciliation_queue WHERE operation_id = ?)",
        )
        .bind(operation_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if !exists && count >= MAX_RECONCILIATION_ROWS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let attempts = reconciliation_attempts(&mut tx, operation_id)
            .await?
            .checked_add(1)
            .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
        let revision = next_revision(&mut tx).await?;
        let mut operation = current.operation.clone();
        operation.updated_revision = revision;
        validate_consumption_input(&operation)?;
        let row_json = encode_row(&operation)?;
        sqlx::query(
            "INSERT INTO bao_reconciliation_queue
             (operation_id, reason, next_attempt_at_unix_ms, attempt_count,
              last_error_sha256, claim_owner, claim_until_unix_ms, claim_generation)
             VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)
             ON CONFLICT(operation_id) DO UPDATE SET
             reason = excluded.reason,
             next_attempt_at_unix_ms = excluded.next_attempt_at_unix_ms,
             attempt_count = excluded.attempt_count,
             last_error_sha256 = excluded.last_error_sha256,
             claim_owner = NULL,
             claim_until_unix_ms = NULL",
        )
        .bind(operation_id)
        .bind(state_text(current.operation.state))
        .bind(u64_bytes(next_attempt_at_unix_ms).as_slice())
        .bind(u64_bytes(attempts).as_slice())
        .bind(error_sha256.as_slice())
        .bind(u64_bytes(persisted_generation).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        let changed = sqlx::query(
            "UPDATE bao_consumption SET row_json = ?, owner_revision = ?, updated_at_unix_ms = ?
             WHERE operation_id = ? AND owner_revision = ?",
        )
        .bind(&row_json)
        .bind(u64_bytes(revision).as_slice())
        .bind(u64_bytes(observed_at_unix_ms).as_slice())
        .bind(operation_id)
        .bind(u64_bytes(expected_revision).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query("UPDATE bao_operation SET updated_at_unix_ms = ? WHERE operation_id = ?")
            .bind(u64_bytes(observed_at_unix_ms).as_slice())
            .bind(operation_id)
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            operation_id,
            Some(state_text(current.operation.state)),
            state_text(current.operation.state),
            error_sha256,
            observed_at_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, observed_at_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteConsumptionRecordV1 {
            operation,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: observed_at_unix_ms,
        })
    }
}
