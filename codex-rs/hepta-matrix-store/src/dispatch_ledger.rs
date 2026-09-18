use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::MatrixEventId;
use crate::MatrixRoomId;
use crate::MatrixTransactionId;

pub const MAX_UNRESOLVED_MATRIX_DISPATCHES: usize = 4_096;
const MAX_IDENTITY_BYTES: usize = 255;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchContext {
    pub homeserver_id: Option<String>,
    pub device_id: Option<String>,
    pub session_generation: u64,
    pub binding_revision: u64,
    pub authority_epoch: Option<u64>,
    pub authority_binding_digest: Option<String>,
    pub grant_id: Option<String>,
    pub grant_payload_digest: Option<String>,
}

impl MatrixDispatchContext {
    pub fn local_unverified(binding_revision: u64, session_generation: u64) -> Self {
        Self {
            homeserver_id: None,
            device_id: None,
            session_generation,
            binding_revision,
            authority_epoch: None,
            authority_binding_digest: None,
            grant_id: None,
            grant_payload_digest: None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchIntent {
    pub operation_id: String,
    pub stable_txn_id: MatrixTransactionId,
    pub room_id: MatrixRoomId,
    pub payload_digest: String,
    pub context: MatrixDispatchContext,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixDispatchState {
    Prepared,
    Dispatched,
    Indeterminate,
    ObservedSucceeded,
    Rejected,
    Redacted,
}

impl MatrixDispatchState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatched => "dispatched",
            Self::Indeterminate => "indeterminate",
            Self::ObservedSucceeded => "observed_succeeded",
            Self::Rejected => "rejected",
            Self::Redacted => "redacted",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "prepared" => Some(Self::Prepared),
            "dispatched" => Some(Self::Dispatched),
            "indeterminate" => Some(Self::Indeterminate),
            "observed_succeeded" => Some(Self::ObservedSucceeded),
            "rejected" => Some(Self::Rejected),
            "redacted" => Some(Self::Redacted),
            _ => None,
        }
    }

    pub fn terminal(self) -> bool {
        matches!(
            self,
            Self::ObservedSucceeded | Self::Rejected | Self::Redacted
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchReceipt {
    pub operation_id: String,
    pub stable_txn_id: MatrixTransactionId,
    pub state: MatrixDispatchState,
    pub accepted_event_id: Option<MatrixEventId>,
    pub observed_event_id: Option<MatrixEventId>,
    pub send_observation_digest: Option<String>,
    pub redaction_observation_digest: Option<String>,
    pub last_attempt: u64,
    pub archived: bool,
    pub idempotent: bool,
}

#[derive(Clone, Debug)]
struct StoredDispatch {
    receipt: MatrixDispatchReceipt,
    homeserver_id: Option<String>,
    room_id: MatrixRoomId,
    device_id: Option<String>,
    session_generation: u64,
    binding_revision: u64,
    authority_epoch: Option<u64>,
    authority_binding_digest: Option<String>,
    grant_id: Option<String>,
    payload_digest: String,
    grant_payload_digest: Option<String>,
}

impl StoredDispatch {
    fn matches_intent(&self, intent: &MatrixDispatchIntent) -> bool {
        self.receipt.operation_id == intent.operation_id
            && self.receipt.stable_txn_id == intent.stable_txn_id
            && self.room_id == intent.room_id
            && self.payload_digest == intent.payload_digest
            && self.homeserver_id == intent.context.homeserver_id
            && self.device_id == intent.context.device_id
            && self.session_generation == intent.context.session_generation
            && self.binding_revision == intent.context.binding_revision
            && self.authority_epoch == intent.context.authority_epoch
            && self.authority_binding_digest == intent.context.authority_binding_digest
            && self.grant_id == intent.context.grant_id
            && self.grant_payload_digest == intent.context.grant_payload_digest
    }
}

pub fn matrix_dispatch_operation_id(txn_id: &MatrixTransactionId) -> String {
    format!("matrix-send:{}", txn_id.as_str())
}

impl MatrixDurableStore {
    pub async fn prepare_matrix_dispatch(
        &self,
        now_ms: u64,
        intent: &MatrixDispatchIntent,
    ) -> Result<MatrixDispatchReceipt, MatrixDurableError> {
        validate_intent(intent)?;
        let outbox = sqlx::query(
            "SELECT room_id, payload_sha256, binding_revision, generation
             FROM outbox_messages WHERE stable_txn_id = ?",
        )
        .bind(intent.stable_txn_id.as_str())
        .fetch_optional(self.sqlite_pool())
        .await
        .map_err(unavailable)?
        .ok_or(MatrixDurableError::Conflict)?;
        let room_id: String = outbox.try_get("room_id").map_err(corrupt)?;
        let payload_digest: String = outbox.try_get("payload_sha256").map_err(corrupt)?;
        let binding_revision = positive_u64(
            outbox
                .try_get::<i64, _>("binding_revision")
                .map_err(corrupt)?,
        )?;
        let generation = positive_u64(outbox.try_get::<i64, _>("generation").map_err(corrupt)?)?;
        if room_id != intent.room_id.as_str()
            || payload_digest != intent.payload_digest
            || binding_revision != intent.context.binding_revision
            || generation != intent.context.session_generation
        {
            return Err(MatrixDurableError::Conflict);
        }
        if let Some(grant_payload_digest) = &intent.context.grant_payload_digest
            && grant_payload_digest != &intent.payload_digest
        {
            return Err(MatrixDurableError::AccessDenied);
        }

        if let Some(mut current) = load_dispatch(self, &intent.stable_txn_id, false).await? {
            if !current.matches_intent(intent) {
                return Err(MatrixDurableError::Conflict);
            }
            current.receipt.idempotent = true;
            return Ok(current.receipt);
        }
        if let Some(mut current) = load_dispatch(self, &intent.stable_txn_id, true).await? {
            if !current.matches_intent(intent) {
                return Err(MatrixDurableError::Conflict);
            }
            current.receipt.idempotent = true;
            return Ok(current.receipt);
        }

        let unresolved = self.unresolved_matrix_dispatch_count().await?;
        if unresolved >= MAX_UNRESOLVED_MATRIX_DISPATCHES {
            return Err(MatrixDurableError::Unavailable);
        }
        let now = to_i64(now_ms)?;
        sqlx::query(
            "INSERT INTO matrix_dispatch_ledger (
                operation_id, stable_txn_id, homeserver_id, room_id, device_id,
                session_generation, binding_revision, authority_epoch,
                authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256,
                state, accepted_event_id, observed_event_id, send_observation_digest,
                redaction_observation_digest, last_attempt, prepared_at_ms, updated_at_ms,
                terminal_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', NULL, NULL, NULL,
                       NULL, 0, ?, ?, NULL)",
        )
        .bind(&intent.operation_id)
        .bind(intent.stable_txn_id.as_str())
        .bind(intent.context.homeserver_id.as_deref())
        .bind(intent.room_id.as_str())
        .bind(intent.context.device_id.as_deref())
        .bind(to_i64(intent.context.session_generation)?)
        .bind(to_i64(intent.context.binding_revision)?)
        .bind(intent.context.authority_epoch.map(to_i64).transpose()?)
        .bind(intent.context.authority_binding_digest.as_deref())
        .bind(intent.context.grant_id.as_deref())
        .bind(&intent.payload_digest)
        .bind(intent.context.grant_payload_digest.as_deref())
        .bind(now)
        .bind(now)
        .execute(self.sqlite_pool())
        .await
        .map_err(|_| MatrixDurableError::Conflict)?;
        self.matrix_dispatch_receipt(&intent.stable_txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn record_matrix_dispatch_attempt(
        &self,
        txn_id: &MatrixTransactionId,
        attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchReceipt, MatrixDurableError> {
        if attempt == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let current = load_dispatch(self, txn_id, false)
            .await?
            .ok_or(MatrixDurableError::Conflict)?;
        if current.receipt.state.terminal() || attempt < current.receipt.last_attempt {
            return Err(MatrixDurableError::Conflict);
        }
        if current.receipt.state == MatrixDispatchState::Dispatched
            && attempt == current.receipt.last_attempt
        {
            let mut receipt = current.receipt;
            receipt.idempotent = true;
            return Ok(receipt);
        }
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'dispatched', last_attempt = ?, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state IN ('prepared', 'dispatched', 'indeterminate')",
        )
        .bind(to_i64(attempt)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        self.matrix_dispatch_receipt(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn record_matrix_transport_acceptance(
        &self,
        txn_id: &MatrixTransactionId,
        attempt: u64,
        event_id: &MatrixEventId,
        now_ms: u64,
    ) -> Result<MatrixDispatchReceipt, MatrixDurableError> {
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let current = load_active_dispatch_tx(&mut transaction, txn_id).await?;
        if current.receipt.last_attempt != attempt
            || !matches!(
                current.receipt.state,
                MatrixDispatchState::Dispatched | MatrixDispatchState::Indeterminate
            )
            || current
                .receipt
                .accepted_event_id
                .as_ref()
                .is_some_and(|current| current != event_id)
        {
            return Err(MatrixDurableError::Conflict);
        }
        let digest = observation_digest(&[
            "transport-accepted",
            txn_id.as_str(),
            event_id.as_str(),
            &attempt.to_string(),
        ]);
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'indeterminate', accepted_event_id = ?, updated_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(event_id.as_str())
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        append_observation(
            &mut transaction,
            &current.receipt.operation_id,
            txn_id,
            "transport_accepted",
            Some(event_id),
            &digest,
            now_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        self.matrix_dispatch_receipt(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn record_matrix_transport_indeterminate_and_retry(
        &self,
        txn_id: &MatrixTransactionId,
        attempt: u64,
        now_ms: u64,
        next_attempt_at_ms: u64,
    ) -> Result<MatrixDispatchReceipt, MatrixDurableError> {
        if next_attempt_at_ms < now_ms {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let current = load_active_dispatch_tx(&mut transaction, txn_id).await?;
        if current.receipt.last_attempt != attempt
            || !matches!(
                current.receipt.state,
                MatrixDispatchState::Dispatched | MatrixDispatchState::Indeterminate
            )
        {
            return Err(MatrixDurableError::Conflict);
        }
        let updated = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'retry_scheduled', lease_until_ms = NULL,
                 next_attempt_at_ms = ?, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(to_i64(next_attempt_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(attempt)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        let digest = observation_digest(&[
            "transport-unknown",
            txn_id.as_str(),
            &attempt.to_string(),
            &now_ms.to_string(),
        ]);
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
        append_observation(
            &mut transaction,
            &current.receipt.operation_id,
            txn_id,
            "transport_unknown",
            None,
            &digest,
            now_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        self.matrix_dispatch_receipt(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn record_matrix_transport_rejection(
        &self,
        txn_id: &MatrixTransactionId,
        attempt: u64,
        now_ms: u64,
    ) -> Result<MatrixDispatchReceipt, MatrixDurableError> {
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let current = load_active_dispatch_tx(&mut transaction, txn_id).await?;
        if current.receipt.last_attempt != attempt
            || !matches!(
                current.receipt.state,
                MatrixDispatchState::Dispatched | MatrixDispatchState::Indeterminate
            )
        {
            return Err(MatrixDurableError::Conflict);
        }
        let updated = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'permanent_failure', lease_until_ms = NULL, updated_at_ms = ?
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .bind(to_i64(attempt)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        let digest = observation_digest(&[
            "transport-rejected",
            txn_id.as_str(),
            &attempt.to_string(),
            &now_ms.to_string(),
        ]);
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'rejected', updated_at_ms = ?, terminal_at_ms = ?
             WHERE stable_txn_id = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        append_observation(
            &mut transaction,
            &current.receipt.operation_id,
            txn_id,
            "transport_rejected",
            None,
            &digest,
            now_ms,
        )
        .await?;
        archive_active_dispatch(&mut transaction, txn_id, now_ms).await?;
        transaction.commit().await.map_err(unavailable)?;
        self.matrix_dispatch_receipt(txn_id)
            .await?
            .ok_or(MatrixDurableError::Corrupt)
    }

    pub async fn observe_matrix_server_event(
        &self,
        txn_hint: Option<&MatrixTransactionId>,
        event_id: &MatrixEventId,
        room_id: &MatrixRoomId,
        binding_revision: u64,
        generation: u64,
        observation_digest: &str,
        observed_at_ms: u64,
    ) -> Result<Option<MatrixDispatchReceipt>, MatrixDurableError> {
        validate_digest(observation_digest)?;
        if binding_revision == 0 || generation == 0 {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        let current = match txn_hint {
            Some(txn_id) => load_active_dispatch_tx_optional(&mut transaction, txn_id).await?,
            None => load_active_dispatch_by_event_tx(&mut transaction, event_id).await?,
        };
        let Some(current) = current else {
            let archived = match txn_hint {
                Some(txn_id) => load_dispatch(self, txn_id, true).await?,
                None => load_archive_by_event(self, event_id).await?,
            };
            if let Some(mut archived) = archived {
                if archived.receipt.state == MatrixDispatchState::ObservedSucceeded
                    && archived.receipt.observed_event_id.as_ref() == Some(event_id)
                    && archived.receipt.send_observation_digest.as_deref()
                        == Some(observation_digest)
                {
                    archived.receipt.idempotent = true;
                    return Ok(Some(archived.receipt));
                }
                return Err(MatrixDurableError::Conflict);
            }
            return Ok(None);
        };
        if current.room_id != *room_id
            || current.binding_revision != binding_revision
            || current.session_generation != generation
            || current
                .receipt
                .accepted_event_id
                .as_ref()
                .is_some_and(|accepted| accepted != event_id)
        {
            return Err(MatrixDurableError::Conflict);
        }
        let txn_id = current.receipt.stable_txn_id.clone();
        let outbox =
            sqlx::query("SELECT state, sent_event_id FROM outbox_messages WHERE stable_txn_id = ?")
                .bind(txn_id.as_str())
                .fetch_optional(&mut *transaction)
                .await
                .map_err(unavailable)?
                .ok_or(MatrixDurableError::Corrupt)?;
        let outbox_state: String = outbox.try_get("state").map_err(corrupt)?;
        let sent_event_id: Option<String> = outbox.try_get("sent_event_id").map_err(corrupt)?;
        if outbox_state == "permanent_failure"
            || sent_event_id
                .as_deref()
                .is_some_and(|existing| existing != event_id.as_str())
        {
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "UPDATE outbox_messages
             SET state = 'sent', lease_until_ms = NULL, sent_event_id = ?,
                 updated_at_ms = MAX(updated_at_ms, ?)
             WHERE stable_txn_id = ?",
        )
        .bind(event_id.as_str())
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "UPDATE matrix_dispatch_ledger
             SET state = 'observed_succeeded', observed_event_id = ?,
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
        .map_err(unavailable)?;
        append_observation(
            &mut transaction,
            &current.receipt.operation_id,
            &txn_id,
            "server_succeeded",
            Some(event_id),
            observation_digest,
            observed_at_ms,
        )
        .await?;
        archive_active_dispatch(&mut transaction, &txn_id, observed_at_ms).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(self.matrix_dispatch_receipt(&txn_id).await?)
    }

    pub async fn observe_matrix_redaction(
        &self,
        target_event_id: &MatrixEventId,
        redaction_event_id: &MatrixEventId,
        redaction_digest: &str,
        observed_at_ms: u64,
    ) -> Result<Option<MatrixDispatchReceipt>, MatrixDurableError> {
        validate_digest(redaction_digest)?;
        let row = sqlx::query(
            "SELECT stable_txn_id, operation_id, state, redaction_observation_digest
             FROM matrix_dispatch_archive WHERE observed_event_id = ?",
        )
        .bind(target_event_id.as_str())
        .fetch_optional(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let txn_id = MatrixTransactionId::parse(
            &row.try_get::<String, _>("stable_txn_id").map_err(corrupt)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?;
        let operation_id: String = row.try_get("operation_id").map_err(corrupt)?;
        let state: String = row.try_get("state").map_err(corrupt)?;
        let current_redaction: Option<String> = row
            .try_get("redaction_observation_digest")
            .map_err(corrupt)?;
        if state == MatrixDispatchState::Redacted.as_str() {
            if current_redaction.as_deref() == Some(redaction_digest) {
                let mut receipt = self
                    .matrix_dispatch_receipt(&txn_id)
                    .await?
                    .ok_or(MatrixDurableError::Corrupt)?;
                receipt.idempotent = true;
                return Ok(Some(receipt));
            }
            return Err(MatrixDurableError::Conflict);
        }
        if state != MatrixDispatchState::ObservedSucceeded.as_str() {
            return Err(MatrixDurableError::Conflict);
        }
        let mut transaction = self.sqlite_pool().begin().await.map_err(unavailable)?;
        sqlx::query(
            "UPDATE matrix_dispatch_archive
             SET state = 'redacted', redaction_observation_digest = ?,
                 updated_at_ms = MAX(updated_at_ms, ?),
                 terminal_at_ms = MAX(terminal_at_ms, ?),
                 archived_at_ms = MAX(archived_at_ms, ?)
             WHERE stable_txn_id = ? AND observed_event_id = ?",
        )
        .bind(redaction_digest)
        .bind(to_i64(observed_at_ms)?)
        .bind(to_i64(observed_at_ms)?)
        .bind(to_i64(observed_at_ms)?)
        .bind(txn_id.as_str())
        .bind(target_event_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        append_observation(
            &mut transaction,
            &operation_id,
            &txn_id,
            "redaction",
            Some(redaction_event_id),
            redaction_digest,
            observed_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(self.matrix_dispatch_receipt(&txn_id).await?)
    }

    pub async fn matrix_dispatch_receipt(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Option<MatrixDispatchReceipt>, MatrixDurableError> {
        if let Some(current) = load_dispatch(self, txn_id, false).await? {
            return Ok(Some(current.receipt));
        }
        Ok(load_dispatch(self, txn_id, true)
            .await?
            .map(|stored| stored.receipt))
    }

    pub async fn matrix_dispatch_receipt_for_event(
        &self,
        event_id: &MatrixEventId,
    ) -> Result<Option<MatrixDispatchReceipt>, MatrixDurableError> {
        let row = sqlx::query(DISPATCH_SELECT_ACTIVE_BY_EVENT)
            .bind(event_id.as_str())
            .fetch_optional(self.sqlite_pool())
            .await
            .map_err(unavailable)?;
        if let Some(row) = row {
            return Ok(Some(stored_from_row(&row, false)?.receipt));
        }
        Ok(load_archive_by_event(self, event_id)
            .await?
            .map(|stored| stored.receipt))
    }

    pub async fn unresolved_matrix_dispatch_count(&self) -> Result<usize, MatrixDurableError> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE state IN ('prepared', 'dispatched', 'indeterminate')",
        )
        .fetch_one(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        usize::try_from(count).map_err(|_| MatrixDurableError::Corrupt)
    }
}

async fn append_observation(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    txn_id: &MatrixTransactionId,
    kind: &str,
    event_id: Option<&MatrixEventId>,
    digest: &str,
    observed_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    sqlx::query(
        "INSERT OR IGNORE INTO matrix_dispatch_observations (
            operation_id, stable_txn_id, kind, event_id, digest, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(operation_id)
    .bind(txn_id.as_str())
    .bind(kind)
    .bind(event_id.map(MatrixEventId::as_str))
    .bind(digest)
    .bind(to_i64(observed_at_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn archive_active_dispatch(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
    archived_at_ms: u64,
) -> Result<(), MatrixDurableError> {
    let inserted = sqlx::query(
        "INSERT INTO matrix_dispatch_archive (
            operation_id, stable_txn_id, homeserver_id, room_id, device_id,
            session_generation, binding_revision, authority_epoch,
            authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256,
            state, accepted_event_id, observed_event_id, send_observation_digest,
            redaction_observation_digest, last_attempt, prepared_at_ms, updated_at_ms,
            terminal_at_ms, archived_at_ms
         )
         SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id,
                session_generation, binding_revision, authority_epoch,
                authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256,
                state, accepted_event_id, observed_event_id, send_observation_digest,
                redaction_observation_digest, last_attempt, prepared_at_ms, updated_at_ms,
                terminal_at_ms, ?
         FROM matrix_dispatch_ledger
         WHERE stable_txn_id = ? AND state IN ('observed_succeeded', 'rejected', 'redacted')",
    )
    .bind(to_i64(archived_at_ms)?)
    .bind(txn_id.as_str())
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if inserted.rows_affected() != 1 {
        return Err(MatrixDurableError::Conflict);
    }
    let deleted = sqlx::query("DELETE FROM matrix_dispatch_ledger WHERE stable_txn_id = ?")
        .bind(txn_id.as_str())
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
    if deleted.rows_affected() != 1 {
        return Err(MatrixDurableError::Corrupt);
    }
    Ok(())
}

async fn load_active_dispatch_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<StoredDispatch, MatrixDurableError> {
    load_active_dispatch_tx_optional(transaction, txn_id)
        .await?
        .ok_or(MatrixDurableError::Conflict)
}

async fn load_active_dispatch_tx_optional(
    transaction: &mut Transaction<'_, Sqlite>,
    txn_id: &MatrixTransactionId,
) -> Result<Option<StoredDispatch>, MatrixDurableError> {
    let row = sqlx::query(DISPATCH_SELECT_ACTIVE_BY_TXN)
        .bind(txn_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?;
    row.map(|row| stored_from_row(&row, false)).transpose()
}

async fn load_active_dispatch_by_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    event_id: &MatrixEventId,
) -> Result<Option<StoredDispatch>, MatrixDurableError> {
    let row = sqlx::query(DISPATCH_SELECT_ACTIVE_BY_EVENT)
        .bind(event_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?;
    row.map(|row| stored_from_row(&row, false)).transpose()
}

async fn load_dispatch(
    store: &MatrixDurableStore,
    txn_id: &MatrixTransactionId,
    archived: bool,
) -> Result<Option<StoredDispatch>, MatrixDurableError> {
    let sql = if archived {
        DISPATCH_SELECT_ARCHIVE_BY_TXN
    } else {
        DISPATCH_SELECT_ACTIVE_BY_TXN
    };
    let row = sqlx::query(sql)
        .bind(txn_id.as_str())
        .fetch_optional(store.sqlite_pool())
        .await
        .map_err(unavailable)?;
    row.map(|row| stored_from_row(&row, archived)).transpose()
}

async fn load_archive_by_event(
    store: &MatrixDurableStore,
    event_id: &MatrixEventId,
) -> Result<Option<StoredDispatch>, MatrixDurableError> {
    let row = sqlx::query(DISPATCH_SELECT_ARCHIVE_BY_EVENT)
        .bind(event_id.as_str())
        .fetch_optional(store.sqlite_pool())
        .await
        .map_err(unavailable)?;
    row.map(|row| stored_from_row(&row, true)).transpose()
}

fn stored_from_row(
    row: &sqlx::sqlite::SqliteRow,
    archived: bool,
) -> Result<StoredDispatch, MatrixDurableError> {
    let stable_txn_id =
        MatrixTransactionId::parse(&row.try_get::<String, _>("stable_txn_id").map_err(corrupt)?)
            .map_err(|_| MatrixDurableError::Corrupt)?;
    let room_id = MatrixRoomId::parse(&row.try_get::<String, _>("room_id").map_err(corrupt)?)
        .map_err(|_| MatrixDurableError::Corrupt)?;
    let state = MatrixDispatchState::parse(&row.try_get::<String, _>("state").map_err(corrupt)?)
        .ok_or(MatrixDurableError::Corrupt)?;
    let accepted_event_id =
        parse_optional_event(row.try_get("accepted_event_id").map_err(corrupt)?)?;
    let observed_event_id =
        parse_optional_event(row.try_get("observed_event_id").map_err(corrupt)?)?;
    Ok(StoredDispatch {
        receipt: MatrixDispatchReceipt {
            operation_id: row.try_get("operation_id").map_err(corrupt)?,
            stable_txn_id,
            state,
            accepted_event_id,
            observed_event_id,
            send_observation_digest: row.try_get("send_observation_digest").map_err(corrupt)?,
            redaction_observation_digest: row
                .try_get("redaction_observation_digest")
                .map_err(corrupt)?,
            last_attempt: nonnegative_u64(row.try_get::<i64, _>("last_attempt").map_err(corrupt)?)?,
            archived,
            idempotent: false,
        },
        homeserver_id: row.try_get("homeserver_id").map_err(corrupt)?,
        room_id,
        device_id: row.try_get("device_id").map_err(corrupt)?,
        session_generation: positive_u64(
            row.try_get::<i64, _>("session_generation")
                .map_err(corrupt)?,
        )?,
        binding_revision: positive_u64(
            row.try_get::<i64, _>("binding_revision").map_err(corrupt)?,
        )?,
        authority_epoch: row
            .try_get::<Option<i64>, _>("authority_epoch")
            .map_err(corrupt)?
            .map(positive_u64)
            .transpose()?,
        authority_binding_digest: row.try_get("authority_binding_digest").map_err(corrupt)?,
        grant_id: row.try_get("grant_id").map_err(corrupt)?,
        payload_digest: row.try_get("payload_sha256").map_err(corrupt)?,
        grant_payload_digest: row.try_get("grant_payload_sha256").map_err(corrupt)?,
    })
}

fn parse_optional_event(
    value: Option<String>,
) -> Result<Option<MatrixEventId>, MatrixDurableError> {
    value
        .map(|value| MatrixEventId::parse(&value).map_err(|_| MatrixDurableError::Corrupt))
        .transpose()
}

fn validate_intent(intent: &MatrixDispatchIntent) -> Result<(), MatrixDurableError> {
    validate_identity(&intent.operation_id)?;
    validate_digest(&intent.payload_digest)?;
    if intent.context.session_generation == 0 || intent.context.binding_revision == 0 {
        return Err(MatrixDurableError::Invalid);
    }
    if let Some(value) = &intent.context.homeserver_id {
        validate_identity(value)?;
    }
    if let Some(value) = &intent.context.device_id {
        validate_identity(value)?;
    }
    if intent.context.authority_epoch == Some(0) {
        return Err(MatrixDurableError::Invalid);
    }
    if let Some(value) = &intent.context.authority_binding_digest {
        validate_digest(value)?;
    }
    match (
        intent.context.grant_id.as_deref(),
        intent.context.grant_payload_digest.as_deref(),
    ) {
        (None, None) => {}
        (Some(grant_id), Some(digest)) => {
            validate_identity(grant_id)?;
            validate_digest(digest)?;
        }
        _ => return Err(MatrixDurableError::Invalid),
    }
    Ok(())
}

fn validate_identity(value: &str) -> Result<(), MatrixDurableError> {
    if value.is_empty()
        || value.len() > MAX_IDENTITY_BYTES
        || value.chars().any(char::is_control)
        || value.chars().any(char::is_whitespace)
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

fn observation_digest(parts: &[&str]) -> String {
    let mut bytes = Vec::new();
    for part in parts {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part.as_bytes());
    }
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
}

fn to_i64(value: u64) -> Result<i64, MatrixDurableError> {
    i64::try_from(value).map_err(|_| MatrixDurableError::Invalid)
}

fn positive_u64(value: i64) -> Result<u64, MatrixDurableError> {
    if value <= 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn nonnegative_u64(value: i64) -> Result<u64, MatrixDurableError> {
    if value < 0 {
        return Err(MatrixDurableError::Corrupt);
    }
    u64::try_from(value).map_err(|_| MatrixDurableError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> MatrixDurableError {
    MatrixDurableError::Unavailable
}

fn corrupt(_: sqlx::Error) -> MatrixDurableError {
    MatrixDurableError::Corrupt
}

const DISPATCH_COLUMNS: &str = "operation_id, stable_txn_id, homeserver_id, room_id, device_id, session_generation, binding_revision, authority_epoch, authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256, state, accepted_event_id, observed_event_id, send_observation_digest, redaction_observation_digest, last_attempt";
const DISPATCH_SELECT_ACTIVE_BY_TXN: &str = "SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id, session_generation, binding_revision, authority_epoch, authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256, state, accepted_event_id, observed_event_id, send_observation_digest, redaction_observation_digest, last_attempt FROM matrix_dispatch_ledger WHERE stable_txn_id = ?";
const DISPATCH_SELECT_ACTIVE_BY_EVENT: &str = "SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id, session_generation, binding_revision, authority_epoch, authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256, state, accepted_event_id, observed_event_id, send_observation_digest, redaction_observation_digest, last_attempt FROM matrix_dispatch_ledger WHERE accepted_event_id = ?";
const DISPATCH_SELECT_ARCHIVE_BY_TXN: &str = "SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id, session_generation, binding_revision, authority_epoch, authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256, state, accepted_event_id, observed_event_id, send_observation_digest, redaction_observation_digest, last_attempt FROM matrix_dispatch_archive WHERE stable_txn_id = ?";
const DISPATCH_SELECT_ARCHIVE_BY_EVENT: &str = "SELECT operation_id, stable_txn_id, homeserver_id, room_id, device_id, session_generation, binding_revision, authority_epoch, authority_binding_digest, grant_id, payload_sha256, grant_payload_sha256, state, accepted_event_id, observed_event_id, send_observation_digest, redaction_observation_digest, last_attempt FROM matrix_dispatch_archive WHERE observed_event_id = ?";

#[allow(dead_code)]
const _: &str = DISPATCH_COLUMNS;
