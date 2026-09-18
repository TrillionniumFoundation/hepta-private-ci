use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::MatrixDurableError;
use crate::MatrixDurableStore;

pub const MAX_UNRESOLVED_SENDS: u64 = 4_096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SendIntent {
    pub operation_id: String,
    pub transaction_id: String,
    pub homeserver_id: String,
    pub room_id: String,
    pub device_id: String,
    pub session_generation: u64,
    pub authority_identity: String,
    pub authority_epoch: u64,
    pub payload_digest: String,
    pub verified_grant_id: Option<String>,
    pub verified_grant_payload_digest: Option<String>,
    pub verified_grant_expires_at_ms: Option<u64>,
    pub reconciliation_deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ServerObservation {
    pub operation_id: String,
    pub transaction_id: String,
    pub homeserver_id: String,
    pub room_id: String,
    pub session_generation: u64,
    pub terminal_observed: bool,
    pub accepted: bool,
    pub server_event_id: Option<String>,
    pub observation_digest: String,
    pub observed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixServerEventObservation {
    pub event_id: MatrixEventId,
    pub transaction_id: Option<MatrixTransactionId>,
    pub room_id: MatrixRoomId,
    pub session_generation: u64,
    pub observation_digest: String,
    pub observed_at_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SendState {
    Prepared,
    Dispatched,
    Accepted,
    Indeterminate,
    Succeeded,
    Failed,
    Redacted,
}

impl SendState {
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
pub struct SendReceipt {
    pub operation_id: String,
    pub transaction_id: String,
    pub state: SendState,
    pub authority_identity: String,
    pub authority_epoch: u64,
    pub verified_grant_id: Option<String>,
    pub server_event_id: Option<String>,
    pub transport_observation_digest: Option<String>,
    pub send_observation_digest: Option<String>,
    pub redaction_observation_digest: Option<String>,
    pub terminal_observed: bool,
    pub idempotent: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixDispatchError {
    #[error("invalid Matrix send identity: {0}")]
    InvalidIdentity(&'static str),
    #[error("invalid Matrix send digest: {0}")]
    InvalidDigest(&'static str),
    #[error("invalid Matrix send generation")]
    InvalidGeneration,
    #[error("Matrix send deadline expired")]
    DeadlineExpired,
    #[error("Matrix unresolved send capacity exceeded")]
    CapacityExceeded,
    #[error("Matrix send payload does not match the supplied verified-grant payload")]
    PayloadMismatch,
    #[error("Matrix operation or transaction identity conflicts with durable state")]
    OperationConflict,
    #[error("Matrix send was not found")]
    SendNotFound,
    #[error("Matrix server observation does not match the durable send")]
    ObservationMismatch,
    #[error("Matrix terminal success is missing a server event")]
    TerminalEventMissing,
    #[error("Matrix send is already terminal")]
    AlreadyTerminal,
    #[error("Matrix dispatch ledger is unavailable")]
    Store,
}

#[derive(Debug)]
struct DispatchRecord {
    intent: SendIntent,
    receipt: SendReceipt,
}

impl MatrixDurableStore {
    pub async fn prepare_send(
        &self,
        now_ms: u64,
        intent: &SendIntent,
    ) -> Result<SendReceipt, MatrixDispatchError> {
        validate_intent_shape(intent)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(store_error)?;
        if let Some(mut current) = load_record_tx(&mut transaction, &intent.operation_id).await? {
            if current.intent == *intent {
                current.receipt.idempotent = true;
                transaction.commit().await.map_err(store_error)?;
                return Ok(current.receipt);
            }
            return Err(MatrixDispatchError::OperationConflict);
        }
        let transaction_reuse: i64 = sqlx::query_scalar(
            "SELECT EXISTS(
                SELECT 1 FROM matrix_dispatch_ledger
                WHERE stable_txn_id = ? AND operation_id != ?
            )",
        )
        .bind(&intent.transaction_id)
        .bind(&intent.operation_id)
        .fetch_one(&mut *transaction)
        .await
        .map_err(store_error)?;
        if transaction_reuse != 0 {
            return Err(MatrixDispatchError::OperationConflict);
        }
        let preobserved =
            matching_server_observation_tx(&mut transaction, intent, None).await?;
        if preobserved.is_none() {
            validate_intent_live(now_ms, intent)?;
            let unresolved: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM matrix_dispatch_ledger
                 WHERE state NOT IN ('succeeded', 'failed', 'redacted')",
            )
            .fetch_one(&mut *transaction)
            .await
            .map_err(store_error)?;
            if u64::try_from(unresolved).map_err(|_| MatrixDispatchError::Store)?
                >= MAX_UNRESOLVED_SENDS
            {
                return Err(MatrixDispatchError::CapacityExceeded);
            }
        }
        sqlx::query(
            "INSERT INTO matrix_dispatch_ledger (
                operation_id, stable_txn_id, homeserver_id, room_id, device_id,
                session_generation, authority_identity, authority_epoch,
                payload_digest, verified_grant_id, verified_grant_payload_digest,
                verified_grant_expires_at_ms, reconciliation_deadline_ms, state,
                created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)",
        )
        .bind(&intent.operation_id)
        .bind(&intent.transaction_id)
        .bind(&intent.homeserver_id)
        .bind(&intent.room_id)
        .bind(&intent.device_id)
        .bind(to_i64(intent.session_generation)?)
        .bind(&intent.authority_identity)
        .bind(to_i64(intent.authority_epoch)?)
        .bind(&intent.payload_digest)
        .bind(&intent.verified_grant_id)
        .bind(&intent.verified_grant_payload_digest)
        .bind(
            intent
                .verified_grant_expires_at_ms
                .map(to_i64)
                .transpose()?,
        )
        .bind(to_i64(intent.reconciliation_deadline_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(store_error)?;

        // A previous process or sync turn may already have observed this exact
        // stable Matrix transaction before the dispatch-ledger row existed.
        // Reconcile that durable observation before any caller can retry wire
        // dispatch, preserving one transaction identity across restart.
        if let Some(observation) = preobserved {
            settle_succeeded_tx(&mut transaction, &intent.operation_id, &observation).await?;
        }
        let receipt = load_record_tx(&mut transaction, &intent.operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?
            .receipt;
        transaction.commit().await.map_err(store_error)?;
        Ok(receipt)
    }

    pub async fn mark_send_dispatched(
        &self,
        operation_id: &str,
        observation_digest: &str,
        observed_at_ms: u64,
    ) -> Result<SendReceipt, MatrixDispatchError> {
        validate_identity(operation_id, "operation")?;
        validate_digest(observation_digest, "dispatch observation")?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(store_error)?;
        let current = load_record_tx(&mut transaction, operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?;
        if current.receipt.state.is_terminal() {
            transaction.commit().await.map_err(store_error)?;
            return Ok(current.receipt);
        }
        append_observation_tx(
            &mut transaction,
            operation_id,
            "dispatch_attempt",
            observation_digest,
            None,
            observed_at_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = CASE WHEN state = 'accepted' THEN 'accepted' ELSE 'dispatched' END,
                 transport_observation_digest = ?, updated_at_ms = MAX(updated_at_ms, ?)
             WHERE operation_id = ?",
        )
        .bind(observation_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(operation_id)
        .execute(&mut *transaction)
        .await
        .map_err(store_error)?;
        let receipt = load_record_tx(&mut transaction, operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?
            .receipt;
        transaction.commit().await.map_err(store_error)?;
        Ok(receipt)
    }

    pub async fn record_transport_accepted(
        &self,
        operation_id: &str,
        event_id: &MatrixEventId,
        observation_digest: &str,
        observed_at_ms: u64,
    ) -> Result<SendReceipt, MatrixDispatchError> {
        validate_identity(operation_id, "operation")?;
        validate_digest(observation_digest, "transport observation")?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(store_error)?;
        let current = load_record_tx(&mut transaction, operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?;
        match current.receipt.state {
            SendState::Succeeded | SendState::Redacted => {
                if current.receipt.server_event_id.as_deref() == Some(event_id.as_str()) {
                    let mut receipt = current.receipt;
                    receipt.idempotent = true;
                    transaction.commit().await.map_err(store_error)?;
                    return Ok(receipt);
                }
                return Err(MatrixDispatchError::AlreadyTerminal);
            }
            SendState::Failed => return Err(MatrixDispatchError::AlreadyTerminal),
            _ => {}
        }
        if let Some(existing) = accepted_event_owner_tx(&mut transaction, event_id.as_str()).await?
            && existing != operation_id
        {
            return Err(MatrixDispatchError::OperationConflict);
        }
        let prior_accepted: Option<String> = sqlx::query_scalar(
            "SELECT accepted_event_id FROM matrix_dispatch_ledger WHERE operation_id = ?",
        )
        .bind(operation_id)
        .fetch_one(&mut *transaction)
        .await
        .map_err(store_error)?;
        if prior_accepted.as_deref().is_some_and(|prior| prior != event_id.as_str()) {
            return Err(MatrixDispatchError::ObservationMismatch);
        }
        append_observation_tx(
            &mut transaction,
            operation_id,
            "transport_accepted",
            observation_digest,
            Some(event_id.as_str()),
            observed_at_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'accepted', accepted_event_id = ?,
                 transport_observation_digest = ?, updated_at_ms = MAX(updated_at_ms, ?)
             WHERE operation_id = ?",
        )
        .bind(event_id.as_str())
        .bind(observation_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(operation_id)
        .execute(&mut *transaction)
        .await
        .map_err(store_error)?;

        if let Some(observation) =
            matching_server_observation_tx(&mut transaction, &current.intent, Some(event_id)).await?
        {
            settle_succeeded_tx(&mut transaction, operation_id, &observation).await?;
        }
        let receipt = load_record_tx(&mut transaction, operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?
            .receipt;
        transaction.commit().await.map_err(store_error)?;
        Ok(receipt)
    }

    pub async fn record_transport_indeterminate(
        &self,
        operation_id: &str,
        observation_digest: &str,
        observed_at_ms: u64,
    ) -> Result<SendReceipt, MatrixDispatchError> {
        validate_identity(operation_id, "operation")?;
        validate_digest(observation_digest, "transport observation")?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(store_error)?;
        let current = load_record_tx(&mut transaction, operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?;
        if current.receipt.state.is_terminal() {
            transaction.commit().await.map_err(store_error)?;
            return Ok(current.receipt);
        }
        append_observation_tx(
            &mut transaction,
            operation_id,
            "transport_indeterminate",
            observation_digest,
            None,
            observed_at_ms,
        )
        .await?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = CASE WHEN state = 'accepted' THEN 'accepted' ELSE 'indeterminate' END,
                 transport_observation_digest = ?,
                 updated_at_ms = MAX(updated_at_ms, ?)
             WHERE operation_id = ?",
        )
        .bind(observation_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(operation_id)
        .execute(&mut *transaction)
        .await
        .map_err(store_error)?;
        let receipt = load_record_tx(&mut transaction, operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?
            .receipt;
        transaction.commit().await.map_err(store_error)?;
        Ok(receipt)
    }

    pub async fn observe_send(
        &self,
        observation: &ServerObservation,
    ) -> Result<SendReceipt, MatrixDispatchError> {
        validate_observation(observation)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(store_error)?;
        let current = load_record_tx(&mut transaction, &observation.operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?;
        if observation.transaction_id != current.intent.transaction_id
            || observation.homeserver_id != current.intent.homeserver_id
            || observation.room_id != current.intent.room_id
            || observation.session_generation != current.intent.session_generation
        {
            return Err(MatrixDispatchError::ObservationMismatch);
        }
        if current.receipt.state.is_terminal() {
            let identical = match current.receipt.state {
                SendState::Succeeded => {
                    observation.terminal_observed
                        && observation.accepted
                        && observation.server_event_id == current.receipt.server_event_id
                        && current.receipt.send_observation_digest.as_deref()
                            == Some(observation.observation_digest.as_str())
                }
                SendState::Failed => {
                    observation.terminal_observed
                        && !observation.accepted
                        && observation.server_event_id.is_none()
                        && current.receipt.send_observation_digest.as_deref()
                            == Some(observation.observation_digest.as_str())
                }
                SendState::Redacted => false,
                _ => false,
            };
            if identical {
                let mut receipt = current.receipt;
                receipt.idempotent = true;
                transaction.commit().await.map_err(store_error)?;
                return Ok(receipt);
            }
            return Err(MatrixDispatchError::AlreadyTerminal);
        }
        if !observation.terminal_observed {
            append_observation_tx(
                &mut transaction,
                &observation.operation_id,
                "transport_indeterminate",
                &observation.observation_digest,
                None,
                observation.observed_at_ms,
            )
            .await?;
            sqlx::query(
                "UPDATE matrix_dispatch_ledger
                 SET state = CASE WHEN state = 'accepted' THEN 'accepted' ELSE 'indeterminate' END,
                     transport_observation_digest = ?,
                     updated_at_ms = MAX(updated_at_ms, ?)
                 WHERE operation_id = ?",
            )
            .bind(&observation.observation_digest)
            .bind(to_i64(observation.observed_at_ms)?)
            .bind(&observation.operation_id)
            .execute(&mut *transaction)
            .await
            .map_err(store_error)?;
        } else if observation.accepted {
            let event_id = observation
                .server_event_id
                .as_deref()
                .ok_or(MatrixDispatchError::TerminalEventMissing)?;
            validate_identity(event_id, "server event")?;
            settle_succeeded_fields_tx(
                &mut transaction,
                &observation.operation_id,
                event_id,
                &observation.observation_digest,
                observation.observed_at_ms,
            )
            .await?;
        } else {
            if observation.server_event_id.is_some() {
                return Err(MatrixDispatchError::ObservationMismatch);
            }
            append_observation_tx(
                &mut transaction,
                &observation.operation_id,
                "server_failed",
                &observation.observation_digest,
                None,
                observation.observed_at_ms,
            )
            .await?;
            sqlx::query(
                "UPDATE matrix_dispatch_ledger
                 SET state = 'failed', send_observation_digest = ?,
                     updated_at_ms = MAX(updated_at_ms, ?), terminal_at_ms = ?
                 WHERE operation_id = ?",
            )
            .bind(&observation.observation_digest)
            .bind(to_i64(observation.observed_at_ms)?)
            .bind(to_i64(observation.observed_at_ms)?)
            .bind(&observation.operation_id)
            .execute(&mut *transaction)
            .await
            .map_err(store_error)?;
        }
        let receipt = load_record_tx(&mut transaction, &observation.operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?
            .receipt;
        transaction.commit().await.map_err(store_error)?;
        Ok(receipt)
    }

    pub async fn observe_server_event(
        &self,
        observation: &MatrixServerEventObservation,
    ) -> Result<(), MatrixDispatchError> {
        validate_server_event_observation(observation)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(store_error)?;
        record_server_event_observation_tx(&mut transaction, observation)
            .await
            .map_err(durable_dispatch_error)?;
        transaction.commit().await.map_err(store_error)?;
        Ok(())
    }

    pub async fn apply_send_redaction(
        &self,
        server_event_id: &str,
        redaction_digest: &str,
        observed_at_ms: u64,
    ) -> Result<SendReceipt, MatrixDispatchError> {
        validate_identity(server_event_id, "server event")?;
        validate_digest(redaction_digest, "redaction")?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(store_error)?;
        let row = sqlx::query(
            "SELECT operation_id, state, redaction_observation_digest
             FROM matrix_dispatch_ledger WHERE server_event_id = ?",
        )
        .bind(server_event_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(store_error)?
        .ok_or(MatrixDispatchError::SendNotFound)?;
        let operation_id: String = row.try_get("operation_id").map_err(store_error)?;
        let state: String = row.try_get("state").map_err(store_error)?;
        let existing_redaction: Option<String> = row
            .try_get("redaction_observation_digest")
            .map_err(store_error)?;
        let replay = state == "redacted"
            && existing_redaction.as_deref() == Some(redaction_digest);
        apply_send_redaction_tx(
            &mut transaction,
            server_event_id,
            redaction_digest,
            observed_at_ms,
        )
        .await
        .map_err(durable_dispatch_error)?;
        let mut receipt = load_record_tx(&mut transaction, &operation_id)
            .await?
            .ok_or(MatrixDispatchError::SendNotFound)?
            .receipt;
        receipt.idempotent = replay;
        transaction.commit().await.map_err(store_error)?;
        Ok(receipt)
    }

    pub async fn send_receipt(
        &self,
        operation_id: &str,
    ) -> Result<Option<SendReceipt>, MatrixDispatchError> {
        validate_identity(operation_id, "operation")?;
        let mut transaction = self.sqlite_pool().begin().await.map_err(store_error)?;
        let receipt = load_record_tx(&mut transaction, operation_id)
            .await?
            .map(|record| record.receipt);
        transaction.commit().await.map_err(store_error)?;
        Ok(receipt)
    }

    pub async fn unresolved_send_count(&self) -> Result<u64, MatrixDispatchError> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE state NOT IN ('succeeded', 'failed', 'redacted')",
        )
        .fetch_one(self.sqlite_pool())
        .await
        .map_err(store_error)?;
        u64::try_from(count).map_err(|_| MatrixDispatchError::Store)
    }
}

pub(crate) async fn record_server_event_observation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    observation: &MatrixServerEventObservation,
) -> Result<(), MatrixDurableError> {
    if !valid_digest(&observation.observation_digest)
        || observation.session_generation == 0
        || observation.observed_at_ms > i64::MAX as u64
    {
        return Err(MatrixDurableError::Invalid);
    }
    if let Some(transaction_id) = &observation.transaction_id {
        if let Some(prior_event_id) = sqlx::query_scalar::<_, String>(
            "SELECT event_id FROM matrix_server_event_observations WHERE stable_txn_id = ?",
        )
        .bind(transaction_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?
            && prior_event_id != observation.event_id.as_str()
        {
            return Err(MatrixDurableError::Conflict);
        }
    }
    let inserted = sqlx::query(
        "INSERT INTO matrix_server_event_observations (
            event_id, stable_txn_id, room_id, session_generation,
            observation_digest, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(event_id) DO NOTHING",
    )
    .bind(observation.event_id.as_str())
    .bind(observation.transaction_id.as_ref().map(MatrixTransactionId::as_str))
    .bind(observation.room_id.as_str())
    .bind(i64::try_from(observation.session_generation).map_err(|_| MatrixDurableError::Invalid)?)
    .bind(&observation.observation_digest)
    .bind(i64::try_from(observation.observed_at_ms).map_err(|_| MatrixDurableError::Invalid)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if inserted.rows_affected() == 0 {
        let row = sqlx::query(
            "SELECT stable_txn_id, room_id, session_generation, observation_digest
             FROM matrix_server_event_observations WHERE event_id = ?",
        )
        .bind(observation.event_id.as_str())
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let stored_txn: Option<String> = row.try_get("stable_txn_id").map_err(unavailable)?;
        let room_id: String = row.try_get("room_id").map_err(unavailable)?;
        let generation: i64 = row.try_get("session_generation").map_err(unavailable)?;
        let digest: String = row.try_get("observation_digest").map_err(unavailable)?;
        if stored_txn.as_deref()
            != observation.transaction_id.as_ref().map(MatrixTransactionId::as_str)
            || room_id != observation.room_id.as_str()
            || u64::try_from(generation).map_err(|_| MatrixDurableError::Corrupt)?
                != observation.session_generation
            || digest != observation.observation_digest
        {
            return Err(MatrixDurableError::Conflict);
        }
    }

    let mut candidates = Vec::new();
    if let Some(transaction_id) = &observation.transaction_id {
        let rows = sqlx::query(
            "SELECT operation_id FROM matrix_dispatch_ledger
             WHERE stable_txn_id = ? OR accepted_event_id = ?",
        )
        .bind(transaction_id.as_str())
        .bind(observation.event_id.as_str())
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        for row in rows {
            let operation_id: String = row.try_get("operation_id").map_err(unavailable)?;
            if !candidates.contains(&operation_id) {
                candidates.push(operation_id);
            }
        }
    } else if let Some(operation_id) = sqlx::query_scalar::<_, String>(
        "SELECT operation_id FROM matrix_dispatch_ledger WHERE accepted_event_id = ?",
    )
    .bind(observation.event_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    {
        candidates.push(operation_id);
    }
    if candidates.len() > 1 {
        return Err(MatrixDurableError::Conflict);
    }
    if let Some(operation_id) = candidates.first() {
        let row = sqlx::query(
            "SELECT room_id, session_generation FROM matrix_dispatch_ledger
             WHERE operation_id = ?",
        )
        .bind(operation_id)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let room_id: String = row.try_get("room_id").map_err(unavailable)?;
        let generation: i64 = row.try_get("session_generation").map_err(unavailable)?;
        if room_id != observation.room_id.as_str()
            || u64::try_from(generation).map_err(|_| MatrixDurableError::Corrupt)?
                != observation.session_generation
        {
            return Err(MatrixDurableError::Conflict);
        }
        settle_succeeded_fields_durable_tx(
            transaction,
            operation_id,
            observation.event_id.as_str(),
            &observation.observation_digest,
            observation.observed_at_ms,
        )
        .await?;
    }
    Ok(())
}

pub(crate) async fn apply_send_redaction_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    server_event_id: &str,
    redaction_digest: &str,
    observed_at_ms: u64,
) -> Result<bool, MatrixDurableError> {
    if !valid_identity(server_event_id)
        || !valid_digest(redaction_digest)
        || observed_at_ms > i64::MAX as u64
    {
        return Err(MatrixDurableError::Invalid);
    }
    let row = sqlx::query(
        "SELECT operation_id, state, redaction_observation_digest
         FROM matrix_dispatch_ledger WHERE server_event_id = ?",
    )
    .bind(server_event_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let Some(row) = row else {
        return Ok(false);
    };
    let operation_id: String = row.try_get("operation_id").map_err(unavailable)?;
    let state: String = row.try_get("state").map_err(unavailable)?;
    let existing: Option<String> = row
        .try_get("redaction_observation_digest")
        .map_err(unavailable)?;
    if state == "redacted" {
        if existing.as_deref() == Some(redaction_digest) {
            return Ok(true);
        }
        return Err(MatrixDurableError::Conflict);
    }
    if state != "succeeded" {
        return Err(MatrixDurableError::Conflict);
    }
    append_observation_durable_tx(
        transaction,
        &operation_id,
        "redaction",
        redaction_digest,
        Some(server_event_id),
        observed_at_ms,
    )
    .await?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'redacted', redaction_observation_digest = ?,
             updated_at_ms = MAX(updated_at_ms, ?), terminal_at_ms = MAX(terminal_at_ms, ?)
         WHERE operation_id = ?",
    )
    .bind(redaction_digest)
    .bind(i64::try_from(observed_at_ms).map_err(|_| MatrixDurableError::Invalid)?)
    .bind(i64::try_from(observed_at_ms).map_err(|_| MatrixDurableError::Invalid)?)
    .bind(&operation_id)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(true)
}

async fn settle_succeeded_fields_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    event_id: &str,
    digest: &str,
    observed_at_ms: u64,
) -> Result<(), MatrixDispatchError> {
    settle_succeeded_fields_durable_tx(
        transaction,
        operation_id,
        event_id,
        digest,
        observed_at_ms,
    )
    .await
    .map_err(durable_dispatch_error)
}

async fn settle_succeeded_fields_durable_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    event_id: &str,
    digest: &str,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    let row = sqlx::query(
        "SELECT stable_txn_id, room_id, state, accepted_event_id, server_event_id,
                send_observation_digest
         FROM matrix_dispatch_ledger WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or(MatrixDurableError::Conflict)?;
    let stable_txn_id: String = row.try_get("stable_txn_id").map_err(unavailable)?;
    let room_id: String = row.try_get("room_id").map_err(unavailable)?;
    let state: String = row.try_get("state").map_err(unavailable)?;
    let accepted_event_id: Option<String> = row.try_get("accepted_event_id").map_err(unavailable)?;
    let server_event_id: Option<String> = row.try_get("server_event_id").map_err(unavailable)?;
    let send_digest: Option<String> = row.try_get("send_observation_digest").map_err(unavailable)?;

    if state == "redacted" {
        if server_event_id.as_deref() == Some(event_id)
            && send_digest.as_deref() == Some(digest)
        {
            return Ok(());
        }
        return Err(MatrixDurableError::Conflict);
    }
    if state == "failed" {
        return Err(MatrixDurableError::Conflict);
    }
    if state == "succeeded" {
        if server_event_id.as_deref() == Some(event_id) && send_digest.as_deref() == Some(digest) {
            return Ok(());
        }
        return Err(MatrixDurableError::Conflict);
    }
    if accepted_event_id.as_deref().is_some_and(|accepted| accepted != event_id) {
        return Err(MatrixDurableError::Conflict);
    }
    let other: i64 = sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM matrix_dispatch_ledger
            WHERE operation_id != ? AND (accepted_event_id = ? OR server_event_id = ?)
         )",
    )
    .bind(operation_id)
    .bind(event_id)
    .bind(event_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if other != 0 {
        return Err(MatrixDurableError::Conflict);
    }
    append_observation_durable_tx(
        transaction,
        operation_id,
        "server_succeeded",
        digest,
        Some(event_id),
        observed_at_ms,
    )
    .await?;
    let at = i64::try_from(observed_at_ms).map_err(|_| MatrixDurableError::Invalid)?;
    sqlx::query(
        "UPDATE matrix_dispatch_ledger
         SET state = 'succeeded', accepted_event_id = COALESCE(accepted_event_id, ?),
             server_event_id = ?, send_observation_digest = ?,
             updated_at_ms = MAX(updated_at_ms, ?), terminal_at_ms = ?
         WHERE operation_id = ?",
    )
    .bind(event_id)
    .bind(event_id)
    .bind(digest)
    .bind(at)
    .bind(at)
    .bind(operation_id)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;

    if let Some(outbox) = sqlx::query(
        "SELECT state, sent_event_id FROM outbox_messages WHERE stable_txn_id = ?",
    )
    .bind(&stable_txn_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    {
        let outbox_state: String = outbox.try_get("state").map_err(unavailable)?;
        let prior_event: Option<String> = outbox.try_get("sent_event_id").map_err(unavailable)?;
        if outbox_state == "sent" && prior_event.as_deref() != Some(event_id) {
            return Err(MatrixDurableError::Conflict);
        }
        let changed = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'sent', lease_until_ms = NULL, sent_event_id = ?,
                 updated_at_ms = MAX(updated_at_ms, ?)
             WHERE stable_txn_id = ?",
        )
        .bind(event_id)
        .bind(at)
        .bind(&stable_txn_id)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        if outbox_state != "sent" {
            sqlx::query(
                "INSERT INTO change_log (kind, room_id, txn_id, recorded_at_ms)
                 VALUES ('outbox_sent', ?, ?, ?)",
            )
            .bind(&room_id)
            .bind(&stable_txn_id)
            .bind(at)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
        }
    }
    Ok(())
}

async fn settle_succeeded_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    observation: &MatrixServerEventObservation,
) -> Result<(), MatrixDispatchError> {
    settle_succeeded_fields_tx(
        transaction,
        operation_id,
        observation.event_id.as_str(),
        &observation.observation_digest,
        observation.observed_at_ms,
    )
    .await
}

async fn matching_server_observation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &SendIntent,
    accepted_event_id: Option<&MatrixEventId>,
) -> Result<Option<MatrixServerEventObservation>, MatrixDispatchError> {
    let row = if let Some(event_id) = accepted_event_id {
        sqlx::query(
            "SELECT event_id, stable_txn_id, room_id, session_generation,
                    observation_digest, observed_at_ms
             FROM matrix_server_event_observations
             WHERE event_id = ? OR stable_txn_id = ?
             ORDER BY CASE WHEN event_id = ? THEN 0 ELSE 1 END
             LIMIT 1",
        )
        .bind(event_id.as_str())
        .bind(&intent.transaction_id)
        .bind(event_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(store_error)?
    } else {
        sqlx::query(
            "SELECT event_id, stable_txn_id, room_id, session_generation,
                    observation_digest, observed_at_ms
             FROM matrix_server_event_observations
             WHERE stable_txn_id = ? LIMIT 1",
        )
        .bind(&intent.transaction_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(store_error)?
    };
    row.map(server_observation_from_row).transpose()
}

async fn accepted_event_owner_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &str,
) -> Result<Option<String>, MatrixDispatchError> {
    sqlx::query_scalar(
        "SELECT operation_id FROM matrix_dispatch_ledger
         WHERE accepted_event_id = ? OR server_event_id = ? LIMIT 1",
    )
    .bind(event_id)
    .bind(event_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(store_error)
}

async fn append_observation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    kind: &str,
    digest: &str,
    event_id: Option<&str>,
    observed_at_ms: u64,
) -> Result<(), MatrixDispatchError> {
    append_observation_durable_tx(
        transaction,
        operation_id,
        kind,
        digest,
        event_id,
        observed_at_ms,
    )
    .await
    .map_err(durable_dispatch_error)
}

async fn append_observation_durable_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    kind: &str,
    digest: &str,
    event_id: Option<&str>,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "INSERT INTO matrix_dispatch_observations (
            operation_id, observation_kind, observation_digest, event_id, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(operation_id, observation_kind, observation_digest, event_id) DO NOTHING",
    )
    .bind(operation_id)
    .bind(kind)
    .bind(digest)
    .bind(event_id.unwrap_or(""))
    .bind(i64::try_from(observed_at_ms).map_err(|_| MatrixDurableError::Invalid)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn load_record_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<DispatchRecord>, MatrixDispatchError> {
    let row = sqlx::query(
        "SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id,
                session_generation, authority_identity, authority_epoch,
                payload_digest, verified_grant_id, verified_grant_payload_digest,
                verified_grant_expires_at_ms, reconciliation_deadline_ms, state,
                server_event_id, transport_observation_digest,
                send_observation_digest, redaction_observation_digest
         FROM matrix_dispatch_ledger WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(store_error)?;
    row.map(dispatch_record_from_row).transpose()
}

fn dispatch_record_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<DispatchRecord, MatrixDispatchError> {
    let state_text: String = row.try_get("state").map_err(store_error)?;
    let state = SendState::parse(&state_text).ok_or(MatrixDispatchError::Store)?;
    let operation_id: String = row.try_get("operation_id").map_err(store_error)?;
    let transaction_id: String = row.try_get("stable_txn_id").map_err(store_error)?;
    let intent = SendIntent {
        operation_id: operation_id.clone(),
        transaction_id: transaction_id.clone(),
        homeserver_id: row.try_get("homeserver_id").map_err(store_error)?,
        room_id: row.try_get("room_id").map_err(store_error)?,
        device_id: row.try_get("device_id").map_err(store_error)?,
        session_generation: from_i64(row.try_get("session_generation").map_err(store_error)?)?,
        authority_identity: row.try_get("authority_identity").map_err(store_error)?,
        authority_epoch: from_i64(row.try_get("authority_epoch").map_err(store_error)?)?,
        payload_digest: row.try_get("payload_digest").map_err(store_error)?,
        verified_grant_id: row.try_get("verified_grant_id").map_err(store_error)?,
        verified_grant_payload_digest: row
            .try_get("verified_grant_payload_digest")
            .map_err(store_error)?,
        verified_grant_expires_at_ms: row
            .try_get::<Option<i64>, _>("verified_grant_expires_at_ms")
            .map_err(store_error)?
            .map(from_i64)
            .transpose()?,
        reconciliation_deadline_ms: from_i64(
            row.try_get("reconciliation_deadline_ms").map_err(store_error)?,
        )?,
    };
    let receipt = SendReceipt {
        operation_id,
        transaction_id,
        state,
        authority_identity: intent.authority_identity.clone(),
        authority_epoch: intent.authority_epoch,
        verified_grant_id: intent.verified_grant_id.clone(),
        server_event_id: row.try_get("server_event_id").map_err(store_error)?,
        transport_observation_digest: row
            .try_get("transport_observation_digest")
            .map_err(store_error)?,
        send_observation_digest: row.try_get("send_observation_digest").map_err(store_error)?,
        redaction_observation_digest: row
            .try_get("redaction_observation_digest")
            .map_err(store_error)?,
        terminal_observed: state.is_terminal(),
        idempotent: false,
    };
    Ok(DispatchRecord { intent, receipt })
}

fn server_observation_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<MatrixServerEventObservation, MatrixDispatchError> {
    let transaction_id: Option<String> = row.try_get("stable_txn_id").map_err(store_error)?;
    let event_id: String = row.try_get("event_id").map_err(store_error)?;
    let room_id: String = row.try_get("room_id").map_err(store_error)?;
    Ok(MatrixServerEventObservation {
        event_id: MatrixEventId::parse(event_id).map_err(|_| MatrixDispatchError::Store)?,
        transaction_id: transaction_id
            .map(MatrixTransactionId::parse)
            .transpose()
            .map_err(|_| MatrixDispatchError::Store)?,
        room_id: MatrixRoomId::parse(room_id).map_err(|_| MatrixDispatchError::Store)?,
        session_generation: from_i64(
            row.try_get("session_generation").map_err(store_error)?,
        )?,
        observation_digest: row.try_get("observation_digest").map_err(store_error)?,
        observed_at_ms: from_i64(row.try_get("observed_at_ms").map_err(store_error)?)?,
    })
}

fn validate_intent_shape(value: &SendIntent) -> Result<(), MatrixDispatchError> {
    for (field, name) in [
        (&value.operation_id, "operation"),
        (&value.transaction_id, "transaction"),
        (&value.homeserver_id, "homeserver"),
        (&value.room_id, "room"),
        (&value.device_id, "device"),
        (&value.authority_identity, "authority"),
    ] {
        validate_identity(field, name)?;
    }
    validate_digest(&value.payload_digest, "payload")?;
    match (
        &value.verified_grant_id,
        &value.verified_grant_payload_digest,
        value.verified_grant_expires_at_ms,
    ) {
        (None, None, None) => {}
        (Some(grant_id), Some(grant_payload_digest), Some(expires_at_ms)) => {
            validate_identity(grant_id, "verified grant")?;
            validate_digest(grant_payload_digest, "verified grant payload")?;
            if grant_payload_digest != &value.payload_digest {
                return Err(MatrixDispatchError::PayloadMismatch);
            }
            if expires_at_ms == 0 || expires_at_ms > i64::MAX as u64 {
                return Err(MatrixDispatchError::DeadlineExpired);
            }
        }
        _ => return Err(MatrixDispatchError::ObservationMismatch),
    }
    if value.session_generation == 0 || value.authority_epoch == 0 {
        return Err(MatrixDispatchError::InvalidGeneration);
    }
    if value.reconciliation_deadline_ms == 0
        || value.reconciliation_deadline_ms > i64::MAX as u64
    {
        return Err(MatrixDispatchError::DeadlineExpired);
    }
    Ok(())
}

fn validate_intent_live(
    now_ms: u64,
    value: &SendIntent,
) -> Result<(), MatrixDispatchError> {
    if value
        .verified_grant_expires_at_ms
        .is_some_and(|expires_at_ms| expires_at_ms <= now_ms)
        || value.reconciliation_deadline_ms <= now_ms
    {
        return Err(MatrixDispatchError::DeadlineExpired);
    }
    Ok(())
}

fn validate_observation(value: &ServerObservation) -> Result<(), MatrixDispatchError> {
    for (field, name) in [
        (&value.operation_id, "operation"),
        (&value.transaction_id, "transaction"),
        (&value.homeserver_id, "homeserver"),
        (&value.room_id, "room"),
    ] {
        validate_identity(field, name)?;
    }
    validate_digest(&value.observation_digest, "observation")?;
    if value.session_generation == 0 || value.observed_at_ms > i64::MAX as u64 {
        return Err(MatrixDispatchError::InvalidGeneration);
    }
    if let Some(event) = &value.server_event_id {
        validate_identity(event, "server event")?;
    }
    Ok(())
}

fn validate_server_event_observation(
    value: &MatrixServerEventObservation,
) -> Result<(), MatrixDispatchError> {
    validate_digest(&value.observation_digest, "server observation")?;
    if value.session_generation == 0 || value.observed_at_ms > i64::MAX as u64 {
        return Err(MatrixDispatchError::InvalidGeneration);
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), MatrixDispatchError> {
    if !valid_identity(value) {
        return Err(MatrixDispatchError::InvalidIdentity(field));
    }
    Ok(())
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 1024
        && !value.chars().any(char::is_whitespace)
        && !value.chars().any(char::is_control)
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), MatrixDispatchError> {
    if !valid_digest(value) {
        return Err(MatrixDispatchError::InvalidDigest(field));
    }
    Ok(())
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn to_i64(value: u64) -> Result<i64, MatrixDispatchError> {
    i64::try_from(value).map_err(|_| MatrixDispatchError::InvalidGeneration)
}

fn from_i64(value: i64) -> Result<u64, MatrixDispatchError> {
    u64::try_from(value).map_err(|_| MatrixDispatchError::Store)
}

fn store_error(_: sqlx::Error) -> MatrixDispatchError {
    MatrixDispatchError::Store
}

fn unavailable(_: sqlx::Error) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}

fn durable_dispatch_error(error: MatrixDurableError) -> MatrixDispatchError {
    match error {
        MatrixDurableError::Conflict | MatrixDurableError::AccessDenied => {
            MatrixDispatchError::OperationConflict
        }
        MatrixDurableError::Invalid => MatrixDispatchError::ObservationMismatch,
        MatrixDurableError::Corrupt | MatrixDurableError::Unavailable => MatrixDispatchError::Store,
    }
}
