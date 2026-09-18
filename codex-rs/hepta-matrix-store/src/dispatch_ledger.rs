use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use super::MatrixDurableError;
use super::MatrixDurableStore;
use super::OutboxRecord;
use super::OutboxState;
use super::to_i64;
use super::to_u64;
use super::unavailable;
use crate::MatrixEventId;
use crate::MatrixRoomId;
use crate::MatrixTransactionId;

const MAX_UNRESOLVED_DISPATCHES: i64 = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixDispatchState {
    Dispatched,
    Accepted,
    Indeterminate,
    ObservedTerminal,
    TerminalFailure,
    Redacted,
}

impl MatrixDispatchState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Dispatched => "dispatched",
            Self::Accepted => "accepted",
            Self::Indeterminate => "indeterminate",
            Self::ObservedTerminal => "observed_terminal",
            Self::TerminalFailure => "terminal_failure",
            Self::Redacted => "redacted",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "dispatched" => Some(Self::Dispatched),
            "accepted" => Some(Self::Accepted),
            "indeterminate" => Some(Self::Indeterminate),
            "observed_terminal" => Some(Self::ObservedTerminal),
            "terminal_failure" => Some(Self::TerminalFailure),
            "redacted" => Some(Self::Redacted),
            _ => None,
        }
    }

    fn unresolved(self) -> bool {
        matches!(
            self,
            Self::Dispatched | Self::Accepted | Self::Indeterminate
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchRecord {
    pub stable_txn_id: MatrixTransactionId,
    pub operation_id: String,
    pub room_id: MatrixRoomId,
    pub payload_sha256: String,
    pub binding_revision: u64,
    pub generation: u64,
    pub authority_identity: String,
    pub authority_epoch: Option<u64>,
    pub grant_payload_digest: Option<String>,
    pub state: MatrixDispatchState,
    pub last_attempt: u64,
    pub transport_event_id: Option<MatrixEventId>,
    pub terminal_event_id: Option<MatrixEventId>,
    pub send_observation_digest: Option<String>,
    pub redaction_observation_digest: Option<String>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
    pub terminal_at_ms: Option<u64>,
    pub redacted_at_ms: Option<u64>,
}

impl MatrixDurableStore {
    /// Record the Matrix send response without claiming external terminality.
    ///
    /// The outbox remains in-flight. If no trusted server event is observed,
    /// its lease expires and the exact same stable transaction identity is
    /// eligible for reconciliation/retry.
    pub async fn record_transport_accepted(
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
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let outbox = outbox_for_txn_raw(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if outbox.state == OutboxState::Sent {
            let dispatch = dispatch_by_txn_tx(&mut transaction, txn_id)
                .await?
                .ok_or(MatrixDurableError::Corrupt)?;
            if dispatch.terminal_event_id.as_ref() == Some(event_id) {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(dispatch);
            }
            return Err(MatrixDurableError::Conflict);
        }
        if outbox.state != OutboxState::InFlight || outbox.attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        ensure_dispatch_for_claim_tx(&mut transaction, &outbox, expected_attempt, now_ms).await?;
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        if !current.state.unresolved() {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(prior) = &current.transport_event_id
            && prior != event_id
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'accepted', transport_event_id = ?, updated_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(event_id.as_str())
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let digest = transport_digest("accepted", txn_id, expected_attempt, Some(event_id));
        insert_observation_tx(
            &mut transaction,
            txn_id,
            "transport_accepted",
            Some(event_id),
            &digest,
            now_ms,
        )
        .await?;
        let record = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    /// Preserve transport uncertainty separately from terminal server truth.
    pub async fn record_transport_indeterminate(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let outbox = outbox_for_txn_raw(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if outbox.attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        if outbox.state == OutboxState::Sent
            && matches!(
                current.state,
                MatrixDispatchState::ObservedTerminal | MatrixDispatchState::Redacted
            )
        {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if outbox.state == OutboxState::PermanentFailure
            && current.state == MatrixDispatchState::TerminalFailure
        {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if outbox.state != OutboxState::InFlight {
            return Err(MatrixDurableError::Conflict);
        }
        ensure_dispatch_for_claim_tx(&mut transaction, &outbox, expected_attempt, now_ms).await?;
        if !current.state.unresolved() {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'indeterminate', updated_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let digest = transport_digest("indeterminate", txn_id, expected_attempt, None);
        insert_observation_tx(
            &mut transaction,
            txn_id,
            "transport_indeterminate",
            None,
            &digest,
            now_ms,
        )
        .await?;
        let record = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    /// Record a terminal transport rejection after the durable outbox has
    /// entered permanent_failure. Reopen reconciliation repairs this ledger
    /// from the outbox if a crash happens between the two writes.
    pub async fn record_transport_terminal_failure(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let outbox = outbox_for_txn_raw(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if outbox.state != OutboxState::PermanentFailure || outbox.attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        ensure_dispatch_for_claim_tx(&mut transaction, &outbox, expected_attempt, now_ms).await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'terminal_failure', updated_at_ms = ?, terminal_at_ms = ?
             WHERE stable_txn_id = ?
               AND state NOT IN ('observed_terminal', 'redacted')",
        )
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let digest = transport_digest("terminal_failure", txn_id, expected_attempt, None);
        insert_observation_tx(
            &mut transaction,
            txn_id,
            "transport_failure",
            None,
            &digest,
            now_ms,
        )
        .await?;
        let record = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    /// Settle an outbound send only from a trusted homeserver timeline
    /// observation. This transition atomically closes the durable outbox and
    /// records immutable observation evidence.
    pub async fn observe_outbox_server_event(
        &self,
        txn_id: &MatrixTransactionId,
        room_id: &MatrixRoomId,
        event_id: &MatrixEventId,
        observation_digest: &Sha256Digest,
        now_ms: u64,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let Some(outbox) = outbox_for_txn_raw(&mut transaction, txn_id).await? else {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(None);
        };
        if &outbox.room_id != room_id || outbox.attempts == 0 {
            return Err(MatrixDurableError::Conflict);
        }
        ensure_dispatch_for_claim_tx(
            &mut transaction,
            &outbox,
            outbox.attempts,
            now_ms,
        )
        .await?;
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        if current.state == MatrixDispatchState::Redacted {
            if current.terminal_event_id.as_ref() == Some(event_id)
                && current.send_observation_digest.as_deref() == Some(observation_digest.as_str())
            {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(Some(current));
            }
            return Err(MatrixDurableError::Conflict);
        }
        if current.state == MatrixDispatchState::ObservedTerminal {
            if current.terminal_event_id.as_ref() != Some(event_id) {
                return Err(MatrixDurableError::Conflict);
            }
            if let Some(digest) = current.send_observation_digest.as_deref() {
                if digest != observation_digest.as_str() {
                    return Err(MatrixDurableError::Conflict);
                }
                transaction.commit().await.map_err(unavailable)?;
                return Ok(Some(current));
            }
            sqlx::query(
                "UPDATE matrix_dispatch_ledger
                 SET send_observation_digest = ?, updated_at_ms = MAX(updated_at_ms, ?)
                 WHERE stable_txn_id = ? AND send_observation_digest IS NULL",
            )
            .bind(observation_digest.as_str())
            .bind(to_i64(now_ms)?)
            .bind(txn_id.as_str())
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            insert_observation_tx(
                &mut transaction,
                txn_id,
                "server_event",
                Some(event_id),
                observation_digest,
                now_ms,
            )
            .await?;
            let upgraded = dispatch_by_txn_tx(&mut transaction, txn_id)
                .await?
                .ok_or(MatrixDurableError::Corrupt)?;
            transaction.commit().await.map_err(unavailable)?;
            return Ok(Some(upgraded));
        }
        if current.state == MatrixDispatchState::TerminalFailure
            || outbox.state == OutboxState::PermanentFailure
        {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(candidate) = &current.transport_event_id
            && candidate != event_id
        {
            return Err(MatrixDurableError::Conflict);
        }

        let updated = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'sent', lease_until_ms = NULL, updated_at_ms = ?, sent_event_id = ?
             WHERE outbox_id = ? AND state IN ('pending', 'in_flight', 'retry_scheduled')",
        )
        .bind(to_i64(now_ms)?)
        .bind(event_id.as_str())
        .bind(to_i64(outbox.outbox_id)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if outbox.state != OutboxState::Sent && updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'observed_terminal',
                 terminal_event_id = ?,
                 send_observation_digest = ?,
                 updated_at_ms = ?,
                 terminal_at_ms = ?
             WHERE stable_txn_id = ?
               AND state IN ('dispatched', 'accepted', 'indeterminate')",
        )
        .bind(event_id.as_str())
        .bind(observation_digest.as_str())
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        insert_observation_tx(
            &mut transaction,
            txn_id,
            "server_event",
            Some(event_id),
            observation_digest,
            now_ms,
        )
        .await?;
        self.append_change(
            &mut transaction,
            super::ChangeKind::OutboxSent,
            Some(room_id),
            Some(event_id),
            Some(txn_id),
            now_ms,
        )
        .await?;
        let record = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(Some(record))
    }

    /// Preserve redaction evidence without overwriting the original send
    /// observation digest.
    pub async fn observe_outbox_redaction(
        &self,
        target_event_id: &MatrixEventId,
        redaction_event_id: &MatrixEventId,
        observation_digest: &Sha256Digest,
        now_ms: u64,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let row = sqlx::query(
            "SELECT stable_txn_id
             FROM matrix_dispatch_ledger
             WHERE terminal_event_id = ?",
        )
        .bind(target_event_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(None);
        };
        let txn_id = MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?;
        let current = dispatch_by_txn_tx(&mut transaction, &txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        if current.state == MatrixDispatchState::Redacted {
            if current.redaction_observation_digest.as_deref()
                == Some(observation_digest.as_str())
            {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(Some(current));
            }
            return Err(MatrixDurableError::Conflict);
        }
        if current.state != MatrixDispatchState::ObservedTerminal {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'redacted',
                 redaction_observation_digest = ?,
                 updated_at_ms = ?,
                 redacted_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'observed_terminal'",
        )
        .bind(observation_digest.as_str())
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        insert_observation_tx(
            &mut transaction,
            &txn_id,
            "redaction",
            Some(redaction_event_id),
            observation_digest,
            now_ms,
        )
        .await?;
        let record = dispatch_by_txn_tx(&mut transaction, &txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(Some(record))
    }

    pub async fn dispatch_for_txn(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let result = dispatch_by_txn_tx(&mut transaction, txn_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }
}

pub(super) async fn record_outbox_claim_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &OutboxRecord,
    attempt: u64,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    ensure_dispatch_for_claim_tx(transaction, record, attempt, now_ms).await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'dispatched', last_attempt = ?, updated_at_ms = ?
         WHERE stable_txn_id = ?
           AND state IN ('dispatched', 'accepted', 'indeterminate')",
    )
    .bind(to_i64(attempt)?)
    .bind(to_i64(now_ms)?)
    .bind(record.stable_txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(super) async fn reconcile_terminal_outbox(
    pool: &sqlx::SqlitePool,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'observed_terminal',
             terminal_event_id = (
                 SELECT sent_event_id FROM outbox_messages
                 WHERE outbox_messages.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
             ),
             terminal_at_ms = COALESCE(terminal_at_ms, (
                 SELECT updated_at_ms FROM outbox_messages
                 WHERE outbox_messages.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
             )),
             updated_at_ms = MAX(updated_at_ms, (
                 SELECT updated_at_ms FROM outbox_messages
                 WHERE outbox_messages.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
             ))
         WHERE stable_txn_id IN (
             SELECT stable_txn_id FROM outbox_messages
             WHERE state = 'sent' AND sent_event_id IS NOT NULL
         )
           AND state IN ('dispatched', 'accepted', 'indeterminate')",
    )
    .execute(pool)
    .await
    .map_err(unavailable)?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'terminal_failure',
             terminal_at_ms = COALESCE(terminal_at_ms, (
                 SELECT updated_at_ms FROM outbox_messages
                 WHERE outbox_messages.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
             )),
             updated_at_ms = MAX(updated_at_ms, (
                 SELECT updated_at_ms FROM outbox_messages
                 WHERE outbox_messages.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
             ))
         WHERE stable_txn_id IN (
             SELECT stable_txn_id FROM outbox_messages WHERE state = 'permanent_failure'
         )
           AND state IN ('dispatched', 'accepted', 'indeterminate')",
    )
    .execute(pool)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn ensure_dispatch_for_claim_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &OutboxRecord,
    attempt: u64,
    now_ms: u64,
) -> Result<(), MatrixDurableError> {
    if attempt == 0 {
        return Err(MatrixDurableError::Invalid);
    }
    let operation_id: String = sqlx::query_scalar(
        "SELECT logical_outbox_id FROM outbox_messages WHERE outbox_id = ?",
    )
    .bind(to_i64(record.outbox_id)?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let payload_sha256 = Sha256Digest::for_bytes(&record.payload);
    let authority_identity =
        format!("matrix-binding:{}:{}", record.binding_revision, record.generation);
    if let Some(existing) = dispatch_by_txn_tx(transaction, &record.stable_txn_id).await? {
        if existing.operation_id != operation_id
            || existing.room_id != record.room_id
            || existing.payload_sha256 != payload_sha256.as_str()
            || existing.binding_revision != record.binding_revision
            || existing.generation != record.generation
            || existing.authority_identity != authority_identity
        {
            return Err(MatrixDurableError::Conflict);
        }
        return Ok(());
    }
    let unresolved: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM matrix_dispatch_ledger
         WHERE state IN ('dispatched', 'accepted', 'indeterminate')",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if unresolved >= MAX_UNRESOLVED_DISPATCHES {
        return Err(MatrixDurableError::Unavailable);
    }
    sqlx::query(
        "INSERT INTO matrix_dispatch_ledger (
            stable_txn_id, operation_id, room_id, payload_sha256,
            binding_revision, generation, authority_identity,
            authority_epoch, grant_payload_digest, state, last_attempt,
            transport_event_id, terminal_event_id,
            send_observation_digest, redaction_observation_digest,
            created_at_ms, updated_at_ms, terminal_at_ms, redacted_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'dispatched', ?,
                   NULL, NULL, NULL, NULL, ?, ?, NULL, NULL)",
    )
    .bind(record.stable_txn_id.as_str())
    .bind(operation_id)
    .bind(record.room_id.as_str())
    .bind(payload_sha256.as_str())
    .bind(to_i64(record.binding_revision)?)
    .bind(to_i64(record.generation)?)
    .bind(authority_identity)
    .bind(to_i64(attempt)?)
    .bind(to_i64(record.created_at_ms)?)
    .bind(to_i64(now_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn outbox_for_txn_raw(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<OutboxRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT outbox_id, stable_txn_id, room_id, kind,
                payload, payload_sha256, logical_txn_count,
                binding_revision, generation, state, attempts, next_attempt_at_ms,
                lease_until_ms, created_at_ms, updated_at_ms, sent_event_id
         FROM outbox_messages WHERE stable_txn_id = ?",
    )
    .bind(txn_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| super::outbox_from_row(&row))
    .transpose()
}

async fn dispatch_by_txn_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT stable_txn_id, operation_id, room_id, payload_sha256,
                binding_revision, generation, authority_identity,
                authority_epoch, grant_payload_digest, state, last_attempt,
                transport_event_id, terminal_event_id,
                send_observation_digest, redaction_observation_digest,
                created_at_ms, updated_at_ms, terminal_at_ms, redacted_at_ms
         FROM matrix_dispatch_ledger WHERE stable_txn_id = ?",
    )
    .bind(txn_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| dispatch_from_row(&row))
    .transpose()
}

async fn insert_observation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    kind: &str,
    event_id: Option<&MatrixEventId>,
    digest: &Sha256Digest,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "INSERT OR IGNORE INTO matrix_dispatch_observations (
            stable_txn_id, kind, event_id, observation_digest, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?)",
    )
    .bind(txn_id.as_str())
    .bind(kind)
    .bind(event_id.map(MatrixEventId::as_str))
    .bind(digest.as_str())
    .bind(to_i64(observed_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn transport_digest(
    disposition: &str,
    txn_id: &MatrixTransactionId,
    attempt: u64,
    event_id: Option<&MatrixEventId>,
) -> Sha256Digest {
    let evidence = format!(
        "hepta.matrix.transport.v1\0{}\0{}\0{}\0{}",
        disposition,
        txn_id.as_str(),
        attempt,
        event_id.map(MatrixEventId::as_str).unwrap_or("")
    );
    Sha256Digest::for_bytes(evidence.as_bytes())
}

fn dispatch_from_row(row: &SqliteRow) -> Result<MatrixDispatchRecord, MatrixDurableError> {
    let state = MatrixDispatchState::parse(
        row.try_get::<String, _>("state")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    let parse_event = |name: &str| -> Result<Option<MatrixEventId>, MatrixDurableError> {
        row.try_get::<Option<String>, _>(name)
            .map_err(unavailable)?
            .map(MatrixEventId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)
    };
    Ok(MatrixDispatchRecord {
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        operation_id: row.try_get("operation_id").map_err(unavailable)?,
        room_id: MatrixRoomId::parse(
            row.try_get::<String, _>("room_id").map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        payload_sha256: row.try_get("payload_sha256").map_err(unavailable)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        authority_identity: row.try_get("authority_identity").map_err(unavailable)?,
        authority_epoch: row
            .try_get::<Option<i64>, _>("authority_epoch")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        grant_payload_digest: row.try_get("grant_payload_digest").map_err(unavailable)?,
        state,
        last_attempt: to_u64(row.try_get("last_attempt").map_err(unavailable)?)?,
        transport_event_id: parse_event("transport_event_id")?,
        terminal_event_id: parse_event("terminal_event_id")?,
        send_observation_digest: row.try_get("send_observation_digest").map_err(unavailable)?,
        redaction_observation_digest: row
            .try_get("redaction_observation_digest")
            .map_err(unavailable)?,
        created_at_ms: to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
        terminal_at_ms: row
            .try_get::<Option<i64>, _>("terminal_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        redacted_at_ms: row
            .try_get::<Option<i64>, _>("redacted_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
    })
}
