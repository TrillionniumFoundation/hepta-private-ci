use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::ChangeKind;
use crate::MatrixDispatchAuthorityDraft;
use crate::MatrixDispatchObservationKind;
use crate::MatrixDispatchObservationRecord;
use crate::MatrixDispatchRecord;
use crate::MatrixDispatchState;
use crate::MatrixDurableError;
use crate::MatrixEventId;
use crate::MatrixRoomId;
use crate::MatrixTransactionId;
use crate::OutboxRecord;
use crate::OutboxState;
use crate::store::MatrixDurableStore;

pub(crate) const MAX_UNRESOLVED_DISPATCHES: i64 = 4_096;

impl MatrixDurableStore {
    pub async fn dispatch_record(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        dispatch_by_txn_pool(self.sqlite_pool(), txn_id).await
    }

    pub async fn dispatch_record_for_operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        validate_local_identity(operation_id)?;
        sqlx::query(
            "SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id,
                    binding_revision, session_generation, authority_epoch, payload_sha256,
                    grant_payload_sha256, deadline_ms, state, last_attempt, accepted_event_id,
                    terminal_event_id, send_observation_sha256, redaction_observation_sha256,
                    prepared_at_ms, updated_at_ms, terminal_at_ms
             FROM matrix_dispatch_ledger WHERE operation_id = ?",
        )
        .bind(operation_id)
        .fetch_optional(self.sqlite_pool())
        .await
        .map_err(unavailable)?
        .map(|row| dispatch_from_row(&row))
        .transpose()
    }

    pub async fn dispatch_observations(
        &self,
        txn_id: &MatrixTransactionId,
        limit: usize,
    ) -> Result<Vec<MatrixDispatchObservationRecord>, MatrixDurableError> {
        if limit == 0 || limit > 4_096 {
            return Err(MatrixDurableError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT observation_seq, stable_txn_id, observation_kind, evidence_sha256,
                    server_event_id, observed_at_ms
             FROM matrix_dispatch_observations
             WHERE stable_txn_id = ?
             ORDER BY observation_seq LIMIT ?",
        )
        .bind(txn_id.as_str())
        .bind(i64::try_from(limit).map_err(|_| MatrixDurableError::Invalid)?)
        .fetch_all(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        rows.iter().map(observation_from_row).collect()
    }

    pub async fn bind_dispatch_authority(
        &self,
        draft: &MatrixDispatchAuthorityDraft,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_local_identity(&draft.operation_id)?;
        validate_local_identity(&draft.homeserver_id)?;
        validate_local_identity(&draft.device_id)?;
        validate_digest(&draft.payload_digest)?;
        validate_digest(&draft.grant_payload_digest)?;
        if draft.session_generation == 0
            || draft.authority_epoch == 0
            || draft.deadline_ms <= draft.prepared_at_ms
            || draft.payload_digest != draft.grant_payload_digest
        {
            return Err(MatrixDurableError::Invalid);
        }

        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = dispatch_by_txn_tx(&mut transaction, &draft.stable_txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if current.room_id != draft.room_id
            || current.session_generation != draft.session_generation
            || current.payload_digest != draft.payload_digest
        {
            return Err(MatrixDurableError::Conflict);
        }
        let exact = current.operation_id == draft.operation_id
            && current.homeserver_id.as_deref() == Some(draft.homeserver_id.as_str())
            && current.device_id.as_deref() == Some(draft.device_id.as_str())
            && current.authority_epoch == Some(draft.authority_epoch)
            && current.grant_payload_digest.as_deref()
                == Some(draft.grant_payload_digest.as_str())
            && current.deadline_ms == Some(draft.deadline_ms);
        if exact {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state != MatrixDispatchState::Prepared
            || current.authority_epoch.is_some()
            || current.grant_payload_digest.is_some()
        {
            return Err(MatrixDurableError::Conflict);
        }
        let operation_conflict: i64 = sqlx::query_scalar(
            "SELECT EXISTS(
                SELECT 1 FROM matrix_dispatch_ledger
                WHERE operation_id = ? AND stable_txn_id != ?
             )",
        )
        .bind(&draft.operation_id)
        .bind(draft.stable_txn_id.as_str())
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if operation_conflict != 0 {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET operation_id = ?, homeserver_id = ?, device_id = ?,
                 authority_epoch = ?, grant_payload_sha256 = ?, deadline_ms = ?,
                 updated_at_ms = MAX(updated_at_ms, ?)
             WHERE stable_txn_id = ? AND state = 'prepared'",
        )
        .bind(&draft.operation_id)
        .bind(&draft.homeserver_id)
        .bind(&draft.device_id)
        .bind(to_i64(draft.authority_epoch)?)
        .bind(&draft.grant_payload_digest)
        .bind(to_i64(draft.deadline_ms)?)
        .bind(to_i64(draft.prepared_at_ms)?)
        .bind(draft.stable_txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let result = dispatch_by_txn_tx(&mut transaction, &draft.stable_txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    /// Record Matrix HTTP/SDK acceptance without claiming terminal delivery.
    pub async fn mark_outbox_accepted(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        event_id: &MatrixEventId,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if matches!(
            current.state,
            MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted
        ) {
            if current.terminal_event_id.as_ref() == Some(event_id) {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(current);
            }
            return Err(MatrixDurableError::Conflict);
        }
        if current.state == MatrixDispatchState::Accepted {
            if current.accepted_event_id.as_ref() == Some(event_id)
                && current.last_attempt == expected_attempt
            {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(current);
            }
            return Err(MatrixDurableError::Conflict);
        }
        if current.state != MatrixDispatchState::Dispatched
            || current.last_attempt != expected_attempt
        {
            return Err(MatrixDurableError::Conflict);
        }
        require_in_flight_attempt_tx(&mut transaction, txn_id, expected_attempt).await?;
        let digest = local_evidence_digest(
            "transport_accepted",
            txn_id,
            expected_attempt,
            Some(event_id),
        )?;
        insert_observation_tx(
            &mut transaction,
            txn_id,
            MatrixDispatchObservationKind::TransportAccepted,
            &digest,
            Some(event_id),
            now_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'accepted', accepted_event_id = ?, updated_at_ms = MAX(updated_at_ms, ?)
             WHERE stable_txn_id = ? AND state = 'dispatched' AND last_attempt = ?",
        )
        .bind(event_id.as_str())
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        self.append_change(
            &mut transaction,
            ChangeKind::OutboxAccepted,
            Some(&current.room_id),
            Some(event_id),
            Some(txn_id),
            now_ms,
        )
        .await?;
        let result = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    /// Freeze a send whose external boundary may already have been crossed.
    /// It is not eligible for automatic resend; reconciliation must settle it.
    pub async fn mark_outbox_indeterminate(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if matches!(
            current.state,
            MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted
        ) {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state == MatrixDispatchState::Indeterminate
            && current.last_attempt == expected_attempt
        {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state != MatrixDispatchState::Dispatched
            || current.last_attempt != expected_attempt
        {
            return Err(MatrixDurableError::Conflict);
        }
        require_in_flight_attempt_tx(&mut transaction, txn_id, expected_attempt).await?;
        let digest =
            local_evidence_digest("transport_retryable", txn_id, expected_attempt, None)?;
        insert_observation_tx(
            &mut transaction,
            txn_id,
            MatrixDispatchObservationKind::TransportRetryable,
            &digest,
            None,
            now_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'indeterminate', updated_at_ms = MAX(updated_at_ms, ?)
             WHERE stable_txn_id = ? AND state = 'dispatched' AND last_attempt = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        self.append_change(
            &mut transaction,
            ChangeKind::OutboxIndeterminate,
            Some(&current.room_id),
            /*event_id*/ None,
            Some(txn_id),
            now_ms,
        )
        .await?;
        let result = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    pub async fn observe_dispatch_terminal_success(
        &self,
        txn_id: &MatrixTransactionId,
        event_id: &MatrixEventId,
        observation_digest: &str,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        settle_success_tx(
            self,
            &mut transaction,
            txn_id,
            event_id,
            observation_digest,
            MatrixDispatchObservationKind::HomeserverEvent,
            now_ms,
        )
        .await?;
        let result = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    pub async fn observe_dispatch_terminal_failure(
        &self,
        txn_id: &MatrixTransactionId,
        observation_digest: &str,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        settle_failure_tx(
            self,
            &mut transaction,
            txn_id,
            observation_digest,
            MatrixDispatchObservationKind::ManualTerminal,
            now_ms,
        )
        .await?;
        let result = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    pub async fn apply_dispatch_redaction(
        &self,
        event_id: &MatrixEventId,
        redaction_digest: &str,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(redaction_digest)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let txn_id = dispatch_txn_for_event_tx(&mut transaction, event_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        settle_redaction_tx(
            self,
            &mut transaction,
            &txn_id,
            event_id,
            redaction_digest,
            now_ms,
        )
        .await?;
        let result = dispatch_by_txn_tx(&mut transaction, &txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }
}

pub(crate) async fn ensure_dispatch_for_outbox_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &OutboxRecord,
) -> Result<(), MatrixDurableError> {
    if let Some(current) = dispatch_by_txn_tx(transaction, &record.stable_txn_id).await? {
        if current.room_id != record.room_id
            || current.binding_revision != record.binding_revision
            || current.session_generation != record.generation
        {
            return Err(MatrixDurableError::Corrupt);
        }
        return refresh_dispatch_payload_tx(transaction, record).await;
    }
    let unresolved: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM matrix_dispatch_ledger
         WHERE state IN ('prepared', 'dispatched', 'retry_scheduled', 'accepted', 'indeterminate')",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if unresolved >= MAX_UNRESOLVED_DISPATCHES {
        return Err(MatrixDurableError::Conflict);
    }
    let payload_digest = Sha256Digest::for_bytes(&record.payload);
    let operation_id = format!("matrix-send:{}", record.stable_txn_id.as_str());
    sqlx::query(
        "INSERT INTO matrix_dispatch_ledger (
            stable_txn_id, operation_id, homeserver_id, room_id, device_id,
            binding_revision, session_generation, authority_epoch, payload_sha256,
            grant_payload_sha256, deadline_ms, state, last_attempt, accepted_event_id,
            terminal_event_id, send_observation_sha256, redaction_observation_sha256,
            prepared_at_ms, updated_at_ms, terminal_at_ms
         ) VALUES (?, ?, NULL, ?, NULL, ?, ?, NULL, ?, NULL, NULL, 'prepared', 0,
                   NULL, NULL, NULL, NULL, ?, ?, NULL)",
    )
    .bind(record.stable_txn_id.as_str())
    .bind(operation_id)
    .bind(record.room_id.as_str())
    .bind(to_i64(record.binding_revision)?)
    .bind(to_i64(record.generation)?)
    .bind(payload_digest.as_str())
    .bind(to_i64(record.created_at_ms)?)
    .bind(to_i64(record.updated_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn refresh_dispatch_payload_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &OutboxRecord,
) -> Result<(), MatrixDurableError> {
    let current = dispatch_by_txn_tx(transaction, &record.stable_txn_id)
        .await?
        .ok_or(MatrixDurableError::Corrupt)?;
    if current.state != MatrixDispatchState::Prepared {
        return Err(MatrixDurableError::Conflict);
    }
    let payload_digest = Sha256Digest::for_bytes(&record.payload);
    if current
        .grant_payload_digest
        .as_deref()
        .is_some_and(|grant| grant != payload_digest.as_str())
    {
        return Err(MatrixDurableError::Conflict);
    }
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET payload_sha256 = ?, updated_at_ms = MAX(updated_at_ms, ?)
         WHERE stable_txn_id = ? AND state = 'prepared'",
    )
    .bind(payload_digest.as_str())
    .bind(to_i64(record.updated_at_ms)?)
    .bind(record.stable_txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn mark_dispatch_claimed_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    attempt: u64,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    if attempt == 0 {
        return Err(MatrixDurableError::Invalid);
    }
    let current = dispatch_by_txn_tx(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Corrupt)?;
    if current.state == MatrixDispatchState::Dispatched && current.last_attempt == attempt {
        return Ok(());
    }
    if !matches!(
        current.state,
        MatrixDispatchState::Prepared | MatrixDispatchState::RetryScheduled
    ) || attempt <= current.last_attempt
    {
        return Err(MatrixDurableError::Conflict);
    }
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'dispatched', last_attempt = ?, updated_at_ms = MAX(updated_at_ms, ?)
         WHERE stable_txn_id = ? AND state IN ('prepared', 'retry_scheduled')",
    )
    .bind(to_i64(attempt)?)
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn mark_dispatch_retry_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    expected_attempt: u64,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    let current = dispatch_by_txn_tx(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Corrupt)?;
    if current.state == MatrixDispatchState::RetryScheduled
        && current.last_attempt == expected_attempt
    {
        return Ok(());
    }
    if current.state != MatrixDispatchState::Dispatched
        || current.last_attempt != expected_attempt
    {
        return Err(MatrixDurableError::Conflict);
    }
    let digest = local_evidence_digest("transport_retryable", txn_id, expected_attempt, None)?;
    insert_observation_tx(
        transaction,
        txn_id,
        MatrixDispatchObservationKind::TransportRetryable,
        &digest,
        None,
        now_ms,
    )
    .await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'retry_scheduled', updated_at_ms = MAX(updated_at_ms, ?)
         WHERE stable_txn_id = ? AND state = 'dispatched' AND last_attempt = ?",
    )
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .bind(to_i64(expected_attempt)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn mark_dispatch_failed_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    expected_attempt: u64,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    let current = dispatch_by_txn_tx(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Corrupt)?;
    if current.state == MatrixDispatchState::Failed {
        return Ok(());
    }
    if matches!(
        current.state,
        MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted
    ) {
        return Err(MatrixDurableError::Conflict);
    }
    let digest = local_evidence_digest("transport_rejected", txn_id, expected_attempt, None)?;
    insert_observation_tx(
        transaction,
        txn_id,
        MatrixDispatchObservationKind::TransportRejected,
        digest.as_str(),
        None,
        now_ms,
    )
    .await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'failed', send_observation_sha256 = ?,
             updated_at_ms = MAX(updated_at_ms, ?), terminal_at_ms = ?
         WHERE stable_txn_id = ?",
    )
    .bind(digest.as_str())
    .bind(to_i64(now_ms)?)
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn mark_dispatch_success_compat_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    event_id: &MatrixEventId,
    expected_attempt: u64,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    let current = dispatch_by_txn_tx(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Corrupt)?;
    if current.state == MatrixDispatchState::Succeeded
        && current.terminal_event_id.as_ref() == Some(event_id)
    {
        return Ok(());
    }
    if matches!(
        current.state,
        MatrixDispatchState::Failed | MatrixDispatchState::Redacted
    ) {
        return Err(MatrixDurableError::Conflict);
    }
    let digest = local_evidence_digest(
        "manual_terminal",
        txn_id,
        expected_attempt,
        Some(event_id),
    )?;
    insert_observation_tx(
        transaction,
        txn_id,
        MatrixDispatchObservationKind::ManualTerminal,
        digest.as_str(),
        Some(event_id),
        now_ms,
    )
    .await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'succeeded', accepted_event_id = COALESCE(accepted_event_id, ?),
             terminal_event_id = ?, send_observation_sha256 = ?,
             updated_at_ms = MAX(updated_at_ms, ?), terminal_at_ms = ?
         WHERE stable_txn_id = ?",
    )
    .bind(event_id.as_str())
    .bind(event_id.as_str())
    .bind(digest.as_str())
    .bind(to_i64(now_ms)?)
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn fence_expired_dispatches_tx(
    store: &MatrixDurableStore,
    transaction: &mut Transaction<'_, Sqlite>,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    let rows = sqlx::query(
        "SELECT dispatch.stable_txn_id, dispatch.room_id, dispatch.last_attempt
         FROM matrix_dispatch_ledger AS dispatch
         JOIN outbox_messages AS outbox
           ON outbox.stable_txn_id = dispatch.stable_txn_id
         WHERE dispatch.state = 'dispatched'
           AND outbox.state = 'in_flight'
           AND outbox.lease_until_ms <= ?
         ORDER BY outbox.outbox_id
         LIMIT 4096",
    )
    .bind(to_i64(now_ms)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    for row in rows {
        let txn_id = MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?;
        let room_id = MatrixRoomId::parse(
            row.try_get::<String, _>("room_id").map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?;
        let attempt = to_u64(row.try_get("last_attempt").map_err(unavailable)?)?;
        let digest = local_evidence_digest("lease_expired_indeterminate", &txn_id, attempt, None)?;
        insert_observation_tx(
            transaction,
            &txn_id,
            MatrixDispatchObservationKind::TransportRetryable,
            digest.as_str(),
            None,
            now_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'indeterminate', updated_at_ms = MAX(updated_at_ms, ?)
             WHERE stable_txn_id = ? AND state = 'dispatched' AND last_attempt = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(attempt)?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        store
            .append_change(
                transaction,
                ChangeKind::OutboxIndeterminate,
                Some(&room_id),
                /*event_id*/ None,
                Some(&txn_id),
                now_ms,
            )
            .await?;
    }
    Ok(())
}

pub(crate) async fn observe_outbound_success_tx(
    store: &MatrixDurableStore,
    transaction: &mut Transaction<'_, Sqlite>,
    transaction_id: Option<&MatrixTransactionId>,
    room_id: &MatrixRoomId,
    binding_revision: u64,
    generation: u64,
    event_id: &MatrixEventId,
    observation_digest: &str,
    observed_at_ms: u64,
) -> Result<bool, MatrixDurableError> {
    validate_digest(observation_digest)?;
    let txn_id = if let Some(txn_id) = transaction_id {
        dispatch_by_txn_tx(transaction, txn_id)
            .await?
            .map(|_| txn_id.clone())
    } else {
        dispatch_txn_for_event_tx(transaction, event_id).await?
    };
    let Some(txn_id) = txn_id else {
        return Ok(false);
    };
    let current = dispatch_by_txn_tx(transaction, &txn_id)
        .await?
        .ok_or(MatrixDurableError::Corrupt)?;
    if current.room_id != *room_id
        || current.binding_revision != binding_revision
        || current.session_generation != generation
    {
        return Err(MatrixDurableError::Conflict);
    }
    settle_success_tx(
        store,
        transaction,
        &txn_id,
        event_id,
        observation_digest,
        MatrixDispatchObservationKind::HomeserverEvent,
        observed_at_ms,
    )
    .await?;
    Ok(true)
}

pub(crate) async fn apply_outbound_redaction_tx(
    store: &MatrixDurableStore,
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &MatrixEventId,
    redaction_digest: &str,
    observed_at_ms: u64,
) -> Result<bool, MatrixDurableError> {
    validate_digest(redaction_digest)?;
    let Some(txn_id) = dispatch_txn_for_event_tx(transaction, event_id).await? else {
        return Ok(false);
    };
    settle_redaction_tx(
        store,
        transaction,
        &txn_id,
        event_id,
        redaction_digest,
        observed_at_ms,
    )
    .await?;
    Ok(true)
}

async fn settle_success_tx(
    store: &MatrixDurableStore,
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    event_id: &MatrixEventId,
    observation_digest: &str,
    kind: MatrixDispatchObservationKind,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    let current = dispatch_by_txn_tx(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Conflict)?;
    if current.state == MatrixDispatchState::Succeeded {
        if current.terminal_event_id.as_ref() == Some(event_id)
            && current.send_observation_digest.as_deref() == Some(observation_digest)
        {
            return Ok(());
        }
        return Err(MatrixDurableError::Conflict);
    }
    if current.state == MatrixDispatchState::Redacted {
        if current.terminal_event_id.as_ref() == Some(event_id) {
            return Ok(());
        }
        return Err(MatrixDurableError::Conflict);
    }
    if current.state == MatrixDispatchState::Failed {
        return Err(MatrixDurableError::Conflict);
    }
    if let Some(accepted) = &current.accepted_event_id
        && accepted != event_id
    {
        return Err(MatrixDurableError::Conflict);
    }
    insert_observation_tx(
        transaction,
        txn_id,
        kind,
        observation_digest,
        Some(event_id),
        now_ms,
    )
    .await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'succeeded', accepted_event_id = COALESCE(accepted_event_id, ?),
             terminal_event_id = ?, send_observation_sha256 = ?,
             updated_at_ms = MAX(updated_at_ms, ?), terminal_at_ms = ?
         WHERE stable_txn_id = ?",
    )
    .bind(event_id.as_str())
    .bind(event_id.as_str())
    .bind(observation_digest)
    .bind(to_i64(now_ms)?)
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    sqlx::query(
        "UPDATE outbox_messages
         SET state = 'sent', lease_until_ms = NULL, sent_event_id = ?,
             updated_at_ms = MAX(updated_at_ms, ?)
         WHERE stable_txn_id = ?
           AND state IN ('pending', 'in_flight', 'retry_scheduled', 'sent')",
    )
    .bind(event_id.as_str())
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    store
        .append_change(
            transaction,
            ChangeKind::OutboxSent,
            Some(&current.room_id),
            Some(event_id),
            Some(txn_id),
            now_ms,
        )
        .await?;
    Ok(())
}

async fn settle_failure_tx(
    store: &MatrixDurableStore,
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    observation_digest: &str,
    kind: MatrixDispatchObservationKind,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    let current = dispatch_by_txn_tx(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Conflict)?;
    if current.state == MatrixDispatchState::Failed {
        if current.send_observation_digest.as_deref() == Some(observation_digest) {
            return Ok(());
        }
        return Err(MatrixDurableError::Conflict);
    }
    if matches!(
        current.state,
        MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted
    ) {
        return Err(MatrixDurableError::Conflict);
    }
    insert_observation_tx(transaction, txn_id, kind, observation_digest, None, now_ms).await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'failed', send_observation_sha256 = ?,
             updated_at_ms = MAX(updated_at_ms, ?), terminal_at_ms = ?
         WHERE stable_txn_id = ?",
    )
    .bind(observation_digest)
    .bind(to_i64(now_ms)?)
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    sqlx::query(
        "UPDATE outbox_messages
         SET state = 'permanent_failure', lease_until_ms = NULL, sent_event_id = NULL,
             updated_at_ms = MAX(updated_at_ms, ?)
         WHERE stable_txn_id = ?
           AND state IN ('pending', 'in_flight', 'retry_scheduled', 'permanent_failure')",
    )
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    store
        .append_change(
            transaction,
            ChangeKind::OutboxFailed,
            Some(&current.room_id),
            /*event_id*/ None,
            Some(txn_id),
            now_ms,
        )
        .await?;
    Ok(())
}

async fn settle_redaction_tx(
    store: &MatrixDurableStore,
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    event_id: &MatrixEventId,
    redaction_digest: &str,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    let current = dispatch_by_txn_tx(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Conflict)?;
    if current.state == MatrixDispatchState::Redacted {
        if current.terminal_event_id.as_ref() == Some(event_id)
            && current.redaction_observation_digest.as_deref() == Some(redaction_digest)
        {
            return Ok(());
        }
        return Err(MatrixDurableError::Conflict);
    }
    if current.state == MatrixDispatchState::Failed {
        return Err(MatrixDurableError::Conflict);
    }
    if current
        .terminal_event_id
        .as_ref()
        .or(current.accepted_event_id.as_ref())
        != Some(event_id)
    {
        return Err(MatrixDurableError::Conflict);
    }
    insert_observation_tx(
        transaction,
        txn_id,
        MatrixDispatchObservationKind::Redaction,
        redaction_digest,
        Some(event_id),
        now_ms,
    )
    .await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'redacted', terminal_event_id = COALESCE(terminal_event_id, ?),
             redaction_observation_sha256 = ?, updated_at_ms = MAX(updated_at_ms, ?),
             terminal_at_ms = COALESCE(terminal_at_ms, ?)
         WHERE stable_txn_id = ?",
    )
    .bind(event_id.as_str())
    .bind(redaction_digest)
    .bind(to_i64(now_ms)?)
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    sqlx::query(
        "UPDATE outbox_messages
         SET state = 'sent', lease_until_ms = NULL, sent_event_id = ?,
             updated_at_ms = MAX(updated_at_ms, ?)
         WHERE stable_txn_id = ?
           AND state IN ('pending', 'in_flight', 'retry_scheduled', 'sent')",
    )
    .bind(event_id.as_str())
    .bind(to_i64(now_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    store
        .append_change(
            transaction,
            ChangeKind::OutboxRedacted,
            Some(&current.room_id),
            Some(event_id),
            Some(txn_id),
            now_ms,
        )
        .await?;
    Ok(())
}

pub(crate) async fn verify_dispatch_schema(
    pool: &sqlx::SqlitePool,
) -> Result<(), MatrixDurableError> {
    let required: i64 = sqlx::query_scalar(
        "WITH required(name, type) AS (
            VALUES
              ('matrix_dispatch_ledger', 'table'),
              ('matrix_dispatch_ledger_by_state', 'index'),
              ('matrix_dispatch_ledger_by_accepted_event', 'index'),
              ('matrix_dispatch_ledger_by_terminal_event', 'index'),
              ('matrix_dispatch_observations', 'table'),
              ('matrix_dispatch_observations_identity', 'index'),
              ('matrix_dispatch_observations_by_txn', 'index'),
              ('matrix_dispatch_ledger_no_delete', 'trigger'),
              ('matrix_dispatch_observations_no_update', 'trigger'),
              ('matrix_dispatch_observations_no_delete', 'trigger')
         )
         SELECT COUNT(*) FROM required
         JOIN sqlite_schema USING (name) WHERE sqlite_schema.type = required.type",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if required != 10 {
        return Err(MatrixDurableError::Corrupt);
    }
    let invalid: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM outbox_messages AS outbox
         LEFT JOIN matrix_dispatch_ledger AS dispatch
           ON dispatch.stable_txn_id = outbox.stable_txn_id
         WHERE dispatch.stable_txn_id IS NULL
            OR dispatch.room_id != outbox.room_id
            OR dispatch.binding_revision != outbox.binding_revision
            OR dispatch.session_generation != outbox.generation
            OR dispatch.payload_sha256 != outbox.payload_sha256
            OR (dispatch.state = 'succeeded' AND (
                dispatch.terminal_event_id IS NULL
                OR dispatch.send_observation_sha256 IS NULL
                OR outbox.state != 'sent'
                OR outbox.sent_event_id != dispatch.terminal_event_id
            ))
            OR (dispatch.state = 'redacted' AND (
                dispatch.terminal_event_id IS NULL
                OR dispatch.redaction_observation_sha256 IS NULL
                OR outbox.state != 'sent'
            ))
            OR (dispatch.state = 'failed' AND outbox.state != 'permanent_failure')",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid != 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(())
}

async fn require_in_flight_attempt_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    expected_attempt: u64,
) -> Result<(), MatrixDurableError> {
    let valid: i64 = sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM outbox_messages
            WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?
         )",
    )
    .bind(txn_id.as_str())
    .bind(to_i64(expected_attempt)?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if valid != 1 {
        return Err(MatrixDurableError::Conflict);
    }
    Ok(())
}

async fn dispatch_txn_for_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &MatrixEventId,
) -> Result<Option<MatrixTransactionId>, MatrixDurableError> {
    let rows = sqlx::query_scalar::<_, String>(
        "SELECT stable_txn_id FROM matrix_dispatch_ledger
         WHERE accepted_event_id = ? OR terminal_event_id = ?
         ORDER BY stable_txn_id LIMIT 2",
    )
    .bind(event_id.as_str())
    .bind(event_id.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    match rows.as_slice() {
        [] => Ok(None),
        [value] => MatrixTransactionId::parse(value.clone())
            .map(Some)
            .map_err(|_| MatrixDurableError::Corrupt),
        _ => Err(MatrixDurableError::Conflict),
    }
}

async fn dispatch_by_txn_pool(
    pool: &sqlx::SqlitePool,
    txn_id: &MatrixTransactionId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    sqlx::query(dispatch_select_sql())
        .bind(txn_id.as_str())
        .fetch_optional(pool)
        .await
        .map_err(unavailable)?
        .map(|row| dispatch_from_row(&row))
        .transpose()
}

async fn dispatch_by_txn_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    sqlx::query(dispatch_select_sql())
        .bind(txn_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?
        .map(|row| dispatch_from_row(&row))
        .transpose()
}

fn dispatch_select_sql() -> &'static str {
    "SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id,
            binding_revision, session_generation, authority_epoch, payload_sha256,
            grant_payload_sha256, deadline_ms, state, last_attempt, accepted_event_id,
            terminal_event_id, send_observation_sha256, redaction_observation_sha256,
            prepared_at_ms, updated_at_ms, terminal_at_ms
     FROM matrix_dispatch_ledger WHERE stable_txn_id = ?"
}

fn dispatch_from_row(row: &SqliteRow) -> Result<MatrixDispatchRecord, MatrixDurableError> {
    let state = MatrixDispatchState::parse(
        row.try_get::<String, _>("state")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let payload_digest: String = row.try_get("payload_sha256").map_err(unavailable)?;
    validate_digest(&payload_digest).map_err(|_| MatrixDurableError::Corrupt)?;
    let grant_payload_digest = row
        .try_get::<Option<String>, _>("grant_payload_sha256")
        .map_err(unavailable)?;
    if let Some(value) = &grant_payload_digest {
        validate_digest(value).map_err(|_| MatrixDurableError::Corrupt)?;
    }
    let send_observation_digest = row
        .try_get::<Option<String>, _>("send_observation_sha256")
        .map_err(unavailable)?;
    if let Some(value) = &send_observation_digest {
        validate_digest(value).map_err(|_| MatrixDurableError::Corrupt)?;
    }
    let redaction_observation_digest = row
        .try_get::<Option<String>, _>("redaction_observation_sha256")
        .map_err(unavailable)?;
    if let Some(value) = &redaction_observation_digest {
        validate_digest(value).map_err(|_| MatrixDurableError::Corrupt)?;
    }
    Ok(MatrixDispatchRecord {
        operation_id: row.try_get("operation_id").map_err(unavailable)?,
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        homeserver_id: row.try_get("homeserver_id").map_err(unavailable)?,
        room_id: MatrixRoomId::parse(
            row.try_get::<String, _>("room_id").map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        device_id: row.try_get("device_id").map_err(unavailable)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        session_generation: to_u64(
            row.try_get("session_generation").map_err(unavailable)?,
        )?,
        authority_epoch: row
            .try_get::<Option<i64>, _>("authority_epoch")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        payload_digest,
        grant_payload_digest,
        deadline_ms: row
            .try_get::<Option<i64>, _>("deadline_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        state,
        last_attempt: to_u64(row.try_get("last_attempt").map_err(unavailable)?)?,
        accepted_event_id: parse_optional_event(row, "accepted_event_id")?,
        terminal_event_id: parse_optional_event(row, "terminal_event_id")?,
        send_observation_digest,
        redaction_observation_digest,
        prepared_at_ms: to_u64(row.try_get("prepared_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
        terminal_at_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
    })
}

fn observation_from_row(
    row: &SqliteRow,
) -> Result<MatrixDispatchObservationRecord, MatrixDurableError> {
    let kind = MatrixDispatchObservationKind::parse(
        row.try_get::<String, _>("observation_kind")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let evidence_digest: String = row.try_get("evidence_sha256").map_err(unavailable)?;
    validate_digest(&evidence_digest).map_err(|_| MatrixDurableError::Corrupt)?;
    Ok(MatrixDispatchObservationRecord {
        observation_seq: to_u64(row.try_get("observation_seq").map_err(unavailable)?)?,
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        kind,
        evidence_digest,
        server_event_id: parse_optional_event(row, "server_event_id")?,
        observed_at_ms: to_u64(row.try_get("observed_at_ms").map_err(unavailable)?)?,
    })
}

fn parse_optional_event(
    row: &SqliteRow,
    field: &str,
) -> Result<Option<MatrixEventId>, MatrixDurableError> {
    row.try_get::<Option<String>, _>(field)
        .map_err(unavailable)?
        .map(MatrixEventId::parse)
        .transpose()
        .map_err(|_| MatrixDurableError::Corrupt)
}

async fn insert_observation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    kind: MatrixDispatchObservationKind,
    evidence_digest: &str,
    event_id: Option<&MatrixEventId>,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    validate_digest(evidence_digest)?;
    sqlx::query(
        "INSERT OR IGNORE INTO matrix_dispatch_observations (
            stable_txn_id, observation_kind, evidence_sha256, server_event_id, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?)",
    )
    .bind(txn_id.as_str())
    .bind(kind.as_str())
    .bind(evidence_digest)
    .bind(event_id.map(MatrixEventId::as_str))
    .bind(to_i64(observed_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn local_evidence_digest(
    kind: &str,
    txn_id: &MatrixTransactionId,
    attempt: u64,
    event_id: Option<&MatrixEventId>,
) -> Result<Sha256Digest, MatrixDurableError> {
    let bytes = serde_json::to_vec(&(
        "hepta.matrix.dispatch-observation.v1",
        kind,
        txn_id.as_str(),
        attempt,
        event_id.map(MatrixEventId::as_str),
    ))
    .map_err(|_| MatrixDurableError::Invalid)?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn validate_digest(value: &str) -> Result<(), MatrixDurableError> {
    Sha256Digest::parse(value.to_string())
        .map(|_| ())
        .map_err(|_| MatrixDurableError::Invalid)
}

fn validate_local_identity(value: &str) -> Result<(), MatrixDurableError> {
    if value.is_empty()
        || value.len() > 255
        || value.chars().any(char::is_whitespace)
        || value.chars().any(char::is_control)
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, MatrixDurableError> {
    i64::try_from(value).map_err(|_| MatrixDurableError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}
