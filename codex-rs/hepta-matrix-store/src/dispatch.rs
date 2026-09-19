use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::ChangeKind;
use crate::MatrixDurableError;
use crate::OutboxRecord;
use crate::OutboxState;
use crate::store::MatrixDurableStore;

pub const MAX_UNRESOLVED_MATRIX_DISPATCHES: u64 = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixDispatchState {
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
pub struct MatrixDispatchAuthority {
    pub authority_epoch: u64,
    pub grant_id: String,
    pub grant_payload_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchAuthorityClaim {
    pub operation_id: String,
    pub subject_id: String,
    pub destination_id: String,
    pub homeserver_id: String,
    pub matrix_user_id: String,
    pub device_id: String,
    pub session_generation: u64,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub grant_id: String,
    pub request_digest: String,
    pub scope_digest: String,
    pub payload_digest: String,
    pub attempt: u64,
    pub expires_at_ms: u64,
    pub claimed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchRecord {
    pub operation_id: String,
    pub stable_txn_id: MatrixTransactionId,
    pub logical_outbox_id: String,
    pub room_id: MatrixRoomId,
    pub binding_revision: u64,
    pub generation: u64,
    pub payload_digest: String,
    pub authority_epoch: Option<u64>,
    pub grant_id: Option<String>,
    pub grant_payload_digest: Option<String>,
    pub state: MatrixDispatchState,
    pub accepted_event_id: Option<MatrixEventId>,
    pub terminal_event_id: Option<MatrixEventId>,
    pub transport_observation_digest: Option<String>,
    pub send_observation_digest: Option<String>,
    pub redaction_observation_digest: Option<String>,
    pub attempts: u64,
    pub prepared_at_ms: u64,
    pub updated_at_ms: u64,
    pub terminal_observed_at_ms: Option<u64>,
}

impl MatrixDurableStore {
    pub async fn record_dispatch_authority_claim(
        &self,
        txn_id: &MatrixTransactionId,
        claim: &MatrixDispatchAuthorityClaim,
    ) -> Result<(), MatrixDurableError> {
        validate_authority_claim(claim)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let dispatch = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if dispatch.state.is_terminal()
            || dispatch.operation_id != claim.operation_id
            || dispatch.payload_digest != claim.payload_digest
            || dispatch.attempts != claim.attempt
            || claim.claimed_at_ms < dispatch.updated_at_ms
        {
            return Err(MatrixDurableError::Conflict);
        }
        let existing = authority_claim_by_attempt_tx(&mut transaction, txn_id, claim.attempt).await?;
        if let Some(existing) = existing {
            if &existing == claim {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(());
            }
            return Err(MatrixDurableError::Conflict);
        }
        let reused_grant: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_authority_claims WHERE grant_id = ?",
        )
        .bind(&claim.grant_id)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if reused_grant != 0 {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "INSERT INTO matrix_dispatch_authority_claims (
                stable_txn_id, attempt, operation_id, subject_id, destination_id,
                homeserver_id, matrix_user_id, device_id, session_generation,
                authority_epoch, revocation_revision, grant_id, request_sha256,
                scope_sha256, payload_sha256, expires_at_ms, claimed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(txn_id.as_str())
        .bind(to_i64(claim.attempt)?)
        .bind(&claim.operation_id)
        .bind(&claim.subject_id)
        .bind(&claim.destination_id)
        .bind(&claim.homeserver_id)
        .bind(&claim.matrix_user_id)
        .bind(&claim.device_id)
        .bind(to_i64(claim.session_generation)?)
        .bind(to_i64(claim.authority_epoch)?)
        .bind(to_i64(claim.revocation_revision)?)
        .bind(&claim.grant_id)
        .bind(&claim.request_digest)
        .bind(&claim.scope_digest)
        .bind(&claim.payload_digest)
        .bind(to_i64(claim.expires_at_ms)?)
        .bind(to_i64(claim.claimed_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(())
    }

    pub async fn dispatch_authority_claim(
        &self,
        txn_id: &MatrixTransactionId,
        attempt: u64,
    ) -> Result<Option<MatrixDispatchAuthorityClaim>, MatrixDurableError> {
        if attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let claim = authority_claim_by_attempt_tx(&mut transaction, txn_id, attempt).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(claim)
    }

    pub async fn prepare_outbox_dispatch(
        &self,
        record: &OutboxRecord,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        self.prepare_outbox_dispatch_with_authority(record, None, now_ms)
            .await
    }

    pub async fn prepare_outbox_dispatch_with_authority(
        &self,
        record: &OutboxRecord,
        authority: Option<&MatrixDispatchAuthority>,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if record.state != OutboxState::InFlight || record.attempts == 0 {
            return Err(MatrixDurableError::Conflict);
        }
        if now_ms < record.updated_at_ms {
            return Err(MatrixDurableError::Invalid);
        }
        let payload_digest = Sha256Digest::for_bytes(&record.payload).as_str().to_string();
        if let Some(authority) = authority {
            validate_authority(authority, &payload_digest)?;
        }

        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = sqlx::query(
            "SELECT logical_outbox_id, payload_sha256
             FROM outbox_messages
             WHERE outbox_id = ? AND stable_txn_id = ? AND room_id = ?
               AND binding_revision = ? AND generation = ?",
        )
        .bind(to_i64(record.outbox_id)?)
        .bind(record.stable_txn_id.as_str())
        .bind(record.room_id.as_str())
        .bind(to_i64(record.binding_revision)?)
        .bind(to_i64(record.generation)?)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .ok_or(MatrixDurableError::Conflict)?;
        let logical_outbox_id: String = identity
            .try_get("logical_outbox_id")
            .map_err(unavailable)?;
        let stored_payload_digest: String = identity
            .try_get("payload_sha256")
            .map_err(unavailable)?;
        if stored_payload_digest != payload_digest {
            return Err(MatrixDurableError::Corrupt);
        }
        validate_identity(&logical_outbox_id)?;
        let operation_id = operation_id(&record.stable_txn_id);
        let existing = dispatch_by_txn_tx(&mut transaction, &record.stable_txn_id).await?;
        let authority_epoch = authority.map(|value| value.authority_epoch);
        let grant_id = authority.map(|value| value.grant_id.as_str());
        let grant_payload_digest = authority.map(|value| value.grant_payload_digest.as_str());

        let prepared = if let Some(existing) = existing {
            if existing.operation_id != operation_id
                || existing.logical_outbox_id != logical_outbox_id
                || existing.room_id != record.room_id
                || existing.binding_revision != record.binding_revision
                || existing.generation != record.generation
                || existing.payload_digest != payload_digest
                || existing.authority_epoch != authority_epoch
                || existing.grant_id.as_deref() != grant_id
                || existing.grant_payload_digest.as_deref() != grant_payload_digest
                || record.attempts < existing.attempts
            {
                return Err(MatrixDurableError::Conflict);
            }
            if existing.state.is_terminal() {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(existing);
            }
            let next_state = if existing.state == MatrixDispatchState::Accepted {
                MatrixDispatchState::Accepted
            } else {
                MatrixDispatchState::Dispatched
            };
            sqlx::query(
                "UPDATE matrix_dispatch_ledger
                 SET state = ?, attempts = ?, updated_at_ms = ?
                 WHERE stable_txn_id = ?",
            )
            .bind(next_state.as_str())
            .bind(to_i64(record.attempts)?)
            .bind(to_i64(now_ms)?)
            .bind(record.stable_txn_id.as_str())
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            MatrixDispatchRecord {
                state: next_state,
                attempts: record.attempts,
                updated_at_ms: now_ms,
                ..existing
            }
        } else {
            let unresolved: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM matrix_dispatch_ledger
                 WHERE state IN ('dispatched', 'accepted', 'indeterminate')",
            )
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if to_u64(unresolved)? >= MAX_UNRESOLVED_MATRIX_DISPATCHES {
                return Err(MatrixDurableError::Conflict);
            }
            sqlx::query(
                "INSERT INTO matrix_dispatch_ledger (
                    stable_txn_id, operation_id, logical_outbox_id, room_id,
                    binding_revision, generation, payload_sha256,
                    authority_epoch, grant_id, grant_payload_sha256,
                    state, accepted_event_id, terminal_event_id,
                    transport_observation_sha256, send_observation_sha256,
                    redaction_observation_sha256, attempts, prepared_at_ms,
                    updated_at_ms, terminal_observed_at_ms
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'dispatched',
                           NULL, NULL, NULL, NULL, NULL, ?, ?, ?, NULL)",
            )
            .bind(record.stable_txn_id.as_str())
            .bind(&operation_id)
            .bind(&logical_outbox_id)
            .bind(record.room_id.as_str())
            .bind(to_i64(record.binding_revision)?)
            .bind(to_i64(record.generation)?)
            .bind(&payload_digest)
            .bind(authority_epoch.map(to_i64).transpose()?)
            .bind(grant_id)
            .bind(grant_payload_digest)
            .bind(to_i64(record.attempts)?)
            .bind(to_i64(now_ms)?)
            .bind(to_i64(now_ms)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            MatrixDispatchRecord {
                operation_id,
                stable_txn_id: record.stable_txn_id.clone(),
                logical_outbox_id,
                room_id: record.room_id.clone(),
                binding_revision: record.binding_revision,
                generation: record.generation,
                payload_digest,
                authority_epoch,
                grant_id: grant_id.map(str::to_owned),
                grant_payload_digest: grant_payload_digest.map(str::to_owned),
                state: MatrixDispatchState::Dispatched,
                accepted_event_id: None,
                terminal_event_id: None,
                transport_observation_digest: None,
                send_observation_digest: None,
                redaction_observation_digest: None,
                attempts: record.attempts,
                prepared_at_ms: now_ms,
                updated_at_ms: now_ms,
                terminal_observed_at_ms: None,
            }
        };

        let digest = transport_observation_digest(
            "dispatch_started",
            &record.stable_txn_id,
            record.attempts,
            None,
            now_ms,
        )?;
        insert_observation_tx(
            &mut transaction,
            &record.stable_txn_id,
            "dispatch_started",
            record.attempts,
            None,
            &digest,
            now_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(prepared)
    }

    pub async fn record_outbox_transport_accepted(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        event_id: &MatrixEventId,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let digest = transport_observation_digest(
            "transport_accepted",
            txn_id,
            expected_attempt,
            Some(event_id),
            now_ms,
        )?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let existing = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(prior) = &existing.accepted_event_id
            && prior != event_id
        {
            return Err(MatrixDurableError::Conflict);
        }
        if existing.state == MatrixDispatchState::Failed {
            return Err(MatrixDurableError::Conflict);
        }
        insert_observation_tx(
            &mut transaction,
            txn_id,
            "transport_accepted",
            expected_attempt,
            Some(event_id),
            &digest,
            now_ms,
        )
        .await?;
        if existing.state.is_terminal() {
            if existing.terminal_event_id.as_ref() != Some(event_id) {
                return Err(MatrixDurableError::Conflict);
            }
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'accepted', accepted_event_id = ?,
                 transport_observation_sha256 = ?, updated_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(event_id.as_str())
        .bind(&digest)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let record = MatrixDispatchRecord {
            state: MatrixDispatchState::Accepted,
            accepted_event_id: Some(event_id.clone()),
            transport_observation_digest: Some(digest),
            updated_at_ms: now_ms,
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn record_outbox_transport_indeterminate(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let digest = transport_observation_digest(
            "transport_indeterminate",
            txn_id,
            expected_attempt,
            None,
            now_ms,
        )?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let existing = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        insert_observation_tx(
            &mut transaction,
            txn_id,
            "transport_indeterminate",
            expected_attempt,
            None,
            &digest,
            now_ms,
        )
        .await?;
        if existing.state.is_terminal() {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        let state = if existing.accepted_event_id.is_some() {
            MatrixDispatchState::Accepted
        } else {
            MatrixDispatchState::Indeterminate
        };
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = ?, transport_observation_sha256 = ?, updated_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(state.as_str())
        .bind(&digest)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let record = MatrixDispatchRecord {
            state,
            transport_observation_digest: Some(digest),
            updated_at_ms: now_ms,
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn record_outbox_transport_rejected(
        &self,
        txn_id: &MatrixTransactionId,
        expected_attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        if expected_attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let digest = transport_observation_digest(
            "transport_rejected",
            txn_id,
            expected_attempt,
            None,
            now_ms,
        )?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let existing = dispatch_by_txn_tx(&mut transaction, txn_id)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if existing.attempts != expected_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        if matches!(
            existing.state,
            MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted
        ) {
            return Err(MatrixDurableError::Conflict);
        }
        insert_observation_tx(
            &mut transaction,
            txn_id,
            "transport_rejected",
            expected_attempt,
            None,
            &digest,
            now_ms,
        )
        .await?;
        if existing.state == MatrixDispatchState::Failed {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing);
        }
        if existing.accepted_event_id.is_some() {
            // A prior request already crossed the transport boundary. A later
            // permanent rejection of a retry cannot prove the original event
            // was absent, so preserve Accepted until homeserver reconciliation.
            sqlx::query(
                "UPDATE matrix_dispatch_ledger
                 SET state = 'accepted', transport_observation_sha256 = ?,
                     updated_at_ms = ?
                 WHERE stable_txn_id = ?",
            )
            .bind(&digest)
            .bind(to_i64(now_ms)?)
            .bind(txn_id.as_str())
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            let record = MatrixDispatchRecord {
                state: MatrixDispatchState::Accepted,
                transport_observation_digest: Some(digest),
                updated_at_ms: now_ms,
                ..existing
            };
            transaction.commit().await.map_err(unavailable)?;
            return Ok(record);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'failed', transport_observation_sha256 = ?,
                 updated_at_ms = ?, terminal_observed_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(&digest)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let record = MatrixDispatchRecord {
            state: MatrixDispatchState::Failed,
            transport_observation_digest: Some(digest),
            updated_at_ms: now_ms,
            terminal_observed_at_ms: Some(now_ms),
            ..existing
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn dispatch_for_txn(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let record = dispatch_by_txn_tx(&mut transaction, txn_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn unresolved_dispatch_count(&self) -> Result<u64, MatrixDurableError> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE state IN ('dispatched', 'accepted', 'indeterminate')",
        )
        .fetch_one(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        to_u64(count)
    }

    pub(crate) async fn observe_outbound_event_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        txn_id: &MatrixTransactionId,
        room_id: &MatrixRoomId,
        event_id: &MatrixEventId,
        observation_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        let existing = match dispatch_by_txn_tx(transaction, txn_id).await? {
            Some(existing) => existing,
            None => {
                let row = sqlx::query(
                    "SELECT logical_outbox_id, room_id, binding_revision, generation,
                            payload_sha256, attempts, created_at_ms
                     FROM outbox_messages WHERE stable_txn_id = ?",
                )
                .bind(txn_id.as_str())
                .fetch_optional(&mut **transaction)
                .await
                .map_err(unavailable)?
                .ok_or(MatrixDurableError::Conflict)?;
                let stored_room = MatrixRoomId::parse(
                    row.try_get::<String, _>("room_id").map_err(unavailable)?,
                )
                .map_err(|_| MatrixDurableError::Corrupt)?;
                if stored_room != *room_id {
                    return Err(MatrixDurableError::Conflict);
                }
                let logical_outbox_id: String =
                    row.try_get("logical_outbox_id").map_err(unavailable)?;
                let payload_digest: String =
                    row.try_get("payload_sha256").map_err(unavailable)?;
                let attempts = to_u64(row.try_get("attempts").map_err(unavailable)?)?.max(1);
                let prepared_at_ms =
                    to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?;
                let operation_id = operation_id(txn_id);
                sqlx::query(
                    "INSERT INTO matrix_dispatch_ledger (
                        stable_txn_id, operation_id, logical_outbox_id, room_id,
                        binding_revision, generation, payload_sha256,
                        authority_epoch, grant_id, grant_payload_sha256,
                        state, accepted_event_id, terminal_event_id,
                        transport_observation_sha256, send_observation_sha256,
                        redaction_observation_sha256, attempts, prepared_at_ms,
                        updated_at_ms, terminal_observed_at_ms
                     ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL,
                               'succeeded', NULL, ?, NULL, ?, NULL, ?, ?, ?, ?)",
                )
                .bind(txn_id.as_str())
                .bind(&operation_id)
                .bind(&logical_outbox_id)
                .bind(room_id.as_str())
                .bind(row.try_get::<i64, _>("binding_revision").map_err(unavailable)?)
                .bind(row.try_get::<i64, _>("generation").map_err(unavailable)?)
                .bind(&payload_digest)
                .bind(event_id.as_str())
                .bind(observation_digest.as_str())
                .bind(to_i64(attempts)?)
                .bind(to_i64(prepared_at_ms)?)
                .bind(to_i64(observed_at_ms)?)
                .bind(to_i64(observed_at_ms)?)
                .execute(&mut **transaction)
                .await
                .map_err(unavailable)?;
                let record = dispatch_by_txn_tx(transaction, txn_id)
                    .await?
                    .ok_or(MatrixDurableError::Corrupt)?;
                insert_observation_tx(
                    transaction,
                    txn_id,
                    "homeserver_event",
                    attempts,
                    Some(event_id),
                    observation_digest.as_str(),
                    observed_at_ms,
                )
                .await?;
                settle_outbox_sent_tx(
                    self,
                    transaction,
                    &record,
                    event_id,
                    observed_at_ms,
                )
                .await?;
                return Ok(record);
            }
        };
        if existing.room_id != *room_id {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(accepted) = &existing.accepted_event_id
            && accepted != event_id
        {
            return Err(MatrixDurableError::Conflict);
        }
        match existing.state {
            MatrixDispatchState::Failed => return Err(MatrixDurableError::Conflict),
            MatrixDispatchState::Redacted => {
                if existing.terminal_event_id.as_ref() == Some(event_id) {
                    return Ok(existing);
                }
                return Err(MatrixDurableError::Conflict);
            }
            MatrixDispatchState::Succeeded => {
                if existing.terminal_event_id.as_ref() == Some(event_id)
                    && existing.send_observation_digest.as_deref()
                        == Some(observation_digest.as_str())
                {
                    return Ok(existing);
                }
                return Err(MatrixDurableError::Conflict);
            }
            MatrixDispatchState::Dispatched
            | MatrixDispatchState::Accepted
            | MatrixDispatchState::Indeterminate => {}
        }
        insert_observation_tx(
            transaction,
            txn_id,
            "homeserver_event",
            existing.attempts,
            Some(event_id),
            observation_digest.as_str(),
            observed_at_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'succeeded', terminal_event_id = ?,
                 send_observation_sha256 = ?, updated_at_ms = ?,
                 terminal_observed_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(event_id.as_str())
        .bind(observation_digest.as_str())
        .bind(to_i64(observed_at_ms)?)
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let record = MatrixDispatchRecord {
            state: MatrixDispatchState::Succeeded,
            terminal_event_id: Some(event_id.clone()),
            send_observation_digest: Some(observation_digest.to_string()),
            updated_at_ms: observed_at_ms,
            terminal_observed_at_ms: Some(observed_at_ms),
            ..existing
        };
        settle_outbox_sent_tx(self, transaction, &record, event_id, observed_at_ms).await?;
        Ok(record)
    }

    pub(crate) async fn apply_dispatch_redaction_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        redaction_event_id: &MatrixEventId,
        target_event_id: &MatrixEventId,
        redaction_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        let rows = sqlx::query(
            "SELECT operation_id, stable_txn_id, logical_outbox_id, room_id,
                    binding_revision, generation, payload_sha256,
                    authority_epoch, grant_id, grant_payload_sha256,
                    state, accepted_event_id, terminal_event_id,
                    transport_observation_sha256, send_observation_sha256,
                    redaction_observation_sha256, attempts, prepared_at_ms,
                    updated_at_ms, terminal_observed_at_ms
             FROM matrix_dispatch_ledger
             WHERE terminal_event_id = ? OR accepted_event_id = ?
             LIMIT 2",
        )
        .bind(target_event_id.as_str())
        .bind(target_event_id.as_str())
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let existing = match rows.as_slice() {
            [] => return Ok(None),
            [row] => dispatch_from_row(row)?,
            _ => return Err(MatrixDurableError::Corrupt),
        };
        if existing.state == MatrixDispatchState::Failed {
            return Err(MatrixDurableError::Conflict);
        }
        if existing.state == MatrixDispatchState::Redacted {
            if existing.terminal_event_id.as_ref() == Some(target_event_id)
                && existing.redaction_observation_digest.as_deref()
                    == Some(redaction_digest.as_str())
            {
                return Ok(Some(existing));
            }
            return Err(MatrixDurableError::Conflict);
        }
        insert_observation_tx(
            transaction,
            &existing.stable_txn_id,
            "redaction",
            existing.attempts,
            Some(redaction_event_id),
            redaction_digest.as_str(),
            observed_at_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'redacted', terminal_event_id = ?,
                 redaction_observation_sha256 = ?, updated_at_ms = ?,
                 terminal_observed_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(target_event_id.as_str())
        .bind(redaction_digest.as_str())
        .bind(to_i64(observed_at_ms)?)
        .bind(to_i64(observed_at_ms)?)
        .bind(existing.stable_txn_id.as_str())
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let record = MatrixDispatchRecord {
            state: MatrixDispatchState::Redacted,
            terminal_event_id: Some(target_event_id.clone()),
            redaction_observation_digest: Some(redaction_digest.to_string()),
            updated_at_ms: observed_at_ms,
            terminal_observed_at_ms: Some(observed_at_ms),
            ..existing
        };
        settle_outbox_sent_tx(
            self,
            transaction,
            &record,
            target_event_id,
            observed_at_ms,
        )
        .await?;
        Ok(Some(record))
    }
}

async fn settle_outbox_sent_tx(
    store: &MatrixDurableStore,
    transaction: &mut Transaction<'_, Sqlite>,
    dispatch: &MatrixDispatchRecord,
    event_id: &MatrixEventId,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    let row = sqlx::query(
        "SELECT state, sent_event_id FROM outbox_messages WHERE stable_txn_id = ?",
    )
    .bind(dispatch.stable_txn_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or(MatrixDurableError::Corrupt)?;
    let state: String = row.try_get("state").map_err(unavailable)?;
    let prior_event: Option<String> = row.try_get("sent_event_id").map_err(unavailable)?;
    if let Some(prior_event) = prior_event {
        let prior_event =
            MatrixEventId::parse(prior_event).map_err(|_| MatrixDurableError::Corrupt)?;
        if prior_event != *event_id {
            return Err(MatrixDurableError::Conflict);
        }
    }
    if state == "sent" {
        return Ok(());
    }
    sqlx::query(
        "UPDATE outbox_messages
         SET state = 'sent', lease_until_ms = NULL, updated_at_ms = ?, sent_event_id = ?
         WHERE stable_txn_id = ?",
    )
    .bind(to_i64(observed_at_ms)?)
    .bind(event_id.as_str())
    .bind(dispatch.stable_txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    store
        .append_change(
            transaction,
            ChangeKind::OutboxSent,
            Some(&dispatch.room_id),
            Some(event_id),
            Some(&dispatch.stable_txn_id),
            observed_at_ms,
        )
        .await?;
    Ok(())
}

async fn authority_claim_by_attempt_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    attempt: u64,
) -> Result<Option<MatrixDispatchAuthorityClaim>, MatrixDurableError> {
    sqlx::query(
        "SELECT operation_id, subject_id, destination_id, homeserver_id,
                matrix_user_id, device_id, session_generation, authority_epoch,
                revocation_revision, grant_id, request_sha256, scope_sha256,
                payload_sha256, attempt, expires_at_ms, claimed_at_ms
         FROM matrix_dispatch_authority_claims
         WHERE stable_txn_id = ? AND attempt = ?",
    )
    .bind(txn_id.as_str())
    .bind(to_i64(attempt)?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| authority_claim_from_row(&row))
    .transpose()
}

fn authority_claim_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<MatrixDispatchAuthorityClaim, MatrixDurableError> {
    let claim = MatrixDispatchAuthorityClaim {
        operation_id: row.try_get("operation_id").map_err(unavailable)?,
        subject_id: row.try_get("subject_id").map_err(unavailable)?,
        destination_id: row.try_get("destination_id").map_err(unavailable)?,
        homeserver_id: row.try_get("homeserver_id").map_err(unavailable)?,
        matrix_user_id: row.try_get("matrix_user_id").map_err(unavailable)?,
        device_id: row.try_get("device_id").map_err(unavailable)?,
        session_generation: to_u64(row.try_get("session_generation").map_err(unavailable)?)?,
        authority_epoch: to_u64(row.try_get("authority_epoch").map_err(unavailable)?)?,
        revocation_revision: to_u64(
            row.try_get("revocation_revision").map_err(unavailable)?,
        )?,
        grant_id: row.try_get("grant_id").map_err(unavailable)?,
        request_digest: row.try_get("request_sha256").map_err(unavailable)?,
        scope_digest: row.try_get("scope_sha256").map_err(unavailable)?,
        payload_digest: row.try_get("payload_sha256").map_err(unavailable)?,
        attempt: to_u64(row.try_get("attempt").map_err(unavailable)?)?,
        expires_at_ms: to_u64(row.try_get("expires_at_ms").map_err(unavailable)?)?,
        claimed_at_ms: to_u64(row.try_get("claimed_at_ms").map_err(unavailable)?)?,
    };
    validate_authority_claim(&claim).map_err(|_| MatrixDurableError::Corrupt)?;
    Ok(claim)
}

async fn dispatch_by_txn_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
    sqlx::query(
        "SELECT operation_id, stable_txn_id, logical_outbox_id, room_id,
                binding_revision, generation, payload_sha256,
                authority_epoch, grant_id, grant_payload_sha256,
                state, accepted_event_id, terminal_event_id,
                transport_observation_sha256, send_observation_sha256,
                redaction_observation_sha256, attempts, prepared_at_ms,
                updated_at_ms, terminal_observed_at_ms
         FROM matrix_dispatch_ledger WHERE stable_txn_id = ?",
    )
    .bind(txn_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .map(|row| dispatch_from_row(&row))
    .transpose()
}

fn dispatch_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<MatrixDispatchRecord, MatrixDurableError> {
    let operation_id: String = row.try_get("operation_id").map_err(unavailable)?;
    let logical_outbox_id: String = row.try_get("logical_outbox_id").map_err(unavailable)?;
    validate_stored_identity(&operation_id)?;
    validate_stored_identity(&logical_outbox_id)?;
    let payload_digest: String = row.try_get("payload_sha256").map_err(unavailable)?;
    validate_stored_digest(&payload_digest)?;
    let grant_id: Option<String> = row.try_get("grant_id").map_err(unavailable)?;
    if let Some(grant_id) = grant_id.as_deref() {
        validate_stored_identity(grant_id)?;
    }
    let grant_payload_digest: Option<String> =
        row.try_get("grant_payload_sha256").map_err(unavailable)?;
    if let Some(digest) = grant_payload_digest.as_deref() {
        validate_stored_digest(digest)?;
        if digest != payload_digest {
            return Err(MatrixDurableError::Corrupt);
        }
    }
    let transport_observation_digest: Option<String> =
        row.try_get("transport_observation_sha256").map_err(unavailable)?;
    let send_observation_digest: Option<String> =
        row.try_get("send_observation_sha256").map_err(unavailable)?;
    let redaction_observation_digest: Option<String> =
        row.try_get("redaction_observation_sha256").map_err(unavailable)?;
    for digest in [
        transport_observation_digest.as_deref(),
        send_observation_digest.as_deref(),
        redaction_observation_digest.as_deref(),
    ]
    .into_iter()
    .flatten()
    {
        validate_stored_digest(digest)?;
    }
    let state = MatrixDispatchState::parse(
        row.try_get::<String, _>("state")
            .map_err(unavailable)?
            .as_str(),
    )
    .ok_or(MatrixDurableError::Corrupt)?;
    Ok(MatrixDispatchRecord {
        operation_id,
        stable_txn_id: MatrixTransactionId::parse(
            row.try_get::<String, _>("stable_txn_id")
                .map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        logical_outbox_id,
        room_id: MatrixRoomId::parse(
            row.try_get::<String, _>("room_id").map_err(unavailable)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?,
        binding_revision: to_u64(row.try_get("binding_revision").map_err(unavailable)?)?,
        generation: to_u64(row.try_get("generation").map_err(unavailable)?)?,
        payload_digest,
        authority_epoch: row
            .try_get::<Option<i64>, _>("authority_epoch")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
        grant_id,
        grant_payload_digest,
        state,
        accepted_event_id: row
            .try_get::<Option<String>, _>("accepted_event_id")
            .map_err(unavailable)?
            .map(MatrixEventId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)?,
        terminal_event_id: row
            .try_get::<Option<String>, _>("terminal_event_id")
            .map_err(unavailable)?
            .map(MatrixEventId::parse)
            .transpose()
            .map_err(|_| MatrixDurableError::Corrupt)?,
        transport_observation_digest,
        send_observation_digest,
        redaction_observation_digest,
        attempts: to_u64(row.try_get("attempts").map_err(unavailable)?)?,
        prepared_at_ms: to_u64(row.try_get("prepared_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
        terminal_observed_at_ms: row
            .try_get::<Option<i64>, _>("terminal_observed_at_ms")
            .map_err(unavailable)?
            .map(to_u64)
            .transpose()?,
    })
}

async fn insert_observation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    kind: &str,
    attempt: u64,
    event_id: Option<&MatrixEventId>,
    digest: &str,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    validate_digest(digest)?;
    sqlx::query(
        "INSERT INTO matrix_dispatch_observations (
            stable_txn_id, observation_kind, attempt, event_id,
            observation_sha256, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(stable_txn_id, observation_kind, observation_sha256) DO NOTHING",
    )
    .bind(txn_id.as_str())
    .bind(kind)
    .bind(to_i64(attempt)?)
    .bind(event_id.map(MatrixEventId::as_str))
    .bind(digest)
    .bind(to_i64(observed_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

#[derive(Serialize)]
struct TransportObservationIdentity<'a> {
    kind: &'a str,
    stable_txn_id: &'a str,
    attempt: u64,
    event_id: Option<&'a str>,
    observed_at_ms: u64,
}

fn transport_observation_digest(
    kind: &str,
    txn_id: &MatrixTransactionId,
    attempt: u64,
    event_id: Option<&MatrixEventId>,
    observed_at_ms: u64,
) -> Result<String, MatrixDurableError> {
    let identity = TransportObservationIdentity {
        kind,
        stable_txn_id: txn_id.as_str(),
        attempt,
        event_id: event_id.map(MatrixEventId::as_str),
        observed_at_ms,
    };
    let encoded = serde_json::to_vec(&identity).map_err(|_| MatrixDurableError::Invalid)?;
    let mut bytes = b"hepta.matrix.dispatch-observation.v1\0".to_vec();
    bytes.extend_from_slice(&encoded);
    Ok(Sha256Digest::for_bytes(&bytes).as_str().to_string())
}

fn operation_id(txn_id: &MatrixTransactionId) -> String {
    format!("matrix.send:{}", txn_id.as_str())
}

fn validate_authority_claim(
    claim: &MatrixDispatchAuthorityClaim,
) -> Result<(), MatrixDurableError> {
    validate_identity(&claim.operation_id)?;
    for value in [&claim.subject_id, &claim.destination_id, &claim.grant_id] {
        if value.is_empty()
            || value.len() > 128
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
        {
            return Err(MatrixDurableError::Invalid);
        }
    }
    for (value, maximum) in [
        (claim.homeserver_id.as_str(), 2048_usize),
        (claim.matrix_user_id.as_str(), 255_usize),
        (claim.device_id.as_str(), 255_usize),
    ] {
        if value.is_empty()
            || value.len() > maximum
            || value.chars().any(char::is_control)
        {
            return Err(MatrixDurableError::Invalid);
        }
    }
    for digest in [
        &claim.request_digest,
        &claim.scope_digest,
        &claim.payload_digest,
    ] {
        validate_digest(digest)?;
    }
    if claim.attempt == 0
        || claim.session_generation == 0
        || claim.authority_epoch == 0
        || claim.revocation_revision == 0
        || claim.expires_at_ms <= claim.claimed_at_ms
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_authority(
    authority: &MatrixDispatchAuthority,
    payload_digest: &str,
) -> Result<(), MatrixDurableError> {
    if authority.authority_epoch == 0 {
        return Err(MatrixDurableError::Invalid);
    }
    validate_identity(&authority.grant_id)?;
    validate_digest(&authority.grant_payload_digest)?;
    if authority.grant_payload_digest != payload_digest {
        return Err(MatrixDurableError::AccessDenied);
    }
    Ok(())
}

fn validate_identity(value: &str) -> Result<(), MatrixDurableError> {
    if !(1..=512).contains(&value.len())
        || !value.bytes().all(|byte| (b' '..=b'~').contains(&byte))
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_stored_identity(value: &str) -> Result<(), MatrixDurableError> {
    validate_identity(value).map_err(|_| MatrixDurableError::Corrupt)
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

fn validate_stored_digest(value: &str) -> Result<(), MatrixDurableError> {
    validate_digest(value).map_err(|_| MatrixDurableError::Corrupt)
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
