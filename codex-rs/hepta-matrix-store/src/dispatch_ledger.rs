use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use sqlx::Row;

use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::OutboxRecord;
use crate::OutboxState;

pub const MAX_UNRESOLVED_MATRIX_DISPATCHES: u64 = 4_096;
const PARKED_LEASE_UNTIL_MS: i64 = i64::MAX;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixDispatchState {
    Prepared,
    Dispatched,
    Accepted,
    Indeterminate,
    ObservedSucceeded,
    ObservedFailed,
    Redacted,
}

impl MatrixDispatchState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatched => "dispatched",
            Self::Accepted => "accepted",
            Self::Indeterminate => "indeterminate",
            Self::ObservedSucceeded => "observed_succeeded",
            Self::ObservedFailed => "observed_failed",
            Self::Redacted => "redacted",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "prepared" => Some(Self::Prepared),
            "dispatched" => Some(Self::Dispatched),
            "accepted" => Some(Self::Accepted),
            "indeterminate" => Some(Self::Indeterminate),
            "observed_succeeded" => Some(Self::ObservedSucceeded),
            "observed_failed" => Some(Self::ObservedFailed),
            "redacted" => Some(Self::Redacted),
            _ => None,
        }
    }

    fn unresolved(self) -> bool {
        matches!(
            self,
            Self::Prepared | Self::Dispatched | Self::Accepted | Self::Indeterminate
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchAuthority {
    pub operation_id: String,
    pub authority_epoch: Option<u64>,
    pub authority_binding_digest: Option<String>,
    pub grant_id: Option<String>,
    pub grant_payload_digest: Option<String>,
}

impl MatrixDispatchAuthority {
    pub fn owner_local(stable_txn_id: &MatrixTransactionId) -> Self {
        Self {
            operation_id: stable_txn_id.as_str().to_string(),
            authority_epoch: None,
            authority_binding_digest: None,
            grant_id: None,
            grant_payload_digest: None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchRecord {
    pub stable_txn_id: MatrixTransactionId,
    pub operation_id: String,
    pub room_id: MatrixRoomId,
    pub session_generation: u64,
    pub payload_digest: String,
    pub authority_epoch: Option<u64>,
    pub authority_binding_digest: Option<String>,
    pub grant_id: Option<String>,
    pub grant_payload_digest: Option<String>,
    pub state: MatrixDispatchState,
    pub attempt: u64,
    pub accepted_event_id: Option<MatrixEventId>,
    pub terminal_event_id: Option<MatrixEventId>,
    pub send_observation_digest: Option<String>,
    pub redaction_observation_digest: Option<String>,
    pub prepared_at_ms: u64,
    pub dispatched_at_ms: Option<u64>,
    pub accepted_at_ms: Option<u64>,
    pub terminal_observed_at_ms: Option<u64>,
    pub redacted_at_ms: Option<u64>,
    pub archived_at_ms: Option<u64>,
}

impl MatrixDurableStore {
    pub async fn prepare_matrix_dispatch(
        &self,
        outbox: &OutboxRecord,
        authority: &MatrixDispatchAuthority,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_authority(authority)?;
        if outbox.state != OutboxState::InFlight || outbox.attempts == 0 {
            return Err(MatrixDurableError::Conflict);
        }
        let payload_digest = Sha256Digest::for_bytes(&outbox.payload)
            .as_str()
            .to_string();
        if authority
            .grant_payload_digest
            .as_deref()
            .is_some_and(|digest| digest != payload_digest)
        {
            return Err(MatrixDurableError::AccessDenied);
        }

        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let existing = load_dispatch_tx(&mut tx, &outbox.stable_txn_id).await?;
        if let Some(existing) = existing {
            if existing.operation_id != authority.operation_id
                || existing.room_id != outbox.room_id
                || existing.session_generation != outbox.generation
                || existing.payload_digest != payload_digest
                || existing.authority_epoch != authority.authority_epoch
                || existing.authority_binding_digest != authority.authority_binding_digest
                || existing.grant_id != authority.grant_id
                || existing.grant_payload_digest != authority.grant_payload_digest
            {
                return Err(MatrixDurableError::Conflict);
            }
            tx.commit().await.map_err(unavailable)?;
            return self
                .matrix_dispatch(&outbox.stable_txn_id)
                .await?
                .ok_or(MatrixDurableError::Corrupt);
        }

        let unresolved: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE state IN ('prepared', 'dispatched', 'accepted', 'indeterminate')",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        if unresolved >= to_i64(MAX_UNRESOLVED_MATRIX_DISPATCHES)? {
            return Err(MatrixDurableError::Unavailable);
        }

        sqlx::query(
            "INSERT INTO matrix_dispatch_ledger (
                stable_txn_id, operation_id, room_id, session_generation,
                payload_sha256, authority_epoch, authority_binding_digest,
                grant_id, grant_payload_sha256, state, attempt, prepared_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)",
        )
        .bind(outbox.stable_txn_id.as_str())
        .bind(&authority.operation_id)
        .bind(outbox.room_id.as_str())
        .bind(to_i64(outbox.generation)?)
        .bind(&payload_digest)
        .bind(authority.authority_epoch.map(to_i64).transpose()?)
        .bind(authority.authority_binding_digest.as_deref())
        .bind(authority.grant_id.as_deref())
        .bind(authority.grant_payload_digest.as_deref())
        .bind(to_i64(outbox.attempts)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(&outbox.stable_txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn mark_matrix_dispatch_dispatched(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        observation_digest: &str,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(observation_digest)?;
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_dispatch_tx(&mut tx, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if current.state == MatrixDispatchState::Dispatched && current.attempt == expected_attempt {
            append_observation_tx(
                &mut tx,
                txn_id,
                "dispatched",
                observation_digest,
                None,
                now_ms,
            )
            .await?;
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        let retrying_uncertain = matches!(
            current.state,
            MatrixDispatchState::Dispatched | MatrixDispatchState::Indeterminate
        );
        if current.state != MatrixDispatchState::Prepared && !retrying_uncertain {
            return Err(MatrixDurableError::Conflict);
        }
        if (retrying_uncertain && expected_attempt <= current.attempt)
            || (current.state == MatrixDispatchState::Prepared
                && expected_attempt < current.attempt)
        {
            return Err(MatrixDurableError::Conflict);
        }
        let outbox_matches: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM outbox_messages
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        if outbox_matches != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        let updated = sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'dispatched', attempt = ?, dispatched_at_ms = ?,
                 accepted_event_id = NULL, accepted_at_ms = NULL
             WHERE stable_txn_id = ? AND state = ? AND attempt = ?",
        )
        .bind(to_i64(expected_attempt)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(current.state.as_str())
        .bind(to_i64(current.attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        append_observation_tx(
            &mut tx,
            txn_id,
            "dispatched",
            observation_digest,
            None,
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn mark_matrix_dispatch_accepted(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        event_id: &MatrixEventId,
        observation_digest: &str,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_dispatch_tx(&mut tx, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if matches!(
            current.state,
            MatrixDispatchState::ObservedSucceeded | MatrixDispatchState::Redacted
        ) && current.terminal_event_id.as_ref() == Some(event_id)
        {
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state == MatrixDispatchState::Accepted
            && current.attempt == expected_attempt
            && current.accepted_event_id.as_ref() == Some(event_id)
        {
            append_observation_tx(
                &mut tx,
                txn_id,
                "accepted",
                observation_digest,
                Some(event_id),
                now_ms,
            )
            .await?;
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state != MatrixDispatchState::Dispatched || current.attempt != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'accepted', accepted_event_id = ?, accepted_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'dispatched' AND attempt = ?",
        )
        .bind(event_id.as_str())
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let parked = sqlx::query(
            "UPDATE outbox_messages
             SET lease_until_ms = ?, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(PARKED_LEASE_UNTIL_MS)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if parked.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        append_observation_tx(
            &mut tx,
            txn_id,
            "accepted",
            observation_digest,
            Some(event_id),
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn mark_matrix_dispatch_indeterminate(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        observation_digest: &str,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_dispatch_tx(&mut tx, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if matches!(
            current.state,
            MatrixDispatchState::ObservedSucceeded | MatrixDispatchState::Redacted
        ) {
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state == MatrixDispatchState::Indeterminate
            && current.attempt == expected_attempt
        {
            append_observation_tx(
                &mut tx,
                txn_id,
                "indeterminate",
                observation_digest,
                None,
                now_ms,
            )
            .await?;
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state != MatrixDispatchState::Dispatched || current.attempt != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'indeterminate'
             WHERE stable_txn_id = ? AND state = 'dispatched' AND attempt = ?",
        )
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        append_observation_tx(
            &mut tx,
            txn_id,
            "indeterminate",
            observation_digest,
            None,
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn park_matrix_dispatch_indeterminate(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_dispatch_tx(&mut tx, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if current.state != MatrixDispatchState::Indeterminate
            || current.attempt != expected_attempt
        {
            return Err(MatrixDurableError::Conflict);
        }
        let parked = sqlx::query(
            "UPDATE outbox_messages
             SET lease_until_ms = ?, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(PARKED_LEASE_UNTIL_MS)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if parked.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        tx.commit().await.map_err(unavailable)?;
        Ok(current)
    }

    pub async fn mark_matrix_dispatch_retryable(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        observation_digest: &str,
        now_ms: u64,
        next_attempt_at_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(observation_digest)?;
        if expected_attempt == 0 || next_attempt_at_ms < now_ms {
            return Err(MatrixDurableError::Invalid);
        }
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_dispatch_tx(&mut tx, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if matches!(
            current.state,
            MatrixDispatchState::ObservedSucceeded | MatrixDispatchState::Redacted
        ) {
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state != MatrixDispatchState::Dispatched || current.attempt != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'prepared', accepted_event_id = NULL, accepted_at_ms = NULL
             WHERE stable_txn_id = ? AND state = 'dispatched' AND attempt = ?",
        )
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let updated = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'retry_scheduled', next_attempt_at_ms = ?,
                 lease_until_ms = NULL, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(to_i64(next_attempt_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        append_observation_tx(
            &mut tx,
            txn_id,
            "retryable",
            observation_digest,
            None,
            now_ms,
        )
        .await?;
        append_change_tx(
            &mut tx,
            "outbox_retry_scheduled",
            &current.room_id,
            None,
            txn_id,
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn mark_matrix_dispatch_failed(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        observation_digest: &str,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_dispatch_tx(&mut tx, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if matches!(
            current.state,
            MatrixDispatchState::ObservedSucceeded | MatrixDispatchState::Redacted
        ) {
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state == MatrixDispatchState::ObservedFailed
            && current.send_observation_digest.as_deref() == Some(observation_digest)
        {
            tx.commit().await.map_err(unavailable)?;
            return Ok(current);
        }
        if current.state != MatrixDispatchState::Dispatched || current.attempt != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'observed_failed', send_observation_digest = ?,
                 terminal_observed_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'dispatched' AND attempt = ?",
        )
        .bind(observation_digest)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let failed = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'permanent_failure', lease_until_ms = NULL, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(expected_attempt)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if failed.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        append_observation_tx(
            &mut tx,
            txn_id,
            "terminal_failure",
            observation_digest,
            None,
            now_ms,
        )
        .await?;
        append_change_tx(
            &mut tx,
            "outbox_failed",
            &current.room_id,
            None,
            txn_id,
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn observe_matrix_dispatch_succeeded(
        &self,
        txn_id: Option<&MatrixTransactionId>,
        event_id: &MatrixEventId,
        room_id: &MatrixRoomId,
        observation_digest: &str,
        now_ms: u64,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = match txn_id {
            Some(txn_id) => load_dispatch_tx(&mut tx, txn_id).await?,
            None => load_dispatch_by_event_tx(&mut tx, event_id).await?,
        };
        let Some(current) = current else {
            tx.commit().await.map_err(unavailable)?;
            return Ok(None);
        };
        if &current.room_id != room_id {
            return Err(MatrixDurableError::Conflict);
        }
        if current.state == MatrixDispatchState::ObservedSucceeded
            && current.terminal_event_id.as_ref() == Some(event_id)
            && current.send_observation_digest.as_deref() == Some(observation_digest)
        {
            tx.commit().await.map_err(unavailable)?;
            return Ok(Some(current));
        }
        if current.state == MatrixDispatchState::Redacted {
            if current.terminal_event_id.as_ref() == Some(event_id)
                && current.send_observation_digest.as_deref() == Some(observation_digest)
            {
                tx.commit().await.map_err(unavailable)?;
                return Ok(Some(current));
            }
            return Err(MatrixDurableError::Conflict);
        }
        if !current.state.unresolved() {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(accepted) = &current.accepted_event_id
            && accepted != event_id
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'observed_succeeded', terminal_event_id = ?,
                 send_observation_digest = ?, terminal_observed_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(event_id.as_str())
        .bind(observation_digest)
        .bind(to_i64(now_ms)?)
        .bind(current.stable_txn_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        let outbox = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'sent', lease_until_ms = NULL, sent_event_id = ?, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state IN ('pending', 'in_flight', 'retry_scheduled')",
        )
        .bind(event_id.as_str())
        .bind(to_i64(now_ms)?)
        .bind(current.stable_txn_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if outbox.rows_affected() == 0 {
            let existing: Option<(String, Option<String>)> = sqlx::query_as(
                "SELECT state, sent_event_id FROM outbox_messages WHERE stable_txn_id = ?",
            )
            .bind(current.stable_txn_id.as_str())
            .fetch_optional(&mut *tx)
            .await
            .map_err(unavailable)?;
            if existing.as_ref() != Some(&("sent".to_string(), Some(event_id.as_str().to_string())))
            {
                return Err(MatrixDurableError::Conflict);
            }
        }
        append_observation_tx(
            &mut tx,
            &current.stable_txn_id,
            "terminal_success",
            observation_digest,
            Some(event_id),
            now_ms,
        )
        .await?;
        append_change_tx(
            &mut tx,
            "outbox_sent",
            &current.room_id,
            Some(event_id),
            &current.stable_txn_id,
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(&current.stable_txn_id).await
    }

    pub async fn observe_matrix_dispatch_redacted(
        &self,
        event_id: &MatrixEventId,
        redaction_digest: &str,
        now_ms: u64,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        validate_digest(redaction_digest)?;
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_dispatch_by_terminal_event_tx(&mut tx, event_id).await?;
        let Some(current) = current else {
            tx.commit().await.map_err(unavailable)?;
            return Ok(None);
        };
        if current.state == MatrixDispatchState::Redacted {
            if current.redaction_observation_digest.as_deref() == Some(redaction_digest) {
                tx.commit().await.map_err(unavailable)?;
                return Ok(Some(current));
            }
            return Err(MatrixDurableError::Conflict);
        }
        if current.state != MatrixDispatchState::ObservedSucceeded {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'redacted', redaction_observation_digest = ?, redacted_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'observed_succeeded'",
        )
        .bind(redaction_digest)
        .bind(to_i64(now_ms)?)
        .bind(current.stable_txn_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        append_observation_tx(
            &mut tx,
            &current.stable_txn_id,
            "redaction",
            redaction_digest,
            Some(event_id),
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        self.matrix_dispatch(&current.stable_txn_id).await
    }

    pub async fn matrix_dispatch(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        let row = sqlx::query(
            "SELECT stable_txn_id, operation_id, room_id, session_generation,
                    payload_sha256, authority_epoch, authority_binding_digest,
                    grant_id, grant_payload_sha256, state, attempt,
                    accepted_event_id, terminal_event_id, send_observation_digest,
                    redaction_observation_digest, prepared_at_ms, dispatched_at_ms,
                    accepted_at_ms, terminal_observed_at_ms, redacted_at_ms, archived_at_ms
             FROM matrix_dispatch_ledger WHERE stable_txn_id = ?",
        )
        .bind(txn_id.as_str())
        .fetch_optional(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        row.as_ref().map(dispatch_from_row).transpose()
    }

    pub async fn archive_terminal_matrix_dispatches(
        &self,
        terminal_before_ms: u64,
        archived_at_ms: u64,
        limit: usize,
    ) -> Result<u64, MatrixDurableError> {
        if limit == 0 || limit > 4_096 || archived_at_ms < terminal_before_ms {
            return Err(MatrixDurableError::Invalid);
        }
        let result = sqlx::query(
            "UPDATE matrix_dispatch_ledger SET archived_at_ms = ?
             WHERE stable_txn_id IN (
                 SELECT stable_txn_id FROM matrix_dispatch_ledger
                 WHERE archived_at_ms IS NULL
                   AND state IN ('observed_succeeded', 'observed_failed', 'redacted')
                   AND COALESCE(redacted_at_ms, terminal_observed_at_ms) <= ?
                 ORDER BY COALESCE(redacted_at_ms, terminal_observed_at_ms), stable_txn_id
                 LIMIT ?
             )",
        )
        .bind(to_i64(archived_at_ms)?)
        .bind(to_i64(terminal_before_ms)?)
        .bind(to_i64(limit as u64)?)
        .execute(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        Ok(result.rows_affected())
    }
}

async fn load_dispatch_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    let row = sqlx::query(
        "SELECT stable_txn_id, operation_id, room_id, session_generation,
                payload_sha256, authority_epoch, authority_binding_digest,
                grant_id, grant_payload_sha256, state, attempt,
                accepted_event_id, terminal_event_id, send_observation_digest,
                redaction_observation_digest, prepared_at_ms, dispatched_at_ms,
                accepted_at_ms, terminal_observed_at_ms, redacted_at_ms, archived_at_ms
         FROM matrix_dispatch_ledger WHERE stable_txn_id = ?",
    )
    .bind(txn_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    row.as_ref().map(dispatch_from_row).transpose()
}

async fn load_dispatch_by_event_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    event_id: &MatrixEventId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    let row = sqlx::query(
        "SELECT stable_txn_id, operation_id, room_id, session_generation,
                payload_sha256, authority_epoch, authority_binding_digest,
                grant_id, grant_payload_sha256, state, attempt,
                accepted_event_id, terminal_event_id, send_observation_digest,
                redaction_observation_digest, prepared_at_ms, dispatched_at_ms,
                accepted_at_ms, terminal_observed_at_ms, redacted_at_ms, archived_at_ms
         FROM matrix_dispatch_ledger
         WHERE accepted_event_id = ? OR terminal_event_id = ?
         ORDER BY terminal_event_id IS NOT NULL DESC LIMIT 1",
    )
    .bind(event_id.as_str())
    .bind(event_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    row.as_ref().map(dispatch_from_row).transpose()
}

async fn load_dispatch_by_terminal_event_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    event_id: &MatrixEventId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    let row = sqlx::query(
        "SELECT stable_txn_id, operation_id, room_id, session_generation,
                payload_sha256, authority_epoch, authority_binding_digest,
                grant_id, grant_payload_sha256, state, attempt,
                accepted_event_id, terminal_event_id, send_observation_digest,
                redaction_observation_digest, prepared_at_ms, dispatched_at_ms,
                accepted_at_ms, terminal_observed_at_ms, redacted_at_ms, archived_at_ms
         FROM matrix_dispatch_ledger WHERE terminal_event_id = ?",
    )
    .bind(event_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    row.as_ref().map(dispatch_from_row).transpose()
}

async fn append_observation_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    txn_id: &MatrixTransactionId,
    kind: &str,
    digest: &str,
    event_id: Option<&MatrixEventId>,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "INSERT INTO matrix_dispatch_observations (
            stable_txn_id, observation_kind, observation_digest,
            server_event_id, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(stable_txn_id, observation_kind, observation_digest) DO NOTHING",
    )
    .bind(txn_id.as_str())
    .bind(kind)
    .bind(digest)
    .bind(event_id.map(MatrixEventId::as_str))
    .bind(to_i64(observed_at_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn append_change_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    kind: &str,
    room_id: &MatrixRoomId,
    event_id: Option<&MatrixEventId>,
    txn_id: &MatrixTransactionId,
    recorded_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "INSERT INTO change_log (kind, room_id, event_id, txn_id, recorded_at_ms)
         VALUES (?, ?, ?, ?, ?)",
    )
    .bind(kind)
    .bind(room_id.as_str())
    .bind(event_id.map(MatrixEventId::as_str))
    .bind(txn_id.as_str())
    .bind(to_i64(recorded_at_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn dispatch_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<MatrixDispatchRecord, MatrixDurableError> {
    let state: String = row.try_get("state").map_err(unavailable)?;
    let stable_txn_id: String = row.try_get("stable_txn_id").map_err(unavailable)?;
    let room_id: String = row.try_get("room_id").map_err(unavailable)?;
    let accepted_event_id: Option<String> =
        row.try_get("accepted_event_id").map_err(unavailable)?;
    let terminal_event_id: Option<String> =
        row.try_get("terminal_event_id").map_err(unavailable)?;
    Ok(MatrixDispatchRecord {
        stable_txn_id: MatrixTransactionId::parse(stable_txn_id)
            .map_err(|_| MatrixDurableError::Corrupt)?,
        operation_id: row.try_get("operation_id").map_err(unavailable)?,
        room_id: MatrixRoomId::parse(room_id).map_err(|_| MatrixDurableError::Corrupt)?,
        session_generation: from_i64(row.try_get("session_generation").map_err(unavailable)?)?,
        payload_digest: row.try_get("payload_sha256").map_err(unavailable)?,
        authority_epoch: optional_u64(row.try_get("authority_epoch").map_err(unavailable)?)?,
        authority_binding_digest: row
            .try_get("authority_binding_digest")
            .map_err(unavailable)?,
        grant_id: row.try_get("grant_id").map_err(unavailable)?,
        grant_payload_digest: row.try_get("grant_payload_sha256").map_err(unavailable)?,
        state: MatrixDispatchState::parse(&state).ok_or(MatrixDurableError::Corrupt)?,
        attempt: from_i64(row.try_get("attempt").map_err(unavailable)?)?,
        accepted_event_id: accepted_event_id
            .map(MatrixEventId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)?,
        terminal_event_id: terminal_event_id
            .map(MatrixEventId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)?,
        send_observation_digest: row
            .try_get("send_observation_digest")
            .map_err(unavailable)?,
        redaction_observation_digest: row
            .try_get("redaction_observation_digest")
            .map_err(unavailable)?,
        prepared_at_ms: from_i64(row.try_get("prepared_at_ms").map_err(unavailable)?)?,
        dispatched_at_ms: optional_u64(row.try_get("dispatched_at_ms").map_err(unavailable)?)?,
        accepted_at_ms: optional_u64(row.try_get("accepted_at_ms").map_err(unavailable)?)?,
        terminal_observed_at_ms: optional_u64(
            row.try_get("terminal_observed_at_ms")
                .map_err(unavailable)?,
        )?,
        redacted_at_ms: optional_u64(row.try_get("redacted_at_ms").map_err(unavailable)?)?,
        archived_at_ms: optional_u64(row.try_get("archived_at_ms").map_err(unavailable)?)?,
    })
}

fn validate_authority(value: &MatrixDispatchAuthority) -> Result<(), MatrixDurableError> {
    if !valid_identity(&value.operation_id)
        || value.authority_epoch == Some(0)
        || value
            .authority_binding_digest
            .as_deref()
            .is_some_and(|value| !valid_digest(value))
        || value
            .grant_id
            .as_deref()
            .is_some_and(|value| !valid_identity(value))
        || value
            .grant_payload_digest
            .as_deref()
            .is_some_and(|value| !valid_digest(value))
        || value.grant_id.is_some() != value.grant_payload_digest.is_some()
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), MatrixDurableError> {
    if valid_digest(value) {
        Ok(())
    } else {
        Err(MatrixDurableError::Invalid)
    }
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:/-".contains(&byte))
}

fn to_i64(value: u64) -> Result<i64, MatrixDurableError> {
    i64::try_from(value).map_err(|_| MatrixDurableError::Invalid)
}

fn from_i64(value: i64) -> Result<u64, MatrixDurableError> {
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn optional_u64(value: Option<i64>) -> Result<Option<u64>, MatrixDurableError> {
    value.map(from_i64).transpose()
}

fn unavailable<T>(_: T) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}
