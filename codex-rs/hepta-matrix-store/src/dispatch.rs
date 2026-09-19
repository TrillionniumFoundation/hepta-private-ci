use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::MatrixEventId;
use crate::MatrixTransactionId;
use crate::MatrixRoomId;
use crate::OutboxRecord;

const MAX_UNRESOLVED_DISPATCHES: i64 = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixDispatchState {
    Prepared,
    Dispatched,
    Accepted,
    Indeterminate,
    Succeeded,
    Failed,
    Redacted,
}

impl MatrixDispatchState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatched => "dispatched",
            Self::Accepted => "accepted",
            Self::Indeterminate => "indeterminate",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Redacted => "redacted",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "prepared" => Some(Self::Prepared),
            "dispatched" => Some(Self::Dispatched),
            "accepted" => Some(Self::Accepted),
            "indeterminate" => Some(Self::Indeterminate),
            "succeeded" => Some(Self::Succeeded),
            "failed" => Some(Self::Failed),
            "redacted" => Some(Self::Redacted),
            _ => None,
        }
    }

    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Redacted)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchRecord {
    pub stable_txn_id: MatrixTransactionId,
    pub operation_id: String,
    pub room_id: String,
    pub homeserver_id: Option<String>,
    pub device_id: Option<String>,
    pub session_generation: Option<u64>,
    pub payload_sha256: String,
    pub binding_revision: u64,
    pub generation: u64,
    pub authority_epoch: Option<u64>,
    pub grant_id: Option<String>,
    pub grant_payload_sha256: Option<String>,
    pub deadline_ms: Option<u64>,
    pub state: MatrixDispatchState,
    pub transport_event_id: Option<MatrixEventId>,
    pub terminal_event_id: Option<MatrixEventId>,
    pub send_observation_digest: Option<String>,
    pub redaction_observation_digest: Option<String>,
    pub prepared_at_ms: u64,
    pub updated_at_ms: u64,
    pub terminal_at_ms: Option<u64>,
}

impl MatrixDurableStore {
    pub async fn prepare_dispatch(
        &self,
        record: &OutboxRecord,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let existing = dispatch_by_txn_tx(&mut transaction, &record.stable_txn_id).await?;
        if let Some(existing) = existing {
            verify_outbox_binding(&existing, record)?;
            transaction
                .commit()
                .await
                .map_err(|_| MatrixDurableError::Unavailable)?;
            return Ok(existing);
        }
        let unresolved: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE state IN ('prepared', 'dispatched', 'accepted', 'indeterminate')",
        )
        .fetch_one(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        if unresolved >= MAX_UNRESOLVED_DISPATCHES {
            return Err(MatrixDurableError::Conflict);
        }
        let payload_sha256 = Sha256Digest::for_bytes(&record.payload).as_str().to_string();
        sqlx::query(
            "INSERT INTO matrix_dispatch_ledger (
                stable_txn_id, operation_id, room_id, payload_sha256,
                binding_revision, generation, state, prepared_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, 'prepared', ?, ?)",
        )
        .bind(record.stable_txn_id.as_str())
        .bind(record.stable_txn_id.as_str())
        .bind(record.room_id.as_str())
        .bind(&payload_sha256)
        .bind(to_i64(record.binding_revision)?)
        .bind(to_i64(record.generation)?)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        let created = dispatch_by_txn_tx(&mut transaction, &record.stable_txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        Ok(created)
    }

