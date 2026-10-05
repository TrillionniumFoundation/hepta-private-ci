//! Existing durable owner consumption implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn claim_consumption(
        &self,
        operation: BaoConsumptionOperationV1,
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionClaimV1, SqliteBaoOwnerErrorV1> {
        Ok(self
            .claim_consumption_inner(operation, now_unix_ms, None)
            .await?
            .claim)
    }

    /// Atomically insert a new operation and lease its reconciliation row to
    /// the forward executor. This closes the gap in which a recovery worker
    /// could observe `Claimed` and seal non-admission before the original
    /// forward task reaches AuthBus. Exact retries return the historical row
    /// without an execution lease and must enter reconciliation instead.
    pub async fn claim_consumption_for_execution(
        &self,
        operation: BaoConsumptionOperationV1,
        now_unix_ms: u64,
        execution_owner: &str,
        lease_ms: u64,
    ) -> Result<SqliteConsumptionExecutionClaimV1, SqliteBaoOwnerErrorV1> {
        validate_identifier(execution_owner)?;
        if lease_ms == 0 || lease_ms > MAX_RECOVERY_LEASE_MS {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        self.claim_consumption_inner(operation, now_unix_ms, Some((execution_owner, lease_ms)))
            .await
    }

    pub(super) async fn claim_consumption_inner(
        &self,
        mut operation: BaoConsumptionOperationV1,
        now_unix_ms: u64,
        execution: Option<(&str, u64)>,
    ) -> Result<SqliteConsumptionExecutionClaimV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_consumption_input(&operation)?;
        if operation.state != BaoConsumptionStateV1::Claimed
            || operation.reservation_id.is_some()
            || operation.receipt.is_some()
            || operation.has_terminal_fields()
            || now_unix_ms == 0
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let claim_until_unix_ms = execution
            .map(|(_, lease_ms)| {
                now_unix_ms
                    .checked_add(lease_ms)
                    .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)
            })
            .transpose()?;
        let mut tx = self.begin().await?;
        advance_time(&mut tx, now_unix_ms).await?;
        if let Some(existing) = load_consumption_any_tx(&mut tx, &operation.operation_id).await? {
            if existing.operation.same_identity(&operation) {
                tx.rollback().await.map_err(storage)?;
                return Ok(SqliteConsumptionExecutionClaimV1 {
                    claim: SqliteConsumptionClaimV1 {
                        record: existing,
                        inserted: false,
                    },
                    execution: None,
                });
            }
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if operation_identity_exists(&mut tx, &operation.operation_id).await? {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        let active: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_consumption")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if active >= MAX_ACTIVE_OPERATIONS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let revision = next_revision(&mut tx).await?;
        operation.created_revision = revision;
        operation.updated_revision = revision;
        validate_consumption_input(&operation)?;
        let row_json = encode_row(&operation)?;
        sqlx::query(
            "INSERT INTO bao_operation
             (operation_id, domain, kind, semantic_sha256, created_at_unix_ms,
              updated_at_unix_ms, terminal)
             VALUES (?, 'consumption', 'read', ?, ?, ?, 0)",
        )
        .bind(&operation.operation_id)
        .bind(operation.semantic_sha256.as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_consumption(
            &mut tx,
            &operation,
            revision,
            now_unix_ms,
            now_unix_ms,
            &row_json,
        )
        .await?;
        insert_transition(
            &mut tx,
            revision,
            &operation.operation_id,
            None,
            state_text(operation.state),
            Digest32::of_bytes(&row_json).into_array(),
            now_unix_ms,
        )
        .await?;
        upsert_reconciliation(
            &mut tx,
            &operation.operation_id,
            operation.state,
            now_unix_ms,
        )
        .await?;
        let record = SqliteConsumptionRecordV1 {
            operation,
            revision,
            created_at_unix_ms: now_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        };
        let execution_claim = if let Some((execution_owner, _)) = execution {
            let claim_generation = 1_u64;
            let changed = sqlx::query(
                "UPDATE bao_reconciliation_queue
                 SET claim_owner = ?, claim_until_unix_ms = ?, claim_generation = ?
                 WHERE operation_id = ? AND claim_owner IS NULL",
            )
            .bind(execution_owner)
            .bind(
                u64_bytes(claim_until_unix_ms.ok_or(SqliteBaoOwnerErrorV1::InvalidInput)?)
                    .as_slice(),
            )
            .bind(u64_bytes(claim_generation).as_slice())
            .bind(&record.operation.operation_id)
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?
            .rows_affected();
            if changed != 1 {
                return Err(SqliteBaoOwnerErrorV1::WriterBusy);
            }
            Some(SqliteReconciliationClaimV1 {
                worker_id: execution_owner.to_owned(),
                record: record.clone(),
                claim_generation,
                claim_until_unix_ms: claim_until_unix_ms
                    .ok_or(SqliteBaoOwnerErrorV1::InvalidInput)?,
                attempt_count: 0,
            })
        } else {
            None
        };
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteConsumptionExecutionClaimV1 {
            claim: SqliteConsumptionClaimV1 {
                record,
                inserted: true,
            },
            execution: execution_claim,
        })
    }

    pub async fn consumption_result(
        &self,
        operation_id: &str,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        validate_identifier(operation_id)?;
        load_consumption_any_pool(&self.pool, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)
    }

    /// Generation-fenced generic transition used by the registered host.
    /// Exact duplicate state is a no-op; changed identity or terminal evidence
    /// conflicts even when the requested state name is the same.
    pub async fn transition_consumption(
        &self,
        operation_id: &str,
        expected_revision: u64,
        mut next: BaoConsumptionOperationV1,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(operation_id)?;
        validate_consumption_input(&next)?;
        if next.operation_id != operation_id
            || expected_revision == 0
            || evidence_sha256 == [0; 32]
            || now_unix_ms == 0
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.begin().await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let current = load_consumption_current_tx(&mut tx, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.operation == next {
            let existing_evidence = establishing_transition_evidence_tx(
                &mut tx,
                operation_id,
                state_text(current.operation.state),
            )
            .await?;
            tx.rollback().await.map_err(storage)?;
            return if existing_evidence == evidence_sha256 {
                Ok(current)
            } else {
                Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
            };
        }
        if current.revision != expected_revision {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        if !current.operation.same_identity(&next)
            || (current.operation.reservation_id.is_some()
                && current.operation.reservation_id != next.reservation_id)
        {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if current.operation.receipt.is_some() && current.operation.receipt != next.receipt {
            return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
        }
        if !current.operation.state.allows_transition_to(next.state)
            || current.operation.terminal_fields_differ(&next)
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        let revision = next_revision(&mut tx).await?;
        next.created_revision = current.operation.created_revision.max(1);
        next.updated_revision = revision;
        validate_consumption_input(&next)?;
        let row_json = encode_row(&next)?;
        let terminal = matches!(
            next.state,
            BaoConsumptionStateV1::Succeeded | BaoConsumptionStateV1::Failed
        );
        let changed = sqlx::query(
            "UPDATE bao_consumption SET
             state = ?, reservation_id = ?, terminal_kind = ?, terminal_code = ?,
             terminal_evidence_sha256 = ?, terminal_observed_cost = ?, row_json = ?,
             owner_revision = ?, updated_at_unix_ms = ?
             WHERE operation_id = ? AND owner_revision = ?",
        )
        .bind(state_text(next.state))
        .bind(next.reservation_id.as_deref())
        .bind(next.terminal_kind.as_deref())
        .bind(next.terminal_code.as_deref())
        .bind(next.terminal_evidence_sha256.map(|value| value.to_vec()))
        .bind(
            next.terminal_observed_cost
                .map(|value| u64_bytes(value).to_vec()),
        )
        .bind(&row_json)
        .bind(u64_bytes(revision).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(operation_id)
        .bind(u64_bytes(expected_revision).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query(
            "UPDATE bao_operation SET updated_at_unix_ms = ?, terminal = ?
             WHERE operation_id = ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(if terminal { 1_i64 } else { 0_i64 })
        .bind(operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            operation_id,
            Some(state_text(current.operation.state)),
            state_text(next.state),
            evidence_sha256,
            now_unix_ms,
        )
        .await?;
        if terminal {
            sqlx::query("DELETE FROM bao_reconciliation_queue WHERE operation_id = ?")
                .bind(operation_id)
                .execute(&mut *tx)
                .await
                .map_err(map_write_error)?;
        } else {
            upsert_reconciliation(&mut tx, operation_id, next.state, now_unix_ms).await?;
        }
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteConsumptionRecordV1 {
            operation: next,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }
}