    pub async fn bind_dispatch_authority(
        &self,
        txn_id: &MatrixTransactionId,
        operation_id: &str,
        homeserver_id: &str,
        device_id: &str,
        session_generation: u64,
        authority_epoch: u64,
        grant_id: &str,
        grant_payload_sha256: &str,
        deadline_ms: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_identity(operation_id)?;
        validate_identity(homeserver_id)?;
        validate_identity(device_id)?;
        validate_identity(grant_id)?;
        validate_digest(grant_payload_sha256)?;
        if session_generation == 0 || authority_epoch == 0 || deadline_ms <= now_ms {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if current.state.is_terminal()
            || current.payload_sha256 != grant_payload_sha256
            || current.updated_at_ms > now_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET operation_id = ?, homeserver_id = ?, device_id = ?,
                 session_generation = ?, authority_epoch = ?, grant_id = ?,
                 grant_payload_sha256 = ?, deadline_ms = ?, updated_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(operation_id)
        .bind(homeserver_id)
        .bind(device_id)
        .bind(to_i64(session_generation)?)
        .bind(to_i64(authority_epoch)?)
        .bind(grant_id)
        .bind(grant_payload_sha256)
        .bind(to_i64(deadline_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        let updated = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        Ok(updated)
    }

    pub async fn mark_dispatch_dispatched(
        &self,
        txn_id: &MatrixTransactionId,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        self.transition_unresolved(txn_id, MatrixDispatchState::Dispatched, None, now_ms)
            .await
    }

    pub async fn mark_dispatch_transport_accepted(
        &self,
        txn_id: &MatrixTransactionId,
        event_id: &MatrixEventId,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        self.transition_unresolved(
            txn_id,
            MatrixDispatchState::Accepted,
            Some(event_id),
            now_ms,
        )
        .await
    }

    pub async fn mark_dispatch_indeterminate(
        &self,
        txn_id: &MatrixTransactionId,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        self.transition_unresolved(txn_id, MatrixDispatchState::Indeterminate, None, now_ms)
            .await
    }

    async fn transition_unresolved(
        &self,
        txn_id: &MatrixTransactionId,
        next: MatrixDispatchState,
        event_id: Option<&MatrixEventId>,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if current.state.is_terminal() {
            if next == MatrixDispatchState::Accepted
                && event_id.is_some()
                && current.terminal_event_id.as_ref() != event_id
                && current.transport_event_id.as_ref() != event_id
            {
                return Err(MatrixDurableError::Conflict);
            }
            transaction
                .commit()
                .await
                .map_err(|_| MatrixDurableError::Unavailable)?;
            return Ok(current);
        }
        if now_ms < current.updated_at_ms {
            return Err(MatrixDurableError::Conflict);
        }
        let kind = match next {
            MatrixDispatchState::Dispatched => "dispatched",
            MatrixDispatchState::Accepted => "transport_accepted",
            MatrixDispatchState::Indeterminate => "indeterminate",
            _ => return Err(MatrixDurableError::Invalid),
        };
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = ?, transport_event_id = COALESCE(?, transport_event_id),
                 updated_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(next.as_str())
        .bind(event_id.map(MatrixEventId::as_str))
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        append_observation(
            &mut transaction,
            txn_id,
            kind,
            event_id.map(MatrixEventId::as_str).unwrap_or(""),
            "",
            now_ms,
        )
        .await?;
        let updated = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        Ok(updated)
    }

    pub async fn observe_dispatch_terminal_success_if_known(
        &self,
        txn_id: &MatrixTransactionId,
        room_id: &MatrixRoomId,
        event_id: &MatrixEventId,
        observation_digest: &str,
        observed_at_ms: u64,
    ) -> Result<bool, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let Some(current) = dispatch_by_txn_tx(&mut transaction, txn_id).await? else {
            transaction
                .commit()
                .await
                .map_err(|_| MatrixDurableError::Unavailable)?;
            return Ok(false);
        };
        if current.state == MatrixDispatchState::Succeeded {
            if current.terminal_event_id.as_ref() == Some(event_id)
                && current.send_observation_digest.as_deref() == Some(observation_digest)
            {
                transaction
                    .commit()
                    .await
                    .map_err(|_| MatrixDurableError::Unavailable)?;
                return Ok(true);
            }
            return Err(MatrixDurableError::Conflict);
        }
        if matches!(current.state, MatrixDispatchState::Failed | MatrixDispatchState::Redacted)
            || current.room_id != room_id.as_str()
            || current
                .transport_event_id
                .as_ref()
                .is_some_and(|transport_event_id| transport_event_id != event_id)
            || observed_at_ms < current.updated_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'succeeded', terminal_event_id = ?,
                 send_observation_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(event_id.as_str())
        .bind(observation_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        append_observation(
            &mut transaction,
            txn_id,
            "terminal_success",
            event_id.as_str(),
            observation_digest,
            observed_at_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE outbox_messages
             SET state = 'sent', lease_until_ms = NULL, sent_event_id = ?,
                 updated_at_ms = MAX(updated_at_ms, ?)
             WHERE stable_txn_id = ? AND state != 'sent'",
        )
        .bind(event_id.as_str())
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        self.compact_dispatch_observations(txn_id, observed_at_ms).await?;
        Ok(true)
    }

    pub async fn observe_dispatch_terminal_failure_if_known(
        &self,
        txn_id: &MatrixTransactionId,
        room_id: &MatrixRoomId,
        observation_digest: &str,
        observed_at_ms: u64,
    ) -> Result<bool, MatrixDurableError> {
        validate_digest(observation_digest)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let Some(current) = dispatch_by_txn_tx(&mut transaction, txn_id).await? else {
            transaction
                .commit()
                .await
                .map_err(|_| MatrixDurableError::Unavailable)?;
            return Ok(false);
        };
        if current.state == MatrixDispatchState::Failed {
            if current.send_observation_digest.as_deref() == Some(observation_digest) {
                transaction
                    .commit()
                    .await
                    .map_err(|_| MatrixDurableError::Unavailable)?;
                return Ok(true);
            }
            return Err(MatrixDurableError::Conflict);
        }
        if matches!(current.state, MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted)
            || current.room_id != room_id.as_str()
            || observed_at_ms < current.updated_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'failed', send_observation_digest = ?,
                 updated_at_ms = ?, terminal_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(observation_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        append_observation(
            &mut transaction,
            txn_id,
            "terminal_failure",
            "",
            observation_digest,
            observed_at_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE outbox_messages
             SET state = 'permanent_failure', lease_until_ms = NULL,
                 updated_at_ms = MAX(updated_at_ms, ?), sent_event_id = NULL
             WHERE stable_txn_id = ? AND state != 'sent'",
        )
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        self.compact_dispatch_observations(txn_id, observed_at_ms).await?;
        Ok(true)
    }

    pub async fn observe_dispatch_redaction_if_known(
        &self,
        room_id: &MatrixRoomId,
        target_event_id: &MatrixEventId,
        redaction_digest: &str,
        observed_at_ms: u64,
    ) -> Result<bool, MatrixDurableError> {
        validate_digest(redaction_digest)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let row = sqlx::query(
            "SELECT stable_txn_id FROM matrix_dispatch_ledger
             WHERE terminal_event_id = ? LIMIT 1",
        )
        .bind(target_event_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        let Some(row) = row else {
            transaction
                .commit()
                .await
                .map_err(|_| MatrixDurableError::Unavailable)?;
            return Ok(false);
        };
        let txn_id = MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(|_| MatrixDurableError::Unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?;
        let current = dispatch_by_txn_tx(&mut transaction, &txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)?;
        if current.state == MatrixDispatchState::Redacted {
            if current.redaction_observation_digest.as_deref() == Some(redaction_digest) {
                transaction
                    .commit()
                    .await
                    .map_err(|_| MatrixDurableError::Unavailable)?;
                return Ok(true);
            }
            return Err(MatrixDurableError::Conflict);
        }
        if current.state != MatrixDispatchState::Succeeded
            || current.room_id != room_id.as_str()
            || observed_at_ms < current.updated_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'redacted', redaction_observation_digest = ?,
                 updated_at_ms = ?, terminal_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(redaction_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        append_observation(
            &mut transaction,
            &txn_id,
            "redaction",
            target_event_id.as_str(),
            redaction_digest,
            observed_at_ms,
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        self.compact_dispatch_observations(&txn_id, observed_at_ms).await?;
        Ok(true)
    }

    pub async fn compact_dispatch_observations(
        &self,
        txn_id: &MatrixTransactionId,
        archived_at_ms: u64,
    ) -> Result<bool, MatrixDurableError> {
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let current = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if !current.state.is_terminal() {
            return Err(MatrixDurableError::Conflict);
        }
        let prior_archive_digest = sqlx::query(
            "SELECT segment_digest
             FROM matrix_dispatch_observation_archives
             WHERE stable_txn_id = ?
             ORDER BY archive_seq DESC LIMIT 1",
        )
        .bind(txn_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?
        .map(|row| row.try_get::<String, _>("segment_digest"))
        .transpose()
        .map_err(|_| MatrixDurableError::Unavailable)?
        .unwrap_or_else(|| "0".repeat(64));
        let rows = sqlx::query(
            "SELECT observation_seq, kind, event_id, evidence_digest, observed_at_ms
             FROM matrix_dispatch_observations
             WHERE stable_txn_id = ?
             ORDER BY observation_seq",
        )
        .bind(txn_id.as_str())
        .fetch_all(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        if rows.is_empty() {
            transaction
                .commit()
                .await
                .map_err(|_| MatrixDurableError::Unavailable)?;
            return Ok(false);
        }
        let mut encoded = Vec::new();
        encoded.extend_from_slice(b"hepta.matrix.dispatch-observation-archive.v1");
        encode_field(&mut encoded, prior_archive_digest.as_bytes());
        let mut first_observed_at_ms = None;
        let mut last_observed_at_ms = 0_u64;
        let mut last_sequence = 0_i64;
        for row in &rows {
            let sequence: i64 = row
                .try_get("observation_seq")
                .map_err(|_| MatrixDurableError::Unavailable)?;
            let kind: String = row
                .try_get("kind")
                .map_err(|_| MatrixDurableError::Unavailable)?;
            let event_id: String = row
                .try_get("event_id")
                .map_err(|_| MatrixDurableError::Unavailable)?;
            let evidence_digest: String = row
                .try_get("evidence_digest")
                .map_err(|_| MatrixDurableError::Unavailable)?;
            let observed_at_ms = to_u64(
                row.try_get("observed_at_ms")
                    .map_err(|_| MatrixDurableError::Unavailable)?,
            )?;
            encode_field(&mut encoded, kind.as_bytes());
            encode_field(&mut encoded, event_id.as_bytes());
            encode_field(&mut encoded, evidence_digest.as_bytes());
            encoded.extend_from_slice(&observed_at_ms.to_be_bytes());
            first_observed_at_ms.get_or_insert(observed_at_ms);
            last_observed_at_ms = observed_at_ms;
            last_sequence = sequence;
        }
        if archived_at_ms < last_observed_at_ms {
            return Err(MatrixDurableError::Invalid);
        }
        let segment_digest = Sha256Digest::for_bytes(&encoded).as_str().to_string();
        sqlx::query(
            "INSERT INTO matrix_dispatch_observation_archives (
                stable_txn_id, prior_archive_digest, segment_digest,
                observation_count, first_observed_at_ms, last_observed_at_ms,
                archived_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(txn_id.as_str())
        .bind(&prior_archive_digest)
        .bind(&segment_digest)
        .bind(to_i64(rows.len() as u64)?)
        .bind(to_i64(first_observed_at_ms.ok_or(MatrixDurableError::Corrupt)?)?)
        .bind(to_i64(last_observed_at_ms)?)
        .bind(to_i64(archived_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        sqlx::query(
            "DELETE FROM matrix_dispatch_observations
             WHERE stable_txn_id = ? AND observation_seq <= ?",
        )
        .bind(txn_id.as_str())
        .bind(last_sequence)
        .execute(&mut *transaction)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        Ok(true)
    }

    pub async fn dispatch_archive_segment_count(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<u64, MatrixDurableError> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_observation_archives
             WHERE stable_txn_id = ?",
        )
        .bind(txn_id.as_str())
        .fetch_one(self.sqlite_pool())
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        u64::try_from(count).map_err(|_| MatrixDurableError::Corrupt)
    }

    pub async fn dispatch_record(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        let mut transaction = self
            .sqlite_pool()
            .begin()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        let record = dispatch_by_txn_tx(&mut transaction, txn_id).await?;
        transaction
            .commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        Ok(record)
    }

    pub async fn unresolved_dispatch_count(&self) -> Result<u64, MatrixDurableError> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE state IN ('prepared', 'dispatched', 'accepted', 'indeterminate')",
        )
        .fetch_one(self.sqlite_pool())
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        u64::try_from(count).map_err(|_| MatrixDurableError::Corrupt)
    }
}

fn verify_outbox_binding(
    dispatch: &MatrixDispatchRecord,
    outbox: &OutboxRecord,
) -> Result<(), MatrixDurableError> {
    if dispatch.stable_txn_id != outbox.stable_txn_id
        || dispatch.room_id != outbox.room_id.as_str()
        || dispatch.payload_sha256 != Sha256Digest::for_bytes(&outbox.payload).as_str()
        || dispatch.binding_revision != outbox.binding_revision
        || dispatch.generation != outbox.generation
    {
        return Err(MatrixDurableError::Conflict);
    }
    Ok(())
}

async fn dispatch_by_txn_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    let row = sqlx::query(
        "SELECT stable_txn_id, operation_id, room_id, homeserver_id, device_id,
                session_generation, payload_sha256,
                binding_revision, generation, authority_epoch, grant_id, grant_payload_sha256,
                deadline_ms, state, transport_event_id, terminal_event_id,
                send_observation_digest, redaction_observation_digest,
                prepared_at_ms, updated_at_ms, terminal_at_ms
         FROM matrix_dispatch_ledger WHERE stable_txn_id = ?",
    )
    .bind(txn_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(|_| MatrixDurableError::Unavailable)?;
    row.map(dispatch_from_row).transpose()
}

fn dispatch_from_row(row: sqlx::sqlite::SqliteRow) -> Result<MatrixDispatchRecord, MatrixDurableError> {
    let state = MatrixDispatchState::parse(
        row.try_get::<String, _>("state")
            .map_err(|_| MatrixDurableError::Unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    Ok(MatrixDispatchRecord {
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(|_| MatrixDurableError::Unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        operation_id: row.try_get("operation_id").map_err(|_| MatrixDurableError::Unavailable)?,
        room_id: row.try_get("room_id").map_err(|_| MatrixDurableError::Unavailable)?,
        homeserver_id: row.try_get("homeserver_id").map_err(|_| MatrixDurableError::Unavailable)?,
        device_id: row.try_get("device_id").map_err(|_| MatrixDurableError::Unavailable)?,
        session_generation: row.try_get::<Option<i64>, _>("session_generation").map_err(|_| MatrixDurableError::Unavailable)?.map(to_u64).transpose()?,
        payload_sha256: row.try_get("payload_sha256").map_err(|_| MatrixDurableError::Unavailable)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(|_| MatrixDurableError::Unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(|_| MatrixDurableError::Unavailable)?)?,
        authority_epoch: row.try_get::<Option<i64>, _>("authority_epoch").map_err(|_| MatrixDurableError::Unavailable)?.map(to_u64).transpose()?,
        grant_id: row.try_get("grant_id").map_err(|_| MatrixDurableError::Unavailable)?,
        grant_payload_sha256: row.try_get("grant_payload_sha256").map_err(|_| MatrixDurableError::Unavailable)?,
        deadline_ms: row.try_get::<Option<i64>, _>("deadline_ms").map_err(|_| MatrixDurableError::Unavailable)?.map(to_u64).transpose()?,
        state,
        transport_event_id: row.try_get::<Option<String>, _>("transport_event_id").map_err(|_| MatrixDurableError::Unavailable)?.map(MatrixEventId::parse).transpose().map_err(|_| MatrixDurableError::Corrupt)?,
        terminal_event_id: row.try_get::<Option<String>, _>("terminal_event_id").map_err(|_| MatrixDurableError::Unavailable)?.map(MatrixEventId::parse).transpose().map_err(|_| MatrixDurableError::Corrupt)?,
        send_observation_digest: row.try_get("send_observation_digest").map_err(|_| MatrixDurableError::Unavailable)?,
        redaction_observation_digest: row.try_get("redaction_observation_digest").map_err(|_| MatrixDurableError::Unavailable)?,
        prepared_at_ms: to_u64(row.try_get("prepared_at_ms").map_err(|_| MatrixDurableError::Unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(|_| MatrixDurableError::Unavailable)?)?,
        terminal_at_ms: row.try_get::<Option<i64>, _>("terminal_at_ms").map_err(|_| MatrixDurableError::Unavailable)?.map(to_u64).transpose()?,
    })
}

async fn append_observation(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    kind: &str,
    event_id: &str,
    evidence_digest: &str,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "INSERT INTO matrix_dispatch_observations (
            stable_txn_id, kind, event_id, evidence_digest, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(stable_txn_id, kind, event_id, evidence_digest, observed_at_ms) DO NOTHING",
    )
    .bind(txn_id.as_str())
    .bind(kind)
    .bind(event_id)
    .bind(evidence_digest)
    .bind(to_i64(observed_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(|_| MatrixDurableError::Unavailable)?;
    Ok(())
}

fn encode_field(target: &mut Vec<u8>, value: &[u8]) {
    target.extend_from_slice(&(value.len() as u64).to_be_bytes());
    target.extend_from_slice(value);
}

fn validate_identity(value: &str) -> Result<(), MatrixDurableError> {
    if value.is_empty()
        || value.len() > 255
        || value.chars().any(char::is_whitespace)
        || value.chars().any(char::is_control)
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), MatrixDurableError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
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

pub(crate) async fn verify_dispatch_schema(
    pool: &sqlx::SqlitePool,
) -> Result<(), MatrixDurableError> {
    let count: i64 = sqlx::query_scalar(
        "WITH required(name, type) AS (VALUES
            ('matrix_dispatch_ledger', 'table'),
            ('matrix_dispatch_ledger_unresolved', 'index'),
            ('matrix_dispatch_ledger_terminal_event', 'index'),
            ('matrix_dispatch_observations', 'table'),
            ('matrix_dispatch_observations_by_txn', 'index'),
            ('matrix_dispatch_observations_no_update', 'trigger'),
            ('matrix_dispatch_observation_archives', 'table'),
            ('matrix_dispatch_observation_archives_by_txn', 'index'),
            ('matrix_dispatch_observation_archives_no_update', 'trigger'),
            ('matrix_dispatch_observation_archives_no_delete', 'trigger')
         )
         SELECT COUNT(*) FROM required
         JOIN sqlite_schema USING (name)
         WHERE sqlite_schema.type = required.type",
    )
    .fetch_one(pool)
    .await
    .map_err(|_| MatrixDurableError::Unavailable)?;
    if count != 10 {
        return Err(MatrixDurableError::Corrupt);
    }

    let invalid_authority_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM matrix_dispatch_ledger
         WHERE (grant_payload_sha256 IS NOT NULL AND grant_payload_sha256 != payload_sha256)
            OR (
                authority_epoch IS NULL
                AND (
                    grant_id IS NOT NULL
                    OR grant_payload_sha256 IS NOT NULL
                    OR deadline_ms IS NOT NULL
                    OR homeserver_id IS NOT NULL
                    OR device_id IS NOT NULL
                    OR session_generation IS NOT NULL
                )
            )
            OR (
                authority_epoch IS NOT NULL
                AND (
                    grant_id IS NULL
                    OR grant_payload_sha256 IS NULL
                    OR deadline_ms IS NULL
                    OR homeserver_id IS NULL
                    OR device_id IS NULL
                    OR session_generation IS NULL
                )
            )",
    )
    .fetch_one(pool)
    .await
    .map_err(|_| MatrixDurableError::Unavailable)?;
    if invalid_authority_rows != 0 {
        return Err(MatrixDurableError::Corrupt);
    }

    let zero_digest = "0".repeat(64);
    let broken_archive_links: i64 = sqlx::query_scalar(
        "WITH ordered AS (
            SELECT stable_txn_id, archive_seq, prior_archive_digest, segment_digest,
                   LAG(segment_digest) OVER (
                       PARTITION BY stable_txn_id ORDER BY archive_seq
                   ) AS previous_segment_digest
            FROM matrix_dispatch_observation_archives
         )
         SELECT COUNT(*) FROM ordered
         WHERE prior_archive_digest
               != COALESCE(previous_segment_digest, ?)",
    )
    .bind(zero_digest)
    .fetch_one(pool)
    .await
    .map_err(|_| MatrixDurableError::Unavailable)?;
    if broken_archive_links != 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(())
}
